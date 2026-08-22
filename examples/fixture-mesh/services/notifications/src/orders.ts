const ORDERS_URL = 'http://orders-svc:8080';

// The notification body needs the customer email, which the event omits.
export async function loadOrder(orderId: string): Promise<unknown> {
  const response = await fetch(`${ORDERS_URL}/orders/${orderId}`, { method: 'GET' });
  return response.json();
}
