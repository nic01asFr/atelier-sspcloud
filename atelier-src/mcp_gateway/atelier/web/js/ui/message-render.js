/** Rendu blocs message (texte markdown, thinking, outils, permissions). */

import { renderMarkdown } from "./markdown.js";
import { highlightElement } from "./code-highlight.js";

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

function truncate(text, max = 4000) {
  const s = String(text || "");
  if (s.length <= max) return { text: s, truncated: false };
  return { text: s.slice(0, max) + "\n… (tronqué)", truncated: true };
}

/**
 * @param {HTMLElement} parent
 * @param {{ type: string, text?: string, name?: string, id?: string, input?: unknown, output?: string, status?: string }} block
 */
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
      det.open = true;
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
function ceQueToujoursAccorde(d) {
  for (const s of d.suggestions || []) {
    if (s.type !== "addRules") continue;
    for (const r of s.rules || []) {
      if (r.ruleContent) return `Ne plus demander pour : ${r.ruleContent}`;
    }
  }
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
    // Répondre a encore un sens : le tour ne reprendra pas, mais un
    // « Toujours » retient la décision et la question ne se reposera plus.
    const p = document.createElement("p");
    p.className = "msg-decision-raison";
    p.textContent =
      "Le tour qui l’attendait n’est plus là. Répondre ne le reprendra pas, "
      + "mais « Toujours » retiendra la décision pour la suite.";
    carte.appendChild(p);
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

  // Refuser sans rien dire laisse l'agent deviner, et il devine mal : mesuré,
  // il en tire une théorie et repart ailleurs. On offre donc la phrase, sans
  // l'imposer.
  refuser.addEventListener("click", () => {
    if (carte.querySelector(".msg-decision-motif")) return;
    const zone = document.createElement("div");
    zone.className = "msg-decision-motif";
    const champ = document.createElement("input");
    champ.type = "text";
    champ.placeholder = "Pourquoi ? (facultatif, l’agent le lira)";
    const valider = document.createElement("button");
    valider.type = "button";
    valider.className = "msg-decision-btn msg-decision-non";
    valider.textContent = "Confirmer le refus";
    valider.addEventListener("click", () => annoncer("deny", champ.value.trim()));
    champ.addEventListener("keydown", (e) => {
      if (e.key === "Enter") valider.click();
    });
    zone.append(champ, valider);
    carte.appendChild(zone);
    champ.focus();
  });

  return carte;
}

/**

 * @param {HTMLElement} parent
 * @param {{ role?: string, text?: string, blocks?: object[], attachments?: object[] }} m
 */
export function appendMessageBody(parent, m) {
  if (m.attachments?.length) {
    const row = document.createElement("div");
    row.className = "msg-attachments";
    for (const a of m.attachments) {
      const chip = document.createElement("span");
      chip.className = "msg-attach-chip";
      chip.textContent = a.name || a.rel_path || "fichier";
      row.appendChild(chip);
    }
    parent.appendChild(row);
  }
  if (m.blocks?.length) {
    for (const block of m.blocks) {
      appendBlock(parent, block);
    }
    const hasTextBlock = m.blocks.some((b) => b.type === "text" && b.text);
    if (!hasTextBlock && m.text) {
      parent.appendChild(renderMarkdown(m.text));
    }
  } else if (m.text) {
    if (m.role === "assistant") {
      parent.appendChild(renderMarkdown(m.text));
    } else {
      const el = document.createElement("div");
      el.className = "msg-text-plain";
      el.textContent = m.text;
      parent.appendChild(el);
    }
  }
}
