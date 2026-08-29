/** Routage URL — query params view / slug / session. */

import * as S from "../state.js";

export function readQuery() {
  const q = new URLSearchParams(location.search);
  return {
    view: S.normalizeView(q.get("view")),
    session: q.get("session"),
    slug: q.get("slug"),
  };
}

export function writeQuery(state) {
  const q = new URLSearchParams();
  if (state.view && state.view !== "code") q.set("view", state.view);
  if (state.view === "code") {
    if (state.slug) q.set("slug", state.slug);
    if (state.sessionId) q.set("session", state.sessionId);
  }
  const qs = q.toString();
  history.replaceState(null, "", qs ? `/?${qs}` : "/");
}
