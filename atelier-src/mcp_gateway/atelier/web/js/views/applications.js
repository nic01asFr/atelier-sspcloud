/**
 * Le panneau « Applications » d'un projet : ses artefacts.
 *
 * Il remplace le lien « Artefacts ». Un artefact est un dossier
 * `artifacts/<nom>/` et une adresse : autonome (des fichiers, en bac à sable)
 * ou serveur (un processus, déclaré par son `artefact.json`). Pour chacun :
 * son mode, son état, son auteur, et les gestes — Ouvrir, Démarrer ou
 * Arrêter, Journal, Copier l'URL.
 *
 * Tout ce qui vient d'une application ou d'un manifeste (nom, titre, raison
 * d'un échec, journal) est posé en `textContent`, jamais en HTML : un journal
 * porte ce que l'application a écrit, balises comprises, et l'interface vit
 * dans l'origine de l'Atelier.
 *
 * « Ouvrir » est un lien vers `/v1/apps/<slug>/<nom>/ouvrir` : c'est
 * l'Atelier qui renvoie vers l'hôte des applications, avec un code d'usage
 * unique. Sans hôte des applications déclaré, le lien est grisé.
 */

const LIBELLES = {
  pret: "prête",
  demarrage: "démarre…",
  redemarrage: "redémarre…",
  arret: "s'arrête…",
  arrete: "arrêtée",
  en_echec: "en échec",
  statique: "fichiers",
  invalide: "manifeste invalide",
};

function el(balise, classe, texte) {
  const n = document.createElement(balise);
  if (classe) n.className = classe;
  if (texte != null) n.textContent = String(texte);
  return n;
}

function bouton(libelle, action, { desactive = false, titre = "" } = {}) {
  const b = el("button", "ghost apps-action", libelle);
  b.setAttribute("type", "button");
  if (titre) b.setAttribute("title", titre);
  if (desactive) b.setAttribute("disabled", "");
  b.addEventListener("click", (ev) => {
    if (ev && ev.preventDefault) ev.preventDefault();
    if (!b.hasAttribute("disabled")) action(b);
  });
  return b;
}

/**
 * Rend le panneau dans `conteneur`.
 *
 * `etat` : `{ slug, expose, artefacts, artefactsUrl }`, tel que
 * `GET /v1/apps?slug=` le rend (plus l'adresse des artefacts).
 * `actions` : `{ demarrer(nom), arreter(nom), journal(nom), copier(texte),
 * recharger() }`, des promesses ; injectées pour que le panneau se teste
 * sans réseau.
 */
export function rendrePanneauApplications(conteneur, etat, actions) {
  const liste = el("div", "apps-liste");
  const titre = el("div", "apps-titre", "Artefacts du projet");
  liste.appendChild(titre);

  if (!etat.expose) {
    liste.appendChild(
      el(
        "p",
        "apps-note",
        "Pas d'hôte des applications sur cette installation : les artefacts serveur se démarrent, mais ne s'ouvrent pas.",
      ),
    );
  }

  // L'index du dossier `artifacts/` : toujours là, même vide.
  const artefacts = el("div", "apps-ligne");
  artefacts.appendChild(el("span", "apps-nom", "Index"));
  artefacts.appendChild(el("span", "apps-etat", "dossier artifacts/"));
  const lienArtefacts = el("a", "session-face-link apps-ouvrir", "Ouvrir");
  lienArtefacts.setAttribute("href", etat.artefactsUrl);
  lienArtefacts.setAttribute("target", "_blank");
  lienArtefacts.setAttribute("rel", "noopener");
  artefacts.appendChild(lienArtefacts);
  liste.appendChild(artefacts);

  const fiches = etat.artefacts || [];
  if (!fiches.length) {
    liste.appendChild(el("p", "apps-note", "Aucun artefact (dossier artifacts/<nom>/)."));
  }

  const zoneJournal = el("pre", "apps-journal");
  zoneJournal.hidden = true;

  for (const f of fiches) {
    const ligne = el("div", "apps-ligne");
    ligne.dataset.app = f.nom;
    ligne.appendChild(el("span", "apps-nom", f.titre || f.nom));
    const libelle = LIBELLES[f.etat] || f.etat;
    const statut = el("span", `apps-etat apps-etat-${f.etat}`, libelle);
    if (f.raison || f.erreur) statut.setAttribute("title", f.erreur || f.raison);
    ligne.appendChild(statut);
    ligne.appendChild(el("span", "apps-mode", f.mode === "serveur" ? "serveur" : "autonome"));
    if (f.auteur) {
      const auteur = el("span", "apps-auteur", f.auteur);
      auteur.setAttribute("title", "Conversation qui l'a créé");
      ligne.appendChild(auteur);
    }

    if (f.ouvrir && f.etat !== "invalide") {
      const lien = el("a", "session-face-link apps-ouvrir", "Ouvrir");
      lien.setAttribute("href", f.ouvrir);
      lien.setAttribute("target", "_blank");
      lien.setAttribute("rel", "noopener");
      ligne.appendChild(lien);
    } else {
      ligne.appendChild(
        bouton("Ouvrir", () => {}, {
          desactive: true,
          titre: f.etat === "invalide" ? "Manifeste invalide" : "Pas d'hôte des applications",
        }),
      );
    }

    if (f.mode === "serveur") {
      const tourne = ["pret", "demarrage", "redemarrage"].includes(f.etat);
      ligne.appendChild(
        bouton(tourne ? "Arrêter" : "Démarrer", async (b) => {
          b.setAttribute("disabled", "");
          try {
            await (tourne ? actions.arreter(f.nom) : actions.demarrer(f.nom));
          } finally {
            await actions.recharger();
          }
        }),
      );
      ligne.appendChild(
        bouton("Journal", async () => {
          const texte = await actions.journal(f.nom);
          // Du texte, rien d'autre : jamais interprété comme du HTML.
          zoneJournal.textContent = texte || "(journal vide)";
          zoneJournal.hidden = false;
        }),
      );
    }
    if (f.url) {
      ligne.appendChild(bouton("Copier l'URL", () => actions.copier(f.url)));
    }
    if (f.erreur) ligne.appendChild(el("div", "apps-erreur", f.erreur));
    liste.appendChild(ligne);
  }

  liste.appendChild(zoneJournal);
  conteneur.replaceChildren(liste);
  return liste;
}

/** Charge l'état depuis l'API et rend le panneau ; `api` est le module `api.js`. */
export async function chargerPanneauApplications(conteneur, slug, api) {
  const recharger = () => chargerPanneauApplications(conteneur, slug, api);
  let etat;
  try {
    etat = await api.listApps(slug);
  } catch (err) {
    conteneur.replaceChildren(el("p", "apps-note", `Applications illisibles : ${err.message}`));
    return;
  }
  rendrePanneauApplications(
    conteneur,
    { slug, expose: etat.expose, artefacts: etat.artefacts, artefactsUrl: api.artifactsUrl(slug) },
    {
      demarrer: (nom) => api.startApp(slug, nom),
      arreter: (nom) => api.stopApp(slug, nom),
      journal: (nom) => api.appJournal(slug, nom, 200),
      copier: (texte) => (navigator.clipboard ? navigator.clipboard.writeText(texte) : Promise.resolve()),
      recharger,
    },
  );
}
