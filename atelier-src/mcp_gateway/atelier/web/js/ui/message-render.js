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

    const inputStr = formatJson(block.input);
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

    if (block.output) {
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
    parent.appendChild(carteDeDecision(block));
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
    const p = document.createElement("p");
    p.className = "msg-decision-raison";
    p.textContent =
      "Le tour qui l’attendait n’est plus là — le service a redémarré depuis. "
      + "Relancez la demande pour décider.";
    carte.appendChild(p);
    return carte;
  }
  if (etat !== "en_attente") return carte;

  const barre = document.createElement("div");
  barre.className = "msg-decision-actions";

  const annoncer = (decision, motif) => {
    carte.dispatchEvent(
      new CustomEvent("atelier:decision", {
        bubbles: true,
        detail: { requestId: d.request_id, decision, motif: motif || "" },
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

  barre.append(autoriser, refuser);
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
