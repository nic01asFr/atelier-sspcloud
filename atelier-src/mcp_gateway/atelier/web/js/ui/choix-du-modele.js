/**
 * Le choix du modèle d'une conversation, comme `/model` dans Claude Code.
 *
 * Fonctions pures : la liste vient du catalogue du service (`GET /v1/models`,
 * les mêmes modèles que le sélecteur de Claude Code), la valeur est celle de la
 * conversation. Vide = le modèle par défaut du service.
 */

/** Alias que Claude Code connaît toujours ; ils pointent sur les créneaux du pod. */
export const ALIAS_DU_CLI = ["default", "sonnet", "opus", "haiku"];

/** Le nom lisible d'un modèle du catalogue. */
export function libelleDuModele(m) {
  const id = String(m?.id || "");
  const libelle = String(m?.label || "").trim();
  if (!libelle || libelle === id) return id;
  // « Albert API · gpt-oss-120b » dit déjà le modèle (l'identifiant public y
  // ajoute `claude-albert-`) ; « Recommandé » non.
  const nu = id.replace(/^claude-[a-z0-9]+-/, "");
  return libelle.includes(id) || libelle.includes(nu) ? libelle : `${id} · ${libelle}`;
}

/**
 * Les options du sélecteur : le défaut d'abord, puis le catalogue.
 * Un modèle déjà choisi mais absent du catalogue (alias, modèle retiré depuis)
 * reste proposé, pour que la conversation ne change pas de modèle à l'affichage.
 */
export function optionsDuModele(catalogue, valeur = "") {
  const modeles = Array.isArray(catalogue?.models) ? catalogue.models : [];
  const defaut = String(catalogue?.default || "");
  const options = [
    { value: "", label: defaut ? `Modèle par défaut · ${defaut}` : "Modèle par défaut" },
  ];
  for (const m of modeles) {
    if (!m?.id) continue;
    options.push({ value: m.id, label: libelleDuModele(m) });
  }
  if (valeur && !options.some((o) => o.value === valeur)) {
    options.push({ value: valeur, label: valeur });
  }
  return options;
}

/** `/model` ou `/model <nom>` ; null pour tout autre texte. */
export function commandeModele(texte) {
  const m = /^\/model(?:\s+(\S+))?\s*$/i.exec(String(texte || "").trim());
  if (!m) return null;
  return { nom: m[1] || "" };
}

/**
 * Ce que désigne un nom tapé après `/model` : un identifiant du catalogue, un
 * alias du CLI, ou le libellé d'un modèle (sans tenir compte de la casse).
 * `default` rend la conversation au défaut. Rien de reconnu : null.
 */
export function resoudreModele(nom, catalogue) {
  const voulu = String(nom || "").trim();
  if (!voulu) return null;
  const bas = voulu.toLowerCase();
  if (bas === "default") return "";
  const modeles = Array.isArray(catalogue?.models) ? catalogue.models : [];
  const exact = modeles.find((m) => m.id === voulu);
  if (exact) return exact.id;
  if (ALIAS_DU_CLI.includes(bas)) return bas;
  const parId = modeles.find((m) => String(m.id).toLowerCase() === bas);
  if (parId) return parId.id;
  const parFin = modeles.filter((m) => String(m.id).toLowerCase().endsWith(`-${bas}`));
  if (parFin.length === 1) return parFin[0].id;
  const parLibelle = modeles.find((m) => libelleDuModele(m).toLowerCase() === bas);
  return parLibelle ? parLibelle.id : null;
}

/** La réponse à `/model` seul : ce qui existe, et ce qui est en cours. */
export function ditLesModeles(catalogue, courant = "") {
  const modeles = Array.isArray(catalogue?.models) ? catalogue.models : [];
  const actuel = courant || catalogue?.default || "";
  if (!modeles.length) return `Modèle : ${actuel || "celui du service"}.`;
  const lignes = modeles.map((m) => `${m.id === actuel ? "• " : "  "}${libelleDuModele(m)}`);
  return `Modèle : ${actuel || "celui du service"}.\n${lignes.join("\n")}\n/model <nom> pour en changer.`;
}
