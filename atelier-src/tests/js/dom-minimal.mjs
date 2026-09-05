// Le DOM que les suites JavaScript se partagent.
//
// L'interface n'a pas de banc d'essai parce qu'un vrai DOM coûterait une
// dépendance (jsdom, donc npm, donc un package.json dans un dépôt Python).
// Or les modules de rendu ne demandent pas un navigateur : ils créent des
// nœuds, les assemblent, y accrochent des écouteurs. Ce fichier fournit
// exactement cela, et rien de plus.
//
// Ce qui est simulé a été relevé dans le code, pas deviné. Ce qui ne l'est
// pas est dit en toutes lettres à la fin du fichier — un test qui s'appuierait
// dessus mentirait.
//
// Usage : importer ce module en premier dans une suite. Il pose `document`,
// `CustomEvent` et `Event` sur `globalThis` dès son évaluation, avant que les
// modules testés ne soient chargés.

const VIDES = new Set(["hr", "input", "img", "br"]);

// Un vrai sérialiseur échappe `& < >` dans le texte, et en plus `"` dans les
// valeurs d'attributs. On fait pareil, sans quoi on ne verrait pas la
// différence entre un texte qui contient « <script> » et une balise.
function echapperTexte(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
}

function echapperAttribut(s) {
  return echapperTexte(s).replace(/"/g, "&quot;");
}

// innerHTML n'est pas analysé : on garde la chaîne telle quelle. Pour rendre
// quand même `textContent` lisible après une coloration syntaxique, on en
// retire les balises.
function texteDuHtml(html) {
  return String(html)
    .replace(/<[^>]*>/g, "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function enTiret(nom) {
  return nom.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}

/**
 * Compile un sélecteur simple.
 *
 * On accepte ce que le code utilise réellement : `:scope > .classe`, `.classe`,
 * `#identifiant`, `balise`, et leurs combinaisons collées (`div.classe`). Tout
 * le reste — descendance, virgules, attributs, pseudo-classes — lève. Mieux
 * vaut une erreur franche qu'un sélecteur qui ne trouve rien en silence et un
 * test qui passe pour de mauvaises raisons.
 */
function compilerSelecteur(selecteur) {
  let s = String(selecteur).trim();
  let direct = false;
  if (s.startsWith(":scope")) {
    s = s.slice(":scope".length).trim();
    if (!s.startsWith(">")) {
      throw new Error(`sélecteur non géré par le DOM minimal : ${selecteur}`);
    }
    s = s.slice(1).trim();
    direct = true;
  }
  if (/[\s,[\]:>~+*]/.test(s) || !s) {
    throw new Error(`sélecteur non géré par le DOM minimal : ${selecteur}`);
  }
  const morceaux = s.match(/[.#]?[A-Za-z0-9_-]+/g) || [];
  const correspond = (n) =>
    morceaux.every((m) => {
      if (m[0] === ".") return n.classList.contains(m.slice(1));
      if (m[0] === "#") return n.id === m.slice(1);
      return n.tagName === m;
    });
  return { direct, correspond };
}

class EvenementSimule {
  constructor(type, init = {}) {
    Object.assign(this, init);
    this.type = type;
    this.bubbles = !!init.bubbles;
    this.detail = init.detail;
    this.target = null;
    this.defaultPrevented = false;
    this.propagationArretee = false;
  }
  preventDefault() {
    this.defaultPrevented = true;
  }
  stopPropagation() {
    this.propagationArretee = true;
  }
}

export class Noeud {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = {};
    this.attributs = new Map();
    this.ecouteurs = new Map();
    this.id = "";
    this._classes = [];
    this._texte = null;
    this._html = null;
    // La mise en page n'existe pas ici ; ces valeurs sont là pour que le code
    // qui les lit ne casse pas, jamais pour être vérifiées.
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    this.offsetHeight = 0;
    this.selectionStart = 0;
  }

  // ── Classes ───────────────────────────────────────────────────────────
  get className() {
    return this._classes.join(" ");
  }
  set className(v) {
    this._classes = String(v || "")
      .split(/\s+/)
      .filter(Boolean);
  }
  get classList() {
    const n = this;
    return {
      add: (...cs) => {
        for (const c of cs) if (c && !n._classes.includes(c)) n._classes.push(c);
      },
      remove: (...cs) => {
        n._classes = n._classes.filter((c) => !cs.includes(c));
      },
      contains: (c) => n._classes.includes(c),
      toggle: (c, force) => {
        const present = n._classes.includes(c);
        const veut = force === undefined ? !present : !!force;
        if (veut && !present) n._classes.push(c);
        if (!veut && present) n._classes = n._classes.filter((x) => x !== c);
        return veut;
      },
      get length() {
        return n._classes.length;
      },
    };
  }

  // ── Contenu ───────────────────────────────────────────────────────────
  get textContent() {
    const propre =
      this._texte !== null ? this._texte : this._html !== null ? texteDuHtml(this._html) : "";
    return propre + this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this.detacherEnfants();
    this._html = null;
    this._texte = v == null ? "" : String(v);
  }
  get innerHTML() {
    return this.contenuHtml();
  }
  set innerHTML(v) {
    this.detacherEnfants();
    this._texte = null;
    this._html = v == null ? "" : String(v);
  }

  // ── Arbre ─────────────────────────────────────────────────────────────
  detacherEnfants() {
    for (const c of this.children) c.parentNode = null;
    this.children.length = 0;
  }
  appendChild(noeud) {
    if (!noeud) return noeud;
    if (noeud.tagName === "#fragment") {
      for (const c of [...noeud.children]) this.appendChild(c);
      noeud.children.length = 0;
      return noeud;
    }
    if (noeud.parentNode) noeud.parentNode.removeChild(noeud);
    noeud.parentNode = this;
    this.children.push(noeud);
    return noeud;
  }
  append(...morceaux) {
    for (const m of morceaux) {
      if (m == null) continue;
      if (typeof m === "string") {
        // Un vrai DOM ajoute un nœud texte à la suite ; on le représente par
        // un `<span>` sans classe, invisible à la sérialisation près.
        const t = new Noeud("#texte");
        t._texte = m;
        this.appendChild(t);
        continue;
      }
      this.appendChild(m);
    }
  }
  removeChild(noeud) {
    const i = this.children.indexOf(noeud);
    if (i >= 0) this.children.splice(i, 1);
    noeud.parentNode = null;
    return noeud;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  replaceChildren(...noeuds) {
    this.detacherEnfants();
    this._texte = null;
    this._html = null;
    this.append(...noeuds);
  }
  contains(autre) {
    for (let n = autre; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  closest(selecteur) {
    const { correspond } = compilerSelecteur(selecteur);
    for (let n = this; n; n = n.parentNode) if (correspond(n)) return n;
    return null;
  }
  descendants() {
    const out = [];
    const marcher = (n) => {
      for (const c of n.children) {
        out.push(c);
        marcher(c);
      }
    };
    marcher(this);
    return out;
  }
  querySelector(selecteur) {
    return this.querySelectorAll(selecteur)[0] || null;
  }
  querySelectorAll(selecteur) {
    const { direct, correspond } = compilerSelecteur(selecteur);
    const candidats = direct ? this.children : this.descendants();
    return candidats.filter(correspond);
  }

  // ── Attributs ─────────────────────────────────────────────────────────
  setAttribute(nom, valeur) {
    if (nom === "class") {
      this.className = valeur;
      return;
    }
    if (nom === "id") {
      this.id = String(valeur);
      return;
    }
    this.attributs.set(nom, String(valeur));
  }
  getAttribute(nom) {
    if (nom === "class") return this.className;
    if (nom === "id") return this.id;
    return this.attributs.has(nom) ? this.attributs.get(nom) : null;
  }
  hasAttribute(nom) {
    return this.getAttribute(nom) !== null;
  }
  removeAttribute(nom) {
    this.attributs.delete(nom);
  }

  // ── Événements ────────────────────────────────────────────────────────
  addEventListener(type, fn) {
    if (!this.ecouteurs.has(type)) this.ecouteurs.set(type, []);
    this.ecouteurs.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const liste = this.ecouteurs.get(type);
    if (!liste) return;
    const i = liste.indexOf(fn);
    if (i >= 0) liste.splice(i, 1);
  }
  /**
   * Remonte le long des parents quand l'événement le demande.
   *
   * C'est la moitié qui compte pour l'Atelier : les cartes de décision
   * n'agissent pas elles-mêmes, elles émettent `atelier:decision` avec
   * `bubbles`, et c'est le fil au-dessus qui l'entend. Un DOM qui ne
   * remonterait pas laisserait passer un bouton qui n'annonce rien.
   */
  dispatchEvent(ev) {
    if (!ev.target) ev.target = this;
    for (let n = this; n; n = n.parentNode) {
      ev.currentTarget = n;
      for (const fn of [...(n.ecouteurs.get(ev.type) || [])]) fn.call(n, ev);
      if (!ev.bubbles || ev.propagationArretee) break;
    }
    return !ev.defaultPrevented;
  }
  click() {
    this.dispatchEvent(new EvenementSimule("click", { bubbles: true }));
  }
  focus() {
    document.actif = this;
  }
  blur() {
    if (document.actif === this) document.actif = null;
  }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
  setSelectionRange() {}

  // ── Sérialisation ─────────────────────────────────────────────────────
  contenuHtml() {
    // Poser innerHTML puis ajouter un enfant garde les deux, comme un vrai
    // DOM : c'est ce qui arrive à un item de liste qui reçoit une sous-liste.
    const propre =
      this._html !== null
        ? this._html
        : this._texte !== null
          ? echapperTexte(this._texte)
          : "";
    return propre + this.children.map((c) => c.html()).join("");
  }
  html() {
    if (this.tagName === "#fragment" || this.tagName === "#texte") return this.contenuHtml();
    const attrs = [];
    if (this.id) attrs.push(` id="${echapperAttribut(this.id)}"`);
    if (this.className) attrs.push(` class="${echapperAttribut(this.className)}"`);
    for (const [k, v] of Object.entries(this.dataset)) {
      attrs.push(` data-${enTiret(k)}="${echapperAttribut(v)}"`);
    }
    for (const nom of ["type", "title", "placeholder", "value", "src", "href", "name"]) {
      if (this[nom] !== undefined && this[nom] !== null && this[nom] !== "") {
        attrs.push(` ${nom}="${echapperAttribut(this[nom])}"`);
      }
    }
    for (const [k, v] of [...this.attributs.entries()].sort()) {
      attrs.push(` ${k}="${echapperAttribut(v)}"`);
    }
    for (const nom of ["hidden", "disabled", "checked", "open"]) {
      if (this[nom]) attrs.push(` ${nom}`);
    }
    const styles = Object.entries(this.style)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${enTiret(k)}:${v}`);
    if (styles.length) attrs.push(` style="${echapperAttribut(styles.join(";"))}"`);
    const ouvert = `<${this.tagName}${attrs.join("")}>`;
    if (VIDES.has(this.tagName)) return ouvert;
    return `${ouvert}${this.contenuHtml()}</${this.tagName}>`;
  }
}

/** Le document simulé, reconstruit à chaque appel de `installerDom`. */
function creerDocument() {
  const corps = new Noeud("body");
  return {
    body: corps,
    actif: null,
    createElement: (t) => new Noeud(String(t).toLowerCase()),
    createDocumentFragment: () => new Noeud("#fragment"),
    createTextNode: (t) => {
      const n = new Noeud("#texte");
      n._texte = String(t);
      return n;
    },
    getElementById: (id) => corps.descendants().find((n) => n.id === id) || null,
    querySelector: (s) => corps.querySelector(s),
    querySelectorAll: (s) => corps.querySelectorAll(s),
    addEventListener: (t, f) => corps.addEventListener(t, f),
    removeEventListener: (t, f) => corps.removeEventListener(t, f),
    dispatchEvent: (e) => corps.dispatchEvent(e),
  };
}

/** Repose un document vierge. Appelée à l'import, réutilisable entre deux cas. */
export function installerDom() {
  globalThis.document = creerDocument();
  globalThis.CustomEvent = EvenementSimule;
  globalThis.Event = EvenementSimule;
  globalThis.location = globalThis.location || { origin: "https://atelier.example" };
  return globalThis.document;
}

installerDom();

// ── Ce qu'une suite utilise pour regarder et pour agir ───────────────────

/** Le nœud, sérialisé — l'équivalent d'`outerHTML`. */
export function html(noeud) {
  return noeud.html();
}

/** Ce que le nœud dit, balises retirées — l'équivalent de `textContent`. */
export function texte(noeud) {
  return noeud.textContent;
}

/** Un clic, tel que l'utilisateur le donne : il remonte le fil. */
export function cliquer(noeud) {
  noeud.click();
}

/** Une touche, pour les champs qui valident sur Entrée. */
export function frapper(noeud, touche) {
  noeud.dispatchEvent(new EvenementSimule("keydown", { bubbles: true, key: touche }));
}

/** Une saisie : la valeur change, puis on le dit, comme le navigateur. */
export function saisir(noeud, valeur) {
  noeud.value = valeur;
  noeud.dispatchEvent(new EvenementSimule("input", { bubbles: true }));
}

/**
 * Recueille les événements d'un type donné émis sous ce nœud.
 *
 * Les cartes annoncent au lieu d'agir ; c'est ce qu'on vérifie.
 */
export function ecouter(noeud, type) {
  const recus = [];
  noeud.addEventListener(type, (ev) => recus.push(ev));
  return recus;
}

/** Un parent jetable, pour rendre un bloc et regarder ce qui en sort. */
export function berceau() {
  return document.createElement("div");
}

export { EvenementSimule };

// ── Ce qui n'est pas simulé, et qu'aucun test ne doit supposer ───────────
//
// - La mise en page : pas de tailles, pas de positions, pas de défilement.
//   `getBoundingClientRect` rend des zéros, `scrollHeight` reste à zéro.
// - L'analyse de `innerHTML` : la chaîne est gardée telle quelle, elle ne
//   devient pas des nœuds. `querySelector` ne voit donc rien de ce qui a été
//   posé par `innerHTML` — seulement ce qui a été créé nœud par nœud.
// - Les sélecteurs composés : descendance (`.a .b`), virgules, attributs et
//   pseudo-classes autres que `:scope >` lèvent une erreur explicite.
// - Le rendu par défaut des balises : `<details>` est un nœud comme un autre,
//   `open` n'ouvre ni ne ferme rien.
// - Les événements natifs : rien ne part tout seul. Un clic n'existe que si la
//   suite l'envoie, et `preventDefault` n'empêche que ce que la suite lit.
