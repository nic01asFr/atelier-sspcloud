// Le transcript du CLI se relit en messages, outils et résultats compris.

import { test } from "node:test";
import assert from "node:assert/strict";

import { messagesFromTranscript } from "../mcp_gateway/atelier/web/js/api.js";

const lignes = [
  { type: "user", message: { role: "user", content: "bonjour" } },
  {
    type: "assistant",
    message: {
      content: [
        { type: "thinking", thinking: "je réfléchis" },
        { type: "text", text: "je lance" },
        { type: "tool_use", id: "t1", name: "Bash", input: { command: "ls" } },
      ],
    },
  },
  {
    type: "user",
    message: { content: [{ type: "tool_result", tool_use_id: "t1", content: "a.txt", is_error: false }] },
  },
  { type: "assistant", message: { content: [{ type: "text", text: "voilà a.txt" }] } },
  { type: "result", subtype: "success", result: "voilà a.txt" },
]
  .map((l) => JSON.stringify(l))
  .join("\n");

test("les outils reçoivent leur sortie et leur état", () => {
  const messages = messagesFromTranscript(lignes);
  const assistant = messages.filter((m) => m.role === "assistant");
  assert.ok(assistant.length >= 1);
  const blocs = assistant.flatMap((m) => m.blocks || []);
  const outil = blocs.find((b) => b.type === "tool");
  assert.ok(outil, "l'appel d'outil est là");
  assert.equal(outil.name, "Bash");
  assert.equal(outil.output, "a.txt");
  assert.equal(outil.status, "done");
  assert.ok(blocs.some((b) => b.type === "thinking" && b.text === "je réfléchis"));
});

test("un résultat en erreur se voit", () => {
  const texte = [
    { type: "assistant", message: { content: [{ type: "tool_use", id: "t2", name: "Bash", input: {} }] } },
    { type: "user", message: { content: [{ type: "tool_result", tool_use_id: "t2", content: "refusé", is_error: true }] } },
    { type: "result", subtype: "success", result: "" },
  ]
    .map((l) => JSON.stringify(l))
    .join("\n");
  const blocs = messagesFromTranscript(texte).flatMap((m) => m.blocks || []);
  assert.equal(blocs.find((b) => b.type === "tool").status, "denied");
});

test("un transcript vide ou illisible ne casse rien", () => {
  assert.deepEqual(messagesFromTranscript(""), []);
  assert.deepEqual(messagesFromTranscript("pas du json\n{"), []);
});
