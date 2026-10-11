// L'agent s'endort en attendant la personne : l'écran le dit, et la question reste répondable.
//
// Une question n'est jamais un refus. Quand personne ne répond à temps, le tour
// ne reçoit rien : il s'arrête. L'écran doit alors montrer trois choses —
// que l'agent attend (et non qu'il a échoué), que la question est toujours là
// avec ses boutons, et qu'elle apparaît même si le tour n'avait jamais été
// regardé (une carte qui n'a jamais été posée).

import { egal, verifier, bilan } from "./verifier.mjs";

import { messagesFromTranscript } from "../../mcp_gateway/atelier/web/js/api.js";
import {
  creerMemoireDuFil,
  recevoirDeLEnvoi,
  recevoirDuDirect,
} from "../../mcp_gateway/atelier/web/js/controllers/chat.js";

const MSG = "L’agent s’est mis en veille";

function scene() {
  const state = { messages: [], busy: false, sessionId: "s1" };
  const ctx = {
    state,
    render: () => {},
    views: { codeChat: { renderThread: () => {} }, fils: { renderFils: () => {} } },
  };
  return { state, ctx };
}

const demande = {
  request_id: "rq1",
  session_id: "s1",
  outil: "Bash",
  arguments: { command: "pip install torch" },
  genre: "autorisation",
};

function veille(extra = {}) {
  return {
    kind: "systeme",
    session_id: "s1",
    cause: "veille",
    tool: "Bash",
    tool_id: "rq1",
    text: JSON.stringify({ ...demande, veille: true }),
    ...extra,
  };
}

// ── 1. La carte déjà posée reste : pas de doublon, et on dit que l'agent dort ─

{
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  state.busy = true;
  state.messages.push({ role: "assistant", text: "", blocks: [], streaming: true });
  const stream = { blocs: [], tools: [], decisions: [], phase: "attente" };
  recevoirDeLEnvoi(ctx, stream, memoire, {
    kind: "decision_attendue", session_id: "s1", tool: "Bash", tool_id: "rq1",
    text: JSON.stringify(demande),
  });
  recevoirDeLEnvoi(ctx, stream, memoire, veille());

  egal(stream.decisions.length, 1, "une seule carte pour la même question");
  egal(stream.decisions[0].etat, "en_attente", "la question reste ouverte, avec ses boutons");
  const dit = stream.blocs.filter((b) => b.type === "systeme" && b.text.includes(MSG));
  egal(dit.length, 1, "l’écran dit que l’agent attend, sans parler d’échec ni de refus");
  verifier(!/refus|échec|erreur/i.test(dit[0].text), "le texte ne laisse pas croire à un refus");
}

// ── 2. Un tour que personne ne regardait : la carte est créée à la veille ───

{
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  state.busy = true;
  state.messages.push({ role: "assistant", text: "", blocks: [], streaming: true });
  const stream = { blocs: [], tools: [], decisions: [], phase: "attente" };
  recevoirDeLEnvoi(ctx, stream, memoire, veille());

  egal(stream.decisions.length, 1, "la question apparaît même sans carte posée avant");
  egal(stream.decisions[0].demande.request_id, "rq1", "c’est bien celle de l’agent");
  egal(stream.decisions[0].etat, "en_attente", "répondable");
}

// ── 3. Suivi d'un tour lancé ailleurs : la veille ouvre et referme la bulle ──

{
  const { state, ctx } = scene();
  const suivi = { flux: null, memoire: creerMemoireDuFil() };
  recevoirDuDirect(ctx, suivi, veille());
  verifier(
    state.messages.some((m) => m.role === "assistant"),
    "une bulle s’ouvre pour montrer la question",
  );
  const clos = recevoirDuDirect(ctx, suivi, {
    kind: "fin", session_id: "s1", cause: "veille", raw_type: "",
  });
  egal(clos, true, "le tour observé se referme sur sa fin");
  egal(
    state.messages.filter((m) => m.role === "assistant" && m.streaming).length,
    0,
    "plus aucune bulle ne reste « en cours »",
  );
}

// ── 4. Relu au rechargement : le message de l'Atelier n'est pas un mot de la personne ─

{
  const ligne = (obj) => JSON.stringify(obj);
  const transcript = [
    ligne({ type: "user", message: { role: "user", content: [{ type: "text", text: "installe torch" }] } }),
    ligne({ type: "assistant", message: { id: "m1", content: [{ type: "text", text: "Je demande." }] } }),
    ligne({
      type: "user",
      isSynthetic: true,
      message: { role: "user", content: [{ type: "text", text: "[Atelier] Tu attendais l’accord de la personne pour : Bash — ls. Elle l’a accordé." }] },
    }),
    ligne({ type: "assistant", message: { id: "m2", content: [{ type: "text", text: "Fait." }] } }),
  ].join("\n");
  const messages = messagesFromTranscript(transcript);
  egal(messages.filter((m) => m.role === "user").length, 1, "un seul message vient de la personne");
  const reponse = messages.filter((m) => m.role === "assistant").flatMap((m) => m.blocks || []);
  verifier(
    reponse.some((b) => b.type === "systeme" && b.text.startsWith("Tu attendais")),
    "la reprise se lit comme une note de l’Atelier, sans sa marque",
  );
}

bilan("veille");
