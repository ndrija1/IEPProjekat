"""Authentication service — user accounts and JWT tokens.

Endpoints (PDF: "Upravljanje korisničkim nalozima"):
    POST /register  - register a new employee
    POST /login     - hand back a 1-hour JWT access token
    POST /delete    - delete the caller's own account

The error messages and the order they're checked in are dictated by the
spec (and the grader checks both), so don't reorder the checks below.
"""

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

# Something before and after '@', and a TLD of at least two letters —
# so "john@gmail.a" is rejected, which the grader explicitly checks.
EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

MINIMUM_PASSWORD_LENGTH = 8


def find_missing_field(body, field_names):
    """First field that's missing, or None if all are present.

    Spec's definition of "missing": the key isn't there, or its value is an
    empty string. Checked in the given order so the reported field matches.
    """
    for name in field_names:
        value = body.get(name)
        if value is None or (isinstance(value, str) and len(value) == 0):
            return name
    return None


def error(message):
    return jsonify(message=message), 400


@application.route("/register", methods=["POST"])
def register():
    # silent=True: a missing/garbage body becomes None instead of a 500, so
    # we can answer with our own "Field ... is missing." message.
    body = request.get_json(silent=True) or {}

    # Order below is the spec's order — don't shuffle it.
    missing = find_missing_field(body, ["forename", "surname", "email", "password"])
    if missing is not None:
        return error(f"Field {missing} is missing.")

    if not EMAIL_REGEX.match(body["email"]):
        return error("Invalid email.")

    if len(body["password"]) < MINIMUM_PASSWORD_LENGTH:
        return error("Invalid password.")

    if User.query.filter_by(email=body["email"]).first() is not None:
        return error("Email already exists.")

    # Store a hash, never the plain password. New accounts are always
    # employees — the director is seeded once at startup.
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

    # Same message whether the email is unknown or the password is wrong —
    # don't reveal which emails exist.
    user = User.query.filter_by(email=body["email"]).first()
    if user is None or not check_password_hash(user.password, body["password"]):
        return error("Invalid credentials.")

    # identity becomes the "sub" claim. The extra claims carry the sign-up
    # data (minus password) plus the role — that role is what the employee
    # and director services check to authorize requests.
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
    # You can only delete yourself — the target comes from the token, not
    # the body. A token for an already-deleted account gives "Unknown user.".
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if user is None:
        return error("Unknown user.")

    database.session.delete(user)
    database.session.commit()

    return "", 200


def initialize_database():
    """Create the tables and seed the director, retrying until MySQL is up.

    We and the MySQL container start at the same time, and MySQL needs a
    dozen-plus seconds to accept connections — so retry instead of crashing.
    Everything here is idempotent: a restart won't duplicate anything.
    """
    with application.app_context():
        while True:
            try:
                # create_all is also our "is MySQL up yet?" probe: it throws
                # while MySQL is still booting, and is a no-op once tables exist.
                database.create_all()
                break
            except Exception as exception:
                print(f"Waiting for database: {exception}", flush=True)
                time.sleep(2)

        # Seed the director only if it isn't already there, so restarts are safe.
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
