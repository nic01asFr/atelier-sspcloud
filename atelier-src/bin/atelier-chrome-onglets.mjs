// atelier-chrome-onglets.mjs — le filtre du navigateur d'une conversation.
//
//   node atelier-chrome-onglets.mjs <commande> [arguments…]
//
// Lancé par atelier-chrome entre le client MCP (le CLI d'une conversation) et
// chrome-devtools-mcp, en stdio. Il relaie chaque ligne JSON-RPC telle quelle,
// et tient trois choses que ni le client ni le serveur ne savent tenir.
//
// 1. Le plafond d'onglets. Un `tools/call` de `new_page` quand la conversation
//    a déjà ATELIER_CHROME_ONGLETS_MAX onglets (défaut 8 ; 0 = pas de plafond)
//    reçoit du filtre lui-même une erreur d'outil que l'agent lit (« ferme un
//    onglet »), et le serveur ne reçoit rien. Le compte vient du serveur :
//    avant de laisser passer un `new_page`, le filtre lui demande `list_pages`
//    et compte les lignes de sa section « ## Pages ». Les pages ouvertes par
//    un site (fenêtre surgissante) sont donc comptées. Si le serveur ne répond
//    pas dans le délai, ou dans une forme que le filtre ne sait pas lire, il
//    se fie au dernier compte vu ; sans compte du tout, il laisse passer. Ce
//    plafond protège la mémoire du pod ; ce n'est pas une frontière de
//    sécurité.
//
// 2. L'écran (docs/navigateur-atelier.md, « Écran en direct »). Quand le
//    lanceur lui donne une conversation (ATELIER_CHROME_CONVERSATION), le
//    dossier des navigateurs (ATELIER_CHROME_RACINE) et le profil de Chrome
//    (ATELIER_CHROME_PROFIL), il publie dans
//    <racine>/ecrans/<conversation>.json, en 0600, ce que l'Atelier doit
//    savoir pour montrer ce navigateur : le port de débogage que Chrome a
//    écrit dans <profil>/DevToolsActivePort (Chrome ne l'ouvre que sur
//    127.0.0.1), la page que l'agent a sélectionnée (lue dans la section
//    « ## Pages » des réponses du serveur, ligne « [selected] »), et le
//    nombre d'actions de l'agent en attente. Le fichier disparaît quand le
//    filtre s'arrête.
//
// 3. La main de la personne. Tant que <racine>/main/<conversation>.json dit
//    `{"prise": true}` (écrit par l'Atelier sur « Prendre la main »), tout
//    `tools/call` de l'agent attend ici : il ne touche pas au navigateur que
//    la personne manipule. Quand elle rend la main (`{"prise": false,
//    "note": "…"}`), les appels retenus repartent dans l'ordre, et la note —
//    ce qui a changé — est ajoutée au résultat du premier : l'agent l'apprend
//    à l'endroit même où il reprend. Sans appel retenu, la note attend le
//    prochain appel. Au-delà de ATELIER_CHROME_MAIN_MAX_S (défaut 1800 s),
//    les appels retenus reçoivent une erreur qui dit à l'agent de demander où
//    en est la personne.
//
// Les messages du client qui arrivent pendant la vérification d'un
// `new_page` attendent leur tour : l'ordre des appels est gardé.

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const PREFIXE = "atelier-onglets-";
const DELAI_MS = Number(process.env.ATELIER_CHROME_ONGLETS_DELAI_MS || 15000);
const brut = process.env.ATELIER_CHROME_ONGLETS_MAX;
const MAX = brut === undefined || brut === "" ? 8 : Number.parseInt(brut, 10);
const PLAFOND = Number.isFinite(MAX) && MAX > 0 ? MAX : 0;

const CONVERSATION = process.env.ATELIER_CHROME_CONVERSATION || "";
const RACINE = process.env.ATELIER_CHROME_RACINE || "";
const PROFIL = process.env.ATELIER_CHROME_PROFIL || "";
const FORME_CONVERSATION = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/;
const ECRAN = !!(RACINE && PROFIL && FORME_CONVERSATION.test(CONVERSATION));
const INTERVALLE_MS = Number(process.env.ATELIER_CHROME_ECRAN_INTERVALLE_MS || 1000);
const MAIN_INTERVALLE_MS = Number(process.env.ATELIER_CHROME_MAIN_INTERVALLE_MS || 500);
const MAIN_MAX_MS = Number(process.env.ATELIER_CHROME_MAIN_MAX_S || 1800) * 1000;

const [commande, ...argumentsServeur] = process.argv.slice(2);
if (!commande) {
  process.stderr.write("atelier-chrome-onglets : commande du serveur manquante\n");
  process.exit(2);
}

// ── État partagé ──────────────────────────────────────────────────────────

let compteVu = null; // dernier nombre d'onglets lu dans une réponse du serveur
let suivant = 0;
let enAttente = null; // { idInterne, ligne, id, minuterie }
const retenus = []; // lignes du client arrivées pendant une vérification
let clientFini = false;

const etat = { port: 0, chemin: "", page: null, attente: 0 };
let empreinteEcrite = "";
let brutDuPort = "";

const tenus = []; // appels retenus pendant que la personne a la main : { ligne, id, depuis }
let minuterieMain = null;
const notes = new Map(); // id d'appel du client (JSON) -> note à ajouter à sa réponse
let noteEnReserve = ""; // une note rendue sans appel retenu : pour le prochain appel

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
  retirerLEtat();
  // Laisser la sortie se vider avant de partir.
  setImmediate(() => process.exit(process.exitCode));
});
process.on("exit", retirerLEtat);

function versServeur(ligne) {
  serveur.stdin.write(ligne + "\n");
}

function versClient(objet) {
  process.stdout.write(JSON.stringify(objet) + "\n");
}

// ── Lecture des réponses du serveur ───────────────────────────────────────

function textesDe(resultat) {
  const blocs = resultat && Array.isArray(resultat.content) ? resultat.content : [];
  return blocs
    .filter((b) => b && b.type === "text" && typeof b.text === "string")
    .map((b) => b.text)
    .join("\n");
}

// Les lignes de la section « ## Pages » d'une réponse d'outil, ou null si
// elle n'en a pas.
function lignesDesPages(resultat) {
  const lignes = textesDe(resultat).split(/\r?\n/);
  const debut = lignes.findIndex((l) => /^#+\s*Pages\b/i.test(l.trim()));
  if (debut < 0) return null;
  const pages = [];
  for (const ligne of lignes.slice(debut + 1)) {
    const l = ligne.trim();
    if (l.startsWith("#")) break;
    if (/^\d+\s*:/.test(l)) pages.push(l);
  }
  return pages;
}

// Le nombre d'onglets d'une réponse d'outil, ou null si elle n'en dit rien.
function compterLesOnglets(resultat) {
  const pages = lignesDesPages(resultat);
  return pages === null ? null : pages.length;
}

// Une ligne de page, telle que l'écrit chrome-devtools-mcp 1.10.1 :
//   `<id>: <titre> (<adresse>) [selected] isolatedContext=<nom>`
// le titre et les deux suffixes étant facultatifs.
function lirePage(ligne) {
  const m = /^(\d+)\s*:\s*(.*)$/.exec(ligne.trim());
  if (!m) return null;
  let reste = m[2].replace(/\s+isolatedContext=\S+$/, "");
  const selectionnee = / \[selected\]$/.test(reste);
  if (selectionnee) reste = reste.slice(0, -" [selected]".length);
  let titre = "";
  let url = reste;
  if (reste.endsWith(")")) {
    const ouvre = reste.lastIndexOf(" (");
    const dedans = ouvre >= 0 ? reste.slice(ouvre + 2, -1) : "";
    if (/^[a-z][a-z0-9+.-]*:/i.test(dedans)) {
      titre = reste.slice(0, ouvre);
      url = dedans;
    }
  }
  return { id: Number(m[1]), url, titre, selectionnee };
}

// La page sélectionnée d'une réponse ; null si la liste n'en marque aucune,
// undefined si la réponse ne liste pas les pages.
function pageSelectionnee(resultat) {
  const pages = lignesDesPages(resultat);
  if (!pages) return undefined;
  for (const ligne of pages) {
    const page = lirePage(ligne);
    if (page && page.selectionnee) return { id: page.id, url: page.url, titre: page.titre };
  }
  return null;
}

// ── L'écran : ce que l'Atelier doit savoir pour montrer ce navigateur ──────

function cheminEtat() {
  return join(RACINE, "ecrans", `${CONVERSATION}.json`);
}

function cheminMain() {
  return join(RACINE, "main", `${CONVERSATION}.json`);
}

function publier() {
  if (!ECRAN || !etat.port) return;
  const fiche = {
    version: 1,
    conversation: CONVERSATION,
    pid: process.pid,
    port: etat.port,
    chemin: etat.chemin,
    page: etat.page,
    attente: etat.attente,
  };
  const empreinte = JSON.stringify(fiche);
  if (empreinte === empreinteEcrite) return;
  try {
    mkdirSync(join(RACINE, "ecrans"), { recursive: true, mode: 0o700 });
    const provisoire = `${cheminEtat()}.${process.pid}.tmp`;
    writeFileSync(provisoire, JSON.stringify({ ...fiche, maj: new Date().toISOString() }) + "\n", {
      mode: 0o600,
    });
    renameSync(provisoire, cheminEtat());
    empreinteEcrite = empreinte;
  } catch (err) {
    process.stderr.write(`atelier-chrome-onglets : état de l'écran non écrit (${err.code || err.message})\n`);
  }
}

function retirerLEtat() {
  if (!ECRAN || !empreinteEcrite) return;
  try {
    const lu = JSON.parse(readFileSync(cheminEtat(), "utf8"));
    // Un autre processus de la même conversation a pu reprendre la fiche.
    if (lu && lu.pid === process.pid) rmSync(cheminEtat(), { force: true });
  } catch {
    // déjà partie
  }
  empreinteEcrite = "";
}

// Chrome écrit son port dans le profil dès qu'il écoute : deux lignes, le port
// et le chemin du point d'entrée du navigateur. Il n'y a rien avant le premier
// outil qui lance Chrome.
function lireLePort() {
  let contenu = "";
  try {
    contenu = readFileSync(join(PROFIL, "DevToolsActivePort"), "utf8");
  } catch {
    return;
  }
  if (contenu === brutDuPort) return;
  const [port, chemin] = contenu.trim().split(/\r?\n/);
  const n = Number.parseInt(port, 10);
  if (!(n > 0 && n < 65536) || !/^\/devtools\/browser\/[A-Za-z0-9-]{1,80}$/.test(chemin || "")) return;
  brutDuPort = contenu;
  etat.port = n;
  etat.chemin = chemin;
  publier();
}

if (ECRAN) {
  setInterval(lireLePort, INTERVALLE_MS).unref();
}

function notePage(resultat) {
  if (!ECRAN) return;
  const page = pageSelectionnee(resultat);
  if (page === undefined) return;
  etat.page = page;
  lireLePort();
  publier();
}

// ── La main de la personne ────────────────────────────────────────────────

// `oubliee` : une main prise depuis plus longtemps que le plafond est une
// main oubliée (Atelier redémarré, page fermée) ; un nouvel appel de l'agent
// ne l'attend pas. Les appels déjà retenus, eux, reçoivent l'erreur du plafond.
function lireLaMain({ oubliee = false } = {}) {
  if (!ECRAN) return null;
  try {
    const lu = JSON.parse(readFileSync(cheminMain(), "utf8"));
    if (!lu || typeof lu !== "object") return null;
    if (!oubliee && lu.prise === true && typeof lu.depuis === "number" && Date.now() - lu.depuis > MAIN_MAX_MS) {
      return null;
    }
    return lu;
  } catch {
    return null;
  }
}

// La note d'une reprise ne sert qu'une fois : le fichier part avec elle.
function consommerLaNote(main) {
  if (!main || main.prise === true || typeof main.note !== "string" || !main.note.trim()) return "";
  try {
    rmSync(cheminMain(), { force: true });
  } catch {
    // l'Atelier l'a peut-être déjà retirée
  }
  return main.note.trim().slice(0, 4000);
}

function ajouterLaNote(resultat, note) {
  if (!note || !resultat || typeof resultat !== "object") return resultat;
  const contenu = Array.isArray(resultat.content) ? resultat.content : [];
  return { ...resultat, content: [...contenu, { type: "text", text: note }] };
}

function direLAttente() {
  etat.attente = tenus.length;
  publier();
}

function refuserLesTropVieux() {
  const maintenant = Date.now();
  while (tenus.length && maintenant - tenus[0].depuis > MAIN_MAX_MS) {
    const { id } = tenus.shift();
    versClient({
      jsonrpc: "2.0",
      id,
      result: {
        content: [
          {
            type: "text",
            text:
              "La personne a pris la main sur ton navigateur et la garde depuis longtemps : cette " +
              "action n'a pas été faite. N'agis plus sur le navigateur ; demande-lui où elle en est.",
          },
        ],
        isError: true,
      },
    });
  }
}

function surveillerLaMain() {
  if (minuterieMain) return;
  minuterieMain = setInterval(() => {
    const main = lireLaMain({ oubliee: true });
    if (main && main.prise === true) {
      refuserLesTropVieux();
      direLAttente();
      if (tenus.length) return;
      clearInterval(minuterieMain);
      minuterieMain = null;
      return;
    }
    clearInterval(minuterieMain);
    minuterieMain = null;
    // Rendue : les appels retenus repartent, dans l'ordre ; le premier porte la note.
    const note = consommerLaNote(main);
    const liberes = tenus.splice(0, tenus.length);
    direLAttente();
    if (liberes.length && note) notes.set(JSON.stringify(liberes[0].id), note);
    else if (note) noteEnReserve = note;
    for (const { ligne } of liberes) traiterDuClient(ligne, { dejaTenu: true });
  }, MAIN_INTERVALLE_MS);
}

// Un appel d'outil pendant que la personne a la main : il attend. Sinon, s'il
// reste une note de la dernière reprise, elle part avec lui.
function tenirSiLaMainEstPrise(recu, ligne) {
  if (!ECRAN || !recu || recu.method !== "tools/call" || recu.id === undefined) return false;
  const main = lireLaMain();
  if (main && main.prise === true) {
    tenus.push({ ligne, id: recu.id, depuis: Date.now() });
    direLAttente();
    surveillerLaMain();
    return true;
  }
  const note = consommerLaNote(main) || noteEnReserve;
  noteEnReserve = "";
  if (note) notes.set(JSON.stringify(recu.id), note);
  return false;
}

// ── Le plafond d'onglets ──────────────────────────────────────────────────

function messageDuPlafond(ouverts) {
  return (
    `Plafond d'onglets atteint : ${ouverts} onglets ouverts dans le navigateur de cette ` +
    `conversation, pour ${PLAFOND} permis (ATELIER_CHROME_ONGLETS_MAX). Ferme un onglet ` +
    `avec close_page avant d'en ouvrir un autre, ou réutilise-en un avec navigate_page.`
  );
}

function finirSiToutEstParti() {
  if (clientFini && !enAttente && !retenus.length) {
    // Le client parti, personne n'attend plus les appels retenus.
    tenus.splice(0, tenus.length);
    serveur.stdin.end();
  }
}

function trancher(ouverts) {
  const { ligne, id, minuterie } = enAttente;
  clearTimeout(minuterie);
  enAttente = null;
  if (ouverts !== null && ouverts >= PLAFOND) {
    process.stderr.write(`atelier-chrome-onglets : new_page refusé (${ouverts}/${PLAFOND})\n`);
    const cle = JSON.stringify(id);
    const note = notes.get(cle) || "";
    notes.delete(cle);
    versClient({
      jsonrpc: "2.0",
      id,
      result: ajouterLaNote({ content: [{ type: "text", text: messageDuPlafond(ouverts) }], isError: true }, note),
    });
  } else {
    versServeur(ligne);
  }
  // Ce qui attendait repart, dans l'ordre ; un autre new_page peut suspendre à nouveau.
  while (retenus.length && !enAttente) traiterDuClient(retenus.shift());
  finirSiToutEstParti();
}

function traiterDuClient(ligne, { dejaTenu = false } = {}) {
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
  const objet = recu && !Array.isArray(recu) ? recu : null;
  if (objet && objet.method === "notifications/cancelled") {
    // Un appel retenu que le client abandonne ne partira pas.
    const annule = objet.params && objet.params.requestId;
    const i = tenus.findIndex((t) => t.id === annule);
    if (i >= 0) {
      tenus.splice(i, 1);
      direLAttente();
    }
  }
  if (!dejaTenu && objet && tenirSiLaMainEstPrise(objet, ligne)) return;
  const estNouvelOnglet =
    PLAFOND > 0 &&
    objet &&
    objet.method === "tools/call" &&
    objet.id !== undefined &&
    objet.params &&
    objet.params.name === "new_page";
  if (!estNouvelOnglet) {
    versServeur(ligne);
    return;
  }
  suivant += 1;
  const idInterne = `${PREFIXE}${suivant}`;
  enAttente = {
    idInterne,
    ligne,
    id: objet.id,
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
    if (recu.result && !recu.result.isError) notePage(recu.result);
    if (enAttente && enAttente.idInterne === recu.id) trancher(compte ?? compteVu);
    return;
  }
  if (recu && recu.result) {
    const compte = compterLesOnglets(recu.result);
    if (compte !== null) compteVu = compte;
    notePage(recu.result);
  }
  if (recu && recu.id !== undefined && notes.size) {
    const cle = JSON.stringify(recu.id);
    const note = notes.get(cle);
    if (note !== undefined) {
      notes.delete(cle);
      if (recu.result) {
        versClient({ ...recu, result: ajouterLaNote(recu.result, note) });
        return;
      }
      // Une erreur de protocole : la note attend l'appel suivant.
      noteEnReserve = note;
    }
  }
  process.stdout.write(ligne + "\n");
}

createInterface({ input: serveur.stdout, crlfDelay: Infinity }).on("line", traiterDuServeur);
const client = createInterface({ input: process.stdin, crlfDelay: Infinity });
client.on("line", (ligne) => traiterDuClient(ligne));
client.on("close", () => {
  clientFini = true;
  finirSiToutEstParti();
});
