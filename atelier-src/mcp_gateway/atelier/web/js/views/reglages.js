/**
 * « Réglages » : ce que l'Atelier a de branché, et de quoi y ajouter.
 *
 * Première section : les fournisseurs de modèles. SSPCloud est celui de
 * l'Atelier (on le montre, on ne le règle pas ici) ; Albert est intégré (on lui
 * donne sa clé) ; les autres, on les ajoute à la main : un nom, l'adresse, la
 * clé. L'Atelier interroge alors le fournisseur, retrouve ses modèles tout
 * seul, et dit pourquoi quand il n'y arrive pas.
 *
 * Une clé part une fois et ne revient jamais : l'écran ne montre que sa
 * présence, et le champ est vidé dès l'envoi.
 *
 * Les mots suivent le lexique (decisions.md S2) : « fournisseur », « modèle »,
 * jamais « provider » ni « endpoint ».
 */

import { createGithubActions, rendreGithub } from "./github.js";

const ETATS = {
  ok: ["mcp-badge mcp-badge-ok", "connecté"],
  sans_cle: ["mcp-badge mcp-badge-warn", "clé manquante"],
  en_erreur: ["mcp-badge mcp-badge-err", "en erreur"],
  adresse_invalide: ["mcp-badge mcp-badge-err", "adresse refusée"],
  inconnu: ["mcp-badge mcp-badge-off", "pas encore interrogé"],
};

/** Un identifiant sûr tiré d'un nom : minuscules, chiffres, tirets, commence par une lettre. */
export function identifiantDepuisLeNom(nom) {
  let id = String(nom || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32)
    .replace(/-+$/g, "");
  if (id && !/^[a-z]/.test(id)) id = `f-${id}`.slice(0, 32);
  return id;
}

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

function champ(etiquette, { type = "text", valeur = "", aide = "", placeholder = "", nom, onInput, secret = false }) {
  const label = el("label", "reglages-champ");
  label.appendChild(el("span", "reglages-etiquette", etiquette));
  const input = el("input");
  input.type = type;
  input.value = valeur;
  if (placeholder) input.placeholder = placeholder;
  input.name = nom;
  input.className = "memoire-champ";
  if (secret) {
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("autocapitalize", "off");
  }
  input.addEventListener("input", () => onInput(input.value));
  label.appendChild(input);
  if (aide) label.appendChild(el("span", "reglages-aide", aide));
  return label;
}

function pastille(etat) {
  const [classe, libelle] = ETATS[etat] || ETATS.inconnu;
  return el("span", classe, libelle);
}

function listeDesModeles(f) {
  const d = el("details", "reglages-modeles");
  const n = f.modeles.length;
  d.appendChild(el("summary", "", `${n} modèle${n > 1 ? "s" : ""}`));
  const ul = el("ul", "reglages-liste-modeles");
  for (const m of f.modeles) {
    const li = el("li");
    li.appendChild(el("code", "", m.id));
    if (m.outils_natifs && f.source !== "sspcloud") li.appendChild(el("span", "reglages-tag", "appels d’outils directs"));
    li.appendChild(el("span", "reglages-aide", ` — ${m.public}`));
    ul.appendChild(li);
  }
  d.appendChild(ul);
  return d;
}

/** Le champ de clé seul : pour Albert et pour « changer la clé » d'un fournisseur déclaré. */
function formulaireDeCle(f, r, actions) {
  const form = el("div", "reglages-formulaire");
  form.appendChild(
    champ(`Clé de ${f.nom}`, {
      type: "password",
      nom: "cle",
      valeur: r.cleSaisie || "",
      secret: true,
      aide: `Elle est gardée dans ${f.fichier_de_la_cle} (lecture réservée au propriétaire) et ne s’affiche plus ensuite.`,
      onInput: (v) => {
        r.cleSaisie = v;
        const ok = $envoi(form);
        if (ok) ok.disabled = !v.trim();
      },
    })
  );
  const gestes = el("div", "reglages-gestes");
  const envoi = bouton("Enregistrer la clé", "primary btn-sm", () => actions.enregistrerLaCle(f), {
    desactive: !String(r.cleSaisie || "").trim() || !!r.travail,
  });
  envoi.dataset.envoi = "1";
  gestes.appendChild(envoi);
  gestes.appendChild(bouton("Annuler", "ghost btn-sm", () => actions.fermerLaCle()));
  form.appendChild(gestes);
  return form;
}

function $envoi(racine) {
  return racine.querySelector("[data-envoi]");
}

function carte(f, r, actions) {
  const c = el("article", "reglages-carte");
  c.dataset.id = f.id;
  const tete = el("header", "reglages-carte-tete");
  tete.appendChild(el("h4", "", f.nom));
  tete.appendChild(pastille(f.etat));
  c.appendChild(tete);
  const adresse = el("p", "reglages-adresse");
  adresse.appendChild(el("code", "", f.base_url));
  c.appendChild(adresse);
  const detail = f.detail || "";
  if (detail) c.appendChild(el("p", f.etat === "en_erreur" || f.etat === "adresse_invalide" ? "agent-form-error" : "reglages-aide", detail));
  if (f.modeles.length) c.appendChild(listeDesModeles(f));

  if (f.source === "sspcloud") {
    c.appendChild(el("p", "reglages-aide", "Le fournisseur de l’Atelier : sa clé se règle à l’installation."));
    return c;
  }
  if (r.cleDe === f.id) {
    c.appendChild(formulaireDeCle(f, r, actions));
    return c;
  }
  const gestes = el("div", "reglages-gestes");
  gestes.appendChild(bouton(f.cle_presente ? "Changer la clé" : "Donner la clé", "ghost btn-sm", () => actions.ouvrirLaCle(f.id)));
  if (f.modifiable) gestes.appendChild(bouton("Modifier", "ghost btn-sm", () => actions.modifier(f)));
  if (r.aRetirer === f.id) {
    gestes.appendChild(
      bouton(f.source === "integre" ? "Confirmer : retirer la clé" : "Confirmer : retirer", "danger btn-sm", () => actions.retirer(f.id))
    );
    gestes.appendChild(bouton("Garder", "ghost btn-sm", () => actions.demanderRetrait(null)));
  } else if (f.cle_presente || f.modifiable) {
    gestes.appendChild(
      bouton(f.source === "integre" ? "Retirer la clé" : "Retirer", "ghost btn-sm", () => actions.demanderRetrait(f.id))
    );
  }
  c.appendChild(gestes);
  return c;
}

function formulaireDAjout(r, actions) {
  const f = r.formulaire;
  const form = el("form", "reglages-formulaire reglages-ajout");
  form.setAttribute("aria-label", f.edition ? `Modifier ${f.nom}` : "Ajouter un fournisseur de modèles");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    actions.enregistrer();
  });
  form.appendChild(el("h4", "", f.edition ? `Modifier « ${f.nom} »` : "Ajouter un fournisseur"));
  form.appendChild(
    champ("Nom", {
      nom: "nom",
      valeur: f.nom,
      placeholder: "Mon serveur vLLM",
      onInput: (v) => {
        f.nom = v;
        if (!f.edition && !f.idModifie) {
          f.id = identifiantDepuisLeNom(v);
          const idChamp = form.querySelector('input[name="id"]');
          if (idChamp) idChamp.value = f.id;
        }
      },
    })
  );
  form.appendChild(
    champ("Adresse de base", {
      nom: "base_url",
      type: "url",
      valeur: f.base_url,
      placeholder: "https://exemple.fr/v1",
      aide: "Au format OpenAI, en https:// (elle finit en général par /v1). Une adresse du pod ou de son réseau interne est refusée.",
      onInput: (v) => {
        f.base_url = v;
        f.test = null;
      },
    })
  );
  form.appendChild(
    champ(f.edition ? "Nouvelle clé (laisser vide pour garder l’actuelle)" : "Clé", {
      nom: "cle",
      type: "password",
      valeur: f.cle,
      secret: true,
      aide: "Gardée à part, en lecture réservée au propriétaire. Elle ne s’affiche plus après l’envoi.",
      onInput: (v) => {
        f.cle = v;
        f.test = null;
      },
    })
  );
  if (!f.edition) {
    const avance = el("details", "reglages-avance");
    avance.appendChild(el("summary", "", "Identifiant (avancé)"));
    avance.appendChild(
      champ("Identifiant", {
        nom: "id",
        valeur: f.id,
        aide: "Minuscules, chiffres et tirets. Les modèles s’appellent ensuite claude-<identifiant>-<modèle>.",
        onInput: (v) => {
          f.id = v.trim().toLowerCase();
          f.idModifie = true;
        },
      })
    );
    form.appendChild(avance);
  }

  const test = f.test;
  if (test) {
    const bloc = el("div", "reglages-test");
    bloc.setAttribute("role", "status");
    bloc.appendChild(el("p", test.ok ? "reglages-ok" : "agent-form-error", test.detail));
    if (test.ok && test.modeles.length) {
      const p = el("p", "reglages-aide", "Cochez les modèles dont vous savez qu’ils gèrent bien les appels d’outils ; l’Atelier contraint les autres pour que ça fonctionne.");
      bloc.appendChild(p);
      const ul = el("ul", "reglages-liste-modeles");
      for (const m of test.modeles) {
        const li = el("li");
        const label = el("label");
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = f.natifs.has(m);
        cb.addEventListener("change", () => (cb.checked ? f.natifs.add(m) : f.natifs.delete(m)));
        label.appendChild(cb);
        label.appendChild(el("code", "", ` ${m}`));
        li.appendChild(label);
        ul.appendChild(li);
      }
      bloc.appendChild(ul);
    }
    form.appendChild(bloc);
  }

  const gestes = el("div", "reglages-gestes");
  const pret = f.base_url.trim() && (f.cle.trim() || f.edition);
  const tester = bouton("Tester et chercher les modèles", "ghost btn-sm", () => actions.tester(), {
    desactive: !f.base_url.trim() || !(f.cle.trim() || f.edition) || !!r.travail,
  });
  tester.type = "button";
  gestes.appendChild(tester);
  const envoi = el("button", "primary btn-sm", f.edition ? "Enregistrer" : "Ajouter");
  envoi.type = "submit";
  envoi.disabled = !pret || !f.nom.trim() || !!r.travail;
  gestes.appendChild(envoi);
  gestes.appendChild(bouton("Annuler", "ghost btn-sm", () => actions.fermerLeFormulaire()));
  form.appendChild(gestes);
  return form;
}

/**
 * L'écran. `actions` : `charger()`, `actualiser()`, `ouvrirLAjout()`, `modifier(f)`,
 * `fermerLeFormulaire()`, `tester()`, `enregistrer()`, `ouvrirLaCle(id)`, `fermerLaCle()`,
 * `enregistrerLaCle(f)`, `demanderRetrait(id|null)`, `retirer(id)`, et `github` (voir `github.js`).
 */
export function rendreReglages(corps, state, actions) {
  const r = state.reglages || {};
  corps.innerHTML = "";

  const tete = el("header", "agent-detail-head");
  tete.appendChild(el("h2", "connectors-title", "Réglages"));
  tete.appendChild(
    el(
      "p",
      "connectors-lead",
      "Ce que l’Atelier a de branché. Les clés sont gardées à part et ne s’affichent jamais : on ne voit que leur présence."
    )
  );
  corps.appendChild(tete);

  const section = el("section", "reglages-section");
  section.setAttribute("aria-labelledby", "reglages-modeles-titre");
  const entete = el("div", "reglages-section-tete");
  const h3 = el("h3", "", "Modèles de langage");
  h3.id = "reglages-modeles-titre";
  entete.appendChild(h3);
  entete.appendChild(bouton("Actualiser", "ghost btn-sm", () => actions.actualiser(), { desactive: !!r.travail }));
  entete.appendChild(bouton("Ajouter un fournisseur", "primary btn-sm", () => actions.ouvrirLAjout(), { desactive: !!r.formulaire }));
  section.appendChild(entete);
  section.appendChild(
    el(
      "p",
      "reglages-aide",
      "Les modèles que vos conversations peuvent utiliser. Albert et vos propres fournisseurs passent par le relais de l’Atelier, qui garde leurs clés."
    )
  );

  const etat = el("div", "reglages-etat");
  etat.setAttribute("aria-live", "polite");
  if (r.travail) etat.appendChild(el("p", "mcp-pool-travail", r.travail));
  if (r.erreur) etat.appendChild(el("p", "agent-form-error", r.erreur));
  if (r.message) etat.appendChild(el("p", "reglages-ok", r.message));
  section.appendChild(etat);

  if (!r.charge) {
    if (!r.erreur) section.appendChild(el("p", "empty-hint", "Lecture des fournisseurs…"));
    corps.appendChild(section);
    if (actions.github) rendreGithub(corps, state, actions.github);
    return corps;
  }

  if (r.formulaire) section.appendChild(formulaireDAjout(r, actions));
  const liste = el("div", "reglages-cartes");
  for (const f of r.fournisseurs || []) liste.appendChild(carte(f, r, actions));
  section.appendChild(liste);
  corps.appendChild(section);
  if (actions.github) rendreGithub(corps, state, actions.github);
  return corps;
}

function formulaireVide() {
  return { id: "", nom: "", base_url: "", cle: "", natifs: new Set(), test: null, edition: false, idModifie: false };
}

/**
 * Les gestes de l'écran, par les routes `/v1/fournisseurs` (la session de
 * l'interface vaut « la personne » : la clé du propriétaire n'écrit pas ici).
 * @param {{ state: object, api: object, render: Function }} deps
 */
export function createReglagesActions({ state, api, render }) {
  const r = () => {
    if (!state.reglages) {
      state.reglages = {
        charge: false, erreur: "", message: "", travail: "", fournisseurs: [],
        formulaire: null, cleDe: null, cleSaisie: "", aRetirer: null,
      };
    }
    return state.reglages;
  };

  async function lire(actualiser) {
    const etat = r();
    etat.travail = actualiser ? "Interrogation des fournisseurs…" : "";
    if (actualiser) render();
    try {
      const reponse = await api.lireFournisseurs(actualiser);
      etat.fournisseurs = Array.isArray(reponse?.fournisseurs) ? reponse.fournisseurs : [];
      etat.erreur = "";
    } catch (err) {
      etat.erreur = err?.message || String(err);
    }
    etat.travail = "";
    etat.charge = true;
    render();
  }

  async function agir(libelle, fn, succes) {
    const etat = r();
    etat.travail = libelle;
    etat.erreur = "";
    etat.message = "";
    render();
    try {
      await fn();
      etat.message = succes;
    } catch (err) {
      etat.erreur = err?.message || String(err);
    }
    etat.travail = "";
    await lire(false);
  }

  const github = createGithubActions({ state, api, render });

  return {
    github,
    charger: () => {
      github.charger();
      return lire(false);
    },
    actualiser: () => lire(true),
    ouvrirLAjout() {
      const etat = r();
      etat.formulaire = formulaireVide();
      etat.cleDe = null;
      etat.message = "";
      render();
    },
    modifier(f) {
      const etat = r();
      etat.formulaire = { ...formulaireVide(), id: f.id, nom: f.nom, base_url: f.base_url, natifs: new Set(f.outils_natifs || []), edition: true };
      etat.cleDe = null;
      render();
    },
    fermerLeFormulaire() {
      const etat = r();
      etat.formulaire = null;
      render();
    },
    async tester() {
      const etat = r();
      const f = etat.formulaire;
      if (!f) return;
      etat.travail = "Interrogation du fournisseur…";
      etat.erreur = "";
      render();
      try {
        f.test = await api.testerFournisseur({ base_url: f.base_url, cle: f.cle, identifiant: f.edition ? f.id : "" });
      } catch (err) {
        f.test = { ok: false, modeles: [], detail: err?.message || String(err) };
      }
      etat.travail = "";
      render();
    },
    async enregistrer() {
      const etat = r();
      const f = etat.formulaire;
      if (!f) return;
      const corps = { nom: f.nom.trim(), base_url: f.base_url.trim(), cle: f.cle, outils_natifs: [...f.natifs] };
      f.cle = ""; // la clé ne reste pas en mémoire de l'écran
      await agir(
        "Enregistrement…",
        async () => {
          await api.reglerFournisseur(f.id, corps);
          etat.formulaire = null;
        },
        f.edition ? "Fournisseur modifié." : "Fournisseur ajouté : ses modèles sont cherchés."
      );
    },
    ouvrirLaCle(id) {
      const etat = r();
      etat.cleDe = id;
      etat.cleSaisie = "";
      etat.formulaire = null;
      etat.aRetirer = null;
      render();
    },
    fermerLaCle() {
      const etat = r();
      etat.cleDe = null;
      etat.cleSaisie = "";
      render();
    },
    async enregistrerLaCle(f) {
      const etat = r();
      const cle = etat.cleSaisie;
      etat.cleSaisie = "";
      await agir(
        "Enregistrement de la clé…",
        async () => {
          await api.reglerFournisseur(f.id, { nom: f.nom, base_url: f.base_url, cle });
          etat.cleDe = null;
        },
        "Clé enregistrée."
      );
    },
    demanderRetrait(id) {
      const etat = r();
      etat.aRetirer = id;
      render();
    },
    async retirer(id) {
      const etat = r();
      etat.aRetirer = null;
      await agir("Retrait…", () => api.retirerFournisseur(id), "Retiré.");
    },
  };
}
