import re
import time

from flask import Flask, request, jsonify
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
from werkzeug.security import generate_password_hash, check_password_hash

import configuration
from configuration import Configuration
from models import database, User, ROLE_DIRECTOR, ROLE_EMPLOYEE

application = Flask(__name__)
application.config.from_object(Configuration)

database.init_app(application)
jwt = JWTManager(application)

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

MINIMUM_PASSWORD_LENGTH = 8


def find_missing_field(body, field_names):
    for name in field_names:
        value = body.get(name)
        if value is None or (isinstance(value, str) and len(value) == 0):
            return name
    return None


def error(message):
    return jsonify(message=message), 400


@application.route("/register", methods=["POST"])
def register():
    body = request.get_json(silent=True) or {}

    missing = find_missing_field(body, ["forename", "surname", "email", "password"])
    if missing is not None:
        return error(f"Field {missing} is missing.")

    if not EMAIL_REGEX.match(body["email"]):
        return error("Invalid email.")

    if len(body["password"]) < MINIMUM_PASSWORD_LENGTH:
        return error("Invalid password.")

    if User.query.filter_by(email=body["email"]).first() is not None:
        return error("Email already exists.")

    user = User(
        email=body["email"],
        password=generate_password_hash(body["password"]),
        forename=body["forename"],
        surname=body["surname"],
        role=ROLE_EMPLOYEE,
    )
    database.session.add(user)
    database.session.commit()

    return "", 200


@application.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}

    missing = find_missing_field(body, ["email", "password"])
    if missing is not None:
        return error(f"Field {missing} is missing.")

    if not EMAIL_REGEX.match(body["email"]):
        return error("Invalid email.")

    user = User.query.filter_by(email=body["email"]).first()
    if user is None or not check_password_hash(user.password, body["password"]):
        return error("Invalid credentials.")

    access_token = create_access_token(
        identity=user.email,
        additional_claims={
            "forename": user.forename,
            "surname": user.surname,
            "email": user.email,
            "role": user.role,
        },
    )

    return jsonify(accessToken=access_token), 200


@application.route("/delete", methods=["POST"])
@jwt_required()
def delete():
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if user is None:
        return error("Unknown user.")

    database.session.delete(user)
    database.session.commit()

    return "", 200


def initialize_database():
    with application.app_context():
        # we start at the same time as MySQL, which needs a moment to accept
        # connections, so retry until create_all goes through
        while True:
            try:
                database.create_all()
                break
            except Exception as exception:
                print(f"Waiting for database: {exception}", flush=True)
                time.sleep(2)

        if User.query.filter_by(email=configuration.DIRECTOR_EMAIL).first() is None:
            director = User(
                email=configuration.DIRECTOR_EMAIL,
                password=generate_password_hash(configuration.DIRECTOR_PASSWORD),
                forename=configuration.DIRECTOR_FORENAME,
                surname=configuration.DIRECTOR_SURNAME,
                role=ROLE_DIRECTOR,
            )
            database.session.add(director)
            database.session.commit()
            print("Initial director account created.", flush=True)


if __name__ == "__main__":
    initialize_database()
    application.run(host="0.0.0.0", port=configuration.SERVICE_PORT)
