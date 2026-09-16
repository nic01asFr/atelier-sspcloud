// Le fil d'un tour se rend dans l'ordre d'arrivée, et les décisions s'y
// lisent avec leur état.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildStreamBlocks,
  fusionnerReflexion,
  texteAssemble,
} from "../mcp_gateway/atelier/web/js/controllers/chat.js";
import { ceQueToujoursAccorde } from "../mcp_gateway/atelier/web/js/ui/message-render.js";

function flux() {
  return { blocs: [], tools: [], decisions: [], phase: "attente" };
}

test("les blocs gardent l'ordre : parole, outil, décision, parole", () => {
  const s = flux();
  s.blocs.push({ type: "text", text: "je regarde" });
  const outil = { type: "tool", id: "t1", name: "Bash", input: { command: "ls" }, output: "", status: "running" };
  s.tools.push(outil);
  s.blocs.push(outil);
  const decision = { type: "decision", demande: { request_id: "r1", tool_use_id: "t1", genre: "autorisation" }, etat: "en_attente" };
  s.decisions.push(decision);
  s.blocs.push(decision);
  s.blocs.push({ type: "text", text: "voilà" });
  const blocs = buildStreamBlocks(s);
  assert.deepEqual(blocs.map((b) => b.type), ["text", "tool", "decision", "text"]);
  assert.equal(blocs[2].argumentsAilleurs, true, "l'outil est rendu juste au-dessus");
});

test("un bloc de texte vide ne se rend pas", () => {
  const s = flux();
  s.blocs.push({ type: "text", text: "   " });
  assert.deepEqual(buildStreamBlocks(s), []);
});

test("une question masque les détails bruts de son outil", () => {
  const s = flux();
  const outil = { type: "tool", id: "q1", name: "AskUserQuestion", input: {}, output: "", status: "done" };
  s.tools.push(outil);
  s.blocs.push(outil);
  s.decisions.push({ type: "decision", demande: { request_id: "r", tool_use_id: "q1", genre: "question" }, etat: "repondu" });
  assert.equal(buildStreamBlocks(s)[0].masquerDetails, true);
});

test("le raisonnement se fusionne sans se doubler", () => {
  assert.equal(fusionnerReflexion("", "abc", "thinking_delta"), "abc");
  assert.equal(fusionnerReflexion("abc", "def", "thinking_delta"), "abcdef");
  assert.equal(fusionnerReflexion("abc", "abc", "thinking"), "abc");
  assert.equal(fusionnerReflexion("ab", "abcd", "thinking"), "abcd", "un texte plus complet remplace");
});

test("le texte assemblé ne prend que la parole", () => {
  const s = flux();
  s.blocs.push({ type: "thinking", text: "hum" });
  s.blocs.push({ type: "text", text: "un" });
  s.blocs.push({ type: "text", text: "deux" });
  assert.equal(texteAssemble(s), "un\n\ndeux");
});

test("« Toujours » nomme toutes les commandes suggérées", () => {
  const d = {
    outil: "Bash",
    suggestions: [
      { type: "addRules", rules: [{ toolName: "Bash", ruleContent: "make" }, { toolName: "Bash", ruleContent: "./deploy.sh" }] },
    ],
  };
  assert.equal(ceQueToujoursAccorde(d), "Ne plus demander pour : make, ./deploy.sh");
  assert.equal(ceQueToujoursAccorde({ outil: "Write", suggestions: [] }), "Ne plus demander pour l’outil Write");
  assert.equal(
    ceQueToujoursAccorde({ outil: "Write", suggestions: [{ type: "addDirectories", directories: ["/a"] }] }),
    "Ne plus demander dans /a"
  );
});
