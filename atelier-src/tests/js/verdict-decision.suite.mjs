// Une autorisation tranchée rejoint le geste qui l'a demandée.
//
// Constat du 03/10 (Chrome sur le pod) : une demande trouvée déjà posée à
// l'ouverture est une carte à part, en bas ; tranchée, elle disparaissait sans
// que la ligne de l'outil dise « autorisé ». Ce qu'il faut tenir :
//   - la carte se retire, et le verdict se pose sur l'outil du fil ;
//   - sans outil dans le fil, ou pour une question, rien ne bouge ;
//   - un verdict inconnu ne change rien ;
//   - la ligne de l'étape porte ce verdict.

import { bilan, egal, verifier } from "./verifier.mjs";
import { appliquerLesVerdicts, idDeLOutil, rattacherLeVerdict, verdictDeLaCause } from "../../mcp_gateway/atelier/web/js/ui/verdict-decision.js";
import * as S from "../../mcp_gateway/atelier/web/js/state.js";
import { regrouperTour } from "../../mcp_gateway/atelier/web/js/ui/etapes.js";

const outil = (id) => ({ type: "tool", id, name: "Bash", input: { command: "ls" }, status: "done" });
const carte = (rid, tid, genre = "autorisation") => ({ type: "decision", etat: "en_attente", demande: { request_id: rid, tool_use_id: tid, genre } });

{
  egal(verdictDeLaCause("allow"), "allow", "accordée");
  egal(verdictDeLaCause("regle:toujours"), "allow", "accordée par une règle");
  egal(verdictDeLaCause("deny"), "deny", "refusée");
  egal(verdictDeLaCause("relachee"), "", "relâchée : ni l'un ni l'autre");
  egal(verdictDeLaCause(undefined), "", "rien");
}

{
  const messages = [
    { role: "assistant", blocks: [{ type: "text", text: "Je vérifie." }, outil("t1"), outil("t2")] },
    { role: "system", blocks: [carte("d1", "t1")] },
  ];
  const apres = rattacherLeVerdict(messages, "d1", "allow");
  egal(apres.length, 1, "le message système qui ne portait que la carte disparaît");
  const t1 = apres[0].blocks.find((b) => b.id === "t1");
  const t2 = apres[0].blocks.find((b) => b.id === "t2");
  egal(t1.verdict, "allow", "le verdict est sur l'outil qui a demandé");
  verifier(t2.verdict === undefined, "les autres outils ne bougent pas");
  verifier(messages[1].blocks.length === 1 && messages[0].blocks[1].verdict === undefined, "les messages d'origine ne sont pas modifiés");

  // La ligne de l'étape le dit.
  const g = regrouperTour(apres[0].blocks, { raisonnement: false });
  egal(g.etapes.filter((e) => e.genre === "outil").map((e) => e.decision), ["allow", ""], "l'étape porte « allow », l'autre rien");
  egal(g.toujoursVisibles, [], "plus rien en bas");

  egal(rattacherLeVerdict(messages, "d1", "deny")[0].blocks.find((b) => b.id === "t1").verdict, "deny", "un refus aussi");
}

{
  const messages = [{ role: "assistant", blocks: [outil("t1")] }, { role: "system", blocks: [carte("d1", "absent")] }];
  egal(rattacherLeVerdict(messages, "d1", "allow"), messages, "outil absent du fil : la carte reste");
  egal(rattacherLeVerdict(messages, "inconnue", "allow"), messages, "demande inconnue : rien");
  egal(rattacherLeVerdict(messages, "d1", ""), messages, "verdict inconnu : rien");
  const question = [{ role: "assistant", blocks: [outil("t1")] }, { role: "system", blocks: [carte("q1", "t1", "question")] }];
  egal(rattacherLeVerdict(question, "q1", "allow"), question, "une question n'est ni accordée ni refusée : elle reste");
  egal(rattacherLeVerdict(null, "d1", "allow"), null, "pas de fil");
}

{
  // La carte dans le message de l'agent, avec d'autres blocs : seule elle sort.
  const messages = [{ role: "assistant", blocks: [outil("t1"), carte("d1", "t1"), { type: "text", text: "suite" }] }];
  const apres = rattacherLeVerdict(messages, "d1", "allow");
  egal(apres[0].blocks.map((b) => b.type), ["tool", "text"], "la carte sort du message, le reste demeure");
  egal(apres[0].blocks[0].verdict, "allow", "et l'outil porte le verdict");
}

// Le verdict survit à la relecture du journal, qui remplace les messages.
{
  const st = {
    messages: [
      { role: "assistant", blocks: [outil("t1")] },
      { role: "system", blocks: [carte("d1", "t1")] },
    ],
  };
  egal(idDeLOutil(st.messages, "d1"), "t1", "l'outil de la demande est retrouvé");
  egal(idDeLOutil(st.messages, "inconnue"), "", "demande inconnue");
  egal(S.rattacherUnVerdict(st, "d1", "allow"), true, "le fil a changé");
  egal(st.messages.length, 1, "la carte est partie");
  egal(st.verdicts, { t1: "allow" }, "le verdict est retenu");
  egal(S.rattacherUnVerdict(st, "d1", "allow"), false, "plus rien à rattacher la seconde fois");

  // Le journal relu ne connaît pas le verdict : setMessages le remet.
  S.setMessages(st, [{ role: "assistant", blocks: [outil("t1"), outil("t2")] }]);
  egal(st.messages[0].blocks[0].verdict, "allow", "l'outil relu porte de nouveau son verdict");
  verifier(st.messages[0].blocks[1].verdict === undefined, "un autre outil n'en reçoit pas");
  const identique = [{ role: "assistant", blocks: [outil("t9")] }];
  verifier(appliquerLesVerdicts(identique, { t1: "allow" }) === identique, "sans outil concerné, le même tableau");
  verifier(appliquerLesVerdicts(identique, {}) === identique && appliquerLesVerdicts(identique, undefined) === identique, "sans verdicts retenus, rien ne change");
}

bilan("verdict-decision");
