/**
 * « GitHub » dans Réglages : connecter son compte, voir ses dépôts, en ouvrir un comme projet.
 *
 * Le jeton part une fois (un jeton « fine-grained », le plus étroit que GitHub sache faire) et ne
 * revient jamais : l'écran ne montre que « connecté : @compte », et le champ est vidé dès l'envoi,
 * comme la clé d'un fournisseur de modèles.
 *
 * Ouvrir un dépôt est un geste de la commande `atelier_projet_depuis_github` : la même que celle de
 * l'Assistant, donc le même résultat, le même journal, et « Annuler » le range sans rien supprimer.
 *
 * Les mots : « dépôt », « projet », « compte » ; jamais « repo » ni « token ».
 */

const VISIBLES_MAX = 40;

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function bouton(libelle, classe, onClick, { desactive = false } = {}) {
  const b = el("button", classe, libelle);
  b.type = "button";
  b.disabled = !!desactive;
  b.addEventListener("click", onClick);
  return b;
}

/** Les dépôts à montrer : ceux qui contiennent la recherche (nom ou description), au plus `max`. */
export function filtrerLesDepots(depots, recherche, max = VISIBLES_MAX) {
  const q = String(recherche || "").trim().toLowerCase();
  const tous = (Array.isArray(depots) ? depots : []).filter(
    (d) => !q || String(d.nom || "").toLowerCase().includes(q) || String(d.description || "").toLowerCase().includes(q)
  );
  return { visibles: tous.slice(0, max), masques: Math.max(0, tous.length - max), total: tous.length };
}

/** « il y a 3 jours » : sans bibliothèque, à la journée près. */
export function ilYA(iso, maintenant = Date.now()) {
  const t = Date.parse(iso || "");
  if (!Number.isFinite(t)) return "";
  const jours = Math.floor((maintenant - t) / 86_400_000);
  if (jours <= 0) return "aujourd’hui";
  if (jours === 1) return "hier";
  if (jours < 31) return `il y a ${jours} jours`;
  const mois = Math.floor(jours / 30);
  if (mois < 12) return `il y a ${mois} mois`;
  const ans = Math.floor(jours / 365);
  return `il y a ${ans} an${ans > 1 ? "s" : ""}`;
}

function ligneDeDepot(d, g, actions) {
  const li = el("li", "github-depot");
  const tete = el("div", "github-depot-tete");
  tete.appendChild(el("code", "", d.nom));
  tete.appendChild(el("span", d.prive ? "mcp-badge mcp-badge-warn" : "mcp-badge mcp-badge-off", d.prive ? "privé" : "public"));
  if (d.archive) tete.appendChild(el("span", "reglages-tag", "archivé"));
  if (!d.ecriture) tete.appendChild(el("span", "reglages-tag", "lecture seule"));
  li.appendChild(tete);
  const detail = [d.description, ilYA(d.maj) && `dernière activité ${ilYA(d.maj)}`].filter(Boolean).join(" — ");
  if (detail) li.appendChild(el("p", "reglages-aide", detail));
  const gestes = el("div", "reglages-gestes");
  if (d.projet) {
    const a = el("a", "ghost btn-sm", `Projet « ${d.projet} »`);
    a.href = `/?slug=${encodeURIComponent(d.projet)}`;
    gestes.appendChild(a);
  } else {
    const ouvre = g.ouverture === d.nom;
    gestes.appendChild(
      bouton(ouvre ? "Ouverture…" : "Ouvrir comme projet", "primary btn-sm", () => actions.ouvrir(d.nom), {
        desactive: !!g.travail || !!g.ouverture,
      })
    );
  }
  li.appendChild(gestes);
  return li;
}

function formulaireDeConnexion(g, actions) {
  const form = el("form", "reglages-formulaire reglages-ajout");
  form.setAttribute("aria-label", "Connecter un compte GitHub");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    actions.connecter();
  });
  const label = el("label", "reglages-champ");
  label.appendChild(el("span", "reglages-etiquette", "Jeton GitHub"));
  const input = el("input");
  input.type = "password";
  input.name = "jeton";
  input.className = "memoire-champ";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("autocapitalize", "off");
  input.placeholder = "github_pat_…";
  input.value = g.jeton || "";
  const envoi = bouton("Connecter", "primary btn-sm", () => actions.connecter(), {
    desactive: !String(g.jeton || "").trim() || !!g.travail,
  });
  envoi.type = "submit";
  input.addEventListener("input", () => {
    g.jeton = input.value;
    envoi.disabled = !input.value.trim();
  });
  label.appendChild(input);
  label.appendChild(
    el(
      "span",
      "reglages-aide",
      "Il est gardé à part (lecture réservée au propriétaire) et ne s’affiche plus ensuite. Les agents ne le voient jamais."
    )
  );
  form.appendChild(label);

  const aide = el("details", "reglages-modeles");
  aide.appendChild(el("summary", "", "Comment créer ce jeton ?"));
  const ol = el("ol", "reglages-liste-modeles");
  const etape = (texte) => ol.appendChild(el("li", "", texte));
  etape("Sur GitHub : Réglages → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.");
  etape("Choisissez les dépôts que l’Atelier peut voir (« Only select repositories » : le plus sûr).");
  etape("Permissions de dépôt : Contents en « Read and write » (lecture seule suffit pour seulement les ouvrir), Metadata en « Read ».");
  etape("Copiez le jeton (il commence par github_pat_) et collez-le ici.");
  aide.appendChild(ol);
  const lien = el("a", "", "Ouvrir la page de création sur GitHub");
  lien.href = "https://github.com/settings/personal-access-tokens/new";
  lien.target = "_blank";
  lien.rel = "noopener noreferrer";
  aide.appendChild(lien);
  form.appendChild(aide);

  const gestes = el("div", "reglages-gestes");
  gestes.appendChild(envoi);
  form.appendChild(gestes);
  return form;
}

/** La section « GitHub ». `actions` : `charger`, `connecter`, `deconnecter`, `demanderDeconnexion`, `actualiser`, `chercher`, `ouvrir`. */
export function rendreGithub(corps, state, actions) {
  const g = state.reglages?.github || {};
  const section = el("section", "reglages-section");
  section.setAttribute("aria-labelledby", "reglages-github-titre");
  const entete = el("div", "reglages-section-tete");
  const h3 = el("h3", "", "GitHub");
  h3.id = "reglages-github-titre";
  entete.appendChild(h3);
  if (g.etat?.connecte) entete.appendChild(bouton("Actualiser", "ghost btn-sm", () => actions.actualiser(), { desactive: !!g.travail }));
  section.appendChild(entete);
  section.appendChild(
    el(
      "p",
      "reglages-aide",
      "Vos dépôts, publics et privés, ouverts comme projets : l’Assistant peut le faire à votre place (« ouvre mon dépôt … »)."
    )
  );

  const etat = el("div", "reglages-etat");
  etat.setAttribute("aria-live", "polite");
  if (g.travail) etat.appendChild(el("p", "mcp-pool-travail", g.travail));
  if (g.erreur) etat.appendChild(el("p", "agent-form-error", g.erreur));
  if (g.message) etat.appendChild(el("p", "reglages-ok", g.message));
  if (g.avertissement) etat.appendChild(el("p", "reglages-aide", g.avertissement));
  section.appendChild(etat);

  if (!g.charge) {
    if (!g.erreur) section.appendChild(el("p", "empty-hint", "Lecture du compte…"));
    corps.appendChild(section);
    return section;
  }

  if (!g.etat?.connecte) {
    section.appendChild(formulaireDeConnexion(g, actions));
    corps.appendChild(section);
    return section;
  }

  const compte = el("div", "github-compte");
  compte.appendChild(
    el(
      "p",
      "",
      `Connecté${g.etat.login ? ` : @${g.etat.login}` : ""}${g.etat.type ? ` (jeton ${g.etat.type})` : ""}`
    )
  );
  if (g.confirmerDeconnexion) {
    compte.appendChild(bouton("Confirmer : déconnecter", "danger btn-sm", () => actions.deconnecter()));
    compte.appendChild(bouton("Garder", "ghost btn-sm", () => actions.demanderDeconnexion(false)));
  } else {
    compte.appendChild(bouton("Déconnecter", "ghost btn-sm", () => actions.demanderDeconnexion(true)));
  }
  section.appendChild(compte);

  const recherche = el("input", "memoire-champ github-recherche");
  recherche.type = "search";
  recherche.placeholder = "Chercher un dépôt…";
  recherche.setAttribute("aria-label", "Chercher un dépôt");
  recherche.value = g.recherche || "";
  recherche.addEventListener("input", () => actions.chercher(recherche.value));
  section.appendChild(recherche);

  const { visibles, masques, total } = filtrerLesDepots(g.depots, g.recherche);
  if (!g.depots?.length && !g.travail && !g.erreur) {
    section.appendChild(el("p", "empty-hint", "Aucun dépôt visible avec ce jeton."));
  } else if (!total && (g.depots || []).length) {
    section.appendChild(el("p", "empty-hint", "Aucun dépôt ne correspond."));
  }
  const ul = el("ul", "github-depots");
  for (const d of visibles) ul.appendChild(ligneDeDepot(d, g, actions));
  section.appendChild(ul);
  if (masques) section.appendChild(el("p", "reglages-aide", `${masques} autre${masques > 1 ? "s" : ""} : affinez la recherche.`));
  if (g.tronque) section.appendChild(el("p", "reglages-aide", "La liste s’arrête à 300 dépôts : cherchez par nom pour les autres."));
  corps.appendChild(section);
  return section;
}

/**
 * Les gestes : `/v1/github` pour le compte (la session de l'interface vaut « la personne »), la commande
 * du catalogue pour ouvrir un dépôt.
 * @param {{ state: object, api: object, render: Function, aller?: (adresse: string) => void }} deps
 */
export function createGithubActions({ state, api, render, aller = (adresse) => window.location.assign(adresse) }) {
  const g = () => {
    if (!state.reglages) state.reglages = {};
    if (!state.reglages.github) {
      state.reglages.github = {
        charge: false, erreur: "", message: "", avertissement: "", travail: "", etat: { connecte: false },
        jeton: "", depots: [], tronque: false, recherche: "", ouverture: "", confirmerDeconnexion: false,
      };
    }
    return state.reglages.github;
  };

  async function lireLesDepots(actualiser) {
    const x = g();
    try {
      const rendu = await api.lireDepotsGithub("", actualiser);
      x.depots = Array.isArray(rendu?.depots) ? rendu.depots : [];
      x.tronque = !!rendu?.tronque;
      x.erreur = "";
    } catch (err) {
      x.erreur = err?.message || String(err);
    }
  }

  async function charger() {
    const x = g();
    try {
      x.etat = (await api.lireGithub()) || { connecte: false };
      x.erreur = "";
      if (x.etat.connecte) await lireLesDepots(false);
    } catch (err) {
      x.erreur = err?.message || String(err);
    }
    x.charge = true;
    render();
  }

  return {
    charger,
    async actualiser() {
      const x = g();
      x.travail = "Lecture de vos dépôts…";
      x.message = "";
      render();
      await lireLesDepots(true);
      x.travail = "";
      render();
    },
    async connecter() {
      const x = g();
      const jeton = x.jeton;
      x.jeton = ""; // le jeton ne reste pas en mémoire de l'écran
      x.travail = "Vérification du jeton auprès de GitHub…";
      x.erreur = "";
      x.message = "";
      x.avertissement = "";
      render();
      try {
        const rendu = await api.connecterGithub({ jeton });
        x.etat = rendu;
        x.avertissement = rendu?.avertissement || "";
        x.message = rendu?.login ? `Compte @${rendu.login} connecté.` : "Compte connecté.";
        if (Array.isArray(rendu?.renouveles) && rendu.renouveles.length) {
          x.message += ` Connecteur${rendu.renouveles.length > 1 ? "s" : ""} mis à jour avec le nouveau jeton : ${rendu.renouveles.join(", ")}.`;
        }
        await lireLesDepots(true);
      } catch (err) {
        x.erreur = err?.message || String(err);
      }
      x.travail = "";
      render();
    },
    demanderDeconnexion(oui) {
      g().confirmerDeconnexion = !!oui;
      render();
    },
    async deconnecter() {
      const x = g();
      x.confirmerDeconnexion = false;
      x.travail = "Déconnexion…";
      render();
      try {
        x.etat = await api.deconnecterGithub();
        x.depots = [];
        x.message = "Compte déconnecté. Les projets déjà ouverts restent là.";
        x.erreur = "";
      } catch (err) {
        x.erreur = err?.message || String(err);
      }
      x.travail = "";
      render();
    },
    chercher(texte) {
      g().recherche = String(texte || "");
      render();
    },
    async ouvrir(nom) {
      const x = g();
      x.ouverture = nom;
      x.erreur = "";
      x.message = "";
      render();
      try {
        const rep = await api.executerCommande("atelier_projet_depuis_github", { depot: nom });
        const slug = rep?.resultat?.projet || rep?.resultat?.charge?.projet || "";
        x.message = slug ? `« ${nom} » est ouvert : projet « ${slug} ».` : `« ${nom} » est ouvert.`;
        x.ouverture = "";
        await lireLesDepots(false);
        render();
        if (slug) aller(`/?slug=${encodeURIComponent(slug)}`);
        return;
      } catch (err) {
        x.erreur = err?.message || String(err);
      }
      x.ouverture = "";
      render();
    },
  };
}
