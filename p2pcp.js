// p2pcp.js — a browser buyer for the CompuCoin compute mesh.
//
// A browser can't open raw TCP, so it talks to a p2pcp node through the WebSocket
// gateway (see p2pcp/gateway.py). This module speaks the wire byte-for-byte with the
// Python core: the same canonical JSON, the same SHA3-256 wire digests, the same
// ed25519 signatures — so a Python seller accepts a browser's receipts.
//
// Crypto is @noble (identical library in browser and Node). Transport is injected:
// pass anything with async send(str) / recv()->str / close(), so this runs over a
// real WebSocket in a browser and over a mock or `ws` client in tests.

import { sha3_256 } from '@noble/hashes/sha3';
import { sha512 } from '@noble/hashes/sha512';
import * as ed from '@noble/ed25519';

// noble-ed25519 needs a SHA-512; wire the pure-JS one so it works identically in
// the browser and in Node (no WebCrypto/subtle dependency).
ed.etc.sha512Sync = (...m) => sha512(ed.etc.concatBytes(...m));

export const HELLO_TYPE = 'P2PCP-HELLO-v0.1';
export const PROTOCOL_VERSION = '0.2';
export const ALG = 0;                       // ed25519 + SHA3-256 (the working slot)
export const VCLASS_NATIVE = 1, VCLASS_FLOAT = -1;

const te = new TextEncoder(), td = new TextDecoder();

export function hex(u8) {
  return Array.from(u8, b => b.toString(16).padStart(2, '0')).join('');
}
export function unhex(s) {
  const u = new Uint8Array(s.length / 2);
  for (let i = 0; i < u.length; i++) u[i] = parseInt(s.substr(i * 2, 2), 16);
  return u;
}
function randomBytes(n) {
  const u = new Uint8Array(n);
  globalThis.crypto.getRandomValues(u);
  return u;
}

// Canonical bytes IDENTICAL to Python's _canon: keys sorted (recursively), tight
// separators, UTF-8. Payloads are ASCII (hex strings + ints), so JSON.stringify and
// Python's json.dumps agree exactly.
function sortDeep(x) {
  if (Array.isArray(x)) return x.map(sortDeep);
  if (x && typeof x === 'object') {
    const o = {};
    for (const k of Object.keys(x).sort()) o[k] = sortDeep(x[k]);
    return o;
  }
  return x;
}
export function canon(obj) { return te.encode(JSON.stringify(sortDeep(obj))); }
export function canonStr(obj) { return JSON.stringify(sortDeep(obj)); }
export function wireMmid(bytes) { return sha3_256(bytes); }

// An identity is an ed25519 keypair; the account IS the 32-byte public key.
export async function newIdentity(seed) {
  const priv = seed || ed.utils.randomPrivateKey();      // 32-byte seed
  const pub = ed.getPublicKey(priv);
  return { priv, pub, accountHex: hex(pub) };
}

export async function helloFrame(id) {
  const msg = {
    type: HELLO_TYPE, account: id.accountHex, nonce: hex(randomBytes(16)),
    alg: ALG, version: PROTOCOL_VERSION, caps: ['compucoin'],
  };
  const sig = ed.sign(canon(msg), id.priv);
  return canonStr({ msg, sig: hex(sig) });
}

// Build the 8-field receipt signing payload (must match ledger.Receipt.signing_payload).
export function receiptPayload(workerHex, requesterHex, k, jobMmidHex, outMmidHex,
                               vclass, nonceHex) {
  return {
    worker: workerHex, requester: requesterHex, amount: k,
    job_commit: jobMmidHex, output_commit: outMmidHex, vclass,
    nonce: nonceHex, alg: ALG,
  };
}

export class Buyer {
  constructor(id) { this.id = id; }

  // Buy one float job (money, no replay audit — the browser's natural role).
  // `transport` is already connected to the gateway with ?target=<node>. Returns
  // { output: string, paid: number, worker: string }.
  async buyFloat(transport, jobBytes, k = 5) {
    await transport.send(await helloFrame(this.id));                    // 1. HELLO
    const workerHello = JSON.parse(await transport.recv());
    const worker = workerHello.msg.account;
    const jobMmid = wireMmid(jobBytes);
    await transport.send(canonStr({                                     // 2. JOB
      t: 'JOB', job: hex(jobBytes), job_mmid: hex(jobMmid),
      n_chunks: 1, k, vclass: VCLASS_FLOAT,
    }));
    const res = JSON.parse(await transport.recv());                     // 3. RESULT
    if (res.t !== 'RESULT') throw new Error('no result: ' + JSON.stringify(res));
    const output = unhex(res.output);
    if (hex(wireMmid(output)) !== res.output_mmid) {
      throw new Error('output digest mismatch — the seller lied about its own bytes');
    }
    const nonce = randomBytes(16);
    const payload = receiptPayload(worker, this.id.accountHex, k, hex(jobMmid),
                                   res.output_mmid, VCLASS_FLOAT, hex(nonce));
    const requesterSig = ed.sign(canon(payload), this.id.priv);
    await transport.send(canonStr({                                     // 4. RECEIPT
      t: 'RECEIPT',
      receipt: { ...payload, worker_sig: '', requester_sig: hex(requesterSig) },
    }));
    const ack = JSON.parse(await transport.recv());                     // 5. ACK
    if (ack.t !== 'RECEIPT_ACK') throw new Error('not co-signed: ' + JSON.stringify(ack));
    return { output: td.decode(output), paid: k, worker };
  }
}
