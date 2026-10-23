/**
 * « Secrets » dans Réglages : les clés et jetons que les connecteurs utilisent, gardés à part dans des fichiers fermés.
 *
 * La valeur se colle ici une fois et ne revient jamais : le champ est vidé dès l'envoi, la réponse ne la porte pas, le journal non plus.
 * Changer la valeur d'un secret met aussitôt à jour les connecteurs qui l'utilisent. « Accorder un secret » (écran des connecteurs)
 * reste sans valeur : il ne manipule que des noms.
 *
 * Les mots : « secret », « valeur », « connecteur » ; jamais « token » ni « clé API ».
 */

import { ilYA } from "./github.js";

const NOM_VALIDE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const GERE_AILLEURS = "github_token"; // se change dans la section GitHub

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function bouton(libelle, classe, onClick, { desactive = false, titre = "" } = {}) {
  const b = el("button", classe, libelle);
  b.type = "button";
  b.disabled = !!desactive;
  if (titre) b.title = titre;
  b.addEventListener("click", onClick);
  return b;
}

/** Le nom proposé est-il utilisable tel quel ? (le serveur revérifie : ceci ne sert qu'à griser le bouton) */
export function nomPlausible(nom) {
  const n = String(nom || "").trim();
  return NOM_VALIDE.test(n) && !n.includes("..");
}

function formulaire(s, actions) {
  const f = s.formulaire;
  const form = el("form", "reglages-formulaire reglages-ajout");
  form.setAttribute("aria-label", f.edition ? `Changer la valeur de ${f.nom}` : "Ajouter un secret");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    actions.enregistrer();
  });

  const labelNom = el("label", "reglages-champ");
  labelNom.appendChild(el("span", "reglages-etiquette", "Nom du secret"));
  const nom = el("input", "memoire-champ");
  nom.type = "text";
  nom.name = "nom";
  nom.autocomplete = "off";
  nom.spellcheck = false;
  nom.setAttribute("autocapitalize", "off");
  nom.placeholder = "grist_api_key";
  nom.value = f.nom || "";
  nom.readOnly = !!f.edition;
  labelNom.appendChild(nom);
  labelNom.appendChild(el("span", "reglages-aide", "Des lettres, chiffres, point, tiret ou souligné. C’est ce nom qu’on choisit dans « Accorder un secret »."));
  form.appendChild(labelNom);

  const labelValeur = el("label", "reglages-champ");
  labelValeur.appendChild(el("span", "reglages-etiquette", "Valeur"));
  const valeur = el("input", "memoire-champ");
  valeur.type = "password";
  valeur.name = "valeur";
  valeur.autocomplete = "off";
  valeur.spellcheck = false;
  valeur.setAttribute("autocapitalize", "off");
  valeur.value = f.valeur || "";
  labelValeur.appendChild(valeur);
  labelValeur.appendChild(
    el("span", "reglages-aide", "Elle part une fois, est gardée dans un fichier fermé, et ne s’affiche plus ensuite. Les agents ne la voient jamais.")
  );
  form.appendChild(labelValeur);

  const gestes = el("div", "reglages-gestes");
  const envoi = bouton(f.edition ? "Changer la valeur" : "Enregistrer", "primary btn-sm", () => actions.enregistrer(), {
    desactive: !nomPlausible(f.nom) || !String(f.valeur || "").trim() || !!s.travail,
  });
  envoi.type = "submit";
  nom.addEventListener("input", () => {
    f.nom = nom.value;
    envoi.disabled = !nomPlausible(f.nom) || !valeur.value.trim();
  });
  valeur.addEventListener("input", () => {
    f.valeur = valeur.value;
    envoi.disabled = !nomPlausible(f.nom) || !valeur.value.trim();
  });
  gestes.appendChild(envoi);
  if (f.edition || f.nom || f.valeur) gestes.appendChild(bouton("Annuler", "ghost btn-sm", () => actions.annuler()));
  form.appendChild(gestes);
  return form;
}

function ligne(secret, s, actions) {
  const li = el("li", "github-depot");
  const tete = el("div", "github-depot-tete");
  tete.appendChild(el("code", "", secret.nom));
  tete.appendChild(
    el(
      "span",
      secret.protege ? "mcp-badge mcp-badge-off" : "mcp-badge mcp-badge-warn",
      secret.protege ? "fermé" : "à protéger : chmod 600"
    )
  );
  li.appendChild(tete);
  const quand = ilYA(secret.modifie);
  const utilise = secret.utilise_par || [];
  li.appendChild(
    el(
      "p",
      "reglages-aide",
      [quand && `modifié ${quand}`, utilise.length ? `utilisé par ${utilise.join(", ")}` : "aucun connecteur ne l’utilise"].filter(Boolean).join(" — ")
    )
  );
  const gestes = el("div", "reglages-gestes");
  if (secret.nom === GERE_AILLEURS) {
    gestes.appendChild(el("span", "reglages-aide", "Se change dans la section GitHub (Déconnecter, puis Connecter)."));
  } else if (s.confirmerRetrait === secret.nom) {
    gestes.appendChild(bouton("Confirmer : retirer", "danger btn-sm", () => actions.retirer(secret.nom)));
    gestes.appendChild(bouton("Garder", "ghost btn-sm", () => actions.demanderRetrait(null)));
  } else {
    gestes.appendChild(bouton("Changer la valeur", "ghost btn-sm", () => actions.changer(secret.nom), { desactive: !!s.travail }));
    gestes.appendChild(
      bouton("Retirer", "ghost btn-sm", () => actions.demanderRetrait(secret.nom), {
        desactive: !!s.travail || utilise.length > 0,
        titre: utilise.length ? `Utilisé par ${utilise.join(", ")} : changez d’abord leur secret.` : "",
      })
    );
  }
  li.appendChild(gestes);
  return li;
}

/** L'écran. `actions` : `charger()`, `changer(nom)`, `annuler()`, `enregistrer()`, `demanderRetrait(nom|null)`, `retirer(nom)`. */
export function rendreSecrets(corps, state, actions) {
  const s = state.reglages?.secrets || {};
  const section = el("section", "reglages-section");
  section.setAttribute("aria-labelledby", "reglages-secrets-titre");
  const entete = el("div", "reglages-section-tete");
  const h3 = el("h3", "", "Secrets");
  h3.id = "reglages-secrets-titre";
  entete.appendChild(h3);
  section.appendChild(entete);
  section.appendChild(
    el(
      "p",
      "reglages-aide",
      "Les clés et jetons que vos connecteurs utilisent, gardés à part. Collez la valeur ici ; pour la donner à un connecteur, « Accorder un secret » dans Connecteurs. Changer la valeur d’un secret met aussitôt à jour les connecteurs qui l’utilisent."
    )
  );

  const etat = el("div", "reglages-etat");
  etat.setAttribute("aria-live", "polite");
  if (s.travail) etat.appendChild(el("p", "mcp-pool-travail", s.travail));
  if (s.erreur) etat.appendChild(el("p", "agent-form-error", s.erreur));
  if (s.message) etat.appendChild(el("p", "reglages-ok", s.message));
  section.appendChild(etat);

  if (!s.charge) {
    if (!s.erreur) section.appendChild(el("p", "empty-hint", "Lecture des secrets…"));
    corps.appendChild(section);
    return section;
  }

  section.appendChild(formulaire({ ...s, formulaire: s.formulaire || { nom: "", valeur: "", edition: false } }, actions));
  const liste = s.liste || [];
  if (!liste.length) section.appendChild(el("p", "empty-hint", "Aucun secret pour l’instant."));
  const ul = el("ul", "github-depots");
  for (const secret of liste) ul.appendChild(ligne(secret, s, actions));
  section.appendChild(ul);
  corps.appendChild(section);
  return section;
}

/**
 * Les gestes : `/v1/secrets` (la session de l'interface vaut « la personne »).
 * @param {{ state: object, api: object, render: Function }} deps
 */
export function createSecretsActions({ state, api, render }) {
  const g = () => {
    if (!state.reglages) state.reglages = {};
    if (!state.reglages.secrets) {
      state.reglages.secrets = { charge: false, erreur: "", message: "", travail: "", liste: [], dossier: "", formulaire: { nom: "", valeur: "", edition: false }, confirmerRetrait: "" };
    }
    return state.reglages.secrets;
  };

  async function lire() {
    const x = g();
    try {
      const rendu = await api.listerSecrets();
      x.liste = Array.isArray(rendu?.secrets) ? rendu.secrets : [];
      x.dossier = rendu?.dossier || "";
      x.erreur = "";
    } catch (err) {
      x.erreur = err?.message || String(err);
    }
    x.charge = true;
  }

  return {
    async charger() {
      await lire();
      render();
    },
    changer(nom) {
      const x = g();
      x.formulaire = { nom, valeur: "", edition: true };
      x.confirmerRetrait = "";
      x.message = "";
      x.erreur = "";
      render();
    },
    annuler() {
      g().formulaire = { nom: "", valeur: "", edition: false };
      render();
    },
    async enregistrer() {
      const x = g();
      const nom = String(x.formulaire?.nom || "").trim();
      const valeur = x.formulaire?.valeur || "";
      x.formulaire = { nom: "", valeur: "", edition: false }; // la valeur ne reste pas en mémoire de l'écran
      x.travail = "Enregistrement…";
      x.erreur = "";
      x.message = "";
      render();
      try {
        const r = await api.ecrireSecret(nom, valeur);
        const faits = Array.isArray(r?.renouveles) ? r.renouveles : [];
        x.message =
          `Secret « ${nom} » ${r?.nouveau ? "créé" : "mis à jour"}.` +
          (faits.length ? ` Connecteur${faits.length > 1 ? "s" : ""} mis à jour avec la nouvelle valeur : ${faits.join(", ")}.` : "");
        await lire();
      } catch (err) {
        x.erreur = err?.message || String(err);
        x.formulaire = { nom, valeur: "", edition: !!(x.liste || []).some((l) => l.nom === nom) }; // le nom reste ; la valeur est à ressaisir
      }
      x.travail = "";
      render();
    },
    demanderRetrait(nom) {
      g().confirmerRetrait = nom || "";
      render();
    },
    async retirer(nom) {
      const x = g();
      x.confirmerRetrait = "";
      x.travail = "Retrait…";
      x.erreur = "";
      x.message = "";
      render();
      try {
        await api.retirerSecret(nom);
        x.message = `Secret « ${nom} » retiré.`;
        await lire();
      } catch (err) {
        x.erreur = err?.message || String(err);
      }
      x.travail = "";
      render();
    },
  };
}
