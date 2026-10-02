// L'extension `atelier-ouvre-claude` : ouvrir la conversation que l'Atelier vient de confier.
//
// Ce qu'elle doit tenir (« VS Code ouvre toujours la conversation courante ») :
//   - une consigne fraîche ouvre cette conversation-là, après avoir fermé les
//     panneaux Claude que VS Code vient de restituer (restitués, ils reviennent vides) ;
//   - la consigne est lue puis supprimée : elle vaut pour une ouverture ;
//   - une consigne ancienne, ou sans date, est jetée sans rien ouvrir : un dossier
//     qui la garde depuis hier ne doit pas rouvrir la conversation d'hier ;
//   - sans consigne, elle ne touche à rien.
// `vscode` n'existe que dans code-server : on le remplace par un faux.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Module, { createRequire } from "node:module";

import { bilan, egal, verifier } from "./verifier.mjs";

const require = createRequire(import.meta.url);
const COMMANDE = "claude-vscode.primaryEditor.open";

function fauxVscode(dossier, { onglets = [] } = {}) {
  const journal = [];
  return {
    journal,
    api: {
      workspace: { workspaceFolders: dossier ? [{ uri: { fsPath: dossier } }] : [] },
      commands: {
        getCommands: async () => [COMMANDE],
        executeCommand: async (nom, ...args) => journal.push(["commande", nom, ...args]),
      },
      window: {
        tabGroups: {
          all: [{ tabs: onglets }],
          close: async (tabs) => journal.push(["fermer", tabs.length]),
        },
      },
    },
  };
}

const charger = Module._load;
async function jouer(dossier, options) {
  const faux = fauxVscode(dossier, options);
  Module._load = function (demande, ...reste) {
    return demande === "vscode" ? faux.api : charger.call(this, demande, ...reste);
  };
  const chemin = require.resolve("../../vscode-extension/atelier-ouvre-claude/extension.js");
  delete require.cache[chemin];
  try {
    await require(chemin).activate();
  } finally {
    Module._load = charger;
  }
  return faux.journal;
}

function projet(consigne) {
  const dossier = fs.mkdtempSync(path.join(os.tmpdir(), "ext-"));
  fs.mkdirSync(path.join(dossier, ".atelier"));
  if (consigne !== undefined) {
    fs.writeFileSync(path.join(dossier, ".atelier", "session.json"), JSON.stringify(consigne));
  }
  return dossier;
}
const marque = (dossier) => path.join(dossier, ".atelier", "session.json");
const maintenant = () => Math.floor(Date.now() / 1000);

// ── Une consigne fraîche ouvre la conversation, une seule fois ───────────
{
  const dossier = projet({ session_id: "conv-courante", slug: "demo", ecrit_le: maintenant() });
  const restitue = { input: { viewType: "mainThreadWebview-claudeVSCodePanel" } };
  const journal = await jouer(dossier, { onglets: [restitue] });
  egal(journal, [["fermer", 1], ["commande", COMMANDE, "conv-courante"]], "ferme le restitué, puis ouvre la conversation");
  verifier(!fs.existsSync(marque(dossier)), "la consigne est reprise : elle ne vaut qu'une ouverture");
  egal(await jouer(dossier), [], "au rechargement suivant, rien : la dernière conversation confiée ne revient pas");
}

// ── Une consigne ancienne, ou sans date, ne rouvre pas la conversation d'hier ──
{
  const hier = projet({ session_id: "conv-d-hier", ecrit_le: maintenant() - 24 * 3600 });
  egal(await jouer(hier), [], "une consigne de la veille n'ouvre rien");
  verifier(!fs.existsSync(marque(hier)), "et elle est jetée");

  const sansDate = projet({ session_id: "conv-ancienne", slug: "demo" });
  egal(await jouer(sansDate), [], "sans date (version qui ne la posait pas) : jetée aussi");
  verifier(!fs.existsSync(marque(sansDate)), "et supprimée");

  const futur = projet({ session_id: "conv-futur", ecrit_le: maintenant() + 3600 });
  egal(await jouer(futur), [], "une date dans le futur n'est pas une consigne fraîche");
}

// ── Le délai, au bord ────────────────────────────────────────────────────
{
  const { consigneFraiche, DUREE_DE_LA_CONSIGNE_S } = require("../../vscode-extension/atelier-ouvre-claude/extension.js");
  const t = 1_000_000;
  verifier(consigneFraiche(t, t * 1000), "à l'instant : fraîche");
  verifier(consigneFraiche(t - DUREE_DE_LA_CONSIGNE_S + 1, t * 1000), "juste avant le délai : fraîche");
  verifier(!consigneFraiche(t - DUREE_DE_LA_CONSIGNE_S - 1, t * 1000), "juste après : périmée");
  verifier(!consigneFraiche(NaN, t * 1000), "pas de date : périmée");
}

// ── Sans consigne, on ne touche à rien ───────────────────────────────────
{
  const restitue = { input: { viewType: "mainThreadWebview-claudeVSCodePanel" } };
  egal(await jouer(projet(), { onglets: [restitue] }), [], "sans consigne : ni fermeture ni ouverture");
  egal(await jouer(null), [], "sans dossier ouvert : rien");
  const abime = projet();
  fs.writeFileSync(marque(abime), "{pas du json");
  egal(await jouer(abime), [], "une consigne illisible n'ouvre rien");
}

bilan("extension-vscode");
