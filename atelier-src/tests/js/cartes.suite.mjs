// Les cartes du fil : ce qu'elles disent, et les gestes qu'elles offrent.
//
// Quatre défauts sont passés par là en une journée, tous corrigés après coup,
// à l'œil, faute d'un banc qui les voie :
//
//   1. une question relâchée s'affichait « Répondu » sans rien à montrer,
//      alors qu'elle n'a reçu aucune réponse et qu'on ne peut plus lui en
//      donner — à la différence d'une autorisation relâchée, qui elle reste
//      répondable parce qu'un « Toujours » retient encore la décision ;
//   2. le choix multiple ne s'annonçait pas : on n'apprenait qu'on pouvait
//      cocher plusieurs options qu'en cliquant deux fois, par hasard ;
//   3. les arguments d'un outil s'affichaient deux fois, dans le bloc d'outil
//      et dans la carte posée juste en dessous ;
//   4. le « Toujours » pouvait accorder plus large que ce qui était demandé,
//      un répertoire entier là où une commande précise suffisait.
//
// Le reste de la suite tient les gestes eux-mêmes, parce qu'une carte qui
// n'annonce rien est une carte morte : les boutons n'agissent pas, ils
// émettent `atelier:decision` et c'est le fil au-dessus qui entend.

import { berceau, cliquer, ecouter, frapper, html, saisir, texte } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import {
  appendMessageBody,
  ceQueToujoursAccorde,
  synchroniserBlocs,
} from "../../mcp_gateway/atelier/web/js/ui/message-render.js";

/**
 * Rend un bloc de décision comme le fil le fait, et tend l'oreille au-dessus.
 *
 * On passe par `synchroniserBlocs` — le chemin réel — et l'écoute est posée
 * sur le conteneur, pas sur la carte : c'est ainsi que le contrôleur écoute,
 * et c'est ce qui vérifie au passage que l'événement remonte bien.
 */
function rendre(bloc) {
  const fil = berceau();
  const recus = ecouter(fil, "atelier:decision");
  synchroniserBlocs(fil, [bloc]);
  return { fil, carte: fil.children[0], recus };
}

/**
 * Le nœud attendu, ou un leurre inerte.
 *
 * Quand un geste disparaît de la carte, on veut le compte-rendu du premier
 * échec et la suite des vérifications — pas une pile d'appels au milieu du
 * fichier, qui cache tout ce qui vient après.
 */
function exige(noeud, message) {
  verifier(!!noeud, message);
  return noeud || berceau();
}

/** Le bouton qui rassemble et envoie, là où un seul clic ne suffit pas. */
function boutonValider(carte) {
  const barre = exige(carte.querySelector(".msg-decision-actions"), "la carte offre une barre de validation");
  return exige(barre.querySelector("button"), "et un bouton pour envoyer les réponses");
}

/**
 * Un champ qu'on n'a pas rempli, tel que le navigateur le donne.
 *
 * Le DOM minimal ne pose pas de `value` par défaut, là où un vrai `<input>`
 * rend la chaîne vide. Sans cela, un cas qui vaut la peine d'être tenu — on
 * refuse sans se justifier — planterait sur la simulation au lieu de dire
 * quelque chose du code. On rétablit donc ici ce que le navigateur garantit,
 * plutôt que de renoncer au cas.
 */
function laisseVide(champ) {
  champ.value = "";
  return champ;
}

/** Une demande d'autorisation telle que le CLI nous la passe. */
function demandeOutil(extra = {}) {
  return {
    request_id: "req_1",
    outil: "Bash",
    arguments: { command: "rm -rf /tmp/essai" },
    ...extra,
  };
}

/** Une question de l'agent, telle qu'elle arrive par le canal des permissions. */
function demandeQuestion(questions, extra = {}) {
  return {
    genre: "question",
    request_id: "req_q",
    arguments: { questions },
    ...extra,
  };
}

// ── 1. Une question relâchée n'est pas une question répondue ──────────────
//
// L'état orphelin arrive quand le tour qui attendait la réponse est parti
// sans elle. La carte affichait « Répondu » et se vidait : elle mentait deux
// fois, sur ce qui s'était passé et sur ce qu'il restait à faire.

{
  const { carte } = rendre({
    type: "decision",
    etat: "orpheline",
    demande: demandeQuestion([
      { question: "On garde laquelle des deux pistes ?", options: [{ label: "La première" }] },
    ]),
  });

  const dit = texte(carte);
  porte(dit, "Question restée sans réponse", "une question relâchée se dit telle, et non « Répondu »");
  nePorte(dit, "Répondu", "elle ne se donne surtout pas pour répondue");
  porte(dit, "On garde laquelle des deux pistes ?", "la question posée est rappelée, sinon la carte est vide");
  porte(dit, "Reposez la question", "et l’on dit quoi faire si elle compte encore");

  // Aucun geste : le tour est parti, il n'y a rien à lui renvoyer et aucune
  // règle à retenir d'un avis qu'on ne donnera plus.
  egal(carte.querySelectorAll("button").length, 0, "une question relâchée n’offre plus aucun bouton");
  egal(carte.querySelectorAll("input").length, 0, "ni champ de réponse : il n’y a plus personne pour l’entendre");
  porte(html(carte), "msg-decision-orpheline", "la carte porte son état, pour le style comme pour le reste");
}

{
  // Le contraste qui donne son sens au cas précédent : une autorisation
  // orpheline, elle, reste répondable — « Toujours » retient la décision
  // pour la suite de la conversation.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "orpheline",
    demande: demandeOutil({
      suggestions: [{ type: "addRules", rules: [{ ruleContent: "Bash(rm:*)" }] }],
    }),
  });

  porte(texte(carte), "restée sans réponse", "une autorisation relâchée le dit aussi, repliée en une ligne (lot H)");
  porte(texte(carte), "Toujours", "mais elle explique que la décision peut encore être retenue");
  verifier(
    carte.querySelector(".msg-decision-toujours") !== null,
    "et le bouton « Toujours » y est bien, contrairement à une question relâchée",
  );

  cliquer(exige(carte.querySelector(".msg-decision-toujours"), "le bouton « Toujours » est là"));
  egal(recus.length, 1, "le geste part malgré le tour perdu");
  egal(recus[0]?.detail?.portee, "toujours", "et il porte la portée durable");
}

// ── 2. Le choix multiple s'annonce ────────────────────────────────────────
//
// Rien ne disait qu'on pouvait cocher plusieurs options. On l'apprenait en
// cliquant une seconde fois et en voyant la première rester allumée.

{
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      {
        question: "Quelles couches garder ?",
        multiSelect: true,
        options: [{ label: "Le bâti" }, { label: "La voirie" }],
      },
    ]),
  });
  porte(texte(carte), "Plusieurs réponses possibles", "un choix multiple s’annonce avant le premier clic");
  egal(carte.querySelectorAll(".msg-question-indice").length, 1, "une seule fois, et pour la seule question concernée");
}

{
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quelle couche garder ?", options: [{ label: "Le bâti" }, { label: "La voirie" }] },
    ]),
  });
  nePorte(texte(carte), "Plusieurs réponses possibles", "un choix unique ne promet pas ce qu’il ne permet pas");
  egal(carte.querySelectorAll(".msg-question-indice").length, 0, "aucun indice là où il n’y a rien à indiquer");
}

{
  // Deux questions dont une seule accepte plusieurs réponses : l'indice suit
  // la question, il n'est pas posé sur la carte entière.
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quel format ?", options: [{ label: "GeoJSON" }] },
      { question: "Quelles couches ?", multiSelect: true, options: [{ label: "Le bâti" }] },
    ]),
  });
  const blocs = carte.querySelectorAll(".msg-question-bloc");
  egal(blocs.length, 2, "chaque question a son bloc");
  egal(blocs[0].querySelectorAll(".msg-question-indice").length, 0, "le choix unique reste muet");
  egal(blocs[1].querySelectorAll(".msg-question-indice").length, 1, "et le choix multiple s’annonce, lui");
}

// ── 3. Les arguments ne se disent qu'une fois ─────────────────────────────
//
// Quand l'outil est rendu juste au-dessus, il porte déjà ses paramètres ;
// la carte les répétait, et la même commande s'affichait deux fois de suite.
// Sans le bloc d'outil — une carte restaurée après rechargement — c'est la
// carte qui doit les porter, sans quoi on autoriserait à l'aveugle.

{
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    argumentsAilleurs: true,
    demande: demandeOutil(),
  });
  nePorte(texte(carte), "rm -rf /tmp/essai", "les arguments se taisent quand le bloc d’outil les porte déjà");
  nePorte(texte(carte), "Ce que l", "et le repli qui les contient disparaît avec eux");
}

{
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeOutil(),
  });
  porte(texte(carte), "rm -rf /tmp/essai", "sans bloc d’outil au-dessus, la carte montre ce qui serait fait");
  porte(texte(carte), "Ce que l", "sous un repli nommé");
}

// ── 4. « Toujours » dit exactement ce qu'il accorde ───────────────────────
//
// La portée la plus étroite d'abord : une commande précise avant un
// répertoire entier, l'outil seulement faute de mieux. Accorder plus large
// que ce qui est demandé est la seule faute vraiment coûteuse ici.

{
  egal(
    ceQueToujoursAccorde({
      outil: "Bash",
      suggestions: [
        { type: "addDirectories", directories: ["/srv/projet"] },
        { type: "addRules", rules: [{ ruleContent: "Bash(git status:*)" }] },
      ],
    }),
    "Ne plus demander pour : Bash(git status:*)",
    "la règle précise l’emporte sur le répertoire entier, quel que soit l’ordre des suggestions",
  );

  egal(
    ceQueToujoursAccorde({
      outil: "Read",
      suggestions: [{ type: "addDirectories", directories: ["/srv/projet"] }],
    }),
    "Ne plus demander dans /srv/projet",
    "faute de règle, le répertoire — mais pas l’outil entier",
  );

  egal(
    ceQueToujoursAccorde({ outil: "Bash", suggestions: [] }),
    "Ne plus demander pour l’outil Bash",
    "l’outil entier seulement quand le CLI ne propose rien de plus étroit",
  );

  egal(ceQueToujoursAccorde({}), "", "sans rien à accorder, on n’invente pas une portée");

  egal(
    ceQueToujoursAccorde({
      outil: "Bash",
      suggestions: [{ type: "addRules", rules: [{}, { ruleContent: "Bash(ls:*)" }] }],
    }),
    "Ne plus demander pour : Bash(ls:*)",
    "une règle sans contenu est enjambée, pas prise pour un refus",
  );

  egal(
    ceQueToujoursAccorde({
      outil: "Bash",
      suggestions: [{ type: "addDirectories", directories: ["", "/srv/projet"] }],
    }),
    "Ne plus demander dans /srv/projet",
    "un répertoire vide ne devient pas une autorisation sur rien",
  );
}

{
  // Ce que la fonction rend se retrouve mot pour mot sur le bouton : sinon
  // l'infobulle promettrait une portée et le serveur en appliquerait une autre.
  const d = demandeOutil({ suggestions: [{ type: "addRules", rules: [{ ruleContent: "Bash(rm:*)" }] }] });
  const { carte } = rendre({ type: "decision", etat: "en_attente", demande: d });
  const toujours = exige(carte.querySelector(".msg-decision-toujours"), "le bouton « Toujours » est là");
  porte(toujours.title, ceQueToujoursAccorde(d), "l’infobulle dit exactement ce que « Toujours » accorderait");
  porte(toujours.title, "cette conversation", "et jusqu’où cela porte");
}

{
  // Sans rien à accorder, pas de bouton : un « Toujours » muet accorderait on
  // ne sait quoi.
  const { carte } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: { request_id: "req_2", arguments: {} },
  });
  egal(carte.querySelectorAll(".msg-decision-toujours").length, 0, "aucun « Toujours » quand aucune portée n’est nommable");
  egal(carte.querySelectorAll(".msg-decision-btn").length, 2, "il reste Autoriser et Refuser, et rien d’autre");
}

// ── Les gestes d'autorisation : annoncer, jamais agir ─────────────────────

{
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeOutil({ suggestions: [{ type: "addRules", rules: [{ ruleContent: "Bash(rm:*)" }] }] }),
  });

  cliquer(exige(carte.querySelector(".msg-decision-oui"), "« Autoriser » est offert"));
  egal(recus.length, 1, "« Autoriser » annonce quelque chose");
  verifier(recus[0]?.bubbles === true, "et l’annonce remonte le fil, sinon le contrôleur ne l’entend jamais");
  egal(recus[0]?.detail?.decision, "allow", "elle dit qu’on autorise");
  egal(recus[0]?.detail?.portee, "une_fois", "cette fois-ci seulement, tant qu’on n’a pas dit « Toujours »");
  egal(recus[0]?.detail?.requestId, "req_1", "et pour quelle demande");

  cliquer(exige(carte.querySelector(".msg-decision-toujours"), "le bouton « Toujours » est là"));
  egal(recus.length, 2, "« Toujours » annonce à son tour");
  egal(recus[1]?.detail?.decision, "allow", "il autorise, lui aussi");
  egal(recus[1]?.detail?.portee, "toujours", "mais pour la suite de la conversation");
}

{
  // Refuser se fait d'un clic (essai du 26/09 : « Confirmer le refus »
  // demandait un second geste). Un refus se rattrape — l'agent peut
  // redemander — : aucune confirmation n'y protège quoi que ce soit.
  const { carte, recus } = rendre({ type: "decision", etat: "en_attente", demande: demandeOutil() });

  cliquer(exige(carte.querySelector(".msg-decision-non"), "« Refuser » est offert"));
  egal(recus.length, 1, "un seul clic sur « Refuser » refuse");
  egal(recus[0]?.detail?.decision, "deny", "on refuse");
  egal(recus[0]?.detail?.motif, "", "sans motif écrit, le motif est vide, et non absent");
  egal(recus[0]?.detail?.portee, "une_fois", "un refus ne se retient pas pour toujours");
  nePorte(texte(carte), "Confirmer", "aucun bouton de confirmation sur la carte");
}

{
  // Refuser sans rien dire laisse l'agent deviner, et il devine mal. La
  // phrase reste offerte, déjà là sous les boutons : ce qui y est écrit part
  // avec le refus, toujours en un clic.
  const { carte, recus } = rendre({ type: "decision", etat: "en_attente", demande: demandeOutil() });
  const zone = exige(carte.querySelector(".msg-decision-motif"), "le champ de motif est offert d’emblée");
  egal(zone.querySelectorAll("button").length, 0, "et il n’apporte pas de second bouton");
  verifier(document.actif !== zone.querySelector("input"), "il ne vole pas le curseur au composeur");

  saisir(zone.querySelector("input"), "  Ce chemin est monté en lecture seule.  ");
  cliquer(exige(carte.querySelector(".msg-decision-non"), "« Refuser » est offert"));
  egal(recus.length, 1, "le refus part au premier clic");
  egal(
    recus[0]?.detail?.motif,
    "Ce chemin est monté en lecture seule.",
    "et le motif part avec, débarrassé de ses espaces — sans lui l’agent repart sur une théorie à lui",
  );
}

{
  // Entrée dans le champ vaut « Refuser » : personne ne va à la souris pour
  // valider une phrase qu'il vient de taper.
  const { carte, recus } = rendre({ type: "decision", etat: "en_attente", demande: demandeOutil() });
  const champ = exige(carte.querySelector(".msg-decision-motif"), "le motif est là").querySelector("input");
  saisir(champ, "Trop large.");
  frapper(champ, "Enter");
  egal(recus.length, 1, "Entrée refuse");
  egal(recus[0]?.detail?.decision, "deny", "c’est bien un refus");
  egal(recus[0]?.detail?.motif, "Trop large.", "avec le motif saisi");
}

{
  // Une carte déjà tranchée ne se rejoue pas : le tour est passé, et un second
  // envoi ferait répondre deux fois à la même demande.
  for (const etat of ["allow", "deny"]) {
    const { carte } = rendre({ type: "decision", etat, demande: demandeOutil() });
    egal(carte.querySelectorAll("button").length, 0, `une carte « ${etat} » n’offre plus de geste`);
  }
  const { carte } = rendre({ type: "decision", etat: "allow", demande: demandeOutil() });
  porte(texte(carte), "Autorisé", "elle dit ce qui a été décidé");
}

// ── Répondre à une question : un clic quand un clic suffit ────────────────

{
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quelle couche garder ?", options: [{ label: "Le bâti" }, { label: "La voirie" }] },
    ]),
  });

  egal(carte.querySelectorAll(".msg-decision-actions").length, 0, "une seule question à choix unique n’a pas de bouton de validation");
  const options = carte.querySelectorAll(".msg-question-option");
  cliquer(options[1]);
  egal(recus.length, 1, "elle se répond d’un seul clic — demander un second geste serait une cérémonie");
  verifier(recus[0]?.bubbles === true, "et la réponse remonte le fil");
  egal(recus[0]?.detail?.requestId, "req_q", "elle porte l’identifiant de la demande");
  egal(recus[0]?.detail?.reponses, [["La voirie"]], "et le libellé choisi, pas son rang");
}

{
  // Choix multiple : cliquer ne doit pas envoyer, sinon on ne pourrait jamais
  // en cocher deux.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      {
        question: "Quelles couches garder ?",
        multiSelect: true,
        options: [{ label: "Le bâti" }, { label: "La voirie" }, { label: "Le relief" }],
      },
    ]),
  });

  const options = carte.querySelectorAll(".msg-question-option");
  cliquer(options[0]);
  cliquer(options[2]);
  egal(recus.length, 0, "un choix multiple ne part pas au premier clic");
  verifier(options[0].classList.contains("choisie"), "les options cochées se voient");
  verifier(!options[1].classList.contains("choisie"), "et les autres non");

  cliquer(options[0]);
  verifier(!options[0].classList.contains("choisie"), "un second clic décoche");

  const valider = boutonValider(carte);
  porte(texte(valider), "Répondre", "il faut alors valider");
  cliquer(valider);
  egal(recus.length, 1, "et la validation envoie tout d’un coup");
  egal(recus[0]?.detail?.reponses, [["Le relief"]], "avec ce qui est resté coché, et seulement cela");
}

{
  // Deux questions : même à choix unique, le premier clic ne peut pas répondre
  // pour la seconde.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quel format ?", options: [{ label: "GeoJSON" }, { label: "GeoPackage" }] },
      { question: "Quelle projection ?", options: [{ label: "Lambert 93" }, { label: "WGS 84" }] },
    ]),
  });

  const options = carte.querySelectorAll(".msg-question-option");
  egal(options.length, 4, "les options des deux questions sont rendues");
  cliquer(options[0]);
  egal(recus.length, 0, "répondre à la première n’envoie pas le tout");
  cliquer(options[3]);
  egal(recus.length, 0, "ni la seconde");
  cliquer(boutonValider(carte));
  egal(
    recus[0]?.detail?.reponses,
    [["GeoJSON"], ["WGS 84"]],
    "la validation rassemble une réponse par question, dans l’ordre des questions",
  );
}

{
  // Le choix unique reste unique : cliquer ailleurs remplace, cela ne cumule
  // pas.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quel format ?", options: [{ label: "GeoJSON" }, { label: "GeoPackage" }] },
      { question: "Quelle projection ?", options: [{ label: "Lambert 93" }] },
    ]),
  });
  const options = carte.querySelectorAll(".msg-question-option");
  cliquer(options[0]);
  cliquer(options[1]);
  verifier(!options[0].classList.contains("choisie"), "l’option précédente s’éteint");
  verifier(options[1].classList.contains("choisie"), "seule la dernière reste allumée");
  cliquer(boutonValider(carte));
  egal(recus[0]?.detail?.reponses[0], ["GeoPackage"], "et une seule réponse part pour cette question");
}

// ── Le champ libre s'ajoute, il ne remplace pas ───────────────────────────
//
// Aucune liste ne prévoit tout. Mais écraser les options cochées dès qu'on
// tape un mot ferait perdre en silence ce qu'on venait de choisir.

{
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      {
        question: "Quelles couches garder ?",
        multiSelect: true,
        options: [{ label: "Le bâti" }, { label: "La voirie" }],
      },
    ]),
  });

  cliquer(carte.querySelectorAll(".msg-question-option")[0]);
  saisir(carte.querySelector(".msg-question-autre"), "Les réseaux enterrés");
  cliquer(boutonValider(carte));
  egal(
    recus[0]?.detail?.reponses,
    [["Le bâti", "Les réseaux enterrés"]],
    "le champ libre s’ajoute aux options cochées au lieu de les effacer",
  );
}

{
  // Effacer le champ libre ne doit pas emporter les options avec lui.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      {
        question: "Quelles couches garder ?",
        multiSelect: true,
        options: [{ label: "Le bâti" }, { label: "La voirie" }],
      },
    ]),
  });
  const options = carte.querySelectorAll(".msg-question-option");
  cliquer(options[0]);
  cliquer(options[1]);
  const libre = carte.querySelector(".msg-question-autre");
  saisir(libre, "Les réseaux");
  saisir(libre, "");
  cliquer(boutonValider(carte));
  egal(
    recus[0]?.detail?.reponses,
    [["Le bâti", "La voirie"]],
    "vider le champ libre ne retire que lui",
  );
}

{
  // Entrée dans le champ libre répond directement : c'est le geste naturel
  // après avoir tapé sa propre réponse.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quel format ?", options: [{ label: "GeoJSON" }] },
      { question: "Quelle projection ?", options: [{ label: "Lambert 93" }] },
    ]),
  });
  const libre = carte.querySelectorAll(".msg-question-autre")[1];
  saisir(libre, "Web Mercator");
  frapper(libre, "Enter");
  egal(recus.length, 1, "Entrée dans le champ libre répond");
  egal(recus[0]?.detail?.reponses, [[], ["Web Mercator"]], "avec ce qui est saisi, à sa place");
}

{
  // Un champ libre vide ne déclenche rien : une touche Entrée dans un champ
  // qu'on n'a pas rempli n'est pas une réponse.
  const { carte, recus } = rendre({
    type: "decision",
    etat: "en_attente",
    demande: demandeQuestion([
      { question: "Quel format ?", multiSelect: true, options: [{ label: "GeoJSON" }] },
    ]),
  });
  frapper(laisseVide(carte.querySelector(".msg-question-autre")), "Enter");
  egal(recus.length, 0, "Entrée sur un champ vide n’envoie pas une réponse vide");
}

// ── Une question répondue montre ce qui a été répondu ─────────────────────
//
// Sinon le fil garde la question sans sa réponse, et l'on ne sait plus ce que
// le modèle a reçu. Ce qui fait foi est le résumé du serveur — c'est lui qui
// est parti au modèle ; la note du navigateur se perd au rechargement.

{
  const { carte } = rendre({
    type: "decision",
    etat: "repondu",
    resume: "Quelles couches garder ?:\n- Le bâti\n- Les réseaux enterrés",
    reponses: [["Ce que le navigateur avait noté"]],
    demande: demandeQuestion([
      { question: "Quelles couches garder ?", multiSelect: true, options: [{ label: "Le bâti" }] },
    ]),
  });

  const dit = texte(carte);
  porte(dit, "Répondu", "la carte se dit répondue");
  porte(dit, "Le bâti", "et montre ce qui est parti au modèle");
  porte(dit, "Les réseaux enterrés", "y compris la réponse libre");
  nePorte(
    dit,
    "Ce que le navigateur avait noté",
    "le résumé du serveur prime sur la note du navigateur, qui ne survit pas au rechargement",
  );
  egal(carte.querySelectorAll("button").length, 0, "et il n’y a plus rien à cliquer");
}

{
  // Sans résumé — une réponse qui vient de partir, le serveur n'ayant pas
  // encore renvoyé la sienne —, on retombe sur ce que le navigateur sait.
  const { carte } = rendre({
    type: "decision",
    etat: "repondu",
    reponses: [["GeoJSON"], []],
    demande: demandeQuestion([
      { header: "Format", question: "Quel format ?", options: [{ label: "GeoJSON" }] },
      { header: "Projection", question: "Quelle projection ?", options: [{ label: "Lambert 93" }] },
    ]),
  });
  const dit = texte(carte);
  porte(dit, "Format", "faute de résumé, chaque question est rappelée");
  porte(dit, "GeoJSON", "avec ce que le navigateur a retenu");
  porte(dit, "sans réponse", "et une question laissée de côté le dit, au lieu de rester muette");
}

{
  // Le canal des permissions rend « allow » là où la question a été répondue :
  // le libellé de l'état ne doit pas transformer un avis en autorisation.
  const { carte } = rendre({
    type: "decision",
    etat: "allow",
    resume: "- La voirie",
    demande: demandeQuestion([{ question: "Quelle couche ?", options: [{ label: "La voirie" }] }]),
  });
  porte(texte(carte), "Répondu", "une question tranchée se dit « Répondu », pas « Autorisé »");
  porte(texte(carte), "La voirie", "et montre la réponse");
}

// ── Le chemin réel : par le corps du message ──────────────────────────────
//
// `synchroniserBlocs` est ce que la suite emprunte partout ailleurs ; on
// vérifie une fois que le chemin complet y mène, conteneur compris.

{
  const message = berceau();
  const recus = ecouter(message, "atelier:decision");
  appendMessageBody(message, {
    role: "assistant",
    blocks: [
      { type: "text", text: "Je dois effacer ce dossier." },
      { type: "decision", etat: "en_attente", argumentsAilleurs: true, demande: demandeOutil() },
    ],
  });

  // Une réponse de l'agent se lit en étapes : la parole d'avant la demande
  // y devient narration, la demande ne se replie jamais.
  const corps = message.querySelector(".tour-visibles");
  verifier(corps !== null, "le corps du message accueille ce qui ne se replie jamais");
  egal(corps.children.length, 1, "la carte, hors du pli des étapes");
  porte(texte(message.querySelector(".tour-etapes-liste")), "Je dois effacer ce dossier.", "et la parole dans les étapes");
  const carte = corps.querySelector(".msg-decision");
  verifier(carte !== null, "la carte de décision est bien rendue par ce chemin");
  cliquer(exige(carte.querySelector(".msg-decision-oui"), "« Autoriser » est offert"));
  egal(recus.length, 1, "et son annonce remonte jusqu’au message, à deux niveaux de là");

  // Une carte tranchée remplace la carte en attente sans laisser l'ancienne :
  // deux cartes pour une demande, c'est deux réponses possibles.
  appendMessageBody(message, {
    role: "assistant",
    blocks: [
      { type: "text", text: "Je dois effacer ce dossier." },
      { type: "decision", etat: "allow", argumentsAilleurs: true, demande: demandeOutil() },
    ],
  });
  egal(corps.querySelectorAll(".msg-decision").length, 1, "une seule carte pour une seule demande");
  egal(corps.querySelectorAll(".msg-decision-btn").length, 0, "et la demande tranchée n’offre plus de geste");
}

bilan("cartes");
