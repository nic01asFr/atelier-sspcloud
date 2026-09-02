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
  const { state, render, composerInput } = ctx;

  // Marge sous laquelle on considère que le lecteur est « en bas ». Assez
  // large pour absorber une ligne qui s'ajoute, assez étroite pour ne pas
  // rattraper quelqu'un qui a délibérément remonté.
  const MARGE_BAS = 80;

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

    if (role === "user" && texte) {
      const renvoyer = document.createElement("button");
      renvoyer.type = "button";
      renvoyer.className = "msg-action";
      renvoyer.textContent = "Renvoyer";
      renvoyer.title = "Reposer cette question dans un nouveau tour";
      renvoyer.disabled = !!state.busy;
      renvoyer.addEventListener("click", () => {
        const champ = $("composer-input");
        if (!champ) return;
        champ.value = texte;
        champ.dispatchEvent(new Event("input", { bubbles: true }));
        champ.focus();
      });
      barre.appendChild(renvoyer);
    }

    div.appendChild(barre);
  }

  // Ce que la bulle dit tant qu'elle n'a rien à montrer. Uniquement des états
  // que les événements attestent : on n'invente pas d'étapes.
  const ATTENTE = {
    attente: "En attente du modèle…",
    reflexion: "Réflexion…",
    outil: "Utilisation d’un outil…",
  };

  function renderAttente(div, m) {
    if (!m.streaming) return;
    if ((m.text || "").trim() || (m.blocks || []).length) return;
    const p = document.createElement("p");
    p.className = "msg-attente";
    p.textContent = ATTENTE[m.phase] || ATTENTE.attente;
    div.appendChild(p);
  }

  function renderThread() {
    const thread = $("thread");
    if (!thread) return;
    // Le fil est reconstruit à chaque rendu, et une réponse en cours en
    // déclenche des centaines. Recoller systématiquement en bas rendait toute
    // relecture impossible : on ne suit donc que si l'on suivait déjà.
    const suivait =
      thread.scrollHeight - thread.scrollTop - thread.clientHeight <= MARGE_BAS;
    const position = thread.scrollTop;
    thread.innerHTML = "";
    if (state.view !== "code") return;
    if (!state.sessionId) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = state.pendingProjectSlug
        ? "Écrivez votre premier message pour démarrer la conversation."
        : "Écrivez votre premier message — un projet sera créé pour l’accueillir.";
      thread.appendChild(hint);
      return;
    }
    if (!state.messages.length) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = "Aucun message — envoie le premier";
      thread.appendChild(hint);
      return;
    }
    for (const m of state.messages) {
      const div = document.createElement("div");
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
      thread.appendChild(div);
    }
    thread.scrollTop = suivait ? thread.scrollHeight : position;
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

    const metaEl = $("session-meta-display");
    if (metaEl) metaEl.textContent = current ? S.sessionMetaLine(current) : "";

    const vs = state.meta?.vscode_url;
    const link = $("session-vscode-link");
    const copyBtn = $("btn-copy-session");
    if (copyBtn) copyBtn.hidden = !enConversation;
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
    const hint = $("session-resume-hint");
    if (hint) {
      if (!enConversation) hint.textContent = "";
      else hint.textContent = vs ? `Workspace ${slug}` : `Pod : projects/${slug}`;
    }
  }

  function renderCodeChat() {
    renderSessionBar();
    renderThread();
    renderComposer();
  }

  return { renderCodeChat, renderThread, renderComposer, renderSessionBar };
}
