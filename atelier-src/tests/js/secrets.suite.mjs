// « Secrets » dans Réglages : coller la valeur d'un secret une fois, la changer, retirer un secret.
//
// Écrit contre le contrat de `/v1/secrets`, avec une fausse route :
//   - la liste montre des noms, la date, les connecteurs qui s'en servent : jamais une valeur ;
//   - la valeur partie n'est plus en mémoire de l'écran (champ vidé dès l'envoi), ni dans un message ;
//   - changer la valeur d'un secret dit quels connecteurs l'ont reçue ;
//   - un secret utilisé ne se retire pas ; `github_token` renvoie à la section GitHub ;
//   - un refus du service se lit, sans la valeur, et le nom reste à l'écran.

import { berceau, cliquer, saisir, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

const { createSecretsActions, rendreSecrets, nomPlausible } = await import("../../mcp_gateway/atelier/web/js/views/secrets.js");

const VALEUR = "jeton-fictif-0123456789abcdef-NE-DOIT-JAMAIS-RESTER";

async function attendre() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

function fausseRoute() {
  const appels = [];
  let liste = [
    { nom: "github_token", protege: true, modifie: "2026-10-23T14:24:00+00:00", utilise_par: ["github"] },
    { nom: "grist_cle", protege: true, modifie: "2026-10-23T10:00:00+00:00", utilise_par: ["grist"] },
    { nom: "provisoire", protege: false, modifie: "", utilise_par: [] },
  ];
  return {
    appels,
    listerSecrets: async () => ({ secrets: liste, dossier: "/work/.secrets" }),
    ecrireSecret: async (nom, valeur) => {
      appels.push(["ecrire", nom, valeur]);
      if (nom === "refuse") throw new Error("« refuse » est réservé à l'Atelier : on n'y écrit pas depuis cet écran.");
      const existe = liste.some((l) => l.nom === nom);
      if (!existe) liste = [...liste, { nom, protege: true, modifie: "", utilise_par: [] }];
      return { nom, protege: true, nouveau: !existe, renouveles: nom === "grist_cle" ? ["grist"] : [] };
    },
    retirerSecret: async (nom) => {
      appels.push(["retirer", nom]);
      liste = liste.filter((l) => l.nom !== nom);
      return { nom, retire: true };
    },
  };
}

function monter() {
  const state = { reglages: {} };
  const route = fausseRoute();
  const parent = berceau();
  const rendre = () => {
    parent.innerHTML = "";
    rendreSecrets(parent, state, actions);
  };
  const actions = createSecretsActions({ state, api: route, render: rendre });
  return { state, route, parent, actions, rendre };
}

const bouton = (parent, libelle) => parent.querySelectorAll("button").find((b) => texte(b) === libelle);
const champ = (parent, nom) => parent.querySelectorAll("input").find((i) => i.name === nom);

// ── La liste : des noms, jamais des valeurs ─────────────────────────────
{
  const { parent, actions, rendre } = monter();
  rendre();
  porte(texte(parent), "Lecture des secrets", "avant lecture, l'écran le dit");
  await actions.charger();
  const t = texte(parent);
  porte(t, "grist_cle", "un secret est listé par son nom");
  porte(t, "utilisé par grist", "on voit quel connecteur s'en sert");
  porte(t, "aucun connecteur ne l’utilise", "un secret inutilisé le dit");
  porte(t, "à protéger : chmod 600", "un fichier trop ouvert est signalé");
  porte(t, "Se change dans la section GitHub", "github_token renvoie à la section GitHub");
  const lignes = parent.querySelectorAll("li");
  const ligneGithub = lignes.find((l) => texte(l).includes("github_token"));
  verifier(!ligneGithub.querySelectorAll("button").length, "github_token n'a ni « Changer » ni « Retirer » ici");
  const retraitGrist = lignes.find((l) => texte(l).includes("grist_cle")).querySelectorAll("button").find((b) => texte(b) === "Retirer");
  verifier(retraitGrist.disabled, "un secret utilisé ne se retire pas");
  porte(retraitGrist.title, "Utilisé par grist", "et la raison est dite");
}

// ── Créer un secret : la valeur part une fois et ne reste nulle part ────
{
  const { state, route, parent, actions, rendre } = monter();
  await actions.charger();
  const envoi = () => bouton(parent, "Enregistrer");
  verifier(envoi().disabled, "rien à envoyer sans nom ni valeur");
  saisir(champ(parent, "nom"), "mon secret");  // espace : pas un nom valide
  saisir(champ(parent, "valeur"), VALEUR);
  verifier(envoi().disabled, "un nom avec un espace grise le bouton");
  saisir(champ(parent, "nom"), "n8n_jeton");
  verifier(!envoi().disabled, "un nom valide et une valeur : le bouton s'active");
  egal(champ(parent, "valeur").type, "password", "la valeur se saisit masquée");
  await actions.enregistrer();
  await attendre();
  egal(route.appels.at(-1), ["ecrire", "n8n_jeton", VALEUR], "la valeur part avec le nom, une seule fois");
  porte(texte(parent), "Secret « n8n_jeton » créé", "l'écran dit ce qui s'est passé");
  nePorte(texte(parent), VALEUR, "la valeur n'apparaît jamais à l'écran");
  nePorte(JSON.stringify(state), VALEUR, "ni dans la mémoire de l'écran");
  egal(champ(parent, "valeur").value, "", "le champ est vide après l'envoi");
  porte(texte(parent), "n8n_jeton", "le nouveau secret est dans la liste");
}

// ── Changer la valeur : les connecteurs concernés sont nommés ───────────
{
  const { route, parent, actions } = monter();
  await actions.charger();
  const ligne = parent.querySelectorAll("li").find((l) => texte(l).includes("grist_cle"));
  cliquer(ligne.querySelectorAll("button").find((b) => texte(b) === "Changer la valeur"));
  egal(champ(parent, "nom").value, "grist_cle", "le nom est repris");
  verifier(champ(parent, "nom").readOnly, "et ne se change pas : on change la valeur de CE secret");
  saisir(champ(parent, "valeur"), VALEUR);
  await actions.enregistrer();
  await attendre();
  porte(texte(parent), "Secret « grist_cle » mis à jour", "un secret existant est « mis à jour »");
  porte(texte(parent), "Connecteur mis à jour avec la nouvelle valeur : grist", "les connecteurs qui l'ont reçue sont nommés");
  nePorte(texte(parent), VALEUR, "sans la valeur");
  egal(route.appels.at(-1), ["ecrire", "grist_cle", VALEUR], "un seul appel");
}

// ── Un refus se lit, sans la valeur, et le nom reste ────────────────────
{
  const { state, parent, actions } = monter();
  await actions.charger();
  saisir(champ(parent, "nom"), "refuse");
  saisir(champ(parent, "valeur"), VALEUR);
  await actions.enregistrer();
  await attendre();
  porte(texte(parent), "réservé à l'Atelier", "le refus du service se lit");
  nePorte(texte(parent), VALEUR, "sans citer la valeur");
  nePorte(JSON.stringify(state), VALEUR, "ni la garder");
  egal(champ(parent, "nom").value, "refuse", "le nom reste, la valeur est à ressaisir");
  egal(champ(parent, "valeur").value, "", "le champ valeur est vide");
}

// ── Retirer : confirmation, puis le secret disparaît ────────────────────
{
  const { route, parent, actions } = monter();
  await actions.charger();
  const ligne = () => parent.querySelectorAll("li").find((l) => texte(l).includes("provisoire"));
  cliquer(ligne().querySelectorAll("button").find((b) => texte(b) === "Retirer"));
  porte(texte(ligne()), "Confirmer : retirer", "un retrait demande confirmation");
  cliquer(ligne().querySelectorAll("button").find((b) => texte(b) === "Garder"));
  verifier(!route.appels.some((a) => a[0] === "retirer"), "« Garder » ne retire rien");
  cliquer(ligne().querySelectorAll("button").find((b) => texte(b) === "Retirer"));
  cliquer(ligne().querySelectorAll("button").find((b) => texte(b) === "Confirmer : retirer"));
  await attendre();
  egal(route.appels.at(-1), ["retirer", "provisoire"], "le retrait part avec le seul nom");
  porte(texte(parent), "Secret « provisoire » retiré", "l'écran le dit");
}

// ── Le nom plausible ────────────────────────────────────────────────────
{
  for (const bon of ["grist_api_key", "n8n.jeton", "A1", "cle-2"]) verifier(nomPlausible(bon), `« ${bon} » est plausible`);
  for (const mauvais of ["", " ", "mon secret", "a/b", "..", "a..b", ".cache", "x".repeat(65)]) verifier(!nomPlausible(mauvais), `« ${mauvais} » ne l'est pas`);
}

bilan("secrets");
