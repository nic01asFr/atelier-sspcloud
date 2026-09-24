// La clé propriétaire ne vit plus dans le navigateur.
//
// L'interface la gardait dans `localStorage["atelier.ownerKey"]`. Le script de
// n'importe quelle page servie dans l'origine de l'Atelier — un corpus déposé
// par un agent l'était — la lisait là, et la clé ouvre tout : le harnais lance
// `claude` en `bypassPermissions`.
//
// Ce que cette suite tient :
//   - l'état de départ ne lit ni n'écrit la clé ;
//   - se connecter l'échange une fois contre le cookie, et rien n'en reste ;
//   - une clé laissée par une version précédente est échangée puis effacée,
//     même si elle ne vaut plus rien ;
//   - les appels à l'API ne portent plus d'en-tête `Authorization`, mais
//     l'en-tête de l'interface que le service exige avec le cookie.

import { bilan, egal, verifier } from "./verifier.mjs";

// Un stockage qu'on peut inspecter après coup.
const stock = new Map();
globalThis.localStorage = {
  getItem: (k) => (stock.has(k) ? stock.get(k) : null),
  setItem: (k, v) => stock.set(k, String(v)),
  removeItem: (k) => stock.delete(k),
};
globalThis.sessionStorage = globalThis.localStorage;

// Ce que l'interface envoie, et ce que le service répond.
const envois = [];
let reponse = { status: 200, body: { status: "ok" } };
globalThis.fetch = async (url, init = {}) => {
  envois.push({ url, init });
  return {
    ok: reponse.status < 400,
    status: reponse.status,
    statusText: "",
    json: async () => reponse.body,
  };
};

const S = await import("../../mcp_gateway/atelier/web/js/state.js");
const api = await import("../../mcp_gateway/atelier/web/js/api.js");

function entetes(envoi) {
  return envoi.init.headers || {};
}

// ── l'état de départ ne touche pas à la clé ──
stock.set("atelier.ownerKey", "cle-d-hier");
const state = S.createState();
egal(state.token, "", "l'état de départ ne reprend pas la clé stockée");
S.setToken(state, "une-cle-quelconque");
egal(state.token, S.SESSION_OUVERTE, "l'état ne garde qu'un marqueur de session");
verifier(
  !Array.from(stock.values()).includes("une-cle-quelconque"),
  "se déclarer connecté n'écrit aucune clé dans le stockage"
);

// ── migration : échange puis effacement ──
envois.length = 0;
const migree = await api.migrerAncienneCle(S.lireAncienneCle, S.oublierAncienneCle);
verifier(migree, "l'ancienne clé ouvre une session");
egal(envois.length, 1, "un seul appel pour l'échange");
egal(envois[0].url, "/v1/auth/cookie", "l'échange passe par /v1/auth/cookie");
egal(entetes(envois[0]).Authorization, "Bearer cle-d-hier", "l'échange porte la clé, une fois");
egal(S.lireAncienneCle(), "", "la clé est effacée après l'échange");
verifier(!stock.has("atelier.ownerKey"), "plus rien sous l'ancien nom");

// Une clé qui ne vaut plus rien est effacée quand même.
stock.set("atelier.ownerKey", "cle-perimee");
reponse = { status: 401, body: { detail: "Bearer owner key required" } };
envois.length = 0;
const refusee = await api.migrerAncienneCle(S.lireAncienneCle, S.oublierAncienneCle);
verifier(!refusee, "une clé refusée n'ouvre rien");
verifier(!stock.has("atelier.ownerKey"), "une clé refusée est effacée aussi");

// Sans ancienne clé, aucun appel.
envois.length = 0;
await api.migrerAncienneCle(S.lireAncienneCle, S.oublierAncienneCle);
egal(envois.length, 0, "rien à migrer, rien d'envoyé");

// ── les appels à l'API ──
reponse = { status: 200, body: { sessions: [] } };
envois.length = 0;
await api.listSessions("session");
await api.getMeta("session");
await api.createSession("session", { slug: "x" });
for (const e of envois) {
  verifier(!("Authorization" in entetes(e)), `${e.url} ne porte pas d'Authorization`);
  egal(entetes(e)["X-Atelier-Interface"], "1", `${e.url} porte l'en-tête de l'interface`);
}

// ── rien dans le code de l'interface n'écrit la clé ──
const { readFile, readdir } = await import("node:fs/promises");
const { join } = await import("node:path");
async function fichiers(dossier) {
  const sortie = [];
  for (const e of await readdir(dossier, { withFileTypes: true })) {
    const p = join(dossier, e.name);
    if (e.isDirectory()) sortie.push(...(await fichiers(p)));
    else if (e.name.endsWith(".js")) sortie.push(p);
  }
  return sortie;
}
for (const f of await fichiers("mcp_gateway/atelier/web/js")) {
  const texte = await readFile(f, "utf-8");
  verifier(
    !/setItem\([^)]*(KEY_OWNER|ownerKey)/.test(texte),
    `${f} n'écrit pas la clé dans le stockage`
  );
}

bilan("cle-hors-navigateur");
