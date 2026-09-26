// Module `filtre` — garde-fou du dépôt mémoire
//
// PROVENANCE : produit par un agent Claude Code dans le pod SSPCloud
// (llm.lab.sspcloud.fr, qwen3-cursor), run 002 du 2026-08-22.
// 41/41 tests, 11/11 cas de conformité hors tests, 1 Mo scanné en 154 ms.
// Spécification et suite de tests écrites d'avance et non modifiées par l'agent.
//
// À RELIRE AVANT ADOPTION : ce code décide de ce qui sort de la machine.

const BLANCHE = ["knowledge", "ideas", "projects"];

// ──────────────────────────────────────────
// estAutorise
// ──────────────────────────────────────────

export function estAutorise(cheminRelatif) {
  if (typeof cheminRelatif !== "string" || cheminRelatif === "") return false;

  // Backslashes → forward slashes
  const c = cheminRelatif.replace(/\\/g, "/");

  // Path traversal always refused
  if (c.split("/").includes("..")) return false;

  // .gitignore at root is the sole exception
  if (c === ".gitignore") return true;

  // Must contain a path separator (single filename not under a folder)
  if (!c.includes("/")) return false;

  // First segment must be in the white list (case-sensitive)
  return BLANCHE.includes(c.split("/")[0]);
}

// ──────────────────────────────────────────
// contientSecret
// ──────────────────────────────────────────

const MOTIFS = [
  ["github-pat",      /github_pat_[A-Za-z0-9_]{20,}/],
  ["github-token",    /(?:ghp_|gho_|ghs_|ghu_)[A-Za-z0-9]{20,}/],
  ["aws-key",         /AKIA[0-9A-Z]{16}/],
  ["generic-token",   /(?:sk-|tok-|bearer-)[A-Za-z0-9]{16,}/],
  ["jwt",             /eyJ[A-Za-z0-9_-]{20,}/],
  ["private-key",     /-----BEGIN[^\n]*PRIVATE KEY-----/],
  ["url-credentials", /[a-zA-Z][A-Za-z0-9+.\-]{0,15}:\/\/[^\/\s@]{1,64}:[^\/@\s]{1,64}@/],
  ["windows-path",    /[A-Za-z]:[\\/][Uu]sers[\\/]/],
  ["unix-home",       /(?:^|[\s"'`(=,;])\/(?:home|Users)\/[^\/\s]+(?=\/)/],
];

export function contientSecret(texte) {
  if (typeof texte !== "string" || texte === "") return [];

  const vus = [];
  for (const [nom, re] of MOTIFS) {
    if (re.test(texte)) vus.push(nom);
  }
  return vus.sort();
}

// ──────────────────────────────────────────
// estTropGros
// ──────────────────────────────────────────

export function estTropGros(octets) {
  return typeof octets === "number" && octets > 1048576;
}

// ──────────────────────────────────────────
// verifierFichier
// ──────────────────────────────────────────

export function verifierFichier({ chemin, contenu, taille } = {}) {
  const raisons = [];

  if (!estAutorise(chemin)) raisons.push("chemin-non-autorise");

  const poids = typeof taille === "number" ? taille : Buffer.byteLength(contenu ?? "", "utf8");
  if (estTropGros(poids)) raisons.push("trop-gros");

  for (const nom of contientSecret(contenu)) raisons.push("secret:" + nom);

  raisons.sort();
  return { ok: raisons.length === 0, raisons };
}
