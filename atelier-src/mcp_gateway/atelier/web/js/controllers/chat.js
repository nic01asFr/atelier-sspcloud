/** Chat SSE — envoi message Claude Code. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { refreshProjects, refreshSessions } from "../services/catalog.js";

function tryParseJson(s) {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

function findStreamTool(stream, toolId) {
  if (toolId) {
    const hit = stream.tools.find((t) => t.id === toolId);
    if (hit) return hit;
  }
  return stream.tools[stream.tools.length - 1];
}

function buildStreamBlocks(stream) {
  const blocks = [];
  if (stream.thinking.trim()) {
    blocks.push({ type: "thinking", text: stream.thinking.trim() });
  }
  for (const t of stream.tools) {
    blocks.push({
      type: "tool",
      name: t.name,
      id: t.id,
      input: t.input,
      output: t.output || "",
      status: t.status || "done",
    });
  }
  if (stream.text.trim()) {
    blocks.push({ type: "text", text: stream.text.trim() });
  }
  return blocks;
}

function pushStreamToUi(state, stream) {
  S.updateLastAssistant(state, {
    text: stream.text.trim(),
    blocks: buildStreamBlocks(stream),
    phase: stream.phase,
  });
}

/**
 * @param {object} ctx
 */
export function createChatController(ctx) {
  const { state, render, views, composerInput, writeQuery } = ctx;

  /**
   * Creation implicite : la conversation — et au besoin le projet qui
   * l'accueille — nait du premier message. Rien n'est ecrit sur le pod
   * tant que l'utilisateur n'a rien envoye.
   */
  async function assurerConversation(texte) {
    let slug = state.pendingProjectSlug || "";
    if (!slug) {
      const titre = S.projectNameFromMessage(texte) || "Nouveau projet";
      const base = S.slugifyProjectName(titre) || "projet";
      slug = S.uniqueProjectSlug(state, base);
      await api.createProject(state.token, { slug, kind: "code", title: titre });
      await refreshProjects(state);
    }
    const rec = await api.createSession(state.token, { slug, kind: "code" });
    S.setSlug(state, slug);
    S.ensureExpanded(state, slug);
    S.setSessionId(state, rec.session_id);
    S.setMessages(state, []);
    S.setPendingProjectSlug(state, null);
    await refreshSessions(state);
    try {
      S.setSessionMcp(state, await api.getSessionMcp(state.token, rec.session_id));
    } catch {
      S.setSessionMcp(state, null);
    }
    writeQuery?.();
  }

  async function onSend(ev) {
    ev.preventDefault();
    const text = $("composer-input")?.value.trim() || "";
    const attachments = state.composerAttachments || [];
    if ((!text && !attachments.length) || state.busy || state.view !== "code") {
      return;
    }

    S.setBusy(state, true);
    S.setError(state, "");

    if (!state.sessionId) {
      try {
        await assurerConversation(text);
      } catch (err) {
        S.setBusy(state, false);
        S.setError(state, err.message || String(err));
        render();
        return;
      }
    }
    S.appendMessage(state, {
      role: "user",
      text: text || "Fichiers joints",
      attachments: attachments.map((a) => ({ ...a })),
    });
    S.appendMessage(state, {
      role: "assistant",
      text: "",
      blocks: [],
      streaming: true,
    });
    $("composer-input").value = "";
    composerInput?.resetGrow?.();
    composerInput?.clearAttachments?.();
    render();

    const attachmentIds = attachments.map((a) => a.id).filter(Boolean);

    const stream = {
      thinking: "",
      text: "",
      tools: [],
      // Le modèle met plusieurs secondes avant son premier mot — mesuré à
      // près de huit sur la passerelle du pod. Pendant ce temps la bulle
      // était muette, et rien ne distinguait « il réfléchit » de « c'est
      // bloqué ». On dit donc où l'on en est, d'après ce que les événements
      // disent réellement.
      phase: "attente",
    };

    try {
      await api.streamEvents(state.sessionId, text, {
        token: state.token,
        attachmentIds,
        onEvent: (ev) => {
          if (ev.kind === "texte" && ev.text) {
            stream.phase = api.isThinkingRawType(ev.raw_type) ? "reflexion" : "reponse";
            if (api.isThinkingRawType(ev.raw_type)) {
              stream.thinking = api.mergeAssistantText(
                stream.thinking,
                ev.text,
                ev.raw_type
              );
            } else {
              stream.text = api.mergeAssistantText(
                stream.text,
                ev.text,
                ev.raw_type || ""
              );
            }
            pushStreamToUi(state, stream);
            views.codeChat.renderThread();
          } else if (ev.kind === "outil_debut") {
            stream.phase = "outil";
            const toolId = ev.tool_id || ev.cause || "";
            if (ev.raw_type === "input_json_delta") {
              const tool = findStreamTool(stream, toolId);
              if (tool) {
                tool.inputPartial = (tool.inputPartial || "") + (ev.text || "");
                try {
                  tool.input = JSON.parse(tool.inputPartial);
                } catch {
                  /* partial */
                }
              }
            } else {
              let input = ev.text ? tryParseJson(ev.text) : undefined;
              const existing = stream.tools.find((t) => t.id === toolId);
              if (existing) {
                existing.name = ev.tool || existing.name;
                if (input && typeof input === "object") existing.input = input;
                if (!existing.status) existing.status = "running";
              } else {
                stream.tools.push({
                  id: toolId,
                  name: ev.tool || "?",
                  input,
                  output: "",
                  status: "running",
                  inputPartial: "",
                });
              }
            }
            pushStreamToUi(state, stream);
            views.codeChat.renderThread();
          } else if (ev.kind === "outil_fin") {
            if (ev.raw_type === "tool_result" || ev.text) {
              const toolId = ev.tool_id || ev.tool || ev.cause || "";
              const tool = findStreamTool(stream, toolId);
              if (tool) {
                if (ev.text) tool.output = ev.text;
                if (
                  ev.raw_type === "permission_denials" ||
                  /permission|haven't granted|refusé|refuse/i.test(ev.text || "")
                ) {
                  tool.status = "denied";
                } else {
                  tool.status = "done";
                }
              }
              pushStreamToUi(state, stream);
              views.codeChat.renderThread();
            }
          } else if (ev.kind === "permission_demandee" && ev.text) {
            const denials = tryParseJson(ev.text);
            if (Array.isArray(denials)) {
              for (const d of denials) {
                if (!d || typeof d !== "object") continue;
                const toolId = d.tool_use_id || "";
                const existing = stream.tools.find((t) => t.id === toolId);
                if (existing) {
                  existing.status = "denied";
                  if (d.tool_name) existing.name = d.tool_name;
                  if (d.tool_input) existing.input = d.tool_input;
                } else {
                  stream.tools.push({
                    id: toolId,
                    name: d.tool_name || "?",
                    input: d.tool_input,
                    output: "",
                    status: "denied",
                    inputPartial: "",
                  });
                }
              }
              pushStreamToUi(state, stream);
              views.codeChat.renderThread();
            }
          } else if (ev.kind === "erreur") {
            S.appendMessage(state, {
              role: "error",
              text: ev.cause || "erreur",
            });
            S.setError(state, ev.cause || "erreur");
            render();
          }
        },
      });
      S.finalizeAssistant(state);
      if (!stream.text.trim() && !stream.tools.length && !stream.thinking.trim()) {
        const last = state.messages[state.messages.length - 1];
        if (last?.role === "assistant" && !last.text) {
          state.messages = state.messages.slice(0, -1);
        }
      }
      S.persistUserTurns(state);
      await refreshSessions(state);
    } catch (err) {
      S.setError(state, err.message || String(err));
      S.finalizeAssistant(state);
    } finally {
      S.setBusy(state, false);
      render();
    }
  }

  return { onSend };
}
