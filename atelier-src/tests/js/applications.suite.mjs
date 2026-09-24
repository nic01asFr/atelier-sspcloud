// Le panneau « Applications » d'un projet.
//
// Ce qu'il doit tenir, dans l'ordre où ça ferait mal :
//   - un journal est du texte : `<script>` écrit par une application reste des
//     caractères, il ne devient jamais un élément de la page de l'Atelier ;
//   - « Ouvrir » est un lien vers la route de l'Atelier qui renvoie vers
//     l'hôte des applications — jamais vers un port, jamais sans hôte ;
//   - Démarrer / Arrêter selon l'état, puis le panneau se recharge ;
//   - l'index du dossier artifacts/ garde sa ligne : le panneau remplace le lien ;
//   - un artefact autonome s'ouvre sans se démarrer.

import { berceau, cliquer, html, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import { rendrePanneauApplications } from "../../mcp_gateway/atelier/web/js/views/applications.js";

function actionsNotees() {
  const appels = [];
  return {
    appels,
    demarrer: async (nom) => appels.push(["demarrer", nom]),
    arreter: async (nom) => appels.push(["arreter", nom]),
    journal: async (nom) => {
      appels.push(["journal", nom]);
      return "<script>alert('vol')</script>\nprête (pid 12)";
    },
    copier: async (t) => appels.push(["copier", t]),
    recharger: async () => appels.push(["recharger"]),
  };
}

const FICHES = [
  {
    nom: "voix",
    titre: "STT & TTS",
    mode: "serveur",
    auteur: "nouveau-projet-2-voix",
    etat: "arrete",
    raison: "",
    url: "https://apps.test/demo/voix/",
    ouvrir: "/v1/apps/demo/voix/ouvrir",
  },
  {
    nom: "carte",
    titre: "Carte",
    mode: "serveur",
    etat: "pret",
    raison: "",
    url: "https://apps.test/demo/carte/",
    ouvrir: "/v1/apps/demo/carte/ouvrir",
  },
  { nom: "rapport", titre: "rapport", mode: "autonome", etat: "statique", url: "https://apps.test/demo/rapport/", ouvrir: "/v1/apps/demo/rapport/ouvrir" },
  { nom: "casse", titre: "casse", mode: "invalide", etat: "invalide", erreur: "<b>port</b> : le champ port n'existe pas", url: "", ouvrir: "" },
];

function ligne(racine, nom) {
  return racine.querySelectorAll(".apps-ligne").find((l) => l.dataset.app === nom);
}

function boutonNomme(racine, libelle) {
  return racine.querySelectorAll("button").find((b) => b.textContent === libelle);
}

async function attendre() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

// ── Avec hôte des applications ──────────────────────────────────────────
{
  const conteneur = berceau();
  const actions = actionsNotees();
  rendrePanneauApplications(
    conteneur,
    { slug: "demo", expose: true, artefacts: FICHES, artefactsUrl: "/v1/artifacts/demo/" },
    actions,
  );

  const artefacts = conteneur.querySelectorAll(".apps-ligne")[0];
  porte(texte(artefacts), "Index", "l'index du dossier artifacts/ garde sa ligne");
  egal(artefacts.querySelector("a").getAttribute("href"), "/v1/artifacts/demo/", "lien des artefacts");

  const voix = ligne(conteneur, "voix");
  const ouvrir = voix.querySelector("a");
  egal(ouvrir.getAttribute("href"), "/v1/apps/demo/voix/ouvrir", "Ouvrir passe par l'Atelier");
  egal(ouvrir.getAttribute("rel"), "noopener", "Ouvrir sans opener");
  porte(texte(voix), "arrêtée", "état lisible");
  porte(texte(voix), "serveur", "mode lisible");
  porte(texte(voix), "nouveau-projet-2-voix", "auteur lisible");

  const rapport = ligne(conteneur, "rapport");
  egal(rapport.querySelector("a").getAttribute("href"), "/v1/apps/demo/rapport/ouvrir", "un artefact autonome s'ouvre aussi");
  egal(boutonNomme(rapport, "Démarrer"), undefined, "un artefact autonome ne se démarre pas");
  porte(texte(rapport), "autonome", "mode autonome lisible");

  cliquer(boutonNomme(voix, "Démarrer"));
  await attendre();
  egal(actions.appels.slice(0, 2), [["demarrer", "voix"], ["recharger"]], "Démarrer puis recharger");

  const carte = ligne(conteneur, "carte");
  verifier(boutonNomme(carte, "Arrêter"), "une application prête s'arrête");
  cliquer(boutonNomme(carte, "Arrêter"));
  await attendre();
  porte(JSON.stringify(actions.appels), '["arreter","carte"]', "Arrêter appelé");

  cliquer(boutonNomme(voix, "Journal"));
  await attendre();
  const journal = conteneur.querySelector(".apps-journal");
  verifier(journal.hidden === false, "le journal s'affiche");
  porte(texte(journal), "<script>alert('vol')</script>", "le journal est rendu tel quel, en texte");
  egal(journal.querySelectorAll("script").length, 0, "aucun élément script n'est créé");
  nePorte(html(journal), "<script>alert", "le journal n'est jamais interprété comme du HTML");

  cliquer(boutonNomme(voix, "Copier l'URL"));
  await attendre();
  porte(JSON.stringify(actions.appels), '["copier","https://apps.test/demo/voix/"]', "copier l'URL publique");

  const casse = ligne(conteneur, "casse");
  porte(texte(casse), "manifeste invalide", "un manifeste faux se voit");
  porte(texte(casse), "<b>port</b>", "l'erreur est du texte, balises comprises");
  egal(casse.querySelectorAll("b").length, 0, "l'erreur ne crée pas d'élément");
  const ouvrirCasse = boutonNomme(casse, "Ouvrir");
  verifier(ouvrirCasse && ouvrirCasse.hasAttribute("disabled"), "un manifeste faux ne s'ouvre pas");
  egal(boutonNomme(casse, "Démarrer"), undefined, "ni ne se démarre");
}

// ── Sans hôte des applications ──────────────────────────────────────────
{
  const conteneur = berceau();
  const sansHote = FICHES.map((f) => ({ ...f, url: "", ouvrir: "" }));
  rendrePanneauApplications(
    conteneur,
    { slug: "demo", expose: false, artefacts: sansHote, artefactsUrl: "/v1/artifacts/demo/" },
    actionsNotees(),
  );
  porte(texte(conteneur), "Pas d'hôte des applications", "l'installation de secours le dit");
  const voix = ligne(conteneur, "voix");
  egal(voix.querySelector("a"), null, "pas de lien Ouvrir sans hôte");
  verifier(boutonNomme(voix, "Ouvrir").hasAttribute("disabled"), "Ouvrir grisé");
  verifier(boutonNomme(voix, "Démarrer"), "on peut toujours démarrer");
  egal(boutonNomme(voix, "Copier l'URL"), undefined, "pas d'URL à copier");
}

// ── Aucun manifeste ─────────────────────────────────────────────────────
{
  const conteneur = berceau();
  rendrePanneauApplications(
    conteneur,
    { slug: "demo", expose: true, artefacts: [], artefactsUrl: "/v1/artifacts/demo/" },
    actionsNotees(),
  );
  porte(texte(conteneur), "artifacts/<nom>/", "dit où créer un artefact");
}

bilan("applications");
