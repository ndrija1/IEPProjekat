import os


MONGO_URI      = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = os.environ.get("MONGO_DATABASE", "fund")

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

ORDER_KEY_PREFIX = "order:"

SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "5001"))


class Configuration:
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "JWT_SECRET_DEV_KEY")
