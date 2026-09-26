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
 */

import { rendrePanneauApplications } from "./applications.js";

const BAC_A_SABLE =
  "allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals allow-same-origin";

// Sous 720 px (règle CSS), le panneau devient une feuille plein écran.

/** L'adresse, sur l'Atelier, qui ouvre la vue par le passage. */
export function adresseDeLaVue(vue) {
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
  const local = { vues: [], actif: null, ouvert: false, catalogue: false, erreur: "" };

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
      montrer(JSON.parse(ev.text));
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

  function rendreCatalogue(zone, { relecture = false } = {}) {
    const slug = state.slug || state.sessions?.find((s) => s.session_id === state.sessionId)?.slug || "";
    // Une relecture (après un geste, ou pendant qu'une création démarre) garde
    // la liste affichée : la remplacer par « Chargement… » chaque seconde
    // ferait clignoter le panneau.
    if (!relecture) zone.replaceChildren(el("p", "apps-note", "Chargement des créations…"));
    const recharger = () => rendreCatalogue(zone, { relecture: true });
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
      outils.replaceChildren(
        bouton(epingle.texte, epingle.titre, () => enregistrer({ ...active, epingle: epingle.suivante }),
          `ghost panneau-btn${active.epingle === "projet" ? " panneau-btn-actif" : ""}`),
        bouton("Recharger", "Recharger cette création", () => {
          const f = iframes.get(active.id);
          if (f) f.src = adresseDeLaVue(active);
        }),
        bouton("Détacher", "Ouvrir dans un onglet du navigateur", () => detacher(active)),
        bouton("Fermer", "Fermer cet onglet du panneau", () => fermerOnglet(active)),
      );
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
      const f = iframePour(v);
      if (f.parentNode !== corps) corps.appendChild(f);
      f.hidden = montrerCatalogue || v.id !== local.actif;
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
