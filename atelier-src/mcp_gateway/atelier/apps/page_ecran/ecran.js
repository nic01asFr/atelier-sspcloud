/**
 * L'écran du navigateur de l'agent, servi par l'hôte des applications sous
 * `/_ecran/<conversation>/`, dans le panneau de l'Atelier.
 *
 * Il ne reçoit que deux choses de son WebSocket (`flux`) : des images JPEG
 * (le screencast de la page que l'agent a sélectionnée) et un état (adresse,
 * titre, main, actions de l'agent en attente). Il n'envoie que des gestes :
 * souris, molette, clavier, adresse — et seulement quand la personne a pris
 * la main. Ni port, ni jeton, ni protocole DevTools ne passent par ici : c'est
 * le serveur qui traduit un geste en commande pour Chrome.
 *
 * Les coordonnées partent en fraction de l'image (0 à 1) : la page ne connaît
 * pas la taille du navigateur de l'agent.
 */

/** L'adresse du flux, à côté de la page. */
export function adresseDuFlux(lieu) {
  const schema = lieu.protocol === "https:" ? "wss:" : "ws:";
  const chemin = lieu.pathname.endsWith("/") ? lieu.pathname : `${lieu.pathname}/`;
  return `${schema}//${lieu.host}${chemin}flux`;
}

/**
 * Où tombe un point de l'élément dans l'image affichée en `object-fit:
 * contain` (bandes comprises), en fraction de l'image ; null hors de l'image.
 */
export function fractionDansImage(x, y, cadre, naturelle) {
  const { largeur, hauteur } = naturelle;
  if (!largeur || !hauteur || !cadre.width || !cadre.height) return null;
  const echelle = Math.min(cadre.width / largeur, cadre.height / hauteur);
  const l = largeur * echelle;
  const h = hauteur * echelle;
  const gauche = cadre.left + (cadre.width - l) / 2;
  const haut = cadre.top + (cadre.height - h) / 2;
  const fx = (x - gauche) / l;
  const fy = (y - haut) / h;
  if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
  return { x: Math.round(fx * 10000) / 10000, y: Math.round(fy * 10000) / 10000 };
}

/** Les touches de modification, dans le codage de DevTools (Alt 1, Ctrl 2, Meta 4, Maj 8). */
export function modificateurs(ev) {
  return (ev.altKey ? 1 : 0) | (ev.ctrlKey ? 2 : 0) | (ev.metaKey ? 4 : 0) | (ev.shiftKey ? 8 : 0);
}

const BOUTONS = ["gauche", "milieu", "droit"];

/** Un geste de souris, prêt à partir. */
export function messageDeSouris(action, ev, fraction) {
  const message = { type: "souris", action, x: fraction.x, y: fraction.y, mod: modificateurs(ev) };
  if (action === "presse" || action === "relache") {
    message.bouton = BOUTONS[ev.button] || "gauche";
    message.clics = Math.min(3, Math.max(1, ev.detail || 1));
  }
  if (action === "molette") {
    message.dx = Math.max(-5000, Math.min(5000, ev.deltaX || 0));
    message.dy = Math.max(-5000, Math.min(5000, ev.deltaY || 0));
  }
  return message;
}

/** Une touche, prête à partir : le texte qu'elle produit, s'il y en a un. */
export function messageDeTouche(action, ev) {
  let texte = "";
  if (action === "bas" && !ev.ctrlKey && !ev.metaKey) {
    if (ev.key && [...ev.key].length === 1) texte = ev.key;
    else if (ev.key === "Enter") texte = "\r";
  }
  return {
    type: "clavier",
    action,
    key: String(ev.key || "").slice(0, 32),
    code: String(ev.code || "").slice(0, 32),
    texte,
    touche: Number.isInteger(ev.keyCode) && ev.keyCode >= 0 && ev.keyCode <= 255 ? ev.keyCode : 0,
    mod: modificateurs(ev),
  };
}

/** Ce que montrent la barre et le bandeau pour un état reçu. */
export function presentation(etat) {
  const main = !!etat.main;
  const attente = Number(etat.attente) || 0;
  let bandeau = "";
  if (main) {
    bandeau =
      attente > 0
        ? `Vous avez la main : l'agent est en pause (${attente} action${attente > 1 ? "s" : ""} en attente). Rendez-la quand vous avez fini.`
        : "Vous avez la main : l'agent est en pause. Rendez-la quand vous avez fini.";
  }
  return {
    adresse: etat.url || "",
    titre: etat.titre || "",
    bouton: main ? "Rendre la main" : "Prendre la main",
    boutonActif: !!etat.disponible || main,
    bandeau,
    message: etat.disponible ? "" : etat.raison || "Le navigateur de l'agent n'est pas ouvert.",
  };
}

function demarrer(doc, fen) {
  const image = doc.getElementById("image");
  const scene = doc.getElementById("scene");
  const champ = doc.getElementById("adresse-champ");
  const aller = doc.getElementById("adresse-aller");
  const formulaire = doc.getElementById("adresse");
  const boutonMain = doc.getElementById("main");
  const bandeau = doc.getElementById("bandeau");
  const message = doc.getElementById("message");

  let ws = null;
  let etat = { disponible: false, main: false };
  let urlImage = "";
  let attenteReconnexion = 500;
  let dernierMouvement = 0;
  let saisie = false;

  const naturelle = () => ({ largeur: image.naturalWidth, hauteur: image.naturalHeight });

  function envoyer(objet) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(objet));
  }

  function rendre() {
    const vue = presentation(etat);
    if (!saisie) champ.value = vue.adresse;
    champ.readOnly = !etat.main;
    champ.title = vue.titre;
    aller.hidden = !etat.main;
    boutonMain.textContent = vue.bouton;
    boutonMain.disabled = !vue.boutonActif;
    boutonMain.classList.toggle("rendre", !!etat.main);
    bandeau.textContent = vue.bandeau;
    bandeau.hidden = !vue.bandeau;
    scene.classList.toggle("main", !!etat.main);
    message.textContent = vue.message;
    message.hidden = !vue.message;
    doc.title = vue.titre ? `${vue.titre} — Navigateur de l'agent` : "Navigateur de l'agent";
  }

  function ouvrir() {
    ws = new fen.WebSocket(adresseDuFlux(fen.location));
    ws.binaryType = "blob";
    ws.onopen = () => {
      attenteReconnexion = 500;
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        const precedente = urlImage;
        urlImage = fen.URL.createObjectURL(ev.data);
        image.src = urlImage;
        if (precedente) fen.URL.revokeObjectURL(precedente);
        return;
      }
      let recu = null;
      try {
        recu = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (recu.type === "etat") {
        etat = recu;
        rendre();
      } else if (recu.type === "refus" && recu.raison) {
        message.textContent = recu.raison;
        message.hidden = false;
        fen.setTimeout(rendre, 2500);
      }
    };
    ws.onclose = (ev) => {
      ws = null;
      if (ev.code === 4401 || ev.code === 4403) {
        etat = { disponible: false, main: false, raison: "Session terminée : rouvrez cet onglet depuis l'Atelier." };
        rendre();
        return;
      }
      etat = { ...etat, disponible: false, raison: "Connexion perdue, nouvel essai…" };
      rendre();
      fen.setTimeout(ouvrir, attenteReconnexion);
      attenteReconnexion = Math.min(10000, attenteReconnexion * 2);
    };
  }

  boutonMain.addEventListener("click", () => {
    envoyer({ type: "main", prendre: !etat.main });
    if (!etat.main) scene.focus();
  });

  formulaire.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!etat.main) return;
    let url = champ.value.trim();
    if (url && !/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
    if (url) envoyer({ type: "aller", url });
    saisie = false;
    scene.focus();
  });
  champ.addEventListener("focus", () => {
    saisie = etat.main;
  });
  champ.addEventListener("blur", () => {
    saisie = false;
    rendre();
  });

  function souris(action) {
    return (ev) => {
      if (!etat.main) return;
      const fraction = fractionDansImage(ev.clientX, ev.clientY, image.getBoundingClientRect(), naturelle());
      if (!fraction) return;
      if (action === "bouge") {
        const maintenant = Date.now();
        if (maintenant - dernierMouvement < 33) return;
        dernierMouvement = maintenant;
      }
      if (action === "presse") scene.focus();
      ev.preventDefault();
      envoyer(messageDeSouris(action, ev, fraction));
    };
  }
  image.addEventListener("mousedown", souris("presse"));
  image.addEventListener("mouseup", souris("relache"));
  image.addEventListener("mousemove", souris("bouge"));
  image.addEventListener("wheel", souris("molette"), { passive: false });
  image.addEventListener("contextmenu", (ev) => {
    if (etat.main) ev.preventDefault();
  });

  function touche(action) {
    return (ev) => {
      if (!etat.main) return;
      ev.preventDefault();
      envoyer(messageDeTouche(action, ev));
    };
  }
  scene.addEventListener("keydown", touche("bas"));
  scene.addEventListener("keyup", touche("haut"));
  scene.addEventListener("paste", (ev) => {
    if (!etat.main) return;
    const texte = ev.clipboardData ? ev.clipboardData.getData("text/plain") : "";
    if (texte) {
      ev.preventDefault();
      envoyer({ type: "texte", texte: texte.slice(0, 2000) });
    }
  });

  rendre();
  ouvrir();
}

if (globalThis.document?.body?.dataset?.ecranAuto === "1") {
  demarrer(globalThis.document, globalThis);
}
