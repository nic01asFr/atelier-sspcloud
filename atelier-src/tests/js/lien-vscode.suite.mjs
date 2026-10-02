// Le lien « VS Code » de la barre de conversation.
//
// Ce qu'il doit tenir (« VS Code ouvre toujours la session Claude courante ») :
//   - il désigne la conversation ouverte, jamais celle d'avant ;
//   - il existe pour l'Assistant comme pour un projet : la porte
//     `/v1/vscode/open` retrouve le dossier et l'identifiant du CLI par la
//     fiche de la conversation ;
//   - sans adresse de code-server, ou sans conversation ouverte, il n'existe pas.

import { bilan, egal, verifier } from "./verifier.mjs";
import { lienVsCode } from "../../mcp_gateway/atelier/web/js/views/code-chat.js";

{
  const projet = lienVsCode({ vscodeUrl: "https://code.exemple", sessionId: "s1", slug: "demo", titre: "/work/projects/demo" });
  egal(projet.hidden, false, "un projet : le lien existe");
  egal(projet.href, "/v1/vscode/open?slug=demo&session=s1", "il désigne la conversation ouverte");
  egal(projet.title, "/work/projects/demo", "le titre dit le dossier");

  const suivante = lienVsCode({ vscodeUrl: "https://code.exemple", sessionId: "s2", slug: "demo" });
  egal(suivante.href, "/v1/vscode/open?slug=demo&session=s2", "une autre conversation, un autre lien");
  egal(suivante.title, "demo", "sans titre, le projet");

  const assistant = lienVsCode({ vscodeUrl: "https://code.exemple", sessionId: "a1", slug: "wikichat-memory", titre: "Assistant" });
  egal(assistant.hidden, false, "l'Assistant : le lien existe aussi");
  egal(assistant.href, "/v1/vscode/open?slug=wikichat-memory&session=a1", "pour sa conversation, pas celle du projet d'avant");
}

{
  const sans = (o) => lienVsCode({ vscodeUrl: "https://code.exemple", sessionId: "s1", slug: "demo", ...o });
  verifier(sans({ vscodeUrl: "" }).hidden, "sans adresse de code-server, pas de lien");
  verifier(sans({ vscodeUrl: undefined }).hidden, "adresse absente : pas de lien");
  verifier(sans({ sessionId: "" }).hidden, "sans conversation ouverte, pas de lien");
  egal(sans({ sessionId: "" }).href, "", "et pas d'adresse périmée");
}

bilan("lien-vscode");
