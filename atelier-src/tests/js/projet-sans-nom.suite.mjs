// « Nouveau projet » : le projet sans nom se nomme au premier message, et ne s'accumule pas.

import { bilan, egal, verifier } from "./verifier.mjs";
import {
  estSansNom,
  projetVideReutilisable,
  titreAuPremierMessage,
} from "../../mcp_gateway/atelier/web/js/ui/projet-sans-nom.js";
import { projectNameFromMessage } from "../../mcp_gateway/atelier/web/js/state.js";

verifier("seul le nom de départ est « sans nom »", () => {
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "Projet sans nom" }), true);
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "" }), true);
  egal(estSansNom({ slug: "projet-sans-nom-8", title: "BigStarter" }), false);
  egal(estSansNom({ slug: "carte", title: "" }), false);
  egal(estSansNom(null), false);
});

verifier("le premier message nomme le projet sans nom", () => {
  const projet = { slug: "projet-sans-nom-8", title: "Projet sans nom" };
  egal(titreAuPremierMessage(projet, "Je veux une carte des écoles de Montpellier", projectNameFromMessage),
    "Je veux une carte des écoles de");
});

verifier("un nom choisi par la personne ne se touche jamais", () => {
  egal(titreAuPremierMessage({ slug: "x", title: "Mon atlas" }, "bonjour", projectNameFromMessage), "");
});

verifier("un message vide ne renomme pas", () => {
  egal(titreAuPremierMessage({ slug: "p", title: "Projet sans nom" }, "   ", projectNameFromMessage), "");
});

verifier("« Nouveau projet » reprend le projet sans nom vide", () => {
  const state = {
    projects: [
      { slug: "projet-sans-nom", title: "Projet sans nom" },
      { slug: "projet-sans-nom-2", title: "Projet sans nom" },
      { slug: "carte", title: "Carte" },
    ],
    sessions: [{ slug: "projet-sans-nom" }],
  };
  egal(projetVideReutilisable(state).slug, "projet-sans-nom-2", "le premier est occupé, le deuxième est libre");
});

verifier("rien à reprendre : un projet rangé ou occupé ne l'est pas", () => {
  const state = {
    projects: [
      { slug: "projet-sans-nom", title: "Projet sans nom", archived: true },
      { slug: "projet-sans-nom-2", title: "Projet sans nom" },
    ],
    sessions: [{ slug: "projet-sans-nom-2" }],
  };
  egal(projetVideReutilisable(state), null);
});

bilan();
