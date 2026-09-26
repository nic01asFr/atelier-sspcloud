/**
 * Vue Assistant — la liste de ses conversations, à gauche du fil.
 *
 * L'Assistant parle dans le même écran que les projets : même fil, même
 * composeur, même panneau (`code-chat.js`, `panneau.js`). Ce module ne tient
 * que ce qui lui est propre :
 *
 * - la colonne de gauche : « Nouvelle conversation », ses conversations, et
 *   le réglage « Ouvrir l'Atelier sur l'Assistant » (désactivé par défaut
 *   pendant la transition, décision A-3) ;
 * - les libellés du fil et du composeur quand c'est lui qui parle.
 *
 * Lexique S2 : on ne dit à l'écran ni artefact, ni MCP, ni jeton.
 */

import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { icone } from "../ui/icones.js";

/** Ce que le fil dit quand c'est l'Assistant qui l'occupe. */
export const LIBELLES = {
  titre: "Assistant",
  nouvelle: "Nouvelle conversation",
  vide:
    "Dites ce qui vous occupe. L’Assistant connaît votre Atelier : il règle vos projets, " +
    "vos connecteurs et vos agents, et confie le travail dans vos projets à un agent.",
  videSansConversation: "Aucune conversation pour l’instant.",
  composeur: "Écrire à l’Assistant…",
  reglage: "Ouvrir l’Atelier sur l’Assistant",
  reglageAide:
    "À l’ouverture, l’Atelier arrive sur ce fil plutôt que sur vos projets. Désactivé par défaut pendant la transition.",
};

/**
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 * @param {object} ctx.actions — `selectSession`, `nouvelle`, `reglerAccueil`
 */
export function createAssistantView(ctx) {
  const { state, actions } = ctx;

  function ligne(s) {
    const li = document.createElement("li");
    li.className = "session-row";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "session-btn";
    btn.dataset.session = s.session_id;
    btn.title = `${S.sessionLabel(s)}
${S.sessionMetaLine(s)}`;
    btn.classList.toggle("active", s.session_id === state.sessionId);
    if (s.session_id === state.sessionId) btn.setAttribute("aria-current", "true");
    const titre = document.createElement("span");
    titre.className = "session-title-row";
    const point = document.createElement("span");
    const enReponse = s.state === "running";
    const enErreur = s.state === "failed" || s.state === "timeout";
    point.className = `status-dot status-dot-${
      s.attend_une_decision ? "warn" : enReponse ? "busy" : enErreur ? "err" : "ok"
    }`;
    const nom = document.createElement("span");
    nom.className = "session-title";
    nom.textContent = S.sessionLabel(s);
    titre.append(point, nom);
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = S.sessionMetaLine(s);
    btn.append(titre, meta);
    btn.addEventListener("click", () => actions.selectSession(s.session_id));
    li.appendChild(btn);
    return li;
  }

  function reglage() {
    const boite = document.createElement("label");
    boite.className = "assistant-reglage";
    boite.title = LIBELLES.reglageAide;
    const case_ = document.createElement("input");
    case_.type = "checkbox";
    case_.id = "assistant-accueil";
    case_.checked = state.meta?.ui?.accueil_assistant === true;
    case_.addEventListener("change", () => actions.reglerAccueil(case_.checked));
    const texte = document.createElement("span");
    texte.textContent = LIBELLES.reglage;
    boite.append(case_, texte);
    return boite;
  }

  let empreinteRendue = "";

  /** La colonne de gauche, à la place de l'arbre des projets. */
  function render() {
    const racine = $("project-tree");
    if (!racine) return;
    // Même règle que l'arbre des projets : on ne reconstruit que ce qui a
    // changé, sans quoi un clic tombé pendant un rendu se perdait.
    const conversationsVues = S.assistantSessions(state);
    const empreinte = [
      state.meta?.ui?.accueil_assistant === true ? 1 : 0,
      ...conversationsVues.map((x) =>
        [x.session_id, x.title || "", x.state || "", x.turns ?? "", x.attend_une_decision ? 1 : 0].join("~")
      ),
    ].join("|");
    if (empreinte === empreinteRendue && racine.dataset.arbre === "assistant") {
      for (const b of racine.querySelectorAll(".session-btn")) {
        const active = b.dataset.session === state.sessionId;
        b.classList.toggle("active", active);
        if (active) b.setAttribute("aria-current", "true");
        else b.removeAttribute("aria-current");
      }
      return;
    }
    empreinteRendue = empreinte;
    racine.dataset.arbre = "assistant";
    racine.innerHTML = "";
    racine.setAttribute("aria-label", "Conversations de l’Assistant");

    const barre = document.createElement("div");
    barre.className = "tree-toolbar";
    const nouvelle = document.createElement("button");
    nouvelle.type = "button";
    nouvelle.className = "ghost tree-add";
    nouvelle.id = "assistant-nouvelle";
    const ditNouvelle = document.createElement("span");
    ditNouvelle.textContent = LIBELLES.nouvelle;
    nouvelle.append(icone("plus"), ditNouvelle);
    nouvelle.addEventListener("click", () => actions.nouvelle());
    barre.appendChild(nouvelle);
    racine.appendChild(barre);

    const bloc = document.createElement("div");
    bloc.className = "project-block assistant-block";
    const tete = document.createElement("div");
    tete.className = "orphan-head";
    tete.textContent = LIBELLES.titre;
    bloc.appendChild(tete);
    const conversations = S.assistantSessions(state);
    if (conversations.length) {
      const liste = document.createElement("ul");
      liste.className = "session-list";
      for (const s of conversations) liste.appendChild(ligne(s));
      bloc.appendChild(liste);
    } else {
      const vide = document.createElement("p");
      vide.className = "tree-empty";
      vide.textContent = LIBELLES.videSansConversation;
      bloc.appendChild(vide);
    }
    racine.appendChild(bloc);
    racine.appendChild(reglage());
  }

  /**
   * La navigation pendant la transition (A-3) : avec « Ouvrir l'Atelier sur
   * l'Assistant », l'Assistant passe en tête et « Code » devient « Projets ».
   */
  function renderNav(nav) {
    const accueil = state.meta?.ui?.accueil_assistant === true;
    const code = nav.querySelector('[data-view="code"]');
    const assistant = nav.querySelector('[data-view="assistant"]');
    if (code) code.textContent = accueil ? "Projets" : "Code";
    if (typeof nav.insertBefore !== "function" || !assistant?.parentNode) return;
    if (accueil && assistant && nav.firstElementChild !== assistant) nav.insertBefore(assistant, nav.firstElementChild);
    if (!accueil && assistant && code && code.nextElementSibling !== assistant) code.after(assistant);
  }

  return { render, renderNav };
}

/**
 * Les gestes propres à l'Assistant : nouvelle conversation, réglage d'accueil.
 *
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 * @param {() => void} ctx.writeQuery
 * @param {object} ctx.api — `reglerAccueilAssistant`
 */
export function createAssistantActions(ctx) {
  const { state, render, writeQuery, api } = ctx;

  function nouvelle() {
    S.setError(state, "");
    S.setView(state, "assistant");
    S.setSessionId(state, null);
    S.setMessages(state, []);
    S.setPendingProjectSlug(state, null);
    writeQuery();
    render();
  }

  async function reglerAccueil(actif) {
    try {
      const etat = await api.reglerAccueilAssistant(actif);
      state.meta = { ...(state.meta || {}), ui: { ...(state.meta?.ui || {}), accueil_assistant: !!etat?.accueil_assistant } };
      S.setError(state, "");
    } catch (err) {
      S.setError(state, `Réglage non enregistré : ${err.message || err}`);
    }
    render();
  }

  return { nouvelle, reglerAccueil };
}
