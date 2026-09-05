// La réutilisation des nœuds : ce qui survit à une mise à jour, et ce qui doit
// être refait.
//
// Le défaut d'origine : un message ne se mettait à jour qu'en entier. Dès
// qu'un bloc bougeait — un outil qui apparaît, une autorisation qu'on accorde
// — son nœud était jeté et tout le corps reconstruit. Mesuré sur une
// conversation réelle : 242 blocs de code et 270 000 caractères refaits pour
// un seul changement, près de deux secondes de gel, et un clignotement de tout
// l'écran à chaque geste. Ce n'était pas la coloration syntaxique — la refaire
// coûte 23 ms — mais bien la reconstruction.
//
// La réutilisation descend maintenant au bloc. Rien ne le garantissait : cette
// suite tient les deux bords à la fois.
//
//   - trop de réutilisation et une carte reste figée sur « en cours… » pour
//     toujours, parce que son empreinte n'a pas vu le statut changer ;
//   - trop peu, et l'on retombe dans les deux secondes de gel.
//
// Ce qui se vérifie ici est donc l'identité des objets (`===`), pas leur
// contenu : un nœud reconstruit à l'identique passerait une comparaison de
// texte tout en ayant coûté le prix qu'on veut éviter.

import { berceau, html, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import {
  appendMessageBody,
  synchroniserBlocs,
} from "../../mcp_gateway/atelier/web/js/ui/message-render.js";

/** Un outil tel que le flux le dépose, en cours par défaut. */
function outil(id, extra = {}) {
  return {
    type: "tool",
    id,
    name: "Bash",
    input: { command: "ls" },
    output: "",
    status: "running",
    ...extra,
  };
}

/** Un segment de parole. Les textes sont tenus distincts d'un bloc à l'autre :
 *  deux blocs identiques partageraient leur empreinte, et l'un des deux ne
 *  serait pas réutilisable. */
function parole(texteDuBloc) {
  return { type: "text", text: texteDuBloc };
}

/** Une demande d'autorisation, telle que le CLI la fait remonter. */
function demande(requestId, extra = {}) {
  return {
    type: "decision",
    demande: { request_id: requestId, outil: "Bash" },
    etat: "en_attente",
    ...extra,
  };
}

/** Les nœuds du conteneur, figés pour être comparés après coup. */
function noeuds(conteneur) {
  return [...conteneur.children];
}

// ── 1. Ce qui n'a pas bougé garde son nœud ───────────────────────────────
//
// Le cœur de l'affaire. Un rendu qui redonnerait un contenu identique dans un
// nœud neuf coûterait exactement ce qu'on cherche à supprimer ; seule
// l'identité de l'objet le dit.

{
  const conteneur = berceau();
  const blocs = [
    parole("Je regarde le fichier."),
    outil("call_1"),
    parole("Il contient trois lignes."),
  ];

  synchroniserBlocs(conteneur, blocs);
  egal(conteneur.children.length, 3, "un nœud rendu par bloc du message");
  const avant = noeuds(conteneur);

  // Le flux renvoie des objets neufs à chaque événement : ce sont des copies,
  // pas les mêmes objets. C'est bien l'empreinte qui doit décider, pas
  // l'identité des blocs.
  synchroniserBlocs(conteneur, blocs.map((b) => ({ ...b })));
  const apres = noeuds(conteneur);
  verifier(
    apres.length === 3 && apres.every((n, i) => n === avant[i]),
    "rien n’a changé : aucun des trois nœuds n’est refait",
  );

  // Et cela tient dans la durée : dix rafraîchissements de suite ne doivent
  // rien reconstruire, sans quoi un flux bavard rendrait la page inutilisable.
  for (let i = 0; i < 10; i += 1) synchroniserBlocs(conteneur, blocs.map((b) => ({ ...b })));
  const encore = noeuds(conteneur);
  verifier(
    encore.length === 3 && encore.every((n, i) => n === avant[i]),
    "dix rafraîchissements de suite ne reconstruisent toujours rien",
  );
}

{
  // Un nœud posé par un rendu à l'ancienne ne porte pas d'empreinte : il n'est
  // pas réutilisable, et surtout il ne doit pas rester en place à côté du
  // rendu neuf. Sinon le corps enflerait à chaque mise à jour.
  const conteneur = berceau();
  const ancien = document.createElement("div");
  ancien.className = "heritage";
  conteneur.appendChild(ancien);

  synchroniserBlocs(conteneur, [parole("Voilà.")]);
  egal(conteneur.children.length, 1, "le nœud hérité, sans empreinte, ne survit pas au premier rendu");
  verifier(conteneur.children[0] !== ancien, "et il n’est pas réutilisé pour autant");
}

{
  // Un segment resté vide ne produit aucun nœud : `appendBlock` n'écrit rien.
  // On s'en assure ici pour que le compte des nœuds reste lisible ailleurs.
  const conteneur = berceau();
  synchroniserBlocs(conteneur, [parole(""), parole("Voilà.")]);
  egal(conteneur.children.length, 1, "un bloc qui ne rend rien n’occupe pas de place");
}

// ── 2. Ce qui change est refait, et lui seul ─────────────────────────────
//
// L'autre bord : le voisin d'un bloc qui bouge n'a aucune raison de payer.

{
  const conteneur = berceau();
  const avantCoup = parole("Je lance la commande.");
  const apresCoup = parole("Il contient trois lignes.");

  synchroniserBlocs(conteneur, [avantCoup, outil("call_1"), apresCoup]);
  const [texteAvant, carte, texteApres] = noeuds(conteneur);

  synchroniserBlocs(conteneur, [
    avantCoup,
    outil("call_1", { status: "done", output: "a.txt" }),
    apresCoup,
  ]);
  const apres = noeuds(conteneur);
  egal(apres.length, 3, "le message garde ses trois blocs");
  verifier(apres[0] === texteAvant, "la parole d’avant l’outil garde son nœud");
  verifier(apres[2] === texteApres, "la parole d’après l’outil garde son nœud");
  verifier(apres[1] !== carte, "seule la carte de l’outil est refaite");
}

// ── 3. L'ordre est préservé ──────────────────────────────────────────────
//
// Réutiliser des nœuds sans les remettre dans l'ordre du tour donnerait un fil
// où la réponse précède la question. Trois gestes le mettent à l'épreuve :
// insérer au milieu, retirer, échanger.

{
  const conteneur = berceau();
  const a = parole("D’abord ceci.");
  const c = parole("Ensuite cela.");

  synchroniserBlocs(conteneur, [a, c]);
  const [noeudA, noeudC] = noeuds(conteneur);

  // Insertion au milieu : c'est le cas courant, un outil qui apparaît entre
  // deux segments de parole déjà affichés.
  synchroniserBlocs(conteneur, [a, outil("call_1"), c]);
  const trois = noeuds(conteneur);
  egal(trois.length, 3, "le bloc inséré s’ajoute sans en chasser aucun");
  verifier(trois[0] === noeudA, "le bloc d’avant l’insertion garde son nœud et son rang");
  verifier(trois[2] === noeudC, "celui d’après aussi : il est décalé, pas refait");
  porte(html(trois[1]), "msg-tool", "et l’outil neuf s’est bien intercalé au milieu");

  // Retrait : le nœud disparaît, les deux autres restent en place.
  synchroniserBlocs(conteneur, [a, c]);
  const deux = noeuds(conteneur);
  egal(deux.length, 2, "le bloc retiré emporte son nœud");
  verifier(deux[0] === noeudA && deux[1] === noeudC, "et les survivants gardent les leurs");
}

{
  // Échange : deux blocs permutent. Rien ne doit être reconstruit, seul
  // l'ordre change. Une réutilisation indexée sur le rang, au lieu de
  // l'empreinte, rendrait ici deux nœuds neufs.
  const conteneur = berceau();
  const un = parole("Premier.");
  const deux = parole("Second.");
  const trois = parole("Troisième.");

  synchroniserBlocs(conteneur, [un, deux, trois]);
  const [n1, n2, n3] = noeuds(conteneur);

  synchroniserBlocs(conteneur, [deux, un, trois]);
  const permute = noeuds(conteneur);
  verifier(permute[0] === n2, "le second bloc, passé devant, garde son nœud");
  verifier(permute[1] === n1, "le premier, passé derrière, garde le sien");
  verifier(permute[2] === n3, "et le troisième n’a pas bougé");
  porte(texte(permute[0]), "Second.", "l’ordre affiché suit l’ordre demandé");
  porte(texte(permute[1]), "Premier.", "et non l’ordre d’origine");

  // Rotation complète : aucun bloc ne retrouve son rang, aucun ne doit être
  // refait pour autant.
  synchroniserBlocs(conteneur, [trois, deux, un]);
  const tourne = noeuds(conteneur);
  verifier(
    tourne[0] === n3 && tourne[1] === n2 && tourne[2] === n1,
    "une rotation complète ne reconstruit rien : elle réordonne",
  );
}

// ── 4. Un bloc qui vit doit se rafraîchir ────────────────────────────────
//
// Le symptôme qu'on a réellement vu : une carte figée sur « en cours… » alors
// que l'outil avait fini depuis longtemps. Une empreinte trop stable ne voit
// ni le statut ni la sortie, et le nœud n'est jamais refait.

{
  const conteneur = berceau();
  const voisin = parole("Je lance la commande.");

  synchroniserBlocs(conteneur, [voisin, outil("call_1")]);
  const enCours = conteneur.children[1];
  porte(texte(enCours), "en cours…", "l’outil qui démarre se dit en cours");

  synchroniserBlocs(conteneur, [voisin, outil("call_1", { status: "done", output: "a.txt" })]);
  const termine = conteneur.children[1];
  verifier(termine !== enCours, "l’outil passé à terminé est redessiné");
  nePorte(texte(termine), "en cours…", "et ne se dit plus en cours — le symptôme vu à l’écran");
  nePorte(html(termine), "msg-tool-running", "sa classe d’attente est retirée avec le reste");
  porte(texte(termine), "terminé", "il annonce qu’il a fini");
  porte(texte(termine), "a.txt", "et montre sa sortie");

  // Une sortie qui s'allonge : c'est le cas d'un outil long dont le résultat
  // arrive par morceaux. Le statut, lui, ne bouge plus.
  synchroniserBlocs(conteneur, [
    voisin,
    outil("call_1", { status: "done", output: "a.txt\nb.txt" }),
  ]);
  const rallonge = conteneur.children[1];
  verifier(rallonge !== termine, "une sortie qui s’allonge refait le nœud");
  porte(texte(rallonge), "b.txt", "et la nouvelle ligne s’affiche");
  verifier(conteneur.children[0] !== undefined, "le voisin est toujours là");

  // Une erreur après coup change l'apparence de la carte : elle doit suivre.
  synchroniserBlocs(conteneur, [
    voisin,
    outil("call_1", { status: "error", output: "a.txt\nb.txt" }),
  ]);
  const echoue = conteneur.children[1];
  verifier(echoue !== rallonge, "un outil qui bascule en erreur est redessiné");
  porte(html(echoue), "msg-tool-error", "et porte la classe qui le dit");
}

{
  // Une carte de décision qu'on répond : même exigence. Une empreinte aveugle
  // à l'état laisserait « Autorisation demandée » sous des boutons devenus
  // sans effet.
  const conteneur = berceau();
  const suite = parole("Puis je continue.");

  synchroniserBlocs(conteneur, [demande("req_1"), suite]);
  const [attente, apresLaDemande] = noeuds(conteneur);
  porte(texte(attente), "Autorisation demandée", "la carte en attente pose la question");
  porte(html(attente), "msg-decision-en_attente", "et se donne pour telle");

  synchroniserBlocs(conteneur, [demande("req_1", { etat: "allow" }), suite]);
  const accordee = conteneur.children[0];
  verifier(accordee !== attente, "une carte qui change d’état est redessinée");
  verifier(conteneur.children[1] === apresLaDemande, "le bloc qui la suit n’est pas touché");
  porte(texte(accordee), "Autorisé", "elle dit maintenant que c’est accordé");
  nePorte(texte(accordee), "Autorisation demandée", "et ne repose plus la question");
  nePorte(html(accordee), "msg-decision-actions", "les boutons d’une décision prise disparaissent");
}

// ── 5. `appendMessageBody` peut être rappelée sans rien doubler ──────────
//
// C'est ce qui permet de rafraîchir un message au lieu de le reconstruire :
// chaque partie a son conteneur, qu'on retrouve. Sans cela, chaque
// rafraîchissement empilerait une copie de plus des pièces jointes, du corps
// et du texte.

{
  // Les pièces jointes.
  const noeud = berceau();
  const message = {
    role: "user",
    text: "",
    blocks: [],
    attachments: [{ name: "note.md" }, { rel_path: "src/api.py" }],
  };

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-attachments").length, 1, "une seule rangée de pièces jointes");
  egal(noeud.querySelectorAll(".msg-attach-chip").length, 2, "une étiquette par pièce jointe");
  const rangee = noeud.querySelector(".msg-attachments");

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-attachments").length, 1, "un second appel n’ajoute pas de rangée");
  egal(noeud.querySelectorAll(".msg-attach-chip").length, 2, "ni ne double les étiquettes");
  verifier(noeud.querySelector(".msg-attachments") === rangee, "c’est la même rangée qu’on met à jour");

  // Une pièce jointe de plus se pose dans la rangée existante.
  message.attachments = [...message.attachments, { name: "carte.geojson" }];
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-attach-chip").length, 3, "la pièce jointe ajoutée apparaît");
  verifier(noeud.querySelector(".msg-attachments") === rangee, "toujours sans refaire la rangée");
  porte(texte(rangee), "carte.geojson", "et l’on voit son nom");
}

{
  // Le conteneur des blocs.
  const noeud = berceau();
  const message = {
    role: "assistant",
    text: "",
    blocks: [parole("Je regarde."), outil("call_1")],
    attachments: [],
  };

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-blocs").length, 1, "un seul conteneur de blocs");
  const corps = noeud.querySelector(".msg-blocs");
  egal(corps.children.length, 2, "et les deux blocs dedans");
  const dedans = noeuds(corps);

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-blocs").length, 1, "un second appel n’ajoute pas de conteneur");
  verifier(noeud.querySelector(".msg-blocs") === corps, "c’est le même corps qu’on met à jour");
  egal(corps.children.length, 2, "et les blocs ne sont pas doublés");
  verifier(
    corps.children[0] === dedans[0] && corps.children[1] === dedans[1],
    "rafraîchir un message ne reconstruit aucun de ses blocs",
  );
}

{
  // Le texte de repli, et sa condition d'existence.
  const noeud = berceau();
  const message = { role: "assistant", text: "Trois lignes lues.", blocks: [], attachments: [] };

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-repli").length, 1, "le texte s’affiche quand aucun bloc ne le porte");
  const repli = noeud.querySelector(".msg-repli");
  porte(texte(repli), "Trois lignes lues.", "et il dit bien ce que le message dit");
  const rendu = repli.children[0];

  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-repli").length, 1, "un second appel n’ajoute pas de repli");
  verifier(noeud.querySelector(".msg-repli") === repli, "c’est le même nœud de repli");
  verifier(repli.children[0] === rendu, "et son rendu n’est même pas refait, le texte n’ayant pas bougé");
  egal(texte(noeud).split("Trois lignes lues.").length - 1, 1, "le texte n’apparaît qu’une fois");

  // Le texte change : le rendu suit.
  message.text = "Quatre lignes lues.";
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-repli").length, 1, "toujours un seul repli");
  porte(texte(noeud), "Quatre lignes lues.", "le nouveau texte s’affiche");
  nePorte(texte(noeud), "Trois lignes lues.", "et l’ancien ne traîne pas dessous");

  // Un bloc de texte prend le relais : le repli n’a plus lieu d’être, sans
  // quoi le message dirait deux fois la même chose.
  message.blocks = [parole("Quatre lignes lues.")];
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-repli").length, 0, "le repli disparaît dès qu’un bloc porte le texte");
  egal(
    texte(noeud).split("Quatre lignes lues.").length - 1,
    1,
    "et le texte n’est dit qu’une fois, par le bloc",
  );

  // Le bloc s’en va : le repli reprend son service.
  message.blocks = [];
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-repli").length, 1, "sans bloc de texte, le repli revient");
  porte(texte(noeud), "Quatre lignes lues.", "et le message reste lisible");
}

{
  // Un bloc d'outil seul ne porte pas le texte : le repli doit rester. Le tri
  // se fait sur le type du bloc, pas sur sa simple présence.
  const noeud = berceau();
  appendMessageBody(noeud, {
    role: "assistant",
    text: "Je lance la commande.",
    blocks: [outil("call_1")],
    attachments: [],
  });
  egal(
    noeud.querySelectorAll(".msg-repli").length,
    1,
    "un outil ne porte pas la parole : le repli reste",
  );
}

// ── 6. Un message qui perd tous ses blocs perd son conteneur ─────────────
//
// Un `.msg-blocs` vide laissé en place garderait la mise en page d'un corps
// qui n'existe plus.

{
  const noeud = berceau();
  const message = {
    role: "assistant",
    text: "",
    blocks: [parole("Je regarde."), outil("call_1")],
    attachments: [],
  };

  appendMessageBody(noeud, message);
  verifier(noeud.querySelector(".msg-blocs") !== null, "le corps existe tant qu’il y a des blocs");

  message.blocks = [];
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-blocs").length, 0, "le corps s’en va avec le dernier bloc");
  nePorte(texte(noeud), "Je regarde.", "et rien de son contenu ne reste affiché");

  // Il revient si des blocs reviennent : la disparition n'est pas définitive.
  message.blocks = [parole("Je reprends.")];
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-blocs").length, 1, "et il se recrée si des blocs reviennent");
  porte(texte(noeud), "Je reprends.", "avec leur contenu");
}

{
  // Deux blocs peuvent porter la même empreinte — deux paragraphes au texte
  // identique, deux outils de même statut et de même sortie. L'index ne gardait
  // qu'un nœud par empreinte : le premier était réutilisé, tous les suivants
  // reconstruits à chaque rafraîchissement, sans qu'aucun n'ait changé. La
  // réutilisation s'arrêtait au premier doublon.
  const noeud = berceau();
  const message = { role: "assistant", blocks: [parole("Pareil."), parole("Pareil."), parole("Pareil.")] };
  appendMessageBody(noeud, message);
  const corps = noeud.querySelector(":scope > .msg-blocs");
  const avant = [...corps.children];
  egal(avant.length, 3, "trois blocs identiques donnent trois nœuds");

  appendMessageBody(noeud, { ...message, blocks: [parole("Pareil."), parole("Pareil."), parole("Pareil.")] });
  const apres = [...noeud.querySelector(":scope > .msg-blocs").children];
  verifier(apres[0] === avant[0], "le premier doublon garde son nœud");
  verifier(apres[1] === avant[1], "le deuxième aussi — c'est ce qui manquait");
  verifier(apres[2] === avant[2], "et le troisième");
}

{
  // Le corps et le texte de repli disparaissent quand ils n'ont plus lieu
  // d'être ; la rangée des pièces jointes, elle, restait vide. L'asymétrie
  // n'avait pas de raison.
  const noeud = berceau();
  const message = {
    role: "user",
    text: "Voici.",
    attachments: [{ name: "plan.md" }],
    blocks: [],
  };
  appendMessageBody(noeud, message);
  egal(noeud.querySelectorAll(".msg-attachments").length, 1, "la rangée apparaît avec les pièces jointes");

  appendMessageBody(noeud, { ...message, attachments: [] });
  egal(noeud.querySelectorAll(".msg-attachments").length, 0, "et s'en va quand il n'y en a plus");
}

bilan("reutilisation");
