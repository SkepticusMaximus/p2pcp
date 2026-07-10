// e2e_buy.mjs — a Node buyer that runs the browser client for real:
//   node e2e_buy.mjs <gateway_port> <node_host> <node_port> <k> <job text>
// Connects to the Python gateway over WebSocket and buys one float job. Prints the
// JSON result. Used by tests/test_js_interop.py to prove the JS client settles a
// real job against a Python seller. In a browser the transport is the native
// WebSocket; here it's the `ws` package wrapped in the same tiny interface.

import './crypto-polyfill.mjs';                 // must be first (Node WebCrypto shim)
import WebSocket from 'ws';
import { Buyer, newIdentity } from './p2pcp.js';

function connect(url) {
  const ws = new WebSocket(url);
  const queue = [], waiters = [];
  ws.on('message', d => {
    const s = d.toString();
    if (waiters.length) waiters.shift()(s); else queue.push(s);
  });
  return new Promise((resolve, reject) => {
    ws.on('error', reject);
    ws.on('open', () => resolve({
      send: s => new Promise(r => ws.send(s, r)),
      recv: () => queue.length ? Promise.resolve(queue.shift())
                               : new Promise(r => waiters.push(r)),
      close: () => ws.close(),
    }));
  });
}

const [, , gwPort, host, port, k, ...jobParts] = process.argv;
const job = new TextEncoder().encode(jobParts.join(' ') || 'hello from the browser');
const buyer = new Buyer(await newIdentity());
const t = await connect(`ws://127.0.0.1:${gwPort}/?target=${host}:${port}`);
try {
  const result = await buyer.buyFloat(t, job, Number(k));
  console.log(JSON.stringify(result));
} finally {
  t.close();
}
