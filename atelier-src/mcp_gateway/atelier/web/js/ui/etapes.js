/**
 * Les étapes d'un tour : ce que l'agent a fait, dit en une phrase.
 *
 * Le fil montrait le brut — le nom technique de chaque outil
 * (`mcp__chrome-devtools-mcp__take_snapshot`), ses paramètres en JSON, son
 * résultat entier — et la réponse se perdait dessous. On présente désormais
 * un tour comme l'extension VS Code : une étape par appel d'outil, dite en
 * clair, repliée sous « Voir les étapes (n) », et la réponse finale lisible
 * en dessous.
 *
 * Ce module ne fait que lire : il ne change ni le transcrit ni le flux, et il
 * ne retire rien. Tout ce qui est replié reste accessible en dépliant.
 *
 * Deux fonctions portent le contrat, et les tests les tiennent :
 *   - `libelleEtape(bloc)` : la phrase d'une étape ;
 *   - `regrouperTour(blocs)` : ce qui se replie (les étapes), ce qui ne se
 *     replie jamais (autorisations, erreurs, refus, cartes d'action), et la
 *     réponse (le dernier texte du tour).
 */

// ── Réglages d'affichage ─────────────────────────────────────────────────
//
// Deux cases, décochées par défaut : montrer le raisonnement, montrer les
// actions et leurs résultats bruts. Retenues par personne (réglages
// d'interface du service, voir `controllers/reglages-fil.js`), identiques en
// Code et dans l'Assistant.

export const REGLAGES_PAR_DEFAUT = Object.freeze({ raisonnement: false, actions: false });

let reglages = { ...REGLAGES_PAR_DEFAUT };

/** Les réglages en vigueur pour le rendu du fil. */
export function reglagesDuFil() {
  return reglages;
}

/** Pose les réglages ; ce qui n'est pas un booléen garde la valeur par défaut. */
export function poserReglagesDuFil(partiel) {
  const suivant = { ...reglages };
  for (const cle of Object.keys(REGLAGES_PAR_DEFAUT)) {
    if (typeof partiel?.[cle] === "boolean") suivant[cle] = partiel[cle];
  }
  reglages = suivant;
  return reglages;
}

// ── Libellés ─────────────────────────────────────────────────────────────

const LONGUEUR_CIBLE = 60;

function court(texte, max = LONGUEUR_CIBLE) {
  const s = String(texte || "").replace(/\s+/g, " ").trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** Le dernier segment d'un chemin : `api.py` pour `/home/x/projet/api.py`. */
export function nomDeFichier(chemin) {
  const s = String(chemin || "").replace(/[\\/]+$/, "");
  const morceaux = s.split(/[\\/]/);
  return morceaux[morceaux.length - 1] || s;
}

function hote(url) {
  try {
    return new URL(String(url)).host || court(url, 40);
  } catch {
    return court(url, 40);
  }
}

function guillemets(texte, max = 40) {
  const s = court(texte, max);
  return s ? `« ${s} »` : "";
}

/** `publish_artifact` devient « Publish artifact ». */
export function humaniser(nom) {
  const s = String(nom || "")
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim()
    .toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

// Les outils de Claude Code. Chaque entrée rend la phrase d'après l'entrée
// de l'outil ; Bash et Task utilisent la description que le modèle a écrite,
// comme l'extension VS Code.
const OUTILS_CLAUDE = {
  Bash: (e) => court(e.description) || `Commande ${guillemets(String(e.command || "").split("\n")[0])}`.trim(),
  BashOutput: () => "Lecture de la sortie d’une commande",
  KillShell: () => "Arrêt d’une commande",
  KillBash: () => "Arrêt d’une commande",
  Task: (e) => court(e.description) || "Travail confié à un sous-agent",
  Agent: (e) => court(e.description) || "Travail confié à un sous-agent",
  TodoWrite: (e) => {
    const taches = Array.isArray(e.todos) ? e.todos : [];
    const faites = taches.filter((t) => t?.status === "completed").length;
    return taches.length ? `Plan de travail (${faites}/${taches.length} faites)` : "Plan de travail";
  },
  Read: (e) => `Lecture de ${nomDeFichier(e.file_path || e.path) || "un fichier"}`,
  Write: (e) => `Écriture de ${nomDeFichier(e.file_path || e.path) || "un fichier"}`,
  Edit: (e) => `Modification de ${nomDeFichier(e.file_path || e.path) || "un fichier"}`,
  MultiEdit: (e) => `Modification de ${nomDeFichier(e.file_path || e.path) || "un fichier"}`,
  NotebookEdit: (e) => `Modification du carnet ${nomDeFichier(e.notebook_path) || ""}`.trim(),
  Grep: (e) => {
    const ou = e.path ? ` dans ${nomDeFichier(e.path)}` : "";
    return `Recherche de ${guillemets(e.pattern) || "texte"}${ou}`;
  },
  Glob: (e) => `Recherche des fichiers ${guillemets(e.pattern)}`.trim(),
  WebFetch: (e) => `Lecture de la page ${hote(e.url)}`.trim(),
  WebSearch: (e) => `Recherche web ${guillemets(e.query)}`.trim(),
  AskUserQuestion: (e) => {
    const q = Array.isArray(e.questions) ? e.questions[0] : null;
    return q?.header ? `Question : ${court(q.header, 40)}` : "Question posée";
  },
  ExitPlanMode: () => "Plan proposé",
  ListMcpResourcesTool: () => "Liste des ressources des connecteurs",
  ReadMcpResourceTool: (e) => `Lecture d’une ressource ${guillemets(e.uri)}`.trim(),
  SlashCommand: (e) => `Commande ${court(e.command, 40)}`,
  Skill: (e) => `Compétence ${court(e.skill || e.command, 40)}`.trim(),
};

// Le navigateur de l'agent (chrome-devtools). Mêmes noms d'une version du
// serveur à l'autre, ou presque : les deux formes sont là.
const NAVIGATEUR = {
  navigate_page: (e) => {
    if (e.type === "back") return "Retour à la page précédente";
    if (e.type === "forward") return "Page suivante";
    if (e.type === "reload") return "Rechargement de la page";
    return e.url ? `Ouverture d’une page (${hote(e.url)})` : "Ouverture d’une page";
  },
  new_page: (e) => (e.url ? `Nouvel onglet (${hote(e.url)})` : "Nouvel onglet"),
  take_snapshot: () => "Lecture de la page",
  take_screenshot: () => "Capture de la page",
  click: () => "Clic sur un élément",
  hover: () => "Survol d’un élément",
  fill: () => "Saisie dans un champ",
  fill_form: () => "Remplissage d’un formulaire",
  type_text: () => "Saisie de texte",
  press_key: (e) => (e.key ? `Appui sur ${court(e.key, 20)}` : "Appui sur une touche"),
  drag: () => "Glisser-déposer",
  upload_file: () => "Envoi d’un fichier",
  handle_dialog: () => "Réponse à une boîte de dialogue",
  evaluate_script: () => "Exécution d’un script dans la page",
  wait_for: () => "Attente d’un contenu dans la page",
  list_pages: () => "Liste des onglets",
  select_page: () => "Changement d’onglet",
  close_page: () => "Fermeture d’un onglet",
  list_network_requests: () => "Lecture des requêtes réseau",
  get_network_request: () => "Lecture d’une requête réseau",
  list_console_messages: () => "Lecture de la console",
  get_console_message: () => "Lecture d’un message de la console",
  resize_page: () => "Redimensionnement de la page",
  emulate: () => "Émulation d’un appareil",
  performance_start_trace: () => "Mesure des performances",
  performance_stop_trace: () => "Fin de la mesure des performances",
  performance_analyze_insight: () => "Analyse des performances",
  lighthouse_audit: () => "Audit de la page",
  take_heapsnapshot: () => "Capture de la mémoire",
};
// Les anciens noms, d'avant `_page` / `take_`.
NAVIGATEUR.navigate = NAVIGATEUR.navigate_page;
NAVIGATEUR.snapshot = NAVIGATEUR.take_snapshot;
NAVIGATEUR.screenshot = NAVIGATEUR.take_screenshot;
NAVIGATEUR.mouse_click = NAVIGATEUR.click;
NAVIGATEUR.key_press = NAVIGATEUR.press_key;
NAVIGATEUR.raise_window = () => "Mise au premier plan de la fenêtre";

const FICHIERS = {
  read_file: (e) => `Lecture de ${nomDeFichier(e.path)}`,
  read_text_file: (e) => `Lecture de ${nomDeFichier(e.path)}`,
  read_multiple_files: () => "Lecture de plusieurs fichiers",
  write_file: (e) => `Écriture de ${nomDeFichier(e.path)}`,
  edit_file: (e) => `Modification de ${nomDeFichier(e.path)}`,
  create_directory: (e) => `Création du dossier ${nomDeFichier(e.path)}`,
  list_directory: (e) => `Liste du dossier ${nomDeFichier(e.path)}`,
  directory_tree: (e) => `Arborescence de ${nomDeFichier(e.path)}`,
  move_file: (e) => `Déplacement de ${nomDeFichier(e.source)}`,
  copy_file: (e) => `Copie de ${nomDeFichier(e.source)}`,
  search_files: (e) => `Recherche des fichiers ${guillemets(e.pattern)}`.trim(),
  get_file_info: (e) => `Informations sur ${nomDeFichier(e.path)}`,
  list_allowed_directories: () => "Liste des dossiers autorisés",
};

// Les commandes de l'Atelier. Le catalogue ne leur donne pas de titre court
// (seulement une description destinée au modèle) : la carte d'action rendue,
// quand il y en a une, fait foi (voir `libelleEtape`) ; sinon cette table.
const ATELIER = {
  atelier_carte: (e) => (e.projet ? `Lecture de la carte du projet ${court(e.projet, 30)}` : "Lecture de la carte de l’Atelier"),
  atelier_fiche: () => "Lecture d’une fiche",
  atelier_projets: () => "Liste des projets",
  atelier_projet_creer: () => "Création d’un projet",
  atelier_projet_modifier: () => "Modification d’un projet",
  atelier_projet_ranger: () => "Rangement d’un projet",
  atelier_projet_ressortir: () => "Retour d’un projet rangé",
  atelier_conversations: () => "Liste des conversations",
  atelier_ouvrir: () => "Ouverture d’une conversation",
  atelier_envoyer: () => "Message envoyé à un agent",
  atelier_suivre: () => "Suivi d’une conversation",
  atelier_transcript: () => "Lecture d’une conversation",
  atelier_interrompre: () => "Arrêt d’un tour",
  atelier_a_valider: () => "Lecture de « À valider »",
  atelier_a_valider_accepter: () => "Acceptation d’une proposition",
  atelier_a_valider_refuser: () => "Refus d’une proposition",
  atelier_journal: () => "Lecture du journal",
  atelier_memoire: () => "Lecture de la mémoire",
  atelier_memoire_proposer: () => "Proposition d’un souvenir",
  atelier_memoire_retenir: () => "Souvenir retenu",
  atelier_memoire_corriger: () => "Correction d’un souvenir",
  atelier_memoire_oublier: () => "Souvenir oublié",
  atelier_montrer: () => "Création montrée dans le panneau",
  atelier_navigateur_ouvrir: () => "Ouverture du navigateur de l’agent",
  atelier_artefacts: () => "Liste des créations",
  atelier_artefact_creer: () => "Création d’une application",
  atelier_artefact_demarrer: () => "Démarrage d’une application",
  atelier_artefact_arreter: () => "Arrêt d’une application",
  atelier_artefact_verifier: () => "Vérification d’une application",
  atelier_artefact_journal: () => "Lecture du journal d’une application",
  atelier_lancer_agent: () => "Lancement d’un agent",
  atelier_lancements: () => "Liste des agents lancés",
  atelier_agent_creer: () => "Création d’un agent",
  atelier_agent_modifier: () => "Modification d’un agent",
  atelier_agent_activer: () => "Activation d’un agent",
  atelier_agent_desactiver: () => "Désactivation d’un agent",
  atelier_agent_supprimer: () => "Suppression d’un agent",
  atelier_connecteur_ajouter: () => "Ajout d’un connecteur",
  atelier_connecteur_retirer: () => "Retrait d’un connecteur",
  atelier_connecteur_choisir: () => "Choix des connecteurs du projet",
  atelier_connecteur_accorder: () => "Secret accordé à un connecteur",
  atelier_rappel: () => "Rappel programmé",
  atelier_decider: () => "Décision rendue",
  atelier_annuler: () => "Annulation d’une action",
};

// Le nom lisible d'un serveur MCP, pour les outils que la table ne connaît pas.
const SERVEURS = {
  "chrome-devtools": "Navigateur",
  "chrome-devtools-mcp": "Navigateur",
  filesystem: "Fichiers",
  github: "GitHub",
  gitlab: "GitLab",
  qgis: "QGIS",
  onyxia: "Onyxia",
  datagouv: "data.gouv",
  blender: "Blender",
  atelier: "Atelier",
  wikichat: "wikichat",
  n8n: "n8n",
};

const TABLES_MCP = {
  "chrome-devtools": NAVIGATEUR,
  "chrome-devtools-mcp": NAVIGATEUR,
  filesystem: FICHIERS,
  atelier: ATELIER,
};

/** `mcp__serveur__outil` en ses deux parties ; null pour un outil natif. */
export function nomMcp(nom) {
  const m = /^mcp__(.+?)__(.+)$/.exec(String(nom || ""));
  return m ? { serveur: m[1], outil: m[2] } : null;
}

function entreeObjet(entree) {
  if (entree && typeof entree === "object") return entree;
  if (typeof entree === "string") {
    try {
      const v = JSON.parse(entree);
      return v && typeof v === "object" ? v : {};
    } catch {
      return {};
    }
  }
  return {};
}

function titreDeCarte(sortie) {
  if (!sortie) return "";
  try {
    const charge = typeof sortie === "string" ? JSON.parse(sortie) : sortie;
    const titre = charge?.carte?.titre;
    return typeof titre === "string" ? titre.trim() : "";
  } catch {
    return "";
  }
}

/**
 * La phrase d'une étape, d'après l'outil et son entrée.
 *
 * @param {{ name?: string, input?: unknown, output?: string }} bloc
 * @returns {string}
 */
export function libelleEtape(bloc) {
  const nom = String(bloc?.name || "");
  const entree = entreeObjet(bloc?.input);

  // Le méta-outil de la passerelle : l'étape est l'outil qu'il appelle.
  const outilNu = nomMcp(nom)?.outil || nom;
  if (outilNu === "gateway_call_tool") {
    const cible = entree.name || entree.tool || entree.tool_name || "";
    if (cible) return libelleEtape({ name: cible, input: entree.arguments || entree.args || {} });
    return "Appel d’un outil";
  }
  if (outilNu === "gateway_find_tools" || outilNu === "gateway_search_tools") {
    return `Recherche d’un outil ${guillemets(entree.query || entree.q || "")}`.trim();
  }

  const natif = OUTILS_CLAUDE[nom];
  if (natif) return natif(entree) || nom;

  const mcp = nomMcp(nom);
  if (mcp) {
    const titre = mcp.serveur === "atelier" ? titreDeCarte(bloc?.output) : "";
    if (titre) return titre;
    const table = TABLES_MCP[mcp.serveur];
    const rendu = table?.[mcp.outil]?.(entree);
    if (rendu) return rendu;
    const serveur = SERVEURS[mcp.serveur] || mcp.serveur;
    return `${serveur} : ${humaniser(mcp.outil)}`;
  }
  // Une commande de l'Atelier appelée sans préfixe (outil local de la passerelle).
  if (ATELIER[nom]) return titreDeCarte(bloc?.output) || ATELIER[nom](entree);
  return humaniser(nom) || "Outil";
}

/** L'icône d'une étape, par famille d'outil. */
export function iconeEtape(bloc) {
  const nom = String(bloc?.name || "");
  if (nom === "Read" || /read_(text_)?file|read_multiple/.test(nom)) return "fichier";
  if (["Write", "Edit", "MultiEdit", "NotebookEdit"].includes(nom) || /write_file|edit_file/.test(nom)) return "crayon";
  if (nom === "Bash" || nom === "BashOutput") return "terminal";
  if (nom === "Grep" || nom === "Glob" || nom === "WebSearch" || /search|find/.test(nom)) return "loupe";
  if (nom === "WebFetch" || /chrome-devtools/.test(nom)) return "globe";
  if (nom === "Task" || nom === "Agent") return "agent";
  if (nom === "TodoWrite") return "liste";
  if (nom === "AskUserQuestion") return "question";
  return "outil";
}

// ── Regroupement d'un tour ───────────────────────────────────────────────

/** Une étape qui ne se replie jamais : en erreur, refusée. */
export function etapeEnEchec(bloc) {
  return bloc?.type === "tool" && (bloc.status === "error" || bloc.status === "denied");
}

/**
 * Sépare un tour en étapes, éléments toujours visibles, et réponse.
 *
 * - La réponse est le texte qui suit le dernier geste du tour (outil,
 *   demande, message du système). Sans geste, tout le texte est réponse.
 * - Les étapes sont tout le reste, dans l'ordre : un outil par étape, le
 *   texte écrit entre deux outils comme narration, et le raisonnement quand
 *   « Montrer le raisonnement » est coché. Décoché (le défaut), il n'est pas
 *   une étape du tout : il occupait une ligne sur deux de la liste, pour un
 *   texte que la personne a choisi de ne pas voir. Le compteur ne compte que
 *   les outils, dans les deux cas.
 * - Ne se replient jamais : les demandes d'autorisation et les questions,
 *   les demandes restées sans réponse, les messages du système, les outils
 *   en erreur ou refusés, les cartes d'action de l'Assistant (`aCarte`).
 *
 * @param {object[]} blocs les blocs du message, dans l'ordre du tour
 * @param {{ aCarte?: (bloc: object) => boolean, raisonnement?: boolean }} [options]
 *   `raisonnement` : montrer le raisonnement ; par défaut, le réglage du fil.
 */
export function regrouperTour(blocs, { aCarte = () => false, raisonnement = reglages.raisonnement } = {}) {
  const liste = Array.isArray(blocs) ? blocs : [];
  let dernierGeste = -1;
  liste.forEach((b, i) => {
    if (b && b.type !== "text" && b.type !== "thinking") dernierGeste = i;
  });

  const etapes = [];
  const toujoursVisibles = [];
  const reponse = [];
  let nombre = 0;

  liste.forEach((b, i) => {
    if (!b) return;
    if (b.type === "text") {
      if (!String(b.text || "").trim()) return;
      if (i > dernierGeste) reponse.push(b);
      else etapes.push({ genre: "narration", bloc: b });
      return;
    }
    if (b.type === "thinking") {
      if (raisonnement && String(b.text || "").trim()) etapes.push({ genre: "raisonnement", bloc: b });
      return;
    }
    if (b.type === "tool") {
      nombre += 1;
      const echec = etapeEnEchec(b);
      etapes.push({ genre: "outil", bloc: b, libelle: libelleEtape(b), echec });
      if (echec || aCarte(b)) toujoursVisibles.push(b);
      return;
    }
    // decision, perimees, systeme : jamais replié.
    toujoursVisibles.push(b);
  });

  return { etapes, nombre, toujoursVisibles, reponse };
}

/**
 * Ce que dit la ligne vivante pendant un tour : l'étape en cours.
 *
 * @param {object[]} blocs
 * @param {string} [phase] la phase du flux (`attente`, `reflexion`, `outil`, `decision`)
 */
export function etapeEnCours(blocs, phase = "") {
  const liste = Array.isArray(blocs) ? blocs : [];
  const dernier = liste[liste.length - 1];
  if (!dernier) return phase === "reflexion" ? "Réflexion…" : "En attente du modèle…";
  if (dernier.type === "tool") {
    return dernier.status === "running" ? `${libelleEtape(dernier)}…` : libelleEtape(dernier);
  }
  if (dernier.type === "thinking") return "Réflexion…";
  if (dernier.type === "decision") return "En attente de votre décision…";
  if (dernier.type === "text") return "Rédaction de la réponse…";
  return "";
}

/** Le résumé du pli : « Voir les étapes (3) », ou le raisonnement seul. */
export function resumeDesEtapes(groupe) {
  if (groupe.nombre > 0) return `Voir les étapes (${groupe.nombre})`;
  if (groupe.etapes.some((e) => e.genre === "raisonnement")) return "Voir le raisonnement";
  return groupe.etapes.length ? "Voir les étapes" : "";
}
