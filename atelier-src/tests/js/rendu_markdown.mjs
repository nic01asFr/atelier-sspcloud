// Banc d'essai du rendu des messages.
//
// Le rendu vit en JavaScript et n'a pas de banc à lui. Un DOM minimal suffit :
// le module ne fait que créer et assembler des nœuds. On rend un corpus, on
// compare à ce qui est attendu, et on sort en erreur au premier écart — la
// suite Python lit ce code de sortie.

class N {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.className = "";
    this.style = {};
    this._html = null;
    this._text = null;
  }
  appendChild(c) {
    this.children.push(c);
    return c;
  }
  set innerHTML(v) {
    this._html = v;
  }
  set textContent(v) {
    this._text = v;
  }
  html() {
    if (this.tagName === "#fragment") return this.children.map((c) => c.html()).join("");
    // Poser innerHTML puis ajouter un enfant garde les deux, comme un vrai DOM :
    // c'est ce qui arrive à un item de liste qui reçoit une sous-liste.
    const dedans =
      (this._html !== null ? this._html : this._text !== null ? this._text : "") +
      this.children.map((c) => c.html()).join("");
    const cls = this.className ? ` class="${this.className}"` : "";
    const al = this.style.textAlign ? ` align=${this.style.textAlign}` : "";
    const attrs = [
      this.type ? ` type=${this.type}` : "",
      this.disabled ? " disabled" : "",
      this.checked ? " coche" : "",
      this.src ? ` src="${this.src}"` : "",
    ].join("");
    if (this.tagName === "hr" || this.tagName === "input" || this.tagName === "img") {
      return `<${this.tagName}${cls}${attrs}>`;
    }
    return `<${this.tagName}${cls}${al}${attrs}>${dedans}</${this.tagName}>`;
  }
}

globalThis.location = { origin: "https://atelier.example" };
globalThis.document = {
  createElement: (t) => new N(t),
  createDocumentFragment: () => new N("#fragment"),
};

const chemin = process.argv[2];
const { renderMarkdown } = await import("file:///" + chemin.replace(/\\/g, "/"));

const rendu = (src) =>
  renderMarkdown(src)
    .html()
    .replace(/^<div class="md-root">/, "")
    .replace(/<\/div>$/, "");

// Chaque cas : un nom, une entrée, et ce que la sortie doit contenir ou non.
const CAS = [
  // ── Titres, texte, ponctuation du discours ────────────────────────────
  ["titres de tous niveaux", "# Un\n#### Quatre\n###### Six", {
    contient: ["<h1 class=\"md-heading\">Un</h1>", "<h4 class=\"md-heading\">Quatre</h4>", "<h6"],
  }],
  ["gras, italique, les deux", "**g** *i* ***gi***", {
    contient: ["<strong>g</strong>", "<em>i</em>", "<em><strong>gi</strong></em>"],
  }],
  ["emphase par tirets bas", "__g__ et _i_", {
    contient: ["<strong>g</strong>", "<em>i</em>"],
  }],
  ["un identifiant n'est pas une emphase", "la variable nom_de_chose ici", {
    absent: ["<em>"],
  }],
  ["barré", "du ~~vieux~~ texte", { contient: ["<del>vieux</del>"] }],
  ["règle horizontale", "avant\n\n---\n\naprès", {
    contient: ["<hr class=\"md-rule\">"],
    absent: ["---"],
  }],
  ["citation", "> un mot\n> deux", {
    contient: ["<blockquote class=\"md-quote\">", "un mot"],
    absent: ["&gt;"],
  }],
  ["saut de ligne dur", "un  \ndeux", { contient: ["un<br>deux"], absent: ["&lt;br&gt;"] }],
  ["échappement d'un astérisque", "littéral \\* ici", {
    contient: ["littéral * ici"],
    absent: ["<em>", "\\*"],
  }],

  // ── Code ──────────────────────────────────────────────────────────────
  ["code en ligne", "appelle `f()` ici", { contient: ["<code class=\"md-code-inline\">f()</code>"] }],
  ["le code n'est pas retouché", "le motif `a * b * c` compte", {
    contient: ["<code class=\"md-code-inline\">a * b * c</code>"],
    absent: ["<em>"],
  }],
  ["le code garde ses tirets bas", "voir `a_b_c` ici", {
    contient: ["<code class=\"md-code-inline\">a_b_c</code>"],
    absent: ["<em>"],
  }],
  ["bloc de code avec langue", "```python\nx = 1\n```", {
    contient: ["md-code-lang\">python", "md-code-block"],
  }],
  ["le markdown d'un bloc de code reste du texte", "```\n# titre\n- item\n```", {
    contient: ["# titre", "- item"],
    absent: ["<h1", "<ul"],
  }],

  // ── Listes ────────────────────────────────────────────────────────────
  ["puces des trois marqueurs", "- a\n\n* b\n\n+ c", { contient: ["<li>a</li>", "<li>b</li>", "<li>c</li>"] }],
  ["numérotation par point et par parenthèse", "1. a\n\n1) b", { contient: ["<ol class=\"md-list\"><li>a</li></ol>", "<li>b</li>"] }],
  ["liste imbriquée", "- parent\n  - enfant\n- suite", {
    contient: ["<li>parent<ul class=\"md-list\"><li>enfant</li></ul></li>", "<li>suite</li>"],
    absent: ["<p class=\"md-p\">  -"],
  }],
  ["liste de tâches", "- [ ] à faire\n- [x] fait", {
    contient: ["type=checkbox disabled>", "type=checkbox disabled coche>"],
    absent: ["[ ]", "[x]"],
  }],

  // ── Liens et images ───────────────────────────────────────────────────
  ["lien", "voir [le site](https://exemple.fr) ici", {
    contient: ["<a href=\"https://exemple.fr\" target=\"_blank\" rel=\"noopener noreferrer\">le site</a>"],
  }],
  ["lien dont l'adresse contient des parenthèses", "[doc](https://exemple.fr/a_(b)_c)", {
    contient: ["href=\"https://exemple.fr/a_(b)_c\""],
  }],
  ["adresse écrite telle quelle", "voir https://exemple.fr ici", {
    contient: ["<a href=\"https://exemple.fr\""],
  }],
  ["adresse entre chevrons", "voir <https://exemple.fr> ici", {
    contient: ["<a href=\"https://exemple.fr\""],
    absent: ["&lt;https"],
  }],
  ["la ponctuation finale reste au texte", "voir https://exemple.fr.", {
    contient: ["href=\"https://exemple.fr\"", "</a>."],
  }],
  ["une image d'ailleurs ne se charge pas seule", "![une figure](https://exemple.fr/a.png)", {
    contient: ["md-image-lien", "une figure", "exemple.fr"],
    absent: ["<img", "!<"],
  }],
  ["une image de l'Atelier s'affiche", "![jointe](https://atelier.example/v1/x.png)", {
    contient: ["<img class=\"md-image\" src=\"https://atelier.example/v1/x.png\""],
  }],
  ["une image de l'Atelier qui agirait n'est pas chargée", "![x](https://atelier.example/v1/sessions/abc/events?message=piege)", {
    contient: ["md-image-lien"],
    absent: ["<img"],
  }],
  ["une image de l'Atelier hors de /v1/ reste affichée", "![x](https://atelier.example/apps/a/logo.png)", {
    contient: ["<img class=\"md-image\""],
  }],
  ["une image sans texte de remplacement montre son adresse",
    "![](https://exemple.fr/a.png)", {
    contient: ["md-image-lien", "https://exemple.fr/a.png"],
    absent: ["<img"],
  }],

  // ── Tableaux ──────────────────────────────────────────────────────────
  ["tableau", "| a | b |\n|---|---|\n| 1 | 2 |", {
    contient: ["<table class=\"md-table\">", "<th>a</th>", "<td>1</td>"],
    absent: ["|---|"],
  }],
  ["alignements", "| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |", {
    contient: ["align=left", "align=center", "align=right"],
  }],
  ["tableau sans barre finale", "| a | b\n|---|---\n| 1 | 2", {
    contient: ["<th>a</th>", "<th>b</th>", "<td>2</td>"],
  }],
  ["ligne trop courte complétée", "| a | b |\n|---|---|\n| 1 |", {
    contient: ["<td>1</td><td></td>"],
  }],
  ["balisage dans une cellule", "| a |\n|---|\n| **x** |", { contient: ["<td><strong>x</strong></td>"] }],
  ["un texte à barres n'est pas un tableau", "| pas un tableau\nsuite", {
    contient: ["<p class=\"md-p\">| pas un tableau"],
    absent: ["<table"],
  }],
  ["le texte qui suit un tableau lui échappe", "| a |\n|---|\n| 1 |\nsuite", {
    contient: ["</table></div><p class=\"md-p\">suite</p>"],
  }],

  // ── Ce qui ne doit jamais passer ──────────────────────────────────────
  ["le HTML brut reste du texte", "<b>x</b> et <script>alert(1)</script>", {
    contient: ["&lt;script&gt;"],
    absent: ["<b>", "<script"],
  }],
  ["une image en HTML brut ne s'exécute pas", "<img src=x onerror=alert(1)>", {
    absent: ["<img src=x"],
  }],
  ["un lien javascript est refusé", "voir [piège](javascript:alert(1)) ici", {
    contient: ["voir piège ici"],
    absent: ["javascript:", "<a "],
  }],
  ["une image javascript est refusée", "![x](javascript:alert(1))", { absent: ["<img"] }],
  ["une adresse data est refusée", "[x](data:text/html,<script>)", { absent: ["<a ", "data:"] }],
  ["on ne sort pas d'un attribut par le libellé", '[a](https://x.fr" onmouseover="alert(1))', {
    absent: ["onmouseover=\"alert"],
  }],
  ["un caractère nul ne se fait pas passer pour un emplacement réservé",
    "`code` puis  0  ici", { absent: ["md-code-inline\">code</code> puis <code"] }],
];

let echecs = 0;
for (const [nom, src, attendu] of CAS) {
  const sortie = rendu(src);
  const manquant = (attendu.contient || []).filter((x) => !sortie.includes(x));
  const detrop = (attendu.absent || []).filter((x) => sortie.includes(x));
  if (manquant.length || detrop.length) {
    echecs += 1;
    console.log(`ÉCHEC  ${nom}`);
    console.log(`  entrée   : ${JSON.stringify(src)}`);
    console.log(`  sortie   : ${sortie}`);
    if (manquant.length) console.log(`  manque   : ${JSON.stringify(manquant)}`);
    if (detrop.length) console.log(`  de trop  : ${JSON.stringify(detrop)}`);
  }
}

console.log(`${CAS.length} cas, ${echecs} échec(s)`);
process.exit(echecs === 0 ? 0 : 1);
