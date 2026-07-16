import os
from datetime import timedelta


DATABASE_HOST     = os.environ.get("DATABASE_HOST", "localhost")
DATABASE_PORT     = os.environ.get("DATABASE_PORT", "3306")
DATABASE_USERNAME = os.environ.get("DATABASE_USERNAME", "root")
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "root")
DATABASE_NAME     = os.environ.get("DATABASE_NAME", "authentication")

# initial director account, seeded on first start
DIRECTOR_FORENAME = os.environ.get("DIRECTOR_FORENAME", "Scrooge")
DIRECTOR_SURNAME  = os.environ.get("DIRECTOR_SURNAME", "McDuck")
DIRECTOR_EMAIL    = os.environ.get("DIRECTOR_EMAIL", "onlymoney@gmail.com")
DIRECTOR_PASSWORD = os.environ.get("DIRECTOR_PASSWORD", "evenmoremoney")

SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "5000"))


class Configuration:
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DATABASE_USERNAME}:{DATABASE_PASSWORD}"
        f"@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
    )
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "JWT_SECRET_DEV_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}  # survive a MySQL restart
