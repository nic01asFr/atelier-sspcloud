// Le choix du modèle d'une conversation (`/model` de Claude Code).
//
// Ce qu'il doit tenir :
//   - le sélecteur propose le défaut, puis tout le catalogue ;
//   - un modèle déjà choisi mais absent du catalogue reste affiché ;
//   - `/model <nom>` comprend un identifiant, un alias du CLI et un libellé ;
//   - `/model` seul dit ce qui existe, et ce qui est en cours.

import { bilan, egal, verifier } from "./verifier.mjs";
import {
  commandeModele,
  ditLesModeles,
  libelleDuModele,
  optionsDuModele,
  resoudreModele,
} from "../../mcp_gateway/atelier/web/js/ui/choix-du-modele.js";

const catalogue = {
  default: "qwen3-6-35b-moe",
  models: [
    { id: "qwen3-6-35b-moe", label: "Recommandé", default: true },
    { id: "qwen3-8-27b", label: "Plus rapide" },
    { id: "claude-albert-gpt-oss-120b", label: "Albert API · gpt-oss-120b" },
    { id: "claude-albert-deepseek-v4-flash-0731", label: "Albert API · deepseek-v4-flash-0731" },
    { id: "qwen3-vl", label: "qwen3-vl" },
  ],
};

{
  egal(libelleDuModele({ id: "qwen3-vl", label: "qwen3-vl" }), "qwen3-vl", "libellé = identifiant : une fois");
  egal(libelleDuModele({ id: "qwen3-6-35b-moe", label: "Recommandé" }), "qwen3-6-35b-moe · Recommandé", "le rôle suit l'identifiant");
  egal(libelleDuModele(catalogue.models[2]), "Albert API · gpt-oss-120b", "un libellé qui dit déjà l'identifiant reste tel quel");
  egal(libelleDuModele({ id: "x" }), "x", "sans libellé, l'identifiant");
}

{
  const o = optionsDuModele(catalogue, "");
  egal(o[0], { value: "", label: "Modèle par défaut · qwen3-6-35b-moe" }, "le défaut d'abord, et il se nomme");
  egal(o.length, 6, "le défaut + les cinq modèles");
  egal(o.map((x) => x.value).slice(1), catalogue.models.map((m) => m.id), "dans l'ordre du catalogue");
  egal(optionsDuModele(null, "")[0].label, "Modèle par défaut", "sans catalogue : le défaut seul, sans nom");
  egal(optionsDuModele({ models: [] }, "").length, 1, "catalogue vide : le défaut seul");

  const ancien = optionsDuModele(catalogue, "modele-retire");
  egal(ancien[ancien.length - 1], { value: "modele-retire", label: "modele-retire" }, "un modèle absent du catalogue reste affiché");
  egal(optionsDuModele(catalogue, "qwen3-8-27b").length, 6, "un modèle du catalogue n'est pas dupliqué");
  egal(optionsDuModele(catalogue, "opus").some((x) => x.value === "opus"), true, "un alias choisi reste affiché");
}

{
  egal(commandeModele("/model"), { nom: "" }, "/model seul");
  egal(commandeModele("/model opus"), { nom: "opus" }, "/model avec un nom");
  egal(commandeModele("  /MODEL   gpt-oss  "), { nom: "gpt-oss" }, "casse et espaces tolérés");
  egal(commandeModele("/model a b"), null, "deux mots : pas une commande de modèle");
  egal(commandeModele("/modelx"), null, "une autre commande");
  egal(commandeModele("parle-moi de /model"), null, "du texte ordinaire");
  egal(commandeModele(""), null, "rien");
}

{
  const r = (nom) => resoudreModele(nom, catalogue);
  egal(r("qwen3-8-27b"), "qwen3-8-27b", "un identifiant du catalogue");
  egal(r("QWEN3-8-27B"), "qwen3-8-27b", "sans tenir compte de la casse");
  egal(r("opus"), "opus", "un alias du CLI");
  egal(r("Sonnet"), "sonnet", "alias, casse tolérée");
  egal(r("default"), "", "default : retour au défaut");
  egal(r("gpt-oss-120b"), "claude-albert-gpt-oss-120b", "la fin d'un identifiant, si elle est sans ambiguïté");
  egal(r("deepseek-v4-flash-0731"), "claude-albert-deepseek-v4-flash-0731", "idem pour un autre fournisseur");
  egal(r("Albert API · gpt-oss-120b"), "claude-albert-gpt-oss-120b", "un libellé entier");
  egal(r("inconnu"), null, "rien de reconnu : null");
  egal(r(""), null, "pas de nom");
  verifier(resoudreModele("qwen3", { models: [{ id: "a-qwen3" }, { id: "b-qwen3" }] }) === null, "une fin ambiguë n'est pas devinée");
}

{
  const sans = ditLesModeles(catalogue, "");
  verifier(sans.includes("Modèle : qwen3-6-35b-moe."), "sans choix : le défaut du service est dit");
  verifier(sans.includes("• qwen3-6-35b-moe · Recommandé"), "le modèle en cours est marqué");
  verifier(sans.includes("  claude-albert-gpt-oss-120b") === false || sans.includes("Albert API · gpt-oss-120b"), "les autres sont listés");
  verifier(sans.includes("/model <nom> pour en changer."), "et on dit comment changer");
  const choisi = ditLesModeles(catalogue, "claude-albert-gpt-oss-120b");
  verifier(choisi.includes("• Albert API · gpt-oss-120b"), "le modèle choisi est marqué, pas le défaut");
  verifier(!choisi.includes("• qwen3-6-35b-moe"), "un seul marqué");
  egal(ditLesModeles({ models: [] }, ""), "Modèle : celui du service.", "sans catalogue, une phrase");
}

bilan("choix-du-modele");
