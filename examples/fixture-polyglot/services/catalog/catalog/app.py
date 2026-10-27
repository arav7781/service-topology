import os

import redis
from fastapi import FastAPI

app = FastAPI()
cache = redis.Redis.from_url(os.environ.get("CACHE_URL", "redis://catalog-cache:6379/0"))


@app.get("/products/{product_id}")
def product(product_id: str):
    return {"id": product_id, "cached": cache.exists(product_id)}
