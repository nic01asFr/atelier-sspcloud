/** Handoff VS Code (cookie + ouverture). */

import * as api from "../api.js";

export async function openVscode(state, slug, sessionId) {
  try {
    await api.setAuthCookie(state.token);
  } catch {
    /* cookie optionnel */
  }
  window.open(api.vscodeOpenUrl(slug, sessionId), "_blank", "noopener");
}
