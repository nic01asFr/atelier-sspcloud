/** Overlay MCP conversation — fetch + toggle composer +. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";

/**
 * @param {object} ctx
 */
export function createComposerMcpController(ctx) {
  const { state, render, composerMcp, navigateView } = ctx;

  async function refreshSessionMcp() {
    if (!state.token || !state.sessionId) {
      state.sessionMcp = null;
      return;
    }
    try {
      state.sessionMcp = await api.getSessionMcp(state.token, state.sessionId);
    } catch (err) {
      if (err.status === 401) return;
      state.sessionMcp = null;
    }
  }

  async function toggleConnector(id, active) {
    if (!state.token || !state.sessionId || state.mcpOverlayBusy) return;
    S.setMcpOverlayBusy(state, true);
    composerMcp.renderComposerMcp();
    try {
      state.sessionMcp = await api.patchSessionMcp(state.token, state.sessionId, {
        overlay: { [id]: active },
      });
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
    } finally {
      S.setMcpOverlayBusy(state, false);
      composerMcp.renderComposerMcp();
    }
  }

  function onMcpButtonClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if ($("btn-composer-mcp")?.disabled) return;
    if (composerMcp.isOpen()) {
      composerMcp.close();
    } else {
      composerMcp.setOpen(true);
      refreshSessionMcp().then(() => composerMcp.renderComposerMcp());
    }
  }

  function onManage() {
    composerMcp.close();
    navigateView("connecteurs");
  }

  function bind() {
    $("btn-composer-mcp")?.addEventListener("click", onMcpButtonClick);
    document.addEventListener("click", (e) => {
      if (!composerMcp.isOpen()) return;
      const wrap = document.querySelector(".composer-input-wrap");
      if (wrap && !wrap.contains(e.target)) {
        composerMcp.close();
        composerMcp.renderComposerMcp();
      }
    });
  }

  return { refreshSessionMcp, toggleConnector, onManage, bind };
}
