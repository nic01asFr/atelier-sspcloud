/**
 * Une autorisation tranchée rejoint le geste qui l'a demandée.
 *
 * Une demande qu'on trouve déjà posée en ouvrant une conversation (un agent
 * lancé ailleurs, un autre onglet) n'est pas dans le fil de l'agent : elle est
 * une carte à part, en bas. Une fois tranchée — par la personne ici, ou par un
 * lanceur —, cette carte n'a plus rien à demander : elle se retire, et son
 * verdict se pose sur la ligne de l'outil (`verdict`), comme pour une demande
 * suivie dans le flux. Fonction pure : elle rend un nouveau tableau.
 */

/** Ce que dit un verdict du service (`cause` d'un `decision_rendue`) : allow, deny, ou rien. */
export function verdictDeLaCause(cause) {
  const c = String(cause || "");
  if (c === "allow" || c.startsWith("regle:")) return "allow";
  if (c === "deny") return "deny";
  return "";
}

/**
 * @param {object[]} messages les messages du fil
 * @param {string} requestId la demande tranchée
 * @param {"allow"|"deny"} etat le verdict
 * @returns {object[]} les messages, la carte retirée si son outil est dans le fil
 */
export function rattacherLeVerdict(messages, requestId, etat) {
  if (!Array.isArray(messages) || (etat !== "allow" && etat !== "deny")) return messages;
  let carte = null;
  for (const m of messages) {
    for (const b of m?.blocks || []) {
      if (b?.type === "decision" && b.demande?.request_id === requestId) carte = b;
    }
  }
  const outilId = carte?.demande?.tool_use_id;
  if (!carte || !outilId || carte.demande?.genre === "question") return messages;
  const outilPresent = messages.some((m) => (m?.blocks || []).some((b) => b?.type === "tool" && b.id === outilId));
  if (!outilPresent) return messages;

  const suivant = [];
  for (const m of messages) {
    const blocs = m?.blocks;
    if (!Array.isArray(blocs)) {
      suivant.push(m);
      continue;
    }
    const nouveaux = [];
    for (const b of blocs) {
      if (b?.type === "decision" && b.demande?.request_id === requestId) continue;
      nouveaux.push(b?.type === "tool" && b.id === outilId ? { ...b, verdict: etat } : b);
    }
    const resteQuelqueChose = nouveaux.some((b) => b?.type !== "decision" || b.demande?.request_id !== requestId);
    // Un message système qui ne portait que cette carte disparaît avec elle.
    if (m.role === "system" && blocs.length > 0 && nouveaux.length === 0) continue;
    suivant.push(resteQuelqueChose || nouveaux.length ? { ...m, blocks: nouveaux } : m);
  }
  return suivant;
}
