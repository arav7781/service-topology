from kafka import KafkaConsumer


def test_consumer_shape():
    # trap: a test double is not topology
    consumer = KafkaConsumer("orders.test", group_id="test")
    assert consumer is not None
