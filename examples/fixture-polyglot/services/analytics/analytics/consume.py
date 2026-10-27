import os

from kafka import KafkaConsumer

consumer = KafkaConsumer(os.environ["ANALYTICS_TOPIC"], group_id="analytics")
