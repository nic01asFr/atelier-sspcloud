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
  const sans = piecesJointesDuTexte("rien de joint ici, sauf un @utilisateur et un mail a@b.fr");
  egal(sans.pieces, [], "une mention ordinaire n'est pas un fichier");
  egal(sans.texte, "rien de joint ici, sauf un @utilisateur et un mail a@b.fr", "le texte n'est pas touché");
  const milieu = piecesJointesDuTexte(`regarde @.atelier/uploads/${ID}_x.txt dans le message`);
  egal(milieu.pieces, [], "une mention au milieu d'une phrase n'est pas retirée");
  egal(piecesJointesDuTexte("").pieces, [], "texte vide");
  egal(piecesJointesDuTexte(undefined).texte, "", "texte absent");
}

bilan("pieces-jointes");
