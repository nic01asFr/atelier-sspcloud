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

import { rendrePanneauApplications, SUIVI_DES_ETATS } from "../../mcp_gateway/atelier/web/js/views/applications.js";

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

// ── L'état suit le superviseur : plus de « démarre… » figé ───────────────
//
// Essai du 26/09 : après « Démarrer », l'application était prête en 1 s
// (journal du superviseur : `prête`), mais le panneau affichait encore
// « démarre… » plus de 90 s après. La route de démarrage rend la main en
// `demarrage`, et rien ne relisait l'état ensuite. Tant qu'une fiche est en
// transition, le panneau relit ; il s'arrête dès que tout est stable.

/** Une horloge à la main : les relectures planifiées, et le temps qui passe. */
function horloge() {
  const h = { t: 0, prevues: [], annulees: 0 };
  h.planifier = (f, ms) => {
    const minuterie = { f, ms, faite: false, annulee: false };
    h.prevues.push(minuterie);
    return minuterie;
  };
  h.annuler = (m) => {
    m.annulee = true;
    h.annulees += 1;
  };
  h.maintenant = () => h.t;
  h.enAttente = () => h.prevues.filter((m) => !m.faite && !m.annulee);
  h.avancer = () => {
    const [m] = h.enAttente();
    if (!m) return false;
    h.t += m.ms;
    m.faite = true;
    m.f();
    return true;
  };
  return h;
}

/** Un superviseur factice : l'état qu'il rend à chaque relecture. */
function panneauSuivi(etats, h, conteneur = berceau()) {
  const lectures = { n: 0 };
  const rendre = () => {
    const etat = etats[Math.min(lectures.n, etats.length - 1)];
    lectures.n += 1;
    rendrePanneauApplications(
      conteneur,
      {
        slug: "demo", expose: true, artefactsUrl: "/v1/artifacts/demo/",
        artefacts: [{ nom: "voix", titre: "Voix", mode: "serveur", etat, url: "", ouvrir: "/v1/apps/demo/voix/ouvrir" }],
      },
      {
        demarrer: async () => {}, arreter: async () => {}, journal: async () => "", copier: async () => {},
        recharger: async () => rendre(),
        planifier: h.planifier, annuler: h.annuler, maintenant: h.maintenant,
      },
    );
  };
  rendre();
  return { conteneur, lectures };
}

{
  const h = horloge();
  const { conteneur, lectures } = panneauSuivi(["demarrage", "demarrage", "pret"], h);
  porte(texte(ligne(conteneur, "voix")), "démarre…", "juste après « Démarrer », l'état est transitoire");
  egal(h.enAttente().length, 1, "une relecture est prévue tant que l'application démarre");
  verifier(h.enAttente()[0].ms <= 1000, "et elle est courte : une seconde au plus");

  h.avancer();
  porte(texte(ligne(conteneur, "voix")), "démarre…", "toujours en cours à la deuxième lecture");
  egal(h.enAttente().length, 1, "on relit encore");

  h.avancer();
  porte(texte(ligne(conteneur, "voix")), "prête", "le panneau suit : l'application est dite prête");
  nePorte(texte(ligne(conteneur, "voix")), "démarre", "et plus « démarre… »");
  egal(h.enAttente().length, 0, "l'état est stable : on cesse de relire");
  egal(lectures.n, 3, "trois lectures en tout, pas une de plus");
  verifier(boutonNomme(ligne(conteneur, "voix"), "Arrêter"), "le geste suit l'état : « Arrêter »");
}

{
  // L'arrêt aussi est transitoire ; un état stable dès le départ ne relit pas.
  const h = horloge();
  panneauSuivi(["arret", "arrete"], h);
  egal(h.enAttente().length, 1, "« s'arrête… » se relit");
  h.avancer();
  egal(h.enAttente().length, 0, "« arrêtée » est stable : fini");

  const calme = horloge();
  panneauSuivi(["pret"], calme);
  egal(calme.prevues.length, 0, "une application déjà prête ne déclenche aucune relecture");
}

{
  // Une seule relecture en attente par panneau, quel que soit le nombre de
  // rendus : sinon chaque geste en ajouterait une, et les lectures
  // s'emballeraient.
  const h = horloge();
  const conteneur = berceau();
  panneauSuivi(["demarrage"], h, conteneur);
  panneauSuivi(["demarrage"], h, conteneur);
  panneauSuivi(["demarrage"], h, conteneur);
  egal(h.enAttente().length, 1, "trois rendus, une seule relecture en attente");
  egal(h.annulees, 2, "les précédentes sont annulées");
}

{
  // Un panneau qu'on ne regarde plus ne relit pas.
  const h = horloge();
  const { conteneur, lectures } = panneauSuivi(["demarrage"], h);
  conteneur.hidden = true;
  h.avancer();
  egal(lectures.n, 1, "caché, le panneau ne relit pas l'état");
  egal(h.enAttente().length, 0, "et ne reprogramme rien");
}

{
  // Un état qui ne bouge plus n'est pas relu indéfiniment : au-delà du plus
  // long démarrage déclarable, on s'arrête (le superviseur l'aurait mis en
  // échec, et « Journal » dit pourquoi).
  const h = horloge();
  const { lectures } = panneauSuivi(["demarrage"], h);
  let tours = 0;
  while (h.avancer() && tours < 10000) tours += 1;
  verifier(h.t > SUIVI_DES_ETATS.dureeMaxMs, "on a relu jusqu'à la limite");
  verifier(tours < 10000, "puis on s'est arrêté");
  verifier(lectures.n < 400, "sans marteler le service (" + lectures.n + " lectures)");
}

bilan("applications");
