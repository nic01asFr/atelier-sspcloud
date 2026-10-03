/**
 * La liste « Services du projet » : ce que l'agent reçoit, pas seulement ce
 * qu'on a coché.
 *
 * Le service distingue le choix (`active`) de la livraison (`distribue`). Un
 * service choisi mais non livré — refusé à l'authentification, ou Onyxia sans
 * déploiement déclaré — ne se coche pas comme les autres : sa case est
 * éteinte, désactivée, et la ligne dit pourquoi. Le choix déjà écrit se garde
 * (`retenus`) : il revient dès que le service est de nouveau livré.
 */

const APPORTS = {
  "Accès aux outils": "chercher un outil, lancer une composition",
  "Coordination et mémoire": "messages, mémoire, agents",
  "Navigateur web": "pages, formulaires, réseau, captures",
};

/** La phrase d'une ligne : ce que le service apporte, ou pourquoi l'agent ne l'a pas. */
export function indiceDuService(c) {
  if (c.fixe) return "toujours présent, dans l’Atelier, VS Code et le terminal";
  if (c.distribue === false) return c.raison || "non livré aux conversations de ce projet";
  if (c.system) return (c.scope || []).length ? `ouvre ${c.scope[0]}` : APPORTS[c.group] || "socle de l’Atelier";
  return `service branché · ${c.id_technique || c.id}`;
}

/**
 * @param {object[]} connecteurs les lignes de `GET /v1/projects/<slug>/mcp`
 * @returns {{ options: object[], retenus: string[] }}
 *   `options` : la liste à cocher ; `retenus` : les choix non livrés à rendre à l'enregistrement.
 */
export function optionsDesServices(connecteurs) {
  const liste = Array.isArray(connecteurs) ? connecteurs : [];
  const options = liste.map((c) => {
    const nonLivre = !c.fixe && c.distribue === false;
    return {
      value: c.id,
      label: c.name,
      checked: nonLivre ? false : !!c.active,
      disabled: !!c.fixe || nonLivre,
      hint: indiceDuService(c),
    };
  });
  const retenus = liste.filter((c) => !c.fixe && c.distribue === false && c.active).map((c) => c.id);
  return { options, retenus };
}
