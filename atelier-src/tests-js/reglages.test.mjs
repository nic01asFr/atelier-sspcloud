// L'écran Réglages : l'identifiant tiré d'un nom, et le module qui s'importe sans navigateur.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createReglagesActions, identifiantDepuisLeNom, rendreReglages } from "../mcp_gateway/atelier/web/js/views/reglages.js";
import { VIEWS, normalizeView } from "../mcp_gateway/atelier/web/js/state.js";

test("un nom devient un identifiant que l'Atelier accepte", () => {
  const ok = /^[a-z][a-z0-9-]{0,31}$/;
  for (const [nom, attendu] of [
    ["Mon serveur vLLM", "mon-serveur-vllm"],
    ["  Étalab — Albert (test) ", "etalab-albert-test"],
    ["2e fournisseur", "f-2e-fournisseur"],
    ["***", ""],
    ["", ""],
  ]) {
    const id = identifiantDepuisLeNom(nom);
    assert.equal(id, attendu, nom);
    if (id) assert.match(id, ok, nom);
  }
  assert.ok(identifiantDepuisLeNom("a".repeat(80)).length <= 32);
  assert.doesNotMatch(identifiantDepuisLeNom("tiret final " + "x".repeat(40)), /-$/);
});

test("la vue Réglages est une vue de la navigation", () => {
  assert.ok(VIEWS.includes("reglages"));
  assert.equal(normalizeView("Reglages"), "reglages");
  assert.equal(normalizeView("inconnue"), "code");
});

test("les gestes existent et la clé saisie ne reste pas en mémoire après l'envoi", async () => {
  const appels = [];
  const api = {
    lireFournisseurs: async () => ({ fournisseurs: [] }),
    reglerFournisseur: async (id, corps) => {
      appels.push([id, corps]);
      return {};
    },
  };
  const state = {};
  const actions = createReglagesActions({ state, api, render: () => {} });
  for (const nom of ["charger", "actualiser", "ouvrirLAjout", "modifier", "fermerLeFormulaire", "tester", "enregistrer",
    "ouvrirLaCle", "fermerLaCle", "enregistrerLaCle", "demanderRetrait", "retirer"]) {
    assert.equal(typeof actions[nom], "function", nom);
  }
  assert.equal(typeof rendreReglages, "function");

  actions.ouvrirLAjout();
  const f = state.reglages.formulaire;
  Object.assign(f, { id: "mon-vllm", nom: "Mon vLLM", base_url: "https://llm.exemple.fr/v1", cle: "sk-secret-0123456789" });
  f.natifs.add("qwen3-coder");
  await actions.enregistrer();
  assert.deepEqual(appels[0], ["mon-vllm", { nom: "Mon vLLM", base_url: "https://llm.exemple.fr/v1", cle: "sk-secret-0123456789", outils_natifs: ["qwen3-coder"] }]);
  assert.equal(f.cle, "", "la clé est vidée dès l'envoi");
  assert.equal(state.reglages.formulaire, null, "le formulaire se ferme après un succès");
  assert.equal(JSON.stringify(state.reglages).includes("sk-secret"), false, "aucune trace de la clé dans l'état de l'écran");

  actions.ouvrirLaCle("albert");
  state.reglages.cleSaisie = "autre-cle-0123456789";
  await actions.enregistrerLaCle({ id: "albert", nom: "Albert API", base_url: "https://albert.api.etalab.gouv.fr/v1" });
  assert.equal(state.reglages.cleSaisie, "");
  assert.equal(JSON.stringify(state.reglages).includes("autre-cle"), false);
});
