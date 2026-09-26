// Aucune icône emoji dans l'interface.
//
// L'interface montrait des emoji en guise d'icônes (dossier, clé, sablier,
// coche, loupe, trombone) : leur rendu change d'un système à l'autre, leur
// taille ne suit pas le texte et ils ignorent le thème. Les icônes viennent
// désormais d'un seul jeu SVG (`ui/icones.js`). Cette suite empêche qu'un
// emoji revienne dans le code de l'interface ou dans la page.

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";

import { bilan, egal } from "./verifier.mjs";

const RACINE = "mcp_gateway/atelier/web";

// Emoji et pictogrammes : symboles divers, dingbats, flèches et formes
// d'emoji, ainsi que les entités HTML numériques au-delà du plan de base.
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2300}-\u{23FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]|&#1\d{4,};/u;

async function fichiers(dossier) {
  const out = [];
  for (const entree of await readdir(dossier, { withFileTypes: true })) {
    const chemin = join(dossier, entree.name);
    if (entree.isDirectory()) out.push(...(await fichiers(chemin)));
    else if (/\.(js|html)$/.test(entree.name)) out.push(chemin);
  }
  return out;
}

const fautes = [];
for (const chemin of await fichiers(RACINE)) {
  const lignes = (await readFile(chemin, "utf-8")).split("\n");
  lignes.forEach((ligne, i) => {
    const code = ligne.trim();
    // Les commentaires peuvent citer ce qu'on a retiré.
    if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
    if (EMOJI.test(ligne)) fautes.push(`${chemin}:${i + 1}: ${code.slice(0, 80)}`);
  });
}

egal(fautes, [], "aucun emoji dans le code de l'interface");

bilan("sans-emoji");
