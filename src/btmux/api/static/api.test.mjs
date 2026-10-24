// Tests headless du client SSE (node --test api.test.mjs) — aucune dépendance.
import test from "node:test";
import assert from "node:assert/strict";
import { openEvents, request, ApiError } from "./api.js";

const enc = new TextEncoder();
function streamOf(chunks, { hang = false } = {}) {
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      if (!hang) c.close();
    },
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("parse SSE : chunks coupés, CRLF, commentaires, pairing fermé, device.removed, retry", async () => {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push(opts.headers);
    return new Response(streamOf([
      "retry: 20\n: ping\n\nevent: dev", "ice\nid: 7\r\ndata: {\"mac\":\"AA\"}\r\n\r\n",
      "event: pairing\nid: 8\ndata: {\"open\":false,\"adapter\":null,\"reason\":\"closed\"}\n\n",
      "event: device.removed\nid: 9\ndata: {\"mac\":\"AA\",\"adapter\":\"sources\"}\n\n",
    ], { hang: calls.length > 1 }), { status: 200 });
  };
  const got = [], states = [];
  const h = openEvents({ onEvent: (t, d) => got.push([t, d]), onState: (u) => states.push(u), onAuth() {} });
  await sleep(120);
  h.close();
  assert.deepEqual(got.slice(0, 2), [["device", { mac: "AA" }], ["pairing", { open: false, adapter: null, reason: "closed" }]]);
  assert.deepEqual(got[2], ["device.removed", { mac: "AA", adapter: "sources" }]);
  assert.equal(states[0], true);
  assert.equal(states[1], false, "fin de flux → onState(false)");
  // reconnexion après retry (20 ms) avec Last-Event-ID
  assert.ok(calls.length >= 2);
  assert.equal(calls[1]["Last-Event-ID"], "9");
  assert.equal(calls[0]["Last-Event-ID"], undefined);
  assert.equal(calls[0].Accept, "text/event-stream");
});

test("401 sur /api/events → onAuth, pas de reconnexion", async () => {
  let n = 0, auth = 0;
  globalThis.fetch = async () => { n++; return new Response("{}", { status: 401 }); };
  const h = openEvents({ onEvent() {}, onState() {}, onAuth: () => auth++ });
  await sleep(60);
  h.close();
  assert.equal(auth, 1);
  assert.equal(n, 1);
});

test("flux KO (réseau) → onState(false) puis nouvelle tentative", async () => {
  let n = 0;
  globalThis.fetch = async () => { n++; throw new TypeError("network"); };
  const states = [];
  const h = openEvents({ onEvent() {}, onState: (u) => states.push(u), onAuth() {} });
  await sleep(3200); // retry par défaut 3000 ms
  h.close();
  assert.ok(states.every((s) => s === false) && states.length >= 1);
  assert.ok(n >= 2);
});

test("request : ApiError avec status/code, 204 → null", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ error: "stale_bond", message: "bond périmé" }), { status: 409 });
  await assert.rejects(request("POST", "/api/devices/AA/pair"), (e) => e instanceof ApiError && e.status === 409 && e.code === "stale_bond");
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await request("DELETE", "/api/pairing"), null);
  globalThis.fetch = async () => { throw new TypeError("x"); };
  await assert.rejects(request("GET", "/api/state"), (e) => e.status === 0);
});
