import { api, ApiError, getToken, setToken, openEvents } from "./api.js";

const POLL_MS = 5000;
const ROLES = {
  sources: { id: "panel-sources", h: "h-src", title: "Sources", hci: "hci-src", sub: "vus comme « casque » par les PC et téléphones" },
  headsets: { id: "panel-headsets", h: "h-hp", title: "Casques", hci: "hci-hp", sub: "le Pi initie l'appairage et la connexion des casques" },
};

const S = {
  version: "", adapters: [], devices: [], discovered: [],
  pairing: null, deadline: 0, // deadline = Date.now() + remaining_s*1000 à la réception
  pending: new Map(), // mac -> échéance (ms) : opération asynchrone pair/connect en cours
  controllers: [], roles: null, draft: null, // draft : {sources, headsets} choisi dans les sélecteurs, non appliqué
  restartUntil: 0, // échéance (ms) du bandeau de redémarrage
  live: false, durations: { headsets: 60, sources: 60 }, busy: new Set(), errors: [],
};
let events = null, pollTimer = null, tickTimer = null;

// ---------- helpers DOM ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k);
  return el;
}
const $ = (id) => document.getElementById(id);
const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const remaining = () => Math.max(0, Math.ceil((S.deadline - Date.now()) / 1000));
const dev = (mac) => S.devices.find((d) => d.mac === mac);
const label = (d) => d.alias || d.name || d.mac;

// ---------- journal ----------
function log(type, text) {
  const pre = $("log");
  const t = new Date().toTimeString().slice(0, 8);
  pre.textContent += `${t}  ${type.padEnd(10)} ${text}\n`;
  const lines = pre.textContent.split("\n");
  if (lines.length > 201) pre.textContent = lines.slice(-201).join("\n");
  pre.scrollTop = pre.scrollHeight;
}

// ---------- erreurs ----------
function pushError(err, ctx = {}) {
  if (err instanceof ApiError && err.status === 401) { askToken(); return; }
  const msg = err.code === "operation_in_progress" ? "Une opération est déjà en cours pour cet appareil, patientez." : err.message;
  const e = { id: Math.random(), title: ctx.title || "Erreur", message: msg, code: err.code, ctx, status: err.status };
  S.errors = [e, ...S.errors].slice(0, 3);
  renderErrors();
}
function dismiss(id) { S.errors = S.errors.filter((e) => e.id !== id); renderErrors(); }
const isStaleBond = (e) => e.status === 409 && /bond|authentication|périm|stale/i.test(`${e.code} ${e.message}`);

function renderErrors() {
  $("errors").replaceChildren(...S.errors.map((e) => {
    const stale = isStaleBond(e) && e.ctx.mac;
    return h("div", { class: "full toast", role: "alert" },
      h("div", { class: "msg" }, h("strong", {}, e.title), " — ",
        e.ctx.mac ? `${e.ctx.mac} : ` : "", e.message,
        stale ? " (bond périmé). Oubliez l'appareil ici et sur la source, puis rouvrez la fenêtre." : ""),
      stale ? h("button", { class: "danger", onclick: () => { dismiss(e.id); forgetThenRepair(e.ctx.mac); } }, "Oublier puis réappairer") : null,
      h("button", { onclick: () => dismiss(e.id), "aria-label": "Fermer le message" }, "Fermer"));
  }));
}

function askToken() {
  S.errors = [{ id: "auth", title: "Jeton refusé (401)", message: "Saisissez un jeton API valide puis cliquez sur « Enregistrer ».", code: "unauthorized", ctx: {}, status: 401 }];
  renderErrors();
  stopLive();
  setStatus("err", "jeton requis");
  $("token").focus();
}

// ---------- actions ----------
async function act(key, fn, ctx) {
  if (S.busy.has(key)) return;
  S.busy.add(key); render();
  try { await fn(); } catch (e) { pushError(e, ctx); }
  finally { S.busy.delete(key); await refresh(); }
}

const PENDING_MS = 60000;
// Opération asynchrone (202) : le bouton reste grisé jusqu'à l'événement `device` du MAC, ou 60 s.
function withPending(mac, call) {
  return async () => {
    S.pending.set(mac, Date.now() + PENDING_MS);
    render();
    try { await call(); } catch (e) {
      if (e.code !== "operation_in_progress") S.pending.delete(mac); // sinon l'opération en cours reste suivie
      throw e;
    }
  };
}
const isPending = (mac) => S.pending.has(mac);
const pendingTag = () => h("span", { class: "pending", role: "status" }, "en cours…");

const confirmDlg = () => $("confirm");
function confirmForget(d) {
  $("confirm-text").replaceChildren(
    h("strong", {}, `Oublier « ${label(d)} » ?`), h("br"),
    `L'appareil sera supprimé de ${ROLES[d.adapter].hci}. Il faudra aussi l'oublier côté ${d.adapter === "sources" ? "source" : "casque"} avant tout nouvel appairage.`);
  return new Promise((resolve) => {
    const dlg = confirmDlg();
    const done = (v) => { dlg.close(); $("confirm-ok").onclick = $("confirm-cancel").onclick = null; resolve(v); };
    $("confirm-ok").onclick = () => done(true);
    $("confirm-cancel").onclick = () => done(false);
    dlg.oncancel = () => resolve(false);
    dlg.showModal();
    $("confirm-cancel").focus();
  });
}

async function onForget(d) {
  if (!(await confirmForget(d))) return;
  act(`forget:${d.mac}`, () => api.forget(d.mac), { title: "Oubli refusé", mac: d.mac });
}
async function forgetThenRepair(mac) {
  const d = dev(mac);
  try { await api.forget(mac); log("device", `${mac} oublié (bond périmé)`); } catch (e) { pushError(e, { title: "Oubli refusé", mac }); return; }
  await refresh();
  const role = d ? d.adapter : "headsets";
  S.errors = [{ id: "hint", title: "Appareil oublié", message: `Oubliez-le aussi côté ${role === "sources" ? "source" : "casque"}, puis rouvrez la fenêtre d'appairage.`, code: "", ctx: {}, status: 0 }];
  renderErrors();
}

// ---------- rendu ----------
function setStatus(kind, text) {
  const s = $("status");
  if (restarting() && kind !== "err") { kind = "warn"; text = "redémarrage du service…"; } // libellé stable pendant toute la coupure
  s.replaceChildren(h("span", { class: `dot ${kind === "ok" ? "" : kind}` }), text);
  $("mode-tag").textContent = S.live ? "SSE" : (pollTimer ? "polling 5 s" : "—");
}
function statusText() {
  return `API ${S.version || "?"} · événements : ${S.live ? "en direct" : "polling 5 s"}`;
}

function tag(text, cls) { return h("span", { class: `tag ${cls || ""}` }, text); }

function deviceRow(d) {
  const key = (a) => `${a}:${d.mac}`;
  const busy = (a) => S.busy.has(key(a));
  return h("tr", {},
    h("td", {}, h("strong", {}, d.alias || d.name || d.mac), h("br"),
      h("span", { class: "mac" }, `${d.alias && d.name ? d.name + " · " : ""}${d.kind === "unknown" ? "inconnu" : d.kind === "source" ? "source" : "casque"}`)),
    h("td", { class: "mac" }, d.mac),
    h("td", {},
      tag(d.connected ? "connecté" : "déconnecté", d.connected ? "on" : "off"),
      d.paired ? tag("appairé", "on") : tag("non appairé", "off"),
      tag(d.trusted ? "de confiance" : "pas de confiance", d.trusted ? "on" : "off"),
      d.blocked ? tag("bloqué", "off") : null,
      d.in_config ? tag("config", "cfg") : tag("hors config", "off")),
    h("td", { class: "actions" },
      d.connected
        ? h("button", { disabled: busy("disconnect"), onclick: () => act(key("disconnect"), () => api.disconnect(d.mac), { title: "Déconnexion impossible", mac: d.mac }) }, "Déconnecter")
        : h("button", { class: "primary", disabled: busy("connect") || isPending(d.mac), onclick: () => act(key("connect"), withPending(d.mac, () => api.connect(d.mac)), { title: "Connexion impossible", mac: d.mac }) }, "Connecter"),
      isPending(d.mac) ? pendingTag() : null,
      d.paired ? h("button", { disabled: busy("trust"), onclick: () => act(key("trust"), () => api.patch(d.mac, { trusted: !d.trusted }), { title: "Modification refusée", mac: d.mac }) },
        d.trusted ? "Retirer la confiance" : "Faire confiance") : null,
      d.paired ? h("button", { class: "danger", disabled: busy("forget"), onclick: () => onForget(d) }, "Oublier") : null));
}

function devicesTable(list) {
  if (!list.length) return h("p", { class: "empty" }, "Aucun appareil connu.");
  return h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Appareil"), h("th", {}, "MAC"), h("th", {}, "État"), h("th", {}, "Actions"))),
    h("tbody", {}, list.map(deviceRow)));
}

function pairBox(role) {
  const w = S.pairing;
  const mine = w && w.adapter === role;
  const other = w && !mine;
  if (mine) {
    return h("div", { class: "pair open" },
      h("div", { class: "info" }, h("strong", {}, "Fenêtre d'appairage ouverte "),
        h("span", { class: "count", "data-countdown": "1" }, fmtTime(remaining())), " restantes",
        role === "sources" ? " — les appareils qui s'appairent maintenant sont acceptés et marqués de confiance" : " — recherche de casques en cours"),
      h("button", { class: "danger", disabled: S.busy.has("close"), onclick: () => act("close", () => api.closePairing(), { title: "Fermeture impossible" }) }, "Fermer"));
  }
  const id = `dur-${role}`;
  return h("div", { class: "pair" },
    h("div", { class: "info" }, h("strong", {}, "Fenêtre d'appairage fermée"), other ? " — une autre fenêtre est ouverte" : ""),
    h("label", {}, "Durée ",
      h("select", { id, onchange: (e) => { S.durations[role] = parseInt(e.target.value, 10); } },
        [30, 60, 120, 300].map((n) => h("option", { value: n, selected: S.durations[role] === n }, `${n} s`)))),
    h("button", { class: "primary", disabled: other || S.busy.has("open:" + role),
      onclick: () => act("open:" + role, () => api.openPairing(role, S.durations[role]), { title: "Ouverture refusée" }) },
      role === "headsets" ? "Rechercher des casques" : "Ouvrir la fenêtre"));
}

function discoveredBlock() {
  const open = S.pairing && S.pairing.adapter === "headsets";
  const rows = S.discovered.filter((x) => !dev(x.mac) || !dev(x.mac).paired);
  return [
    h("h3", { class: "sub-title" }, "Casques découverts ", h("span", { class: "sub inline" }, "(pendant une recherche)")),
    !open ? h("p", { class: "empty" }, "Aucune recherche en cours.")
      : !rows.length ? h("p", { class: "empty" }, "Recherche en cours… aucun casque vu pour l'instant.")
      : h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Appareil"), h("th", {}, "MAC"), h("th", {}, "Signal"), h("th", {}, "Actions"))),
        h("tbody", {}, rows.map((x) => h("tr", {},
          h("td", {}, x.name || "(sans nom)"), h("td", { class: "mac" }, x.mac), h("td", {}, x.rssi != null ? `${x.rssi} dBm` : "—"),
          h("td", { class: "actions" }, h("button", { class: "primary", disabled: S.busy.has("pair:" + x.mac) || isPending(x.mac),
            onclick: () => act("pair:" + x.mac, withPending(x.mac, () => api.pair(x.mac)), { title: "Appairage refusé", mac: x.mac }) }, "Appairer"),
            isPending(x.mac) ? pendingTag() : null))))),
  ];
}

function renderPanel(role) {
  const r = ROLES[role];
  const a = S.adapters.find((x) => x.role === role);
  const el = $(r.id);
  if (S.roles && S.roles[role] === null && !a) {
    el.replaceChildren(
      h("h2", { id: r.h }, r.title, " ", tag(r.hci, "off"), tag("rôle non affecté", "off")),
      h("p", { class: "empty" }, `Aucun contrôleur n'est affecté au rôle « ${r.title} ». Choisissez-en un dans la section Contrôleurs.`));
    return;
  }
  el.replaceChildren(...[
    h("h2", { id: r.h }, r.title, " ", tag(r.hci, "on"),
      a ? [tag(`alias ${a.alias}`), tag(a.powered ? "powered" : "éteint", a.powered ? "on" : "off")] : tag("absent", "off")),
    h("p", { class: "sub" }, a ? `${a.mac} · ${a.hci} · classe ${a.class} · ${r.sub}` : r.sub),
    pairBox(role),
    devicesTable(S.devices.filter((d) => d.adapter === role)),
    role === "headsets" ? discoveredBlock() : null].flat().filter(Boolean));
}

// ----- contrôleurs (#23) -----
const ROLE_LABEL = { sources: "Sources (hci-src)", headsets: "Casques (hci-hp)", none: "Aucun" };
const busLabel = (c) => (c.bus === "usb" ? `USB${c.usb_id ? " " + c.usb_id : ""}` : c.bus === "uart" ? "UART" : "inconnu");
const shortMac = (m) => m.split(":").slice(-2).join(":");
const ctlByMac = (mac) => S.controllers.find((c) => c.mac === mac);
const ctlName = (mac) => { const c = ctlByMac(mac); return c ? `${c.name || c.hci} (${shortMac(mac)})` : (mac ? shortMac(mac) : "aucun"); };
const current = () => ({ sources: S.roles ? S.roles.sources : null, headsets: S.roles ? S.roles.headsets : null });
const draftOrCurrent = () => S.draft || current();
const changed = () => { const d = draftOrCurrent(), c = current(); return d.sources !== c.sources || d.headsets !== c.headsets; };
const restarting = () => !!(S.roles && S.roles.pending) || Date.now() < S.restartUntil;

function roleOf(c) { const d = draftOrCurrent(); return d.sources === c.mac ? "sources" : d.headsets === c.mac ? "headsets" : "none"; }
function chooseRole(c, role) {
  const d = { ...draftOrCurrent() };
  if (d.sources === c.mac) d.sources = null;
  if (d.headsets === c.mac) d.headsets = null;
  if (role !== "none") d[role] = c.mac; // l'ancien titulaire du rôle passe à « Aucun » : à réaffecter (permutation en deux choix)
  S.draft = d;
  render();
}

function draftSummary() {
  const d = draftOrCurrent(), c = current(), out = [];
  for (const role of ["sources", "headsets"]) {
    if (d[role] !== c[role]) out.push(h("span", {}, h("strong", {}, ROLES[role].title), ` ${shortMac(c[role] || "—")} → ${d[role] ? shortMac(d[role]) : "aucun"} `));
  }
  return out;
}

function renderControllers() {
  const el = $("panel-controllers");
  const locked = restarting();
  const rows = S.controllers.map((c) => h("tr", {},
    h("td", {}, h("strong", {}, c.name || c.hci), h("br"), h("span", { class: "mac" }, c.hci)),
    h("td", { class: "mac" }, c.mac), h("td", {}, busLabel(c)),
    h("td", {}, c.present === false ? tag("absent", "off") : tag(c.powered ? "powered" : "éteint", c.powered ? "on" : "off"),
      c.present === false ? null : (!c.pairable && !c.discoverable ? tag("fermé", "on") : tag("ouvert", "off")),
      tag(c.connected_devices ? `${c.connected_devices} appareil${c.connected_devices > 1 ? "s" : ""} connecté${c.connected_devices > 1 ? "s" : ""}` : "0 appareil")),
    h("td", {}, h("select", { "aria-label": `Rôle du contrôleur ${shortMac(c.mac)}`, disabled: locked || c.present === false,
      onchange: (e) => chooseRole(c, e.target.value) },
      ["sources", "headsets", "none"].map((r) => h("option", { value: r, selected: roleOf(c) === r }, ROLE_LABEL[r]))))));
  el.replaceChildren(...[
    h("h2", { id: "h-ctl" }, "Contrôleurs Bluetooth ", tag(`${S.controllers.length} détecté${S.controllers.length > 1 ? "s" : ""}`),
      S.roles ? tag(`affectation : ${S.roles.source === "state" ? "état (API)" : "config"}`, S.roles.source === "state" ? "on" : "") : null),
    h("p", { class: "sub" }, "Choisissez quel contrôleur joue chaque rôle (USB ou UART). Les contrôleurs sans rôle sont fermés (ni appairables ni visibles). L'affectation est mémorisée par adresse et appliquée par un redémarrage du service (~15–20 s)."),
    S.controllers.length
      ? h("table", {}, h("thead", {}, h("tr", {}, ["Contrôleur", "Adresse", "Bus", "État", "Rôle"].map((t) => h("th", {}, t)))), h("tbody", {}, rows))
      : h("p", { class: "empty" }, "Aucun contrôleur détecté."),
    changed() ? h("div", { class: "pair" },
      h("span", { class: "status info" }, "Modification en attente : ", draftSummary()),
      h("button", { disabled: locked, onclick: () => { S.draft = null; render(); } }, "Annuler"),
      h("button", { class: "primary", disabled: locked || S.busy.has("roles"), onclick: () => applyRoles(false) }, S.busy.has("roles") ? "Application en cours… (déconnexion des appareils, jusqu'à ~5 s par appareil)" : "Appliquer")) : null,
  ].filter(Boolean));
}

function renderBanner() {
  const b = $("restart-banner");
  if (!restarting()) { b.hidden = true; b.replaceChildren(); return; }
  b.hidden = false;
  b.replaceChildren(h("span", { class: "dot warn" }), h("strong", {}, "Application de l'affectation… "),
    "le service btmux redémarre (environ 15 à 20 s). Les actions sont désactivées ; la page se reconnecte automatiquement. ",
    h("span", { class: "spacer" }), h("span", { class: "count", "data-restart": "1" }, fmtTime(Math.max(0, Math.ceil((S.restartUntil - Date.now()) / 1000)))));
}

function startRestart() { S.restartUntil = Date.now() + 20000; }

function confirmRoles(lines) {
  $("confirm-roles-text").replaceChildren(h("strong", {}, "Appliquer la nouvelle affectation ?"), h("br"),
    `${lines.length ? lines.length + " appareil(s) connecté(s) seront déconnectés : " + lines.join(", ") + ". " : ""}Les appareils devront être reconnectés (ils restent appairés). Le service btmux redémarre (environ 15 à 20 s) ; l'interface se reconnecte et se met à jour dès que les rôles sont actifs.`);
  return new Promise((resolve) => {
    const dlg = $("confirm-roles");
    const done = (v) => { dlg.close(); $("confirm-roles-ok").onclick = $("confirm-roles-cancel").onclick = null; resolve(v); };
    $("confirm-roles-ok").onclick = () => done(true);
    $("confirm-roles-cancel").onclick = () => done(false);
    dlg.oncancel = () => resolve(false);
    dlg.showModal();
    $("confirm-roles-cancel").focus();
  });
}
const detailLabel = (x) => (typeof x === "string" ? x : x && (x.alias || x.name || x.mac) || "?");

async function applyRoles(confirm) {
  const d = draftOrCurrent();
  S.busy.add("roles"); render();
  try {
    const roles = await api.putRoles({ sources: d.sources, headsets: d.headsets, confirm });
    S.roles = roles && roles.sources !== undefined ? roles : S.roles;
    S.draft = null; startRestart();
    log("roles", `affectation acceptée : redémarrage attendu (~15–20 s)`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.code === "devices_connected" && !confirm) {
      const list = Array.isArray(e.details) ? e.details.map(detailLabel) : [];
      S.busy.delete("roles");
      if (await confirmRoles(list)) return applyRoles(true);
    } else if (e instanceof ApiError && e.status === 409 && e.code === "pairing_open") {
      pushError(new ApiError(409, e.code, "Fermez d'abord la fenêtre d'appairage, puis réessayez."), { title: "Affectation refusée" });
    } else if (e instanceof ApiError && e.status === 409 && e.code === "change_pending") {
      pushError(new ApiError(409, e.code, "Un changement d'affectation est déjà en cours, patientez."), { title: "Affectation refusée" });
    } else if (e instanceof ApiError && e.status === 502 && e.code === "disconnect_failed") {
      const list = Array.isArray(e.details) ? e.details.map(detailLabel).join(", ") : "";
      pushError(new ApiError(502, e.code, `Impossible de déconnecter${list ? ` : ${list}` : " certains appareils"}. Rien n'a été modifié, aucun redémarrage : réessayez.`), { title: "Affectation non appliquée" });
    } else pushError(e, { title: "Affectation refusée" });
  } finally { S.busy.delete("roles"); render(); }
}

function render() {
  renderBanner();
  renderControllers();
  renderPanel("sources");
  renderPanel("headsets");
  if (restarting()) document.querySelectorAll("main button, main select").forEach((n) => { n.disabled = true; });
  if (S.live || pollTimer) setStatus(S.live ? "ok" : "warn", statusText());
}

function tick() {
  let expired = false;
  for (const [mac, t] of S.pending) if (Date.now() >= t) { S.pending.delete(mac); expired = true; }
  if (expired) render();
  document.querySelectorAll("[data-restart]").forEach((n) => { n.textContent = fmtTime(Math.max(0, Math.ceil((S.restartUntil - Date.now()) / 1000))); });
  if (S.restartUntil && Date.now() >= S.restartUntil && !(S.roles && S.roles.pending)) { S.restartUntil = 0; render(); }
  document.querySelectorAll("[data-countdown]").forEach((n) => { n.textContent = fmtTime(remaining()); });
  if (S.pairing && remaining() === 0) refresh();
}

// ---------- données ----------
function setPairing(w) {
  // Contrat 3db8c3c : fenêtre fermée = objet {open:false, reason} (jamais null) ; null/sans adapter toléré.
  S.pairing = w && w.open !== false && w.adapter ? w : null;
  S.deadline = S.pairing ? Date.now() + (S.pairing.remaining_s ?? 0) * 1000 : 0;
  if (!S.pairing) S.discovered = [];
}

function applyControllers(st) {
  if (Array.isArray(st.controllers)) S.controllers = st.controllers;
  if (st.roles) {
    const was = S.roles;
    S.roles = st.roles;
    if (!st.roles.pending) S.restartUntil = 0;
    if (S.draft && was && (was.sources !== st.roles.sources || was.headsets !== st.roles.headsets)) S.draft = null;
  }
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const st = await api.state();
    S.version = st.version; S.adapters = st.adapters; S.devices = st.devices;
    applyControllers(st);
    setPairing(st.pairing);
    if (S.pairing && S.pairing.adapter === "headsets") S.discovered = await api.discovered();
    if (S.errors.some((e) => e.id === "net")) dismiss("net");
    render();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) askToken();
    else if (restarting()) setStatus("warn", "redémarrage du service…");
    else { setStatus("err", e.message); if (!S.errors.some((x) => x.id === "net")) { S.errors = [{ id: "net", title: "API", message: e.message, code: e.code, ctx: {}, status: e.status }, ...S.errors]; renderErrors(); } }
  } finally { refreshing = false; }
}

function onEvent(type, data) {
  switch (type) {
    case "controllers":
      S.controllers = data;
      log("controllers", `${data.length} contrôleur(s)`);
      break;
    case "roles":
      S.roles = data;
      if (data.pending && data.restart_expected) startRestart();
      else if (!data.pending) S.restartUntil = 0;
      log("roles", `sources=${data.sources ? shortMac(data.sources) : "—"} casques=${data.headsets ? shortMac(data.headsets) : "—"}${data.pending ? " (en cours, redémarrage attendu)" : ""}`);
      break;
    case "adapter": {
      const i = S.adapters.findIndex((a) => a.role === data.role);
      i >= 0 ? (S.adapters[i] = data) : S.adapters.push(data);
      log("adapter", `${data.hci} powered=${data.powered} discoverable=${data.discoverable} pairable=${data.pairable}`);
      break;
    }
    case "device": {
      S.pending.delete(data.mac);
      const i = S.devices.findIndex((d) => d.mac === data.mac);
      i >= 0 ? (S.devices[i] = data) : S.devices.push(data);
      log("device", `${ROLES[data.adapter]?.hci ?? data.adapter}  ${label(data)}  ${data.connected ? "connecté" : "déconnecté"}${data.paired ? ", appairé" : ""}`);
      break;
    }
    case "device.removed": {
      S.pending.delete(data.mac);
      S.devices = S.devices.filter((d) => d.mac !== data.mac);
      log("device", `${ROLES[data.adapter]?.hci ?? data.adapter}  ${data.mac}  retiré`);
      break;
    }
    case "state": // état complet (Last-Event-ID hors tampon serveur)
      S.version = data.version; S.adapters = data.adapters; S.devices = data.devices;
      applyControllers(data);
      setPairing(data.pairing);
      log("state", "état complet resynchronisé");
      if (S.pairing && S.pairing.adapter === "headsets") refresh();
      break;
    case "pairing":
      setPairing(data);
      log("pairing", S.pairing ? `${ROLES[S.pairing.adapter].hci} fenêtre ouverte (${S.pairing.remaining_s} s)`
        : `fenêtre fermée${data && data.reason ? ` (${data.reason})` : ""}`);
      break;
    case "discovered": {
      const i = S.discovered.findIndex((x) => x.mac === data.mac);
      i >= 0 ? (S.discovered[i] = data) : S.discovered.push(data);
      log("discovered", `${data.name || data.mac}  ${data.rssi} dBm`);
      break;
    }
    default: return;
  }
  render();
}

// ---------- flux : SSE + repli polling ----------
function startPolling() { if (!pollTimer) pollTimer = setInterval(refresh, POLL_MS); }
function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

function startLive() {
  stopLive();
  refresh();
  tickTimer = setInterval(tick, 1000);
  events = openEvents({
    onEvent,
    onAuth: askToken,
    onState: (up) => {
      const changed = S.live !== up;
      S.live = up;
      if (up) { stopPolling(); if (changed) refresh(); } // resynchronisation après (re)connexion
      else startPolling();
      if (changed) { log("flux", up ? "SSE connecté" : "SSE interrompu — repli polling 5 s"); render(); }
      setStatus(up ? "ok" : "warn", statusText());
    },
  });
  startPolling(); // jusqu'à la 1re connexion SSE
}
function stopLive() {
  if (events) events.close();
  events = null; S.live = false; stopPolling(); clearInterval(tickTimer);
}

// ---------- init ----------
$("token").value = getToken();
$("token-form").addEventListener("submit", (e) => {
  e.preventDefault();
  setToken($("token").value.trim());
  S.errors = []; renderErrors();
  startLive();
});
render();
renderErrors();
if (getToken()) startLive(); else askToken();
