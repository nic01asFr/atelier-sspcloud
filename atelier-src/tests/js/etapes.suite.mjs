// Les étapes d'un tour, et ce que le refine de l'interface a corrigé autour.
//
// Le fil montrait le brut de chaque outil — son nom technique, ses
// paramètres, son résultat entier — et la réponse se perdait dessous. Un tour
// se lit désormais comme dans l'extension VS Code : une étape par appel
// d'outil, dite en clair, repliée sous « Voir les étapes (n) », et la réponse
// en dessous. Cette suite tient :
//
//   1. la table des libellés (Claude Code, navigateur, fichiers, Atelier,
//      outils inconnus) ;
//   2. le regroupement d'un tour : outils et textes intermédiaires en étapes,
//      dernier texte en réponse ;
//   3. ce qui ne se replie jamais : autorisations, erreurs et refus, cartes
//      d'action ;
//   4. l'étape vivante pendant le flux, et la stabilité des nœuds ;
//   5. les réglages « Détails techniques » ;
//   6. les petits correctifs voisins : message long replié, heure, cause
//      d'arrêt, raccourcis, arbre des conversations qui ne se refait plus.

import { berceau, cliquer, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import {
  etapeEnCours,
  humaniser,
  libelleEtape,
  nomDeFichier,
  poserReglagesDuFil,
  regrouperTour,
  reglagesDuFil,
  resumeDesEtapes,
} from "../../mcp_gateway/atelier/web/js/ui/etapes.js";
import {
  appendMessageBody,
  messageLong,
  planDeTravail,
  texteDeLaReponse,
} from "../../mcp_gateway/atelier/web/js/ui/message-render.js";
import { NOMS_ICONES, svgIcone } from "../../mcp_gateway/atelier/web/js/ui/icones.js";
import { gesteDuClavier } from "../../mcp_gateway/atelier/web/js/ui/raccourcis.js";
import { causeLisible, estUnArret } from "../../mcp_gateway/atelier/web/js/controllers/chat.js";
import { reglagesDepuisMeta } from "../../mcp_gateway/atelier/web/js/controllers/reglages-fil.js";
import { heureDuMessage, nomDeLOrateur, questionPrecedente } from "../../mcp_gateway/atelier/web/js/views/code-chat.js";
import { empreinteDeLArbre } from "../../mcp_gateway/atelier/web/js/views/code-tree.js";
import { memeTexte } from "../../mcp_gateway/atelier/web/js/views/agent.js";
import { libelleControle } from "../../mcp_gateway/atelier/web/js/views/gardiens.js";
import { filtrerOutils } from "../../mcp_gateway/atelier/web/js/views/composition-builder.js";
import { badgeStatutComposition } from "../../mcp_gateway/atelier/web/js/views/connectors.js";
import { appliquerTheme, themeDepuisMeta, themeValable } from "../../mcp_gateway/atelier/web/js/controllers/theme.js";

const outil = (id, name, input = {}, extra = {}) => ({ type: "tool", id, name, input, output: "", status: "done", ...extra });
const parole = (t) => ({ type: "text", text: t });

// ── 1. La table des libellés ─────────────────────────────────────────────

{
  egal(libelleEtape(outil("a", "Bash", { command: "ls -la", description: "Liste les fichiers" })), "Liste les fichiers",
    "Bash : la description écrite par le modèle, comme dans VS Code");
  egal(libelleEtape(outil("a", "Bash", { command: "npm test\nnpm run lint" })), "Commande « npm test »",
    "Bash sans description : la première ligne de la commande");
  egal(libelleEtape(outil("a", "Task", { description: "Explorer le dépôt" })), "Explorer le dépôt", "Task : sa description");
  egal(libelleEtape(outil("a", "Read", { file_path: "/home/x/projet/api.py" })), "Lecture de api.py", "Read : verbe et fichier");
  egal(libelleEtape(outil("a", "Edit", { file_path: "C:\\x\\app.css" })), "Modification de app.css", "Edit, chemin Windows compris");
  egal(libelleEtape(outil("a", "Write", { file_path: "/tmp/notes.md" })), "Écriture de notes.md", "Write");
  egal(libelleEtape(outil("a", "Grep", { pattern: "profil" })), "Recherche de « profil »", "Grep : le motif cherché");
  egal(libelleEtape(outil("a", "Glob", { pattern: "**/*.js" })), "Recherche des fichiers « **/*.js »", "Glob");
  egal(libelleEtape(outil("a", "WebFetch", { url: "https://example.com/a/b" })), "Lecture de la page example.com", "WebFetch : l'hôte");
  egal(
    libelleEtape(outil("a", "TodoWrite", { todos: [{ status: "completed" }, { status: "pending" }] })),
    "Plan de travail (1/2 faites)",
    "TodoWrite : l'avancement du plan",
  );

  egal(libelleEtape(outil("a", "mcp__chrome-devtools-mcp__navigate_page", { url: "https://example.com" })),
    "Ouverture d’une page (example.com)", "navigateur : ouvrir une page");
  egal(libelleEtape(outil("a", "mcp__chrome-devtools__take_snapshot")), "Lecture de la page", "navigateur : lire la page");
  egal(libelleEtape(outil("a", "mcp__chrome-devtools-mcp__click", { uid: "1_3" })), "Clic sur un élément", "navigateur : cliquer");
  egal(libelleEtape(outil("a", "mcp__chrome-devtools-mcp__navigate_page", { type: "back" })), "Retour à la page précédente",
    "navigateur : revenir en arrière");
  egal(libelleEtape(outil("a", "mcp__chrome-devtools-mcp__screenshot")), "Capture de la page", "un ancien nom d'outil se lit aussi");
  egal(libelleEtape(outil("a", "mcp__filesystem__list_directory", { path: "/home/x/projet" })), "Liste du dossier projet",
    "fichiers : lister un dossier");

  egal(libelleEtape(outil("a", "mcp__atelier__atelier_carte", { forme: "projet", projet: "lecteur" })),
    "Lecture de la carte du projet lecteur", "commande de l'Atelier : sa table");
  egal(
    libelleEtape(outil("a", "mcp__atelier__atelier_projet_creer", {}, { output: JSON.stringify({ carte: { titre: "Projet créé" } }) })),
    "Projet créé",
    "commande de l'Atelier : la carte d'action rendue fait foi",
  );
  egal(
    libelleEtape(outil("a", "mcp__atelier__gateway_call_tool", { name: "mcp__chrome-devtools__take_snapshot", arguments: {} })),
    "Lecture de la page",
    "le méta-outil de la passerelle : l'étape est l'outil qu'il appelle",
  );

  egal(libelleEtape(outil("a", "mcp__qgis__publish_artifact")), "QGIS : Publish artifact", "outil inconnu : serveur lisible et nom humanisé");
  egal(libelleEtape(outil("a", "mcp__serveur-perso__faire_un_truc")), "serveur-perso : Faire un truc", "serveur inconnu : son nom tel quel");
  egal(humaniser("publishArtifact"), "Publish artifact", "humaniser découpe aussi le camelCase");
  egal(nomDeFichier("/a/b/c/"), "c", "un dossier terminé par une barre garde son nom");

  const long = libelleEtape(outil("a", "Bash", { description: "x".repeat(200) }));
  verifier(long.length <= 60, "une phrase d'étape reste courte");
}

// ── 2. Le regroupement d'un tour ─────────────────────────────────────────

{
  const blocs = [
    { type: "thinking", text: "Je dois lire le fichier." },
    parole("Je regarde le fichier."),
    outil("t1", "Read", { file_path: "/p/api.py" }),
    parole("Je vois le lien, je clique."),
    outil("t2", "mcp__chrome-devtools__click"),
    parole("Le titre de la page est « IANA »."),
    parole("Autre chose ?"),
  ];
  const g = regrouperTour(blocs);
  egal(g.nombre, 2, "une étape par appel d'outil");
  egal(
    g.etapes.map((e) => e.genre),
    ["raisonnement", "narration", "outil", "narration", "outil"],
    "le raisonnement et les textes intermédiaires restent à leur place dans les étapes",
  );
  egal(g.reponse.map((b) => b.text), ["Le titre de la page est « IANA ».", "Autre chose ?"],
    "le texte qui suit le dernier outil est la réponse");
  egal(g.toujoursVisibles, [], "rien à épingler dans un tour sans incident");
  egal(resumeDesEtapes(g), "Voir les étapes (2)", "le pli dit combien d'étapes");

  const sansOutil = regrouperTour([{ type: "thinking", text: "hmm" }, parole("Bonjour.")]);
  egal(sansOutil.reponse.length, 1, "sans outil, tout le texte est réponse");
  egal(resumeDesEtapes(sansOutil), "Voir le raisonnement", "et le pli ne garde que le raisonnement");
  egal(resumeDesEtapes(regrouperTour([parole("Bonjour.")])), "", "une réponse seule n'a pas de pli");
  egal(texteDeLaReponse({ blocks: blocs }), "Le titre de la page est « IANA ».\n\nAutre chose ?",
    "« Copier » prend la réponse, sans la narration");
}

// ── 3. Ce qui ne se replie jamais ────────────────────────────────────────

{
  const demande = { type: "decision", etat: "en_attente", demande: { request_id: "r1", outil: "Bash", arguments: {} } };
  const enErreur = outil("t1", "Bash", { description: "Lance les tests" }, { status: "error", output: "boom" });
  const refuse = outil("t2", "mcp__github__get_me", {}, { status: "denied" });
  const carte = outil("t3", "mcp__atelier__atelier_projet_creer", {}, { output: JSON.stringify({ carte: { titre: "Projet créé" } }) });
  const g = regrouperTour(
    [parole("Je lance."), enErreur, refuse, demande, carte, { type: "systeme", text: "relance" }, parole("Fini.")],
    { aCarte: (b) => b === carte },
  );
  egal(g.toujoursVisibles, [enErreur, refuse, demande, carte, { type: "systeme", text: "relance" }],
    "erreurs, refus, demandes, cartes d'action et messages du système restent visibles, dans l'ordre");
  egal(g.nombre, 3, "une étape en erreur reste une étape, comptée");
  verifier(g.etapes.find((e) => e.bloc === enErreur)?.echec === true, "et marquée en échec dans la liste");

  // Le chemin complet : le pli, puis ce qui est épinglé, puis la réponse.
  const noeud = berceau();
  appendMessageBody(noeud, { role: "assistant", text: "", blocks: [parole("Je lance."), enErreur, demande, parole("Fini.")] });
  const visibles = noeud.querySelector(".tour-visibles");
  egal(visibles.querySelectorAll(".msg-decision").length, 1, "la demande d'autorisation est hors du pli");
  egal(visibles.querySelectorAll(".etape-echec").length, 1, "l'étape en erreur aussi, marquée");
  porte(texte(visibles), "Lance les tests", "dite en clair");
  porte(texte(noeud.querySelector(".tour-reponse")), "Fini.", "et la réponse en dessous");
  verifier(noeud.children.indexOf(noeud.querySelector(".tour-etapes")) < noeud.children.indexOf(visibles),
    "le pli vient avant ce qui est épinglé");
}

// ── 4. Pendant le flux ───────────────────────────────────────────────────

{
  egal(etapeEnCours([], "attente"), "En attente du modèle…", "rien encore : on attend le modèle");
  egal(etapeEnCours([{ type: "thinking", text: "…" }]), "Réflexion…", "le raisonnement se dit");
  egal(etapeEnCours([outil("t", "mcp__chrome-devtools__take_snapshot", {}, { status: "running" })]), "Lecture de la page…",
    "l'étape en cours, vivante");
  egal(etapeEnCours([parole("Voici")]), "Rédaction de la réponse…", "la réponse qui s'écrit");

  const noeud = berceau();
  const lecture = outil("t1", "Read", { file_path: "/p/a.py" }, { status: "running" });
  const m = { role: "assistant", text: "", blocks: [lecture], streaming: true, phase: "outil" };
  appendMessageBody(noeud, m);
  const pli = noeud.querySelector(".tour-etapes");
  porte(texte(pli.querySelector(".tour-vivant")), "Lecture de a.py…", "la ligne vivante dit l'étape en cours");
  porte(texte(pli.querySelector(".tour-resume-texte")), "Voir les étapes (1)", "le compte se met à jour en direct");

  pli.open = true; // la personne a déplié pendant le tour
  m.blocks = [{ ...lecture, status: "done" }, outil("t2", "Bash", { description: "Liste" }, { status: "running" })];
  appendMessageBody(noeud, m);
  verifier(noeud.querySelector(".tour-etapes") === pli, "le pli reste le même nœud pendant le flux");
  verifier(pli.open === true, "et ce qu'on a déplié le reste");
  porte(texte(pli.querySelector(".tour-resume-texte")), "Voir les étapes (2)", "deux étapes maintenant");

  m.streaming = false;
  m.blocks = [...m.blocks.slice(0, 1), { ...m.blocks[1], status: "done" }, parole("Voilà.")];
  appendMessageBody(noeud, m);
  verifier(pli.querySelector(".tour-vivant").hidden, "le tour fini, la ligne vivante s'efface");
}

// ── 5. Les réglages « Détails techniques » ───────────────────────────────

{
  egal(reglagesDepuisMeta({ ui: {} }), { raisonnement: false, actions: false }, "décochés par défaut");
  egal(reglagesDepuisMeta({ ui: { fil_raisonnement: true } }), { raisonnement: true, actions: false }, "lus depuis le service");

  const blocs = [{ type: "thinking", text: "Je réfléchis." }, outil("t1", "Read", { file_path: "/p/a.py" }, { output: "1" }), parole("Ok.")];
  poserReglagesDuFil({ raisonnement: false, actions: false });
  const replie = berceau();
  appendMessageBody(replie, { role: "assistant", blocks: blocs });
  verifier(!replie.querySelector(".tour-etapes").open, "par défaut, les étapes sont repliées");
  egal(replie.querySelectorAll(".msg-tool").length, 0, "et le brut d'un outil n'est construit qu'au dépliage");

  poserReglagesDuFil({ actions: true });
  const deplie = berceau();
  appendMessageBody(deplie, { role: "assistant", blocks: blocs });
  verifier(deplie.querySelector(".tour-etapes").open, "« actions » coché : les étapes s'ouvrent");
  egal(deplie.querySelectorAll(".msg-tool").length, 1, "et chaque outil montre son détail brut");
  verifier(deplie.querySelector(".etape-raisonnement").querySelector(".etape-pli").open === false, "le raisonnement reste replié tant qu'on ne l'a pas demandé");

  poserReglagesDuFil({ raisonnement: true, actions: false });
  const pense = berceau();
  appendMessageBody(pense, { role: "assistant", blocks: blocs });
  verifier(pense.querySelector(".etape-raisonnement").querySelector(".etape-pli").open, "« raisonnement » coché : il se lit d'emblée");
  poserReglagesDuFil({ raisonnement: "oui" });
  egal(reglagesDuFil().raisonnement, true, "une valeur qui n'est pas un booléen ne change rien");
  poserReglagesDuFil({ raisonnement: false, actions: false });
}

// ── 6. Correctifs voisins ────────────────────────────────────────────────

{
  // Un message long de la personne se replie, et se déplie.
  verifier(!messageLong("court"), "un message court reste entier");
  verifier(messageLong("x".repeat(5000)), "un fichier collé est long");
  const noeud = berceau();
  appendMessageBody(noeud, { role: "user", text: "ligne\n".repeat(40) });
  const bascule = noeud.querySelector(".msg-long-bascule");
  verifier(!!bascule && noeud.querySelector(".msg-long-replie"), "le message long se montre replié");
  cliquer(bascule);
  verifier(!noeud.querySelector(".msg-long-replie"), "« Afficher tout » le déplie");
  egal(bascule.textContent, "Réduire", "et le bouton dit le geste inverse");

  // Le plan de travail coché.
  const plan = planDeTravail({ todos: [
    { content: "Lire", status: "completed" },
    { content: "Écrire", activeForm: "Écriture en cours", status: "in_progress" },
    { content: "Tester", status: "pending" },
  ] });
  egal(plan.children.length, 3, "une ligne par tâche");
  porte(texte(plan.children[1]), "Écriture en cours", "la tâche en cours se lit à sa forme active");
  verifier(plan.children[0].className.includes("plan-tache-faite"), "la tâche faite est cochée");

  // L'heure du pied de message.
  const maintenant = new Date(2026, 8, 26, 15, 0);
  egal(heureDuMessage(new Date(2026, 8, 26, 14, 5).toISOString(), maintenant), "14:05", "le jour même : l'heure");
  egal(heureDuMessage(new Date(2026, 8, 24, 9, 3).toISOString(), maintenant), "24/09 09:03", "avant : la date aussi");
  egal(heureDuMessage("", maintenant), "", "sans horodatage, rien");

  // Qui parle, en français.
  egal(nomDeLOrateur("user", false), "Vous", "« Vous », pas « USER »");
  egal(nomDeLOrateur("assistant", false), "Claude", "en Code, Claude");
  egal(nomDeLOrateur("assistant", true), "Assistant", "dans l'Assistant, l'Assistant");

  // « Relancer » repose la question qui précède la réponse.
  const fil = [{ role: "user", text: "A ?", rang: 0 }, { role: "assistant", text: "a" }, { role: "user", text: "B ?", rang: 1 }, { role: "assistant", text: "b" }];
  egal(questionPrecedente(fil, 3)?.text, "B ?", "la dernière question avant la réponse");
  egal(questionPrecedente([{ role: "user", text: "x" }, { role: "assistant" }], 1), null, "sans rang, pas de relance possible");

  // La cause d'un arrêt.
  egal(causeLisible("exit_143"), "Tour arrêté.", "« exit_143 » ne s'affiche plus");
  verifier(estUnArret("exit_143") && !estUnArret("exit_1"), "un arrêt demandé n'est pas une panne");

  // Les raccourcis ne se déclenchent pas pendant la saisie.
  egal(gesteDuClavier({ key: "/", target: { tagName: "BODY" } }), "composeur", "« / » mène au composeur");
  egal(gesteDuClavier({ key: "/", target: { tagName: "TEXTAREA" } }), "", "sauf quand on écrit");
  egal(gesteDuClavier({ key: "n", altKey: true, target: { tagName: "TEXTAREA" } }), "nouvelle", "Alt+N marche partout");
  egal(gesteDuClavier({ key: "Escape", target: { tagName: "INPUT", type: "text" } }), "fermer", "Échap referme, même en saisie");
  egal(gesteDuClavier({ key: "/", ctrlKey: true, target: { tagName: "BODY" } }), "", "aucun geste avec Ctrl");

  // L'arbre ne se refait que s'il a changé.
  const etat = { montrerArchives: false, editingProjectSlug: null, editingSessionId: null, expandedSlugs: new Set(["p"]) };
  const projets = [{ slug: "p", title: "P", path: "/p" }];
  const sessions = [{ session_id: "s1", title: "Un", state: "idle", turns: 2 }];
  const e1 = empreinteDeLArbre(etat, projets, [], () => sessions);
  egal(empreinteDeLArbre(etat, projets, [], () => sessions), e1, "même données, même empreinte : pas de reconstruction");
  verifier(empreinteDeLArbre(etat, projets, [], () => [{ ...sessions[0], state: "running" }]) !== e1,
    "un état qui change refait l'arbre");

  // Les icônes : un jeu SVG, sans emoji.
  verifier(NOMS_ICONES.length >= 20, "le jeu d'icônes est là");
  verifier(NOMS_ICONES.every((n) => svgIcone(n).startsWith("<svg")), "chaque icône est un SVG");
  nePorte(svgIcone("inconnue"), "undefined", "une icône inconnue retombe sur l'outil générique");

  // Une description qui répète le nom ne se répète pas.
  verifier(memeTexte("Agent Qgis complet", " agent qgis  complet "), "même texte, casse et espaces mis à part");
  verifier(!memeTexte("", ""), "deux vides ne sont pas « le même texte »");

  // Le contrôle quotidien de cohérence des surfaces a son libellé.
  egal(libelleControle("coherence.surfaces"), "Chaque surface donne à l’agent ce que dit son profil",
    "un contrôle se dit en phrase, pas par son identifiant");
}

// ── 7. Compositions : trouver un outil parmi des centaines ──────────────

{
  const select = document.createElement("select");
  const groupe = (label, outils) => {
    const g = document.createElement("optgroup");
    g.label = label;
    for (const [valeur, texte] of outils) {
      const o = document.createElement("option");
      o.value = valeur;
      o.textContent = texte;
      g.appendChild(o);
    }
    select.appendChild(g);
    return g;
  };
  const nav = groupe("Navigateur web", [["chrome__navigate_page", "Ouvrir une page"], ["chrome__click", "Cliquer"]]);
  const data = groupe("data.gouv", [["datagouv__search_datasets", "Chercher des jeux de données"]]);
  egal(filtrerOutils(select, "donnees"), 1, "la recherche ignore accents et casse");
  verifier(nav.hidden && !data.hidden, "un connecteur sans outil trouvé se masque");
  egal(filtrerOutils(select, "navigateur"), 2, "le nom du connecteur compte aussi");
  egal(filtrerOutils(select, "navigate_page"), 1, "et le nom technique");
  egal(filtrerOutils(select, ""), 3, "une recherche vide montre tout");

  egal(badgeStatutComposition("production").textContent, "active", "l'état d'une composition se dit en français");
  egal(badgeStatutComposition("temporary").textContent, "brouillon", "un « temporary » est un brouillon");
}

// ── 8. Le thème ──────────────────────────────────────────────────────────

{
  const attributs = new Map();
  const doc = {
    documentElement: {
      setAttribute: (k, v) => attributs.set(k, v),
      removeAttribute: (k) => attributs.delete(k),
    },
  };
  const memo = new Map();
  const stockage = { setItem: (k, v) => memo.set(k, v), removeItem: (k) => memo.delete(k) };

  egal(themeValable("Clair"), "clair", "la casse ne compte pas");
  egal(themeValable("fluo"), "systeme", "un thème inconnu revient au système");
  egal(themeDepuisMeta({ ui: {} }), "systeme", "par défaut : suivre le système");
  egal(themeDepuisMeta({ ui: { theme: "sombre" } }), "sombre", "le choix retenu par le service");

  appliquerTheme("clair", doc, stockage);
  egal(attributs.get("data-theme"), "clair", "clair : l'attribut est posé");
  egal(memo.get("atelier.theme"), "clair", "et gardé pour le prochain chargement, sans éclair");
  appliquerTheme("systeme", doc, stockage);
  verifier(!attributs.has("data-theme"), "suivre le système : plus d'attribut");
  verifier(!memo.has("atelier.theme"), "ni de copie locale");
  const refuse = { setItem: () => { throw new Error("refusé"); }, removeItem: () => { throw new Error("refusé"); } };
  egal(appliquerTheme("sombre", doc, refuse), "sombre", "un stockage refusé n'empêche pas d'appliquer le thème");
}

bilan("etapes");
