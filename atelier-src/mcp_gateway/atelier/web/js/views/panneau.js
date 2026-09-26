/**
 * Le panneau : la colonne à droite du fil, où s'affichent les créations.
 *
 * Il vit hors du fil, et c'est tout son principe : le fil est reconstruit à
 * chaque image (`thread.replaceChildren`), et une iframe détachée puis
 * rattachée se recharge. Ici, chaque onglet garde son iframe tant qu'il est
 * ouvert ; changer d'onglet ne fait que la masquer.
 *
 * Une vue du panneau ouvre une création par l'Atelier
 * (`/v1/apps/<projet>/<nom>/ouvrir`), qui la confie à l'hôte des applications
 * avec un code de passage. Seul l'Atelier peut encadrer cet hôte
 * (`frame-ancestors`). L'iframe porte `allow-same-origin` : une application a
 * besoin de son cookie sur son propre hôte, qui n'est jamais celui de
 * l'Atelier ; les fichiers d'une création, eux, sont servis en bac à sable
 * par leur propre CSP, quoi que dise l'iframe.
 *
 * Où vivent les onglets (décision J-e) : avec la conversation par défaut ;
 * « Épingler au projet » les montre dans toutes les conversations du projet.
 * « Montrer » (outil de l'agent) ouvre le panneau seul (J-f).
 *
 * Tout ce qui vient d'une création (titre, nom) est posé en `textContent`.
 *
 * Les services du namespace (bureau de Blender ou de QGIS, éditeur n8n)
 * s'ouvrent depuis l'onglet « Bureaux » du catalogue, par l'Atelier
 * (`/v1/bureaux/<connecteur>/<vue>/ouvrir`), et sont relayés par l'hôte des
 * applications, le jeton du service posé côté serveur. Un bureau est un flux
 * vivant : il ne s'ouvre que sur un geste de la personne, jamais sur un
 * événement (J-f), n'est pas épinglé, et son cadre n'existe que tant que son
 * onglet est affiché (masqué, le flux s'arrête).
 */

import { rendrePanneauApplications } from "./applications.js";

const BAC_A_SABLE =
  "allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals allow-same-origin";

// Sous 720 px (règle CSS), le panneau devient une feuille plein écran.

/** Une vue d'un service du namespace (bureau, éditeur), et non une création. */
export function estUnService(vue) {
  return !!(vue && vue.connecteur);
}

/** Un flux vivant : ne s'ouvre jamais seul, ne tourne que s'il est affiché. */
export function estUnFluxVivant(vue) {
  return estUnService(vue) && vue.genre === "bureau";
}

/** L'onglet d'un service, tiré de sa fiche du catalogue. */
export function vueDeService(fiche) {
  return {
    id: `s_${fiche.connecteur}_${fiche.nom}`,
    genre: fiche.genre,
    connecteur: fiche.connecteur,
    nom: fiche.nom,
    titre: fiche.titre || `${fiche.connecteur} : ${fiche.nom}`,
    par: "personne",
  };
}

/** L'adresse, sur l'Atelier, qui ouvre la vue par le passage. */
export function adresseDeLaVue(vue) {
  if (estUnService(vue)) {
    if (!vue.nom) return "";
    return `/v1/bureaux/${encodeURIComponent(vue.connecteur)}/${encodeURIComponent(vue.nom)}/ouvrir`;
  }
  if (!vue || !vue.projet || !vue.nom) return "";
  const base = `/v1/apps/${encodeURIComponent(vue.projet)}/${encodeURIComponent(vue.nom)}/ouvrir`;
  return vue.chemin ? `${base}?chemin=${encodeURIComponent(vue.chemin)}` : base;
}

/** La liste des onglets après qu'une vue arrive : même objet, même onglet. */
export function fusionnerVues(vues, vue) {
  const reste = (vues || []).filter((v) => v.id !== vue.id);
  return [...reste, vue];
}

/** Ce qu'affiche le bouton d'épingle d'une vue, et ce qu'il fera. */
export function libelleEpingle(vue) {
  return vue?.epingle === "projet"
    ? { texte: "Épinglée au projet", titre: "Ne garder que dans cette conversation", suivante: "conversation" }
    : { texte: "Épingler au projet", titre: "Montrer dans toutes les conversations du projet", suivante: "projet" };
}

/** Les services du catalogue, lus sur l'Atelier (repli si `api` ne les porte pas). */
async function lireBureaux() {
  const res = await fetch("/v1/bureaux", { headers: { "X-Atelier-Interface": "1", Accept: "application/json" } });
  if (!res.ok) throw new Error(`services illisibles (${res.status})`);
  return res.json();
}

function el(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte != null) n.textContent = String(texte);
  return n;
}

function bouton(texte, titre, action, classe = "ghost panneau-btn") {
  const b = el("button", classe, texte);
  b.type = "button";
  if (titre) {
    b.title = titre;
    b.setAttribute("aria-label", titre);
  }
  b.addEventListener("click", action);
  return b;
}

/**
 * @param {object} ctx
 * @param {object} ctx.state   l'état de l'application
 * @param {object} ctx.api     le module `api.js`
 * @param {() => void} ctx.render
 */
export function createPanneauView(ctx) {
  const { state, api, render } = ctx;
  const iframes = new Map();
  let sessionChargee = null;
  let chargement = null;
  const local = { vues: [], actif: null, ouvert: false, catalogue: false, erreur: "", rayon: "creations" };

  const racine = () => document.getElementById("panneau");
  const vueCode = () => document.getElementById("view-code");

  function ouvrir(oui) {
    local.ouvert = !!oui;
    rendre();
  }

  async function charger(sessionId) {
    sessionChargee = sessionId;
    for (const f of iframes.values()) f.remove();
    iframes.clear();
    local.vues = [];
    local.actif = null;
    local.catalogue = false;
    local.erreur = "";
    if (!sessionId) {
      local.ouvert = false;
      rendre();
      return;
    }
    const demande = api.panneauVues(sessionId);
    chargement = demande;
    try {
      const rendu = await demande;
      if (chargement !== demande || sessionChargee !== sessionId) return;
      local.vues = rendu.vues || [];
      local.actif = local.vues.length ? local.vues[local.vues.length - 1].id : null;
    } catch (err) {
      local.erreur = err.message || String(err);
    }
    rendre();
  }

  /** Une vue arrive (Montrer, ou le catalogue) : son onglet s'active, le panneau s'ouvre. */
  function montrer(vue, { recharger = true } = {}) {
    if (!vue?.id) return;
    const deja = local.vues.some((v) => v.id === vue.id);
    local.vues = fusionnerVues(local.vues, vue);
    local.actif = vue.id;
    local.ouvert = true;
    local.catalogue = false;
    // Montrée à nouveau après une modification : on la recharge.
    const cadre = iframes.get(vue.id);
    if (deja && recharger && cadre) cadre.src = adresseDeLaVue(vue);
    rendre();
  }

  /** Événement `panneau_montrer` du flux en direct de la conversation. */
  function surEvenement(ev) {
    if (ev?.cause !== "panneau_montrer" || !ev.text) return false;
    if (ev.session_id && ev.session_id !== state.sessionId) return true;
    try {
      const vue = JSON.parse(ev.text);
      // Un service (bureau, éditeur) ne s'ouvre que sur un geste (J-f).
      if (estUnService(vue)) return true;
      montrer(vue);
    } catch {
      /* un descripteur illisible ne s'affiche pas */
    }
    return true;
  }

  async function enregistrer(vue) {
    try {
      const propre = await api.panneauEnregistrer(state.sessionId, vue);
      montrer(propre, { recharger: false });
    } catch (err) {
      local.erreur = err.message || String(err);
      rendre();
    }
  }

  async function fermerOnglet(vue) {
    local.vues = local.vues.filter((v) => v.id !== vue.id);
    iframes.get(vue.id)?.remove();
    iframes.delete(vue.id);
    if (local.actif === vue.id) local.actif = local.vues.length ? local.vues[local.vues.length - 1].id : null;
    if (!local.vues.length) local.ouvert = false;
    rendre();
    // Un service n'est pas enregistré : rien à retirer côté Atelier.
    if (estUnService(vue)) return;
    try {
      await api.panneauRetirer(state.sessionId, vue.id);
    } catch (err) {
      local.erreur = err.message || String(err);
      rendre();
    }
  }

  function detacher(vue) {
    window.open(adresseDeLaVue(vue), "_blank", "noopener");
  }

  function iframePour(vue) {
    let f = iframes.get(vue.id);
    if (!f) {
      f = document.createElement("iframe");
      f.className = "panneau-cadre";
      f.setAttribute("sandbox", BAC_A_SABLE);
      f.setAttribute("referrerpolicy", "no-referrer");
      f.setAttribute("allow", "clipboard-write; fullscreen");
      f.title = vue.titre || vue.nom;
      f.src = adresseDeLaVue(vue);
      iframes.set(vue.id, f);
    }
    return f;
  }

  /** Le catalogue : deux rayons, les créations du projet et les bureaux des connecteurs. */
  function rendreCatalogue(zone, options = {}) {
    const rayons = el("div", "panneau-onglets");
    rayons.setAttribute("role", "tablist");
    rayons.setAttribute("aria-label", "Catalogue du panneau");
    const contenu = el("div", "panneau-rayon");
    for (const [cle, libelle] of [["creations", "Créations"], ["bureaux", "Bureaux"]]) {
      const b = el("button", "panneau-onglet", libelle);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", local.rayon === cle ? "true" : "false");
      b.addEventListener("click", () => {
        if (local.rayon === cle) return;
        local.rayon = cle;
        rendreCatalogue(zone);
      });
      rayons.appendChild(b);
    }
    zone.replaceChildren(rayons, contenu);
    if (local.rayon === "bureaux") rendreBureaux(contenu);
    else rendreCreations(contenu, options);
  }

  /** Le rayon « Bureaux » : les services que déclarent les connecteurs actifs. */
  function rendreBureaux(zone) {
    zone.replaceChildren(el("p", "apps-note", "Chargement des bureaux…"));
    const lire = api.listBureaux || lireBureaux;
    Promise.resolve()
      .then(() => lire())
      .then((etat) => {
        const liste = el("div", "apps-liste");
        liste.appendChild(el("div", "apps-titre", "Bureaux et éditeurs des connecteurs"));
        const fiches = etat?.vues || [];
        if (!etat?.expose) {
          liste.appendChild(
            el("p", "apps-note", "Pas d'hôte des applications sur cette installation : les bureaux ne s'ouvrent pas."),
          );
        } else if (!fiches.length) {
          liste.appendChild(el("p", "apps-note", "Aucun connecteur actif ne propose de bureau."));
        }
        for (const f of fiches) {
          const ligne = el("div", "apps-ligne");
          ligne.dataset.service = `${f.connecteur}/${f.nom}`;
          ligne.appendChild(el("span", "apps-nom", f.titre || f.nom));
          ligne.appendChild(el("span", "apps-etat", f.genre === "bureau" ? "bureau" : "éditeur"));
          const b = bouton("Montrer", "Afficher dans le panneau, à côté du fil", () =>
            montrer(vueDeService(f), { recharger: false }),
          );
          if (!etat.expose) b.setAttribute("disabled", "");
          ligne.appendChild(b);
          liste.appendChild(ligne);
        }
        zone.replaceChildren(liste);
      })
      .catch((err) => zone.replaceChildren(el("p", "apps-note", `Bureaux illisibles : ${err.message}`)));
  }

  function rendreCreations(zone, { relecture = false } = {}) {
    const slug = state.slug || state.sessions?.find((s) => s.session_id === state.sessionId)?.slug || "";
    // Une relecture (après un geste, ou pendant qu'une création démarre) garde
    // la liste affichée : la remplacer par « Chargement… » chaque seconde
    // ferait clignoter le panneau.
    if (!relecture) zone.replaceChildren(el("p", "apps-note", "Chargement des créations…"));
    const recharger = () => rendreCreations(zone, { relecture: true });
    api
      .listApps(slug)
      .then((etat) =>
        rendrePanneauApplications(
          zone,
          { slug, expose: etat.expose, artefacts: etat.artefacts, artefactsUrl: api.artifactsUrl(slug) },
          {
            demarrer: (nom) => api.startApp(slug, nom),
            arreter: (nom) => api.stopApp(slug, nom),
            journal: (nom) => api.appJournal(slug, nom, 200),
            copier: (texte) => (navigator.clipboard ? navigator.clipboard.writeText(texte) : Promise.resolve()),
            montrer: (f) =>
              enregistrer({ projet: slug, nom: f.nom, titre: f.titre || f.nom, epingle: "conversation" }),
            recharger,
          },
        ),
      )
      .catch((err) => zone.replaceChildren(el("p", "apps-note", `Créations illisibles : ${err.message}`)));
  }

  /** Dessine le panneau sans jamais recréer une iframe ouverte. */
  function rendre() {
    const aside = racine();
    const code = vueCode();
    if (!aside || !code) return;
    const visible = state.view === "code" && !!state.sessionId && local.ouvert;
    aside.hidden = !visible;
    code.classList.toggle("panneau-ouvert", visible);
    if (!visible) {
      // Panneau replié : aucun bureau ne tourne pour rien.
      for (const v of local.vues) {
        if (!estUnFluxVivant(v)) continue;
        iframes.get(v.id)?.remove();
        iframes.delete(v.id);
      }
    }
    const bascule = document.getElementById("session-panneau-button");
    if (bascule) {
      bascule.hidden = !(state.view === "code" && state.sessionId);
      bascule.setAttribute("aria-expanded", visible ? "true" : "false");
      bascule.textContent = local.vues.length ? `Panneau (${local.vues.length})` : "Panneau";
    }
    if (!visible) return;

    const onglets = document.getElementById("panneau-onglets");
    onglets.replaceChildren(
      ...local.vues.map((v) => {
        const b = el("button", "panneau-onglet", v.titre || v.nom);
        b.type = "button";
        b.setAttribute("role", "tab");
        b.setAttribute("aria-selected", v.id === local.actif ? "true" : "false");
        b.title = v.epingle === "projet" ? `${v.titre} — épinglée au projet` : v.titre;
        if (v.epingle === "projet") b.classList.add("panneau-onglet-projet");
        if (v.par === "agent") b.classList.add("panneau-onglet-agent");
        b.addEventListener("click", () => {
          local.actif = v.id;
          local.catalogue = false;
          rendre();
        });
        return b;
      }),
    );

    const active = local.vues.find((v) => v.id === local.actif) || null;
    const outils = document.getElementById("panneau-outils");
    if (active) {
      const epingle = libelleEpingle(active);
      const gestes = [];
      // Un service n'est pas épinglé : il ne revient pas seul (J-f).
      if (!estUnService(active)) {
        gestes.push(
          bouton(epingle.texte, epingle.titre, () => enregistrer({ ...active, epingle: epingle.suivante }),
            `ghost panneau-btn${active.epingle === "projet" ? " panneau-btn-actif" : ""}`),
        );
      }
      gestes.push(
        bouton("Recharger", estUnService(active) ? "Recharger cet onglet" : "Recharger cette création", () => {
          const f = iframes.get(active.id);
          if (f) f.src = adresseDeLaVue(active);
        }),
        bouton("Détacher", "Ouvrir dans un onglet du navigateur", () => detacher(active)),
        bouton("Fermer", "Fermer cet onglet du panneau", () => fermerOnglet(active)),
      );
      outils.replaceChildren(...gestes);
      outils.hidden = false;
    } else {
      outils.replaceChildren();
      outils.hidden = true;
    }

    const catalogue = document.getElementById("panneau-catalogue");
    const montrerCatalogue = local.catalogue || !local.vues.length;
    if (montrerCatalogue && catalogue.hidden) rendreCatalogue(catalogue);
    catalogue.hidden = !montrerCatalogue;

    const corps = document.getElementById("panneau-corps");
    for (const v of local.vues) {
      const masquee = montrerCatalogue || v.id !== local.actif;
      if (masquee && estUnFluxVivant(v)) {
        // Un bureau masqué ne tourne pas : son cadre part, le flux s'arrête.
        iframes.get(v.id)?.remove();
        iframes.delete(v.id);
        continue;
      }
      const f = iframePour(v);
      if (f.parentNode !== corps) corps.appendChild(f);
      f.hidden = masquee;
    }
    for (const [id, f] of iframes) {
      if (!local.vues.some((v) => v.id === id)) {
        f.remove();
        iframes.delete(id);
      }
    }
    const note = document.getElementById("panneau-note");
    note.textContent = local.erreur;
    note.hidden = !local.erreur;
  }

  function bind() {
    document.getElementById("session-panneau-button")?.addEventListener("click", () => ouvrir(!local.ouvert));
    document.getElementById("panneau-ajouter")?.addEventListener("click", () => {
      local.catalogue = !local.catalogue;
      rendre();
    });
    document.getElementById("panneau-replier")?.addEventListener("click", () => ouvrir(false));
  }

  /** Appelé à chaque rendu : charge le panneau de la conversation qui s'ouvre. */
  function renderPanneau() {
    // Changer d'onglet de navigation ne ferme pas le panneau : seul un
    // changement de conversation le recharge.
    const sid = state.sessionId || null;
    if (sid !== sessionChargee) {
      charger(sid);
      return;
    }
    rendre();
  }

  return { bind, renderPanneau, montrer, surEvenement, ouvrir };
}
