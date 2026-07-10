// Node-only shim: Node 18 doesn't expose WebCrypto as globalThis.crypto by default
// (browsers always do). Import this FIRST in a Node entry point so p2pcp.js and noble
// find crypto.getRandomValues. Browsers never load this file.
import { webcrypto } from 'node:crypto';
if (!globalThis.crypto) globalThis.crypto = webcrypto;
