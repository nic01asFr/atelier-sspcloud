/** Coloration syntaxique légère (sans dépendance externe). */

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ESC[c] || c);
}

const LANG_ALIASES = {
  js: "javascript",
  ts: "typescript",
  py: "python",
  sh: "bash",
  shell: "bash",
  yml: "yaml",
};

function normalizeLang(lang) {
  const l = String(lang || "").trim().toLowerCase();
  return LANG_ALIASES[l] || l;
}

/**
 * Une seule passe, une seule expression : chaque morceau du texte n'est
 * colorié qu'une fois.
 *
 * Les règles s'appliquaient l'une après l'autre sur le HTML déjà produit, et
 * la règle des chaînes trouvait alors ses guillemets dans `class="hl-kw"` —
 * le balisage se déchirait et l'écran montrait `"hl-kw">python` en clair au
 * milieu des sorties d'outils. Ici la première règle qui prend gagne, à la
 * position où elle prend, et le reste du texte n'est jamais relu.
 *
 * L'ordre des règles est celui de la priorité : un commentaire avant une
 * chaîne, une chaîne avant un mot-clé.
 */
function tokenize(html, regles) {
  const re = new RegExp(regles.map(([source]) => `(${source})`).join("|"), "gm");
  return html.replace(re, (...args) => {
    const groupes = args.slice(1, 1 + regles.length);
    const rang = groupes.findIndex((g) => g !== undefined);
    if (rang < 0) return args[0];
    return `<span class="${regles[rang][1]}">${args[0]}</span>`;
  });
}

const CHAINE_DOUBLE = String.raw`"[^"\\]*(?:\\.[^"\\]*)*"`;
const CHAINE_SIMPLE = String.raw`'[^'\\]*(?:\\.[^'\\]*)*'`;
const NOMBRE = String.raw`\b\d+(?:\.\d+)?\b`;

const REGLES = {
  json: [
    [CHAINE_DOUBLE, "hl-str"],
    [String.raw`\b(?:true|false|null)\b`, "hl-kw"],
    [String.raw`-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b`, "hl-num"],
  ],
  bash: [
    [String.raw`(?:^|(?<=\n))#[^\n]*`, "hl-cmt"],
    [CHAINE_DOUBLE, "hl-str"],
    [CHAINE_SIMPLE, "hl-str"],
    [String.raw`\$\{[^}]+\}|\$[A-Za-z_]\w*`, "hl-var"],
    [
      String.raw`\b(?:if|then|else|fi|for|do|done|case|esac|while|function|return|export|local|echo|cd|cat|grep|python3?)\b`,
      "hl-kw",
    ],
  ],
  python: [
    [String.raw`#.*$`, "hl-cmt"],
    [CHAINE_DOUBLE, "hl-str"],
    [CHAINE_SIMPLE, "hl-str"],
    [
      String.raw`\b(?:def|class|if|elif|else|for|while|return|import|from|as|with|try|except|raise|pass|lambda|yield|async|await|True|False|None)\b`,
      "hl-kw",
    ],
    [NOMBRE, "hl-num"],
  ],
  javascript: [
    [String.raw`//.*$|/\*[\s\S]*?\*/`, "hl-cmt"],
    [CHAINE_DOUBLE, "hl-str"],
    [CHAINE_SIMPLE, "hl-str"],
    [
      String.raw`\b(?:const|let|var|function|return|if|else|for|while|class|extends|import|export|from|async|await|new|typeof|instanceof|null|undefined|true|false)\b`,
      "hl-kw",
    ],
    [NOMBRE, "hl-num"],
  ],
};
REGLES.typescript = REGLES.javascript;
REGLES.yaml = REGLES.json;

/**
 * @param {string} code
 * @param {string} lang
 * @returns {string} HTML safe
 */
export function highlightCode(code, lang) {
  const html = escapeHtml(code);
  const regles = REGLES[normalizeLang(lang)];
  return regles ? tokenize(html, regles) : html;
}

/**
 * @param {HTMLElement} el — pre ou code
 * @param {string} lang
 */
export function highlightElement(el, lang) {
  if (!el) return;
  const text = el.textContent || "";
  if (!text.trim()) return;
  el.innerHTML = highlightCode(text, lang);
  el.classList.add("hl-root");
}
