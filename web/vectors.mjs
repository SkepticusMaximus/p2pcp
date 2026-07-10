// vectors.mjs — emit deterministic crypto/serialization vectors for the JS client,
// so tests/test_js_interop.py can prove they are byte-identical to the Python core
// and that a JS-signed receipt verifies under PyNaCl. Fixed seed → reproducible.

import * as ed from '@noble/ed25519';
import { newIdentity, canon, canonStr, wireMmid, receiptPayload, hex } from './p2pcp.js';

const seed = new Uint8Array(32).fill(1);
const id = await newIdentity(seed);

const canonSampleObj = { b: 2, a: 1, nested: { y: 1, x: 2 }, arr: [3, 1, 2] };
const rp = receiptPayload('aa'.repeat(32), id.accountHex, 5,
                          'bb'.repeat(32), 'cc'.repeat(32), -1, 'dd'.repeat(16));

console.log(JSON.stringify({
  account: id.accountHex,
  canonSample: canonStr(canonSampleObj),
  sha3abc: hex(wireMmid(new TextEncoder().encode('abc'))),
  receiptPayload: rp,
  receiptCanon: canonStr(rp),
  receiptSig: hex(ed.sign(canon(rp), id.priv)),
}));
