// L'écran du navigateur de l'agent (page servie par l'hôte des applications).
//
// Ce qu'il doit tenir :
//   - le flux se joint à côté de la page, en wss sous https ;
//   - un clic part en fraction de l'image affichée, bandes comprises, et rien
//     ne part hors de l'image ;
//   - une touche porte son texte seulement quand elle en produit un ;
//   - la barre et le bandeau disent qui a la main, et « Rendre la main »
//     remplace « Prendre la main » ;
//   - aucun port, aucun chemin DevTools dans ce que la page fabrique.

import { EvenementSimule, cliquer, installerDom, saisir } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, verifier } from "./verifier.mjs";

import {
  adresseDuFlux,
  demarrer,
  fractionDansImage,
  messageDeSouris,
  messageDeTouche,
  modificateurs,
  presentation,
  tailleAjustee,
} from "../../mcp_gateway/atelier/apps/page_ecran/ecran.js";

// ── Le flux ────────────────────────────────────────────────────────────
{
  egal(
    adresseDuFlux({ protocol: "https:", host: "apps.exemple", pathname: "/_ecran/conv-a/" }),
    "wss://apps.exemple/_ecran/conv-a/flux",
    "wss sous https, à côté de la page",
  );
  egal(
    adresseDuFlux({ protocol: "http:", host: "127.0.0.1:8788", pathname: "/_ecran/conv-a" }),
    "ws://127.0.0.1:8788/_ecran/conv-a/flux",
    "ws en local, barre ajoutée",
  );
}

// ── La souris : en fraction de l'image, bandes comprises ───────────────
{
  // Une image 1280x720 dans un cadre 800x600 : bandes de 75 px en haut et en bas.
  const cadre = { left: 0, top: 0, width: 800, height: 600 };
  const naturelle = { largeur: 1280, hauteur: 720 };
  egal(fractionDansImage(400, 300, cadre, naturelle), { x: 0.5, y: 0.5 }, "le centre");
  egal(fractionDansImage(0, 75, cadre, naturelle), { x: 0, y: 0 }, "le coin, sous la bande");
  egal(fractionDansImage(400, 40, cadre, naturelle), null, "dans la bande : rien ne part");
  egal(fractionDansImage(400, 300, cadre, { largeur: 0, hauteur: 0 }), null, "sans image : rien ne part");
  const decale = { left: 100, top: 50, width: 640, height: 360 };
  egal(fractionDansImage(420, 230, decale, naturelle), { x: 0.5, y: 0.5 }, "cadre décalé dans la page");

  const ev = { button: 2, detail: 2, shiftKey: true, ctrlKey: false, altKey: false, metaKey: false };
  egal(
    messageDeSouris("presse", ev, { x: 0.25, y: 0.75 }),
    { type: "souris", action: "presse", x: 0.25, y: 0.75, mod: 8, bouton: "droit", clics: 2 },
    "bouton, clics et touches de modification",
  );
  const molette = messageDeSouris("molette", { deltaX: 0, deltaY: 99999 }, { x: 0.1, y: 0.1 });
  egal(molette.dy, 5000, "une molette démesurée est bornée");
  egal(modificateurs({ altKey: true, ctrlKey: true, metaKey: true, shiftKey: true }), 15, "codage DevTools");
}

// ── Le clavier ─────────────────────────────────────────────────────────
{
  const lettre = messageDeTouche("bas", { key: "é", code: "Digit2", keyCode: 50 });
  egal(lettre.texte, "é", "une lettre porte son texte");
  egal(messageDeTouche("bas", { key: "Enter", code: "Enter", keyCode: 13 }).texte, "\r", "Entrée aussi");
  egal(messageDeTouche("bas", { key: "ArrowLeft", code: "ArrowLeft", keyCode: 37 }).texte, "", "une flèche non");
  egal(messageDeTouche("bas", { key: "c", code: "KeyC", ctrlKey: true, keyCode: 67 }).texte, "", "un raccourci non plus");
  egal(messageDeTouche("haut", { key: "a", code: "KeyA", keyCode: 65 }).texte, "", "une touche relâchée non plus");
  egal(messageDeTouche("bas", { key: "x".repeat(100), code: "", keyCode: 999 }).key.length, 32, "nom de touche borné");
  egal(messageDeTouche("bas", { key: "a", code: "KeyA", keyCode: 999 }).touche, 0, "code hors bornes écarté");
}

// ── La barre et le bandeau ─────────────────────────────────────────────
{
  const libre = presentation({ disponible: true, main: false, url: "https://a.test/", titre: "A" });
  egal(libre.bouton, "Prendre la main", "l'agent pilote : on peut prendre la main");
  egal(libre.bandeau, "", "pas de bandeau");
  egal(libre.adresse, "https://a.test/", "l'adresse courante");
  verifier(libre.boutonActif, "bouton actif");

  const prise = presentation({ disponible: true, main: true, attente: 2, url: "https://a.test/" });
  egal(prise.bouton, "Rendre la main", "main prise : on la rend");
  egal(prise.bandeau, "Vous avez la main : l'agent est en pause (2 actions en attente). Rendez-la quand vous avez fini.", "le bandeau le dit");
  egal(presentation({ disponible: true, main: true, attente: 1 }).bandeau.includes("1 action en attente"), true, "singulier");

  const absent = presentation({ disponible: false, raison: "Le navigateur de l'agent n'est pas ouvert." });
  verifier(!absent.boutonActif, "rien à prendre sans navigateur");
  egal(absent.message, "Le navigateur de l'agent n'est pas ouvert.", "la raison se lit");
  nePorte(JSON.stringify([libre, prise, absent]), "devtools", "aucun chemin DevTools");
}

// ── La barre d'adresse : « Aller » et les mises à jour venues du serveur ──
//
// Essais du 26/09 : taper une adresse puis cliquer « Aller » ramenait
// l'ancienne adresse, alors qu'Entrée marchait. Un clic sur le bouton retire
// d'abord le focus du champ (blur), avant le clic et la soumission : le
// blur redessinait la barre et remettait l'adresse du serveur dans le champ,
// et c'est elle que la soumission envoyait.

/** La page de l'écran, montée sur le DOM minimal, avec un faux flux. */
function monterLEcran() {
  const doc = installerDom();
  const noeud = (balise, id, parent = doc.body) => {
    const n = doc.createElement(balise);
    n.id = id;
    parent.appendChild(n);
    return n;
  };
  const formulaire = noeud("form", "adresse");
  const champ = noeud("input", "adresse-champ", formulaire);
  const aller = noeud("button", "adresse-aller", formulaire);
  noeud("button", "main");
  noeud("div", "bandeau");
  const scene = noeud("main", "scene");
  noeud("img", "image", scene);
  noeud("p", "message", scene);
  const flux = [];
  class FauxFlux {
    constructor() {
      this.readyState = 1;
      this.envoyes = [];
      flux.push(this);
    }
    send(texte) {
      this.envoyes.push(JSON.parse(texte));
    }
  }
  const fen = {
    WebSocket: FauxFlux,
    location: { protocol: "https:", host: "apps.exemple", pathname: "/_ecran/conv-a/" },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
    setTimeout: () => 0,
  };
  demarrer(doc, fen);
  const ws = flux[0];
  const etat = (e) => ws.onmessage({ data: JSON.stringify({ type: "etat", disponible: true, ...e }) });
  const evenement = (n, type) => n.dispatchEvent(new EvenementSimule(type, {}));
  const allers = () => ws.envoyes.filter((m) => m.type === "aller").map((m) => m.url);
  return { champ, aller, formulaire, etat, evenement, allers };
}

{
  const e = monterLEcran();
  e.etat({ main: true, url: "https://ancienne.test/" });
  egal(e.champ.value, "https://ancienne.test/", "le champ montre l'adresse de la page");

  // Au clavier puis à la souris, dans l'ordre du navigateur : focus, saisie,
  // blur (le bouton prend le focus au mousedown), clic, soumission.
  e.evenement(e.champ, "focus");
  saisir(e.champ, "nouvelle.test");
  e.evenement(e.champ, "blur");
  e.evenement(e.formulaire, "submit");
  egal(e.allers(), ["https://nouvelle.test"], "« Aller » envoie l'adresse tapée, pas l'ancienne");
}

{
  const e = monterLEcran();
  e.etat({ main: true, url: "https://a.test/" });
  e.evenement(e.champ, "focus");
  saisir(e.champ, "b.te");
  e.etat({ main: true, url: "https://a.test/", titre: "A", attente: 1 });
  egal(e.champ.value, "b.te", "un état du serveur n'écrase pas le champ pendant la saisie");
  e.evenement(e.champ, "blur");
  e.etat({ main: true, url: "https://a2.test/" });
  egal(e.champ.value, "b.te", "ni une adresse modifiée non soumise, une fois le focus parti");
  e.evenement(e.formulaire, "submit");
  e.etat({ main: true, url: "https://b.te/" });
  egal(e.champ.value, "https://b.te/", "soumise, l'adresse suit de nouveau la page");
}

{
  const e = monterLEcran();
  e.etat({ main: true, url: "https://a.test/" });
  e.evenement(e.champ, "focus");
  saisir(e.champ, "abandonnee.test");
  e.evenement(e.champ, "blur");
  e.etat({ main: false, url: "https://c.test/" });
  egal(e.champ.value, "https://c.test/", "main rendue : le brouillon part, la barre suit la page");
  egal(e.allers(), [], "et rien n'a été envoyé");
}

// ── Sans bandes noires, et un bouton qui répond ──────────────────────────
//
// L'image remplissait toute la scène en `contain` : une page plus large que
// haute laissait deux bandes noires (essais du 26/09). Elle prend désormais
// la taille exacte qui tient dans la scène ; et « Prendre la main » dit qu'il
// attend l'accord du serveur au lieu de rester muet.

{
  egal(tailleAjustee({ width: 800, height: 900 }, { largeur: 1600, hauteur: 900 }), { largeur: 800, hauteur: 450 },
    "une page large se cale sur la largeur, sans bande au-dessus");
  egal(tailleAjustee({ width: 800, height: 300 }, { largeur: 1600, hauteur: 900 }), { largeur: 533, hauteur: 300 },
    "une scène basse cale la hauteur");
  egal(tailleAjustee({ width: 4000, height: 4000 }, { largeur: 400, hauteur: 300 }), { largeur: 800, hauteur: 600 },
    "jamais plus du double de la taille réelle");
  egal(tailleAjustee({ width: 800, height: 600 }, { largeur: 0, hauteur: 0 }), null, "sans image, rien à ajuster");
  const f = fractionDansImage(400, 225, { left: 0, top: 0, width: 800, height: 450 }, { largeur: 1600, hauteur: 900 });
  egal(f, { x: 0.5, y: 0.5 }, "une boîte aux proportions de l'image : le centre reste le centre");
}

{
  const e = monterLEcran();
  e.etat({ main: false, url: "https://a.test/" });
  const bouton = document.getElementById("main");
  cliquer(bouton);
  egal(bouton.textContent, "Prise de la main…", "le bouton dit qu'il attend l'accord");
  verifier(bouton.disabled, "et ne se reclique pas entre-temps");
  e.etat({ main: true, url: "https://a.test/" });
  egal(bouton.textContent, "Rendre la main", "l'état suivant le remet d'aplomb");
  verifier(!bouton.disabled, "réactivé");
}

bilan("ecran");
