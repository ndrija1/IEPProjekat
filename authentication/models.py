from flask_sqlalchemy import SQLAlchemy

database = SQLAlchemy()

ROLE_DIRECTOR = "director"
ROLE_EMPLOYEE = "employee"


class User(database.Model):
    """A user account.

    The specification stores: email and password (used for login),
    forename, surname and the user's role (director or employee).
    """

    __tablename__ = "users"

    id       = database.Column(database.Integer, primary_key=True)
    email    = database.Column(database.String(256), nullable=False, unique=True)
    # Stores a werkzeug password hash, never the plain-text password.
    password = database.Column(database.String(256), nullable=False)
    forename = database.Column(database.String(256), nullable=False)
    surname  = database.Column(database.String(256), nullable=False)
    role     = database.Column(database.String(16), nullable=False)
