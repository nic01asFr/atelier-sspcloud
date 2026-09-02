// Vérifie que markdown.js s'évalue, et que le rendu des tableaux tient.
// Un DOM minimal suffit : le module ne fait que créer et assembler des nœuds.
class N {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.className = "";
    this.style = {};
    this._html = "";
    this._text = "";
  }
  appendChild(c) { this.children.push(c); return c; }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = v; }
  get textContent() {
    if (this._text) return this._text;
    if (this._html) return this._html.replace(/<[^>]*>/g, "");
    return this.children.map((c) => c.textContent).join(" ");
  }
  querySelectorAll(sel) {
    const tag = sel.replace(/^.*\s/, "");
    const out = [];
    const visite = (n) => {
      if (n.tagName === tag) out.push(n);
      n.children.forEach(visite);
    };
    this.children.forEach(visite);
    return out;
  }
}

globalThis.document = {
  createElement: (t) => new N(t),
  createDocumentFragment: () => new N("#fragment"),
};

const chemin = process.argv[2];
const { renderMarkdown } = await import("file:///" + chemin.replace(/\\/g, "/"));

const essai = [
  "Voici l'inventaire.",
  "",
  "| Catégorie | Points d'intérêt | Nb |",
  "|---|:---:|---:|",
  "| **Métier / territorial** | ENS13 patrimoine, `CRESO` | 12 |",
  "| Widgets | Artefactory, TaskFlow | 4 |",
  "",
  "Fin du tableau.",
].join("\n");

const root = renderMarkdown(essai);
const tables = root.querySelectorAll("table");
const paras = root.querySelectorAll("p");

const entetes = tables[0] ? tables[0].querySelectorAll("th").map((t) => t.textContent) : [];
const lignes = tables[0] ? tables[0].querySelectorAll("tr").length - 1 : 0;
const cellules = tables[0] ? tables[0].querySelectorAll("td").map((t) => t.textContent) : [];
const aligns = tables[0] ? tables[0].querySelectorAll("th").map((t) => t.style.textAlign || "-") : [];

console.log("tableaux            :", tables.length);
console.log("en-têtes            :", entetes);
console.log("alignements         :", aligns);
console.log("lignes de corps     :", lignes);
console.log("cellules            :", cellules);
console.log("paragraphes         :", paras.map((p) => p.textContent));
console.log("gras rendu          :", cellules.length ? !/\*\*/.test(cellules[0]) : false);
console.log("aucune barre restée :", !paras.some((p) => p.textContent.includes("|")));

// Un texte qui commence par une barre sans ligne de séparation reste du texte.
const faux = renderMarkdown("| pas un tableau\nsuite du texte");
console.log("faux positif évité  :", faux.querySelectorAll("table").length === 0);

const ok =
  tables.length === 1 &&
  entetes.length === 3 &&
  lignes === 2 &&
  cellules.length === 6 &&
  aligns[1] === "center" &&
  aligns[2] === "right" &&
  !paras.some((p) => p.textContent.includes("|")) &&
  faux.querySelectorAll("table").length === 0;
console.log(ok ? "\nOK" : "\nÉCHEC");
process.exit(ok ? 0 : 1);
