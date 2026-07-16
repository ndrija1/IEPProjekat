import json
import re
import uuid
from functools import wraps

import redis
from bson import ObjectId
from dateutil import parser as date_parser
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


def find_missing_field(body, field_names):
    for name in field_names:
        value = body.get(name)
        if value is None or (isinstance(value, str) and len(value) == 0):
            return name
    return None


def is_valid_price(value):
    # bool is a subclass of int in Python, so exclude it explicitly
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def format_date(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def serialize_asset(document):
    asset = {
        "id": str(document["_id"]),
        "name": document["name"],
        "categories": document["categories"],
        "buying_date": format_date(document["buying_date"]),
        "buying_price": document["buying_price"],
        "info": document.get("info", {}),
    }
    if "selling_date" in document:
        asset["selling_date"]  = format_date(document["selling_date"])
        asset["selling_price"] = document["selling_price"]
    return asset


def build_search_query(body):
    query = {}

    name = body.get("name")
    if name:
        query["name"] = {"$regex": re.escape(name)}

    category = body.get("category")
    if category:
        query["categories"] = category

    buying_date = body.get("buying_date")
    if buying_date:
        query["buying_date"] = {"$gt": date_parser.parse(buying_date)}

    selling_date = body.get("selling_date")
    if selling_date:
        # unsold assets have no selling_date, so they naturally fall out here
        query["selling_date"] = {"$lt": date_parser.parse(selling_date)}

    for info_filter in body.get("info_filters", []):
        operator = info_filter["operator"]
        if not operator.startswith("$"):
            operator = "$" + operator
        query["info." + info_filter["field"]] = {operator: info_filter["value"]}

    return query


@application.route("/search", methods=["POST"])
@roles_required("employee")
def search():
    body  = request.get_json(silent=True) or {}
    query = build_search_query(body)

    found = [serialize_asset(document) for document in assets.find(query)]

    return jsonify(assets=found), 200


def store_order(order):
    orders_store.set(configuration.ORDER_KEY_PREFIX + str(uuid.uuid4()), json.dumps(order))


@application.route("/create_buy_order", methods=["POST"])
@roles_required("employee")
def create_buy_order():
    body = request.get_json(silent=True) or {}

    missing = find_missing_field(body, ["name", "categories", "buying_price", "info"])
    if missing is not None:
        return error(f"Field {missing} is missing.")

    if len(body["categories"]) == 0:
        return error("Categories list is empty.")

    if not is_valid_price(body["buying_price"]):
        return error("Invalid buying price.")

    store_order({
        "order_type": "BUY",
        "name": body["name"],
        "categories": body["categories"],
        "buying_price": body["buying_price"],
        "info": body["info"],
    })

    return "", 200


@application.route("/create_sell_order", methods=["POST"])
@roles_required("employee")
def create_sell_order():
    body = request.get_json(silent=True) or {}

    missing = find_missing_field(body, ["id", "selling_price"])
    if missing is not None:
        return error(f"Field {missing} is missing.")

    asset_id = body["id"]
    if not ObjectId.is_valid(asset_id) or assets.find_one({"_id": ObjectId(asset_id)}) is None:
        return error("Invalid id.")

    if not is_valid_price(body["selling_price"]):
        return error("Invalid selling price.")

    store_order({
        "order_type": "SELL",
        "id": asset_id,
        "selling_price": body["selling_price"],
    })

    return "", 200


if __name__ == "__main__":
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
