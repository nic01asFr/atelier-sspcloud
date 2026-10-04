// « Nouveau projet » : le nom se donne, et se vérifie, avant la création.

import { bilan, egal, verifier } from "./verifier.mjs";
import { LONGUEUR_MAX, nettoyerLeNom, verifierLeNom } from "../../mcp_gateway/atelier/web/js/ui/nouveau-projet.js";

const projets = [
  { slug: "carte", title: "Carte des écoles" },
  { slug: "depth-models", title: "" },
  { slug: "ancien", title: "Atlas", archived: true },
];

verifier("un nom vide ou d'espaces n'est pas un nom", () => {
  egal(verifierLeNom("", projets), "Donnez un nom au projet.");
  egal(verifierLeNom("   ", projets), "Donnez un nom au projet.");
  egal(verifierLeNom(undefined, projets), "Donnez un nom au projet.");
});

verifier("un nom libre est accepté", () => {
  egal(verifierLeNom("Atlas des collèges", projets), "");
});

verifier("un nom déjà pris est refusé, sans tenir compte des accents ni de la casse", () => {
  egal(verifierLeNom("carte des ECOLES", projets).startsWith("Un projet porte déjà ce nom"), true);
  egal(verifierLeNom("Carte des écoles", projets).length > 0, true);
});

verifier("un projet sans titre compte sous son identifiant", () => {
  egal(verifierLeNom("Depth Models", projets), "", "le slug « depth-models » n'est pas le titre « Depth Models »");
  egal(verifierLeNom("depth-models", projets).length > 0, true);
});

verifier("le nom d'un projet rangé reste pris", () => {
  egal(verifierLeNom("atlas", projets).length > 0, true);
});

verifier("un nom trop long est refusé", () => {
  egal(verifierLeNom("x".repeat(LONGUEUR_MAX + 1), projets).includes("trop long"), true);
  egal(verifierLeNom("x".repeat(LONGUEUR_MAX), projets), "");
});

verifier("les espaces sont resserrés avant tout", () => {
  egal(nettoyerLeNom("  Atlas   des \n écoles "), "Atlas des écoles");
  egal(verifierLeNom("  Carte   des  écoles ", projets).length > 0, true);
});

bilan();
