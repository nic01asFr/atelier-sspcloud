// Aucune couleur écrite en dur hors du fichier des jetons.
//
// Les deux thèmes (sombre, clair) partagent les mêmes jetons, définis dans
// css/jetons.css. Une couleur écrite en dur ailleurs ne suivrait pas le
// thème : un texte sombre sur fond sombre, ou l'inverse, dès qu'on change.
// Cette suite relit les feuilles de style et le code de l'interface.
//
// Elle vérifie aussi que chaque jeton du thème sombre a son pendant clair.

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

import { bilan, egal, verifier } from "./verifier.mjs";

const WEB = "mcp_gateway/atelier/web";
const COULEUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|:\s*(white|black)\s*[;}]/;

async function fichiers(dossier, extensions) {
  const out = [];
  for (const entree of await readdir(dossier, { withFileTypes: true })) {
    const chemin = join(dossier, entree.name);
    if (entree.isDirectory()) out.push(...(await fichiers(chemin, extensions)));
    else if (extensions.test(entree.name)) out.push(chemin);
  }
  return out;
}

const fautes = [];
for (const chemin of await fichiers(WEB, /\.(css|js|html)$/)) {
  if (chemin.endsWith("jetons.css")) continue;
  const lignes = (await readFile(chemin, "utf-8")).split("\n");
  lignes.forEach((ligne, i) => {
    const code = ligne.trim();
    if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
    // Une entité HTML (`&#128193;`) n'est pas une couleur ; `#id` dans un
    // sélecteur JS non plus : on ne retient que les motifs de couleur.
    const nettoye = ligne.replace(/&#\d+;/g, "").replace(/getElementById\([^)]*\)/g, "");
    if (/\.(js|html)$/.test(chemin) && !/(color|background|fill|stroke|border)\s*[:=]/.test(nettoye)) return;
    if (COULEUR.test(nettoye)) fautes.push(`${chemin}:${i + 1}: ${code.slice(0, 90)}`);
  });
}
egal(fautes, [], "aucune couleur en dur hors de css/jetons.css");

// Chaque jeton du thème sombre a son pendant dans le thème clair.
const jetons = await readFile(join(WEB, "css/jetons.css"), "utf-8");
const bloc = (debut) => {
  const i = jetons.indexOf(debut);
  const j = jetons.indexOf("}", i);
  return new Set([...jetons.slice(i, j).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
};
const sombre = bloc(":root {");
const clair = bloc(':root[data-theme="clair"] {');
const alias = new Set(["--bg", "--bg-elev", "--bg-sidebar", "--text", "--muted", "--danger", "--user", "--assistant"]);
const manquants = [...sombre].filter((n) => !alias.has(n) && !clair.has(n));
egal(manquants, [], "chaque jeton sombre a son pendant clair");
verifier(sombre.size > 40, "le thème sombre définit ses jetons");
verifier(jetons.includes('@media (prefers-color-scheme: light)'), "« suivre le système » suit prefers-color-scheme");

bilan("jetons");
