import re

from dateutil import parser as date_parser
from flask import Flask, request, jsonify
from pymongo import MongoClient

import configuration

# same asset search as the employee service, but public (no JWT),
# with extra optional min_price / max_price filters
application = Flask(__name__)

mongo  = MongoClient(configuration.MONGO_URI)
assets = mongo[configuration.MONGO_DATABASE]["assets"]


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
        query["selling_date"] = {"$lt": date_parser.parse(selling_date)}

    price = {}
    if body.get("min_price") is not None:
        price["$gte"] = body["min_price"]
    if body.get("max_price") is not None:
        price["$lte"] = body["max_price"]
    if price:
        query["buying_price"] = price

    for info_filter in body.get("info_filters", []):
        operator = info_filter["operator"]
        if not operator.startswith("$"):
            operator = "$" + operator
        query["info." + info_filter["field"]] = {operator: info_filter["value"]}

    return query


@application.route("/search", methods=["POST"])
def search():
    body  = request.get_json(silent=True) or {}
    query = build_search_query(body)

    found = [serialize_asset(document) for document in assets.find(query)]

    return jsonify(assets=found), 200


if __name__ == "__main__":
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
