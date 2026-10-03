// La liste « Services du projet » dit ce que l'agent reçoit.
//
// Constat du 03/10 : la fenêtre cochait Onyxia pour `depth-models`, alors que
// l'agent n'avait aucun outil Onyxia (pas de déploiement déclaré). Ce qu'il faut tenir :
//   - un service livré se coche comme avant ;
//   - un service choisi mais non livré est éteint, désactivé, et dit pourquoi ;
//   - le choix déjà écrit se garde à l'enregistrement, pour le jour où il est livré ;
//   - l'accès aux outils de l'Atelier reste fixe.

import { bilan, egal, verifier } from "./verifier.mjs";
import { indiceDuService, optionsDesServices } from "../../mcp_gateway/atelier/web/js/ui/services-du-projet.js";

const lignes = [
  { id: "atelier", name: "Accès aux outils", fixe: true, active: true, system: true, group: "Accès aux outils", scope: [] },
  { id: "Onyxia", name: "Onyxia", active: true, distribue: false, par_deploiement: true, raison: "s'ouvre par le déploiement du projet, et aucun n'est déclaré", system: false, group: "Onyxia", scope: [] },
  { id: "chrome-devtools-mcp", name: "Navigateur web", active: true, system: true, group: "Navigateur web", scope: [] },
  { id: "n8n", name: "n8n", active: true, distribue: false, echec_authentification: 401, raison: "refusé à l'authentification (401) : à reconnecter dans Connecteurs", scope: [] },
  { id: "qgis", name: "qgis", active: false, id_technique: "qgis", scope: [] },
  { id: "datagouv", name: "datagouv", active: true, distribue: true, id_technique: "datagouv", scope: [] },
];

{
  const { options, retenus } = optionsDesServices(lignes);
  const par = Object.fromEntries(options.map((o) => [o.value, o]));
  egal([par.atelier.checked, par.atelier.disabled], [true, true], "l'accès aux outils reste fixe");
  egal([par.Onyxia.checked, par.Onyxia.disabled], [false, true], "Onyxia sans déploiement : éteint et désactivé");
  verifier(par.Onyxia.hint.includes("déploiement"), "la ligne dit pourquoi");
  egal([par.n8n.checked, par.n8n.disabled], [false, true], "un refus d'authentification aussi");
  verifier(par.n8n.hint.includes("reconnecter"), "et dit quoi faire");
  egal([par.datagouv.checked, par.datagouv.disabled], [true, false], "un service livré se coche comme avant");
  egal([par.qgis.checked, par.qgis.disabled], [false, false], "un service non choisi reste décoché et libre");
  egal([par["chrome-devtools-mcp"].checked, par["chrome-devtools-mcp"].disabled], [true, false], "un service du socle aussi");
  egal(retenus.sort(), ["Onyxia", "n8n"], "le choix des non-livrés se garde pour plus tard");
}

{
  // Livré (déploiement déclaré) : la case est active et cochée.
  const { options, retenus } = optionsDesServices([{ id: "Onyxia", name: "Onyxia", active: true, distribue: true, par_deploiement: true, raison: "borné au déploiement du projet", scope: [] }]);
  egal([options[0].checked, options[0].disabled], [true, false], "Onyxia livré : coché");
  egal(retenus, [], "rien à retenir");
  verifier(indiceDuService({ id: "x", distribue: false }) === "non livré aux conversations de ce projet", "sans raison, une phrase par défaut");
  egal(optionsDesServices(null), { options: [], retenus: [] }, "pas de liste");
}

bilan("services-du-projet");
