// Le panneau à droite du fil, et les défauts d'interface du lot H.
//
// Ce qu'il doit tenir :
//   - une vue du panneau s'ouvre par l'Atelier (passage), jamais par une
//     adresse de l'hôte écrite à la main ;
//   - l'iframe d'un onglet survit au rendu : rendre deux fois ne la recrée pas ;
//   - « Montrer » (outil de l'agent) ouvre le panneau seul, sur le bon onglet ;
//   - la fin d'un tour lancé d'ici, reçue en retard par le flux en direct,
//     n'ouvre pas une seconde bulle (réponse en double) ;
//   - les demandes d'un tour disparu se replient en une ligne ;
//   - ce qu'un hook dit (relance de wikichat) se lit dans le fil ;
//   - le texte affiché suit le lexique : « Créations », « Montrer », jamais
//     « artefact » ;
//   - un bureau (service du namespace) s'ouvre par l'Atelier, depuis l'onglet
//     « Bureaux » du catalogue, jamais sur un événement (J-f) ; masqué ou
//     panneau replié, son cadre part et le flux s'arrête.

import { berceau, cliquer, ecouter, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import {
  adresseDeLaVue,
  createPanneauView,
  estUnFluxVivant,
  estUnService,
  fusionnerVues,
  libelleEpingle,
  vueDeService,
} from "../../mcp_gateway/atelier/web/js/views/panneau.js";
import { rendrePanneauApplications } from "../../mcp_gateway/atelier/web/js/views/applications.js";
import { libelleEchanges, rendreFils } from "../../mcp_gateway/atelier/web/js/views/fils.js";
import { ouvreUnTour, buildStreamBlocks } from "../../mcp_gateway/atelier/web/js/controllers/chat.js";
import { appendBlock, carteDAction } from "../../mcp_gateway/atelier/web/js/ui/message-render.js";
import { messageSysteme, messagesFromTranscript } from "../../mcp_gateway/atelier/web/js/api.js";

async function attendre() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
}

// ── Adresses et onglets ────────────────────────────────────────────────
{
  egal(adresseDeLaVue({ projet: "demo", nom: "carte" }), "/v1/apps/demo/carte/ouvrir", "par l'Atelier");
  egal(
    adresseDeLaVue({ projet: "demo", nom: "carte", chemin: "a b.html" }),
    "/v1/apps/demo/carte/ouvrir?chemin=a%20b.html",
    "le chemin est encodé",
  );
  egal(adresseDeLaVue({ projet: "demo" }), "", "sans nom, pas d'adresse");
  const vues = fusionnerVues([{ id: "a" }, { id: "b" }], { id: "a", titre: "neuf" });
  egal(vues.map((v) => v.id), ["b", "a"], "même objet, même onglet, remis au bout");
  egal(libelleEpingle({ epingle: "projet" }).suivante, "conversation", "désépingler du projet");
  egal(libelleEpingle({ epingle: "conversation" }).texte, "Épingler au projet", "libellé d'épingle");
}

// ── Le panneau : iframe gardée, Montrer ouvre seul ─────────────────────
{
  const ids = ["panneau", "view-code", "session-panneau-button", "panneau-onglets", "panneau-outils",
    "panneau-catalogue", "panneau-corps", "panneau-note", "panneau-ajouter", "panneau-replier"];
  for (const id of ids) {
    const n = document.createElement(id === "panneau" ? "aside" : "div");
    n.id = id;
    document.body.appendChild(n);
  }
  document.getElementById("panneau").hidden = true;
  document.getElementById("panneau-catalogue").hidden = true;

  const carte = { id: "v_1", genre: "creation", projet: "demo", nom: "carte", chemin: "", titre: "Carte", epingle: "conversation", par: "agent" };
  const appels = [];
  const api = {
    panneauVues: async (sid) => (appels.push(["vues", sid]), { vues: [carte] }),
    panneauEnregistrer: async (sid, vue) => (appels.push(["enregistrer", vue.epingle]), { ...carte, ...vue, id: vue.id || "v_2" }),
    panneauRetirer: async (sid, id) => (appels.push(["retirer", id]), { retiree: true }),
    listApps: async () => ({ expose: true, artefacts: [] }),
    artifactsUrl: () => "/v1/artifacts/demo/",
  };
  const state = { view: "code", sessionId: "s1", slug: "demo", sessions: [] };
  const panneau = createPanneauView({ state, api, render: () => {} });
  panneau.bind();
  panneau.renderPanneau();
  await attendre();
  egal(appels[0], ["vues", "s1"], "les onglets de la conversation se chargent");
  verifier(document.getElementById("panneau").hidden, "fermé tant qu'on ne l'ouvre pas");
  porte(texte(document.getElementById("session-panneau-button")), "Panneau (1)", "le bouton dit combien");

  cliquer(document.getElementById("session-panneau-button"));
  verifier(!document.getElementById("panneau").hidden, "le bouton ouvre le panneau");
  const cadre = document.querySelector(".panneau-cadre");
  verifier(cadre, "un cadre pour l'onglet");
  egal(cadre.getAttribute("src") || cadre.src, "/v1/apps/demo/carte/ouvrir", "le cadre passe par l'Atelier");
  porte(cadre.getAttribute("sandbox"), "allow-scripts", "bac à sable posé");
  nePorte(cadre.getAttribute("sandbox"), "allow-top-navigation", "jamais la navigation du haut");
  panneau.renderPanneau();
  panneau.renderPanneau();
  verifier(document.querySelector(".panneau-cadre") === cadre, "rendre à nouveau ne recrée pas le cadre");

  // Replier, puis l'agent montre : le panneau s'ouvre seul, sur son onglet.
  cliquer(document.getElementById("panneau-replier"));
  verifier(document.getElementById("panneau").hidden, "replier ferme le panneau");
  const neuve = { ...carte, id: "v_9", nom: "rapport", titre: "Rapport" };
  const pris = panneau.surEvenement({ kind: "systeme", cause: "panneau_montrer", session_id: "s1", text: JSON.stringify(neuve) });
  verifier(pris, "l'événement Montrer est reconnu");
  verifier(!document.getElementById("panneau").hidden, "Montrer ouvre le panneau seul (J-f)");
  const actif = document.getElementById("panneau-onglets").querySelectorAll("button").find((b) => b.getAttribute("aria-selected") === "true");
  egal(texte(actif), "Rapport", "l'onglet montré est actif");
  verifier(document.querySelector(".panneau-cadre") !== null, "son cadre existe");
  verifier(!panneau.surEvenement({ kind: "systeme", cause: "message_suivant" }), "un autre événement n'est pas pour le panneau");
  panneau.surEvenement({ kind: "systeme", cause: "panneau_montrer", session_id: "autre", text: JSON.stringify({ ...carte, id: "v_x" }) });
  egal(document.getElementById("panneau-onglets").querySelectorAll("button").length, 2, "une autre conversation ne s'invite pas");

  // Épingler, puis fermer.
  const epingler = document.getElementById("panneau-outils").querySelectorAll("button").find((b) => texte(b) === "Épingler au projet");
  cliquer(epingler);
  await attendre();
  porte(JSON.stringify(appels), '["enregistrer","projet"]', "épingler au projet enregistre");
  const fermer = document.getElementById("panneau-outils").querySelectorAll("button").find((b) => texte(b) === "Fermer");
  cliquer(fermer);
  await attendre();
  verifier(appels.some((a) => a[0] === "retirer"), "fermer retire l'onglet côté service");
}

// ── Les bureaux : par l'Atelier, sur un geste, jamais en tâche de fond ─
{
  const fiche = { connecteur: "blender", nom: "bureau", genre: "bureau", titre: "Bureau Blender", ouvrir: "/v1/bureaux/blender/bureau/ouvrir" };
  const vue = vueDeService(fiche);
  egal(adresseDeLaVue(vue), "/v1/bureaux/blender/bureau/ouvrir", "un bureau s'ouvre par l'Atelier");
  verifier(estUnService(vue) && estUnFluxVivant(vue), "un bureau est un flux vivant");
  verifier(!estUnFluxVivant(vueDeService({ ...fiche, nom: "editeur", genre: "application" })), "un éditeur n'en est pas un");
  verifier(!estUnService({ projet: "demo", nom: "carte" }), "une création n'est pas un service");
  nePorte(JSON.stringify(vue), "amont", "l'onglet ne connaît pas l'amont");

  // Un panneau neuf, sur des éléments neufs : ceux du bloc précédent partent.
  const ids = ["panneau", "view-code", "session-panneau-button", "panneau-onglets", "panneau-outils",
    "panneau-catalogue", "panneau-corps", "panneau-note", "panneau-ajouter", "panneau-replier"];
  for (const id of ids) {
    document.getElementById(id)?.remove();
    const n = document.createElement(id === "panneau" ? "aside" : "div");
    n.id = id;
    document.body.appendChild(n);
  }
  document.getElementById("panneau").hidden = true;
  document.getElementById("panneau-catalogue").hidden = true;

  const carte = { id: "v_1", genre: "creation", projet: "demo", nom: "carte", chemin: "", titre: "Carte", epingle: "conversation", par: "personne" };
  const appels = [];
  const api = {
    panneauVues: async () => ({ vues: [carte] }),
    panneauEnregistrer: async (sid, v) => (appels.push(["enregistrer"]), v),
    panneauRetirer: async (sid, id) => (appels.push(["retirer", id]), { retiree: true }),
    listApps: async () => ({ expose: true, artefacts: [] }),
    artifactsUrl: () => "/v1/artifacts/demo/",
    listBureaux: async () => (appels.push(["bureaux"]), { expose: true, vues: [fiche], refusees: [] }),
  };
  const state = { view: "code", sessionId: "s2", slug: "demo", sessions: [] };
  const panneau = createPanneauView({ state, api, render: () => {} });
  panneau.bind();
  panneau.renderPanneau();
  await attendre();

  const aside = document.getElementById("panneau");
  const corps = document.getElementById("panneau-corps");
  const cadreDuBureau = () => corps.querySelectorAll(".panneau-cadre").find((f) => (f.getAttribute("src") || f.src) === "/v1/bureaux/blender/bureau/ouvrir") || null;
  const onglet = (t) => document.getElementById("panneau-onglets").querySelectorAll("button").find((b) => texte(b) === t);

  // L'agent ne peut pas ouvrir un bureau : l'événement est pris, rien ne s'ouvre.
  verifier(panneau.surEvenement({ kind: "systeme", cause: "panneau_montrer", session_id: "s2", text: JSON.stringify(vue) }), "l'événement est reconnu");
  verifier(aside.hidden, "un bureau ne s'ouvre jamais seul (J-f)");
  egal(document.getElementById("session-panneau-button").textContent, "Panneau (1)", "aucun onglet de plus");

  // La personne : « + », puis l'onglet « Bureaux » du catalogue.
  cliquer(document.getElementById("session-panneau-button"));
  cliquer(document.getElementById("panneau-ajouter"));
  const catalogue = document.getElementById("panneau-catalogue");
  verifier(!catalogue.hidden, "le catalogue s'ouvre");
  const rayons = catalogue.querySelectorAll("button").filter((b) => b.getAttribute("role") === "tab").map((b) => texte(b));
  egal(rayons, ["Créations", "Bureaux"], "deux rayons au catalogue");
  cliquer(catalogue.querySelectorAll("button").find((b) => texte(b) === "Bureaux"));
  await attendre();
  verifier(appels.some((a) => a[0] === "bureaux"), "les bureaux se lisent sur l'Atelier");
  porte(texte(catalogue), "Bureau Blender", "le bureau est proposé");
  nePorte(texte(catalogue), "rtefact", "le lexique tient");
  cliquer(catalogue.querySelectorAll("button").find((b) => texte(b) === "Montrer"));
  verifier(!aside.hidden && catalogue.hidden, "Montrer ouvre l'onglet du bureau");
  verifier(cadreDuBureau(), "le cadre passe par l'Atelier");
  porte(cadreDuBureau().getAttribute("sandbox"), "allow-same-origin", "noVNC a besoin de son cookie sur l'hôte");
  nePorte(cadreDuBureau().getAttribute("sandbox"), "allow-top-navigation", "jamais la navigation du haut");
  const gestes = document.getElementById("panneau-outils").querySelectorAll("button").map((b) => texte(b));
  egal(gestes, ["Recharger", "Détacher", "Fermer"], "un bureau ne s'épingle pas");
  verifier(!appels.some((a) => a[0] === "enregistrer"), "et ne s'enregistre pas");

  // Masqué, le flux s'arrête ; affiché, il repart.
  cliquer(onglet("Carte"));
  verifier(cadreDuBureau() === null, "onglet masqué : le cadre du bureau part");
  verifier(corps.querySelectorAll(".panneau-cadre").length === 1, "la création, elle, garde son cadre");
  cliquer(onglet("Bureau Blender"));
  verifier(cadreDuBureau(), "rendu visible, le bureau revient");
  cliquer(document.getElementById("panneau-replier"));
  verifier(cadreDuBureau() === null, "panneau replié : aucun bureau ne tourne");

  // Fermer : rien à retirer côté Atelier.
  panneau.ouvrir(true);
  cliquer(onglet("Bureau Blender"));
  cliquer(document.getElementById("panneau-outils").querySelectorAll("button").find((b) => texte(b) === "Fermer"));
  await attendre();
  verifier(!appels.some((a) => a[0] === "retirer"), "fermer un bureau n'appelle pas le panneau de l'Atelier");
  egal(document.getElementById("panneau-onglets").querySelectorAll("button").map((b) => texte(b)), ["Carte"], "l'onglet est parti");
}

// ── Les créations : « Montrer » remplace le nouvel onglet ──────────────
{
  const conteneur = berceau();
  const montrees = [];
  rendrePanneauApplications(
    conteneur,
    {
      slug: "demo", expose: true, artefactsUrl: "/v1/artifacts/demo/",
      artefacts: [{ nom: "carte", titre: "Carte", mode: "autonome", etat: "statique", ouvrir: "/v1/apps/demo/carte/ouvrir", url: "" }],
    },
    { montrer: (f) => montrees.push(f.nom), recharger: async () => {} },
  );
  porte(texte(conteneur), "Créations du projet", "le lexique : créations");
  nePorte(texte(conteneur), "rtefact", "jamais « artefact » à l'écran");
  egal(conteneur.querySelectorAll("a").filter((a) => !a.parentNode.hidden).length, 0, "aucun lien vers un nouvel onglet");
  const montrer = conteneur.querySelectorAll("button").find((b) => texte(b) === "Montrer");
  cliquer(montrer);
  egal(montrees, ["carte"], "Montrer ouvre dans le panneau");
}

// ── Réponse en double : la traîne d'un tour n'ouvre pas de bulle ────────
{
  verifier(!ouvreUnTour({ kind: "texte", raw_type: "result_text", text: "réponse" }), "le texte de résultat n'ouvre pas de bulle");
  verifier(!ouvreUnTour({ kind: "fin" }), "une fin n'ouvre pas de bulle");
  verifier(!ouvreUnTour({ kind: "decision_rendue" }), "une décision rendue non plus");
  verifier(!ouvreUnTour({ kind: "outil_fin", text: "x" }), "ni une fin d'outil");
  verifier(ouvreUnTour({ kind: "texte", raw_type: "content_block_delta", text: "Bon" }), "une parole ouvre une bulle");
  verifier(ouvreUnTour({ kind: "outil_debut" }), "un outil aussi");
  verifier(ouvreUnTour({ kind: "systeme", cause: "message_systeme", text: "x" }), "un message de hook aussi");
}

// ── Ce que wikichat dit dans le fil ────────────────────────────────────
{
  const flux = { blocs: [{ type: "text", text: "je regarde" }, { type: "systeme", text: "wikichat : tour prolongé (relance 1/3)." }], tools: [], decisions: [] };
  const blocs = buildStreamBlocks(flux);
  egal(blocs.map((b) => b.type), ["text", "systeme"], "le message du hook garde sa place");
  const b = berceau();
  appendBlock(b, blocs[1]);
  porte(texte(b), "relance 1/3", "il se lit dans le fil");
  egal(b.querySelectorAll(".msg-systeme").length, 1, "à part de la parole de l'agent");

  egal(messageSysteme({ type: "system", subtype: "informational", content: "tour prolongé" }), "tour prolongé", "informational");
  egal(messageSysteme({ type: "system", subtype: "hook_response", output: JSON.stringify({ systemMessage: "relance" }) }), "relance", "hook_response");
  egal(messageSysteme({ type: "system", subtype: "init" }), "", "init ne dit rien");
  const relu = messagesFromTranscript([
    JSON.stringify({ type: "assistant", message: { content: [{ type: "text", text: "fini" }] } }),
    JSON.stringify({ type: "system", systemMessage: "wikichat : réponse attendue" }),
    JSON.stringify({ type: "result", subtype: "success", result: "fini" }),
  ].join("\n"));
  porte(JSON.stringify(relu), "wikichat : réponse attendue", "relu au rechargement");
}

// ── Les demandes d'un tour disparu : repliées, classables ──────────────
{
  const b = berceau();
  appendBlock(b, { type: "perimees", demandes: [
    { request_id: "r1", outil: "Bash", description: "ls" },
    { request_id: "r2", outil: "Write", description: "a.txt" },
  ] });
  const pli = b.querySelector(".msg-perimees");
  verifier(pli && pli.tagName === "details", "une seule ligne repliée");
  porte(texte(pli), "2 demandes d’un tour terminé", "elle dit combien");
  egal(pli.querySelectorAll("button").map((x) => texte(x)), ["Classer"], "un seul geste, pas d'Autoriser/Refuser");
  const recus = ecouter(b, "atelier:classer");
  cliquer(pli.querySelector("button"));
  egal(recus[0]?.detail?.requestIds, ["r1", "r2"], "classer annonce les demandes");

  const seule = berceau();
  appendBlock(seule, { type: "decision", etat: "orpheline", demande: { request_id: "r3", outil: "Bash", genre: "autorisation" } });
  const carteOrpheline = seule.querySelector(".msg-decision-pliee");
  verifier(carteOrpheline && carteOrpheline.tagName === "details", "une demande orpheline du tour se replie aussi");
  egal(carteOrpheline.querySelectorAll("button").filter((x) => texte(x) === "Autoriser").length, 0, "sans bouton Autoriser");
}

// ── Échanges et cartes d'action ────────────────────────────────────────
{
  egal(libelleEchanges({ fils: [] }), "", "rien à dire, rien d'affiché");
  const rendu = { agent: "demo-abc", fils: [{ id: "f-1", participants: ["demo-abc", "gardien"], attend: ["demo-abc"], sujet: "<b>parité</b>", en_retard: true, messages: [{ de: "gardien", extrait: "tu prends ?" }] }] };
  porte(libelleEchanges(rendu), "1 attend une réponse", "le bouton dit qui attend");
  const zone = berceau();
  rendreFils(zone, rendu);
  porte(texte(zone), "<b>parité</b>", "le sujet reste du texte");
  egal(zone.querySelectorAll("b").length, 0, "aucun élément créé depuis wikichat");
  porte(texte(zone), "en retard", "le retard se voit");

  const carteAction = carteDAction(JSON.stringify({ carte: { titre: "Projet créé", resume: "cartes", voir: { lien: "javascript:alert(1)" } } }));
  porte(texte(carteAction), "Projet créé", "la carte d'action se lit");
  egal(carteAction.querySelectorAll("a").length, 0, "un lien javascript: n'est jamais posé");
  const avecLien = carteDAction({ carte: { titre: "Vue", voir: { lien: "/v1/apps/demo/x/ouvrir" } } });
  egal(avecLien.querySelectorAll("a").length, 1, "un lien de l'Atelier l'est");
  egal(carteDAction("pas du json"), null, "une sortie ordinaire n'a pas de carte");
}

bilan("panneau");
