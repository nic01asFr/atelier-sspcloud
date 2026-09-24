#!/usr/bin/env node
/**
 * Génère la vitrine bilingue de l'Atelier depuis site/vitrine.json :
 *   dist/index.html     (français, langue par défaut)
 *   dist/en/index.html  (anglais)
 *   dist/assets/        (captures, icône)
 * Ne pas éditer le HTML produit à la main : régénérer.
 *
 * Dans vitrine.json, un texte est soit une chaîne neutre (nom, URL, couleur,
 * tags), soit un objet {"fr": "...", "en": "..."}. Tout texte que la page
 * affiche vient de là, libellés compris : le générateur n'écrit aucune phrase
 * dans une langue donnée, sinon elle finirait sur la mauvaise page.
 *
 * La version affichée est relue dans le chart, jamais recopiée.
 *
 * Sortie : site/dist par défaut, ou le dossier passé dans SITE_OUT. On
 * n'écrit que nos fichiers, sans vider le dossier : la CI y dépose aussi
 * index.yaml et l'archive du chart.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(ROOT, "..");
const VITRINE = path.join(ROOT, "vitrine.json");
const CHART_DIR = path.join(REPO, "charts", "atelier");
const DIST = process.env.SITE_OUT || path.join(ROOT, "dist");
export const PAGES_URL = "https://nic01asfr.github.io/atelier-sspcloud";

/** Les langues publiées. La première est la page racine et le x-default. */
export const LANGUES = [
  { code: "fr", libelle: "FR", dossier: "" },
  { code: "en", libelle: "EN", dossier: "en/" },
];
const CODES = LANGUES.map((l) => l.code);

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
 * avec le chemin de sa clé (ex. « produit.sequence[2].texte : en manquant »).
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

export function chargerVitrine(fichier = VITRINE) {
  const v = JSON.parse(fs.readFileSync(fichier, "utf8"));
  for (const k of ["nom", "pitch", "couleur", "depot", "points", "interface"]) {
    if (v[k] == null || (Array.isArray(v[k]) && v[k].length === 0)) {
      throw new Error(`vitrine.json: champ requis manquant ou vide: ${k}`);
    }
  }
  if (!v.produit?.sequence?.length) {
    throw new Error("vitrine.json: produit.sequence requis");
  }
  if (!/^#[0-9a-fA-F]{6}$/.test(v.couleur)) {
    throw new Error("vitrine.json: couleur doit être au format #RRGGBB");
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

const code = (texte) => `<pre class="code"><code>${echapper(texte)}</code></pre>`;
const label = (texte) => `<span class="sec-label">${echapper(texte)}</span>`;

function blocChiffres(chiffres) {
  if (!chiffres?.length) return "";
  return `<div class="chiffres">
${chiffres.map((c) => `      <div><strong>${echapper(c.valeur)}</strong><span>${echapper(c.libelle)}</span></div>`).join("\n")}
    </div>`;
}

function blocPoints(v) {
  return `<section id="promesse">
    <h2>${label(v.interface.labelPromesse)} ${echapper(v.interface.titrePromesse)}</h2>
    <ul class="points">
${v.points.map((p) => `      <li><b>${echapper(p.titre)}</b> ${echapper(p.texte)}</li>`).join("\n")}
    </ul>
  </section>`;
}

function blocFonctionnalites(v) {
  const l = v.fonctionnalites || [];
  if (!l.length) return "";
  return `<section id="fonctionnalites">
    <h2>${label(v.interface.labelCapacites)} ${echapper(v.titreFonctionnalites)}</h2>
    <div class="grid">
${l.map((f) => `      <article class="card">
        <h3>${echapper(f.titre)}</h3>
        <p>${echapper(f.texte)}</p>
        ${f.pourQui ? `<p class="note">${echapper(f.pourQui)}</p>` : ""}
      </article>`).join("\n")}
    </div>
  </section>`;
}

function blocSequence(v) {
  return `<section id="parcours">
    <h2>${label(v.interface.labelParcours)} ${echapper(v.produit.titreSequence)}</h2>
    <ol class="steps">
${v.produit.sequence.map((s, i) => `      <li><span class="n">${i + 1}</span><div><b>${echapper(s.titre)}</b><p>${echapper(s.texte)}</p></div></li>`).join("\n")}
    </ol>
  </section>`;
}

function blocInstaller(v) {
  if (!v.installer) return "";
  return `<section id="installer">
    <h2>${label(v.interface.labelInstaller)} ${echapper(v.installer.titre)}</h2>
    <div class="grid">
${v.installer.cartes.map((c) => `      <article class="card">
        <h3>${echapper(c.titre)}</h3>
        <p>${echapper(c.texte)}</p>
        ${c.code ? code(c.code) : ""}
        ${c.note ? `<p class="note">${echapper(c.note)}</p>` : ""}
      </article>`).join("\n")}
    </div>
  </section>`;
}

function blocApercu(v, prefixe) {
  const l = v.captures?.liste || [];
  if (!l.length) return "";
  return `<section id="apercu">
    <h2>${label(v.interface.labelApercu)} ${echapper(v.captures.titre)}</h2>
    <div class="galerie">
${l.map((c) => `      <figure>
        <a href="${prefixe}assets/${echapper(c.fichier)}"><img src="${prefixe}assets/${echapper(c.fichier)}" alt="${echapper(c.alt)}" loading="lazy" /></a>
        <figcaption>${echapper(c.legende)}</figcaption>
      </figure>`).join("\n")}
    </div>
  </section>`;
}

function blocContextes(v) {
  const l = v.produit.contextes || [];
  if (!l.length) return "";
  return `<section id="usages">
    <h2>${label(v.interface.labelUsages)} ${echapper(v.produit.titreContextes)}</h2>
    <div class="grid">
${l.map((c) => `      <article class="card">
        <h3>${echapper(c.titre)}</h3>
        <p>${echapper(c.texte)}</p>
        ${c.pourquoi ? `<p class="note">${echapper(c.pourquoi)}</p>` : ""}
      </article>`).join("\n")}
    </div>
  </section>`;
}

function blocAVenir(v) {
  if (!v.aVenir) return "";
  return `<section id="a-venir">
    <h2>${label(v.interface.labelAVenir)} ${echapper(v.aVenir.titre)}</h2>
    <p class="lead">${echapper(v.aVenir.texte)}</p>
  </section>`;
}

function blocEncart(encart) {
  if (!encart) return "";
  const lien = encart.lien
    ? `<p><a class="btn ghost" href="${echapper(encart.lien.url)}">${echapper(encart.lien.libelle)}</a></p>`
    : "";
  return `<aside class="encart" id="securite">
    <h2>${echapper(encart.titre)}</h2>
    <p>${echapper(encart.texte)}</p>
    ${lien}
  </aside>`;
}

function blocStack(v) {
  if (!v.stack) return "";
  return `<section id="stack">
    <h2>${label(v.interface.labelStack)} ${echapper(v.stack.titre)}</h2>
    <p class="lead">${echapper(v.stack.texte)}</p>
    <div class="tags">${(v.stack.items || []).map((i) => `<span class="tag">${echapper(i)}</span>`).join("")}</div>
  </section>`;
}

function blocJournal(v) {
  if (!v.journal?.length) return "";
  return `<section id="journal">
    <h2>${label(v.interface.labelJournal)} ${echapper(v.interface.titreJournal)}</h2>
    <div class="journal">
${v.journal.map((j) => `      <div><b>${echapper(j.version)}</b><p>${echapper(j.texte)}</p></div>`).join("\n")}
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
  return `<nav class="langues" aria-label="${echapper(libelle)}">${liens.join(" · ")}</nav>`;
}

function liensAlternatifs() {
  const liens = LANGUES.map((l) => `<link rel="alternate" hreflang="${l.code}" href="${PAGES_URL}/${l.dossier}" />`);
  liens.push(`<link rel="alternate" hreflang="x-default" href="${PAGES_URL}/${LANGUES[0].dossier}" />`);
  return liens.join("\n  ");
}

/**
 * Rend la page d'une langue. `v` est la vitrine déjà localisée : chaque
 * texte y est une chaîne.
 */
export function rendreHtml(v, langue, versions) {
  // Les couleurs reprennent l'interface de l'Atelier : fond bleu nuit, cartes
  // ardoise, sable pour l'accent, titres à empattements. Pas de commentaire
  // dans le gabarit : il finirait en français sur la page anglaise.
  const racine = versRacine(langue);
  const ui = v.interface;
  const tags = (v.tags || []).map((t) => `<span class="tag">${echapper(t)}</span>`).join("");
  const depotCourt = v.depot.replace(/^https?:\/\//, "");
  const hero = v.captures?.hero;

  return `<!DOCTYPE html>
<html lang="${langue.code}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${echapper(v.nom)} · SSPCloud</title>
  <meta name="description" content="${echapper(v.pitch)}" />
  <meta property="og:title" content="${echapper(v.nom)}" />
  <meta property="og:description" content="${echapper(v.pitch)}" />
  <meta property="og:type" content="website" />
  <meta property="og:locale" content="${langue.code === "fr" ? "fr_FR" : "en_US"}" />
  <meta name="theme-color" content="#12161c" />
  <link rel="canonical" href="${PAGES_URL}/${langue.dossier}" />
  ${liensAlternatifs()}
  <link rel="icon" href="${racine}assets/atelier.svg" type="image/svg+xml" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --accent: ${echapper(v.couleur)};
      --accent-soft: rgba(214, 178, 122, 0.12);
      --bg: #12161c;
      --top: #0f1318;
      --card: #1a2029;
      --card-line: #2a323e;
      --ink: #eef1f5;
      --soft: #c9d0da;
      --muted: #8e98a6;
      --line: #232a34;
      --ok: #3fb67a;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 15px; line-height: 1.6;
      color: var(--ink); background: var(--bg);
      -webkit-font-smoothing: antialiased;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    ::selection { background: var(--accent-soft); }
    .wrap { width: min(1000px, calc(100% - 2rem)); margin: 0 auto; }

    .topbar {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 10px 16px; border-bottom: 1px solid var(--line); background: var(--top);
    }
    .topbar img { width: 22px; height: 22px; }
    .crumb { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--muted); }
    .crumb b { color: var(--soft); font-weight: 600; }
    .status { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
    .langues { margin-left: auto; font-family: "IBM Plex Mono", monospace; font-size: 12.5px; color: var(--muted); }
    .langues [aria-current] { color: var(--ink); font-weight: 600; border-bottom: 2px solid var(--accent); }
    .langues a { color: var(--soft); }

    header.hero { padding: clamp(2.4rem, 7vw, 4rem) 0 1rem; }
    .eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 1.4px; text-transform: uppercase; color: var(--accent); margin: 0 0 12px; }
    .brand { font-family: "Fraunces", Georgia, serif; font-weight: 700; font-size: clamp(2.4rem, 7vw, 3.6rem); letter-spacing: -0.01em; line-height: 1.05; margin: 0 0 0.8rem; }
    .pitch { font-size: clamp(1rem, 2.2vw, 1.13rem); max-width: 46rem; color: var(--soft); margin: 0 0 1.2rem; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0 0 1.4rem; }
    .tag { font-family: "IBM Plex Mono", monospace; font-size: 11px; padding: 3px 9px; border-radius: 999px; background: var(--card); color: var(--soft); border: 1px solid var(--card-line); }
    .cta { display: flex; flex-wrap: wrap; gap: 0.65rem; margin-bottom: 1.4rem; }
    .btn { font-weight: 600; font-size: 13.5px; padding: 9px 16px; border-radius: 8px; display: inline-flex; align-items: center; }
    .btn:hover { text-decoration: none; }
    .btn.primary { background: var(--accent); color: #1b1710; }
    .btn.primary:hover { filter: brightness(1.08); }
    .btn.ghost { color: var(--soft); border: 1px solid var(--card-line); }
    .btn.ghost:hover { border-color: var(--accent); color: var(--ink); }

    .code {
      margin: 0.6rem 0; padding: 12px 14px; overflow-x: auto;
      background: var(--top); border: 1px solid var(--line); border-radius: 8px;
      font-family: "IBM Plex Mono", monospace; font-size: 12.5px; line-height: 1.55; color: var(--soft);
    }

    .ecran { margin: 1.4rem 0 0; }
    .ecran img, .galerie img {
      display: block; width: 100%; height: auto;
      border: 1px solid var(--card-line); border-radius: 12px; background: var(--top);
    }
    .ecran img { box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45); }

    main section, main aside { margin: 2.6rem 0; }
    h2 { font-family: "Fraunces", Georgia, serif; font-size: 21px; font-weight: 600; margin: 0 0 1rem; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
    h2 .sec-label { font-family: "IBM Plex Sans", sans-serif; font-size: 10.5px; font-weight: 700; letter-spacing: 1.3px; text-transform: uppercase; color: var(--accent); }
    h3 { font-size: 14.5px; font-weight: 700; margin: 0 0 0.4rem; }
    .lead, .accroche { max-width: 46rem; color: var(--soft); }

    .chiffres { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-top: 1.2rem; }
    .chiffres div { padding: 14px 15px; background: var(--card); border: 1px solid var(--card-line); border-radius: 10px; }
    .chiffres strong { font-family: "IBM Plex Mono", monospace; font-size: 1.45rem; display: block; color: var(--ink); }
    .chiffres span { color: var(--muted); font-size: 12.5px; }

    .points { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
    .points li { padding: 13px 15px; background: var(--card); border: 1px solid var(--card-line); border-radius: 10px; color: var(--soft); }
    .points b { display: block; color: var(--ink); margin-bottom: 0.15rem; }

    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
    .card { padding: 15px 16px; min-width: 0; background: var(--card); border: 1px solid var(--card-line); border-radius: 10px; }
    .card p { margin: 0; color: var(--soft); font-size: 13.8px; }
    .card p + p, .card .code + p { margin-top: 0.6rem; }
    .note { color: var(--muted) !important; font-size: 12.5px !important; margin-top: 0.6rem !important; }

    .galerie { display: grid; grid-template-columns: 2fr 2fr 1fr; gap: 12px; align-items: start; }
    .galerie figure { margin: 0; min-width: 0; }
    .galerie figcaption { margin-top: 0.5rem; color: var(--muted); font-size: 12.5px; }
    @media (max-width: 760px) { .galerie { grid-template-columns: 1fr; } .galerie figure:last-child { max-width: 260px; } }

    .steps { list-style: none; padding: 0; margin: 0 0 1rem; display: grid; gap: 10px; }
    .steps li { display: grid; grid-template-columns: 2rem 1fr; gap: 0.8rem; padding: 12px 14px; background: var(--card); border: 1px solid var(--card-line); border-radius: 10px; }
    .steps .n { font-family: "IBM Plex Mono", monospace; font-weight: 600; color: var(--accent); }
    .steps p { margin: 0.2rem 0 0; color: var(--muted); font-size: 13.5px; overflow-wrap: anywhere; }

    #a-venir { padding: 14px 16px; border: 1px dashed var(--card-line); border-radius: 12px; }
    #a-venir .lead { margin: 0; }

    .encart { padding: 16px 18px; background: var(--accent-soft); border: 1px solid var(--accent); border-radius: 12px; }
    .encart h2 { margin-bottom: 0.5rem; }
    .encart p { color: var(--soft); margin: 0 0 0.8rem; }

    .journal { border-left: 2px solid var(--line); padding-left: 1.1rem; }
    .journal div { margin-bottom: 1rem; }
    .journal b { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--accent); }
    .journal p { margin: 0.2rem 0 0; color: var(--muted); font-size: 13.5px; }

    footer { margin: 3rem auto 2rem; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12.5px; }
    @media (prefers-reduced-motion: no-preference) {
      .hero .brand, .hero .pitch, .hero .cta, .ecran { animation: rise 0.5s ease both; }
      .hero .pitch { animation-delay: 0.05s; }
      .hero .cta { animation-delay: 0.1s; }
      .ecran { animation-delay: 0.15s; }
      @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    }
  </style>
</head>
<body>
  <div class="topbar">
    <img src="${racine}assets/atelier.svg" alt="" />
    <span class="crumb"><b>${echapper(v.nom)}</b> · ${echapper(ui.chart)} ${echapper(versions.chart)}</span>
    <span class="status"><span class="dot" aria-hidden="true"></span> SSPCloud · Onyxia · open source</span>
    ${selecteurLangue(langue, ui.choixLangue)}
  </div>
  <header class="hero">
    <div class="wrap">
      <p class="eyebrow">${echapper(ui.eyebrow)}</p>
      <h1 class="brand">${echapper(v.nom)}</h1>
      <p class="pitch">${echapper(v.pitch)}</p>
      <div class="tags">${tags}</div>
      <div class="cta">
        <a class="btn primary" href="#installer">${echapper(ui.boutonInstaller)}</a>
        <a class="btn ghost" href="${echapper(v.depot)}">${echapper(ui.boutonCode)}</a>
      </div>
      ${hero ? `<figure class="ecran"><img src="${racine}assets/${echapper(hero.fichier)}" alt="${echapper(hero.alt)}" width="1440" height="900" /></figure>` : ""}
    </div>
  </header>
  <main class="wrap">
    <section id="produit">
      <p class="accroche">${echapper(v.produit.accroche)}</p>
      ${blocChiffres(v.chiffres)}
    </section>
    ${blocPoints(v)}
    ${blocFonctionnalites(v)}
    ${blocApercu(v, racine)}
    ${blocSequence(v)}
    ${blocInstaller(v)}
    ${blocContextes(v)}
    ${blocEncart(v.encart)}
    ${blocAVenir(v)}
    ${blocStack(v)}
    ${blocJournal(v)}
  </main>
  <footer class="wrap">
    <p>${echapper(ui.piedLicence)} · <a href="${echapper(v.depot)}">${echapper(depotCourt)}</a></p>
    <p>${echapper(ui.piedProjet)}</p>
  </footer>
</body>
</html>
`;
}

export function generate({ vitrinePath = VITRINE, chartDir = CHART_DIR, distDir = DIST } = {}) {
  const brute = chargerVitrine(vitrinePath);
  const versions = lireVersions(chartDir);
  const gabarits = { version: versions.chart, pages: PAGES_URL };

  fs.mkdirSync(path.join(distDir, "assets"), { recursive: true });
  for (const asset of fs.readdirSync(path.join(ROOT, "assets"))) {
    fs.copyFileSync(path.join(ROOT, "assets", asset), path.join(distDir, "assets", asset));
  }

  const pages = LANGUES.map((langue) => {
    const html = rendreHtml(localiser(brute, langue.code, gabarits), langue, versions);
    const dossier = path.join(distDir, langue.dossier);
    fs.mkdirSync(dossier, { recursive: true });
    const out = path.join(dossier, "index.html");
    fs.writeFileSync(out, html, "utf8");
    return { langue: langue.code, out, bytes: Buffer.byteLength(html, "utf8") };
  });
  return { pages, versions };
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const r = generate();
  for (const p of r.pages) console.log(`[site] ${p.langue} : écrit ${p.out} (${p.bytes} octets)`);
  console.log(`[site] chart ${r.versions.chart}`);
}
