/** Handoff VS Code : la session de navigation est déjà un cookie, on ouvre. */

import * as api from "../api.js";

export async function openVscode(state, slug, sessionId) {
  window.open(api.vscodeOpenUrl(slug, sessionId), "_blank", "noopener");
}
