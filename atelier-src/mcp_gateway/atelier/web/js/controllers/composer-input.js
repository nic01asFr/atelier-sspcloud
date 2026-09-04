/** Composer — auto-grow textarea, pièces jointes, arrêt génération. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { bindAutoGrowTextarea, syncAutoGrowTextarea } from "../ui/auto-grow-textarea.js";

const MAX_TEXTAREA_PX = 160;
const MAX_ATTACHMENTS = 8;

function formatSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * @param {object} ctx
 */
export function createComposerInputController(ctx) {
  const { state, render } = ctx;
  let grow = null;

  function syncGrow() {
    syncAutoGrowTextarea($("composer-input"));
  }

  function resetGrow() {
    grow?.reset();
  }

  function clearAttachments() {
    state.composerAttachments = [];
    renderAttachments();
  }

  function renderAttachments() {
    const strip = $("composer-attachments");
    if (!strip) return;
    const files = state.composerAttachments || [];
    strip.innerHTML = "";
    if (!files.length) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    for (const f of files) {
      const chip = document.createElement("span");
      chip.className = "composer-attach-chip";
      const label = document.createElement("span");
      label.className = "composer-attach-chip-label";
      label.textContent = `${f.name} (${formatSize(f.size)})`;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "composer-attach-chip-remove";
      rm.setAttribute("aria-label", `Retirer ${f.name}`);
      rm.textContent = "×";
      rm.addEventListener("click", async () => {
        if (state.token && state.sessionId && f.id) {
          try {
            await api.deleteSessionAttachment(state.token, state.sessionId, f.id);
          } catch {
            /* ignore stale */
          }
        }
        state.composerAttachments = state.composerAttachments.filter((x) => x !== f);
        renderAttachments();
        syncGrow();
      });
      chip.append(label, rm);
      strip.appendChild(chip);
    }
  }

  async function onStop() {
    if (!state.token || !state.sessionId || !state.busy) return;
    try {
      await api.interruptSession(state.token, state.sessionId);
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    }
  }

  function onAttachClick(e) {
    e.preventDefault();
    const input = $("composer-attach-input");
    if (input && !input.disabled) input.click();
  }

  async function onAttachFiles(e) {
    const input = e.target;
    const files = input?.files;
    if (!files?.length || !state.token || !state.sessionId) return;
    const pending = state.composerAttachments || [];
    if (pending.length >= MAX_ATTACHMENTS) {
      S.setError(state, `Maximum ${MAX_ATTACHMENTS} fichiers par message.`);
      render();
      input.value = "";
      return;
    }
    S.setError(state, "");
    for (const file of files) {
      if (pending.length >= MAX_ATTACHMENTS) break;
      try {
        const meta = await api.uploadSessionAttachment(
          state.token,
          state.sessionId,
          file
        );
        state.composerAttachments.push(meta);
      } catch (err) {
        S.setError(state, err.message || String(err));
        break;
      }
    }
    input.value = "";
    renderAttachments();
    syncGrow();
    render();
  }

  function bind() {
    const input = $("composer-input");
    grow = bindAutoGrowTextarea(input, { maxHeight: MAX_TEXTAREA_PX });

    $("btn-stop")?.addEventListener("click", onStop);
    $("btn-composer-attach")?.addEventListener("click", onAttachClick);
    $("composer-attach-input")?.addEventListener("change", onAttachFiles);
    $("composer-mode")?.addEventListener("change", onModeChange);
  }

  /** Le mode de travail se pose sur la conversation, pas sur le message. */
  async function onModeChange(ev) {
    const mode = ev.target.value;
    if (!state.sessionId) return;
    try {
      const rec = await api.patchSession(state.token, state.sessionId, {
        permission_mode: mode,
      });
      // La liste porte l'état des conversations : sans cette mise à jour, le
      // sélecteur reviendrait à sa valeur d'avant au prochain rendu.
      const i = (state.sessions || []).findIndex((x) => x.session_id === rec.session_id);
      if (i >= 0) state.sessions[i] = rec;
      render();
    } catch (err) {
      S.setError(state, `Mode non appliqué : ${err.message}`);
      render();
    }
  }

  return {
    bind,
    syncGrow,
    resetGrow,
    renderAttachments,
    clearAttachments,
  };
}
