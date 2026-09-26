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

import { bilan, egal, nePorte, verifier } from "./verifier.mjs";

import {
  adresseDuFlux,
  fractionDansImage,
  messageDeSouris,
  messageDeTouche,
  modificateurs,
  presentation,
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

bilan("ecran");
