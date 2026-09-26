/** Client HTTP/SSE Atelier — seul module qui parle au réseau. */

// L'interface ne porte plus la clé : elle parle à l'API par le cookie de
// session (`HttpOnly`, joint de lui-même en même origine) et par cet en-tête,
// qu'une page d'une autre origine ne peut pas poser. Le paramètre `token` des
// fonctions ci-dessous n'est plus qu'un reste de signature : il n'est pas lu.
export const ENTETE_INTERFACE = { "X-Atelier-Interface": "1" };

const jsonHeaders = (_token) => ({
  ...ENTETE_INTERFACE,
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

/** Le défaut de mode d'un projet (`.claude/settings.local.json`). */
export async function getProjectMode(token, slug) {
  const res = await fetch(`/v1/projets/${encodeURIComponent(slug)}/mode`, { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function setProjectMode(token, slug, mode) {
  const res = await fetch(`/v1/projets/${encodeURIComponent(slug)}/mode`, {
    method: "PUT",
    headers: jsonHeaders(token),
    body: JSON.stringify({ mode }),
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
      headers: { ...ENTETE_INTERFACE },
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
export async function repondreDecision(token, requestId, { decision, motif, portee, reponses } = {}) {
  const res = await fetch(`/v1/decisions/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({
      decision,
      motif: motif || "",
      portee: portee || "une_fois",
      reponses: reponses || null,
    }),
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

export async function listProjects(token, { kind, includeArchived = false } = {}) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (includeArchived) params.set("include_archived", "true");
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

/**
 * Regarde un tour sans le déclencher.
 *
 * L'adresse de `streamEvents` porte le message : s'y brancher relancerait le
 * tour. Celle-ci ne fait qu'écouter — un second onglet, un écran resté
 * ouvert, une conversation reprise ailleurs.
 *
 * Rend une fonction qui referme le canal.
 */
/** Dépose un message qui partira quand le tour en cours aura fini. */
export async function mettreEnFile(token, sessionId, message) {
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    { method: "POST", headers: jsonHeaders(token), body: JSON.stringify({ message }) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Ce qui attend son tour dans cette conversation. */
export async function fileDesMessages(token, sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/file`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Retire un message avant son départ. */
export async function annulerMessageEnFile(token, sessionId, messageId) {
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/file/${encodeURIComponent(messageId)}`,
    { method: "DELETE", headers: jsonHeaders(token) }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

export function suivreSession(sessionId, { onEvent } = {}) {
  const es = new EventSource(
    `/v1/sessions/${encodeURIComponent(sessionId)}/live`
  );
  const handle = (kind, e) => {
    let data = {};
    try {
      data = JSON.parse(e.data);
    } catch {
      data = { text: e.data };
    }
    onEvent?.({ kind: kind || data.kind || "systeme", ...data });
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
  return () => es.close();
}

export function streamEvents(sessionId, message, { onEvent, attachmentIds = [], envoi = "" } = {}) {
  // Pas de clé dans l'adresse : le cookie de session part de lui-même en
  // même origine, et une URL se journalise partout où elle passe.
  const params = new URLSearchParams({ message: message || "" });
  // Identifiant de cet envoi : une reconnexion d'EventSource reprend la même
  // adresse, et le serveur refuse de rejouer un envoi déjà reçu.
  // L'appelant le fournit pour reconnaître son tour quand il revient aussi
  // par le flux en direct.
  params.set("envoi", envoi || globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
  if (attachmentIds.length) {
    params.set("attachments", attachmentIds.join(","));
  }
  const url =
    `/v1/sessions/${encodeURIComponent(sessionId)}/events?` + params.toString();

  return new Promise((resolve, reject) => {
    const es = new EventSource(url);
    let settled = false;
    let enchaine = false;

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
      // Un tour peut traiter plusieurs messages : celui qu'on a envoyé, puis
      // ceux écrits pendant qu'il travaillait. Chacun finit par un `fin`, mais
      // le flux, lui, continue. Le serveur annonce l'enchaînement juste avant
      // — on garde donc la ligne ouverte jusqu'au dernier.
      if (ev.kind === "systeme" && ev.cause === "message_suivant") {
        enchaine = true;
        return;
      }
      if (ev.kind === "fin" && enchaine) {
        enchaine = false;
        return;
      }
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

/**
 * Ce que l'en-tête d'un outil doit dire, d'après ce que le CLI a rendu.
 *
 * Le drapeau `is_error` du résultat décide, et lui seul : un résultat normal
 * est « terminé », quoi qu'il contienne. On cherchait le mot « permission »
 * dans le texte de la sortie ; la page https://example.com, lue par
 * `take_snapshot`, en contient un, et l'outil s'affichait « permission
 * refusée » alors qu'il avait rendu la page (essais du 26/09). Le texte ne
 * sert plus qu'à distinguer, parmi les résultats en erreur, un refus (message
 * du CLI ou de l'Atelier) d'un échec de l'outil.
 *
 * @param {boolean|undefined} enErreur `is_error` du résultat
 * @param {string} texte sortie de l'outil
 * @returns {"done"|"denied"|"error"}
 */
export function statutDuResultat(enErreur, texte) {
  if (enErreur !== true) return "done";
  return /haven't granted|permission|refusé|refuse|denied/i.test(String(texte || ""))
    ? "denied"
    : "error";
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
/** Le `systemMessage` d'un hook, sous les formes que le CLI lui donne (voir `events.py`). */
export function messageSysteme(obj) {
  if (!obj || typeof obj !== "object") return "";
  if (typeof obj.systemMessage === "string" && obj.systemMessage.trim()) return obj.systemMessage.trim();
  const sousType = obj.subtype || "";
  if (!["informational", "hook_response", "hook_system_message", "stop_hook_summary"].includes(sousType)) return "";
  for (const cle of ["output", "stdout"]) {
    const brut = obj[cle];
    if (typeof brut === "string" && brut.trim().startsWith("{")) {
      try {
        const sortie = JSON.parse(brut);
        if (typeof sortie?.systemMessage === "string") return sortie.systemMessage.trim();
      } catch {
        /* pas du JSON : rien à dire */
      }
    }
  }
  const messages = obj.hookSystemMessages || obj.systemMessages;
  if (Array.isArray(messages)) {
    const dits = messages.filter((m) => typeof m === "string" && m.trim()).map((m) => m.trim());
    if (dits.length) return dits.join(String.fromCharCode(10));
  }
  if (sousType === "informational" && typeof (obj.content || obj.message) === "string") {
    return String(obj.content || obj.message).trim();
  }
  return "";
}

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
  // L'heure de la dernière ligne lue : celle d'une réponse est l'heure de sa
  // dernière ligne, pour le pied du message (« 14:05 · Copier · Relancer »).
  let derniereHeure = "";
  // Ce qui a déjà été lu, par identifiant. Une conversation s'écrit dans deux
  // registres fondus par le service ; si une même ligne y figure sous deux
  // formes, elle garde son `message.id`, et un appel d'outil son `id`. On ne
  // compare pas les textes d'un message à l'autre : deux paroles identiques
  // de deux messages restent deux paroles.
  const lignesVues = new Set();
  const blocsVus = new Set();
  const outilsVus = new Set();
  const dejaLu = (messageId, block) => {
    if (block.type === "tool_use" && block.id) {
      if (outilsVus.has(block.id)) return true;
      outilsVus.add(block.id);
      return false;
    }
    if (!messageId || (block.type !== "thinking" && block.type !== "text")) return false;
    const cle = [messageId, block.type, block.thinking || block.text || ""].join("|");
    if (blocsVus.has(cle)) return true;
    blocsVus.add(cle);
    return false;
  };

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
      ...(derniereHeure ? { horodatage: derniereHeure } : {}),
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
    if (obj.uuid) {
      if (lignesVues.has(obj.uuid)) continue;
      lignesVues.add(obj.uuid);
    }
    if (typeof obj.timestamp === "string" && obj.timestamp) derniereHeure = obj.timestamp;

    // Ne pas rejouer stream_event : le fichier transcript contient déjà les lignes
    // assistant/result finales ; les deltas doublonnent texte et thinking au reload.
    if (type === "assistant") {
      const content = obj.message?.content;
      if (Array.isArray(content)) {
        const messageId = obj.message?.id || "";
        for (const block of content) {
          if (!block || typeof block !== "object") continue;
          if (dejaLu(messageId, block)) continue;
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
              tool.status = statutDuResultat(block.is_error, tool.output);
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
              tool.status = statutDuResultat(block.is_error, tool.output);
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
        messages.push({
          role: "user",
          text: dit,
          rang: rangUser,
          ...(derniereHeure ? { horodatage: derniereHeure } : {}),
        });
        rangUser += 1;
      }
    } else if (type === "system") {
      // Ce qu'un hook a dit à la personne (relance de wikichat) : relu au
      // rechargement comme il s'est affiché en direct.
      const dit = messageSysteme(obj);
      if (dit) {
        flushText();
        flushThink();
        blocks.push({ type: "systeme", text: dit });
      }
    } else if (type === "result") {
      const denials = Array.isArray(obj.permission_denials) ? obj.permission_denials : [];
      for (const d of denials) {
        if (!d || typeof d !== "object") continue;
        const toolId = String(d.tool_use_id || "");
        const tool = findToolBlock(blocks, toolId);
        if (tool) {
          // Un résultat normal déjà lu dit que l'outil s'est exécuté.
          if (!(tool.status === "done" && tool.output)) tool.status = "denied";
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
    // Un fragment n'est jamais une répétition : « 33 » arrive en « 3 » puis « 3 ».
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

/**
 * Les réglages d'affichage du fil, retenus par le service (`ui.json`).
 *
 * @param {{ raisonnement?: boolean, actions?: boolean }} reglages
 */
export async function enregistrerReglagesFil(reglages) {
  const corps = {};
  if (typeof reglages?.raisonnement === "boolean") corps.fil_raisonnement = reglages.raisonnement;
  if (typeof reglages?.actions === "boolean") corps.fil_actions = reglages.actions;
  const res = await fetch("/v1/meta", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(corps),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Le thème de l'interface, retenu par le service : `systeme`, `clair`, `sombre`. */
export async function enregistrerTheme(theme) {
  const res = await fetch("/v1/meta", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ theme }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function listModels(token) {
  const res = await fetch("/v1/models", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

/**
 * Échange la clé propriétaire contre une session de navigation.
 *
 * C'est le seul appel qui porte la clé, et la seule fois où l'interface la
 * tient : l'appelant ne la garde nulle part ensuite. Tout le reste passe par
 * le cookie que cette réponse pose.
 */
export async function ouvrirSession(cle) {
  const res = await fetch("/v1/auth/cookie", {
    method: "POST",
    credentials: "same-origin",
    headers: { Authorization: `Bearer ${cle}`, Accept: "application/json" },
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/**
 * Migration : une version précédente gardait la clé dans `localStorage`.
 * On l'échange contre le cookie, puis on l'efface — qu'elle vaille encore ou
 * non. Rend vrai si une session a été ouverte ainsi.
 */
export async function migrerAncienneCle(lire, oublier) {
  const cle = lire();
  if (!cle) return false;
  try {
    await ouvrirSession(cle);
    return true;
  } catch {
    return false;
  } finally {
    oublier();
  }
}

/** Ferme la session de navigation côté serveur, pas seulement le cookie. */
export async function clearAuthCookie() {
  try {
    await fetch("/v1/auth/cookie", { method: "DELETE", headers: { ...ENTETE_INTERFACE } });
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

// L'état du navigateur, tel que le pod le voit : lanceur prêt ou non, Chrome
// ouverts et plafond (voir `navigateur_routes.py`). Il n'y a plus de bureau :
// Chrome tourne sans écran dans le processus de chaque agent. Mis en cache
// quelques secondes, parce que la fiche du connecteur se redessine souvent.
let chromeEtatCache = null;
let chromeEtatDate = 0;
let chromeEtatEnCours = null;

export async function chromeHealth({ maxAgeMs = 30000 } = {}) {
  if (chromeEtatCache && Date.now() - chromeEtatDate < maxAgeMs) return chromeEtatCache;
  if (chromeEtatEnCours) return chromeEtatEnCours;
  chromeEtatEnCours = (async () => {
    try {
      const res = await fetch("/chrome/health", { headers: { ...ENTETE_INTERFACE, Accept: "application/json" } });
      chromeEtatCache = res.ok ? (await res.json()) || {} : { pret: false };
    } catch {
      chromeEtatCache = { pret: false };
    }
    chromeEtatDate = Date.now();
    chromeEtatEnCours = null;
    return chromeEtatCache;
  })();
  return chromeEtatEnCours;
}

/** Dernier état connu, sans appel réseau (null tant qu'on n'a rien demandé). */
export function chromeHealthConnu() {
  return chromeEtatCache;
}

// Les livrables qu'un agent a déposés dans le dossier `artifacts/` du projet,
// servis derrière la porte de l'Atelier, en bac à sable. La barre finale : un
// dossier sans elle est redirigé, pour que ses liens relatifs se résolvent.
export function artifactsUrl(slug) {
  return `/v1/artifacts/${encodeURIComponent(slug)}/`;
}

// Les applications d'un projet (docs/atelier-applications.md). L'ouverture
// passe par un lien (`fiche.ouvrir`), pas par ce module : c'est une
// navigation, que l'Atelier renvoie vers l'hôte des applications.
function cheminApp(slug, nom) {
  return `/v1/apps/${encodeURIComponent(slug)}/${encodeURIComponent(nom)}`;
}

export async function listApps(slug) {
  const res = await fetch(`/v1/apps?slug=${encodeURIComponent(slug)}`, { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function startApp(slug, nom) {
  const res = await fetch(`${cheminApp(slug, nom)}/demarrer`, { method: "POST", headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function stopApp(slug, nom) {
  const res = await fetch(`${cheminApp(slug, nom)}/arreter`, { method: "POST", headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Le journal, en texte : l'appelant le pose en `textContent`, jamais en HTML. */
export async function appJournal(slug, nom, lignes = 200) {
  const res = await fetch(`${cheminApp(slug, nom)}/journal?lignes=${lignes}`, {
    headers: { ...ENTETE_INTERFACE, Accept: "text/plain" },
  });
  if (!res.ok) await parseError(res);
  return res.text();
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

/** Les clients distants enregistres auprès de cet Atelier. */
export async function listerClientsDistants(token) {
  const res = await fetch("/v1/oauth/clients", { headers: jsonHeaders(token) });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Debranche un client distant : son accord, ses jetons et lui-meme. */
export async function revoquerClientDistant(token, clientId) {
  const res = await fetch(`/v1/oauth/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
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

// ── Le panneau à droite du fil, et les échanges wikichat ─────────────────

/** Les onglets du panneau d'une conversation : épinglés au projet, puis à elle. */
export async function panneauVues(sessionId) {
  const res = await fetch(`/v1/panneau/${encodeURIComponent(sessionId)}`, { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Garde une vue avec la conversation (`epingle: "conversation"`) ou le projet. */
export async function panneauEnregistrer(sessionId, vue) {
  const res = await fetch(`/v1/panneau/${encodeURIComponent(sessionId)}/vues`, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(vue),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function panneauRetirer(sessionId, vueId) {
  const res = await fetch(
    `/v1/panneau/${encodeURIComponent(sessionId)}/vues/${encodeURIComponent(vueId)}`,
    { method: "DELETE", headers: jsonHeaders() }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Les échanges wikichat de la conversation (fils ouverts, par défaut). */
export async function filsDeLaConversation(sessionId, statut = "ouvert") {
  const res = await fetch(
    `/v1/sessions/${encodeURIComponent(sessionId)}/fils?statut=${encodeURIComponent(statut)}`,
    { headers: jsonHeaders() }
  );
  if (!res.ok) await parseError(res);
  return res.json();
}

// ── Ce qui agit seul, « À valider » et le journal (vague 2, vue Agents) ───

/** Un agent par gardien : contrôles, alertes, constats, échéance, gestes. */
export async function getGardiens() {
  const res = await fetch("/v1/gardiens", { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Toutes les tâches automatiques : gardiens, triggers, routines, créations. */
export async function getAutomates() {
  const res = await fetch("/v1/automates", { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/**
 * Lancer, couper, réactiver ou activer (`id` : `gardien.<nom>`,
 * `controle.<id>` ou `trigger.<id>`). Le service tranche qui en a le droit.
 */
export async function agirSurAutomate(id, geste) {
  const res = await fetch("/v1/automates/action", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ id, geste }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** La file « À valider » : `{statut, action, resultat: {propositions, nombre, note?}}`. */
export async function listerAValider({ statut = "en_attente" } = {}) {
  const q = new URLSearchParams({ statut });
  const res = await fetch(`/v1/a-valider?${q}`, { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Accepter ou refuser une proposition ; `complete` : les réponses qu'elle attend. */
export async function deciderAValider(id, decision, { motif = "", complete = null } = {}) {
  const corps = { decision, motif };
  if (complete && Object.keys(complete).length) corps.complete = complete;
  const res = await fetch(`/v1/a-valider/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(corps),
  });
  // Un refus du catalogue (403, 422) porte sa raison dans `resultat.erreur`.
  let reponse = null;
  try {
    reponse = await res.clone().json();
  } catch {
    reponse = null;
  }
  if (!reponse || !reponse.statut) {
    if (!res.ok) await parseError(res);
    return reponse;
  }
  if (reponse.statut !== "fait") {
    const err = new Error(reponse?.resultat?.erreur || "La décision n'a pas abouti.");
    err.status = res.status;
    throw err;
  }
  return reponse;
}

/** Le journal unique, le plus récent d'abord. */
export async function lireJournal({ source = "", acteur = "", limite = 300 } = {}) {
  const q = new URLSearchParams({ limite: String(limite) });
  if (source) q.set("source", source);
  if (acteur) q.set("acteur", acteur);
  const res = await fetch(`/v1/journal?${q}`, { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/**
 * Une commande du catalogue, appelée par la personne (`POST /v1/commandes/<nom>`).
 *
 * Les réservées (activer un agent, accorder un secret) ne passent que par
 * ici : la session de l'interface vaut « la personne ». Un refus ou un échec
 * lève une erreur qui porte la raison du service.
 */
export async function executerCommande(nom, args = {}) {
  const res = await fetch(`/v1/commandes/${encodeURIComponent(nom)}`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ arguments: args }),
  });
  let corps = null;
  try {
    corps = await res.clone().json();
  } catch {
    corps = null;
  }
  if (res.status === 404) {
    const err = new Error(`Cette action n’est pas encore disponible ici (${nom}).`);
    err.status = 404;
    throw err;
  }
  if (!corps || !corps.statut) {
    if (!res.ok) await parseError(res);
    return corps;
  }
  if (corps.statut !== "fait") {
    const raison = corps?.resultat?.erreur || corps?.resultat?.detail || corps.statut;
    const err = new Error(typeof raison === "string" ? raison : JSON.stringify(raison));
    err.status = res.status;
    throw err;
  }
  return corps;
}

/** Les noms des secrets qu'on peut accorder, jamais leurs valeurs. */
export async function listerNomsDesSecrets() {
  const res = await fetch("/v1/secrets/noms", { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

// ── Lancements et processus vivants (équipe L, branche v2-lancements) ─────

/**
 * Les processus vivants d'une conversation et ce que vaut un changement de
 * mode : `{mode_choisi, processus, vscode_vivant, note?, ecart?}`. Rend null
 * si le service ne sert pas encore cette route.
 */
export async function processusDeLaConversation(sessionId) {
  const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/processus`, {
    headers: jsonHeaders(),
  });
  if (res.status === 404) return null;
  if (!res.ok) await parseError(res);
  return res.json();
}

/** Les agents lancés par l'Atelier (wikichat, gardiens) : `{lancements, nombre}`. */
export async function listerLancements({ etat = "", origine = "", projet = "", limite = 30 } = {}) {
  const q = new URLSearchParams({ limite: String(limite) });
  if (etat) q.set("etat", etat);
  if (origine) q.set("origine", origine);
  if (projet) q.set("projet", projet);
  const res = await fetch(`/v1/lancements?${q}`, { headers: jsonHeaders() });
  if (res.status === 404) return { lancements: [], nombre: 0, absent: true };
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function arreterLancement(id) {
  const res = await fetch(`/v1/lancements/${encodeURIComponent(id)}/arreter`, {
    method: "POST",
    headers: jsonHeaders(),
    body: "{}",
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

// ── L'Assistant (vague 3, équipe A) ──────────────────────────────────────────

/**
 * Le « Oui » de la personne sur l'aperçu d'une commande engageante
 * (`POST /v1/commandes/confirmer`). Lève une erreur qui porte la raison si
 * le service ne l'a pas fait.
 */
export async function confirmerCommande(jeton) {
  const res = await fetch("/v1/commandes/confirmer", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ jeton }),
  });
  let corps = null;
  try {
    corps = await res.clone().json();
  } catch {
    corps = null;
  }
  if (!corps || corps.statut !== "fait") {
    if (!corps) await parseError(res);
    const raison = corps?.resultat?.erreur || corps?.detail || corps?.statut || res.statusText;
    const err = new Error(typeof raison === "string" ? raison : JSON.stringify(raison));
    err.status = res.status;
    throw err;
  }
  return corps;
}

/** L'état du dossier de l'Assistant : réglage d'accueil, taille de son contexte. */
export async function lireAssistant() {
  const res = await fetch("/v1/assistant", { headers: jsonHeaders() });
  if (!res.ok) await parseError(res);
  return res.json();
}

/** « Ouvrir l'Atelier sur l'Assistant » : un choix de la personne, depuis l'interface. */
export async function reglerAccueilAssistant(actif) {
  const res = await fetch("/v1/assistant/reglages", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ accueil_assistant: !!actif }),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}
