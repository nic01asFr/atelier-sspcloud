// Les clients distants dans l'onglet Connecteurs : ce que la liste dit.
//
// La liste existe pour une raison précise : avant elle, un client branché sur
// l'Atelier depuis l'extérieur n'était visible nulle part, et la seule façon
// de le débrancher était de renouveler la clé — ce qui coupe tout le reste
// avec. Une liste qui se tromperait sur l'état d'un client ramènerait
// exactement ce défaut, en donnant en plus l'impression d'avoir regardé.
//
// Ce que cette suite tient :
//   - le cas vide dit quoi faire, au lieu de ne rien dire ;
//   - « autorisé » et « détient un jeton » ne sont pas le même fait, et ne
//     doivent pas se confondre : un client autorisé hier dont les jetons sont
//     tombés n'est plus branché, il est seulement déjà connu ;
//   - le bouton agit sur le bon client — avec un seul appel pour toute la
//     liste, un décalage d'indice débrancherait le voisin.

import { cliquer, installerDom, texte } from "./dom-minimal.mjs";
import { bilan, egal, porte, verifier } from "./verifier.mjs";

import { renderClientsDistants } from "../../mcp_gateway/atelier/web/js/views/connectors.js";

installerDom();

function rendre(clients) {
  const body = document.createElement("div");
  const revoques = [];
  renderClientsDistants(
    { clientsDistants: clients },
    { revoquerClientDistant: (c) => revoques.push(c.client_id) },
    body
  );
  return { body, revoques };
}

function lignes(body) {
  // La liste est retrouvée par sa classe, pas par son rang : le titre de la
  // section est posé en `innerHTML`, que ce DOM garde en chaîne sans l'analyser.
  const sec = body.children[0];
  const ul = Array.from(sec.children).find((n) => n.className === "agent-queue");
  return ul.children;
}

// ── Le cas vide ──────────────────────────────────────────────────────────

{
  const { body } = rendre([]);
  porte(
    texte(body),
    "Aucun client branché",
    "sans client, la section le dit"
  );
  porte(
    texte(body),
    "demande votre clé",
    "et dit comment en brancher un — sinon l’écran est un cul-de-sac"
  );
}

// ── Autorisé n'est pas branché ───────────────────────────────────────────

{
  const { body } = rendre([
    {
      client_id: "abc",
      nom: "Claude",
      accorde: true,
      jetons: 0,
      enregistre_le: "2026-09-20 10:00:00",
    },
  ]);
  const ligne = lignes(body)[0];
  porte(texte(ligne), "Claude", "le nom du client s’affiche");
  porte(texte(ligne), "autorisé", "l’accord donné se voit");
  porte(
    texte(ligne),
    "aucun jeton en cours",
    "et l’absence de jeton aussi : autorisé hier ne veut pas dire branché"
  );
  verifier(
    ligne.children[0].className.includes("status-dot-off"),
    "la pastille suit le jeton, pas l’accord"
  );
}

{
  const { body } = rendre([
    { client_id: "abc", nom: "Claude", accorde: true, jetons: 2 },
  ]);
  const ligne = lignes(body)[0];
  porte(texte(ligne), "2 jetons en cours", "le pluriel suit le compte");
  verifier(
    ligne.children[0].className.includes("status-dot-ok"),
    "un client qui détient un jeton est branché"
  );
}

{
  const { body } = rendre([{ client_id: "xyz", nom: "", accorde: false, jetons: 0 }]);
  const ligne = lignes(body)[0];
  porte(
    texte(ligne),
    "enregistré, jamais autorisé",
    "s’enregistrer n’ouvre rien, et la liste ne laisse pas croire l’inverse"
  );
  porte(texte(ligne), "xyz", "sans nom, l’identifiant tient lieu de nom");
}

// ── Le bouton agit sur le bon ────────────────────────────────────────────

{
  const { body, revoques } = rendre([
    { client_id: "premier", nom: "Un", accorde: true, jetons: 1 },
    { client_id: "second", nom: "Deux", accorde: true, jetons: 1 },
    { client_id: "troisieme", nom: "Trois", accorde: false, jetons: 0 },
  ]);
  egal(lignes(body).length, 3, "une ligne par client");
  const deuxieme = lignes(body)[1];
  cliquer(deuxieme.children[2]);
  egal(revoques.join(","), "second", "c’est le client de la ligne qui part");
}

bilan("clients distants");
