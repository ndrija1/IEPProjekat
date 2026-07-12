"""All configuration for the employee service, read from environment variables.

Defaults are suitable for running directly on the host; docker-compose and
Kubernetes override them through environment variables (ConfigMap / Secret).
"""

import os


MONGO_URI      = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DATABASE = os.environ.get("MONGO_DATABASE", "fund")

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Pending orders are stored in Redis under keys "<ORDER_KEY_PREFIX><uuid>".
ORDER_KEY_PREFIX = "order:"

SERVICE_PORT = int(os.environ.get("SERVICE_PORT", "5001"))


class Configuration:
    """Flask configuration object."""

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "JWT_SECRET_DEV_KEY")
