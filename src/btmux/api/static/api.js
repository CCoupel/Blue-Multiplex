// Client HTTP btmuxd — jeton Bearer en localStorage, jamais en dur.
const KEY = "btmux.token";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code || "";
  }
}

export function getToken() {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
}
export function setToken(t) {
  try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch { /* stockage indisponible */ }
}

function headers(extra = {}) {
  const h = { ...extra };
  const t = getToken();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

export async function request(method, path, body) {
  const opts = { method, headers: headers(body !== undefined ? { "Content-Type": "application/json" } : {}) };
  if (body !== undefined) opts.body = JSON.stringify(body);
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new ApiError(0, "network", "API injoignable");
  }
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch { /* corps non JSON */ }
    throw new ApiError(res.status, data.error, data.message);
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  health: () => request("GET", "/api/health"),
  state: () => request("GET", "/api/state"),
  discovered: () => request("GET", "/api/discovered"),
  openPairing: (adapter, duration) => request("POST", "/api/pairing", { adapter, duration }),
  closePairing: () => request("DELETE", "/api/pairing"),
  pair: (mac) => request("POST", `/api/devices/${encodeURIComponent(mac)}/pair`),
  connect: (mac) => request("POST", `/api/devices/${encodeURIComponent(mac)}/connect`),
  disconnect: (mac) => request("POST", `/api/devices/${encodeURIComponent(mac)}/disconnect`),
  forget: (mac) => request("POST", `/api/devices/${encodeURIComponent(mac)}/forget`),
  patch: (mac, fields) => request("PATCH", `/api/devices/${encodeURIComponent(mac)}`, fields),
};

// SSE via fetch : EventSource ne sait pas envoyer l'en-tête Authorization (exigé sur /api/events).
// Retourne un handle { close() } ; onEvent(type, data) ; onState(true|false) ; onAuth() sur 401.
export function openEvents({ onEvent, onState, onAuth }) {
  const ctrl = new AbortController();
  let retry = 3000;
  let lastId = "";
  let closed = false;

  async function run() {
    while (!closed) {
      try {
        const h = headers({ Accept: "text/event-stream" });
        if (lastId) h["Last-Event-ID"] = lastId;
        const res = await fetch("/api/events", { headers: h, signal: ctrl.signal });
        if (res.status === 401) { onAuth(); onState(false); return; }
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        onState(true);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const ev = parseBlock(block);
            if (ev.retry) retry = ev.retry;
            if (ev.id) lastId = ev.id;
            if (ev.has) onEvent(ev.type, ev.data);
          }
        }
      } catch (e) {
        if (closed) return;
      }
      if (closed) return;
      onState(false);
      await new Promise((r) => setTimeout(r, retry));
    }
  }

  function parseBlock(block) {
    let type = "message", id = "", retryMs = 0;
    const data = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const c = line.indexOf(":");
      const f = c < 0 ? line : line.slice(0, c);
      const v = c < 0 ? "" : line.slice(c + 1).replace(/^ /, "");
      if (f === "event") type = v;
      else if (f === "data") data.push(v);
      else if (f === "id") id = v;
      else if (f === "retry") retryMs = parseInt(v, 10) || 0;
    }
    let parsed = null;
    if (data.length) {
      try { parsed = JSON.parse(data.join("\n")); } catch { parsed = null; }
    }
    return { type, id, retry: retryMs, has: data.length > 0, data: parsed };
  }

  run();
  return { close() { closed = true; ctrl.abort(); } };
}
