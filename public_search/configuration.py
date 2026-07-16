import os


MONGO_URI      = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = os.environ.get("MONGO_DATABASE", "fund")
SERVICE_PORT   = int(os.environ.get("SERVICE_PORT", "5003"))
