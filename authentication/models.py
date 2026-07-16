from flask_sqlalchemy import SQLAlchemy

database = SQLAlchemy()

ROLE_DIRECTOR = "director"
ROLE_EMPLOYEE = "employee"


class User(database.Model):
    __tablename__ = "users"

    id       = database.Column(database.Integer, primary_key=True)
    email    = database.Column(database.String(256), nullable=False, unique=True)
    password = database.Column(database.String(256), nullable=False)  # werkzeug hash
    forename = database.Column(database.String(256), nullable=False)
    surname  = database.Column(database.String(256), nullable=False)
    role     = database.Column(database.String(16), nullable=False)
