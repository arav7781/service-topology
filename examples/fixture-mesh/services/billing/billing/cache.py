"""Invoice de-duplication cache."""

import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://billing-cache:6379/0")


def cache_key(order_id):
    return "invoice:{0}".format(order_id)
