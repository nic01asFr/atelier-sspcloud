#!/usr/bin/env node
/**
 * Vérifie les liens relatifs de la documentation : chaque lien d'un fichier
 * Markdown suivi par git vers un fichier du dépôt doit mener à un fichier qui
 * existe, et une ancre (`#titre`) vers un titre qui existe.
 *
 *   node scripts/verifier-liens.mjs          # tout le dépôt
 *   node scripts/verifier-liens.mjs docs     # un dossier
 *
 * Sortie 0 sans lien cassé, 1 sinon. Les liens externes (http, https,
 * mailto) ne sont pas suivis : ce script ne touche pas au réseau.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RACINE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Le slug d'un titre, comme GitHub le calcule pour ses ancres. */
export function slugDeTitre(titre) {
  return titre
    .trim()
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[`*_~]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s/g, "-");
}

/** Les ancres d'un fichier Markdown : titres (avec suffixes -1, -2…) et ancres HTML. */
export function ancresDe(texte) {
  const vues = new Map();
  const ancres = new Set();
  let dansUnBloc = false;
  for (const ligne of texte.split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(ligne)) dansUnBloc = !dansUnBloc;
    if (dansUnBloc) continue;
    const m = ligne.match(/^#{1,6}\s+(.*?)\s*#*\s*$/);
    if (m) {
      const base = slugDeTitre(m[1]);
      const n = vues.get(base) || 0;
      vues.set(base, n + 1);
      ancres.add(n ? `${base}-${n}` : base);
    }
    for (const a of ligne.matchAll(/<a\s+(?:name|id)="([^"]+)"/g)) ancres.add(a[1]);
  }
  return ancres;
}

/** Les liens d'un texte Markdown, hors blocs de code et code en ligne. */
export function liensDe(texte) {
  const liens = [];
  let dansUnBloc = false;
  texte.split(/\r?\n/).forEach((ligne, i) => {
    if (/^\s*(```|~~~)/.test(ligne)) {
      dansUnBloc = !dansUnBloc;
      return;
    }
    if (dansUnBloc) return;
    const sansCode = ligne.replace(/`[^`]*`/g, "");
    for (const m of sansCode.matchAll(/!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g)) {
      liens.push({ cible: m[1], ligne: i + 1 });
    }
    for (const m of sansCode.matchAll(/(?:src|href)="([^"]+)"/g)) liens.push({ cible: m[1], ligne: i + 1 });
  });
  return liens;
}

function estExterne(cible) {
  return /^[a-z][a-z0-9+.-]*:/i.test(cible) || cible.startsWith("//");
}

export function verifier(fichiers, racine = RACINE) {
  const erreurs = [];
  const cacheAncres = new Map();
  const ancresDuFichier = (f) => {
    if (!cacheAncres.has(f)) cacheAncres.set(f, ancresDe(fs.readFileSync(f, "utf8")));
    return cacheAncres.get(f);
  };
  for (const relatif of fichiers) {
    const fichier = path.join(racine, relatif);
    const texte = fs.readFileSync(fichier, "utf8");
    for (const { cible, ligne } of liensDe(texte)) {
      if (estExterne(cible)) continue;
      const [chemin, ancre] = cible.split("#");
      let visee = fichier;
      if (chemin) {
        const decode = decodeURIComponent(chemin);
        visee = decode.startsWith("/") ? path.join(racine, decode) : path.resolve(path.dirname(fichier), decode);
        if (!fs.existsSync(visee)) {
          erreurs.push(`${relatif}:${ligne} : ${cible} (fichier absent)`);
          continue;
        }
      }
      if (ancre && visee.endsWith(".md") && fs.statSync(visee).isFile()) {
        if (!ancresDuFichier(visee).has(decodeURIComponent(ancre).toLowerCase())) {
          erreurs.push(`${relatif}:${ligne} : ${cible} (ancre absente)`);
        }
      }
    }
  }
  return erreurs;
}

function fichiersMarkdown(dossier) {
  const sortie = execFileSync("git", ["ls-files", "--", dossier ? `${dossier}` : "."], { cwd: RACINE, encoding: "utf8" });
  return sortie.split("\n").filter((f) => f.endsWith(".md"));
}

const estLePointDEntree = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (estLePointDEntree) {
  const fichiers = fichiersMarkdown(process.argv[2] || "");
  const erreurs = verifier(fichiers);
  for (const e of erreurs) console.log(e);
  console.log(`[liens] ${fichiers.length} fichiers Markdown, ${erreurs.length} lien(s) cassé(s)`);
  process.exit(erreurs.length ? 1 : 0);
}
