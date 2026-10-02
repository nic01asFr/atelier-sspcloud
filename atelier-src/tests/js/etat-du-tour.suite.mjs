// L'état du tour est celui de la conversation AFFICHÉE.
//
// Mesuré au banc (agent factice lent) : pendant qu'une conversation A tournait,
// B (au repos) s'ouvrait en « Mettre en file » avec un bouton Arrêter ; le flux
// de A écrivait dans le fil de B ; l'arrêt de B devenait impossible quand A
// finissait. Ce qu'il faut tenir :
//   - « en cours » = son propre flux dans cet onglet, ou un tour lancé ailleurs
//     que dit la liste (`running`) — jamais la conversation d'une autre ;
//   - changer de conversation n'y reporte ni « occupé » ni la file de l'autre.

import { bilan, egal } from "./verifier.mjs";
import { tourDeLaConversation } from "../../mcp_gateway/atelier/web/js/ui/etat-du-tour.js";
import * as S from "../../mcp_gateway/atelier/web/js/state.js";

const liste = [
  { session_id: "A", state: "running" },
  { session_id: "B", state: "idle" },
  { session_id: "C", state: "created" },
];

{
  const t = (o) => tourDeLaConversation({ sessions: liste, busy: false, ...o });
  egal(t({ sessionId: "A" }), { ici: false, ailleurs: true, enCours: true }, "A tourne, lancé ailleurs : en cours, Arrêter possible");
  egal(t({ sessionId: "B" }), { ici: false, ailleurs: false, enCours: false }, "B au repos : pas en cours, même si A tourne");
  egal(t({ sessionId: "C" }).enCours, false, "une conversation neuve n'est pas en cours");
  egal(t({ sessionId: "B", busy: true }), { ici: true, ailleurs: false, enCours: true }, "son propre flux : en cours");
  egal(t({ sessionId: "A", busy: true }).ailleurs, false, "son propre flux et running : ici, pas « ailleurs »");
  egal(t({ sessionId: null }).enCours, false, "pas de conversation ouverte");
  egal(t({ sessionId: "inconnue" }).enCours, false, "une conversation absente de la liste");
  egal(tourDeLaConversation({}).enCours, false, "état vide");
}

{
  const st = { sessionId: "A", busy: true, enFile: [{ id: "m1", texte: "x" }] };
  S.setSessionId(st, "A");
  egal(st.busy, true, "le même identifiant : rien ne change");
  egal(st.enFile.length, 1, "la file reste");
  S.setSessionId(st, "B");
  egal(st.busy, false, "une autre conversation : « occupé » ne la suit pas");
  egal(st.enFile, [], "et la file de l'autre non plus");
  egal(st.sessionId, "B", "l'identifiant a bien changé");
  S.setSessionId(st, null);
  egal(st.sessionId, null, "fermer la conversation");
}

bilan("etat-du-tour");
