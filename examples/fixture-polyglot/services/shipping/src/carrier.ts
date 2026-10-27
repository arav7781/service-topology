import { notifyCustomer } from './notify';

export async function createShipment(order: string): Promise<void> {
  await fetch('https://api.easypost.com/v2/shipments', { method: 'POST', body: order });
  await notifyCustomer(order);
}
