/**
 * Les échanges d'une conversation avec d'autres agents (fils wikichat).
 *
 * wikichat tient, pour chaque conversation, les fils de messages qu'elle
 * échange : qui attend une réponse de qui, pour quand, et les derniers mots.
 * L'Atelier les relit (`GET /v1/sessions/{id}/fils`, contrat de
 * `hooks-et-dialogue.md` §8) et les montre sous la barre de la conversation.
 *
 * Le bouton « Échanges » ne paraît que s'il y a au moins un fil ouvert ; il
 * dit combien attendent cette conversation. Tout ce qui vient de wikichat est
 * posé en `textContent`.
 */

function el(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte != null) n.textContent = String(texte);
  return n;
}

/** Combien de fils attendent l'agent de cette conversation. */
export function filsQuiAttendent(rendu) {
  const agent = rendu?.agent || "";
  return (rendu?.fils || []).filter((f) => agent && (f.attend || []).includes(agent)).length;
}

/** Le libellé du bouton : rien à dire, rien d'affiché. */
export function libelleEchanges(rendu) {
  const fils = rendu?.fils || [];
  if (!fils.length) return "";
  const attendent = filsQuiAttendent(rendu);
  return attendent ? `Échanges (${fils.length}, ${attendent} attend${attendent > 1 ? "ent" : ""} une réponse)` : `Échanges (${fils.length})`;
}

export function rendreFils(conteneur, rendu) {
  const liste = el("div", "apps-liste");
  liste.appendChild(el("div", "apps-titre", "Échanges avec d'autres agents"));
  if (rendu?.indisponible) {
    liste.appendChild(el("p", "apps-note", "wikichat ne répond pas : les échanges ne se lisent pas pour l'instant."));
  }
  for (const f of rendu?.fils || []) {
    const ligne = el("div", "apps-ligne fil-ligne");
    ligne.appendChild(el("span", "apps-nom", (f.participants || []).join(" ↔ ")));
    const attend = (f.attend || []).length ? `attend : ${f.attend.join(", ")}` : "rien d'attendu";
    const etat = el("span", `apps-etat${f.en_retard ? " fil-en-retard" : ""}`, f.en_retard ? `${attend} (en retard)` : attend);
    ligne.appendChild(etat);
    ligne.appendChild(el("div", "fil-sujet", f.sujet || ""));
    for (const m of (f.messages || []).slice(-3)) {
      ligne.appendChild(el("div", "fil-message", `${m.de || "?"} : ${m.extrait || ""}`));
    }
    liste.appendChild(ligne);
  }
  conteneur.replaceChildren(liste);
}

export function createFilsView({ state, api }) {
  let session = null;
  let rendu = null;
  let ouvert = false;

  async function charger(sessionId) {
    const meme = session === sessionId;
    session = sessionId;
    if (!meme) {
      rendu = null;
      ouvert = false;
      rendre();
    }
    if (!sessionId) return;
    try {
      const r = await api.filsDeLaConversation(sessionId);
      if (session === sessionId) rendu = r;
    } catch {
      rendu = null;
    }
    rendre();
  }

  function rendre() {
    const bouton = document.getElementById("session-fils-button");
    const zone = document.getElementById("fils-panel");
    if (!bouton || !zone) return;
    const libelle = state.view === "code" && state.sessionId ? libelleEchanges(rendu) : "";
    bouton.hidden = !libelle;
    bouton.textContent = libelle || "Échanges";
    zone.hidden = !(libelle && ouvert);
    bouton.setAttribute("aria-expanded", zone.hidden ? "false" : "true");
    if (!zone.hidden) rendreFils(zone, rendu);
  }

  function bind() {
    document.getElementById("session-fils-button")?.addEventListener("click", () => {
      ouvert = !ouvert;
      rendre();
    });
  }

  /** À chaque rendu ; relit quand la conversation change, ou sur demande. */
  function renderFils({ relire = false } = {}) {
    const sid = state.sessionId || null;
    if (sid !== session || relire) {
      charger(sid);
      return;
    }
    rendre();
  }

  return { bind, renderFils };
}
