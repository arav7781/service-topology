import pika

connection = pika.BlockingConnection(pika.URLParameters("amqp://rabbitmq:5672"))
channel = connection.channel()
channel.queue_declare(queue="fulfillment.payments")
channel.queue_bind(queue="fulfillment.payments", exchange="payments", routing_key="payment.captured")


def on_payment(ch, method, properties, body):
    print("payment captured for", body)


channel.basic_consume(queue="fulfillment.payments", on_message_callback=on_payment)
