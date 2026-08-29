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

  if (block.type === "text" && block.text) {
    parent.appendChild(renderMarkdown(block.text));
    return;
  }
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
