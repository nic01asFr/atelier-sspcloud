// La file de messages et la bulle en cours, telles que l'écran les tient.

import { test } from "node:test";
import assert from "node:assert/strict";

import * as S from "../mcp_gateway/atelier/web/js/state.js";

function etat() {
  return { messages: [], enFile: [] };
}

test("un message en file part dans l'ordre, par son texte", () => {
  const s = etat();
  S.ajouterEnFile(s, { id: "a", texte: "un" });
  S.ajouterEnFile(s, { id: "b", texte: "deux" });
  S.ajouterEnFile(s, { id: "c", texte: "un" });
  assert.equal(S.retirerDeLaFile(s, "un").id, "a", "le premier qui correspond");
  assert.deepEqual(s.enFile.map((m) => m.id), ["b", "c"]);
  assert.equal(S.retirerDeLaFile(s, "absent"), null);
  S.retirerDeLaFileParId(s, "c");
  assert.deepEqual(s.enFile.map((m) => m.id), ["b"]);
});

test("la mise à jour vise la bulle en cours, pas la dernière", () => {
  const s = etat();
  S.appendMessage(s, { role: "assistant", text: "", blocks: [], streaming: true });
  S.appendMessage(s, { role: "user", text: "en file" });
  S.updateLastAssistant(s, { text: "réponse", blocks: [{ type: "text", text: "réponse" }], phase: "reponse" });
  assert.equal(s.messages[0].text, "réponse");
  assert.equal(s.messages[0].phase, "reponse");
  assert.equal(s.messages[1].text, "en file", "le message utilisateur n'a pas bougé");
});

test("clore la bulle la fige", () => {
  const s = etat();
  S.appendMessage(s, { role: "assistant", text: "a", streaming: true });
  S.finalizeAssistant(s);
  assert.equal(s.messages[0].streaming, false);
  S.updateLastAssistant(s, "b");
  assert.equal(s.messages[0].text, "a", "plus rien n'y entre");
});
