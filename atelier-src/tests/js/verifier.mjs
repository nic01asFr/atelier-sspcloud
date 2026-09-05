// Le strict nécessaire pour affirmer quelque chose dans une suite JavaScript.
//
// Pas de bibliothèque : le dépôt est en Python, node n'y est qu'un exécutant.
// Ce qu'une assertion doit faire tient en trois lignes — dire ce qu'elle
// attendait, dire ce qu'elle a eu, et faire sortir le processus en erreur pour
// que pytest le voie.

let verifications = 0;
let echecs = 0;

function montrer(v) {
  if (v === undefined) return "undefined";
  if (typeof v === "string") return JSON.stringify(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** Comparaison de valeurs, structure comprise : deux listes de blocs se comparent. */
function memeValeur(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (a === null || b === null || typeof a !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ca = Object.keys(a);
  const cb = Object.keys(b);
  if (ca.length !== cb.length) return false;
  return ca.every((c) => Object.hasOwn(b, c) && memeValeur(a[c], b[c]));
}

function signaler(message, attendu, obtenu) {
  echecs += 1;
  console.log(`ÉCHEC  ${message}`);
  if (attendu !== undefined) console.log(`  attendu : ${attendu}`);
  if (obtenu !== undefined) console.log(`  obtenu  : ${obtenu}`);
}

/** La condition doit tenir. Le message dit ce qui est en jeu, pas ce qu'on teste. */
export function verifier(condition, message) {
  verifications += 1;
  if (!condition) signaler(message, "vrai", montrer(condition));
  return !!condition;
}

/** Les deux valeurs doivent être les mêmes, jusque dans leur structure. */
export function egal(obtenu, attendu, message) {
  verifications += 1;
  if (memeValeur(obtenu, attendu)) return true;
  signaler(message, montrer(attendu), montrer(obtenu));
  return false;
}

/** Le texte doit porter ce morceau — pour un rendu qu'on ne veut pas figer en entier. */
export function porte(texteObtenu, morceau, message) {
  verifications += 1;
  if (String(texteObtenu).includes(morceau)) return true;
  signaler(message, `contient ${montrer(morceau)}`, montrer(texteObtenu));
  return false;
}

/** Le texte ne doit pas porter ce morceau — ce qu'on empêche de revenir. */
export function nePorte(texteObtenu, morceau, message) {
  verifications += 1;
  if (!String(texteObtenu).includes(morceau)) return true;
  signaler(message, `sans ${montrer(morceau)}`, montrer(texteObtenu));
  return false;
}

/**
 * Le compte-rendu, et le verdict que pytest lira.
 *
 * Un seul échec suffit à faire sortir en 1 ; on les affiche tous d'abord, car
 * s'arrêter au premier obligerait à relancer autant de fois qu'il y a de
 * défauts.
 */
export function bilan(nomDeLaSuite) {
  console.log(`${nomDeLaSuite} : ${verifications} vérification(s), ${echecs} échec(s)`);
  process.exit(echecs === 0 ? 0 : 1);
}
