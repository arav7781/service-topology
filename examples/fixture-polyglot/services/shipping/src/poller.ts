import { ReceiveMessageCommand, SQSClient } from '@aws-sdk/client-sqs';
import { createShipment } from './carrier';

const sqs = new SQSClient({});

export async function poll(): Promise<void> {
  const out = await sqs.send(new ReceiveMessageCommand({ QueueUrl: process.env.SHIPMENTS_QUEUE_URL }));
  for (const message of out.Messages ?? []) await createShipment(message.Body ?? '');
}
