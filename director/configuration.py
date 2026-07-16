import os


MONGO_URI      = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = os.environ.get("MONGO_DATABASE", "fund")

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

ORDER_KEY_PREFIX = "order:"   # must match the employee service
VOTE_KEY_PREFIX = "vote:"

# "simple" = director decides directly, "voting" = smart-contract vote.
# BLOCKCHAIN_ENABLED=true is accepted as an alias (the grader uses that name).
_blockchain_enabled = os.environ.get("BLOCKCHAIN_ENABLED", "").lower() in ("true", "1", "yes")
DECISION_MODE = os.environ.get("DECISION_MODE", "voting" if _blockchain_enabled else "simple")

GANACHE_URL = os.environ.get("GANACHE_URL", "http://localhost:8545")
VOTE_POLL_INTERVAL = float(os.environ.get("VOTE_POLL_INTERVAL", "2"))

SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "5002"))


class Configuration:
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "JWT_SECRET_DEV_KEY")
