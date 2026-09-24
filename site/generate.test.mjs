import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  PAGES_URL, chargerVitrine, echapper, generate, localiser, lireVersions, verifierTraductions,
} from "./generate.mjs";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const brute = () => JSON.parse(fs.readFileSync(path.join(ROOT, "vitrine.json"), "utf8"));

test("echapper neutralise le HTML", () => {
  assert.equal(echapper(`a<b>&"c`), "a&lt;b&gt;&amp;&quot;c");
  assert.equal(echapper("« x » : y"), "«&nbsp;x&nbsp;»&nbsp;: y");
});

test("chargerVitrine refuse un JSON incomplet", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-site-"));
  const f = path.join(dir, "bad.json");
  fs.writeFileSync(f, JSON.stringify({ nom: "X" }));
  assert.throws(() => chargerVitrine(f), /champ requis/);
});

test("chargerVitrine refuse une traduction incomplète, en nommant la clé", () => {
  const v = brute();
  v.produit.sequence[1].texte.en = "  ";
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-site-"));
  const f = path.join(dir, "trou.json");
  fs.writeFileSync(f, JSON.stringify(v));
  assert.throws(() => chargerVitrine(f), /produit\.sequence\[1\]\.texte : en manquant ou vide/);
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

test("lireVersions relit le chart plutôt qu'une copie", () => {
  const v = lireVersions();
  assert.match(v.chart, /^\d+\.\d+\.\d+$/);
});

test("generate produit les deux pages, leurs sections et les assets", () => {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-dist-"));
  fs.writeFileSync(path.join(dist, "index.yaml"), "apiVersion: v1\n");
  const { pages, versions } = generate({ distDir: dist });
  assert.deepEqual(pages.map((p) => p.langue), ["fr", "en"]);
  assert.ok(fs.existsSync(path.join(dist, "index.yaml")), "generate a effacé un fichier qui n'est pas à lui");

  const fr = fs.readFileSync(path.join(dist, "index.html"), "utf8");
  const en = fs.readFileSync(path.join(dist, "en", "index.html"), "utf8");
  assert.match(fr, /<html lang="fr">/);
  assert.match(en, /<html lang="en">/);

  for (const html of [fr, en]) {
    assert.ok(Buffer.byteLength(html) > 5000);
    for (const id of ["produit", "promesse", "fonctionnalites", "apercu", "parcours", "installer", "usages", "securite", "a-venir", "stack", "journal"]) {
      assert.match(html, new RegExp(`id="${id}"`), `section ${id} absente`);
    }
    assert.ok(html.includes(`<link rel="alternate" hreflang="fr" href="${PAGES_URL}/" />`), "hreflang fr absent");
    assert.ok(html.includes(`<link rel="alternate" hreflang="en" href="${PAGES_URL}/en/" />`), "hreflang en absent");
    assert.ok(html.includes(`<link rel="alternate" hreflang="x-default" href="${PAGES_URL}/" />`), "x-default absent");
    assert.match(html, /--accent: #D6B27A/);
    assert.ok(html.includes(versions.chart), "version du chart absente");
    assert.ok(html.includes(`helm repo add atelier ${PAGES_URL}`), "commande helm absente");
    assert.doesNotMatch(html, /undefined|\[object Object\]|\{\{/);
  }

  assert.match(fr, /rel="canonical" href="https:\/\/nic01asfr\.github\.io\/atelier-sspcloud\/"/);
  assert.match(en, /rel="canonical" href="https:\/\/nic01asfr\.github\.io\/atelier-sspcloud\/en\/"/);
  // Sélecteur : chaque page se marque courante et pointe vers l'autre.
  assert.match(fr, /<span aria-current="page" lang="fr">FR<\/span> · <a href="en\/" hreflang="en"/);
  assert.match(en, /<a href="\.\.\/" hreflang="fr" lang="fr">FR<\/a> · <span aria-current="page" lang="en">EN<\/span>/);
  // Les assets se résolvent depuis chaque page.
  assert.match(fr, /src="assets\/01-code\.png"/);
  assert.match(en, /src="\.\.\/assets\/01-code\.png"/);
  for (const f of ["atelier.svg", "01-code.png", "03-connecteurs.png", "04-agents.png", "05-code-mobile.png"]) {
    assert.ok(fs.existsSync(path.join(dist, "assets", f)), `asset ${f} absent`);
  }
});

test("la page anglaise ne reprend aucun texte français de la vitrine", () => {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "atelier-dist-"));
  generate({ distDir: dist });
  const en = fs.readFileSync(path.join(dist, "en", "index.html"), "utf8");
  const trahisons = [];
  const parcourir = (v) => {
    if (Array.isArray(v)) return v.forEach(parcourir);
    if (v && typeof v === "object") {
      if (typeof v.fr === "string" && typeof v.en === "string") {
        // Un texte identique dans les deux langues (« Stack », « Helm ») ne trahit rien.
        if (v.fr !== v.en && en.includes(echapper(v.fr))) trahisons.push(v.fr);
        return;
      }
      Object.values(v).forEach(parcourir);
    }
  };
  parcourir(brute());
  assert.deepEqual(trahisons, []);
  assert.doesNotMatch(en, /\b(le|la|les|des|une|avec|pour|dans)\b [a-zà-ÿ]/, "mot français courant sur la page anglaise");
});
