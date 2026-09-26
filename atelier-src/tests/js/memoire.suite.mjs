// « Ma mémoire » (vague 3, équipe M) : ce qui est retenu, d'où ça vient, Corriger, Oublier.
//   - les quatre parties (profil, préférences, interprétations, faits d'office) ;
//   - « d'où ça vient » sur chaque ligne ;
//   - Corriger ouvre un champ, Enregistrer appelle `atelier_memoire_corriger` ;
//   - Oublier demande une confirmation avant `atelier_memoire_oublier` ;
//   - les propositions en attente mènent à « À valider » ;
//   - les mots de l'écran suivent le lexique.

import { cliquer, saisir, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const { rendreMemoire, createMemoireActions, origineLisible, PARTIES } = await import(
  "../../mcp_gateway/atelier/web/js/views/memoire.js"
);

const MAINTENANT = Date.parse("2026-09-26T10:00:00Z");
const DONNEES = {
  elements: [
    { id: "m-1", type: "profil", texte: "Travaille au Cerema", par: "personne", cree_le: "2026-09-20T10:00:00Z",
      source: { conversation: "0123456789abcdef", projet: "carte" } },
    { id: "m-2", type: "preference", texte: "Pas de notification la nuit", par: "personne", cree_le: "2026-09-25T10:00:00Z", source: {} },
    { id: "m-3", type: "fait", texte: "25/09 : projet « Marchés publics » créé", par: "code", cree_le: "2026-09-25T14:05:00Z",
      source: { projet: "marches-publics", conversation: "fedcba9876543210" } },
  ],
  propositions_en_attente: [{ id: "av-1", titre: "Retenir (préférence) : réponses courtes" }],
  fiches: 12,
};

function bouton(noeud, libelle) {
  return noeud.querySelectorAll("button").find((b) => texte(b) === libelle) || null;
}

function ligne(noeud, id) {
  return noeud.querySelectorAll("li").find((li) => li.dataset.id === id) || null;
}

// ── Le rendu ───────────────────────────────────────────────────────────
{
  egal(PARTIES.map((p) => p.type), ["profil", "preference", "interpretation", "fait"], "quatre parties");
  const state = { memoire: { charge: true, donnees: DONNEES } };
  const appels = [];
  const actions = {
    editer: (id) => appels.push(["editer", id]),
    demanderOubli: (id) => appels.push(["oubli?", id]),
    corriger: (id, t) => appels.push(["corriger", id, t]),
    oublier: (id) => appels.push(["oublier", id]),
    voirAValider: () => appels.push(["a-valider"]),
  };
  const c = document.createElement("div");
  rendreMemoire(c, state, actions, { maintenant: MAINTENANT });
  const t = texte(c);
  porte(t, "Ma mémoire", "le titre");
  porte(t, "Travaille au Cerema", "le profil");
  porte(t, "Pas de notification la nuit", "une préférence");
  porte(t, "Faits retenus d’office", "les faits ont leur partie");
  porte(t, "Rien de retenu.", "une partie vide se dit");
  porte(t, "1 proposition attend votre accord", "les propositions en attente");
  porte(t, "12 conversations fichées", "le nombre de fiches");
  porte(texte(ligne(c, "m-3")), "extrait par le code", "d'où vient un fait");
  porte(texte(ligne(c, "m-1")), "validé par vous", "d'où vient le profil");
  porte(texte(ligne(c, "m-1")), "conversation 01234567", "la conversation d'origine, courte");
  for (const mot of ["MCP", "jeton", "artefact", "wikichat", "trigger"]) nePorte(t, mot, `lexique : pas de « ${mot} »`);

  cliquer(bouton(ligne(c, "m-2"), "Corriger"));
  egal(appels.at(-1), ["editer", "m-2"], "Corriger ouvre l'édition");
  cliquer(bouton(ligne(c, "m-2"), "Oublier"));
  egal(appels.at(-1), ["oubli?", "m-2"], "Oublier demande d'abord");
  cliquer(bouton(c, "Voir dans « À valider »"));
  egal(appels.at(-1), ["a-valider"], "les propositions mènent à « À valider »");

  // En édition : un champ, Enregistrer envoie le nouveau texte.
  state.memoire.enEdition = "m-2";
  rendreMemoire(c, state, actions, { maintenant: MAINTENANT });
  const champ = ligne(c, "m-2").querySelector("input");
  verifier(champ && champ.value === "Pas de notification la nuit", "le champ reprend le texte");
  saisir(champ, "Pas de notification entre 22 h et 7 h");
  cliquer(bouton(ligne(c, "m-2"), "Enregistrer"));
  egal(appels.at(-1), ["corriger", "m-2", "Pas de notification entre 22 h et 7 h"], "Enregistrer corrige");

  // Confirmation d'oubli.
  state.memoire.enEdition = null;
  state.memoire.aOublier = "m-3";
  rendreMemoire(c, state, actions, { maintenant: MAINTENANT });
  cliquer(bouton(ligne(c, "m-3"), "Confirmer l’oubli"));
  egal(appels.at(-1), ["oublier", "m-3"], "l'oubli confirmé part");

  // Pas encore lu ; une erreur se dit.
  rendreMemoire(c, { memoire: { charge: false } }, actions);
  porte(texte(c), "Lecture de la mémoire", "en cours de lecture");
  rendreMemoire(c, { memoire: { charge: true, erreur: "wikichat ne répond pas" , donnees: {} } }, actions);
  porte(texte(c), "ne répond pas", "l'erreur se lit");
}

// ── Le contrôleur : par les commandes du catalogue ─────────────────────
{
  const state = {};
  const appels = [];
  const api = {
    executerCommande: async (nom, args) => {
      appels.push([nom, args]);
      if (nom === "atelier_memoire") return { statut: "fait", resultat: DONNEES };
      return { statut: "fait", resultat: {} };
    },
  };
  let rendus = 0;
  const a = createMemoireActions({ state, api, render: () => (rendus += 1) });
  await a.charger();
  verifier(state.memoire.charge && state.memoire.donnees.elements.length === 3, "la mémoire se lit");
  await a.corriger("m-2", "  Pas de notification la nuit, ni le week-end ");
  egal(appels.find((x) => x[0] === "atelier_memoire_corriger"), ["atelier_memoire_corriger", { id: "m-2", texte: "Pas de notification la nuit, ni le week-end" }], "corriger par la commande réservée");
  await a.corriger("m-2", "   ");
  porte(state.memoire.erreur, "Oublier", "un texte vide n'efface pas : il renvoie à Oublier");
  await a.oublier("m-3");
  egal(appels.find((x) => x[0] === "atelier_memoire_oublier"), ["atelier_memoire_oublier", { id: "m-3" }], "oublier par la commande réservée");
  verifier(rendus > 0, "l'écran se redessine");
  egal(origineLisible({ type: "fait", par: "code", source: {} }), "extrait par le code", "un fait sans date");
}

bilan("memoire");
