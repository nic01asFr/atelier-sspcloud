/**
 * « Ma mémoire » : ce que l'Atelier retient de vous, et de quoi le corriger (A-7).
 *
 * Quatre parties, lues par la commande `atelier_memoire` (wikichat tient la
 * mémoire, l'Atelier en est la porte) :
 *   - qui vous êtes, vos préférences, ce que l'Assistant a compris : rien n'y
 *     entre sans votre accord, donné dans « À valider » ;
 *   - les faits retenus d'office : extraits de vos conversations par le code
 *     (un projet créé, une création, un agent lancé, une décision), jamais
 *     par un modèle.
 * Chaque ligne dit d'où elle vient, et porte « Corriger » et « Oublier »
 * (commandes réservées à la personne : `atelier_memoire_corriger`,
 * `atelier_memoire_oublier`). Un fait oublié n'est plus réenregistré.
 *
 * Les mots suivent le lexique (decisions.md S2).
 */

import { dateHumaine } from "./gardiens.js";

export const PARTIES = [
  { type: "profil", titre: "Qui vous êtes", vide: "Rien encore. Ce que vous validez dans « À valider » apparaît ici." },
  { type: "preference", titre: "Vos préférences", vide: "Aucune préférence retenue." },
  { type: "interpretation", titre: "Ce que l’Assistant a compris", vide: "Rien de retenu." },
  { type: "fait", titre: "Faits retenus d’office", vide: "Aucun fait pour l’instant : ils arrivent quand une conversation se termine." },
];

/** D'où vient une ligne, en mots. */
export function origineLisible(el, maintenant) {
  const source = el?.source && typeof el.source === "object" ? el.source : {};
  const morceaux = [];
  if (el?.type === "fait" || el?.par === "code") morceaux.push("extrait par le code");
  else morceaux.push("validé par vous");
  if (source.projet) morceaux.push(`projet « ${source.projet} »`);
  if (source.conversation) morceaux.push(`conversation ${String(source.conversation).slice(0, 8)}`);
  const quand = el?.modifie_le || el?.cree_le;
  if (quand) morceaux.push(dateHumaine(quand, maintenant));
  if (Array.isArray(el?.historique) && el.historique.length) morceaux.push("corrigé");
  return morceaux.join(" · ");
}

function bouton(libelle, classe, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = libelle;
  b.addEventListener("click", onClick);
  return b;
}

function ligne(el, m, actions, maintenant) {
  const li = document.createElement("li");
  li.className = "memoire-ligne";
  li.dataset.id = String(el.id || "");
  if (m.enEdition === el.id) {
    const champ = document.createElement("input");
    champ.type = "text";
    champ.className = "memoire-champ";
    champ.value = m.brouillon ?? String(el.texte || "");
    champ.setAttribute("aria-label", "Nouveau texte");
    champ.addEventListener("input", () => {
      m.brouillon = champ.value;
    });
    li.appendChild(champ);
    li.appendChild(bouton("Enregistrer", "btn-sm", () => actions.corriger(el.id, m.brouillon ?? champ.value)));
    li.appendChild(bouton("Annuler", "ghost btn-sm", () => actions.editer(null)));
    return li;
  }
  const texte = document.createElement("span");
  texte.className = "memoire-texte";
  texte.textContent = String(el.texte || "");
  const origine = document.createElement("span");
  origine.className = "memoire-origine";
  origine.textContent = origineLisible(el, maintenant);
  li.appendChild(texte);
  li.appendChild(origine);
  const gestes = document.createElement("span");
  gestes.className = "memoire-gestes";
  if (m.aOublier === el.id) {
    gestes.appendChild(bouton("Confirmer l’oubli", "danger btn-sm", () => actions.oublier(el.id)));
    gestes.appendChild(bouton("Garder", "ghost btn-sm", () => actions.demanderOubli(null)));
  } else {
    gestes.appendChild(bouton("Corriger", "ghost btn-sm", () => actions.editer(el.id)));
    gestes.appendChild(bouton("Oublier", "ghost btn-sm", () => actions.demanderOubli(el.id)));
  }
  li.appendChild(gestes);
  return li;
}

/**
 * L'écran « Ma mémoire ». `actions` : `charger()`, `editer(id|null)`,
 * `corriger(id, texte)`, `demanderOubli(id|null)`, `oublier(id)`, `voirAValider()`.
 */
export function rendreMemoire(corps, state, actions, { maintenant } = {}) {
  const m = state.memoire || {};
  corps.innerHTML = "";

  const tete = document.createElement("header");
  tete.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Ma mémoire";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Ce que l’Atelier retient de vous. Rien n’y entre sans votre accord, sauf les faits tirés de vos conversations par le code. Vous pouvez tout corriger ou oublier.";
  tete.appendChild(h);
  tete.appendChild(lead);
  corps.appendChild(tete);

  if (m.erreur) {
    const p = document.createElement("p");
    p.className = "agent-form-error";
    p.textContent = m.erreur;
    corps.appendChild(p);
  }
  if (!m.charge) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = m.erreur ? "" : "Lecture de la mémoire…";
    if (p.textContent) corps.appendChild(p);
    return corps;
  }

  const donnees = m.donnees || {};
  const attente = Array.isArray(donnees.propositions_en_attente) ? donnees.propositions_en_attente : [];
  if (attente.length) {
    const encart = document.createElement("p");
    encart.className = "memoire-attente";
    encart.textContent = `${attente.length} proposition${attente.length > 1 ? "s" : ""} attend${attente.length > 1 ? "ent" : ""} votre accord. `;
    encart.appendChild(bouton("Voir dans « À valider »", "ghost btn-sm", () => actions.voirAValider()));
    corps.appendChild(encart);
  }

  const elements = Array.isArray(donnees.elements) ? donnees.elements : [];
  for (const partie of PARTIES) {
    const section = document.createElement("section");
    section.className = "memoire-partie";
    section.dataset.type = partie.type;
    const h3 = document.createElement("h3");
    h3.textContent = partie.titre;
    section.appendChild(h3);
    const siens = elements.filter((e) => e.type === partie.type);
    if (!siens.length) {
      const p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = partie.vide;
      section.appendChild(p);
    } else {
      const ul = document.createElement("ul");
      ul.className = "memoire-liste";
      for (const el of siens) ul.appendChild(ligne(el, m, actions, maintenant));
      section.appendChild(ul);
    }
    corps.appendChild(section);
  }

  const pied = document.createElement("p");
  pied.className = "empty-hint";
  const fiches = donnees.fiches ?? null;
  pied.textContent =
    (fiches !== null ? `${fiches} conversation${fiches > 1 ? "s" : ""} fichée${fiches > 1 ? "s" : ""}. ` : "") +
    "Les conversations se retrouvent par leur fiche ; leur texte n’est jamais recopié ici.";
  corps.appendChild(pied);
  return corps;
}

/**
 * Les gestes de l'écran, par les commandes du catalogue (la session de
 * l'interface vaut « la personne »).
 * @param {{ state: object, api: { executerCommande: Function }, render: Function, naviguer?: Function }} deps
 */
export function createMemoireActions({ state, api, render, naviguer }) {
  const m = () => {
    if (!state.memoire) state.memoire = { charge: false, erreur: "", donnees: null, enEdition: null, brouillon: null, aOublier: null };
    return state.memoire;
  };

  async function charger() {
    const etat = m();
    try {
      const r = await api.executerCommande("atelier_memoire", {});
      etat.donnees = r?.resultat || {};
      etat.erreur = "";
    } catch (err) {
      etat.erreur = err?.message || String(err);
    }
    etat.charge = true;
    render();
  }

  async function geste(nom, args) {
    const etat = m();
    try {
      await api.executerCommande(nom, args);
      etat.erreur = "";
    } catch (err) {
      etat.erreur = err?.message || String(err);
    }
    etat.enEdition = null;
    etat.brouillon = null;
    etat.aOublier = null;
    await charger();
  }

  return {
    charger,
    editer(id) {
      const etat = m();
      etat.enEdition = id;
      etat.brouillon = null;
      etat.aOublier = null;
      render();
    },
    corriger(id, texte) {
      const propre = String(texte || "").trim();
      if (!propre) {
        m().erreur = "Le texte ne peut pas être vide : pour l’effacer, utilisez « Oublier ».";
        render();
        return Promise.resolve();
      }
      return geste("atelier_memoire_corriger", { id, texte: propre });
    },
    demanderOubli(id) {
      const etat = m();
      etat.aOublier = id;
      etat.enEdition = null;
      render();
    },
    oublier(id) {
      return geste("atelier_memoire_oublier", { id });
    },
    voirAValider() {
      if (naviguer) naviguer("a-valider");
    },
  };
}
