/**
 * Les gardiens et les tâches automatiques, dans la vue Agents.
 *
 * Décision J-i (26/09) : pas de page Gardiens. Un gardien est un agent
 * spécifique — une vérification automatique, sans IA — montré comme les
 * agents planifiés : une carte dans la liste, une fiche au clic, avec ses
 * gestes « Lancer maintenant » et « Couper / Réactiver ».
 *
 * Tout texte suit le lexique (decisions.md S2) : « gardien », « tâche
 * automatique », « création », « à valider ». Les identifiants internes des
 * contrôles ne s'affichent qu'en appoint, en petit.
 */

const GARDIENS = {
  sante: {
    nom: "Santé",
    role:
      "Vérifie que l’Atelier, le relais du modèle, wikichat et vos créations répondent, et relance ce qui est tombé, dans des limites fixées.",
  },
  securite: {
    nom: "Sécurité",
    role:
      "Cherche ce qui serait ouvert à tous, les secrets laissés en clair et les fichiers sensibles trop lisibles. Il prévient ; il ne corrige rien seul.",
  },
  coherence: {
    nom: "Cohérence",
    role: "Vérifie que ce qui est déclaré correspond à ce qui tourne vraiment.",
  },
  entretien: {
    nom: "Entretien",
    role:
      "Fait l’inventaire de tout ce qui se lance seul et signale ce qui n’a pas de limite de dépense.",
  },
};

const CONTROLES = {
  "entretien.automates": "Inventaire des tâches automatiques",
  "sante.atelier": "L’Atelier répond",
  "sante.relais": "Le relais du modèle répond",
  "sante.wikichat": "wikichat répond",
  "sante.creations": "Vos créations répondent",
  "sante.ci-main": "Les tests de la version principale passent",
  "sante.image-main": "Le code en service est à jour",
  "sante.disque": "Place sur le disque",
  "securite.ecoutes": "Rien d’ouvert à tous",
  "securite.secrets-en-clair": "Aucun secret laissé en clair",
  "securite.droits": "Fichiers sensibles bien protégés",
  "securite.bypass": "Aucun agent sans garde-fou",
  "gardiens.homme-mort": "Un contrôle n’a pas tourné à l’heure",
};

const GESTES = {
  relancer_atelier: "Relancer l’Atelier",
  relancer_wikichat: "Relancer wikichat",
  relancer_relais: "Relancer le relais du modèle",
};

const ETATS = {
  ok: { texte: "Tout va bien", ton: "ok" },
  attention: { texte: "À surveiller", ton: "warn" },
  alerte: { texte: "Alerte", ton: "err" },
  coupe: { texte: "Coupé", ton: "off" },
  inconnu: { texte: "Pas encore passé", ton: "off" },
  actif: { texte: "Active", ton: "ok" },
  sans_declaration: { texte: "Sans limite de dépense", ton: "warn" },
  absent: { texte: "Absent", ton: "err" },
  en_echec: { texte: "En échec", ton: "err" },
};

export function nomDuGardien(id) {
  return GARDIENS[id]?.nom || String(id || "");
}

export function roleDuGardien(id) {
  return GARDIENS[id]?.role || "Une vérification automatique.";
}

export function libelleControle(id) {
  return CONTROLES[id] || String(id || "");
}

// Les résumés que l'inventaire des gardiens écrit portent des mots internes :
// on les dit avec ceux de l'interface.
const RESUMES = [
  [/^trigger actif sans budget déclaré$/, "tâche automatique active sans limite de dépense"],
  [/^routine actif sans budget déclaré$/, "tâche en plusieurs étapes active sans limite de dépense"],
  [/^processus qui écoute sans déclaration$/, "service qui écoute sans être déclaré"],
];

export function resumeLisible(texte) {
  const t = String(texte || "");
  for (const [motif, lisible] of RESUMES) if (motif.test(t)) return lisible;
  return t.replace(/\btriggers?\b/g, "tâche automatique").replace(/\broutines?\b/g, "tâche automatique");
}

/** L'objet d'une alerte : un contrôle, une tâche de wikichat, un port. */
export function libelleObjet(objet) {
  const o = String(objet || "");
  let m = o.match(/^wikichat\.trigger\.(.+)$/);
  if (m) return `tâche « ${m[1]} »`;
  m = o.match(/^wikichat\.routine\.(.+)$/);
  if (m) return `tâche en plusieurs étapes « ${m[1]} »`;
  m = o.match(/^demon\.port-(\d+)$/);
  if (m) return `port ${m[1]}`;
  m = o.match(/^creation\.(.+)$/);
  if (m) return `création « ${m[1]} »`;
  return libelleControle(o);
}

export function libelleGeste(nom) {
  return GESTES[nom] || String(nom || "");
}

export function libelleEtat(etat, genre = "") {
  if (etat === "coupe" && genre && genre !== "gardien") {
    return { texte: "Coupée", ton: "off" };
  }
  return ETATS[etat] || { texte: String(etat || "—"), ton: "off" };
}

const pad = (n) => String(n).padStart(2, "0");

/** « chaque minute », « toutes les 15 min », « chaque jour à 07:15 »… */
export function quandHumain(quand) {
  if (!quand || typeof quand !== "object") return "—";
  if (quand.toutes_les_min) {
    const n = Number(quand.toutes_les_min);
    if (n === 1) return "chaque minute";
    if (n < 60) return `toutes les ${n} min`;
    if (n === 60) return "toutes les heures";
    if (n % 60 === 0) return `toutes les ${n / 60} h`;
    return `toutes les ${n} min`;
  }
  if (quand.cron) {
    const p = String(quand.cron).trim().split(/\s+/);
    if (p.length === 5) {
      const [mi, h, jm, mo, js] = p;
      if (h.startsWith("*/") && /^\d+$/.test(mi)) return `toutes les ${h.slice(2)} h`;
      if (/^\d+$/.test(mi) && /^\d+$/.test(h) && jm === "*" && mo === "*") {
        const heure = `${pad(h)}:${pad(mi)}`;
        if (js === "*") return `chaque jour à ${heure}`;
        if (js === "1-5") return `en semaine à ${heure}`;
        return `certains jours à ${heure}`;
      }
    }
    return "selon un horaire";
  }
  if (quand.evenement) return "quand un événement survient";
  if (quand.par) return "lancée par une tâche automatique";
  if (quand.en_continu) return "en continu";
  return "—";
}

/** « il y a 3 min », « dans 12 min », sinon « 25/09 à 20:00 ». */
export function dateHumaine(iso, maintenant = Date.now()) {
  if (!iso) return "jamais";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const ecart = Math.round((d.getTime() - maintenant) / 60000);
  if (Math.abs(ecart) < 1) return "à l’instant";
  if (ecart < 0 && ecart > -60) return `il y a ${-ecart} min`;
  if (ecart > 0 && ecart < 60) return `dans ${ecart} min`;
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} à ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Le plafond d'une tâche automatique, en mots. */
export function plafondHumain(automate) {
  const p = automate?.plafond || {};
  if (p.jetons === 0) return "sans IA, aucune dépense";
  const morceaux = [];
  if (p.par_jour) morceaux.push(`${p.par_jour} fois par jour au plus`);
  if (p.redemarrages) {
    morceaux.push(
      `${p.redemarrages} redémarrages${p.fenetre_min ? ` en ${p.fenetre_min} min` : ""} au plus`
    );
  }
  if (automate?.genre === "trigger" || automate?.genre === "routine") {
    morceaux.push(p.budget ? "limite de dépense déclarée" : "sans limite de dépense");
  }
  return morceaux.length ? morceaux.join(", ") : "—";
}

const GENRES = {
  gardien: "Gardien",
  trigger: "Tâche automatique",
  routine: "Tâche en plusieurs étapes",
  creation: "Création servie",
};

export function libelleGenre(automate) {
  if (automate?.genre === "trigger" && automate?.agent) return "Agent planifié";
  return GENRES[automate?.genre] || "Tâche automatique";
}

export function titreAutomate(automate) {
  if (automate?.genre === "gardien") return `Gardien ${nomDuGardien(automate.titre).toLowerCase()}`;
  if (automate?.genre === "creation" && automate?.projet) {
    return `${automate.titre} (projet ${automate.projet})`;
  }
  return automate?.titre || automate?.id || "";
}

const LIBELLES_GESTES = {
  lancer: "Lancer maintenant",
  couper: "Couper",
  reactiver: "Réactiver",
  activer: "Activer",
};

function point(ton, titre) {
  const el = document.createElement("span");
  el.className = `status-dot status-dot-${ton || "off"}`;
  el.title = titre || "";
  el.setAttribute("aria-label", titre || "état");
  return el;
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

function ligneCle(k, v) {
  const li = document.createElement("li");
  const a = document.createElement("span");
  a.className = "agent-kv-k";
  a.textContent = k;
  const b = document.createElement("span");
  b.className = "agent-kv-v";
  b.textContent = v;
  li.appendChild(a);
  li.appendChild(b);
  return li;
}

function section(titre) {
  const sec = document.createElement("section");
  sec.className = "agent-section";
  const h = document.createElement("h3");
  h.className = "connectors-sub";
  h.textContent = titre;
  sec.appendChild(h);
  return sec;
}

function vide(texte) {
  const p = document.createElement("p");
  p.className = "empty-hint";
  p.textContent = texte;
  return p;
}

/** La carte d'un gardien dans la liste de la vue Agents. */
export function carteGardien(g, { choisi, onChoisir, maintenant } = {}) {
  const li = document.createElement("li");
  li.className = "agent-card gardien-card" + (choisi ? " agent-card-selected" : "");
  li.dataset.gardien = g.id;
  li.setAttribute("role", "button");
  li.tabIndex = 0;
  li.addEventListener("click", () => onChoisir?.(g.id));
  li.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    onChoisir?.(g.id);
  });

  const tete = document.createElement("div");
  tete.className = "agent-card-head";
  const rang = document.createElement("div");
  rang.className = "agent-card-title-row";
  const etat = libelleEtat(g.etat, "gardien");
  rang.appendChild(point(etat.ton, etat.texte));
  const nom = document.createElement("strong");
  nom.className = "agent-card-name";
  nom.textContent = nomDuGardien(g.id);
  rang.appendChild(nom);
  tete.appendChild(rang);
  li.appendChild(tete);

  const desc = document.createElement("p");
  desc.className = "agent-card-desc";
  const n = (g.alertes || []).length;
  desc.textContent =
    g.etat === "coupe"
      ? "Coupé : il ne vérifie plus rien."
      : n
        ? `${n} alerte${n > 1 ? "s" : ""} ouverte${n > 1 ? "s" : ""}`
        : etat.texte;
  li.appendChild(desc);

  const meta = document.createElement("div");
  meta.className = "agent-card-meta";
  const prochaine = document.createElement("span");
  prochaine.textContent = g.prochaine
    ? `prochaine vérification ${dateHumaine(g.prochaine, maintenant)}`
    : "aucune vérification prévue";
  meta.appendChild(prochaine);
  li.appendChild(meta);
  return li;
}

/**
 * La fiche d'un gardien : état, gestes, alertes ouvertes, derniers constats,
 * contrôles avec leur prochaine échéance, gestes récents.
 *
 * `actions.agir(id, geste)` avec `id` = `gardien.<nom>` ou `controle.<id>`.
 */
export function ficheGardien(corps, g, { actions, enCours = "", maintenant } = {}) {
  corps.innerHTML = "";
  const tete = document.createElement("header");
  tete.className = "agent-detail-head";
  const rang = document.createElement("div");
  rang.className = "agent-card-title-row";
  const etat = libelleEtat(g.etat, "gardien");
  rang.appendChild(point(etat.ton, etat.texte));
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = `Gardien ${nomDuGardien(g.id).toLowerCase()}`;
  rang.appendChild(h);
  const badge = document.createElement("span");
  badge.className = `gardien-etat gardien-etat-${etat.ton}`;
  badge.textContent = etat.texte;
  rang.appendChild(badge);
  tete.appendChild(rang);
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = `${roleDuGardien(g.id)} Une vérification automatique, sans IA : elle ne coûte rien.`;
  tete.appendChild(lead);
  corps.appendChild(tete);

  const barre = document.createElement("div");
  barre.className = "agent-head-actions gardien-gestes";
  const occupe = enCours === `gardien.${g.id}`;
  const peut = g.actions || {};
  barre.appendChild(
    bouton("Lancer maintenant", "primary btn-sm", () => actions.agir(`gardien.${g.id}`, "lancer"), occupe || !peut.lancer)
  );
  if (peut.reactiver) {
    barre.appendChild(
      bouton("Réactiver", "ghost btn-sm", () => actions.agir(`gardien.${g.id}`, "reactiver"), occupe)
    );
  }
  if (peut.couper) {
    barre.appendChild(
      bouton("Couper", "ghost btn-sm gardien-couper", () => actions.couper(`gardien.${g.id}`, nomDuGardien(g.id)), occupe)
    );
  }
  corps.appendChild(barre);

  const repere = document.createElement("ul");
  repere.className = "agent-kv";
  repere.appendChild(ligneCle("Dernière vérification", dateHumaine(g.derniere, maintenant)));
  repere.appendChild(
    ligneCle("Prochaine", g.prochaine ? dateHumaine(g.prochaine, maintenant) : "aucune prévue")
  );
  repere.appendChild(ligneCle("Dépense", "aucune (sans IA)"));
  corps.appendChild(repere);

  // Alertes ouvertes.
  const secAlertes = section("Alertes ouvertes");
  const alertes = g.alertes || [];
  if (!alertes.length) {
    secAlertes.appendChild(vide("Aucune alerte ouverte."));
  } else {
    const ul = document.createElement("ul");
    ul.className = "gardien-alertes";
    for (const a of alertes) {
      const li = document.createElement("li");
      li.className = `gardien-alerte gardien-alerte-${a.niveau === "alerte" ? "alerte" : "attention"}`;
      const t = document.createElement("strong");
      t.textContent = resumeLisible(a.resume) || libelleControle(a.controle);
      li.appendChild(t);
      const sous = document.createElement("span");
      sous.className = "agent-queue-sub";
      const bouts = [];
      if (a.objet) bouts.push(libelleObjet(a.objet));
      bouts.push(`depuis ${dateHumaine(a.depuis, maintenant)}`);
      if (a.compte > 1) bouts.push(`vu ${a.compte} fois`);
      sous.textContent = bouts.join(" · ");
      li.appendChild(sous);
      if (a.preuve) {
        const preuve = document.createElement("span");
        preuve.className = "gardien-preuve";
        preuve.textContent = a.preuve;
        li.appendChild(preuve);
      }
      ul.appendChild(li);
    }
    secAlertes.appendChild(ul);
  }
  corps.appendChild(secAlertes);

  // Derniers constats (le dernier passage de chaque contrôle).
  const secConstats = section("Derniers constats");
  const constats = g.constats || [];
  if (!constats.length) {
    secConstats.appendChild(vide("Rien à signaler au dernier passage."));
  } else {
    const ul = document.createElement("ul");
    ul.className = "gardien-constats";
    for (const c of constats.slice(0, 20)) {
      const li = document.createElement("li");
      li.textContent = `${resumeLisible(c.resume) || "constat"} (vérification « ${libelleControle(c.controle)} », ${dateHumaine(c.quand, maintenant)})`;
      ul.appendChild(li);
    }
    secConstats.appendChild(ul);
  }
  corps.appendChild(secConstats);

  // Les contrôles du gardien.
  const secControles = section("Ce qu’il vérifie");
  const ulc = document.createElement("ul");
  ulc.className = "gardien-controles";
  for (const c of g.controles || []) {
    const li = document.createElement("li");
    li.className = "gardien-controle";
    li.dataset.controle = c.id;
    const gauche = document.createElement("div");
    gauche.className = "gardien-controle-texte";
    const eC = c.coupe || !c.actif ? libelleEtat("coupe") : libelleEtat(c.etat || "inconnu");
    const rangC = document.createElement("div");
    rangC.className = "agent-card-title-row";
    rangC.appendChild(point(eC.ton, eC.texte));
    const nomC = document.createElement("strong");
    nomC.textContent = libelleControle(c.id);
    rangC.appendChild(nomC);
    gauche.appendChild(rangC);
    const sous = document.createElement("span");
    sous.className = "agent-queue-sub";
    const bouts = [quandHumain(c.quand)];
    if (c.en_cours) bouts.push("en cours");
    else if (c.actif && c.prochaine) bouts.push(`prochaine ${dateHumaine(c.prochaine, maintenant)}`);
    if (c.coupe) bouts.push("coupé à la main");
    else if (!c.actif_declare) bouts.push("coupé dans la déclaration");
    if (c.derniere) bouts.push(`dernière ${dateHumaine(c.derniere, maintenant)}`);
    sous.textContent = bouts.join(" · ");
    gauche.appendChild(sous);
    li.appendChild(gauche);

    const btns = document.createElement("div");
    btns.className = "agent-queue-actions";
    const occupeC = enCours === `controle.${c.id}` || occupe;
    if (c.actif) {
      btns.appendChild(bouton("Lancer", "ghost btn-sm", () => actions.agir(`controle.${c.id}`, "lancer"), occupeC || c.en_cours));
      btns.appendChild(bouton("Couper", "ghost btn-sm", () => actions.couper(`controle.${c.id}`, libelleControle(c.id)), occupeC));
    } else if (c.coupe) {
      btns.appendChild(bouton("Réactiver", "ghost btn-sm", () => actions.agir(`controle.${c.id}`, "reactiver"), occupeC));
    }
    li.appendChild(btns);
    ulc.appendChild(li);
  }
  secControles.appendChild(ulc);
  corps.appendChild(secControles);

  // Gestes récents.
  const secGestes = section("Gestes récents");
  const gestes = g.gestes || [];
  if (!gestes.length) {
    secGestes.appendChild(vide("Aucun geste : ce gardien n’a rien eu à relancer."));
  } else {
    const ul = document.createElement("ul");
    ul.className = "agent-history";
    for (const x of gestes) {
      const li = document.createElement("li");
      const issue =
        x.resultat === "refuse"
          ? "retenu"
          : x.apres?.etat && x.apres.etat !== "alerte"
            ? "réussi"
            : x.apres
              ? "sans effet"
              : "fait";
      li.textContent = `${dateHumaine(x.quand, maintenant)} · ${libelleGeste(x.nom)} · ${issue}`;
      ul.appendChild(li);
    }
    secGestes.appendChild(ul);
  }
  corps.appendChild(secGestes);
  return corps;
}

/**
 * Toutes les tâches automatiques, une seule liste : gardiens, agents
 * planifiés et tâches de wikichat, créations servies.
 *
 * `actions.agir(id, geste)`, `actions.choisirGardien(nom)`. `pilote` faux :
 * les gestes sur les tâches de wikichat sont masqués (rien pour les porter).
 */
export function listeAutomates(conteneur, donnees, { actions, enCours = "", maintenant } = {}) {
  conteneur.innerHTML = "";
  const automates = donnees?.automates || [];
  const pilote = !!donnees?.sources?.pilote;
  for (const note of donnees?.notes || []) {
    const p = document.createElement("p");
    p.className = "agent-note";
    p.textContent = note;
    conteneur.appendChild(p);
  }
  if (!automates.length) {
    conteneur.appendChild(vide("Aucune tâche automatique connue pour l’instant."));
    return conteneur;
  }
  const ul = document.createElement("ul");
  ul.className = "automates-liste";
  for (const a of automates) {
    const li = document.createElement("li");
    li.className = "automate";
    li.dataset.automate = a.id;
    const texte = document.createElement("div");
    texte.className = "automate-texte";
    const rang = document.createElement("div");
    rang.className = "agent-card-title-row";
    const e = libelleEtat(a.etat, a.genre);
    rang.appendChild(point(e.ton, e.texte));
    const nom = document.createElement("strong");
    nom.textContent = titreAutomate(a);
    rang.appendChild(nom);
    const genre = document.createElement("span");
    genre.className = "automate-genre";
    genre.textContent = libelleGenre(a);
    rang.appendChild(genre);
    texte.appendChild(rang);

    const sous = document.createElement("span");
    sous.className = "agent-queue-sub";
    const derniere = a.derniere ? dateHumaine(a.derniere, maintenant) : "jamais";
    const prochaine = a.prochaine
      ? dateHumaine(a.prochaine, maintenant)
      : a.prochaine_texte || (a.genre === "routine" ? "lancée par une tâche" : a.genre === "creation" ? "en continu" : "—");
    sous.textContent = `${e.texte} · dernière : ${derniere} · prochaine : ${prochaine} · plafond : ${plafondHumain(a)}`;
    texte.appendChild(sous);
    li.appendChild(texte);

    const btns = document.createElement("div");
    btns.className = "agent-queue-actions";
    const occupe = enCours === a.id;
    if (a.genre === "gardien") {
      btns.appendChild(bouton("Voir", "ghost btn-sm", () => actions.choisirGardien?.(a.titre)));
    }
    for (const geste of a.gestes || []) {
      if (a.genre === "trigger" && !pilote) continue;
      if (a.genre === "gardien" && geste === "couper") continue; // depuis sa fiche seulement
      const b = bouton(
        LIBELLES_GESTES[geste] || geste,
        geste === "activer" ? "primary btn-sm" : "ghost btn-sm",
        () => actions.agir(a.id, geste),
        occupe
      );
      if (geste === "activer") b.title = "Réservé à vous : un agent ne peut pas activer une tâche automatique.";
      btns.appendChild(b);
    }
    li.appendChild(btns);
    ul.appendChild(li);
  }
  conteneur.appendChild(ul);
  return conteneur;
}
