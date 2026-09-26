import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  PAGES_URL, STATUTS, capturesCitees, chargerVitrine, echapper, generate, localiser, lireControles,
  lireJetons, lireVersions, lireVues, verifierTraductions,
} from "./generate.mjs";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const brute = () => JSON.parse(fs.readFileSync(path.join(ROOT, "vitrine.json"), "utf8"));
const ecrire = (v) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-site-"));
  const f = path.join(dir, "vitrine.json");
  fs.writeFileSync(f, JSON.stringify(v));
  return f;
};
const genererDansUnDossier = () => {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-dist-"));
  fs.writeFileSync(path.join(dist, "index.yaml"), "apiVersion: v1\n");
  const r = generate({ distDir: dist });
  return {
    ...r,
    dist,
    fr: fs.readFileSync(path.join(dist, "index.html"), "utf8"),
    en: fs.readFileSync(path.join(dist, "en", "index.html"), "utf8"),
  };
};

test("echapper neutralise le HTML", () => {
  assert.equal(echapper(`a<b>&"c`), "a&lt;b&gt;&amp;&quot;c");
  assert.equal(echapper("« x » : y"), "«&nbsp;x&nbsp;»&nbsp;: y");
});

test("chargerVitrine refuse un JSON incomplet", () => {
  assert.throws(() => chargerVitrine(ecrire({ nom: "X" })), /champ requis/);
});

test("chargerVitrine refuse une traduction incomplète, en nommant la clé", () => {
  const v = brute();
  v.cas.liste[1].titre.en = "  ";
  assert.throws(() => chargerVitrine(ecrire(v)), /cas\.liste\[1\]\.titre : en manquant ou vide/);
});

test("chargerVitrine refuse un statut inconnu", () => {
  const v = brute();
  v.capacites.familles[0].items[0].statut = "presque";
  assert.throws(() => chargerVitrine(ecrire(v)), /statut inconnu/);
});

test("verifierTraductions signale chaque trou avec son chemin", () => {
  const erreurs = verifierTraductions({
    a: { fr: "oui", en: "yes" },
    b: [{ titre: { fr: "seul" } }],
    c: { en: "only", autre: 1 },
  });
  assert.deepEqual(erreurs, [
    "b[0].titre : en manquant ou vide",
    "c : clés de langue mêlées à d'autres clés (en, autre)",
    "c : fr manquant ou vide",
  ]);
});

test("vitrine.json : chaque texte a son français et son anglais", () => {
  const erreurs = verifierTraductions(brute());
  assert.deepEqual(erreurs, [], `traductions incomplètes :\n  ${erreurs.join("\n  ")}`);
});

test("localiser résout les traductions et les gabarits", () => {
  const v = { a: { fr: "v{{version}}", en: "v{{version}} en" }, b: ["neutre", { fr: "x", en: "y" }] };
  assert.deepEqual(localiser(v, "en", { version: "1.2.3" }), { a: "v1.2.3 en", b: ["neutre", "y"] });
});

test("ce qui se lit dans le code est lu dans le code", () => {
  assert.match(lireVersions().chart, /^\d+\.\d+\.\d+$/);
  const vues = lireVues();
  assert.deepEqual(vues, ["Code", "Assistant", "Connecteurs", "Agents", "À valider", "Journal", "Ma mémoire"]);
  assert.ok(lireControles() > 0);
  const jetons = lireJetons();
  assert.match(jetons, /:root\[data-theme="clair"\]/);
  assert.match(jetons, /prefers-color-scheme: light/);
  assert.doesNotMatch(jetons, /\/\*/, "les commentaires des jetons ne passent pas dans la page");
});

test("chaque capture citée existe dans ses deux thèmes", () => {
  const citees = capturesCitees(brute());
  assert.ok(citees.length >= 4);
  for (const f of citees) {
    assert.ok(fs.existsSync(path.join(ROOT, "assets", "captures", f)), `capture absente : ${f}`);
  }
});

test("generate produit les deux pages, leurs sections et les assets", () => {
  const { pages, versions, vues, controles, dist, fr, en } = genererDansUnDossier();
  assert.deepEqual(pages.map((p) => p.langue), ["fr", "en"]);
  assert.ok(fs.existsSync(path.join(dist, "index.yaml")), "generate a effacé un fichier qui n'est pas à lui");
  assert.match(fr, /<html lang="fr">/);
  assert.match(en, /<html lang="en">/);

  for (const html of [fr, en]) {
    assert.ok(Buffer.byteLength(html) > 20000);
    for (const id of ["contenu", "promesse", "capacites", "visite", "cas", "associations", "architecture", "installer", "limites", "stack"]) {
      assert.match(html, new RegExp(`id="${id}"`), `section ${id} absente`);
    }
    // Chaque lien du menu mène à une section de la page.
    for (const m of html.matchAll(/<a href="#([a-z-]+)">/g)) {
      assert.match(html, new RegExp(`id="${m[1]}"`), `ancre #${m[1]} sans cible`);
    }
    assert.ok(html.includes(`<link rel="alternate" hreflang="fr" href="${PAGES_URL}/" />`), "hreflang fr absent");
    assert.ok(html.includes(`<link rel="alternate" hreflang="en" href="${PAGES_URL}/en/" />`), "hreflang en absent");
    assert.ok(html.includes(`<link rel="alternate" hreflang="x-default" href="${PAGES_URL}/" />`), "x-default absent");
    // Les couleurs sont celles de l'interface, dans ses deux thèmes.
    assert.match(html, /--surface-1: #121519;/);
    assert.match(html, /:root\[data-theme="clair"\]/);
    assert.match(html, /\.ecran-sombre/);
    // Chiffres lus dans le code.
    assert.ok(html.includes(versions.chart), "version du chart absente");
    assert.ok(html.includes(`<strong>${vues.length}</strong>`), "nombre de vues absent");
    assert.ok(html.includes(`<strong>${controles}</strong>`), "nombre de contrôles absent");
    assert.ok(html.includes(`helm repo add atelier ${PAGES_URL}`), "commande helm absente");
    assert.ok(html.includes(`curl -fsSL ${PAGES_URL}/install.sh | bash`), "commande install.sh absente");
    assert.doesNotMatch(html, /undefined|\[object Object\]|\{\{/);
    // Accessibilité : un lien d'évitement, des images toutes décrites, un schéma titré.
    assert.match(html, /class="evitement" href="#contenu"/);
    const images = [...html.matchAll(/<img [^>]*>/g)].map((m) => m[0]);
    assert.ok(images.length > 10);
    for (const img of images.filter((i) => !i.includes("atelier.svg"))) {
      assert.match(img, /alt="[^"]{20,}"/, `image sans description : ${img.slice(0, 80)}`);
    }
    assert.match(html, /<svg class="schema"[^>]*role="img" aria-labelledby="schema-titre">/);
    // Aucun statut hors de la liste.
    for (const m of html.matchAll(/class="statut statut-(\w+)"/g)) assert.ok(m[1] in STATUTS);
  }

  assert.match(fr, /rel="canonical" href="https:\/\/nic01asfr\.github\.io\/atelier-sspcloud\/"/);
  assert.match(en, /rel="canonical" href="https:\/\/nic01asfr\.github\.io\/atelier-sspcloud\/en\/"/);
  // Sélecteur : chaque page se marque courante et pointe vers l'autre.
  assert.match(fr, /<span aria-current="page" lang="fr">FR<\/span> <a href="en\/" hreflang="en"/);
  assert.match(en, /<a href="\.\.\/" hreflang="fr" lang="fr">FR<\/a> <span aria-current="page" lang="en">EN<\/span>/);
  // Les captures se résolvent depuis chaque page, dans les deux thèmes.
  assert.match(fr, /src="assets\/captures\/code-creation-clair\.webp"/);
  assert.match(fr, /src="assets\/captures\/code-creation-sombre\.webp"/);
  assert.match(en, /src="\.\.\/assets\/captures\/code-creation-clair\.webp"/);
  for (const f of ["atelier.svg", ...capturesCitees(brute()).map((c) => `captures/${c}`)]) {
    assert.ok(fs.existsSync(path.join(dist, "assets", f)), `asset ${f} absent`);
  }
});

test("la page anglaise ne reprend aucun texte français de la vitrine", () => {
  const { en } = genererDansUnDossier();
  const vues = lireVues();
  const trahisons = [];
  const parcourir = (v) => {
    if (Array.isArray(v)) return v.forEach(parcourir);
    if (v && typeof v === "object") {
      if (typeof v.fr === "string" && typeof v.en === "string") {
        // Un texte identique dans les deux langues (« Architecture ») ne trahit rien.
        // Les noms de vues de l'interface, lus dans son code, restent en français.
        const nomDeVue = vues.some((n) => n.includes(v.fr));
        if (v.fr !== v.en && !nomDeVue && en.includes(echapper(v.fr))) trahisons.push(v.fr);
        return;
      }
      Object.values(v).forEach(parcourir);
    }
  };
  parcourir(brute());
  assert.deepEqual(trahisons, []);
  // Les noms des vues restent en français (ce sont ceux de l'interface) ;
  // aucune phrase française ne doit passer ailleurs.
  const texte = en.replace(/<[^>]+>/g, " ").replace(/Ma mémoire|À valider|Connecteurs|Journal/g, "");
  assert.doesNotMatch(texte, /\b(le|la|les|des|une|avec|pour|dans)\b [a-zà-ÿ]/, "mot français courant sur la page anglaise");
});

test("le script de thème survit à un stockage indisponible", () => {
  const { fr } = genererDansUnDossier();
  const scripts = [...fr.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  assert.equal(scripts.length, 2);
  for (const s of scripts) assert.match(s, /try\s*\{[^}]*localStorage/);
});
