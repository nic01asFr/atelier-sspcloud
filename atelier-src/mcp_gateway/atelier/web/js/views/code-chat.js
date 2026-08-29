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

  function renderThread() {
    const thread = $("thread");
    if (!thread) return;
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
      thread.appendChild(div);
    }
    thread.scrollTop = thread.scrollHeight;
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
