/** Chat SSE — envoi message Claude Code. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import {
  buildMessagesFromServer,
  refreshProjects,
  refreshSessions,
} from "../services/catalog.js";

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

/** Le dernier bloc du fil, s'il est bien du type voulu — pour y coller la suite. */
export function blocCourant(stream, type) {
  const dernier = stream.blocs[stream.blocs.length - 1];
  return dernier && dernier.type === type ? dernier : null;
}

/**
 * Assemble les fragments de raisonnement.
 *
 * `mergeAssistantText` les refuse — c'est un garde-fou qui protège le texte
 * de la réponse d'y voir tomber du raisonnement. Seulement l'appelant s'en
 * servait aussi pour le tampon de réflexion, qui restait donc vide : le
 * raisonnement n'apparaissait jamais en direct, et ne se lisait qu'après
 * rechargement, relu du transcript.
 */
export function fusionnerReflexion(buf, chunk, rawType) {
  if (!chunk) return buf || "";
  if (!buf) return chunk;
  if (chunk === buf) return buf;
  if (rawType === "thinking_delta") return buf + chunk;
  if (chunk.startsWith(buf)) return chunk;
  return buf + chunk;
}

/**
 * Verse dans un bloc ce qui arrive du tour : fragments en direct, puis le bloc
 * complet que le CLI renvoie quand il l'a fini.
 *
 * Un fragment s'ajoute toujours. On jetait celui qui répétait la fin du
 * tampon, pour se garder d'un doublon qui n'arrive pas : « 33 tests » devenait
 * « 3 tests ». Le bloc complet, qui ne ressemblait plus au tampon, s'ajoutait
 * alors derrière lui au lieu de le remplacer, et chaque parole de l'agent se
 * lisait deux fois, la première fausse.
 *
 * Le bloc complet fait foi sur ce que ses fragments ont dit, et seulement
 * là-dessus : ce qui précédait dans le bloc reste.
 */
export function verserTexte(cible, texte, rawType = "") {
  const fragment =
    rawType === "content_block_delta" ||
    rawType === "text_delta" ||
    rawType === "thinking_delta";
  if (fragment) {
    if (cible.debutDirect === undefined) cible.debutDirect = cible.text.length;
    cible.text += texte;
    return cible;
  }
  if (cible.debutDirect !== undefined) {
    cible.text = cible.text.slice(0, cible.debutDirect) + texte;
    delete cible.debutDirect;
    return cible;
  }
  cible.text = api.isThinkingRawType(rawType)
    ? fusionnerReflexion(cible.text, texte, rawType)
    : api.mergeAssistantText(cible.text, texte, rawType);
  return cible;
}

/** Ce que l'agent a dit, tous segments confondus — pour la copie et le repli. */
export function texteAssemble(stream) {
  return stream.blocs
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join(String.fromCharCode(10, 10))
    .trim();
}

/**
 * Un événement du flux en direct peut-il ouvrir une bulle de réponse ?
 *
 * La fin d'un tour arrive deux fois : par le flux de celui qui l'a lancé, et
 * par le flux en direct, qu'écoute aussi cet onglet. Ce dernier peut arriver
 * après que l'onglet a rendu la main : son « texte de résultat » ouvrait alors
 * une seconde bulle, et la réponse s'affichait en double (lot H). Seul un
 * début de tour ouvre une bulle : une parole, un outil, une question, un
 * message d'un hook. Une fin, un résultat, une décision rendue, jamais.
 */
export function ouvreUnTour(ev) {
  if (!ev) return false;
  if (ev.kind === "texte") return !!ev.text && ev.raw_type !== "result_text";
  if (ev.kind === "systeme") return ev.cause === "message_systeme";
  return ev.kind === "outil_debut" || ev.kind === "decision_attendue";
}

/**
 * Ce que cet onglet a déjà rendu, reconnu à ses identifiants.
 *
 * Un tour lancé d'ici arrive par deux flux : celui de l'envoi, et le flux en
 * direct que l'onglet écoute aussi. Le lot H écartait le second pendant
 * quatre secondes après la fin du tour, et seulement s'il commençait par une
 * fin. Rien ne borne pourtant le retard d'un flux sur l'autre : une copie en
 * direct arrivée après ce délai ouvrait une bulle, et tout le tour —
 * raisonnement, outil refusé, réponse — s'affichait deux fois (essai du
 * 26/09, Lecteur Grist). On ne compte plus le temps, on ne compare pas les
 * textes : on reconnaît l'envoi (`envoi`), le message du modèle
 * (`message_id`) et la ligne du CLI (`uuid`).
 */
export function creerMemoireDuFil() {
  return { envois: new Set(), messages: new Set(), lignes: new Set() };
}

/** Retient ce qu'apporte un événement rendu par le flux de l'envoi. */
export function retenirEvenement(memoire, ev) {
  if (!memoire || !ev) return;
  if (ev.envoi) memoire.envois.add(ev.envoi);
  if (ev.message_id) memoire.messages.add(ev.message_id);
  if (ev.uuid) memoire.lignes.add(ev.uuid);
}

/** Cet événement du flux en direct a-t-il déjà été rendu par l'envoi ? */
export function dejaRendu(memoire, ev) {
  if (!memoire || !ev) return false;
  return (
    (!!ev.envoi && memoire.envois.has(ev.envoi)) ||
    (!!ev.message_id && memoire.messages.has(ev.message_id)) ||
    (!!ev.uuid && memoire.lignes.has(ev.uuid))
  );
}

/**
 * Rend le tour dans son ordre, et non par catégories.
 *
 * Les blocs étaient assemblés par nature : tout le raisonnement, puis tous
 * les outils, puis toutes les demandes, puis tout le texte. Or un tour ne se
 * déroule pas ainsi — il dit, il agit, il redit. Les regrouper mettait les
 * appels d'outils en haut et la parole en bas, si bien qu'on ne pouvait plus
 * suivre : ce qui motivait un outil se lisait après lui, et une question
 * d'autorisation se retrouvait loin du geste qui l'avait provoquée.
 *
 * On garde donc l'ordre d'arrivée. `stream.blocs` est le fil, `stream.tools`
 * et `stream.decisions` n'en sont que des index — ils pointent sur les mêmes
 * objets, si bien qu'une mise à jour se voit des deux côtés.
 */
export function buildStreamBlocks(stream) {
  const outilsAQuestion = new Set(
    (stream.decisions || [])
      .filter((d) => d.demande?.genre === "question")
      .map((d) => d.demande?.tool_use_id)
  );
  const blocks = [];
  for (const b of stream.blocs) {
    if (b.type === "systeme") {
      if (b.text) blocks.push({ type: "systeme", text: b.text });
      continue;
    }
    if (b.type === "thinking" || b.type === "text") {
      if (b.text && b.text.trim()) blocks.push({ type: b.type, text: b.text.trim() });
      continue;
    }
    if (b.type === "tool") {
      blocks.push({
        type: "tool",
        // La carte de question montre déjà les options et la réponse en
        // clair ; répéter la charge brute et le résultat n'apprend rien.
        masquerDetails: outilsAQuestion.has(b.id),
        name: b.name,
        id: b.id,
        input: b.input,
        output: b.output || "",
        status: b.status || "done",
      });
      continue;
    }
    if (b.type === "decision") {
      blocks.push({
        type: "decision",
        demande: b.demande,
        etat: b.etat,
        resume: b.resume,
        // L'outil concerné est rendu juste au-dessus, paramètres compris.
        argumentsAilleurs: stream.tools.some(
          (o) => o.id && o.id === b.demande?.tool_use_id
        ),
      });
    }
  }
  return blocks;
}

/**
 * Va rechercher la suite d'un tour dont le flux s'est coupé.
 *
 * Rend vrai si l'on a pu relire la conversation. On attend d'abord que le
 * tour s'achève côté serveur : relire trop tôt ne montrerait qu'un fil
 * tronqué, et donnerait l'impression que le reste s'est perdu.
 */
/** Relit la conversation telle que le service la voit maintenant.
 *
 * Sans attendre la fin d'un tour, contrairement au rattrapage : ici rien ne
 * tourne de notre côté, c'est l'autre fenêtre qui a écrit.
 */
async function relireLeJournal(state, render) {
  const sessionId = state.sessionId;
  if (!sessionId) return false;
  try {
    const messages = await buildMessagesFromServer(state, sessionId);
    if (state.sessionId !== sessionId) return false;
    state.messages = messages;
    render();
    return true;
  } catch {
    return false;
  }
}

async function rattraperLeFil(state, render) {
  const sessionId = state.sessionId;
  if (!sessionId) return false;
  try {
    for (let essai = 0; essai < 120; essai += 1) {
      const fiche = await api.getSession(state.token, sessionId);
      if (fiche?.state !== "running") break;
      await new Promise((r) => setTimeout(r, 2000));
    }
    if (state.sessionId !== sessionId) return false;
    state.messages = await buildMessagesFromServer(state, sessionId);
    render();
    return true;
  } catch {
    return false;
  }
}

function pushStreamToUi(state, stream) {
  S.updateLastAssistant(state, {
    text: texteAssemble(stream),
    blocks: buildStreamBlocks(stream),
    phase: stream.phase,
  });
}

/**
 * Applique un événement du tour à l'écran.
 *
 * Sorti de la fermeture d'envoi pour servir deux fois : à celui qui a
 * lancé le tour, et à celui qui le regarde depuis un autre onglet. Les
 * deux reçoivent les mêmes événements et doivent en tirer le même fil.
 */
function appliquerEvenement(ctx, stream, ev) {
  const { state, render, views } = ctx;
    if (ev.kind === "texte" && ev.text) {
      const reflexion = api.isThinkingRawType(ev.raw_type);
      stream.phase = reflexion ? "reflexion" : "reponse";
      // Le texte complet arrive une seconde fois à la fin du tour. Il
      // servait à repartir de zéro sur un tampon unique ; avec des
      // segments il écraserait le dernier et doublerait les précédents.
      // On ne le prend donc que si rien n'est venu en direct.
      const dejaDit = stream.blocs.some(
        (b) => b.type === "text" && b.text.trim()
      );
      if (ev.raw_type === "result_text" && dejaDit) return;
      const type = reflexion ? "thinking" : "text";
      let cible = blocCourant(stream, type);
      if (!cible) {
        cible = { type, text: "" };
        stream.blocs.push(cible);
      }
      verserTexte(cible, ev.text, ev.raw_type || "");
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
          const bloc = {
            type: "tool",
            id: toolId,
            name: ev.tool || "?",
            input,
            output: "",
            status: "running",
            inputPartial: "",
          };
          stream.tools.push(bloc);
          stream.blocs.push(bloc);
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
          // Une question voyage dans le message d'un refus, et le CLI la
          // compte donc parmi ses refus. L'afficher ainsi contredirait la
          // carte juste en dessous, qui dit « Répondu ».
          const etaitUneQuestion = (stream.decisions || []).some(
            (q) => q.demande?.genre === "question" && q.demande?.tool_use_id === toolId
          );
          const existing = stream.tools.find((t) => t.id === toolId);
          if (existing) {
            existing.status = etaitUneQuestion ? "done" : "denied";
            if (d.tool_name) existing.name = d.tool_name;
            if (d.tool_input) existing.input = d.tool_input;
          } else {
            const bloc = {
              type: "tool",
              id: toolId,
              name: d.tool_name || "?",
              input: d.tool_input,
              output: "",
              status: "denied",
              inputPartial: "",
            };
            stream.tools.push(bloc);
            stream.blocs.push(bloc);
          }
        }
        pushStreamToUi(state, stream);
        views.codeChat.renderThread();
      }
    } else if (ev.kind === "decision_attendue" && ev.text) {
      // Le tour est suspendu : il attend qu'on réponde, aussi longtemps
      // qu'il le faudra. On montre la question là où l'œil est déjà.
      const demande = tryParseJson(ev.text);
      if (demande && typeof demande === "object") {
        const bloc = { type: "decision", demande, etat: "en_attente" };
        stream.decisions.push(bloc);
        stream.blocs.push(bloc);
        stream.phase = "decision";
        pushStreamToUi(state, stream);
        views.codeChat.renderThread();
        // La liste latérale doit dire « autorisation demandée » : c'est
        // elle qu'on regarde depuis un autre fil.
        refreshSessions(state).then(render);
      }
    } else if (ev.kind === "decision_rendue") {
      refreshSessions(state).then(render);
      const posee = stream.decisions.find(
        (d) => d.demande?.request_id === ev.tool_id
      );
      if (posee) {
        // « relachee » n'est pas un refus : le tour a rendu sa mémoire
        // faute de réponse, mais la question reste posée et répondable.
        // L'afficher comme refusée mentirait sur ce qui s'est passé.
        // Une question n'est ni accordée ni refusée : elle est
        // répondue. Le libellé du refus n'est qu'un véhicule, et
        // l'afficher comme tel mentirait sur ce qui s'est passé.
        const question = posee.demande?.genre === "question";
        posee.etat = question
          ? // Une question relâchée n'a pas été répondue : le tour est
            // reparti sans cet avis, et rien ne la rattrapera.
            ev.cause === "relachee"
            ? "orpheline"
            : "repondu"
          : ev.cause === "allow" || ev.cause?.startsWith("regle:")
            ? "allow"
            : ev.cause === "relachee"
              ? "orpheline"
              : "deny";
        if (question && ev.text) posee.resume = ev.text;
        stream.phase = "reponse";
        pushStreamToUi(state, stream);
        views.codeChat.renderThread();
      }
    } else if (ev.kind === "systeme" && ev.cause === "message_systeme" && ev.text) {
      // Ce qu'un hook dit à la personne : une relance de wikichat, le plus
      // souvent (« tour prolongé — réponse attendue par… »). Dit à sa place
      // dans le tour, sans se mêler à la parole de l'agent.
      stream.blocs.push({ type: "systeme", text: ev.text });
      pushStreamToUi(state, stream);
      views.codeChat.renderThread();
      views.fils?.renderFils({ relire: true });
    } else if (ev.kind === "systeme" && ev.cause === "message_suivant") {
    // Le tour enchaîne sur un message qui attendait. C'est un autre échange :
    // on referme la réponse en cours et on rouvre une bulle, sans quoi les
    // deux réponses se mêleraient dans la même.
    S.finalizeAssistant(state);
    S.retirerDeLaFile(state, ev.text || "");
    S.appendMessage(state, { role: "user", text: ev.text || "" });
    S.appendMessage(state, { role: "assistant", text: "", blocks: [], streaming: true });
    stream.blocs.length = 0;
    stream.tools.length = 0;
    stream.decisions.length = 0;
    stream.phase = "attente";
    render();
  } else if (ev.kind === "erreur") {
      S.appendMessage(state, {
        role: "error",
        text: ev.cause || "erreur",
      });
      S.setError(state, ev.cause || "erreur");
      render();
    }
}

/** Un événement du flux de l'envoi : retenu, puis rendu. */
export function recevoirDeLEnvoi(ctx, stream, memoire, ev) {
  retenirEvenement(memoire, ev);
  appliquerEvenement(ctx, stream, ev);
}

/**
 * Un événement du flux en direct, pour un tour que cet onglet n'a pas lancé.
 *
 * `suivi` : `{ flux, memoire }`, où `flux` est le tour observé en cours (ou
 * null) et `memoire` ce que le flux de l'envoi a déjà rendu. Rend vrai quand
 * l'événement a clos un tour observé.
 */
export function recevoirDuDirect(ctx, suivi, ev) {
  const { state } = ctx;
  // Déjà rendu par le flux de l'envoi : c'est le même tour, vu une seconde
  // fois. Ni bulle, ni ajout à la bulle en cours.
  if (dejaRendu(suivi.memoire, ev)) return false;
  if (!suivi.flux) {
    // Une fin sans début : rien à ouvrir.
    if (!ouvreUnTour(ev)) return false;
    suivi.flux = { blocs: [], tools: [], decisions: [], phase: "attente" };
    S.appendMessage(state, {
      role: "assistant",
      text: "",
      blocks: [],
      streaming: true,
    });
  }
  appliquerEvenement(ctx, suivi.flux, ev);
  if (ev.kind === "fin" || ev.kind === "erreur") {
    suivi.flux = null;
    S.finalizeAssistant(state);
    return true;
  }
  return false;
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
      const titre = S.projectNameFromMessage(texte) || "Projet sans nom";
      const base = S.slugifyProjectName(titre) || "projet";
      slug = S.uniqueProjectSlug(state, base);
      await api.createProject(state.token, { slug, kind: "code", title: titre });
      await refreshProjects(state);
    }
    const rec = await api.createSession(state.token, { slug, kind: "code" });
    // Le mode choisi avant le premier message vaut dès ce premier tour.
    if (state.modeEnAttente) {
      try {
        await api.patchSession(state.token, rec.session_id, { permission_mode: state.modeEnAttente });
      } catch (err) {
        S.setError(state, `Mode non appliqué : ${err.message}`);
      }
      state.modeEnAttente = "";
    }
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
    if ((!text && !attachments.length) || state.view !== "code") {
      return;
    }

    // Un tour travaille déjà : le message ne se perd pas et n'en lance pas un
    // second. Il attend, et partira dans le tour en cours dès qu'il aura fini
    // le précédent. Le tour peut avoir été lancé ailleurs — un autre onglet,
    // ou cet onglet avant rechargement : on le suit alors sans être occupé,
    // et lancer un flux par-dessus figeait l'écran jusqu'au rechargement.
    if (state.busy || tourEnCoursAilleurs()) {
      if (!state.sessionId || !text) return;
      $("composer-input").value = "";
      composerInput?.resetGrow?.();
      try {
        const rendu = await api.mettreEnFile(state.token, state.sessionId, text);
        const depose = (rendu?.events || []).find((e) => e.cause === "message_en_file");
        S.ajouterEnFile(state, { id: depose?.tool_id || "", texte: text });
      } catch (err) {
        S.setError(state, err.message || String(err));
      }
      render();
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
      // Le fil du tour, dans son ordre d'arrivée. `tools` et `decisions` n'en
      // sont que des index : ils pointent sur les mêmes objets, si bien
      // qu'une mise à jour se voit des deux côtés.
      blocs: [],
      tools: [],
      decisions: [],
      // Le modèle met plusieurs secondes avant son premier mot — mesuré à
      // près de huit sur la passerelle du pod. Pendant ce temps la bulle
      // était muette, et rien ne distinguait « il réfléchit » de « c'est
      // bloqué ». On dit donc où l'on en est, d'après ce que les événements
      // disent réellement.
      phase: "attente",
    };

    // L'identifiant de cet envoi, retenu avant le premier octet : le flux en
    // direct porte le même, et peut devancer celui-ci.
    const envoi =
      globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    memoire.envois.add(envoi);

    try {
      await api.streamEvents(state.sessionId, text, {
        attachmentIds,
        envoi,
        onEvent: (ev) => {
          // Dès le premier signe de vie, la liste latérale doit passer
          // « en réponse » : elle restait « jamais lancée » tout le tour.
          if (!stream.listeRafraichie) {
            stream.listeRafraichie = true;
            refreshSessions(state).then(render);
          }
          recevoirDeLEnvoi({ state, render, views }, stream, memoire, ev);
        },
      });
      S.finalizeAssistant(state);
      if (!stream.blocs.length) {
        const last = state.messages[state.messages.length - 1];
        if (last?.role === "assistant" && !last.text) {
          state.messages = state.messages.slice(0, -1);
        }
      }
      S.persistUserTurns(state);
      await refreshSessions(state);
    } catch (err) {
      // Le lien peut tomber alors que le tour, lui, continue sur le pod. On
      // ne peut pas le rouvrir : l'adresse du flux porte le message, et s'y
      // rebrancher relancerait le tour. Mais on peut faire ce que
      // l'utilisateur faisait à la main — attendre la fin, puis relire la
      // conversation. Sans cela l'écran restait figé jusqu'au rechargement.
      S.finalizeAssistant(state);
      const repris = await rattraperLeFil(state, render);
      if (!repris) S.setError(state, err.message || String(err));
    } finally {
      // La fin du tour arrive aussi par le flux en direct, parfois après
      // celui-ci : `memoire` la fait reconnaître (voir `dejaRendu`).
      S.setBusy(state, false);
      render();
      views.fils?.renderFils({ relire: true });
    }
  }

  // Ce qui écoute la conversation ouverte, quand quelqu'un d'autre la fait
  // tourner. Un seul canal à la fois : on referme en changeant de fil.
  let fermerLObservation = null;
  let sessionObservee = null;
  // Le tour observé en cours, et ce que les envois d'ici ont déjà rendu.
  // La mémoire survit aux changements de fil : un envoi reste le nôtre.
  const memoire = creerMemoireDuFil();
  let suivi = { flux: null, memoire };

  function tourEnCoursAilleurs() {
    if (suivi.flux) return true;
    const fiche = (state.sessions || []).find((s) => s.session_id === state.sessionId);
    return fiche?.state === "running";
  }

  function cesserDObserver() {
    if (fermerLObservation) fermerLObservation();
    fermerLObservation = null;
    sessionObservee = null;
    suivi = { flux: null, memoire };
  }

  /**
   * Suit un tour lancé ailleurs — un autre onglet, VS Code, un agent.
   *
   * Le fil se remplissait uniquement chez celui qui avait envoyé le message,
   * puisque le flux est attaché à cette requête. Ailleurs, l'écran restait
   * muet jusqu'au rechargement.
   */
  function observer(sessionId) {
    if (sessionObservee === sessionId) return;
    cesserDObserver();
    if (!sessionId) return;
    sessionObservee = sessionId;

    fermerLObservation = api.suivreSession(sessionId, {
      onEvent: (ev) => {
        if (state.sessionId !== sessionId || ev.kind === "heartbeat") return;
        // « Montrer » : l'agent ouvre une création dans le panneau, pendant
        // son tour même. C'est ce flux-ci qui le porte, d'où qu'ait été lancé
        // le tour (décision J-f : le panneau s'ouvre seul).
        if (views.panneau?.surEvenement(ev)) return;
        // On ne se mêle pas d'un tour qu'on a lancé soi-même : celui-là a
        // déjà son flux, et deux écritures sur le même fil se marcheraient
        // dessus.
        if (state.busy) return;
        // Le journal a bougé ailleurs — dans VS Code, le plus souvent. On ne
        // rejoue pas un flux qu'on n'a pas : on relit, et la lecture fondue
        // rend l'histoire complete. A traiter avant d'ouvrir un bloc de flux,
        // sinon on poserait une bulle vide pour un evenement qui n'en veut pas.
        if (ev.kind === "systeme" && ev.cause === "journal_change") {
          relireLeJournal(state, render);
          return;
        }
        // La traîne d'un tour lancé d'ici est reconnue à ses identifiants,
        // quel que soit son retard : elle n'ouvre pas de seconde bulle.
        if (recevoirDuDirect({ state, render, views }, suivi, ev)) {
          refreshSessions(state).then(render);
        }
      },
    });
  }

  /** Retire un message de la file, tant qu'il n'est pas parti. */
  async function annulerEnFile(messageId) {
    if (!state.sessionId || !messageId) return;
    try {
      await api.annulerMessageEnFile(state.token, state.sessionId, messageId);
      S.retirerDeLaFileParId(state, messageId);
    } catch (err) {
      // Déjà parti : il est dans le tour, plus dans la file. On le dit.
      S.retirerDeLaFileParId(state, messageId);
      if (!/404/.test(err?.message || "")) {
        S.setError(state, err.message || String(err));
      }
    }
    render();
  }

  return { onSend, observer, cesserDObserver, annulerEnFile };
}
