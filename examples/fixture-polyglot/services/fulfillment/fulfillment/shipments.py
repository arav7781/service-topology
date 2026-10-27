import os

import boto3

sqs = boto3.client("sqs")


def request_shipment(order):
    sqs.send_message(QueueUrl=os.environ["SHIPMENTS_QUEUE_URL"], MessageBody=order)
