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

function applyRule(html, re, cls) {
  return html.replace(re, (m) => `<span class="${cls}">${m}</span>`);
}

function highlightJson(html) {
  html = applyRule(html, /"(?:\\.|[^"\\])*"/g, "hl-str");
  html = applyRule(html, /\b(true|false|null)\b/g, "hl-kw");
  html = applyRule(html, /-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/g, "hl-num");
  return html;
}

function highlightBash(html) {
  html = applyRule(html, /(^|\n)(#[^\n]*)/g, "$1<span class=\"hl-cmt\">$2</span>");
  html = applyRule(html, /(\$\{[^}]+\}|\$[A-Za-z_][\w]*)/g, "hl-var");
  html = applyRule(
    html,
    /\b(if|then|else|fi|for|do|done|case|esac|while|function|return|export|local|echo|cd|cat|grep|python3?)\b/g,
    "hl-kw"
  );
  html = applyRule(html, /"[^"]*"/g, "hl-str");
  html = applyRule(html, /'[^']*'/g, "hl-str");
  return html;
}

function highlightPython(html) {
  html = applyRule(html, /(#.*$)/gm, "<span class=\"hl-cmt\">$1</span>");
  html = applyRule(
    html,
    /\b(def|class|if|elif|else|for|while|return|import|from|as|with|try|except|raise|pass|lambda|yield|async|await|True|False|None)\b/g,
    "hl-kw"
  );
  html = applyRule(html, /"[^"\\]*(?:\\.[^"\\]*)*"/g, "hl-str");
  html = applyRule(html, /'[^'\\]*(?:\\.[^'\\]*)*'/g, "hl-str");
  html = applyRule(html, /\b\d+(?:\.\d+)?\b/g, "hl-num");
  return html;
}

function highlightJavascript(html) {
  html = applyRule(html, /(\/\/.*$|\/\*[\s\S]*?\*\/)/gm, "<span class=\"hl-cmt\">$1</span>");
  html = applyRule(
    html,
    /\b(const|let|var|function|return|if|else|for|while|class|extends|import|export|from|async|await|new|typeof|instanceof|null|undefined|true|false)\b/g,
    "hl-kw"
  );
  html = applyRule(html, /"[^"\\]*(?:\\.[^"\\]*)*"/g, "hl-str");
  html = applyRule(html, /'[^'\\]*(?:\\.[^'\\]*)*'/g, "hl-str");
  html = applyRule(html, /\b\d+(?:\.\d+)?\b/g, "hl-num");
  return html;
}

const HIGHLIGHTERS = {
  json: highlightJson,
  bash: highlightBash,
  python: highlightPython,
  javascript: highlightJavascript,
  typescript: highlightJavascript,
  yaml: highlightJson,
};

/**
 * @param {string} code
 * @param {string} lang
 * @returns {string} HTML safe
 */
export function highlightCode(code, lang) {
  const html = escapeHtml(code);
  const fn = HIGHLIGHTERS[normalizeLang(lang)];
  return fn ? fn(html) : html;
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
