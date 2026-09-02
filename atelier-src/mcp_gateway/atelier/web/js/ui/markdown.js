/** Rendu markdown safe (assistant) — pas de HTML brut utilisateur. */

import { highlightCode } from "./code-highlight.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ESC[c] || c);
}

function safeUrl(href) {
  const u = String(href || "").trim();
  if (/^https?:\/\//i.test(u)) return u;
  return null;
}

function inlineMarkdown(escaped) {
  let s = escaped;
  s = s.replace(/`([^`]+)`/g, "<code class=\"md-code-inline\">$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, href) => {
    const url = safeUrl(href);
    if (!url) return label;
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  return s;
}

// Une ligne de tableau : au moins une barre, et rien d'autre qu'elle pour la
// reconnaitre. On n'exige pas la barre finale — les modeles l'omettent.
const LIGNE_TABLEAU = /^\s*\|.*$/;
// La ligne de separation, qui seule distingue un tableau d'un texte a barres :
// des tirets, des deux-points d'alignement, et des barres.
const SEPARATEUR = /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/;

function cellules(ligne) {
  return ligne
    .trim()
    .replace(/^\|/, "")
    .replace(/\|\s*$/, "")
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, "|"));
}

function alignements(ligne) {
  return cellules(ligne).map((c) => {
    const gauche = c.startsWith(":");
    const droite = c.endsWith(":");
    if (gauche && droite) return "center";
    if (droite) return "right";
    return gauche ? "left" : "";
  });
}

function remplirLigne(tr, valeurs, aligns, balise) {
  valeurs.forEach((valeur, n) => {
    const cell = document.createElement(balise);
    if (aligns[n]) cell.style.textAlign = aligns[n];
    cell.innerHTML = inlineMarkdown(escapeHtml(valeur));
    tr.appendChild(cell);
  });
}

/**
 * Construit le tableau qui commence a `depart`, et rend l'indice de la ligne
 * qui le suit. Les lignes plus courtes que l'en-tete sont completees : une
 * cellule manquante vaut mieux qu'un tableau qui se decale.
 */
function construireTableau(lines, depart) {
  const entetes = cellules(lines[depart]);
  const aligns = alignements(lines[depart + 1]);
  const table = document.createElement("table");
  table.className = "md-table";

  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  remplirLigne(trh, entetes, aligns, "th");
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  let i = depart + 2;
  while (i < lines.length && LIGNE_TABLEAU.test(lines[i]) && lines[i].trim()) {
    const valeurs = cellules(lines[i]);
    while (valeurs.length < entetes.length) valeurs.push("");
    const tr = document.createElement("tr");
    remplirLigne(tr, valeurs.slice(0, entetes.length), aligns, "td");
    tbody.appendChild(tr);
    i += 1;
  }
  table.appendChild(tbody);

  // Un tableau large doit defiler dans sa boite, pas pousser la conversation.
  const boite = document.createElement("div");
  boite.className = "md-table-wrap";
  boite.appendChild(table);
  return { el: boite, suivant: i };
}

function renderProse(text) {
  const frag = document.createDocumentFragment();
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^#{1,3}\s+/.test(line)) {
      const level = line.match(/^#+/)[0].length;
      const el = document.createElement(`h${Math.min(level, 3)}`);
      el.className = "md-heading";
      el.innerHTML = inlineMarkdown(escapeHtml(line.replace(/^#+\s+/, "")));
      frag.appendChild(el);
      i += 1;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const ul = document.createElement("ul");
      ul.className = "md-list";
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        const li = document.createElement("li");
        li.innerHTML = inlineMarkdown(escapeHtml(lines[i].replace(/^[-*]\s+/, "")));
        ul.appendChild(li);
        i += 1;
      }
      frag.appendChild(ul);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const ol = document.createElement("ol");
      ol.className = "md-list";
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        const li = document.createElement("li");
        li.innerHTML = inlineMarkdown(escapeHtml(lines[i].replace(/^\d+\.\s+/, "")));
        ol.appendChild(li);
        i += 1;
      }
      frag.appendChild(ol);
      continue;
    }
    // Le tableau se reconnait a sa ligne de separation, jamais a la premiere
    // ligne seule : un texte qui commence par une barre n'est pas un tableau.
    if (
      LIGNE_TABLEAU.test(line) &&
      i + 1 < lines.length &&
      SEPARATEUR.test(lines[i + 1]) &&
      lines[i + 1].includes("|")
    ) {
      const { el, suivant } = construireTableau(lines, i);
      frag.appendChild(el);
      i = suivant;
      continue;
    }
    const pLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^#{1,3}\s+/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i]) &&
      // Sans cette condition, le paragraphe avalait le tableau qui le suit et
      // le rendait tel quel, barres comprises. C'est ce qu'on voyait a l'ecran.
      !(LIGNE_TABLEAU.test(lines[i]) && i + 1 < lines.length && SEPARATEUR.test(lines[i + 1]) && lines[i + 1].includes("|"))
    ) {
      pLines.push(lines[i]);
      i += 1;
    }
    const p = document.createElement("p");
    p.className = "md-p";
    p.innerHTML = inlineMarkdown(escapeHtml(pLines.join("\n")));
    frag.appendChild(p);
  }
  return frag;
}

/**
 * @param {string} text
 * @returns {HTMLElement}
 */
export function renderMarkdown(text) {
  const root = document.createElement("div");
  root.className = "md-root";
  const src = String(text || "");
  const parts = src.split(/(```[\w-]*\n[\s\S]*?```)/g);
  for (const part of parts) {
    if (!part) continue;
    const fence = part.match(/^```([\w-]*)\n([\s\S]*)```$/);
    if (fence) {
      const lang = fence[1] || "";
      const code = fence[2].replace(/\n$/, "");
      const wrap = document.createElement("div");
      wrap.className = "md-code-wrap";
      if (lang) {
        const label = document.createElement("div");
        label.className = "md-code-lang";
        label.textContent = lang;
        wrap.appendChild(label);
      }
      const pre = document.createElement("pre");
      pre.className = "md-code-block";
      const codeEl = document.createElement("code");
      codeEl.className = "hl-root";
      codeEl.innerHTML = highlightCode(code, lang);
      pre.appendChild(codeEl);
      wrap.appendChild(pre);
      root.appendChild(wrap);
    } else {
      root.appendChild(renderProse(part));
    }
  }
  return root;
}
