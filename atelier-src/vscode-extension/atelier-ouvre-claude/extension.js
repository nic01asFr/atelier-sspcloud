// Ouvre l'extension Claude Code sur la conversation qu'on lisait dans
// l'Atelier.
//
// Rien d'autre ne peut le faire. Le reglage `claudeCode.preferredLocation`
// dit ou Claude s'ouvre, pas qu'il s'ouvre ; les parametres d'URL de
// code-server ne savent qu'ouvrir des fichiers ; et le CLI distant, sollicite
// depuis un terminal, se contente de passer l'adresse au navigateur, qui ne
// connait pas le schema `vscode:` et laisse un onglet vide.
//
// Reste la commande que l'extension enregistre elle-meme. Elle prend
// l'identifiant de la conversation en premier argument : sans lui, elle en
// ouvre une neuve — c'est l'onglet vide qu'on voyait s'empiler par-dessus
// celui que VS Code venait de restaurer.
//
// L'identifiant est ecrit par l'Atelier dans le projet, au moment ou il
// passe la main (voir vscode_handoff.py).

const vscode = require("vscode");
const fs = require("fs");
const path = require("path");

const COMMANDE = "claude-vscode.primaryEditor.open";
const MARQUE = path.join(".atelier", "session.json");
// Le temps qu'une consigne reste valable : de quoi laisser code-server demarrer
// a froid (extensions, fenetre), pas de quoi rouvrir la conversation d'hier.
const DUREE_DE_LA_CONSIGNE_S = 30 * 60;

// L'Atelier depose la conversation qu'il confie, et on la reprend : le
// fichier vaut pour cette ouverture-la, pas pour toutes les suivantes. Le
// laisser en place ferait rouvrir la derniere conversation confiee a chaque
// rechargement de VS Code, en fermant celle sur laquelle on travaillait.
function reprendreConversationConfiee() {
  const dossier = (vscode.workspace.workspaceFolders || [])[0];
  if (!dossier) return "";
  const marque = path.join(dossier.uri.fsPath, MARQUE);
  let session = "";
  let ecritLe = NaN;
  try {
    const consigne = JSON.parse(fs.readFileSync(marque, "utf8"));
    session = String(consigne.session_id || "").trim();
    ecritLe = Number(consigne.ecrit_le);
  } catch (_) {
    return "";
  }
  try {
    fs.unlinkSync(marque);
  } catch (_) {
    // Rien a faire : au pire on rouvrira la meme conversation.
  }
  // Une consigne vaut pour l'ouverture qui vient d'etre demandee. Celle qu'un
  // dossier garde depuis longtemps (code-server n'a pas ouvert ce dossier a ce
  // moment-la) ouvrirait une conversation d'hier : on la jette, sans l'ouvrir.
  // Sans date, elle vient d'une version qui ne la posait pas : meme sort.
  return consigneFraiche(ecritLe, Date.now()) ? session : "";
}

function consigneFraiche(ecritLe, maintenantMs) {
  if (!Number.isFinite(ecritLe)) return false;
  const age = maintenantMs / 1000 - ecritLe;
  return age >= -60 && age <= DUREE_DE_LA_CONSIGNE_S;
}

// VS Code restitue les onglets d'une fenetre deja ouverte une fois, dont le
// panneau Claude que la visite precedente avait laisse. Restitue, il revient
// vide : la conversation n'est pas rechargee avec lui. Si on se contente
// d'ouvrir la bonne a cote, on se retrouve avec deux onglets Claude, dont un
// sans rien dedans. On ferme donc ce qui a ete restitue avant d'ouvrir.
async function fermerPanneauxRestitues() {
  const restitues = [];
  for (const groupe of vscode.window.tabGroups.all) {
    for (const onglet of groupe.tabs) {
      const type = onglet.input && onglet.input.viewType;
      if (typeof type === "string" && type.includes("claudeVSCodePanel")) restitues.push(onglet);
    }
  }
  if (restitues.length) await vscode.window.tabGroups.close(restitues, false);
  return restitues.length;
}

// Les deux extensions s'eveillent au meme signal, sans ordre garanti : on
// attend que la commande existe plutot que de supposer qu'elle est deja la.
async function attendreCommande(limiteMs) {
  const echeance = Date.now() + limiteMs;
  for (;;) {
    if ((await vscode.commands.getCommands(true)).includes(COMMANDE)) return true;
    if (Date.now() > echeance) return false;
    await new Promise((suite) => setTimeout(suite, 300));
  }
}

async function activate() {
  // Sans consigne, on ne touche a rien : VS Code a restitue ce qu'il devait,
  // et ce n'est pas a nous de le defaire.
  const session = reprendreConversationConfiee();
  if (!session) return;
  if (!(await attendreCommande(30000))) return;
  await fermerPanneauxRestitues();
  await vscode.commands.executeCommand(COMMANDE, session);
}

module.exports = { activate, deactivate() {}, consigneFraiche, DUREE_DE_LA_CONSIGNE_S };
