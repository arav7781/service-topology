import { Kafka } from 'kafkajs';

const kafka = new Kafka({
  clientId: 'notifications-svc',
  brokers: [process.env.KAFKA_BROKER ?? 'kafka:9092'],
});

const consumer = kafka.consumer({ groupId: 'notifications' });
const producer = kafka.producer();

export async function start(): Promise<void> {
  await consumer.connect();
  await consumer.subscribe({ topic: 'orders.created', fromBeginning: false });

  await consumer.run({
    eachMessage: async ({ message }) => {
      await send(message.key?.toString() ?? 'unknown');
    },
  });
}

// Every delivery attempt is itself an event, so the audit trail is a topic.
async function send(orderId: string): Promise<void> {
  await producer.send({
    topic: 'notifications.sent',
    messages: [{ key: orderId, value: JSON.stringify({ orderId }) }],
  });
}
