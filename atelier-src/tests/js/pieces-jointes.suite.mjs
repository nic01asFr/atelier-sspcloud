// Les fichiers joints d'un message se lisent par leur nom.
//
// L'Atelier ajoute au message, pour Claude, une mention `@.atelier/uploads/
// <id>_<nom>` (la mention `@fichier` de Claude Code). Relu depuis la
// transcription, le message la porte en clair ; l'écran montre une pastille.

import { bilan, egal } from "./verifier.mjs";
import { piecesJointesDuTexte } from "../../mcp_gateway/atelier/web/js/ui/message-render.js";

const ID = "06d952d1-34ed-409c-aa3c-7aeb97c2d7d0";

{
  const r = piecesJointesDuTexte(`résume ce fichier\n@.atelier/uploads/${ID}_notes-de-reunion.txt`);
  egal(r.texte, "résume ce fichier", "le texte de la personne reste");
  egal(r.pieces, [{ name: "notes-de-reunion.txt" }], "le fichier se lit par son nom");
}

{
  const r = piecesJointesDuTexte(`@.atelier/uploads/${ID}_a.png\n@.atelier/uploads/${ID.replace("06", "07")}_mon fichier (2).pdf`);
  egal(r.texte, "", "des fichiers seuls : pas de texte");
  egal(r.pieces.map((p) => p.name), ["a.png", "mon fichier (2).pdf"], "plusieurs fichiers, noms avec espaces et parenthèses");
}

{
  // Depuis le 13/10 : chemin absolu (un modèle non-Claude lisait le relatif depuis son HOME), et une ligne de
  // conseil pour les fichiers que Read ne lit pas tel quel.
  const dossier = "/home/onyxia/work/wikichat-memory/assistant/sessions/abc";
  const r = piecesJointesDuTexte(
    `corrige-le\n@${dossier}/.atelier/uploads/${ID}_CANBT.html\n` +
      `@${dossier}/.atelier/uploads/${ID.replace("06", "07")}_bilan 2025.xlsx\n` +
      "(pièce jointe « bilan 2025.xlsx » — classeur : le lire avec python (`pandas.read_excel` ou `openpyxl`), jamais avec Read)"
  );
  egal(r.texte, "corrige-le", "ni le chemin absolu ni la ligne de conseil ne s'affichent");
  egal(r.pieces.map((p) => p.name), ["CANBT.html", "bilan 2025.xlsx"], "le chemin absolu se lit par le nom du fichier");
  const ancien = piecesJointesDuTexte(`@.atelier/uploads/${ID}_vieux.txt`);
  egal(ancien.pieces, [{ name: "vieux.txt" }], "les messages d'avant (chemin relatif) se lisent encore");
}

{
  const sans = piecesJointesDuTexte("rien de joint ici, sauf un @utilisateur et un mail a@b.fr");
  egal(sans.pieces, [], "une mention ordinaire n'est pas un fichier");
  egal(sans.texte, "rien de joint ici, sauf un @utilisateur et un mail a@b.fr", "le texte n'est pas touché");
  const milieu = piecesJointesDuTexte(`regarde @.atelier/uploads/${ID}_x.txt dans le message`);
  egal(milieu.pieces, [], "une mention au milieu d'une phrase n'est pas retirée");
  egal(piecesJointesDuTexte("").pieces, [], "texte vide");
  egal(piecesJointesDuTexte(undefined).texte, "", "texte absent");
}

bilan("pieces-jointes");
