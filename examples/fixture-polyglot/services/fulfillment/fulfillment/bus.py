"""A thin wrapper so handlers never import confluent_kafka directly."""

from confluent_kafka import Consumer


class EventBus:
    def __init__(self, group):
        self._consumer = Consumer({"bootstrap.servers": "kafka:9092", "group.id": group})

    def subscribe(self, topic, handler):
        self._consumer.subscribe([topic])
        self._handler = handler
