// atelier-chrome-onglets.mjs — plafond d'onglets du navigateur d'une conversation.
//
//   node atelier-chrome-onglets.mjs <commande> [arguments…]
//
// Lancé par atelier-chrome entre le client MCP (le CLI d'une conversation) et
// chrome-devtools-mcp, en stdio. Il relaie chaque ligne JSON-RPC telle quelle,
// sauf une : un `tools/call` de `new_page` quand la conversation a déjà
// ATELIER_CHROME_ONGLETS_MAX onglets (défaut 8 ; 0 = pas de plafond). Il rend
// alors lui-même une erreur d'outil que l'agent lit (« ferme un onglet »),
// et le serveur ne reçoit rien.
//
// Le compte vient du serveur : avant de laisser passer un `new_page`, le
// filtre lui demande `list_pages` et compte les lignes de sa section
// « ## Pages ». Les pages ouvertes par un site (fenêtre surgissante) sont donc
// comptées. Si le serveur ne répond pas dans le délai, ou dans une forme que
// le filtre ne sait pas lire, il se fie au dernier compte vu dans une réponse
// du serveur ; sans compte du tout, il laisse passer. Ce plafond protège la
// mémoire du pod ; ce n'est pas une frontière de sécurité.
//
// Les messages du client qui arrivent pendant la vérification attendent leur
// tour : l'ordre des appels est gardé.

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const PREFIXE = "atelier-onglets-";
const DELAI_MS = Number(process.env.ATELIER_CHROME_ONGLETS_DELAI_MS || 15000);
const brut = process.env.ATELIER_CHROME_ONGLETS_MAX;
const MAX = brut === undefined || brut === "" ? 8 : Number.parseInt(brut, 10);
const PLAFOND = Number.isFinite(MAX) && MAX > 0 ? MAX : 0;

const [commande, ...argumentsServeur] = process.argv.slice(2);
if (!commande) {
  process.stderr.write("atelier-chrome-onglets : commande du serveur manquante\n");
  process.exit(2);
}

const serveur = spawn(commande, argumentsServeur, { stdio: ["pipe", "pipe", "inherit"] });
serveur.on("error", (err) => {
  process.stderr.write(`atelier-chrome-onglets : ${err.message}\n`);
  process.exit(127);
});
serveur.stdin.on("error", () => {});
process.stdout.on("error", () => {});

for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"]) {
  process.on(signal, () => {
    try {
      serveur.kill(signal);
    } catch {
      // déjà parti
    }
  });
}
serveur.on("exit", (code, signal) => {
  process.exitCode = code ?? (signal ? 128 : 1);
  // Laisser la sortie se vider avant de partir.
  setImmediate(() => process.exit(process.exitCode));
});

let compteVu = null; // dernier nombre d'onglets lu dans une réponse du serveur
let suivant = 0;
let enAttente = null; // { idInterne, ligne, id, minuterie }
const retenus = []; // lignes du client arrivées pendant une vérification
let clientFini = false;

function versServeur(ligne) {
  serveur.stdin.write(ligne + "\n");
}

function versClient(objet) {
  process.stdout.write(JSON.stringify(objet) + "\n");
}

// Le nombre d'onglets d'une réponse d'outil, ou null si elle n'en dit rien.
function compterLesOnglets(resultat) {
  const blocs = resultat && Array.isArray(resultat.content) ? resultat.content : [];
  const texte = blocs
    .filter((b) => b && b.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("\n");
  const lignes = texte.split(/\r?\n/);
  const debut = lignes.findIndex((l) => /^#+\s*Pages\b/i.test(l.trim()));
  if (debut < 0) return null;
  let n = 0;
  for (const ligne of lignes.slice(debut + 1)) {
    const l = ligne.trim();
    if (l.startsWith("#")) break;
    if (/^\d+\s*:/.test(l)) n += 1;
  }
  return n;
}

function messageDuPlafond(ouverts) {
  return (
    `Plafond d'onglets atteint : ${ouverts} onglets ouverts dans le navigateur de cette ` +
    `conversation, pour ${PLAFOND} permis (ATELIER_CHROME_ONGLETS_MAX). Ferme un onglet ` +
    `avec close_page avant d'en ouvrir un autre, ou réutilise-en un avec navigate_page.`
  );
}

function trancher(ouverts) {
  const { ligne, id, minuterie } = enAttente;
  clearTimeout(minuterie);
  enAttente = null;
  if (ouverts !== null && ouverts >= PLAFOND) {
    process.stderr.write(`atelier-chrome-onglets : new_page refusé (${ouverts}/${PLAFOND})\n`);
    versClient({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: messageDuPlafond(ouverts) }], isError: true } });
  } else {
    versServeur(ligne);
  }
  // Ce qui attendait repart, dans l'ordre ; un autre new_page peut suspendre à nouveau.
  while (retenus.length && !enAttente) traiterDuClient(retenus.shift());
  if (clientFini && !enAttente && !retenus.length) serveur.stdin.end();
}

function traiterDuClient(ligne) {
  if (enAttente) {
    retenus.push(ligne);
    return;
  }
  let recu = null;
  try {
    recu = JSON.parse(ligne);
  } catch {
    // pas du JSON : on relaie tel quel, le serveur répondra
  }
  const estNouvelOnglet =
    PLAFOND > 0 &&
    recu &&
    !Array.isArray(recu) &&
    recu.method === "tools/call" &&
    recu.id !== undefined &&
    recu.params &&
    recu.params.name === "new_page";
  if (!estNouvelOnglet) {
    versServeur(ligne);
    return;
  }
  suivant += 1;
  const idInterne = `${PREFIXE}${suivant}`;
  enAttente = {
    idInterne,
    ligne,
    id: recu.id,
    minuterie: setTimeout(() => {
      if (enAttente && enAttente.idInterne === idInterne) trancher(compteVu);
    }, DELAI_MS),
  };
  versServeur(
    JSON.stringify({
      jsonrpc: "2.0",
      id: idInterne,
      method: "tools/call",
      params: { name: "list_pages", arguments: {} },
    })
  );
}

function traiterDuServeur(ligne) {
  let recu = null;
  try {
    recu = JSON.parse(ligne);
  } catch {
    process.stdout.write(ligne + "\n");
    return;
  }
  if (recu && typeof recu.id === "string" && recu.id.startsWith(PREFIXE)) {
    // Réponse à notre propre question : elle ne va pas au client.
    const compte = recu.result && !recu.result.isError ? compterLesOnglets(recu.result) : null;
    if (compte !== null) compteVu = compte;
    if (enAttente && enAttente.idInterne === recu.id) trancher(compte ?? compteVu);
    return;
  }
  if (recu && recu.result) {
    const compte = compterLesOnglets(recu.result);
    if (compte !== null) compteVu = compte;
  }
  process.stdout.write(ligne + "\n");
}

createInterface({ input: serveur.stdout, crlfDelay: Infinity }).on("line", traiterDuServeur);
const client = createInterface({ input: process.stdin, crlfDelay: Infinity });
client.on("line", traiterDuClient);
client.on("close", () => {
  clientFini = true;
  if (!enAttente && !retenus.length) serveur.stdin.end();
});
