import { connect, StringCodec } from 'nats';

const sc = StringCodec();

export async function notifyCustomer(order: string): Promise<void> {
  const nc = await connect({ servers: process.env.NATS_URL });
  nc.publish('user.notify', sc.encode(order));
}
