// L'écran GitHub de Réglages : le filtre des dépôts, et des gestes qui ne gardent jamais le jeton.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createGithubActions, filtrerLesDepots, ilYA, rendreGithub } from "../mcp_gateway/atelier/web/js/views/github.js";
import { createReglagesActions } from "../mcp_gateway/atelier/web/js/views/reglages.js";

const JETON = "github_pat_A1b2C3d4E5f6G7h8A1b2C3d4E5f6G7h8";

const DEPOTS = [
  { nom: "octo/projet", description: "Cartes des sentiers", prive: true },
  { nom: "octo/autre", description: "", prive: false },
  { nom: "asso/carto", description: "Une carte", prive: false },
];

test("filtrer : par nom ou description, sans casse, avec un plafond qui se dit", () => {
  assert.deepEqual(filtrerLesDepots(DEPOTS, "").visibles.map((d) => d.nom), ["octo/projet", "octo/autre", "asso/carto"]);
  assert.deepEqual(filtrerLesDepots(DEPOTS, "CARTE").visibles.map((d) => d.nom), ["octo/projet", "asso/carto"]);
  assert.deepEqual(filtrerLesDepots(DEPOTS, "octo/a").visibles.map((d) => d.nom), ["octo/autre"]);
  const beaucoup = Array.from({ length: 50 }, (_, i) => ({ nom: `o/d${i}`, description: "" }));
  const f = filtrerLesDepots(beaucoup, "", 40);
  assert.equal(f.visibles.length, 40);
  assert.equal(f.masques, 10);
  assert.equal(f.total, 50);
  assert.deepEqual(filtrerLesDepots(null, "x"), { visibles: [], masques: 0, total: 0 });
});

test("ilYA : à la journée près, et vide si la date est illisible", () => {
  const maintenant = Date.parse("2026-10-13T12:00:00Z");
  assert.equal(ilYA("2026-10-13T08:00:00Z", maintenant), "aujourd’hui");
  assert.equal(ilYA("2026-10-12T08:00:00Z", maintenant), "hier");
  assert.equal(ilYA("2026-10-10T08:00:00Z", maintenant), "il y a 3 jours");
  assert.equal(ilYA("2026-07-01T08:00:00Z", maintenant), "il y a 3 mois");
  assert.equal(ilYA("2024-01-01T08:00:00Z", maintenant), "il y a 2 ans");
  assert.equal(ilYA("", maintenant), "");
  assert.equal(ilYA("pas une date", maintenant), "");
});

test("les gestes existent et le jeton saisi ne reste pas en mémoire après l'envoi", async () => {
  const appels = [];
  const api = {
    lireGithub: async () => ({ connecte: false }),
    connecterGithub: async (corps) => {
      appels.push(corps);
      return { connecte: true, login: "octo", type: "fine-grained" };
    },
    lireDepotsGithub: async () => ({ depots: DEPOTS, tronque: false }),
  };
  const state = {};
  const actions = createGithubActions({ state, api, render: () => {} });
  for (const nom of ["charger", "actualiser", "connecter", "demanderDeconnexion", "deconnecter", "chercher", "ouvrir"]) {
    assert.equal(typeof actions[nom], "function", nom);
  }
  assert.equal(typeof rendreGithub, "function");

  await actions.charger();
  assert.equal(state.reglages.github.etat.connecte, false);
  state.reglages.github.jeton = JETON;
  await actions.connecter();
  assert.deepEqual(appels, [{ jeton: JETON }]);
  assert.equal(state.reglages.github.jeton, "", "le jeton est vidé dès l'envoi");
  assert.equal(state.reglages.github.etat.login, "octo");
  assert.equal(state.reglages.github.depots.length, 3);
  assert.equal(JSON.stringify(state).includes(JETON), false, "aucune trace du jeton dans l'état de l'écran");
});

test("un jeton refusé se lit tel quel et ne laisse rien derrière", async () => {
  const api = {
    connecterGithub: async () => {
      throw new Error("GitHub refuse ce jeton : il est invalide, expiré ou révoqué.");
    },
  };
  const state = {};
  const actions = createGithubActions({ state, api, render: () => {} });
  state.reglages = { github: { jeton: JETON, etat: { connecte: false } } };
  await actions.connecter();
  const g = state.reglages.github;
  assert.match(g.erreur, /invalide, expiré ou révoqué/);
  assert.equal(g.jeton, "");
  assert.equal(g.etat.connecte, false);
  assert.equal(JSON.stringify(state).includes(JETON), false);
});

test("ouvrir un dépôt passe par la commande de l'Assistant, puis va au projet", async () => {
  const commandes = [];
  const allers = [];
  const api = {
    executerCommande: async (nom, args) => {
      commandes.push([nom, args]);
      return { statut: "fait", resultat: { projet: "projet" } };
    },
    lireDepotsGithub: async () => ({ depots: DEPOTS }),
  };
  const state = {};
  const actions = createGithubActions({ state, api, render: () => {}, aller: (a) => allers.push(a) });
  await actions.ouvrir("octo/projet");
  assert.deepEqual(commandes, [["atelier_projet_depuis_github", { depot: "octo/projet" }]]);
  assert.deepEqual(allers, ["/?slug=projet"]);
  assert.match(state.reglages.github.message, /projet « projet »/);
  assert.equal(state.reglages.github.ouverture, "");
});

test("ouvrir un dépôt qui échoue dit pourquoi et ne va nulle part", async () => {
  const allers = [];
  const api = {
    executerCommande: async () => {
      throw new Error("Ce dépôt est trop gros pour s'ouvrir d'ici (800 Mo ; au plus 500 Mo).");
    },
  };
  const state = {};
  const actions = createGithubActions({ state, api, render: () => {}, aller: (a) => allers.push(a) });
  await actions.ouvrir("octo/enorme");
  assert.match(state.reglages.github.erreur, /trop gros/);
  assert.deepEqual(allers, []);
  assert.equal(state.reglages.github.ouverture, "");
});

test("se déconnecter demande d'abord confirmation, puis vide la liste", async () => {
  const api = { deconnecterGithub: async () => ({ connecte: false }) };
  const state = { reglages: { github: { etat: { connecte: true }, depots: DEPOTS } } };
  const actions = createGithubActions({ state, api, render: () => {} });
  actions.demanderDeconnexion(true);
  assert.equal(state.reglages.github.confirmerDeconnexion, true);
  await actions.deconnecter();
  assert.equal(state.reglages.github.etat.connecte, false);
  assert.deepEqual(state.reglages.github.depots, []);
  assert.equal(state.reglages.github.confirmerDeconnexion, false);
});

test("Réglages embarque les gestes GitHub", () => {
  const actions = createReglagesActions({ state: {}, api: {}, render: () => {} });
  assert.equal(typeof actions.github.ouvrir, "function");
});
