/**
 * Les agents lancés par l'Atelier, en cours et récents (équipe L, lot D et G5).
 *
 * wikichat (réveil sur mention, tâche automatique, tâche en plusieurs étapes)
 * et les gardiens (réparateurs) ne lancent plus `claude` eux-mêmes : ils le
 * demandent à l'Atelier, qui tient une fiche par lancement (`GET
 * /v1/lancements`). La vue Agents les montre ici : d'où ils viennent, en
 * mots ; le projet, l'état, la durée, la branche ; « Arrêter » tant qu'ils
 * tournent ; et, pour un réparateur, le lien vers sa proposition.
 */

import { dateHumaine, libelleControle } from "./gardiens.js";

const ETATS = {
  en_cours: { texte: "En cours", ton: "busy" },
  fini: { texte: "Terminé", ton: "ok" },
  echec: { texte: "Échec", ton: "err" },
  delai: { texte: "Arrêté : trop long", ton: "warn" },
  arrete: { texte: "Arrêté", ton: "off" },
  interrompu: { texte: "Interrompu", ton: "warn" },
};

export function libelleEtatLancement(etat) {
  return ETATS[etat] || { texte: String(etat || "—"), ton: "off" };
}

/** `wikichat:trigger:evt-wake-any:mention`, `wikichat:routine:x`, `gardien:sante.ci-main`… en mots. */
export function libelleOrigine(origine) {
  const o = String(origine || "");
  if (o.startsWith("gardien:")) {
    const controle = o.slice("gardien:".length);
    return `Gardien réparateur (« ${libelleControle(controle)} »)`;
  }
  const reste = o.startsWith("wikichat:") ? o.slice("wikichat:".length) : o;
  if (/^trigger:evt-wake-any(:|$)/.test(reste)) return "Réveil sur mention";
  let m = reste.match(/^trigger:(.+)$/);
  if (m) return `Tâche automatique « ${m[1]} »`;
  m = reste.match(/^routine:(.+)$/);
  if (m) return `Tâche en plusieurs étapes « ${m[1]} »`;
  if (o.startsWith("wikichat:")) return `wikichat (${reste})`;
  return o || "—";
}

/** « 3 min 12 s », « 1 h 04 », à partir des horodatages de la fiche. */
export function dureeHumaine(debut, fin, maintenant = Date.now()) {
  const d = Date.parse(debut || "");
  if (Number.isNaN(d)) return "—";
  const f = fin ? Date.parse(fin) : maintenant;
  const s = Math.max(0, Math.round(((Number.isNaN(f) ? maintenant : f) - d) / 1000));
  if (s < 60) return `${s} s`;
  const min = Math.floor(s / 60);
  if (min < 60) return `${min} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
}

/** Les en cours d'abord, puis les plus récents ; `garder` au plus. */
export function trierLancements(liste, garder = 12) {
  const tous = [...(liste || [])];
  tous.sort((a, b) => {
    const ea = a.etat === "en_cours" ? 0 : 1;
    const eb = b.etat === "en_cours" ? 0 : 1;
    if (ea !== eb) return ea - eb;
    return String(b.cree_le || "").localeCompare(String(a.cree_le || ""));
  });
  return tous.slice(0, garder);
}

function bouton(texte, classe, action, desactive = false) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = texte;
  b.disabled = !!desactive;
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    action();
  });
  return b;
}

/**
 * La section « En cours et récents ». `actions.arreter(id)`,
 * `actions.ouvrirProposition(id)`, `actions.ouvrirConversation(projet, id)`.
 */
export function listeLancements(conteneur, donnees, { actions, enCours = "", maintenant } = {}) {
  conteneur.innerHTML = "";
  if (donnees?.absent) {
    const p = document.createElement("p");
    p.className = "agent-note";
    p.textContent = "Les lancements par l’Atelier ne sont pas encore servis ici.";
    conteneur.appendChild(p);
    return conteneur;
  }
  const liste = trierLancements(donnees?.lancements);
  if (!liste.length) {
    const p = document.createElement("p");
    p.className = "agent-note";
    p.textContent = "Aucun agent lancé récemment par wikichat ou par les gardiens.";
    conteneur.appendChild(p);
    return conteneur;
  }
  const ul = document.createElement("ul");
  ul.className = "automates-liste";
  for (const l of liste) {
    const li = document.createElement("li");
    li.className = "automate lancement";
    li.dataset.lancement = l.id;
    const texte = document.createElement("div");
    texte.className = "automate-texte";
    const rang = document.createElement("div");
    rang.className = "agent-card-title-row";
    const e = libelleEtatLancement(l.etat);
    const point = document.createElement("span");
    point.className = `status-dot status-dot-${e.ton}`;
    point.title = e.texte;
    point.setAttribute("aria-label", e.texte);
    rang.appendChild(point);
    const nom = document.createElement("strong");
    nom.textContent = libelleOrigine(l.origine);
    rang.appendChild(nom);
    const etat = document.createElement("span");
    etat.className = "automate-genre";
    etat.textContent = e.texte;
    rang.appendChild(etat);
    texte.appendChild(rang);

    const sous = document.createElement("span");
    sous.className = "agent-queue-sub";
    const bouts = [];
    if (l.projet) bouts.push(`projet ${l.projet}`);
    bouts.push(`${l.etat === "en_cours" ? "depuis" : "durée"} ${dureeHumaine(l.cree_le, l.fini_le, maintenant)}`);
    if (l.cree_le) bouts.push(`lancé ${dateHumaine(l.cree_le, maintenant)}`);
    if (l.branche) bouts.push(`branche ${l.branche}`);
    sous.textContent = bouts.join(" · ");
    texte.appendChild(sous);
    if (l.reparation?.resume) {
      const constat = document.createElement("span");
      constat.className = "agent-queue-sub";
      constat.textContent = `Constat : ${l.reparation.resume}`;
      texte.appendChild(constat);
    }
    if (l.erreur) {
      const err = document.createElement("span");
      err.className = "gardien-preuve";
      err.textContent = l.erreur;
      texte.appendChild(err);
    }
    li.appendChild(texte);

    const btns = document.createElement("div");
    btns.className = "agent-queue-actions";
    if (l.proposition) {
      btns.appendChild(bouton("Voir sa proposition", "primary btn-sm", () => actions.ouvrirProposition?.(l.proposition)));
    }
    if (l.conversation) {
      btns.appendChild(bouton("Ouvrir", "ghost btn-sm", () => actions.ouvrirConversation?.(l.projet, l.conversation)));
    }
    if (l.etat === "en_cours") {
      btns.appendChild(bouton("Arrêter", "ghost btn-sm gardien-couper", () => actions.arreter?.(l.id), enCours === l.id));
    }
    li.appendChild(btns);
    ul.appendChild(li);
  }
  conteneur.appendChild(ul);
  return conteneur;
}
