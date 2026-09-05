/** Vue Code — barre session, fil de chat, composer. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { appendMessageBody } from "../ui/message-render.js";

/**
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 */
export function createCodeChatView(ctx) {
  const { state, render, composerInput, actions } = ctx;

  // Marge sous laquelle on considère que le lecteur est « en bas ». Assez
  // large pour absorber une ligne qui s'ajoute, assez étroite pour ne pas
  // rattraper quelqu'un qui a délibérément remonté.
  const MARGE_BAS = 80;
// Plus grand que tout fil concevable : le navigateur ramène au maximum réel.
const BAS_DU_FIL = 1e9;

  /**
   * Corriger une question, puis repartir d'elle.
   *
   * On ne réécrit pas le passé : une session Claude ne se rembobine pas. Le
   * serveur ouvre une conversation qui reprend celle-ci jusqu'avant ce
   * message, et la version corrigée y est envoyée. L'originale reste intacte,
   * et le fil qu'on lit continue bien à partir d'ici.
   */
  function ouvrirEdition(div, m, texte) {
    if (div.querySelector(".msg-edition")) return;
    const zone = document.createElement("div");
    zone.className = "msg-edition";
    const champ = document.createElement("textarea");
    champ.className = "msg-edition-champ";
    champ.value = texte;
    champ.rows = Math.min(8, texte.split("\n").length + 1);
    const barre = document.createElement("div");
    barre.className = "msg-actions";

    const valider = document.createElement("button");
    valider.type = "button";
    valider.className = "msg-action";
    valider.textContent = "Reprendre ici";
    valider.addEventListener("click", () => {
      const nouveau = champ.value.trim();
      if (!nouveau) return;
      actions?.reprendreIci?.(m.rang, nouveau);
    });

    const annuler = document.createElement("button");
    annuler.type = "button";
    annuler.className = "msg-action";
    annuler.textContent = "Annuler";
    annuler.addEventListener("click", () => zone.remove());

    champ.addEventListener("keydown", (e) => {
      if (e.key === "Escape") zone.remove();
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        valider.click();
      }
    });

    barre.append(valider, annuler);
    zone.append(champ, barre);
    div.appendChild(zone);
    champ.focus();
    champ.select();
  }

  /**
   * Les gestes qu'on peut faire d'un message, discrètement.
   *
   * On ne pouvait rien en faire : ni copier une réponse — le geste le plus
   * attendu d'une interface conversationnelle — ni reposer une question quand
   * un tour avait échoué.
   *
   * Corriger un message déjà envoyé n'y figure pas, et ce n'est pas un oubli :
   * une session Claude ne se rembobine pas, il faudrait la forker. Offrir la
   * correction serait mentir sur ce qui se passe.
   */
  function renderMessageActions(div, m) {
    const role = m.role || "";
    const texte = (m.text || "").trim();
    if (m.streaming || (!texte && role !== "user")) return;

    const barre = document.createElement("div");
    barre.className = "msg-actions";

    const copier = document.createElement("button");
    copier.type = "button";
    copier.className = "msg-action";
    copier.textContent = "Copier";
    copier.title = "Copier le texte du message";
    copier.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(texte);
        copier.textContent = "Copié";
        setTimeout(() => {
          copier.textContent = "Copier";
        }, 1500);
      } catch {
        S.setError(state, "Copie refusée par le navigateur.");
        render();
      }
    });
    barre.appendChild(copier);

    if (role === "user" && texte && typeof m.rang === "number") {
      const modifier = document.createElement("button");
      modifier.type = "button";
      modifier.className = "msg-action";
      modifier.textContent = "Modifier";
      modifier.title = "Corriger cette question et repartir d’ici";
      modifier.disabled = !!state.busy;
      modifier.addEventListener("click", () => ouvrirEdition(div, m, texte));
      barre.appendChild(modifier);
    }

    div.appendChild(barre);
  }

  // Ce que la bulle dit tant qu'elle n'a rien à montrer. Uniquement des états
  // que les événements attestent : on n'invente pas d'étapes.
  const ATTENTE = {
    attente: "En attente du modèle…",
    reflexion: "Réflexion…",
    outil: "Utilisation d’un outil…",
    decision: "En attente de votre décision…",
  };

  function renderAttente(div, m) {
    if (!m.streaming) return;
    if ((m.text || "").trim() || (m.blocks || []).length) return;
    const p = document.createElement("p");
    p.className = "msg-attente";
    p.textContent = ATTENTE[m.phase] || ATTENTE.attente;
    div.appendChild(p);
  }

  // Une réponse en cours appelle le rendu des centaines de fois — mesuré : 269
  // fragments pour une seule réponse. Or chaque rendu reconstruit le fil puis
  // lit `scrollHeight`, ce qui force une mise en page synchrone de tout
  // l'arbre. Mesuré à la trace : 2 968 ms de mise en page bloquante pour une
  // seule réponse sur 33 messages, et l'onglet se fige sur une conversation
  // plus longue.
  //
  // On ne rend donc qu'une fois par image d'écran. Les appels intermédiaires
  // se fondent dans celui qui vient, et le navigateur retrouve la main entre
  // deux.
  let renduEnAttente = false;

  function renderThread() {
    if (renduEnAttente) return;
    renduEnAttente = true;
    requestAnimationFrame(() => {
      renduEnAttente = false;
      const suite = rendreLeFil();
      // Le défilement attend l'image suivante. Écrit dans la foulée, il
      // oblige le navigateur à calculer la mise en page sur-le-champ pour
      // savoir où est le bas ; une image plus tard, elle est déjà faite et
      // l'écriture ne coûte rien.
      if (suite) requestAnimationFrame(suite);
    });
  }

  // Une seule écoute, posée sur le fil et non sur les cartes : le fil est
  // reconstruit à chaque rendu, les cartes ne survivent pas, le conteneur si.
  let ecouteDecisions = false;

  /**
   * Rend la décision au serveur, qui réveille le tour.
   *
   * La carte annonce, elle n'agit pas. Un 409 dit que plus personne
   * n'attendait — tour fini, interrompu, ou service redémarré : on le dit
   * plutôt que de laisser croire qu'on a débloqué quelque chose.
   */
  async function repondre(detail) {
    try {
      await api.repondreDecision(state.token, detail.requestId, {
        decision: detail.decision,
        motif: detail.motif,
        portee: detail.portee,
        reponses: detail.reponses,
      });
    } catch (e) {
      S.setError(
        state,
        /409/.test(e?.message || "")
          ? "Ce tour n’attend plus cette décision."
          : e?.message || "Réponse refusée."
      );
      render();
      return;
    }
    // Le tour rend bien la décision par le flux — mais seulement si un flux
    // écoute. Après un rechargement, il n'y en a plus : la carte resterait à
    // « en attente » alors qu'on vient de répondre. On la referme ici.
    marquerDecision(
      detail.requestId,
      detail.decision === "allow" ? "allow" : "deny",
      detail.reponses
    );
    render();
    if (!state.busy) await reprendreLesQuestions();
  }

  /** Referme une carte, où qu'elle soit dans le fil. */
  function marquerDecision(requestId, etat, reponses) {
    for (const m of state.messages || []) {
      for (const b of m.blocks || []) {
        if (b.type !== "decision" || b.demande?.request_id !== requestId) continue;
        b.etat = etat;
        // Ce qu'on a répondu se garde avec la carte : sans cela le fil
        // conserverait la question sans sa réponse.
        if (reponses) b.reponses = reponses;
      }
    }
  }

  /**
   * Va chercher les questions posées depuis, quand aucun flux n'écoute.
   *
   * Refuser n'arrête pas l'agent — mesuré : il lit le motif et tente une autre
   * route, donc une autre question. Sans ce rappel, on répondrait une fois
   * puis on regarderait un écran muet pendant que le tour attend.
   */
  async function reprendreLesQuestions() {
    const connues = new Set();
    for (const m of state.messages || []) {
      for (const b of m.blocks || []) {
        if (b.type === "decision" && b.demande?.request_id) connues.add(b.demande.request_id);
      }
    }
    for (let essai = 0; essai < 6; essai += 1) {
      await new Promise((r) => setTimeout(r, 2000));
      let liste;
      try {
        liste = await api.decisionsEnAttente(state.token, state.sessionId);
      } catch {
        return;
      }
      const neuves = (liste?.vives || []).filter((d) => !connues.has(d.request_id));
      if (!neuves.length) continue;
      for (const d of neuves) {
        connues.add(d.request_id);
        S.appendMessage(state, {
          role: "system",
          blocks: [{ type: "decision", demande: d, etat: "en_attente" }],
        });
      }
      render();
      return;
    }
  }

  function rendreLeFil() {
    const thread = $("thread");
    if (!thread) return;
    if (!ecouteDecisions) {
      ecouteDecisions = true;
      thread.addEventListener("atelier:decision", (e) => repondre(e.detail));
    }
    // Le fil est reconstruit à chaque rendu, et une réponse en cours en
    // déclenche des centaines. Recoller systématiquement en bas rendait toute
    // relecture impossible : on ne suit donc que si l'on suivait déjà.
    const suivait =
      thread.scrollHeight - thread.scrollTop - thread.clientHeight <= MARGE_BAS;
    const position = thread.scrollTop;
    if (state.view !== "code") {
      thread.replaceChildren();
      return;
    }
    if (!state.sessionId) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = state.pendingProjectSlug
        ? "Écrivez votre premier message pour démarrer la conversation."
        : "Écrivez votre premier message — un projet sera créé pour l’accueillir.";
      thread.replaceChildren(hint);
      return;
    }
    if (!state.messages.length) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = "Aucun message — envoie le premier";
      thread.replaceChildren(hint);
      return;
    }
    // Pendant une réponse, un seul message change — le dernier. Reconstruire
    // les autres coûte leur rendu markdown et invalide toute la mise en page,
    // pour un résultat identique au caractère près. On garde donc le nœud d'un
    // message dont l'empreinte n'a pas bougé.
    const anciens = new Map();
    for (const noeud of [...thread.children]) {
      if (noeud.dataset?.empreinte) anciens.set(noeud.dataset.empreinte, noeud);
    }
    const voulus = [];
    for (const m of state.messages) {
      const empreinte = empreinteDuMessage(m);
      const garde = anciens.get(empreinte);
      if (garde) {
        anciens.delete(empreinte);
        voulus.push(garde);
        continue;
      }
      voulus.push(construireMessage(m, empreinte));
    }
    thread.replaceChildren(...voulus);
    // On rend le geste au lieu de le faire : l'appelant l'exécutera à l'image
    // suivante, quand la mise en page sera déjà calculée.
    return () => {
      thread.scrollTop = suivait ? BAS_DU_FIL : position;
    };
  }

  /** De quoi reconnaître un message déjà rendu, sans comparer tout son texte. */
  function empreinteDuMessage(m) {
    const texte = m.text || "";
    const outils = (m.tools || []).map((t) => `${t.name}:${t.status}:${(t.output || "").length}`);
    // Les blocs aussi : une question qui se pose, puis se referme, ne change
    // ni le texte ni sa longueur. Sans cette ligne, le nœud serait réutilisé
    // tel quel et la carte ne bougerait jamais.
    const blocs = (m.blocks || []).map(
      (b) => `${b.type}:${b.etat || b.status || ""}:${b.demande?.request_id || b.id || ""}`
    );
    return [
      m.id || "",
      m.role || "system",
      m.rang ?? "",
      texte.length,
      // La longueur ne suffit pas quand un texte se réécrit à taille égale ;
      // les bords le disent à peu de frais.
      texte.slice(0, 24),
      texte.slice(-24),
      m.streaming ? "1" : "0",
      m.phase || "",
      outils.join("|"),
      blocs.join("|"),
    ].join("");
  }

  function construireMessage(m, empreinte) {
    const div = document.createElement("div");
    div.dataset.empreinte = empreinte;
    const role = m.role || "system";
    div.className = `msg ${role === "user" ? "user" : role === "assistant" ? "assistant" : role === "error" ? "error-msg" : role === "tool" ? "tool" : "system"}`;
    if (m.streaming) div.classList.add("msg-streaming");
    if (role === "user" || role === "assistant") {
      const label = document.createElement("span");
      label.className = "role";
      label.textContent = role;
      div.appendChild(label);
    } else if (role === "error") {
      const label = document.createElement("span");
      label.className = "role";
      label.textContent = "erreur";
      div.appendChild(label);
    }
    appendMessageBody(div, m);
    renderAttente(div, m);
    renderMessageActions(div, m);
    return div;
  }

  function renderComposer() {
    const sessionReady = state.view === "code" && !!state.token;
    const canSend = sessionReady && !state.busy;
    const input = $("composer-input");
    const send = $("btn-send");
    const stop = $("btn-stop");
    const attach = $("btn-composer-attach");
    const attachInput = $("composer-attach-input");
    const hasContent =
      !!input?.value.trim() || (state.composerAttachments?.length > 0);
    if (input) input.disabled = !canSend;
    if (send) {
      send.disabled = !canSend || !hasContent;
      send.hidden = state.busy;
    }
    if (stop) stop.hidden = !state.busy;
    const peutJoindre = sessionReady && !!state.sessionId;
    if (attach) attach.disabled = !peutJoindre;
    if (attachInput) attachInput.disabled = !peutJoindre;

    // Le mode de travail appartient à la conversation : on ne le propose donc
    // qu'une fois qu'elle existe. Il ne vaut que pour les tours à venir, ce que
    // dit l'infobulle — sans quoi on croirait qu'il réécrit le passé.
    const mode = $("composer-mode");
    if (mode) {
      const courante = state.sessions?.find((x) => x.session_id === state.sessionId);
      mode.disabled = !peutJoindre || state.busy;
      mode.hidden = !peutJoindre;
      const valeur = courante?.permission_mode || "";
      if (mode.value !== valeur) mode.value = valeur;
      mode.title = valeur === "plan"
        ? "Plan — l’agent réfléchit et propose, sans rien modifier. S’applique aux tours à venir."
        : "Comment l’agent travaille dans ce fil. S’applique aux tours à venir.";
    }
    composerInput?.syncGrow?.();
    composerInput?.renderAttachments?.();
  }

  /**
   * Barre de conversation — deux etats sur le meme composant :
   * conversation ouverte (projet fige) ou accueil (projet a choisir).
   */
  function renderSessionBar() {
    const bar = $("session-bar");
    if (!bar) return;
    if (state.view !== "code") {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;

    const enConversation = !!state.sessionId;
    const current = enConversation
      ? state.sessions.find((s) => s.session_id === state.sessionId)
      : null;
    const slug = enConversation
      ? state.slug || current?.slug || ""
      : state.pendingProjectSlug || "";
    const project = state.projects.find((p) => p.slug === slug);

    const titleEl = $("session-title-display");
    if (titleEl) {
      titleEl.textContent = enConversation
        ? (current ? S.sessionLabel(current) : "Session")
        : "Nouvelle conversation";
    }

    // Projet : fige en conversation, choisissable sur l'accueil.
    const projectEl = $("session-project-label");
    const selectEl = $("session-project-select");
    if (projectEl) {
      projectEl.hidden = !enConversation;
      projectEl.textContent = project?.title || slug || "—";
    }
    if (selectEl) {
      selectEl.hidden = enConversation;
      if (!enConversation) {
        const avant = selectEl.value;
        selectEl.innerHTML = "";
        const neuf = document.createElement("option");
        neuf.value = "";
        neuf.textContent = "Nouveau projet";
        selectEl.appendChild(neuf);
        for (const p of S.codeProjects(state)) {
          const opt = document.createElement("option");
          opt.value = p.slug;
          opt.textContent = p.title || p.slug;
          selectEl.appendChild(opt);
        }
        const voulu = state.pendingProjectSlug || "";
        selectEl.value = [...selectEl.options].some((o) => o.value === voulu)
          ? voulu
          : avant && [...selectEl.options].some((o) => o.value === avant)
            ? avant
            : "";
      }
    }

    // L'état et le nombre de tours se lisent déjà dans la liste, en face de
    // chaque conversation ; les répéter ici doublait sans rien apprendre.
    const vs = state.meta?.vscode_url;
    const link = $("session-vscode-link");
    if (link) {
      if (vs && enConversation) {
        link.hidden = false;
        link.href = api.vscodeOpenUrl(slug, state.sessionId);
        link.title = project?.path || slug;
      } else {
        link.hidden = true;
        link.removeAttribute("href");
      }
    }
  }

  function renderCodeChat() {
    renderSessionBar();
    renderThread();
    renderComposer();
  }

  return { renderCodeChat, renderThread, renderComposer, renderSessionBar };
}
