// Ce que l'écran dit doit être vrai, et dit une seule fois de la même façon.
//
// Relevé le 17 septembre 2026 dans l'Atelier : la pastille annonçait « au
// repos » quand la ligne juste en dessous lisait « idle » ; l'arbre parlait de
// « sessions » là où tout le reste dit « conversations » ; et douze projets
// rangés — avec cinq conversations — avaient disparu de l'écran sans aucun
// moyen de les revoir.

import { test } from "node:test";
import assert from "node:assert/strict";

import * as S from "../mcp_gateway/atelier/web/js/state.js";

test("les états se lisent en français, comme la pastille", () => {
  assert.equal(S.etatLisible("idle"), "au repos");
  assert.equal(S.etatLisible("running"), "en réponse");
  assert.equal(S.etatLisible("failed"), "en erreur");
  assert.equal(S.etatLisible("archived"), "rangée");
  assert.equal(S.etatLisible("created"), "jamais lancée");
  assert.equal(S.etatLisible("done"), "au repos");
});

test("un état inconnu se montre tel quel plutôt que de disparaître", () => {
  assert.equal(S.etatLisible("zigzag"), "zigzag");
  assert.equal(S.etatLisible(""), "");
});

test("la ligne sous le titre dit l'état et le nombre de tours", () => {
  assert.equal(S.sessionMetaLine({ state: "idle", turns: 6 }), "au repos · 6 tours");
  assert.equal(S.sessionMetaLine({ state: "running", turns: 1 }), "en réponse · 1 tour");
  assert.ok(!S.sessionMetaLine({ state: "idle", turns: 2 }).includes("idle"));
});

test("une conversation qui attend une autorisation le dit avant tout", () => {
  const ligne = S.sessionMetaLine({ state: "running", turns: 3, attend_une_decision: true });
  assert.equal(ligne, "autorisation demandée · 3 tours");
});

function etat(sessions) {
  return { sessions, projects: [], meta: { assistant_slug: "wikichat-memory" }, montrerArchives: false };
}

test("ce qui est rangé se cache, et se montre quand on le demande", () => {
  const e = etat([
    { session_id: "a", slug: "p", kind: "code", state: "idle" },
    { session_id: "b", slug: "p", kind: "code", state: "archived" },
  ]);
  assert.deepEqual(S.codeSessions(e).map((s) => s.session_id), ["a"]);
  S.setMontrerArchives(e, true);
  assert.deepEqual(S.codeSessions(e).map((s) => s.session_id), ["a", "b"]);
  S.setMontrerArchives(e, false);
  assert.deepEqual(S.codeSessions(e).map((s) => s.session_id), ["a"]);
});

test("un projet créé sans nom ne porte pas le nom du bouton qui le crée", async () => {
  const { readFileSync } = await import("node:fs");
  const lus = ["js/controllers/projects.js", "js/controllers/chat.js", "js/views/code-chat.js"].map(
    (f) => readFileSync(new URL("../mcp_gateway/atelier/web/" + f, import.meta.url), "utf8")
  );
  for (const source of lus) {
    assert.ok(!/"Nouveau projet"/.test(source), "« Nouveau projet » ne désigne plus qu'une action");
  }
});

test("les états de composition et d'exécution se lisent en français", async () => {
  const c = await import("../mcp_gateway/atelier/web/js/views/connectors.js");
  assert.equal(c.statutLisible("production"), "active");
  assert.equal(c.statutLisible("temporary"), "brouillon");
  assert.equal(c.statutLisible("failed", c.ETATS_EXECUTION), "échouée");
  assert.equal(c.statutLisible("completed", c.ETATS_EXECUTION), "terminée");
  assert.equal(c.statutLisible("inédit"), "inédit", "un état inconnu reste visible");
});
