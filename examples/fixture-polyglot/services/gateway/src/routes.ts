import axios from 'axios';
import express from 'express';
import { interval } from 'rxjs';

const ordersApi = axios.create({ baseURL: process.env.ORDERS_API_URL });
const CATALOG_URL = process.env.CATALOG_URL ?? 'http://catalog:8000';

export const router = express.Router();

router.post('/checkout', async (req, res) => {
  const order = await ordersApi.post('/orders', req.body);
  res.send(order.data); // trap: an Express response, not a broker
});

router.get('/products/:id', async (req, res) => {
  const product = await fetch(`${CATALOG_URL}/products/${req.params.id}`);
  res.send(await product.json());
});

// trap: RxJS, not a message broker - and a localhost call, not topology
interval(60_000).subscribe(() => fetch('http://localhost:3000/health'));
