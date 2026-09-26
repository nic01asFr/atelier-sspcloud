#!/usr/bin/env node
/**
 * Génère la vitrine bilingue de l'Atelier depuis site/vitrine.json :
 *   dist/index.html     (français, langue par défaut)
 *   dist/en/index.html  (anglais)
 *   dist/assets/        (captures, icône)
 * Ne pas éditer le HTML produit à la main : régénérer.
 *
 * Dans vitrine.json, un texte est soit une chaîne neutre (nom, URL, tags),
 * soit un objet {"fr": "...", "en": "..."}. Tout texte que la page affiche
 * vient de là, libellés compris : le générateur n'écrit aucune phrase dans une
 * langue donnée, sinon elle finirait sur la mauvaise page.
 *
 * Ce qui peut se lire dans le code n'est jamais recopié dans vitrine.json :
 *   - la version, dans le chart ;
 *   - les vues de l'interface, dans son index.html ;
 *   - le nombre de contrôles des gardiens, dans leur déclaration ;
 *   - les couleurs des deux thèmes, dans les jetons de l'interface
 *     (web/css/jetons.css), repris tels quels : la vitrine a la même identité
 *     que l'Atelier, et suit son thème clair ou sombre.
 *
 * Sortie : site/dist par défaut, ou le dossier passé dans SITE_OUT. On
 * n'écrit que nos fichiers, sans vider le dossier : la CI y dépose aussi
 * index.yaml et les archives du chart.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(ROOT, "..");
const VITRINE = path.join(ROOT, "vitrine.json");
const CHART_DIR = path.join(REPO, "charts", "atelier");
const WEB_DIR = path.join(REPO, "atelier-src", "mcp_gateway", "atelier", "web");
const GARDIENS = path.join(REPO, "atelier-src", "mcp_gateway", "gardiens", "gardiens.json");
const DIST = process.env.SITE_OUT || path.join(ROOT, "dist");
export const PAGES_URL = "https://nic01asfr.github.io/atelier-sspcloud";
export const GUIDE_URL = "https://github.com/nic01asFr/atelier-sspcloud/blob/main/docs/fonctionnalites.md";

/** Les langues publiées. La première est la page racine et le x-default. */
export const LANGUES = [
  { code: "fr", libelle: "FR", dossier: "" },
  { code: "en", libelle: "EN", dossier: "en/" },
];
const CODES = LANGUES.map((l) => l.code);

/** Les statuts d'une brique, et la clé de leur libellé dans `interface`. */
export const STATUTS = { service: "enService", integre: "integre", enPartie: "enPartie", pasFait: "pasFait" };

export function echapper(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    // Typographie française : les guillemets et deux-points ne passent pas
    // seuls à la ligne. Sans effet sur un texte anglais, qui n'a pas ces
    // espaces.
    .replace(/« /g, "«&nbsp;")
    .replace(/ »/g, "&nbsp;»")
    .replace(/ ([:;?!])/g, "&nbsp;$1");
}

const estObjet = (o) => o !== null && typeof o === "object" && !Array.isArray(o);

/** Un objet de traduction : ses clés sont des codes de langue, et rien d'autre. */
export function estTraduction(o) {
  if (!estObjet(o)) return false;
  const cles = Object.keys(o);
  return cles.length > 0 && cles.some((k) => CODES.includes(k)) && cles.every((k) => CODES.includes(k));
}

/**
 * Parcourt la vitrine et rend la liste des traductions incomplètes, chacune
 * avec le chemin de sa clé (ex. « cas.liste[2].titre : en manquant »).
 * Un objet qui porte une clé de langue parmi d'autres clés est aussi signalé :
 * c'est presque toujours une traduction mal rangée.
 */
export function verifierTraductions(v, chemin = "") {
  const erreurs = [];
  if (Array.isArray(v)) {
    v.forEach((x, i) => erreurs.push(...verifierTraductions(x, `${chemin}[${i}]`)));
    return erreurs;
  }
  if (!estObjet(v)) return erreurs;
  const cles = Object.keys(v);
  const langues = cles.filter((k) => CODES.includes(k));
  if (langues.length) {
    const ici = chemin || "(racine)";
    if (langues.length !== cles.length) {
      erreurs.push(`${ici} : clés de langue mêlées à d'autres clés (${cles.join(", ")})`);
    }
    for (const code of CODES) {
      const t = v[code];
      if (typeof t !== "string" || t.trim() === "") {
        erreurs.push(`${ici} : ${code} manquant ou vide`);
      }
    }
    return erreurs;
  }
  for (const k of cles) erreurs.push(...verifierTraductions(v[k], chemin ? `${chemin}.${k}` : k));
  return erreurs;
}

/** Remplace chaque objet de traduction par son texte dans la langue voulue. */
export function localiser(v, langue, gabarits = {}) {
  if (Array.isArray(v)) return v.map((x) => localiser(x, langue, gabarits));
  if (estTraduction(v)) return substituer(v[langue], gabarits);
  if (estObjet(v)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, localiser(x, langue, gabarits)]));
  }
  return typeof v === "string" ? substituer(v, gabarits) : v;
}

function substituer(s, gabarits) {
  return String(s).replace(/\{\{(\w+)\}\}/g, (m, nom) => (nom in gabarits ? gabarits[nom] : m));
}

const REQUIS = ["nom", "pitch", "depot", "interface", "promesse", "capacites", "visite", "cas", "associations", "architecture", "installer", "limites"];

export function chargerVitrine(fichier = VITRINE) {
  const v = JSON.parse(fs.readFileSync(fichier, "utf8"));
  for (const k of REQUIS) {
    if (v[k] == null || (Array.isArray(v[k]) && v[k].length === 0)) {
      throw new Error(`vitrine.json: champ requis manquant ou vide: ${k}`);
    }
  }
  const statuts = [
    ...(v.capacites.familles || []).flatMap((f) => f.items || []),
    ...(v.cas.liste || []),
  ];
  for (const s of statuts) {
    if (!(s.statut in STATUTS)) {
      throw new Error(`vitrine.json: statut inconnu « ${s.statut} » (${Object.keys(STATUTS).join(", ")})`);
    }
  }
  const erreurs = verifierTraductions(v);
  if (erreurs.length) {
    throw new Error(`vitrine.json: traductions incomplètes :\n  ${erreurs.join("\n  ")}`);
  }
  return v;
}

/** Version du chart, lue dans le chart lui-même. */
export function lireVersions(chartDir = CHART_DIR) {
  const chart = fs.readFileSync(path.join(chartDir, "Chart.yaml"), "utf8");
  const m = chart.match(/^version:\s*"?([^"\s]+)"?/m);
  if (!m) throw new Error("version introuvable : Chart.yaml version");
  return { chart: m[1] };
}

/** Les vues de l'interface, lues dans les onglets de son index.html. */
export function lireVues(webDir = WEB_DIR) {
  const html = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
  const vues = [...html.matchAll(/class="nav-tab[^"]*"\s+data-view="[^"]+">([^<]+)</g)].map((m) => m[1].trim());
  if (!vues.length) throw new Error("aucune vue trouvée dans web/index.html");
  return vues;
}

/** Le nombre de contrôles que déclarent les gardiens. */
export function lireControles(fichier = GARDIENS) {
  const d = JSON.parse(fs.readFileSync(fichier, "utf8"));
  if (!Array.isArray(d.controles) || !d.controles.length) throw new Error("gardiens.json : aucun contrôle");
  return d.controles.length;
}

/** Les jetons de couleur de l'interface, tels quels (thème sombre, clair, système). */
export function lireJetons(webDir = WEB_DIR) {
  const css = fs.readFileSync(path.join(webDir, "css", "jetons.css"), "utf8");
  if (!css.includes(':root[data-theme="clair"]')) throw new Error("jetons.css : thème clair introuvable");
  return css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\n\s*\n/g, "\n").trim();
}

const statut = (ui, cle) => `<span class="statut statut-${cle}">${echapper(ui[STATUTS[cle]])}</span>`;

/** Une capture dans ses deux thèmes : le CSS montre celle du thème courant. */
function capture(racine, fichier, alt, ui, { classe = "", largeur = 1440, hauteur = 900, charger = "lazy" } = {}) {
  const une = (theme) => {
    const src = `${racine}assets/captures/${echapper(fichier)}-${theme}.webp`;
    return `<a class="ecran-${theme}" href="${src}" title="${echapper(ui.agrandir)}"><img src="${src}" alt="${echapper(alt)}" width="${largeur}" height="${hauteur}" loading="${charger}" decoding="async" /></a>`;
  };
  return `<div class="capture ${classe}">${une("clair")}${une("sombre")}</div>`;
}

function titreDeSection(id, titre, intro = "") {
  return `<h2 id="${id}-titre">${echapper(titre)}</h2>${intro ? `\n      <p class="intro">${echapper(intro)}</p>` : ""}`;
}

function blocPromesse(v) {
  return `<section class="bloc" aria-labelledby="promesse-titre" id="promesse">
      ${titreDeSection("promesse", v.promesse.titre)}
      <ul class="trio">
${v.promesse.points.map((p) => `        <li><h3>${echapper(p.titre)}</h3><p>${echapper(p.texte)}</p></li>`).join("\n")}
      </ul>
    </section>`;
}

function blocCapacites(v) {
  const ui = v.interface;
  return `<section class="bloc" aria-labelledby="capacites-titre" id="capacites">
      ${titreDeSection("capacites", v.capacites.titre, v.capacites.intro)}
      <p class="legende-statuts">${echapper(ui.legendeStatuts)}</p>
${v.capacites.familles.map((f) => `      <div class="famille">
        <h3>${echapper(f.titre)}</h3>
        <ul class="cartes">
${f.items.map((c) => `          <li class="carte">
            <div class="carte-tete"><h4>${echapper(c.titre)}</h4>${statut(ui, c.statut)}</div>
            <p>${echapper(c.texte)}</p>
            ${c.ancre ? `<a class="lien-guide" href="${GUIDE_URL}#${encodeURI(c.ancre)}">${echapper(ui.enSavoirPlus)}<span class="visuellement-cache"> : ${echapper(c.titre)}</span></a>` : ""}
          </li>`).join("\n")}
        </ul>
      </div>`).join("\n")}
    </section>`;
}

function blocVisite(v, racine) {
  const ui = v.interface;
  const m = v.visite.mobile;
  return `<section class="bloc" aria-labelledby="visite-titre" id="visite">
      ${titreDeSection("visite", v.visite.titre, v.visite.intro)}
      <div class="galerie">
${v.visite.captures.map((c) => `        <figure>
          ${capture(racine, c.fichier, c.alt, ui)}
          <figcaption><strong>${echapper(c.titre)}</strong> ${echapper(c.legende)}</figcaption>
        </figure>`).join("\n")}
      </div>
      ${m ? `<figure class="mobile">
        ${capture(racine, m.fichier, m.alt, ui, { classe: "capture-mobile", largeur: 390, hauteur: 844 })}
        <figcaption><strong>${echapper(m.titre)}</strong> ${echapper(m.legende)}</figcaption>
      </figure>` : ""}
      <p class="note">${echapper(ui.sourceCaptures)}</p>
    </section>`;
}

function puces(liste) {
  return `<ul class="puces">${liste.map((b) => `<li>${echapper(b)}</li>`).join("")}</ul>`;
}

function blocCas(v, racine) {
  const ui = v.interface;
  const captures = Object.fromEntries([...v.visite.captures, v.visite.mobile].filter(Boolean).map((c) => [c.fichier, c]));
  return `<section class="bloc" aria-labelledby="cas-titre" id="cas">
      ${titreDeSection("cas", v.cas.titre, v.cas.intro)}
${v.cas.liste.map((c, i) => {
    const cap = c.capture ? captures[c.capture] : null;
    const mobile = cap && cap === v.visite.mobile;
    return `      <article class="cas${cap ? "" : " cas-sans-capture"}" id="cas-${echapper(c.id)}" aria-labelledby="cas-${echapper(c.id)}-titre">
        <div class="cas-texte">
          <p class="cas-numero">${String(i + 1).padStart(2, "0")}</p>
          <div class="carte-tete"><h3 id="cas-${echapper(c.id)}-titre">${echapper(c.titre)}</h3>${statut(ui, c.statut)}</div>
          <p class="etiquette">${echapper(ui.briques)}</p>
          ${puces(c.briques)}
          <p class="etiquette">${echapper(ui.etapes)}</p>
          <ol class="etapes">
${c.etapes.map((e) => `            <li>${echapper(e)}</li>`).join("\n")}
          </ol>
          ${c.limite ? `<p class="limite"><strong>${echapper(ui.limite)}</strong> ${echapper(c.limite)}</p>` : ""}
        </div>
        ${cap ? capture(racine, cap.fichier, cap.alt, ui, mobile ? { classe: "capture-mobile", largeur: 390, hauteur: 844 } : {}) : ""}
      </article>`;
  }).join("\n")}
    </section>`;
}

function blocAssociations(v) {
  const a = v.associations;
  return `<section class="bloc" aria-labelledby="associations-titre" id="associations">
      ${titreDeSection("associations", a.titre, a.intro)}
      <ul class="associations">
${a.liste.map((x) => `        <li>
          <p class="formule">${x.briques.map((b) => `<span class="brique">${echapper(b)}</span>`).join('<span class="plus" aria-hidden="true">+</span>')}</p>
          <p>${echapper(x.texte)}</p>
        </li>`).join("\n")}
      </ul>
    </section>`;
}

/** Le schéma des processus d'un pod, en SVG, aux couleurs des jetons. */
export function schemaArchitecture(s) {
  const boite = (x, y, l, h, texte, classe = "") => {
    const lignes = String(texte).split(" · ");
    const t = lignes.map((ligne, i) => `<tspan x="${x + l / 2}" dy="${i === 0 ? (lignes.length > 1 ? -8 : 0) : 17}">${echapper(ligne)}</tspan>`).join("");
    return `<g class="boite ${classe}"><rect x="${x}" y="${y}" width="${l}" height="${h}" rx="10" /><text x="${x + l / 2}" y="${y + h / 2 + 5}" text-anchor="middle">${t}</text></g>`;
  };
  const fleche = (x1, y1, x2, y2) => `<line class="fleche" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" marker-end="url(#pointe)" />`;
  return `<svg class="schema" viewBox="0 0 960 480" role="img" aria-labelledby="schema-titre">
        <title id="schema-titre">${echapper(s.titre)}</title>
        <defs><marker id="pointe" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" /></marker></defs>
        ${boite(20, 20, 200, 50, s.vous, "externe")}
        ${boite(240, 20, 200, 50, s.distant, "externe")}
        ${boite(480, 20, 200, 50, s.connecteurs, "externe")}
        ${boite(700, 20, 240, 50, s.modeles, "externe")}
        ${boite(140, 100, 200, 50, s.ingress, "externe")}
        ${fleche(120, 70, 200, 100)}
        ${fleche(340, 70, 280, 100)}
        <g class="pod"><rect x="20" y="180" width="920" height="285" rx="14" /><text x="920" y="206" text-anchor="end">${echapper(s.pod)}</text></g>
        ${boite(40, 220, 260, 60, s.atelier, "fort")}
        ${boite(380, 220, 260, 60, s.claude)}
        ${boite(680, 220, 240, 60, s.relais)}
        ${boite(40, 320, 320, 56, s.apps, "fort")}
        ${boite(40, 400, 320, 50, s.creations)}
        ${boite(400, 320, 240, 56, s.wikichat)}
        ${boite(680, 320, 240, 56, s.gardiens)}
        ${fleche(200, 150, 170, 220)}
        ${fleche(330, 150, 330, 320)}
        ${fleche(300, 250, 380, 250)}
        ${fleche(640, 250, 680, 250)}
        ${fleche(540, 220, 575, 70)}
        ${fleche(800, 220, 815, 70)}
        ${fleche(510, 280, 510, 320)}
        ${fleche(200, 376, 200, 400)}
      </svg>`;
}

function blocArchitecture(v) {
  const a = v.architecture;
  return `<section class="bloc" aria-labelledby="architecture-titre" id="architecture">
      ${titreDeSection("architecture", a.titre, a.texte)}
      <figure class="figure-schema">${schemaArchitecture(a.schema)}</figure>
    </section>`;
}

function blocInstaller(v) {
  const i = v.installer;
  return `<section class="bloc" aria-labelledby="installer-titre" id="installer">
      ${titreDeSection("installer", i.titre, i.intro)}
      <ol class="cartes cartes-installer">
${i.cartes.map((c) => `        <li class="carte">
          <h3>${echapper(c.titre)}</h3>
          <p>${echapper(c.texte)}</p>
          ${c.code ? `<pre class="code" tabindex="0"><code>${echapper(c.code)}</code></pre>` : ""}
          ${c.note ? `<p class="note">${echapper(c.note)}</p>` : ""}
        </li>`).join("\n")}
      </ol>
    </section>`;
}

function blocLimites(v) {
  const l = v.limites;
  return `<section class="bloc" aria-labelledby="limites-titre" id="limites">
      ${titreDeSection("limites", l.titre, l.etat)}
      <ul class="trio trio-limites">
${l.points.map((p) => `        <li><h3>${echapper(p.titre)}</h3><p>${echapper(p.texte)}</p></li>`).join("\n")}
      </ul>
      ${l.lien ? `<p><a class="bouton secondaire" href="${echapper(l.lien.url)}">${echapper(l.lien.libelle)}</a></p>` : ""}
    </section>`;
}

function blocStackEtJournal(v) {
  const s = v.stack;
  const j = v.journal;
  return `<section class="bloc deux-colonnes" aria-labelledby="stack-titre" id="stack">
      <div>
        ${titreDeSection("stack", s.titre, s.texte)}
        ${puces(s.items || [])}
      </div>
      <div>
        <h2 id="journal-titre">${echapper(j.titre)}</h2>
        <dl class="journal">
${j.entrees.map((e) => `          <dt>${echapper(e.version)}</dt><dd>${echapper(e.texte)}</dd>`).join("\n")}
        </dl>
        ${j.lien ? `<p><a href="${echapper(j.lien.url)}">${echapper(j.lien.libelle)}</a></p>` : ""}
      </div>
    </section>`;
}

/** Chemin relatif d'une page vers la racine du site : "" ou "../". */
const versRacine = (langue) => "../".repeat(langue.dossier.split("/").filter(Boolean).length);

function selecteurLangue(langue, libelle) {
  const racine = versRacine(langue);
  const liens = LANGUES.map((l) => l.code === langue.code
    ? `<span aria-current="page" lang="${l.code}">${l.libelle}</span>`
    : `<a href="${`${racine}${l.dossier}` || "./"}" hreflang="${l.code}" lang="${l.code}">${l.libelle}</a>`);
  return `<nav class="langues" aria-label="${echapper(libelle)}">${liens.join(" ")}</nav>`;
}

function liensAlternatifs() {
  const liens = LANGUES.map((l) => `<link rel="alternate" hreflang="${l.code}" href="${PAGES_URL}/${l.dossier}" />`);
  liens.push(`<link rel="alternate" hreflang="x-default" href="${PAGES_URL}/${LANGUES[0].dossier}" />`);
  return liens.join("\n  ");
}

/**
 * Le choix du thème : suivre le système, clair ou sombre, comme dans
 * l'Atelier. Posé avant le premier rendu, sans éclair ; le stockage local
 * peut manquer (navigation privée), la page s'en passe alors.
 */
const SCRIPT_THEME_INITIAL = `(function(){try{var t=localStorage.getItem("atelier-vitrine-theme");if(t==="clair"||t==="sombre")document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;

function scriptTheme(ui) {
  const libelles = JSON.stringify({ systeme: ui.themeSysteme, clair: ui.themeClair, sombre: ui.themeSombre });
  return `(function(){
  var L=${libelles},ordre=["systeme","clair","sombre"],b=document.getElementById("theme");
  function courant(){return document.documentElement.getAttribute("data-theme")||"systeme";}
  function montrer(){var c=courant();b.querySelector("[data-libelle]").textContent=L[c];b.setAttribute("data-choix",c);}
  b.addEventListener("click",function(){
    var s=ordre[(ordre.indexOf(courant())+1)%ordre.length];
    if(s==="systeme")document.documentElement.removeAttribute("data-theme");else document.documentElement.setAttribute("data-theme",s);
    try{if(s==="systeme")localStorage.removeItem("atelier-vitrine-theme");else localStorage.setItem("atelier-vitrine-theme",s);}catch(e){}
    montrer();
  });
  montrer();
})();`;
}

const STYLE = `
  :root { --font: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif; --display: "Fraunces", Georgia, serif; --mono: ui-monospace, "Cascadia Code", "SFMono-Regular", Consolas, monospace; --largeur: 72rem; }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
  body { margin: 0; font-family: var(--font); font-size: 1rem; line-height: 1.6; color: var(--texte-1); background: var(--surface-1); -webkit-font-smoothing: antialiased; }
  a { color: var(--accent); text-underline-offset: 3px; }
  a:hover { color: var(--accent-clair); }
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; border-radius: 4px; }
  ::selection { background: var(--surface-active-fort); }
  .visuellement-cache { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .evitement { position: absolute; left: 1rem; top: -4rem; background: var(--accent); color: var(--sur-accent); padding: 0.5rem 1rem; border-radius: 6px; z-index: 10; }
  .evitement:focus { top: 1rem; }
  .enveloppe { width: min(var(--largeur), calc(100% - 2rem)); margin: 0 auto; }

  .entete { position: sticky; top: 0; z-index: 5; background: var(--surface-0); border-bottom: 1px solid var(--line); }
  .entete .enveloppe { display: flex; align-items: center; gap: 1rem; min-height: 3.25rem; flex-wrap: wrap; padding: 0.4rem 0; }
  .marque { display: inline-flex; align-items: center; gap: 0.55rem; color: var(--texte-1); text-decoration: none; font-family: var(--display); font-weight: 700; font-size: 1.3rem; }
  .marque img { width: 24px; height: 24px; }
  .version { font-family: var(--mono); font-size: 0.8rem; color: var(--texte-3); }
  .menu { display: flex; gap: 0.2rem; flex-wrap: wrap; margin-left: auto; }
  .menu a { color: var(--texte-2); text-decoration: none; font-size: 0.87rem; padding: 0.3rem 0.55rem; border-radius: 6px; }
  .menu a:hover { background: var(--surface-survol); color: var(--texte-1); }
  .outils { display: flex; align-items: center; gap: 0.6rem; }
  .langues { font-size: 0.87rem; display: flex; gap: 0.4rem; }
  .langues a, .langues span { padding: 0.25rem 0.4rem; border-radius: 6px; text-decoration: none; color: var(--texte-2); }
  .langues [aria-current] { color: var(--texte-1); font-weight: 600; box-shadow: inset 0 -2px 0 var(--accent); }
  .bouton-theme { font: inherit; font-size: 0.87rem; color: var(--texte-2); background: transparent; border: 1px solid var(--line); border-radius: 6px; padding: 0.25rem 0.6rem; cursor: pointer; display: inline-flex; gap: 0.4rem; align-items: center; min-height: 2rem; }
  .bouton-theme:hover { background: var(--surface-survol); color: var(--texte-1); }
  .bouton-theme svg { width: 1em; height: 1em; }
  @media (max-width: 1080px) { .menu { display: none; } .outils { margin-left: auto; } }
  @media (max-width: 520px) { .version { display: none; } .entete .enveloppe { flex-wrap: nowrap; } .bouton-theme > span:first-of-type { display: none; } }

  .hero { padding: clamp(2.5rem, 7vw, 4.5rem) 0 2rem; background: linear-gradient(180deg, var(--surface-0), var(--surface-1)); border-bottom: 1px solid var(--line); }
  .surtitre { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); margin: 0 0 0.8rem; }
  h1 { font-family: var(--display); font-weight: 700; font-size: clamp(2.6rem, 7vw, 4rem); line-height: 1.02; margin: 0 0 1rem; letter-spacing: -0.01em; }
  .pitch { font-size: clamp(1.05rem, 2.2vw, 1.25rem); color: var(--texte-2); max-width: 48rem; margin: 0 0 0.9rem; }
  .pour-qui { color: var(--texte-3); max-width: 48rem; margin: 0 0 1.4rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.6rem; margin: 0 0 1.4rem; }
  .bouton { display: inline-flex; align-items: center; min-height: 2.6rem; padding: 0.5rem 1.1rem; border-radius: 6px; font-weight: 600; text-decoration: none; font-size: 0.95rem; }
  .bouton.principal { background: var(--accent); color: var(--sur-accent); }
  .bouton.principal:hover { background: var(--accent-clair); color: var(--sur-accent); }
  .bouton.secondaire { color: var(--texte-1); border: 1px solid var(--bordure-champ); }
  .bouton.secondaire:hover { background: var(--surface-survol); color: var(--texte-1); }
  .tags { display: flex; flex-wrap: wrap; gap: 0.4rem; list-style: none; padding: 0; margin: 0 0 2rem; }
  .tags li, .puces li { font-family: var(--mono); font-size: 0.8rem; padding: 0.15rem 0.6rem; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--line); color: var(--texte-2); }

  .capture a { display: block; }
  .capture img { display: block; width: 100%; height: auto; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); box-shadow: var(--ombre-2); }
  .ecran-sombre { display: none !important; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="clair"]) .ecran-sombre { display: block !important; } :root:not([data-theme="clair"]) .ecran-clair { display: none !important; } }
  :root[data-theme="sombre"] .ecran-sombre { display: block !important; }
  :root[data-theme="sombre"] .ecran-clair { display: none !important; }
  .capture-mobile { max-width: 300px; }
  .capture-mobile img { border-radius: 22px; }

  .chiffres { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 0.8rem; margin: 2rem 0 0; padding: 0; list-style: none; }
  .chiffres li { background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 0.9rem 1rem; }
  .chiffres strong { display: block; font-family: var(--display); font-size: 1.9rem; line-height: 1.1; color: var(--texte-1); }
  .chiffres span { color: var(--texte-2); font-size: 0.87rem; }

  main { padding-bottom: 2rem; }
  .bloc { padding: clamp(2.5rem, 6vw, 4rem) 0 0; scroll-margin-top: 4rem; }
  h2 { font-family: var(--display); font-weight: 700; font-size: clamp(1.6rem, 3.6vw, 2.15rem); line-height: 1.15; margin: 0 0 0.7rem; }
  h3 { font-size: 1.1rem; line-height: 1.3; margin: 0 0 0.4rem; }
  h4 { font-size: 1rem; line-height: 1.3; margin: 0; }
  .intro { color: var(--texte-2); max-width: 50rem; margin: 0 0 1.5rem; font-size: 1.05rem; }
  .note { color: var(--texte-3); font-size: 0.87rem; }

  .trio { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr)); gap: 1rem; }
  .trio li { background: var(--surface-2); border: 1px solid var(--line); border-top: 3px solid var(--accent); border-radius: 10px; padding: 1.1rem 1.2rem; }
  .trio p { margin: 0; color: var(--texte-2); }
  .trio-limites li { border-top-color: var(--attention); }

  .legende-statuts { color: var(--texte-3); font-size: 0.87rem; margin: -0.6rem 0 1.4rem; max-width: 50rem; }
  .famille { margin: 0 0 1.8rem; }
  .famille > h3 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--texte-3); margin: 0 0 0.8rem; }
  .cartes { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr)); gap: 0.9rem; }
  .carte { background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.1rem; display: flex; flex-direction: column; gap: 0.5rem; min-width: 0; }
  .carte p { margin: 0; color: var(--texte-2); font-size: 0.95rem; }
  .carte-tete { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; flex-wrap: wrap; }
  .lien-guide { font-size: 0.87rem; margin-top: auto; }
  .statut { font-size: 0.75rem; font-weight: 600; padding: 0.1rem 0.55rem; border-radius: 999px; white-space: nowrap; }
  .statut-service { background: var(--ok-fond); color: var(--ok-texte); }
  .statut-integre { background: var(--info-fond); color: var(--info-texte); }
  .statut-enPartie, .statut-pasFait { background: var(--attention-fond); color: var(--attention-texte); }

  .galerie { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 30rem), 1fr)); gap: 1.6rem 1.4rem; }
  figure { margin: 0; min-width: 0; }
  figcaption { margin-top: 0.7rem; color: var(--texte-2); font-size: 0.93rem; }
  figcaption strong { color: var(--texte-1); margin-right: 0.3rem; }
  figure.mobile { display: grid; grid-template-columns: minmax(0, 300px) minmax(0, 1fr); gap: 1.4rem; align-items: center; margin-top: 2rem; }
  @media (max-width: 640px) { figure.mobile { grid-template-columns: 1fr; } figure.mobile .capture-mobile { max-width: 240px; } }

  .cas { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr); gap: 1.6rem; align-items: start; padding: 1.6rem 0; border-top: 1px solid var(--line); }
  .cas:nth-of-type(even) .capture { order: -1; }
  .cas-sans-capture { grid-template-columns: minmax(0, 1fr); }
  .cas-sans-capture .cas-texte { max-width: 50rem; }
  .cas .capture-mobile { justify-self: center; }
  @media (max-width: 860px) { .cas { grid-template-columns: 1fr; } .cas:nth-of-type(even) .capture { order: 0; } }
  .cas-numero { font-family: var(--display); font-size: 1rem; color: var(--accent); margin: 0 0 0.2rem; font-weight: 700; }
  .etiquette { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--texte-3); margin: 1rem 0 0.4rem; font-weight: 600; }
  .puces { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .etapes { margin: 0; padding-left: 1.3rem; color: var(--texte-2); }
  .etapes li { margin: 0 0 0.35rem; padding-left: 0.2rem; }
  .etapes li::marker { color: var(--accent); font-weight: 700; }
  .limite { margin: 1rem 0 0; padding: 0.6rem 0.8rem; border-left: 3px solid var(--attention); background: var(--surface-legere); color: var(--texte-2); font-size: 0.93rem; }
  .limite strong { color: var(--texte-1); margin-right: 0.3rem; }

  .associations { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr)); gap: 0.9rem; }
  .associations li { background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.1rem; }
  .associations p { margin: 0; color: var(--texte-2); }
  .formule { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin: 0 0 0.6rem !important; }
  .brique { font-size: 0.85rem; font-weight: 600; color: var(--texte-1); background: var(--surface-active); border: 1px solid var(--accent-dim); border-radius: 6px; padding: 0.1rem 0.5rem; }
  .plus { color: var(--accent); font-weight: 700; }

  .figure-schema { background: var(--surface-2); border: 1px solid var(--line); border-radius: 12px; padding: 1rem; overflow-x: auto; }
  .schema { display: block; width: 100%; min-width: 640px; height: auto; font-family: var(--font); font-size: 14px; }
  .schema .boite rect { fill: var(--surface-3); stroke: var(--line); }
  .schema .boite text { fill: var(--texte-1); }
  .schema .fort rect { fill: var(--surface-active-fort); stroke: var(--accent-dim); }
  .schema .externe rect { fill: var(--surface-1); stroke: var(--bordure-champ); stroke-dasharray: 5 4; }
  .schema .pod rect { fill: none; stroke: var(--accent-dim); stroke-width: 1.5; }
  .schema .pod text { fill: var(--texte-2); font-weight: 600; }
  .schema .fleche { stroke: var(--texte-3); stroke-width: 1.5; }
  .schema marker path { fill: var(--texte-3); }

  .cartes-installer { counter-reset: none; }
  .code { margin: 0.3rem 0 0; padding: 0.75rem 0.9rem; overflow-x: auto; background: var(--code-fond); border: 1px solid var(--line); border-radius: 6px; font-family: var(--mono); font-size: 0.82rem; line-height: 1.55; color: var(--texte-1); white-space: pre; }

  .deux-colonnes { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: 2rem; }
  .journal { margin: 0; }
  .journal dt { font-family: var(--mono); font-size: 0.87rem; color: var(--accent); font-weight: 600; }
  .journal dd { margin: 0.2rem 0 1rem; color: var(--texte-2); font-size: 0.95rem; }

  .pied { margin-top: 3rem; border-top: 1px solid var(--line); background: var(--surface-0); color: var(--texte-3); font-size: 0.87rem; }
  .pied .enveloppe { padding: 1.5rem 0 2rem; display: flex; flex-wrap: wrap; gap: 0.4rem 2rem; justify-content: space-between; }
  .pied p { margin: 0.2rem 0; max-width: 46rem; }
`;

/**
 * Rend la page d'une langue. `v` est la vitrine déjà localisée : chaque
 * texte y est une chaîne.
 */
export function rendreHtml(v, langue, contexte) {
  const racine = versRacine(langue);
  const ui = v.interface;
  const menu = ["capacites", "visite", "cas", "associations", "architecture", "installer", "limites"];
  const hero = v.visite.captures[0];
  return `<!DOCTYPE html>
<html lang="${langue.code}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${echapper(v.nom)} · Claude Code · SSPCloud</title>
  <meta name="description" content="${echapper(v.pitch)}" />
  <meta property="og:title" content="${echapper(v.nom)}" />
  <meta property="og:description" content="${echapper(v.pitch)}" />
  <meta property="og:type" content="website" />
  <meta property="og:image" content="${PAGES_URL}/assets/captures/${echapper(hero.fichier)}-clair.webp" />
  <meta property="og:locale" content="${langue.code === "fr" ? "fr_FR" : "en_US"}" />
  <meta name="color-scheme" content="light dark" />
  <link rel="canonical" href="${PAGES_URL}/${langue.dossier}" />
  ${liensAlternatifs()}
  <link rel="icon" href="${racine}assets/atelier.svg" type="image/svg+xml" />
  <script>${SCRIPT_THEME_INITIAL}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet" />
  <style>
${contexte.jetons}
${STYLE}
  </style>
</head>
<body>
  <a class="evitement" href="#contenu">${echapper(ui.evitement)}</a>
  <header class="entete">
    <div class="enveloppe">
      <a class="marque" href="${racine}${langue.dossier}" aria-label="${echapper(v.nom)}"><img src="${racine}assets/atelier.svg" alt="" width="24" height="24" />${echapper(v.nom)}</a>
      <span class="version">${echapper(ui.chart)} ${echapper(contexte.versions.chart)}</span>
      <nav class="menu" aria-label="${echapper(ui.navigation)}">
${menu.map((id) => `        <a href="#${id}">${echapper(ui.menu[id])}</a>`).join("\n")}
      </nav>
      <div class="outils">
        ${selecteurLangue(langue, ui.choixLangue)}
        <button type="button" class="bouton-theme" id="theme"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg><span>${echapper(ui.theme)}</span> <span data-libelle>${echapper(ui.themeSysteme)}</span></button>
      </div>
    </div>
  </header>
  <div class="hero">
    <div class="enveloppe">
      <p class="surtitre">${echapper(ui.eyebrow)}</p>
      <h1>${echapper(v.nom)}</h1>
      <p class="pitch">${echapper(v.pitch)}</p>
      ${v.pourQui ? `<p class="pour-qui">${echapper(v.pourQui)}</p>` : ""}
      <div class="actions">
        <a class="bouton principal" href="#installer">${echapper(ui.boutonInstaller)}</a>
        <a class="bouton secondaire" href="${echapper(v.depot)}">${echapper(ui.boutonCode)}</a>
        <a class="bouton secondaire" href="${GUIDE_URL}">${echapper(ui.boutonGuide)}</a>
      </div>
      <ul class="tags">${(v.tags || []).map((t) => `<li>${echapper(t)}</li>`).join("")}</ul>
      <figure>
        ${capture(racine, hero.fichier, hero.alt, ui, { charger: "eager" })}
      </figure>
      <ul class="chiffres">
${(v.chiffres || []).map((c) => `        <li><strong>${echapper(c.valeur)}</strong><span>${echapper(c.libelle)}</span></li>`).join("\n")}
      </ul>
    </div>
  </div>
  <main id="contenu" class="enveloppe" tabindex="-1">
    ${blocPromesse(v)}
    ${blocCapacites(v)}
    ${blocVisite(v, racine)}
    ${blocCas(v, racine)}
    ${blocAssociations(v)}
    ${blocArchitecture(v)}
    ${blocInstaller(v)}
    ${blocLimites(v)}
    ${blocStackEtJournal(v)}
  </main>
  <footer class="pied">
    <div class="enveloppe">
      <div>
        <p>${echapper(ui.piedLicence)}</p>
        <p>${echapper(ui.piedProjet)}</p>
      </div>
      <p><a href="${echapper(v.depot)}">${echapper(v.depot.replace(/^https?:\/\//, ""))}</a> · <a href="#">${echapper(ui.retour)}</a></p>
    </div>
  </footer>
  <script>${scriptTheme(ui)}</script>
</body>
</html>
`;
}

function copierDossier(source, cible) {
  fs.mkdirSync(cible, { recursive: true });
  for (const entree of fs.readdirSync(source, { withFileTypes: true })) {
    const s = path.join(source, entree.name);
    const c = path.join(cible, entree.name);
    if (entree.isDirectory()) copierDossier(s, c);
    else fs.copyFileSync(s, c);
  }
}

/** Les captures que la vitrine cite, chacune dans ses deux thèmes. */
export function capturesCitees(v) {
  const noms = new Set([...v.visite.captures.map((c) => c.fichier), v.visite.mobile?.fichier, ...v.cas.liste.map((c) => c.capture)].filter(Boolean));
  return [...noms].flatMap((n) => [`${n}-clair.webp`, `${n}-sombre.webp`]);
}

export function generate({ vitrinePath = VITRINE, chartDir = CHART_DIR, webDir = WEB_DIR, gardiens = GARDIENS, distDir = DIST } = {}) {
  const brute = chargerVitrine(vitrinePath);
  const versions = lireVersions(chartDir);
  const vues = lireVues(webDir);
  const controles = lireControles(gardiens);
  const jetons = lireJetons(webDir);
  const manquantes = capturesCitees(brute).filter((f) => !fs.existsSync(path.join(ROOT, "assets", "captures", f)));
  if (manquantes.length) throw new Error(`captures absentes de site/assets/captures : ${manquantes.join(", ")}`);
  const gabarits = {
    version: versions.chart,
    pages: PAGES_URL,
    vues: String(vues.length),
    listeVues: vues.join(", "),
    controles: String(controles),
  };

  copierDossier(path.join(ROOT, "assets"), path.join(distDir, "assets"));

  const pages = LANGUES.map((langue) => {
    const html = rendreHtml(localiser(brute, langue.code, gabarits), langue, { versions, jetons });
    const dossier = path.join(distDir, langue.dossier);
    fs.mkdirSync(dossier, { recursive: true });
    const out = path.join(dossier, "index.html");
    fs.writeFileSync(out, html, "utf8");
    return { langue: langue.code, out, bytes: Buffer.byteLength(html, "utf8") };
  });
  return { pages, versions, vues, controles };
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const r = generate();
  for (const p of r.pages) console.log(`[site] ${p.langue} : écrit ${p.out} (${p.bytes} octets)`);
  console.log(`[site] chart ${r.versions.chart}, ${r.vues.length} vues, ${r.controles} contrôles de gardiens`);
}
