// Le fil d'un tour : son ordre, ses segments, son raisonnement, ses nœuds.
//
// Quatre défauts se sont logés là en une seule journée, tous trouvés à l'œil
// ou au chronomètre, aucun par un test. Cette suite les tient :
//
//   1. les blocs s'affichaient groupés par nature — tous les outils en haut,
//      toute la parole en bas — au lieu de suivre l'ordre du tour ;
//   2. le texte tenait dans un tampon unique, si bien qu'un outil au milieu
//      d'une phrase ne la coupait pas et que la suite s'y recollait ;
//   3. le raisonnement passait par `mergeAssistantText`, qui le refuse par
//      conception : le tampon restait vide, rien n'apparaissait en direct ;
//   4. l'empreinte d'un bloc décidait de la réutilisation de son nœud ; trop
//      stable, un outil ne se rafraîchissait plus, trop instable, tout était
//      redessiné à chaque événement.

import { berceau, cliquer, ecouter, html, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import {
  blocCourant,
  buildStreamBlocks,
  creerMemoireDuFil,
  fusionnerReflexion,
  recevoirDeLEnvoi,
  recevoirDuDirect,
  texteAssemble,
} from "../../mcp_gateway/atelier/web/js/controllers/chat.js";
import { mergeAssistantText, messagesFromTranscript } from "../../mcp_gateway/atelier/web/js/api.js";
import {
  appendBlock,
  empreinteDuBloc,
  synchroniserBlocs,
} from "../../mcp_gateway/atelier/web/js/ui/message-render.js";

/** Un outil tel que le flux le dépose : le même objet dans `blocs` et `tools`. */
function outil(id, nom, extra = {}) {
  return {
    type: "tool",
    id,
    name: nom,
    input: { file_path: `/tmp/${id}` },
    output: "",
    status: "running",
    inputPartial: "",
    ...extra,
  };
}

// ── 1. L'ordre d'arrivée, et non les catégories ──────────────────────────
//
// Le tour dit, il agit, il redit. Regrouper mettait ce qui motive un outil
// après l'outil, et une demande d'autorisation loin du geste qui l'a causée.

{
  const lecture = outil("call_1", "Read", { output: "trois lignes", status: "done" });
  const ecriture = outil("call_2", "Write", { status: "running" });
  const flux = {
    blocs: [
      { type: "thinking", text: "Il faut d’abord lire." },
      { type: "text", text: "Je regarde le fichier." },
      lecture,
      { type: "text", text: "Il contient trois lignes ; je corrige la deuxième." },
      ecriture,
    ],
    tools: [lecture, ecriture],
    decisions: [],
  };

  const rendus = buildStreamBlocks(flux);
  egal(
    rendus.map((b) => b.type),
    ["thinking", "text", "tool", "text", "tool"],
    "les blocs gardent l’ordre du tour au lieu d’être groupés par nature",
  );
  egal(rendus[1].text, "Je regarde le fichier.", "la parole d’avant l’outil reste avant lui");
  egal(
    rendus[3].text,
    "Il contient trois lignes ; je corrige la deuxième.",
    "la parole d’après l’outil reste après lui",
  );
  egal(rendus[2].id, "call_1", "le premier outil rendu est le premier appelé");
  egal(rendus[4].status, "running", "l’outil en cours se donne pour tel");
}

{
  // Une décision arrive au milieu du fil, pas à la fin : elle se rend là où
  // le geste a eu lieu.
  const bash = outil("call_3", "Bash", { status: "denied" });
  const demande = {
    type: "decision",
    demande: { request_id: "req_1", outil: "Bash", tool_use_id: "call_3" },
    etat: "en_attente",
  };
  const flux = {
    blocs: [{ type: "text", text: "Je lance la commande." }, bash, demande],
    tools: [bash],
    decisions: [demande],
  };
  const rendus = buildStreamBlocks(flux);
  egal(
    rendus.map((b) => b.type),
    ["text", "tool", "decision"],
    "la demande d’autorisation suit l’outil qui l’a provoquée",
  );
  verifier(
    rendus[2].argumentsAilleurs === true,
    "les arguments ne sont pas répétés quand l’outil est rendu juste au-dessus",
  );
}

{
  // Une question voyage par le canal des autorisations. Sa carte montre déjà
  // les options et la réponse ; répéter la charge brute n'apprend rien.
  const question = outil("call_4", "AskUserQuestion", { status: "done" });
  const posee = {
    type: "decision",
    demande: { genre: "question", request_id: "req_2", tool_use_id: "call_4" },
    etat: "repondu",
  };
  const flux = { blocs: [question, posee], tools: [question], decisions: [posee] };
  const rendus = buildStreamBlocks(flux);
  verifier(rendus[0].masquerDetails === true, "l’outil d’une question cache ses détails");
}

{
  // Un fragment vide ne mérite pas de bloc : c'est ce qui laissait des trous
  // dans le fil quand le flux ouvrait un segment sans rien y mettre.
  const flux = {
    blocs: [
      { type: "text", text: "   " },
      { type: "text", text: "Voilà." },
    ],
    tools: [],
    decisions: [],
  };
  egal(
    buildStreamBlocks(flux).map((b) => b.text),
    ["Voilà."],
    "un segment resté vide n’est pas rendu",
  );
}

// ── 2. Le texte se découpe en segments ───────────────────────────────────
//
// `blocCourant` est ce qui décide : il ne rend le dernier bloc que s'il est du
// type voulu. Un outil au bout du fil ferme donc le segment, et la parole
// suivante en ouvre un autre.

{
  const lecture = outil("call_1", "Read");
  const flux = { blocs: [{ type: "text", text: "Je regarde." }], tools: [], decisions: [] };

  verifier(
    blocCourant(flux, "text") === flux.blocs[0],
    "tant que rien ne s’intercale, la parole continue le même segment",
  );
  verifier(
    blocCourant(flux, "thinking") === null,
    "un raisonnement ne se colle pas à la fin d’un segment de parole",
  );

  flux.blocs.push(lecture);
  flux.tools.push(lecture);
  verifier(
    blocCourant(flux, "text") === null,
    "un outil ferme le segment en cours : la parole suivante en ouvre un autre",
  );

  flux.blocs.push({ type: "text", text: "Il contient trois lignes." });
  verifier(
    blocCourant(flux, "text") === flux.blocs[2],
    "le nouveau segment est bien le second, pas le premier rouvert",
  );
  egal(
    flux.blocs.filter((b) => b.type === "text").length,
    2,
    "deux segments de parole coexistent autour de l’outil",
  );

  egal(
    texteAssemble(flux),
    "Je regarde.\n\nIl contient trois lignes.",
    "la copie du message recolle les segments, séparés d’une ligne vide",
  );
}

{
  egal(blocCourant({ blocs: [] }, "text"), null, "un fil vide n’a pas de segment ouvert");
}

// ── 3. Le raisonnement s’accumule, là où le texte de réponse le refuse ────
//
// `mergeAssistantText` écarte les fragments de raisonnement — c'est un
// garde-fou voulu, qui empêche le raisonnement de tomber dans la réponse.
// L'appelant s'en servait aussi pour le tampon de réflexion, qui restait donc
// vide : le raisonnement n'apparaissait qu'après rechargement.

{
  egal(
    mergeAssistantText("Je ", "vais", "thinking_delta"),
    "Je ",
    "le texte de réponse refuse un fragment de raisonnement — c’est voulu",
  );
  egal(
    mergeAssistantText("", "Je vais", "thinking"),
    "",
    "et il le refuse même quand le tampon est vide : rien ne s’affichait",
  );

  let buf = "";
  for (const morceau of ["Il faut ", "d’abord ", "lire le fichier."]) {
    buf = fusionnerReflexion(buf, morceau, "thinking_delta");
  }
  egal(
    buf,
    "Il faut d’abord lire le fichier.",
    "la fusion du raisonnement accumule bien les fragments successifs",
  );

  // Un fragment n'est jamais une redite : jeter celui qui ressemblait à la fin
  // du tampon changeait « 33 tests » en « 3 tests », mesuré sur le pod.
  egal(
    fusionnerReflexion("Il faut 3", "3", "thinking_delta"),
    "Il faut 33",
    "un fragment identique à la fin du tampon s’ajoute quand même",
  );
  egal(
    fusionnerReflexion("Il faut", "Il faut lire le fichier.", "thinking"),
    "Il faut lire le fichier.",
    "un envoi complet remplace le tampon qu’il prolonge, au lieu de s’y ajouter",
  );
  egal(fusionnerReflexion("Il faut", "", "thinking_delta"), "Il faut", "un vide ne casse rien");
  egal(fusionnerReflexion("", "Il faut", "thinking"), "Il faut", "le premier fragment ouvre le tampon");
}

// ── 4. L’empreinte : ce qui décide de redessiner un nœud ─────────────────
//
// Trop stable, un outil garde son ancienne carte et ne se rafraîchit plus.
// Trop instable, tout le message est reconstruit à chaque événement — mesuré
// à deux secondes de gel sur une conversation réelle.

{
  const enCours = outil("call_1", "Bash", { status: "running" });
  const memeChose = outil("call_1", "Bash", { status: "running" });
  verifier(
    empreinteDuBloc(enCours) === empreinteDuBloc(memeChose),
    "deux états identiques donnent la même empreinte : le nœud est réutilisable",
  );
  verifier(
    empreinteDuBloc(enCours) !== empreinteDuBloc({ ...enCours, status: "done" }),
    "un changement de statut change l’empreinte : la carte doit se redessiner",
  );
  verifier(
    empreinteDuBloc({ ...enCours, output: "ligne 1" }) !==
      empreinteDuBloc({ ...enCours, output: "ligne 1\nligne 2" }),
    "une sortie qui s’allonge change l’empreinte",
  );
  verifier(
    empreinteDuBloc(enCours) !== empreinteDuBloc({ ...enCours, masquerDetails: true }),
    "masquer les détails change ce qui est affiché, donc l’empreinte",
  );
  verifier(
    empreinteDuBloc(enCours) ===
      empreinteDuBloc({ ...enCours, inputPartial: "{\"comm" }),
    "le tampon d’assemblage des paramètres ne s’affiche pas : il ne compte pas",
  );

  const attente = {
    type: "decision",
    demande: { request_id: "req_1", outil: "Bash" },
    etat: "en_attente",
  };
  verifier(
    empreinteDuBloc(attente) ===
      empreinteDuBloc({ type: "decision", demande: { request_id: "req_1" }, etat: "en_attente" }),
    "une demande identique garde son empreinte, quel que soit l’objet qui la porte",
  );
  verifier(
    empreinteDuBloc(attente) !== empreinteDuBloc({ ...attente, etat: "allow" }),
    "une carte qui change d’état change d’empreinte",
  );
  verifier(
    empreinteDuBloc({ ...attente, etat: "repondu", resume: "A" }) !==
      empreinteDuBloc({ ...attente, etat: "repondu", resume: "A et B" }),
    "la réponse retenue fait partie de ce qui est affiché",
  );

  verifier(
    empreinteDuBloc({ type: "text", text: "Voilà." }) ===
      empreinteDuBloc({ type: "text", text: "Voilà." }),
    "un texte inchangé garde son empreinte",
  );
  verifier(
    empreinteDuBloc({ type: "text", text: "Voilà." }) !==
      empreinteDuBloc({ type: "text", text: "Voilà, enfin." }),
    "un texte qui grossit change d’empreinte",
  );
  verifier(
    empreinteDuBloc({ type: "text", text: "Voilà." }) !==
      empreinteDuBloc({ type: "thinking", text: "Voilà." }),
    "le même texte dit en raisonnement n’est pas le même bloc",
  );
}

// ── L’empreinte à l’œuvre : les nœuds qui survivent ──────────────────────
//
// C'est le point de tout ce qui précède : garder les nœuds dont l'empreinte
// n'a pas bougé, et ne refaire que ce qui change.

{
  const conteneur = berceau();
  const parole = { type: "text", text: "Je lance la commande." };
  const enCours = { type: "tool", id: "call_1", name: "Bash", input: { command: "ls" }, output: "", status: "running" };

  synchroniserBlocs(conteneur, [parole, enCours]);
  egal(conteneur.children.length, 2, "un bloc rendu par bloc du message");
  const noeudParole = conteneur.children[0];
  const noeudOutil = conteneur.children[1];
  porte(html(noeudOutil), "msg-tool-running", "l’outil en cours porte sa classe");
  porte(texte(noeudOutil), "en cours…", "et le dit en toutes lettres");

  synchroniserBlocs(conteneur, [parole, { ...enCours }]);
  verifier(
    conteneur.children[0] === noeudParole && conteneur.children[1] === noeudOutil,
    "rien n’a changé : aucun nœud n’est refait",
  );

  synchroniserBlocs(conteneur, [parole, { ...enCours, status: "done", output: "a.txt" }]);
  verifier(conteneur.children[0] === noeudParole, "le texte inchangé garde son nœud");
  verifier(conteneur.children[1] !== noeudOutil, "l’outil terminé est redessiné");
  porte(texte(conteneur.children[1]), "terminé", "et il dit qu’il a fini");
  porte(texte(conteneur.children[1]), "a.txt", "et montre sa sortie");
  nePorte(html(conteneur.children[1]), "msg-tool-running", "il ne se dit plus en cours");
}

// ── Le socle lui-même : un clic remonte le fil ───────────────────────────
//
// Les cartes n'agissent pas, elles annoncent : le contrôleur écoute
// `atelier:decision` sur le fil, au-dessus. Un DOM qui ne ferait pas remonter
// l'événement laisserait passer un bouton muet.

{
  const fil = berceau();
  const recus = ecouter(fil, "atelier:decision");
  appendBlock(fil, {
    type: "decision",
    etat: "en_attente",
    demande: {
      genre: "question",
      request_id: "req_9",
      arguments: {
        questions: [
          { question: "On garde laquelle ?", options: [{ label: "La première" }, { label: "La seconde" }] },
        ],
      },
    },
  });

  const carte = fil.children[0];
  const options = carte.querySelectorAll(".msg-question-option");
  egal(options.length, 2, "les options de l’agent sont rendues telles qu’il les a écrites");

  cliquer(options[1]);
  egal(recus.length, 1, "une question à choix unique se répond d’un seul clic");
  // Lu prudemment : si l’événement ne remonte pas, on veut le compte-rendu du
  // premier échec, pas une pile d’appels.
  const annonce = recus[0]?.detail || {};
  egal(annonce.requestId, "req_9", "la réponse porte l’identifiant de la demande");
  egal(annonce.reponses, [["La seconde"]], "et le libellé choisi, pas son rang");
}

// ── 5. Un tour lancé d'ici, reçu par deux flux : une seule réponse ─────────
//
// Essai du 26/09 (Lecteur Grist, conversation neuve) : après un tour où la
// personne avait refusé un outil, la réponse s'affichait deux fois — deux
// blocs « ASSISTANT » identiques, même raisonnement, même outil refusé, même
// texte. Le flux de l'envoi et le flux en direct livrent les mêmes
// événements ; le second n'était écarté que quatre secondes après la fin du
// tour, et seulement s'il commençait par une fin. Arrivé plus tard, il
// ouvrait sa bulle et rejouait tout le tour.
//
// La mise en scène : l'envoi rend le tour, la main est rendue, puis le flux en
// direct livre le même tour. Aucune horloge n'est consultée : c'est
// l'identité des événements qui décide.

// Les décisions font relire la liste des conversations : pas de réseau dans
// une suite, on rend une liste vide.
globalThis.fetch = async () => ({ ok: true, json: async () => ({ sessions: [] }) });

/** Le tour du 26/09, tel que les deux flux le livrent : mêmes identifiants. */
function tourAvecRefus(envoi) {
  const m = "msg_01Refus";
  const commun = { session_id: "s1", envoi };
  return [
    { ...commun, kind: "texte", raw_type: "thinking_delta", text: "Je lis la table.", uuid: "u1" },
    { ...commun, kind: "texte", raw_type: "thinking", text: "Je lis la table.", uuid: "u2", message_id: m },
    {
      ...commun, kind: "outil_debut", raw_type: "assistant", tool: "Bash", tool_id: "toolu_1",
      text: JSON.stringify({ command: "curl grist" }), uuid: "u3", message_id: m,
    },
    {
      ...commun, kind: "decision_attendue", tool: "Bash", tool_id: "req_1",
      text: JSON.stringify({ request_id: "req_1", outil: "Bash", tool_use_id: "toolu_1" }),
    },
    { ...commun, kind: "decision_rendue", tool: "Bash", tool_id: "req_1", cause: "deny" },
    { ...commun, kind: "outil_fin", raw_type: "tool_result", tool_id: "toolu_1", text: "Refusé par l'utilisateur.", erreur: true, uuid: "u4" },
    { ...commun, kind: "texte", raw_type: "assistant", text: "Je n'ai pas lancé la commande.", uuid: "u5", message_id: "msg_02Fin" },
    { ...commun, kind: "texte", raw_type: "result_text", text: "Je n'ai pas lancé la commande.", uuid: "u6" },
    { ...commun, kind: "fin", raw_type: "result", cause: "success", uuid: "u6" },
  ];
}

function scene() {
  const state = { messages: [], busy: false, sessionId: "s1" };
  const ctx = {
    state,
    render: () => {},
    views: { codeChat: { renderThread: () => {} }, fils: { renderFils: () => {} } },
  };
  return { state, ctx };
}

function bullesAssistant(state) {
  return state.messages.filter((m) => m.role === "assistant");
}

{
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  const envoi = "envoi-26-09";
  memoire.envois.add(envoi);

  // Le flux de l'envoi : la bulle ouverte par l'envoi, remplie par lui.
  state.busy = true;
  state.messages.push({ role: "user", text: "Lis la table Grist." });
  state.messages.push({ role: "assistant", text: "", blocks: [], streaming: true });
  const stream = { blocs: [], tools: [], decisions: [], phase: "attente" };
  for (const ev of tourAvecRefus(envoi)) recevoirDeLEnvoi(ctx, stream, memoire, ev);
  state.messages = state.messages.map((m) => ({ ...m, streaming: false }));
  state.busy = false;

  egal(bullesAssistant(state).length, 1, "l’envoi rend une seule réponse");
  egal(
    bullesAssistant(state)[0].blocks.map((b) => b.type),
    ["thinking", "tool", "decision", "text"],
    "le raisonnement, l’outil refusé, la décision puis la réponse",
  );

  // Le flux en direct, en retard : le même tour, les mêmes identifiants.
  const suivi = { flux: null, memoire };
  for (const ev of tourAvecRefus(envoi)) recevoirDuDirect(ctx, suivi, ev);

  egal(
    bullesAssistant(state).length,
    1,
    "le même tour reçu par le flux en direct n’ouvre pas de seconde bulle",
  );
  verifier(suivi.flux === null, "et aucun tour observé ne reste ouvert");
  egal(
    bullesAssistant(state)[0].blocks.map((b) => b.type),
    ["thinking", "tool", "decision", "text"],
    "la bulle de l’envoi n’a rien reçu en double",
  );
}

{
  // Le même message, reconnu à son seul `message_id` ou à son seul `uuid` :
  // un événement qui ne porterait pas l'envoi ne rouvre pas la réponse.
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  state.messages.push({ role: "assistant", text: "", blocks: [], streaming: true });
  const stream = { blocs: [], tools: [], decisions: [], phase: "attente" };
  const dit = { kind: "texte", raw_type: "assistant", text: "Voilà.", uuid: "u9", message_id: "msg_9" };
  recevoirDeLEnvoi(ctx, stream, memoire, dit);
  state.messages = state.messages.map((m) => ({ ...m, streaming: false }));

  const suivi = { flux: null, memoire };
  recevoirDuDirect(ctx, suivi, { ...dit, uuid: "" });
  recevoirDuDirect(ctx, suivi, { ...dit, message_id: "" });
  egal(bullesAssistant(state).length, 1, "reconnu par message_id comme par uuid");
}

{
  // Ce n'est pas le texte qui décide : un autre tour qui dit la même chose
  // (lancé d'ailleurs, autres identifiants) s'affiche bien.
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  memoire.envois.add("envoi-a");
  memoire.messages.add("msg_a");
  const suivi = { flux: null, memoire };
  const autre = { session_id: "s1", envoi: "envoi-b" };
  recevoirDuDirect(ctx, suivi, { ...autre, kind: "texte", raw_type: "assistant", text: "Voilà.", message_id: "msg_b", uuid: "ub1" });
  recevoirDuDirect(ctx, suivi, { ...autre, kind: "fin", raw_type: "result", uuid: "ub2" });
  egal(bullesAssistant(state).length, 1, "un tour d’ailleurs ouvre sa bulle, même s’il dit la même chose");
  porte(bullesAssistant(state)[0].text, "Voilà.", "et il s’y écrit");
}

{
  // Relu du journal : une même ligne présente deux fois (les deux registres
  // fondus) ne fait ni deux raisonnements ni deux outils. Même règle : par
  // identifiant (`uuid`, `message.id`, `id` de l'appel), pas par texte.
  const ligne = (o) => JSON.stringify(o);
  const pense = { type: "thinking", thinking: "Je lis la table." };
  const appel = { type: "tool_use", id: "toolu_1", name: "Bash", input: { command: "curl grist" } };
  const transcript = [
    ligne({ type: "user", message: { content: [{ type: "text", text: "Lis la table Grist." }] } }),
    ligne({ type: "assistant", uuid: "a1", message: { id: "msg_01", content: [pense] } }),
    ligne({ type: "assistant", uuid: "a2", message: { id: "msg_01", content: [appel] } }),
    ligne({
      type: "user", uuid: "r1",
      message: { content: [{ type: "tool_result", tool_use_id: "toolu_1", is_error: true, content: "Refusé." }] },
    }),
    // La même chose, sous d'autres uuid (l'autre registre) :
    ligne({ type: "assistant", uuid: "b1", message: { id: "msg_01", content: [pense] } }),
    ligne({ type: "assistant", uuid: "b2", message: { id: "msg_01", content: [appel] } }),
    // Et une ligne strictement rejouée :
    ligne({ type: "assistant", uuid: "a2", message: { id: "msg_01", content: [appel] } }),
    ligne({ type: "assistant", uuid: "a3", message: { id: "msg_02", content: [{ type: "text", text: "Je n'ai pas lancé la commande." }] } }),
    ligne({ type: "result", subtype: "success", result: "Je n'ai pas lancé la commande." }),
  ].join(String.fromCharCode(10));
  const assistants = messagesFromTranscript(transcript).filter((m) => m.role === "assistant");
  egal(assistants.length, 1, "une seule réponse relue");
  egal(
    (assistants[0]?.blocks || []).map((b) => b.type),
    ["thinking", "tool", "text"],
    "un raisonnement, un outil, une réponse",
  );
  egal(assistants[0]?.blocks?.[1]?.status, "denied", "l’outil reste refusé");

  // Deux messages distincts qui disent la même chose restent deux paroles.
  const redit = [
    ligne({ type: "assistant", uuid: "c1", message: { id: "msg_x", content: [{ type: "text", text: "D’accord." }] } }),
    ligne({ type: "assistant", uuid: "c2", message: { id: "msg_y", content: [{ type: "text", text: "D’accord." }] } }),
  ].join(String.fromCharCode(10));
  egal(
    messagesFromTranscript(redit)[0].blocks.filter((b) => b.type === "text").length,
    2,
    "le même texte dans deux messages n’est pas un doublon",
  );
}

{
  // Essais du 26/09 : `take_snapshot` a lu https://example.com, dont le texte
  // dit « without needing permission ». Le statut se lisait dans le texte :
  // l'outil, exécuté et rendu, s'affichait « permission refusée ». C'est le
  // `is_error` du CLI (`erreur` de l'événement) qui décide.
  const page =
    'uid=1_0 RootWebArea "Example Domain" ' +
    'uid=1_2 StaticText "This domain is for use in ' +
    'documentation examples without needing permission. Avoid use in operations."';
  const { state, ctx } = scene();
  const memoire = creerMemoireDuFil();
  state.messages.push({ role: "assistant", text: "", blocks: [], streaming: true });
  const stream = { blocs: [], tools: [], decisions: [], phase: "attente" };
  const commun = { session_id: "s1" };
  const evenements = [
    { ...commun, kind: "outil_debut", raw_type: "assistant", tool: "mcp__chrome-devtools-mcp__take_snapshot", tool_id: "t_lu", text: "{}", uuid: "p1" },
    { ...commun, kind: "outil_fin", raw_type: "tool_result", tool_id: "t_lu", text: page, erreur: false, uuid: "p2" },
    { ...commun, kind: "outil_debut", raw_type: "assistant", tool: "Bash", tool_id: "t_refus", text: "{}", uuid: "p3" },
    {
      ...commun, kind: "outil_fin", raw_type: "tool_result", tool_id: "t_refus", erreur: true, uuid: "p4",
      text: "Claude requested permissions to use Bash, but you haven't granted it yet.",
    },
    { ...commun, kind: "outil_debut", raw_type: "assistant", tool: "Read", tool_id: "t_echec", text: "{}", uuid: "p5" },
    { ...commun, kind: "outil_fin", raw_type: "tool_result", tool_id: "t_echec", text: "File does not exist.", erreur: true, uuid: "p6" },
    // Même si un décompte de fin de tour nommait la lecture, elle a rendu la page.
    {
      ...commun, kind: "permission_demandee", raw_type: "permission_denials", uuid: "p7",
      text: JSON.stringify([
        { tool_name: "mcp__chrome-devtools-mcp__take_snapshot", tool_use_id: "t_lu" },
        { tool_name: "Bash", tool_use_id: "t_refus" },
      ]),
    },
  ];
  for (const ev of evenements) recevoirDeLEnvoi(ctx, stream, memoire, ev);
  const statut = (id) => stream.tools.find((t) => t.id === id)?.status;
  egal(statut("t_lu"), "done", "une lecture qui a rendu la page est « terminée », même si la page parle de permission");
  egal(statut("t_refus"), "denied", "un refus du CLI reste un refus");
  egal(statut("t_echec"), "error", "un échec de l’outil se dit « erreur », pas « terminé »");

  const racine = berceau();
  appendBlock(racine, stream.tools.find((t) => t.id === "t_lu"));
  porte(texte(racine), "terminé", "l’en-tête dit « terminé »");
  nePorte(texte(racine), "permission refusée", "et jamais « permission refusée »");

  // Relu du journal : même règle.
  const ligne = (o) => JSON.stringify(o);
  const relu = messagesFromTranscript(
    [
      ligne({ type: "assistant", uuid: "r1", message: { id: "m1", content: [{ type: "tool_use", id: "t_lu", name: "mcp__chrome-devtools-mcp__take_snapshot", input: {} }] } }),
      ligne({ type: "user", uuid: "r2", message: { content: [{ type: "tool_result", tool_use_id: "t_lu", content: [{ type: "text", text: page }] }] } }),
      ligne({ type: "result", subtype: "success", result: "", permission_denials: [{ tool_name: "x", tool_use_id: "t_lu" }] }),
    ].join(String.fromCharCode(10)),
  );
  egal(relu[0]?.blocks?.[0]?.status, "done", "relue, la lecture reste « terminée »");
}

bilan("flux-conversation");
