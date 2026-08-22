"""Read-side client for the orders service."""

import os

import requests

ORDERS_BASE_URL = os.environ["ORDERS_SERVICE_URL"]


def fetch_order(order_id):
    """The invoice needs the full order, which the event does not carry."""
    response = requests.get(ORDERS_BASE_URL + "/orders/" + str(order_id), timeout=5)
    response.raise_for_status()
    return response.json()
