import os

from .bus import EventBus
from .shipments import request_shipment

ORDER_PLACED = os.environ.get("ORDER_PLACED_TOPIC", "orders.placed")

bus = EventBus(group="fulfillment")
bus.subscribe(ORDER_PLACED, request_shipment)
