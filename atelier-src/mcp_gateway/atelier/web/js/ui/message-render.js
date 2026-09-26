/** Rendu blocs message (texte markdown, thinking, outils, permissions). */

import { renderMarkdown } from "./markdown.js";
import { highlightElement } from "./code-highlight.js";
import { carteDAction } from "../views/assistant-cartes.js";

const TOOL_ICONS = {
  Read: "📄",
  Write: "✎",
  Edit: "✎",
  Bash: "⌘",
  Grep: "🔍",
  Task: "⚙",
  WebFetch: "🌐",
  WebSearch: "🔎",
};

function toolIcon(name) {
  return TOOL_ICONS[name] || "🔧";
}

function formatJson(value) {
  if (value == null || value === "") return "";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function guessOutputLang(toolName, text) {
  const t = String(text || "").trim();
  if (toolName === "Bash" || t.startsWith("$") || /^(sudo |cd |export )/.test(t)) return "bash";
  if (t.startsWith("{") || t.startsWith("[")) return "json";
  return "";
}

// Le résultat brut d'un outil se replie :
//   - toujours dans le fil de l'Assistant, où il n'est qu'une preuve derrière
//     la carte d'action (essais du 26/09 : le JSON d'`atelier_carte` s'étalait
//     déplié) ;
//   - partout au-delà d'une longueur raisonnable : Code et l'Assistant
//     partagent ce rendu, et un résultat de plusieurs écrans noie le fil.
// Un résultat court reste déplié en Code, comme avant.
export const RESULTAT_LONG_CARACTERES = 1500;
export const RESULTAT_LONG_LIGNES = 25;
let replierToujours = false;

/** Règle le repli des résultats pour le fil affiché (vrai : l'Assistant). */
export function replierLesResultats(toujours) {
  replierToujours = !!toujours;
}

/** Le résultat de cet outil s'affiche-t-il replié ? */
export function resultatReplie(sortie) {
  if (replierToujours) return true;
  const texte = String(sortie || "");
  return texte.length > RESULTAT_LONG_CARACTERES || texte.split("\n").length > RESULTAT_LONG_LIGNES;
}

function truncate(text, max = 4000) {
  const s = String(text || "");
  if (s.length <= max) return { text: s, truncated: false };
  return { text: s.slice(0, max) + "\n… (tronqué)", truncated: true };
}

/**
 * @param {HTMLElement} parent
 * @param {{ type: string, text?: string, name?: string, id?: string, input?: unknown, output?: string, status?: string }} block
 */
/**
 * La carte d'action qu'une commande rend (`{carte: {...}}`), ou l'aperçu d'une
 * commande engageante : voir `views/assistant-cartes.js`, qui porte « Voir »,
 * « Annuler » et « Oui ».
 */
export { carteDAction };

export function appendBlock(parent, block) {
  if (block.type === "thinking" && block.text) {
    const details = document.createElement("details");
    details.className = "msg-thinking";
    const summary = document.createElement("summary");
    summary.textContent = "Raisonnement";
    const pre = document.createElement("pre");
    pre.textContent = block.text;
    details.append(summary, pre);
    parent.appendChild(details);
    return;
  }

  if (block.type === "tool") {
    const card = document.createElement("div");
    card.className = "msg-tool";
    if (block.status === "running") card.classList.add("msg-tool-running");
    if (block.status === "error") card.classList.add("msg-tool-error");
    if (block.status === "denied") card.classList.add("msg-tool-denied");

    const head = document.createElement("div");
    head.className = "msg-tool-head";
    const icon = document.createElement("span");
    icon.className = "msg-tool-icon";
    icon.textContent = toolIcon(block.name || "");
    const label = document.createElement("span");
    label.className = "msg-tool-label";
    label.textContent = block.name || "outil";
    const status = document.createElement("span");
    status.className = "msg-tool-status";
    if (block.status === "running") status.textContent = "en cours…";
    else if (block.status === "denied") status.textContent = "permission refusée";
    else if (block.status === "error") status.textContent = "erreur";
    else status.textContent = "terminé";
    head.append(icon, label, status);
    card.appendChild(head);

    // Une commande de l'Atelier rend une carte d'action (`carte`, format
    // commun des commandes, transverse §1.8) : on la montre avant le détail.
    const action = carteDAction(block.output);
    if (action) card.appendChild(action);

    const inputStr = block.masquerDetails ? "" : formatJson(block.input);
    if (inputStr) {
      const det = document.createElement("details");
      det.className = "msg-tool-section";
      det.open = block.status === "running";
      const sum = document.createElement("summary");
      sum.textContent = "Paramètres";
      const pre = document.createElement("pre");
      pre.className = "msg-tool-body";
      pre.textContent = inputStr;
      highlightElement(pre, "json");
      det.append(sum, pre);
      card.appendChild(det);
    }

    if (block.output && !block.masquerDetails) {
      const { text: outText } = truncate(block.output);
      const det = document.createElement("details");
      det.className = "msg-tool-section";
      det.open = !resultatReplie(block.output);
      const sum = document.createElement("summary");
      sum.textContent = "Résultat";
      const pre = document.createElement("pre");
      pre.className = "msg-tool-body msg-tool-output";
      pre.textContent = outText;
      highlightElement(pre, guessOutputLang(block.name, outText));
      det.append(sum, pre);
      card.appendChild(det);
    }

    parent.appendChild(card);
    return;
  }

  if (block.type === "systeme" && block.text) {
    // Un message d'un hook (wikichat) : dit à la personne, pas par l'agent.
    const p = document.createElement("p");
    p.className = "msg-systeme";
    p.textContent = block.text;
    parent.appendChild(p);
    return;
  }

  if (block.type === "perimees") {
    parent.appendChild(carteDesPerimees(block));
    return;
  }

  if (block.type === "decision") {
    const question = block.demande?.genre === "question";
    parent.appendChild(question ? carteDeQuestion(block) : carteDeDecision(block));
    return;
  }

  if (block.type === "text" && block.text) {
    parent.appendChild(renderMarkdown(block.text));
    return;
  }
}


// Ce que le CLI donne comme cause, dit en français. Les libellés inconnus
// passent tels quels : mieux vaut l'anglais du CLI qu'un silence.
const RAISONS = {
  workingDir: "Hors des répertoires autorisés",
  permissionRule: "Une règle du projet l'interdit",
  mode: "Le mode de la conversation ne l'autorise pas",
};

/**
 * Les demandes d'un tour qui n'est plus là, rangées ensemble et repliées.
 *
 * Une demande d'autorisation dont le tour a disparu (service redémarré,
 * processus mort) restait affichée avec ses boutons, une carte par demande :
 * sept dans une seule conversation (lot H). Plus personne ne l'attend. On la
 * range donc en historique : une ligne repliée, qui dit combien il y en a ;
 * dépliée, ce que chacune demandait, et un seul geste, « Classer », qui les
 * retire pour de bon.
 */
function carteDesPerimees(block) {
  const demandes = block.demandes || [];
  const carte = document.createElement("details");
  carte.className = "msg-perimees";
  const resume = document.createElement("summary");
  resume.textContent =
    demandes.length === 1
      ? "1 demande d’un tour terminé, restée sans réponse"
      : `${demandes.length} demandes d’un tour terminé, restées sans réponse`;
  carte.appendChild(resume);
  const liste = document.createElement("ul");
  liste.className = "msg-perimees-liste";
  for (const d of demandes) {
    const li = document.createElement("li");
    const quoi = d.genre === "question" ? "Question" : d.affichage || d.outil || "outil";
    li.textContent = d.description ? `${quoi} — ${d.description}` : quoi;
    liste.appendChild(li);
  }
  carte.appendChild(liste);
  const note = document.createElement("p");
  note.className = "msg-decision-raison";
  note.textContent = "Le tour qui les attendait ne reprendra pas. Les classer les retire de la conversation.";
  carte.appendChild(note);
  const classer = document.createElement("button");
  classer.type = "button";
  classer.className = "msg-decision-btn";
  classer.textContent = "Classer";
  classer.addEventListener("click", () => {
    classer.disabled = true;
    carte.dispatchEvent(
      new CustomEvent("atelier:classer", {
        bubbles: true,
        detail: { requestIds: demandes.map((d) => d.request_id).filter(Boolean) },
      })
    );
  });
  carte.appendChild(classer);
  return carte;
}

/**
 * L'agent demande un avis, pas une permission.
 *
 * Le modèle appelle son outil de question ; l'appel nous arrive par le canal
 * des autorisations, mais ce qu'il attend est une réponse. On rend donc les
 * options telles qu'il les a écrites — libellés et descriptions — au lieu
 * d'un « autoriser / refuser » qui ne voudrait rien dire ici.
 *
 * Une seule question à choix unique se répond d'un clic : c'est le cas
 * courant, et attendre un second geste pour valider serait une cérémonie.
 * Dès qu'il y a plusieurs questions, ou un choix multiple, on rassemble et
 * l'on valide en une fois.
 */
function carteDeQuestion(block) {
  const d = block.demande || {};
  const etat = block.etat || "en_attente";
  const questions = Array.isArray(d.arguments?.questions) ? d.arguments.questions : [];
  const carte = document.createElement("div");
  carte.className = `msg-decision msg-question msg-decision-${etat}`;

  const tete = document.createElement("div");
  tete.className = "msg-decision-head";
  const marque = document.createElement("span");
  marque.className = "msg-decision-icon";
  const perdue = etat === "orpheline";
  marque.textContent = etat === "en_attente" ? "?" : perdue ? "⊘" : "✓";
  const titre = document.createElement("span");
  titre.className = "msg-decision-title";
  titre.textContent =
    etat === "en_attente"
      ? "L’agent vous demande"
      : perdue
        ? "Question restée sans réponse"
        : "Répondu";
  tete.append(marque, titre);
  carte.appendChild(tete);

  if (perdue) {
    // Contrairement à une autorisation, une question relâchée ne se rattrape
    // pas : il n'y a pas de règle à en tirer, et le modèle a déjà appris que
    // personne ne répondait. Le dire, plutôt que de laisser croire à un choix.
    const q = document.createElement("p");
    q.className = "msg-decision-cible";
    q.textContent = questions.map((x) => x.question || x.header || "").join(" / ");
    const note = document.createElement("p");
    note.className = "msg-decision-raison";
    note.textContent =
      "Personne n’a répondu à temps ; le tour est reparti sans cet avis. "
      + "Reposez la question si elle compte encore.";
    carte.append(q, note);
    return carte;
  }

  if (etat !== "en_attente") {
    // Une fois répondu, on montre ce qu'on a dit — sinon le fil garderait la
    // question sans sa réponse. Ce qui fait foi, c'est ce que le serveur a
    // envoyé au modèle ; le navigateur reconstruit ses blocs depuis le flux
    // et perdrait sa propre note.
    const lignes = String(block.resume || "")
      .split(String.fromCharCode(10))
      .map((l) => l.replace(/^-\s*/, "").trim())
      .filter((l) => l && !l.endsWith(":"));
    if (lignes.length) {
      for (const l of lignes) {
        const p = document.createElement("p");
        p.className = "msg-decision-cible";
        p.textContent = l;
        carte.appendChild(p);
      }
    } else {
      for (const [rang, q] of questions.entries()) {
        const dit = (block.reponses || [])[rang] || [];
        const p = document.createElement("p");
        p.className = "msg-decision-cible";
        p.textContent = `${q.header || q.question || ""} : ${dit.join(", ") || "(sans réponse)"}`;
        carte.appendChild(p);
      }
    }
    return carte;
  }

  const choisi = questions.map(() => []);
  const unSeulClic = questions.length === 1 && !questions[0]?.multiSelect;

  const repondre = () => {
    carte.dispatchEvent(
      new CustomEvent("atelier:decision", {
        bubbles: true,
        detail: { requestId: d.request_id, decision: "deny", reponses: choisi },
      })
    );
  };

  for (const [rang, q] of questions.entries()) {
    const bloc = document.createElement("div");
    bloc.className = "msg-question-bloc";
    const texte = document.createElement("p");
    texte.className = "msg-question-texte";
    texte.textContent = q.question || q.header || "";
    bloc.appendChild(texte);

    // Rien ne disait qu'on pouvait en cocher plusieurs : on ne l'apprenait
    // qu'en cliquant deux fois, et par hasard.
    if (q.multiSelect) {
      const indice = document.createElement("p");
      indice.className = "msg-question-indice";
      indice.textContent = "Plusieurs réponses possibles";
      bloc.appendChild(indice);
    }

    const options = Array.isArray(q.options) ? q.options : [];
    const liste = document.createElement("div");
    liste.className = "msg-question-options";
    for (const opt of options) {
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "msg-question-option";
      const libelle = document.createElement("span");
      libelle.className = "msg-question-label";
      libelle.textContent = opt.label || "";
      bouton.appendChild(libelle);
      if (opt.description) {
        const desc = document.createElement("span");
        desc.className = "msg-question-desc";
        desc.textContent = opt.description;
        bouton.appendChild(desc);
      }
      bouton.addEventListener("click", () => {
        if (q.multiSelect) {
          const i = choisi[rang].indexOf(opt.label);
          if (i >= 0) choisi[rang].splice(i, 1);
          else choisi[rang].push(opt.label);
          bouton.classList.toggle("choisie", i < 0);
          return;
        }
        choisi[rang] = [opt.label];
        for (const autre of liste.querySelectorAll(".msg-question-option")) {
          autre.classList.toggle("choisie", autre === bouton);
        }
        if (unSeulClic) repondre();
      });
      liste.appendChild(bouton);
    }
    bloc.appendChild(liste);

    // Aucune liste ne prévoit tout : on garde la porte ouverte, comme le fait
    // Claude Code avec son « Other ».
    const autre = document.createElement("input");
    autre.type = "text";
    autre.className = "msg-question-autre";
    autre.placeholder = "Autre réponse…";
    autre.addEventListener("input", () => {
      const libre = autre.value.trim();
      const retenues = choisi[rang].filter((v) =>
        options.some((o) => o.label === v)
      );
      choisi[rang] = libre ? [...retenues, libre] : retenues;
    });
    autre.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && autre.value.trim()) repondre();
    });
    bloc.appendChild(autre);
    carte.appendChild(bloc);
  }

  if (!unSeulClic) {
    const barre = document.createElement("div");
    barre.className = "msg-decision-actions";
    const valider = document.createElement("button");
    valider.type = "button";
    valider.className = "msg-decision-btn msg-decision-oui";
    valider.textContent = "Répondre";
    valider.addEventListener("click", repondre);
    barre.appendChild(valider);
    carte.appendChild(barre);
  }

  return carte;
}

/**
 * Ce qu'un « Toujours » accorderait, en toutes lettres.
 *
 * Reprend les suggestions du CLI dans l'ordre où elles portent le moins loin :
 * une commande précise avant un répertoire entier, l'outil seulement faute de
 * mieux. Le libellé dit exactement ce qu'on accorde — accorder plus large que
 * ce qu'on croit est la seule vraie faute possible ici.
 */
export function ceQueToujoursAccorde(d) {
  // Toutes les commandes suggérées, pas la première : pour `a && b` le CLI
  // en propose une par sous-commande, et « toujours » les retient toutes.
  const commandes = [];
  for (const s of d.suggestions || []) {
    if (s.type !== "addRules") continue;
    for (const r of s.rules || []) {
      if (r.ruleContent) commandes.push(r.ruleContent);
    }
  }
  if (commandes.length) return `Ne plus demander pour : ${commandes.join(", ")}`;
  for (const s of d.suggestions || []) {
    if (s.type !== "addDirectories") continue;
    for (const dossier of s.directories || []) {
      if (dossier) return `Ne plus demander dans ${dossier}`;
    }
  }
  return d.outil ? `Ne plus demander pour l’outil ${d.outil}` : "";
}

/**
 * La question posée par un tour, et les deux gestes qui la referment.
 *
 * Tout ce qu'on affiche vient de la demande du CLI — l'outil, ses arguments
 * en entier, la raison du blocage. Rien n'est deviné : c'est sa propre boîte
 * de dialogue, rendue ici.
 *
 * Les boutons n'agissent pas eux-mêmes : ils annoncent. Le contrôleur écoute
 * l'événement sur le fil et parle au serveur. Ce module reste un rendu.
 */
function carteDeDecision(block) {
  const d = block.demande || {};
  const etat = block.etat || "en_attente";
  const carte = document.createElement("div");
  carte.className = `msg-decision msg-decision-${etat}`;

  const tete = document.createElement("div");
  tete.className = "msg-decision-head";
  const marque = document.createElement("span");
  marque.className = "msg-decision-icon";
  const MARQUES = { en_attente: "⏳", allow: "✓", deny: "✕", orpheline: "⊘" };
  // Une question orpheline n'est ni accordée ni refusée : son tour n'est plus
  // là pour recevoir la réponse. Le dire, plutôt que de la faire passer pour
  // un refus.
  const TITRES = {
    en_attente: "Autorisation demandée",
    allow: "Autorisé",
    deny: "Refusé",
    orpheline: "Question sans réponse possible",
  };
  marque.textContent = MARQUES[etat] || "⏳";
  const titre = document.createElement("span");
  titre.className = "msg-decision-title";
  titre.textContent = TITRES[etat] || TITRES.en_attente;
  const outil = document.createElement("span");
  outil.className = "msg-decision-tool";
  outil.textContent = `${toolIcon(d.outil || "")} ${d.outil || "outil"}`;
  tete.append(marque, titre, outil);
  carte.appendChild(tete);

  if (d.description) {
    const quoi = document.createElement("p");
    quoi.className = "msg-decision-cible";
    quoi.textContent = d.description;
    carte.appendChild(quoi);
  }

  const raison = RAISONS[d.raison_type] || d.raison || "";
  if (raison) {
    const p = document.createElement("p");
    p.className = "msg-decision-raison";
    p.textContent = raison;
    carte.appendChild(p);
  }

  const args = block.argumentsAilleurs ? "" : formatJson(d.arguments);
  if (args) {
    const det = document.createElement("details");
    det.className = "msg-tool-section";
    det.open = etat === "en_attente";
    const sum = document.createElement("summary");
    sum.textContent = "Ce que l’outil ferait";
    const pre = document.createElement("pre");
    pre.className = "msg-tool-body";
    pre.textContent = args;
    highlightElement(pre, "json");
    det.append(sum, pre);
    carte.appendChild(det);
  }

  if (etat === "orpheline") {
    // Plus personne ne l'attend : la carte se replie en une ligne (lot H).
    // Dépliée, « Toujours » garde un sens — la décision est retenue et la
    // question ne se reposera plus — ; « Autoriser une fois » n'en a plus.
    const pli = document.createElement("details");
    pli.className = "msg-decision msg-decision-orpheline msg-decision-pliee";
    const resume = document.createElement("summary");
    resume.textContent = `Demande restée sans réponse — ${d.affichage || d.outil || "outil"}`;
    pli.appendChild(resume);
    for (const enfant of [...carte.children].slice(1)) pli.appendChild(enfant);
    const p = document.createElement("p");
    p.className = "msg-decision-raison";
    p.textContent =
      "Le tour qui l’attendait n’est plus là. Répondre ne le reprendra pas, "
      + "mais « Toujours » retiendra la décision pour la suite.";
    pli.appendChild(p);
    const toujours = ceQueToujoursAccorde(d);
    if (toujours) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "msg-decision-btn msg-decision-toujours";
      b.textContent = "Toujours";
      b.title = `${toujours} — dans cette conversation.`;
      b.addEventListener("click", () =>
        pli.dispatchEvent(
          new CustomEvent("atelier:decision", {
            bubbles: true,
            detail: { requestId: d.request_id, decision: "allow", motif: "", portee: "toujours" },
          })
        )
      );
      pli.appendChild(b);
    }
    return pli;
  } else if (etat !== "en_attente") {
    return carte;
  }

  const barre = document.createElement("div");
  barre.className = "msg-decision-actions";

  const annoncer = (decision, motif, portee) => {
    carte.dispatchEvent(
      new CustomEvent("atelier:decision", {
        bubbles: true,
        detail: {
          requestId: d.request_id,
          decision,
          motif: motif || "",
          portee: portee || "une_fois",
        },
      })
    );
  };

  const autoriser = document.createElement("button");
  autoriser.type = "button";
  autoriser.className = "msg-decision-btn msg-decision-oui";
  autoriser.textContent = "Autoriser";
  autoriser.addEventListener("click", () => annoncer("allow"));

  const refuser = document.createElement("button");
  refuser.type = "button";
  refuser.className = "msg-decision-btn msg-decision-non";
  refuser.textContent = "Refuser";

  // « Toujours » n'est pas un raccourci de confort : sans lui, dix-sept
  // questions pour un seul tour, mesuré. Il vaut pour cette conversation
  // seulement, et son infobulle dit ce qu'il accorde.
  const portee = ceQueToujoursAccorde(d);
  if (portee) {
    const toujours = document.createElement("button");
    toujours.type = "button";
    toujours.className = "msg-decision-btn msg-decision-toujours";
    toujours.textContent = "Toujours";
    toujours.title = `${portee} — dans cette conversation.`;
    toujours.addEventListener("click", () => annoncer("allow", "", "toujours"));
    barre.append(autoriser, toujours, refuser);
  } else {
    barre.append(autoriser, refuser);
  }
  carte.appendChild(barre);

  // Refuser se fait d'un clic. Un refus se rattrape — l'agent lit le refus,
  // essaie autre chose, et peut redemander : il n'y a rien à protéger par une
  // confirmation, qui ne faisait que doubler le geste (essai du 26/09).
  //
  // Refuser sans rien dire laisse pourtant l'agent deviner, et il devine
  // mal : mesuré, il en tire une théorie et repart ailleurs. La phrase reste
  // donc offerte, déjà là sous les boutons, sans être imposée : ce qui y est
  // écrit part avec le refus, et Entrée y vaut « Refuser ».
  const zone = document.createElement("div");
  zone.className = "msg-decision-motif";
  const champ = document.createElement("input");
  champ.type = "text";
  champ.placeholder = "Pourquoi refuser ? (facultatif, l’agent le lira)";
  champ.setAttribute("aria-label", "Motif du refus");
  champ.addEventListener("keydown", (e) => {
    if (e.key === "Enter") refuser.click();
  });
  zone.appendChild(champ);
  carte.appendChild(zone);

  refuser.addEventListener("click", () => annoncer("deny", (champ.value || "").trim()));

  return carte;
}

/**

 * @param {HTMLElement} parent
 * @param {{ role?: string, text?: string, blocks?: object[], attachments?: object[] }} m
 */
/**
 * De quoi reconnaître un bloc déjà rendu, sans comparer tout son contenu.
 *
 * Un identifiant d'outil ou de demande suffit à l'ancrer ; le reste dit ce
 * qui, en changeant, doit le faire redessiner — un statut, une sortie qui
 * s'allonge, un texte qui grossit.
 */
export function empreinteDuBloc(b) {
  if (b.type === "tool") {
    return [
      "tool", b.id || "", b.name || "", b.status || "",
      (b.output || "").length, JSON.stringify(b.input || "").length,
      b.masquerDetails ? "1" : "0",
      // Le repli dépend du fil affiché : passer de Code à l'Assistant redessine.
      replierToujours ? "r" : "",
    ].join(":");
  }
  if (b.type === "perimees") {
    return ["per", (b.demandes || []).map((d) => d.request_id).join(",")].join(":");
  }
  if (b.type === "decision") {
    return [
      "dec", b.demande?.request_id || "", b.etat || "",
      (b.resume || "").length, b.argumentsAilleurs ? "1" : "0",
    ].join(":");
  }
  const texte = b.text || "";
  return [b.type, texte.length, texte.slice(0, 16), texte.slice(-16)].join(":");
}

/**
 * Met le corps d'un message à jour sans le refaire.
 *
 * Un message ne changeait qu'en entier : dès qu'un bloc bougeait — un outil
 * qui apparaît, une autorisation qu'on accorde — tout était reconstruit.
 * Mesuré sur une conversation réelle : 242 blocs de code et 270 000
 * caractères refaits pour un seul changement, près de deux secondes de gel.
 * D'où le clignotement à chaque outil et à chaque réponse.
 *
 * On garde donc les nœuds dont l'empreinte n'a pas bougé. Le coût redevient
 * proportionnel à ce qui change, non à ce qui est affiché.
 */
export function synchroniserBlocs(conteneur, blocks) {
  // Une empreinte peut désigner plusieurs nœuds : deux paragraphes au texte
  // identique, deux outils de même statut et de même sortie. N'en garder qu'un
  // par empreinte faisait reconstruire tous les suivants à chaque rafraîchis-
  // sement, sans qu'aucun d'eux n'ait changé — la réutilisation s'arrêtait au
  // premier. On les file donc dans l'ordre, et l'on sert le plus ancien.
  const anciens = new Map();
  for (const n of conteneur.children) {
    const emp = n.dataset?.bloc;
    if (!emp) continue;
    const file = anciens.get(emp);
    if (file) file.push(n);
    else anciens.set(emp, [n]);
  }
  const voulus = [];
  for (const block of blocks) {
    const emp = empreinteDuBloc(block);
    const file = anciens.get(emp);
    const garde = file && file.length ? file.shift() : null;
    if (garde) {
      if (!file.length) anciens.delete(emp);
      voulus.push(garde);
      continue;
    }
    const berceau = document.createElement("div");
    appendBlock(berceau, block);
    for (const n of [...berceau.children]) {
      if (n.dataset) n.dataset.bloc = emp;
      voulus.push(n);
    }
  }
  conteneur.replaceChildren(...voulus);
}

export function appendMessageBody(parent, m) {
  // Appelable deux fois sur le même nœud sans le doubler : chaque partie a
  // son conteneur, qu'on retrouve et qu'on met à jour. C'est ce qui permet
  // de rafraîchir un message sans le reconstruire.
  const rangeeExistante = parent.querySelector(":scope > .msg-attachments");
  if (!m.attachments?.length && rangeeExistante) {
    // Le corps et le texte de repli disparaissent quand ils n'ont plus lieu
    // d'être ; cette rangée restait, vide. L'asymétrie n'avait pas de raison.
    rangeeExistante.remove();
  }
  if (m.attachments?.length) {
    let row = rangeeExistante;
    if (!row) {
      row = document.createElement("div");
      row.className = "msg-attachments";
      parent.appendChild(row);
    }
    row.replaceChildren(
      ...m.attachments.map((a) => {
        const chip = document.createElement("span");
        chip.className = "msg-attach-chip";
        chip.textContent = a.name || a.rel_path || "fichier";
        return chip;
      })
    );
  }

  let corps = parent.querySelector(":scope > .msg-blocs");
  if (m.blocks?.length) {
    if (!corps) {
      corps = document.createElement("div");
      corps.className = "msg-blocs";
      parent.appendChild(corps);
    }
    synchroniserBlocs(corps, m.blocks);
  } else if (corps) {
    corps.remove();
    corps = null;
  }

  // Le texte de repli : quand aucun bloc ne le porte déjà.
  const porteParUnBloc = (m.blocks || []).some((b) => b.type === "text" && b.text);
  let repli = parent.querySelector(":scope > .msg-repli");
  if (m.text && !porteParUnBloc) {
    if (!repli) {
      repli = document.createElement("div");
      repli.className = "msg-repli";
      parent.appendChild(repli);
    }
    if (repli.dataset.texte !== m.text) {
      repli.dataset.texte = m.text;
      repli.replaceChildren(
        m.role === "assistant"
          ? renderMarkdown(m.text)
          : Object.assign(document.createElement("div"), {
              className: "msg-text-plain",
              textContent: m.text,
            })
      );
    }
  } else if (repli) {
    repli.remove();
  }
}

