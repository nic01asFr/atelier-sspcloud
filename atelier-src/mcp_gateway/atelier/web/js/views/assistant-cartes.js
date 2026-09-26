/**
 * Les cartes d'action du fil : ce qu'une commande de l'Atelier a fait, ou propose.
 *
 * Une commande qui agit rend une `carte` (transverse §1.8), construite par elle
 * et jamais rédigée par le modèle : titre, résumé, preuve, « Voir » et
 * « Annuler ». Une commande engageante rend d'abord un aperçu
 * (`confirmation_requise`) et ne fait rien : la carte offre alors « Oui ».
 *
 * Les boutons n'appellent rien eux-mêmes. Ils émettent un événement qui
 * remonte le fil (`atelier:carte-annuler`, `atelier:carte-oui`) ; le contrôleur
 * (`createCartesActions`) l'entend, appelle le service au nom de la personne,
 * et retient l'issue ici pour que la carte, redessinée, la montre encore.
 *
 * Tout est posé en texte (`textContent`) ; « Voir » n'accepte qu'une adresse
 * de l'Atelier (chemin absolu) ou en https.
 */

// L'issue des gestes déjà faits, par identifiant d'action ou de jeton : le fil
// se reconstruit souvent, la carte doit se souvenir qu'on l'a annulée.
const issues = new Map();
// Ce que chaque carte montrait, pour la redessiner à l'identique après un geste.
const donneesParCle = new Map();

export function issueDe(cle) {
  return issues.get(cle) || null;
}

export function retenirIssue(cle, issue) {
  if (cle) issues.set(cle, issue);
}

export function oublierLesIssues() {
  issues.clear();
  donneesParCle.clear();
}

function marquer(boite, cle, donnees) {
  if (!cle) return;
  boite.dataset.cle = cle;
  donneesParCle.set(cle, donnees);
}

/**
 * Redessine, sous `racine`, les cartes d'une action ou d'un aperçu.
 *
 * Le fil garde le nœud d'un message qui n'a pas changé : l'issue d'un geste
 * ne change pas le message, elle ne se verrait donc qu'au rechargement. On
 * remplace ici les seules cartes concernées.
 */
export function redessinerLesCartes(racine, cle) {
  const donnees = donneesParCle.get(cle);
  if (!racine || !donnees) return 0;
  let n = 0;
  for (const ancienne of [...racine.querySelectorAll(".msg-carte")]) {
    if (ancienne.dataset?.cle !== cle) continue;
    const neuve = carteDAction(donnees);
    if (neuve) {
      // Le contenu change, le nœud reste : le fil n'a rien à recoller.
      ancienne.className = neuve.className;
      ancienne.replaceChildren(...neuve.children);
      n += 1;
    }
  }
  return n;
}

// Ce qu'une commande engageante demande, dit avec les mots de l'écran (S2).
const LIBELLES_D_APERCU = {
  atelier_lancer_agent: "Confier ce travail à un agent",
  atelier_connecteur_ajouter: "Ajouter ce connecteur",
  atelier_connecteur_retirer: "Retirer ce connecteur",
  atelier_projet_structurer: "Mettre le projet à la structure de l’Atelier",
  atelier_projet_deployer_declarer: "Déclarer le déploiement du projet",
  atelier_decider: "Accorder cette autorisation",
};

// Les champs d'un aperçu qu'on montre, dans cet ordre, s'ils sont simples.
const CHAMPS_D_APERCU = [
  ["projet", "Projet"],
  ["nom", "Nom"],
  ["duree_s", "Durée maximale"],
  ["mode", "Mode"],
  ["branche", "Branche"],
  ["message", "Consigne"],
];

function lire(sortie) {
  if (sortie && typeof sortie === "object") return sortie;
  if (typeof sortie !== "string") return null;
  try {
    return JSON.parse(sortie);
  } catch {
    return null;
  }
}

function bouton(texte, classe, evenement, detail) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `ghost btn-sm ${classe}`;
  b.textContent = texte;
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    b.disabled = true;
    b.dispatchEvent(new CustomEvent(evenement, { bubbles: true, detail }));
  });
  return b;
}

function lienVoir(voir) {
  const lien = voir && typeof voir === "object" ? String(voir.lien || "") : "";
  if (!/^(\/(?!\/)|https:\/\/)/.test(lien)) return null;
  const a = document.createElement("a");
  a.href = lien;
  a.target = "_blank";
  a.rel = "noopener";
  a.className = "msg-carte-voir";
  a.textContent = "Voir";
  return a;
}

function duree(valeur) {
  const s = Number(valeur);
  if (!Number.isFinite(s) || s <= 0) return String(valeur);
  return s >= 60 ? `${Math.round(s / 60)} min` : `${s} s`;
}

function carteFaite(c, donnees) {
  const boite = document.createElement("div");
  boite.className = "msg-carte";
  if (donnees) marquer(boite, String(c.action || ""), donnees);
  const titre = document.createElement("strong");
  titre.textContent = String(c.titre);
  boite.appendChild(titre);
  if (c.resume) {
    const p = document.createElement("p");
    p.textContent = String(c.resume);
    boite.appendChild(p);
  }
  if (c.preuve) {
    const p = document.createElement("p");
    p.className = "msg-carte-preuve";
    p.textContent = typeof c.preuve === "string" ? c.preuve : JSON.stringify(c.preuve);
    boite.appendChild(p);
  }
  const gestes = document.createElement("div");
  gestes.className = "msg-carte-gestes";
  const voir = lienVoir(c.voir);
  if (voir) gestes.appendChild(voir);
  const action = String(c.action || "");
  const annuler = c.annuler && typeof c.annuler === "object" ? c.annuler : null;
  const issue = issueDe(action);
  if (issue) {
    const note = document.createElement("span");
    note.className = `msg-carte-issue msg-carte-issue-${issue.etat}`;
    note.textContent = issue.texte;
    gestes.appendChild(note);
  } else if (annuler && action) {
    gestes.appendChild(
      bouton(String(annuler.libelle || "Annuler"), "msg-carte-annuler", "atelier:carte-annuler", {
        action,
        commande: String(annuler.commande || "atelier_annuler"),
        arguments: annuler.arguments && typeof annuler.arguments === "object" ? annuler.arguments : { action },
      })
    );
  }
  if (gestes.children.length) boite.appendChild(gestes);
  return boite;
}

function carteDApercu(d) {
  const boite = document.createElement("div");
  boite.className = "msg-carte msg-carte-apercu";
  marquer(boite, String(d.confirmation || ""), d);
  const titre = document.createElement("strong");
  titre.textContent = LIBELLES_D_APERCU[d.commande] || "Action à confirmer";
  boite.appendChild(titre);
  const note = document.createElement("p");
  note.className = "msg-carte-note";
  note.textContent = "Rien n’est fait tant que vous n’avez pas dit oui.";
  boite.appendChild(note);
  const apercu = d.apercu && typeof d.apercu === "object" ? d.apercu : {};
  if (apercu.refus) {
    const p = document.createElement("p");
    p.className = "msg-carte-refus";
    p.textContent = String(apercu.refus);
    boite.appendChild(p);
  }
  const liste = document.createElement("dl");
  liste.className = "msg-carte-champs";
  for (const [cle, libelle] of CHAMPS_D_APERCU) {
    const v = apercu[cle];
    if (v == null || v === "" || typeof v === "object") continue;
    const dt = document.createElement("dt");
    dt.textContent = libelle;
    const dd = document.createElement("dd");
    const texte = cle === "duree_s" ? duree(v) : String(v);
    dd.textContent = texte.length > 240 ? `${texte.slice(0, 240)}…` : texte;
    liste.append(dt, dd);
  }
  if (liste.children.length) boite.appendChild(liste);
  const jeton = String(d.confirmation || "");
  const gestes = document.createElement("div");
  gestes.className = "msg-carte-gestes";
  const issue = issueDe(jeton);
  if (issue) {
    const etat = document.createElement("span");
    etat.className = `msg-carte-issue msg-carte-issue-${issue.etat}`;
    etat.textContent = issue.texte;
    gestes.appendChild(etat);
    if (issue.carte) boite.appendChild(carteFaite(issue.carte));
  } else if (jeton && !apercu.refus) {
    gestes.appendChild(
      bouton("Oui", "msg-carte-oui primary", "atelier:carte-oui", { jeton, commande: String(d.commande || "") })
    );
  }
  if (gestes.children.length) boite.appendChild(gestes);
  return boite;
}

/**
 * La carte que rend une commande, ou rien.
 *
 * @param {string | object} sortie — le résultat de l'outil, en JSON ou déjà lu
 * @returns {HTMLElement | null}
 */
export function carteDAction(sortie) {
  const donnees = lire(sortie);
  if (!donnees || typeof donnees !== "object") return null;
  if (donnees.confirmation_requise === true && donnees.confirmation) return carteDApercu(donnees);
  const c = donnees.carte;
  if (!c || typeof c !== "object" || !c.titre) return null;
  return carteFaite(c, donnees);
}

/**
 * Cette sortie porte-t-elle une carte d'action ? Même critère que
 * `carteDAction`, sans rien construire : le fil le demande à chaque image
 * pendant un tour.
 *
 * @param {string | object} sortie
 */
export function aUneCarte(sortie) {
  if (!sortie) return false;
  if (typeof sortie === "string" && !sortie.trimStart().startsWith("{")) return false;
  const donnees = lire(sortie);
  if (!donnees || typeof donnees !== "object") return false;
  if (donnees.confirmation_requise === true && donnees.confirmation) return true;
  const c = donnees.carte;
  return !!(c && typeof c === "object" && c.titre);
}

/**
 * Les gestes des cartes : « Annuler » et « Oui », au nom de la personne.
 *
 * @param {object} ctx
 * @param {object} ctx.api — `executerCommande`, `confirmerCommande`
 * @param {() => void} [ctx.rendreLeFil]
 * @param {() => HTMLElement} [ctx.racine] — où chercher les cartes (le fil)
 * @param {(msg: string) => void} ctx.erreur
 * @param {EventTarget} [ctx.cible] — là où l'on écoute (le document)
 */
export function createCartesActions(ctx) {
  const { api, erreur } = ctx;
  const cible = ctx.cible || document;
  const racine = () => ctx.racine?.() || (typeof document !== "undefined" ? document.body : null);
  const rendre = (cle) => {
    redessinerLesCartes(racine(), cle);
    ctx.rendreLeFil?.();
  };

  async function annuler(detail) {
    const { action, commande, arguments: args } = detail || {};
    if (!action) return;
    retenirIssue(action, { etat: "encours", texte: "Annulation…" });
    rendre(action);
    try {
      await api.executerCommande(commande || "atelier_annuler", args || { action });
      retenirIssue(action, { etat: "fait", texte: "Annulé" });
    } catch (err) {
      issues.delete(action);
      erreur(`Annulation impossible : ${err.message || err}`);
    }
    rendre(action);
  }

  async function oui(detail) {
    const { jeton } = detail || {};
    if (!jeton) return;
    retenirIssue(jeton, { etat: "encours", texte: "En cours…" });
    rendre(jeton);
    try {
      const reponse = await api.confirmerCommande(jeton);
      retenirIssue(jeton, { etat: "fait", texte: "Fait", carte: reponse?.resultat?.carte || null });
    } catch (err) {
      retenirIssue(jeton, { etat: "refus", texte: err.message || String(err) });
    }
    rendre(jeton);
  }

  function bind() {
    cible.addEventListener("atelier:carte-annuler", (e) => annuler(e.detail));
    cible.addEventListener("atelier:carte-oui", (e) => oui(e.detail));
  }

  return { bind, annuler, oui };
}

// ── « Non vérifié » : une affirmation sans carte ─────────────────────────
//
// Mesuré sur le pod : après un refus, le modèle annonce parfois un résultat
// qui n'a pas eu lieu (« Lien créé… vérifié », un aperçu inventé). Seule une
// commande qui agit rend une carte d'action ; un message de l'Assistant qui
// affirme avoir fait, créé, lancé ou vérifié quelque chose, sans carte dans
// le même tour, est donc marqué « non vérifié ». Le marquage ne juge pas le
// fond : il dit seulement qu'aucune preuve n'est à l'écran.

// Ce qui affirme un résultat : « c'est fait », « projet créé », « j'ai lancé »,
// « est relié », « vérifié »… Une négation juste avant (« rien n'est fait »,
// « pas encore créé », « non vérifié ») n'en est pas une.
// `\b` ne connaît pas les lettres accentuées : les bornes de mot se disent ici
// par « pas une lettre » avant et après.
const DEBUT = String.raw`(?<!\p{L})`;
const FIN = String.raw`(?!\p{L})`;
const PARTICIPES = String.raw`(?:cré|lanc|reli|ajout|rang|annul|supprim|activ|désactiv|modifi|renomm|branch|confi|termin|exécut)ée?s?`;
const AFFIRMATIONS = new RegExp(
  [
    String.raw`c['’]est fait${FIN}`,
    String.raw`${DEBUT}fait\s*[.!]`,
    String.raw`${DEBUT}(?:j['’]ai|je l['’]ai|est|sont|a été|ont été|bien)\s+${PARTICIPES}${FIN}`,
    String.raw`${DEBUT}(?:projet|lien|agent|connecteur|création|relation|tâche)s?\s+${PARTICIPES}${FIN}`,
    String.raw`${DEBUT}vérifiée?s?${FIN}`,
  ].join("|"),
  "giu"
);
const NEGATION = new RegExp(
  String.raw`${DEBUT}(?:n['’]|pas|rien|jamais|non|sans|si|quand|une fois|avant|dès que|«)${FIN}[^.!?\n]{0,24}$`,
  "iu"
);

/** Le texte affirme-t-il un résultat (fait, créé, lancé, vérifié…) ? */
export function affirmeUnResultat(texte) {
  const t = String(texte || "");
  AFFIRMATIONS.lastIndex = 0;
  for (let m = AFFIRMATIONS.exec(t); m; m = AFFIRMATIONS.exec(t)) {
    const avant = t.slice(Math.max(0, m.index - 30), m.index);
    if (!NEGATION.test(avant)) return true;
  }
  return false;
}

function texteDuMessage(m) {
  const morceaux = [m?.text || ""];
  for (const b of m?.blocks || []) if (b?.type === "text" && b.text) morceaux.push(b.text);
  return morceaux.join("\n");
}

/** Une carte d'action (d'une commande qui a agi) parmi les blocs du message. */
function porteUneCarte(m) {
  for (const b of m?.blocks || []) {
    if (b?.type !== "tool") continue;
    const d = lire(b.output);
    if (d && typeof d === "object" && d.carte && typeof d.carte === "object" && d.carte.titre) return true;
  }
  return false;
}

/**
 * Ce message de l'Assistant affirme-t-il un résultat sans carte dans son tour ?
 *
 * Le tour va du dernier message de la personne jusqu'à celui-ci : un résultat
 * rendu plus tôt dans le même tour compte comme preuve. Un message en cours
 * d'écriture n'est pas jugé.
 */
export function nonVerifie(messages, rang) {
  const m = messages?.[rang];
  if (!m || m.role !== "assistant" || m.streaming) return false;
  if (!affirmeUnResultat(texteDuMessage(m))) return false;
  for (let i = rang; i >= 0; i -= 1) {
    const x = messages[i];
    if (i < rang && x?.role === "user") break;
    if (porteUneCarte(x)) return false;
  }
  return true;
}

/** Pose (ou retire) la marque « non vérifié » sur le nœud d'un message. */
export function marquerNonVerifie(noeud, actif) {
  if (!noeud) return;
  for (const enfant of [...(noeud.children || [])]) {
    if (enfant.classList?.contains("msg-non-verifie")) enfant.remove();
  }
  if (!actif) return;
  const marque = document.createElement("span");
  marque.className = "msg-non-verifie";
  marque.textContent = "non vérifié";
  marque.title = "Aucune carte d’action ne confirme ce qui est annoncé dans ce tour.";
  noeud.appendChild(marque);
}

