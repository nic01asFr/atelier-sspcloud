/** Rendu markdown des messages.
 *
 * Règle unique dont tout le reste découle : le texte est échappé d'abord, et
 * les transformations ne travaillent que sur du texte déjà échappé. Aucun HTML
 * venu du modèle ou de l'utilisateur n'atteint la page. C'est la raison pour
 * laquelle ce fichier fabrique le balisage à la main plutôt que d'appeler une
 * bibliothèque : on sait exactement ce qui sort.
 */

import { highlightCode } from "./code-highlight.js";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
function escapeHtml(s) {
  // Le caractère nul part avec le reste : il sert de garde aux emplacements
  // réservés ci-dessous, et un message qui en contiendrait un pourrait sinon
  // s'y faire passer pour l'un d'eux.
  return String(s).replace(/\u0000/g, "").replace(/[&<>"]/g, (c) => ESC[c] || c);
}

function safeUrl(href) {
  const u = String(href || "").trim();
  if (/^https?:\/\//i.test(u)) return u;
  return null;
}

// Les emplacements réservés qui mettent un fragment à l'abri des passes
// suivantes. Le caractère nul n'apparaît jamais dans du texte échappé : rien
// de ce que le modèle écrit ne peut donc en fabriquer un.
const GARDE = "\u0000";

function lienVers(url, texte) {
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${texte}</a>`;
}

function poser(mis, html) {
  mis.push(html);
  return `${GARDE}${mis.length - 1}${GARDE}`;
}

function reposer(s, mis) {
  return s.replace(new RegExp(`${GARDE}(\\d+)${GARDE}`, "g"), (_, n) => mis[Number(n)]);
}

// Ce qu'une contre-oblique rend littéral, d'après CommonMark. Écrit en
// expression littérale : bâtie par concaténation de chaînes, le crochet
// fermant de la liste refermait la classe avant l'heure, et plus rien n'était
// jamais échappé.
const ECHAPPEMENT = /\\([\\`*_{}[\]()#+\-.!~>|])/g;

// Une URL entre parenthèses peut elle-même en contenir une paire — c'est le cas
// de bien des liens de documentation. Sans cela le lien se coupait au premier
// signe fermant, et le reste de l'adresse restait affiché en clair.
const CIBLE = String.raw`\(((?:[^()\s]|\([^()]*\))+)\)`;
const IMAGE = new RegExp(String.raw`!\[([^\]]*)\]` + CIBLE, "g");
const LIEN = new RegExp(String.raw`\[([^\]]+)\]` + CIBLE, "g");
// Une adresse écrite telle quelle, sans balisage autour. Les esperluettes du
// texte sont déjà échappées : on accepte `&amp;` pour ne pas couper une URL à
// son premier paramètre, et on laisse la ponctuation finale au texte.
const URL_NUE = /(^|[\s(])(https?:\/\/(?:[^\s<>"'`&]|&amp;)+)/g;
const URL_CHEVRONS = /&lt;(https?:\/\/(?:[^\s<>"'`&]|&amp;)+)&gt;/g;
const PONCTUATION_FINALE = /[.,;:!?]+$/;

/**
 * Le balisage qui vit à l'intérieur d'une ligne.
 *
 * L'ordre n'est pas indifférent. Le code passe en premier et se met à l'abri :
 * sans cela `a * b * c` entre accents graves ressortait avec un `<em>` au
 * milieu — du code affiché faux, ce qui est pire que du code non stylé. Les
 * échappements viennent ensuite, pour qu'un astérisque protégé ne soit pas lu
 * comme une emphase.
 */
function inlineMarkdown(escaped) {
  const mis = [];
  let s = escaped;

  s = s.replace(/(`+)([\s\S]*?)\1/g, (_, __, code) =>
    poser(mis, `<code class="md-code-inline">${code}</code>`)
  );
  s = s.replace(ECHAPPEMENT, (_, c) => poser(mis, c));

  s = s.replace(IMAGE, (entier, alt, href) => {
    const url = safeUrl(href);
    if (!url) return alt;
    return poser(
      mis,
      `<img class="md-image" src="${escapeHtml(url)}" alt="${alt}" loading="lazy">`
    );
  });
  s = s.replace(LIEN, (entier, label, href) => {
    const url = safeUrl(href);
    if (!url) return label;
    return poser(mis, lienVers(url, label));
  });
  s = s.replace(URL_CHEVRONS, (entier, href) => {
    const url = safeUrl(href);
    return url ? poser(mis, lienVers(url, url)) : entier;
  });
  s = s.replace(URL_NUE, (entier, avant, href) => {
    const fin = href.match(PONCTUATION_FINALE);
    const propre = fin ? href.slice(0, -fin[0].length) : href;
    const url = safeUrl(propre);
    if (!url) return entier;
    return avant + poser(mis, lienVers(url, propre)) + (fin ? fin[0] : "");
  });

  s = s.replace(/\*\*\*([\s\S]+?)\*\*\*/g, "<em><strong>$1</strong></em>");
  s = s.replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>");
  // Les tirets bas ne comptent qu'aux bords d'un mot : sans cette réserve,
  // `nom_de_variable` ressortait coupé par une emphase.
  s = s.replace(/(^|[^\w])__([^_]+)__(?!\w)/g, "$1<strong>$2</strong>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^\w_])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  s = s.replace(/~~([\s\S]+?)~~/g, "<del>$1</del>");

  return reposer(s, mis);
}

// ── Les blocs ────────────────────────────────────────────────────────────

const TITRE = /^(#{1,6})\s+(.*)$/;
const REGLE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const CITATION = /^\s*>\s?(.*)$/;
const PUCE = /^(\s*)([-*+])\s+(.*)$/;
const NUMERO = /^(\s*)(\d+)[.)]\s+(.*)$/;
const TACHE = /^\[([ xX])\]\s+(.*)$/;
const LIGNE_TABLEAU = /^\s*\|.*$/;
// La ligne de séparation, qui seule distingue un tableau d'un texte à barres :
// des tirets, des deux-points d'alignement, et des barres.
const SEPARATEUR = /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/;

function estUneListe(ligne) {
  return PUCE.test(ligne) || NUMERO.test(ligne);
}

function debutDeTableau(lines, i) {
  return (
    LIGNE_TABLEAU.test(lines[i]) &&
    i + 1 < lines.length &&
    SEPARATEUR.test(lines[i + 1]) &&
    lines[i + 1].includes("|")
  );
}

function cellules(ligne) {
  return ligne
    .trim()
    .replace(/^\|/, "")
    .replace(/\|\s*$/, "")
    .split(/(?<!\\)\|/)
    .map((c) => c.trim());
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
 * Construit le tableau qui commence à `depart`, et rend l'indice de la ligne
 * qui le suit. Les lignes plus courtes que l'en-tête sont complétées : une
 * cellule vide vaut mieux qu'un tableau qui se décale.
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

  // Un tableau large défile dans sa boîte plutôt que de pousser la conversation.
  const boite = document.createElement("div");
  boite.className = "md-table-wrap";
  boite.appendChild(table);
  return { el: boite, suivant: i };
}

function contenuDeLItem(li, texte) {
  const tache = texte.match(TACHE);
  if (!tache) {
    li.innerHTML = inlineMarkdown(escapeHtml(texte));
    return;
  }
  li.className = "md-task";
  const case_ = document.createElement("input");
  case_.type = "checkbox";
  case_.disabled = true;
  case_.checked = tache[1].toLowerCase() === "x";
  li.appendChild(case_);
  const dit = document.createElement("span");
  dit.innerHTML = inlineMarkdown(escapeHtml(tache[2]));
  li.appendChild(dit);
}

/**
 * Construit la liste qui commence à `depart`, imbrications comprises.
 *
 * Sans cette reconnaissance de l'indentation, une sous-liste sortait de sa
 * liste et s'affichait en paragraphe, tirets compris — ce qui arrive à chaque
 * plan un peu structuré.
 */
function construireListe(lines, depart) {
  const premier = lines[depart].match(PUCE) || lines[depart].match(NUMERO);
  const retrait = premier[1].length;
  const ordonnee = !PUCE.test(lines[depart]);
  const liste = document.createElement(ordonnee ? "ol" : "ul");
  liste.className = "md-list";

  let i = depart;
  let dernier = null;
  while (i < lines.length) {
    const ligne = lines[i];
    if (!ligne.trim() || !estUneListe(ligne)) break;
    const m = ligne.match(PUCE) || ligne.match(NUMERO);
    const indent = m[1].length;
    if (indent < retrait) break;
    if (indent > retrait) {
      // Une sous-liste appartient à l'item qui la précède.
      const sous = construireListe(lines, i);
      (dernier || liste).appendChild(sous.el);
      i = sous.suivant;
      continue;
    }
    const li = document.createElement("li");
    contenuDeLItem(li, m[3]);
    liste.appendChild(li);
    dernier = li;
    i += 1;
  }
  return { el: liste, suivant: i };
}

function construireCitation(lines, depart) {
  const dedans = [];
  let i = depart;
  while (i < lines.length && CITATION.test(lines[i])) {
    dedans.push(lines[i].match(CITATION)[1]);
    i += 1;
  }
  const bq = document.createElement("blockquote");
  bq.className = "md-quote";
  // Une citation peut contenir n'importe quoi d'autre : on repasse dessus.
  bq.appendChild(renderProse(dedans.join("\n")));
  return { el: bq, suivant: i };
}

/**
 * Un saut de ligne dur — deux espaces en fin de ligne, ou une contre-oblique —
 * se voit. Un simple retour à la ligne reste un pli du texte, comme partout
 * ailleurs en markdown.
 */
function joindreParagraphe(lignesEchappees) {
  return lignesEchappees
    .map((l, n) => {
      const dur = /(\s{2,}|\\)$/.test(l);
      const nu = l.replace(/(\s{2,}|\\)$/, "");
      if (n === lignesEchappees.length - 1) return nu;
      return nu + (dur ? "<br>" : "\n");
    })
    .join("");
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
    if (REGLE.test(line)) {
      const hr = document.createElement("hr");
      hr.className = "md-rule";
      frag.appendChild(hr);
      i += 1;
      continue;
    }
    const titre = line.match(TITRE);
    if (titre) {
      const el = document.createElement(`h${titre[1].length}`);
      el.className = "md-heading";
      el.innerHTML = inlineMarkdown(escapeHtml(titre[2]));
      frag.appendChild(el);
      i += 1;
      continue;
    }
    if (CITATION.test(line)) {
      const { el, suivant } = construireCitation(lines, i);
      frag.appendChild(el);
      i = suivant;
      continue;
    }
    if (debutDeTableau(lines, i)) {
      const { el, suivant } = construireTableau(lines, i);
      frag.appendChild(el);
      i = suivant;
      continue;
    }
    if (estUneListe(line)) {
      const { el, suivant } = construireListe(lines, i);
      frag.appendChild(el);
      i = suivant;
      continue;
    }
    const pLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !TITRE.test(lines[i]) &&
      !REGLE.test(lines[i]) &&
      !CITATION.test(lines[i]) &&
      !estUneListe(lines[i]) &&
      // Sans cette condition, le paragraphe avalait le bloc qui le suit et le
      // rendait tel quel, barres comprises. C'est ce qu'on voyait à l'écran.
      !debutDeTableau(lines, i)
    ) {
      pLines.push(lines[i]);
      i += 1;
    }
    const p = document.createElement("p");
    p.className = "md-p";
    // L'échappement passe avant l'assemblage : posé après, il transformait le
    // <br> d'un saut de ligne dur en texte visible.
    p.innerHTML = inlineMarkdown(joindreParagraphe(pLines.map(escapeHtml)));
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
