/** Client HTTP/SSE Atelier — seul module qui parle au réseau. */

const jsonHeaders = (token) => ({
  Authorization: `Bearer ${token}`,
  "Content-Type": "application/json",
  Accept: "application/json",
});

async function parseError(res) {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body.detail || JSON.stringify(body);
  } catch {
    /* ignore */
  }
  const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  err.status = res.status;
  throw err;
}

export async function createSession(token, { slug, model, title, kind } = {}) {
  const res = await fetch("/v1/sessions", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({
      slug: slug || null,
      model: model || null,
      title: title || null,
      kind: kind || null,
    }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function listSessions(
  token,
  { slug, kind, includeArchived = false, syncTitles = true } = {}
) {
  const params = new URLSearchParams();
  if (slug) params.set("slug", slug);
  if (kind) params.set("kind", kind);
  if (includeArchived) params.set("include_archived", "true");
  if (!syncTitles) params.set("sync_titles", "false");
  const q = params.toString() ? `?${params}` : "";
  const res = await fetch(`/v1/sessions${q}`, { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  const data = await res.json();
  return data.sessions || [];
}

export async function patchSession(token, sessionId, patch) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify(patch),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteSession(token, sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function interruptSession(token, sessionId) {
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/interrupt`,
    { method: "POST", headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function uploadSessionAttachment(token, sessionId, file) {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/attachments`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteSessionAttachment(token, sessionId, attachmentId) {
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE", headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getSession(token, sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getSessionMcp(token, sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/mcp`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getProjectMcp(token, slug) {
  const res = await fetch(`/v1/projects/${encodeURIComponent(slug)}/mcp`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function putProjectMcp(token, slug, servers) {
  const res = await fetch(`/v1/projects/${encodeURIComponent(slug)}/mcp`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify({ servers }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/**
 * Les questions qu'un tour attend, vives ou seulement tracées.
 *
 * Sert au rechargement : une question posée avant qu'on ferme l'onglet doit
 * se retrouver au retour, sinon « elle peut attendre » devient « elle est
 * perdue ».
 */
export async function decisionsEnAttente(token, sessionId = "") {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const res = await fetch(`/v1/decisions${q}`, { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Rend la décision au tour qui l'attend. */
export async function repondreDecision(token, requestId, { decision, motif, portee } = {}) {
  const res = await fetch(`/v1/decisions/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ decision, motif: motif || "", portee: portee || "une_fois" }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function patchSessionMcp(token, sessionId, { overlay } = {}) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/mcp`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify({ overlay: overlay || {} }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getTranscript(token, sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/transcript`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function listProjects(token, { kind } = {}) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  const q = params.toString() ? `?${params}` : "";
  const res = await fetch(`/v1/projects${q}`, { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  const data = await res.json();
  return data.projects || [];
}

export async function createProject(token, { slug, kind, title } = {}) {
  const res = await fetch("/v1/projects", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ slug, kind: kind || null, title: title || null }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function patchProject(token, slug, patch) {
  const res = await fetch(`/v1/projects/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify(patch),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteProject(token, slug) {
  const res = await fetch(`/v1/projects/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export function streamEvents(sessionId, message, { onEvent, attachmentIds = [] } = {}) {
  // Pas de clé dans l'adresse : le cookie de session part de lui-même en
  // même origine, et une URL se journalise partout où elle passe.
  const params = new URLSearchParams({ message: message || "" });
  if (attachmentIds.length) {
    params.set("attachments", attachmentIds.join(","));
  }
  const url =
    `/v1/sessions/${encodeURIComponent(sessionId)}/events?` + params.toString();

  return new Promise((resolve, reject) => {
    const es = new EventSource(url);
    let settled = false;

    const finish = (fn, arg) => {
      if (settled) return;
      settled = true;
      es.close();
      fn(arg);
    };

    const handle = (kind, e) => {
      let data = {};
      try {
        data = JSON.parse(e.data);
      } catch {
        data = { text: e.data };
      }
      const ev = { kind: kind || data.kind || "systeme", ...data };
      onEvent?.(ev);
      if (ev.kind === "fin" || ev.kind === "erreur") {
        finish(resolve, ev);
      }
    };

    for (const kind of [
      "texte",
      "outil_debut",
      "outil_fin",
      "permission_demandee",
      "decision_attendue",
      "decision_rendue",
      "fin",
      "erreur",
      "heartbeat",
      "systeme",
    ]) {
      es.addEventListener(kind, (e) => handle(kind, e));
    }

    es.onmessage = (e) => handle(null, e);
    es.onerror = () => {
      if (!settled) {
        finish(reject, new Error("SSE connection error"));
      }
    };
  });
}

/** @typedef {{ type: string, text?: string, name?: string, id?: string, input?: unknown, output?: string, status?: string }} ContentBlock */

function toolOutputText(block) {
  const content = block?.content;
  // Claude écrit la sortie tantôt en blocs, tantôt d'une seule pièce. Ne
  // reconnaître que la première forme laissait l'outil affiché « terminé »
  // avec une sortie vide.
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((c) => c && c.type === "text" && c.text)
    .map((c) => c.text)
    .join("\n");
}

function findToolBlock(blocks, toolId) {
  if (toolId) {
    const hit = blocks.find((b) => b.type === "tool" && b.id === toolId);
    if (hit) return hit;
  }
  for (let i = blocks.length - 1; i >= 0; i--) {
    if (blocks[i].type === "tool") return blocks[i];
  }
  return null;
}

/**
 * Parse un transcript stream-json Claude Code en messages UI ordonnés.
 * @returns {Array<{ role: string, text?: string, blocks?: ContentBlock[] }>}
 */
export function messagesFromTranscript(transcriptText) {
  const messages = [];
  if (!transcriptText) return messages;

  const blocks = [];
  let textAcc = "";
  let thinkAcc = "";
  // Rang du message dans les prises de parole de l'utilisateur. C'est par lui
  // que l'interface et le serveur désignent le même message quand on demande
  // de reprendre la conversation à cet endroit.
  let rangUser = 0;

  const flushText = () => {
    const t = textAcc.trim();
    if (t) blocks.push({ type: "text", text: t });
    textAcc = "";
  };

  const flushThink = () => {
    const t = thinkAcc.trim();
    if (t) blocks.push({ type: "thinking", text: t });
    thinkAcc = "";
  };

  const pushAssistant = (fallbackText = "") => {
    flushText();
    flushThink();
    const textParts = blocks.filter((b) => b.type === "text").map((b) => b.text);
    const text = textParts.join("\n\n").trim() || (fallbackText || "").trim();
    if (!text && !blocks.length) return;
    messages.push({
      role: "assistant",
      text,
      blocks: [...blocks],
    });
    blocks.length = 0;
    textAcc = "";
    thinkAcc = "";
  };

  for (const line of transcriptText.split("\n")) {
    const raw = line.trim();
    if (!raw) continue;
    let obj;
    try {
      obj = JSON.parse(raw);
    } catch {
      continue;
    }
    const type = obj.type;

    // Ne pas rejouer stream_event : le fichier transcript contient déjà les lignes
    // assistant/result finales ; les deltas doublonnent texte et thinking au reload.
    if (type === "assistant") {
      const content = obj.message?.content;
      if (Array.isArray(content)) {
        for (const block of content) {
          if (!block || typeof block !== "object") continue;
          if (block.type === "thinking" && block.thinking) {
            flushText();
            blocks.push({ type: "thinking", text: block.thinking });
          } else if (block.type === "text" && block.text) {
            flushThink();
            textAcc += block.text;
            flushText();
          } else if (block.type === "tool_use") {
            flushText();
            flushThink();
            blocks.push({
              type: "tool",
              name: block.name || "?",
              id: block.id || "",
              input: block.input,
              output: "",
              status: "done",
            });
          } else if (block.type === "tool_result") {
            const tool = findToolBlock(blocks, block.tool_use_id || "");
            const out = toolOutputText(block);
            if (tool) {
              tool.output = out;
              tool.status = block.is_error ? "denied" : "done";
            }
          }
        }
      }
    } else if (type === "user") {
      // Les retours d'outils voyagent dans les enregistrements user : sans
      // les lire, chaque outil s'affiche « terminé » avec une sortie vide dès
      // qu'on recharge la conversation. Le texte, lui, n'est présent que dans
      // les transcripts repris de Claude Code — l'Atelier passe le sien en
      // argument, il n'apparaît pas dans le flux.
      const content = obj.message?.content;
      const dits = [];
      if (typeof content === "string") {
        if (content.trim()) dits.push(content);
      } else if (Array.isArray(content)) {
        for (const block of content) {
          if (!block || typeof block !== "object") continue;
          if (block.type === "tool_result") {
            const tool = findToolBlock(blocks, block.tool_use_id || "");
            if (tool) {
              tool.output = toolOutputText(block);
              tool.status = block.is_error ? "denied" : "done";
            }
          } else if (block.type === "text" && block.text) {
            dits.push(block.text);
          }
        }
      }
      const dit = dits.join("\n\n").trim();
      if (dit && !obj.isMeta) {
        // Un mot de l'utilisateur clôt la réponse en cours.
        pushAssistant();
        messages.push({ role: "user", text: dit, rang: rangUser });
        rangUser += 1;
      }
    } else if (type === "result") {
      const denials = Array.isArray(obj.permission_denials) ? obj.permission_denials : [];
      for (const d of denials) {
        if (!d || typeof d !== "object") continue;
        const toolId = String(d.tool_use_id || "");
        const tool = findToolBlock(blocks, toolId);
        if (tool) {
          tool.status = "denied";
          if (!tool.name) tool.name = d.tool_name || "?";
          if (!tool.input && d.tool_input) tool.input = d.tool_input;
        } else {
          blocks.push({
            type: "tool",
            name: d.tool_name || "?",
            id: toolId,
            input: d.tool_input,
            output: "",
            status: "denied",
          });
        }
      }
      const subtype = obj.subtype || "";
      if (obj.is_error || subtype === "error_during_execution") {
        flushText();
        flushThink();
        blocks.length = 0;
        const errs = Array.isArray(obj.errors) ? obj.errors : [];
        const cause =
          errs.filter(Boolean).join("; ") ||
          (typeof obj.result === "string" ? obj.result : "") ||
          subtype ||
          "erreur";
        messages.push({ role: "error", text: cause });
      } else {
        const resultText = typeof obj.result === "string" ? obj.result : "";
        const hasText = textAcc.trim() || blocks.some((b) => b.type === "text");
        pushAssistant(hasText ? "" : resultText);
      }
    }
  }

  if (textAcc.trim() || thinkAcc.trim() || blocks.length) {
    pushAssistant();
  }

  return messages;
}

/** Fusionne messages user (sessionStorage) + transcript (assistant). */
export function mergeChatMessages(stored, parsed) {
  // Un transcript qui porte lui-même les messages de l'utilisateur se suffit,
  // et son ordre est le vrai : c'est le cas des conversations reprises de
  // Claude Code. Le sessionStorage reste la source pour les autres, où le
  // flux ne renvoie pas ce qu'on a écrit. On ne lui préfère le transcript que
  // s'il en dit au moins autant, pour ne rien perdre.
  const ditsTranscript = (parsed || []).filter((m) => m.role === "user");
  const ditsStockes = (stored || []).filter((m) => m.role === "user");
  if (ditsTranscript.length && ditsTranscript.length >= ditsStockes.length) {
    return parsed;
  }
  const users = (stored || []).filter((m) => m.role === "user");
  const assistantSide = (parsed || []).filter(
    (m) => m.role === "assistant" || m.role === "error"
  );
  const cachedAssist = (stored || []).filter(
    (m) => m.role === "assistant" || m.role === "error"
  );
  const assistants = assistantSide.length ? assistantSide : cachedAssist;
  if (!assistants.length) return users.length ? users : stored || [];
  if (!users.length) return assistants;
  const out = [];
  const n = Math.max(users.length, assistants.length);
  for (let i = 0; i < n; i++) {
    if (i < users.length) out.push(users[i]);
    if (i < assistants.length) out.push(assistants[i]);
  }
  return out;
}

/** @deprecated Utiliser messagesFromTranscript */
export function assistantMessagesFromTranscript(transcriptText) {
  return messagesFromTranscript(transcriptText)
    .filter((m) => m.role === "assistant" && m.text)
    .map((m) => m.text);
}

export function isThinkingRawType(rawType = "") {
  return rawType === "thinking" || rawType === "thinking_delta";
}

export function mergeAssistantText(buf, chunk, rawType = "") {
  if (!chunk) return buf || "";
  if (isThinkingRawType(rawType)) return buf || "";
  if (!buf) return chunk;
  if (chunk === buf) return buf;
  if (rawType === "text_delta" || rawType === "content_block_delta") {
    if (buf.endsWith(chunk)) return buf;
    return buf + chunk;
  }
  if (rawType === "result_text") return chunk;
  if (chunk.startsWith(buf)) return chunk;
  if (buf.startsWith(chunk)) return buf;
  if (buf.includes(chunk) || chunk.includes(buf)) {
    return buf.length >= chunk.length ? buf : chunk;
  }
  return buf + chunk;
}

export async function getMeta(token) {
  const res = await fetch("/v1/meta", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function listModels(token) {
  const res = await fetch("/v1/models", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function setAuthCookie(token) {
  const res = await fetch("/v1/auth/cookie", {
    method: "POST",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Ferme la session de navigation côté serveur, pas seulement le cookie. */
export async function clearAuthCookie() {
  try {
    await fetch("/v1/auth/cookie", { method: "DELETE" });
  } catch {
    // Se déconnecter ne doit jamais échouer faute de réseau : l'état local
    // est nettoyé de toute façon, et la session expirera d'elle-même.
  }
}

/**
 * Reprend une conversation d'avant son n-ième message, sous une nouvelle
 * identité. L'originale reste intacte.
 */
export async function forkSession(token, sessionId, rang, titre = "") {
  const res = await fetch(`/v1/sessions/${sessionId}/fork`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ rang, titre }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export function vscodeOpenUrl(slug, sessionId) {
  const q = new URLSearchParams();
  if (slug) q.set("slug", slug);
  if (sessionId) q.set("session", sessionId);
  const qs = q.toString();
  return `/v1/vscode/open${qs ? `?${qs}` : ""}`;
}

export async function listMcpServers(token) {
  const res = await fetch("/v1/mcp/servers", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  const data = await res.json();
  return data.servers || {};
}

export async function getMcpOverview(token) {
  const res = await fetch("/v1/mcp/overview", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function reprobeMcpPool(token) {
  const res = await fetch("/v1/mcp/reprobe", {
    method: "POST",
    headers: jsonHeaders(token),
    body: "{}",
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function setMcpEnabled(token, name, enabled) {
  const res = await fetch(`/v1/mcp/servers/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: jsonHeaders(token),
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function importMcpServers(token, mcpServers, { replace = false } = {}) {
  const res = await fetch("/v1/mcp/import", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ mcpServers, replace }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteMcpServer(token, name) {
  const res = await fetch(`/v1/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getMcpProfiles(token) {
  const res = await fetch("/v1/mcp/profiles", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function activateMcpProfile(token, { kind, id }) {
  const res = await fetch("/v1/mcp/profiles/activate", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ kind, id }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function createMcpProfile(token, body) {
  const res = await fetch("/v1/mcp/profiles/custom", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function updateMcpProfile(token, profileId, body) {
  const res = await fetch(
    `/v1/mcp/profiles/custom/${encodeURIComponent(profileId)}`,
    {
      method: "PUT",
      headers: jsonHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteMcpProfile(token, profileId) {
  const res = await fetch(
    `/v1/mcp/profiles/custom/${encodeURIComponent(profileId)}`,
    { method: "DELETE", headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getProfilePiloteBindings(token, kind, profileId) {
  const res = await fetch(
    `/v1/mcp/profiles/${encodeURIComponent(kind)}/${encodeURIComponent(profileId)}/pilote-bindings`,
    { headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getAgentOverview(token) {
  const res = await fetch("/v1/agent/overview", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function setAgentDaemon(token, paused) {
  const res = await fetch("/v1/agent/daemon", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ paused }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function createAgent(token, body) {
  const res = await fetch("/v1/agent", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Compositions enregistrees dans la passerelle de l'Atelier. */
export async function listCompositions(token) {
  const res = await fetch("/v1/compositions", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function getComposition(token, id) {
  const res = await fetch(`/v1/compositions/${encodeURIComponent(id)}`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** action : promote | demote | validate | execute */
export async function actOnComposition(token, id, action, body) {
  const res = await fetch(
    `/v1/compositions/${encodeURIComponent(id)}/${action}`,
    {
      method: "POST",
      headers: jsonHeaders(token),
      body: body ? JSON.stringify(body) : undefined,
    }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteComposition(token, id) {
  const res = await fetch(`/v1/compositions/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Schema d'entree d'un outil, pour proposer ses parametres. */
export async function mcpToolSchema(token, tool) {
  const res = await fetch(
    "/v1/mcp/tools/schema?tool=" + encodeURIComponent(tool),
    { headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Enregistre un enchaînement d'appels, en brouillon. */
export async function createComposition(token, body) {
  const res = await fetch("/v1/compositions", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Reecrit une composition existante. */
export async function updateComposition(token, compId, body) {
  const res = await fetch(`/v1/compositions/${encodeURIComponent(compId)}`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Enregistre une variante d'outil aux parametres figes. */
export async function createToolVariant(token, body) {
  const res = await fetch("/v1/mcp/tool-variants", {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Outils exposes par chaque service du pool. */
export async function mcpTools(token) {
  const res = await fetch("/v1/mcp/tools", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Outils integres reconnus par le harness. */
export async function agentTools(token) {
  const res = await fetch("/v1/agent/tools", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Fil de l'agent : les derniers tours de sa session Claude. */
export async function agentTranscript(token, agentId) {
  const res = await fetch(
    `/v1/agent/${encodeURIComponent(agentId)}/transcript`,
    { headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Relance l'agent sur sa session precedente (pas de message libre). */
export async function continueAgent(token, agentId) {
  const res = await fetch(
    `/v1/agent/${encodeURIComponent(agentId)}/continue`,
    { method: "POST", headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function fireAgent(token, agentId) {
  const res = await fetch(`/v1/agent/${encodeURIComponent(agentId)}/fire`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: "{}",
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function toggleAgent(token, agentId) {
  const res = await fetch(`/v1/agent/${encodeURIComponent(agentId)}/toggle`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: "{}",
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function decideAgentAction(token, agentId, body) {
  const res = await fetch(`/v1/agent/${encodeURIComponent(agentId)}/decide`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function deleteAgent(token, agentId) {
  const res = await fetch(`/v1/agent/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}
