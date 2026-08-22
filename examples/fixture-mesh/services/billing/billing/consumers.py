"""Consume accepted orders and raise an invoice for each one."""

import os

from kafka import KafkaConsumer

GROUP_ID = os.environ.get("BILLING_GROUP_ID", "billing")


def build_consumer():
    """One consumer, one topic - orders.created is the only input."""
    return KafkaConsumer(
        "orders.created",
        group_id=GROUP_ID,
        bootstrap_servers=os.environ.get("KAFKA_BROKER", "kafka:9092"),
    )


def run():
    consumer = build_consumer()
    for message in consumer:
        raise_invoice(message.key, message.value)


def raise_invoice(key, payload):
    return {"order_id": key, "payload": payload}
