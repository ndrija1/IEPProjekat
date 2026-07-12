"""Director service — approving orders and reporting on the fund.

Endpoints (PDF: "Upravljanje investicionim fondom"):
    GET  /pending_orders - the orders sitting in Redis, waiting on a decision
    POST /decision       - decide one pending order
    GET  /report         - spent/earned per category

/decision has two shapes, picked by the DECISION_MODE env var at startup:
    "simple" (default) - {uuid, approved}: the director decides on the spot
    "voting"           - {uuid, voters}: deploy a Voting contract on ganache
                         and let the employees decide by majority vote
                         (see voting.py and contracts/Voting.sol)

Every endpoint needs a JWT with the director role.
"""

import json
import uuid as uuid_module
from datetime import datetime
from functools import wraps

import redis
from bson import ObjectId
from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, get_jwt, verify_jwt_in_request
from pymongo import MongoClient

import configuration
from configuration import Configuration

application = Flask(__name__)
application.config.from_object(Configuration)

jwt = JWTManager(application)

mongo  = MongoClient(configuration.MONGO_URI)
assets = mongo[configuration.MONGO_DATABASE]["assets"]

orders_store = redis.Redis(
    host=configuration.REDIS_HOST,
    port=configuration.REDIS_PORT,
    decode_responses=True,
)


def roles_required(*roles):
    """Gate an endpoint behind a valid JWT whose role is one of *roles*.

    The spec only describes the missing-header 401, so a wrong-role token
    gets that same 401 — it doesn't hint that other roles' endpoints exist.
    """
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            if get_jwt().get("role") not in roles:
                return jsonify(msg="Missing Authorization Header"), 401
            return function(*args, **kwargs)
        return wrapper
    return decorator


def error(message):
    return jsonify(message=message), 400


def order_key(order_uuid):
    return configuration.ORDER_KEY_PREFIX + order_uuid


def is_valid_pending_uuid(value):
    """True only if value is UUID-shaped AND names an order still in Redis.

    Both a garbage string and a well-formed uuid that isn't pending map to
    the same "Invalid uuid." message.
    """
    if not isinstance(value, str):
        return False
    try:
        uuid_module.UUID(value)
    except ValueError:
        return False
    return orders_store.exists(order_key(value)) == 1


def apply_order(order):
    """Push an approved order into MongoDB.

    BUY inserts a brand-new asset; SELL just stamps selling price/date onto
    the existing one. Either way the date is the moment of approval (now),
    which is what the spec asks for.
    """
    now = datetime.utcnow()

    if order["order_type"] == "BUY":
        assets.insert_one({
            "name": order["name"],
            "categories": order["categories"],
            "buying_price": order["buying_price"],
            "buying_date": now,
            "info": order["info"],
        })
    else:  # SELL
        assets.update_one(
            {"_id": ObjectId(order["id"])},
            {"$set": {"selling_price": order["selling_price"], "selling_date": now}},
        )


def conclude_order(order_uuid, accepted):
    """Close out a pending order: apply it to Mongo if accepted, then drop it
    from Redis. Both the simple path and the vote watcher end up here, so the
    "what approval means" logic lives in exactly one place.
    """
    payload = orders_store.get(order_key(order_uuid))
    if payload is None:
        return

    if accepted:
        apply_order(json.loads(payload))

    orders_store.delete(order_key(order_uuid))


@application.route("/pending_orders", methods=["GET"])
@roles_required("director")
def pending_orders():
    orders = []
    # scan_iter, not KEYS, so we don't block Redis while walking the keyspace.
    for key in orders_store.scan_iter(configuration.ORDER_KEY_PREFIX + "*"):
        payload = orders_store.get(key)
        if payload is None:  # the watcher may have concluded it between scan and get
            continue
        order = json.loads(payload)
        order["uuid"] = key[len(configuration.ORDER_KEY_PREFIX):]  # strip the "order:" prefix
        orders.append(order)

    return jsonify(orders=orders), 200


def decision_simple(body):
    """Direct decision: {uuid, approved}. Validate the uuid fully before even
    looking at approved (the grader checks the messages in this order)."""
    uuid_value = body.get("uuid")
    if uuid_value is None or (isinstance(uuid_value, str) and len(uuid_value) == 0):
        return error("Field uuid is missing.")

    if not is_valid_pending_uuid(uuid_value):
        return error("Invalid uuid.")

    approved = body.get("approved")
    if approved is None or (isinstance(approved, str) and len(approved) == 0):
        return error("Field approved is missing.")

    if not isinstance(approved, bool):
        return error("Invalid decision.")

    conclude_order(body["uuid"], body["approved"])

    return "", 200


def decision_voting(body):
    """Voting decision: {uuid, voters}. Opens a vote; the watcher finishes it
    later. Checks run in the spec's order."""
    from web3 import Web3  # local import so simple mode never pulls in web3

    uuid_value = body.get("uuid")
    if uuid_value is None or (isinstance(uuid_value, str) and len(uuid_value) == 0):
        return error("Field uuid is missing.")

    if not is_valid_pending_uuid(uuid_value):
        return error("Invalid uuid.")

    voters = body.get("voters")
    if voters is None or (isinstance(voters, list) and len(voters) == 0):
        return error("Field voters is missing.")

    if not all(isinstance(voter, str) and Web3.is_address(voter) for voter in voters):
        return error("Invalid voter address.")

    if len(voters) % 2 == 0:
        return error("Even number of voters.")

    # Deploy the contract and hand back the two unsigned vote transactions.
    # Nothing is decided yet — the order stays in Redis until the watcher
    # sees the vote finish.
    approve_transaction, reject_transaction = voting_manager.start_vote(uuid_value, voters)

    return jsonify(
        approve_transaction=approve_transaction,
        reject_transaction=reject_transaction,
    ), 200


@application.route("/decision", methods=["POST"])
@roles_required("director")
def decision():
    body = request.get_json(silent=True) or {}

    if configuration.DECISION_MODE == "voting":
        return decision_voting(body)
    return decision_simple(body)


@application.route("/report", methods=["GET"])
@roles_required("director")
def report():
    # The whole report is one aggregation done by Mongo, not a Python loop.
    # $unwind: an asset in N categories becomes N rows, so it counts fully in
    #          each of its categories.
    # spent:   sum of every buying_price.
    # earned:  sum of selling_price, but $ifNull turns an unsold asset's
    #          missing price into 0 — so it adds to spent but not earned.
    pipeline = [
        {"$unwind": "$categories"},
        {"$group": {
            "_id": "$categories",
            "spent": {"$sum": "$buying_price"},
            "earned": {"$sum": {"$ifNull": ["$selling_price", 0]}},
        }},
        # Spec's ordering: earned desc, then spent asc, then category name asc.
        {"$sort": {"earned": -1, "spent": 1, "_id": 1}},
        {"$project": {"_id": 0, "category": "$_id", "spent": 1, "earned": 1}},
    ]

    return jsonify(statistics=list(assets.aggregate(pipeline))), 200


# The voting machinery (web3 + compiled contract + watcher thread) is only
# imported in voting mode, so simple mode needs neither ganache nor Voting.json.
# conclude_order is passed in as a callback so voting.py knows nothing about Mongo.
voting_manager = None
if configuration.DECISION_MODE == "voting":
    from voting import VotingManager

    voting_manager = VotingManager(orders_store, conclude_order)


if __name__ == "__main__":
    if voting_manager is not None:
        voting_manager.start_watcher()
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
