// La modale formulaire : ce qu'il advient de son bouton d'envoi.
//
// Le défaut d'origine ne se voyait pas au premier essai, et c'est ce qui l'a
// rendu long à trouver : un utilisateur enregistrait un connecteur, ça
// marchait ; il en enregistrait un second, et là plus rien — un sablier au
// survol du bouton, et aucun envoi. Le bouton est désactivé le temps de la
// requête, la modale se ferme ensuite sans jamais le réarmer, et l'ouverture
// suivante ne remettait que le libellé. Le premier enregistrement passait,
// tous les suivants étaient impossibles jusqu'au rechargement de la page.
//
// La correction a introduit un second défaut de la même famille : la classe
// `modal-submit-envoi`, qui marque l'envoi en cours, n'était retirée qu'en cas
// d'erreur. Après un succès elle restait collée : le bouton était cliquable
// mais gardait son curseur d'attente — le même mensonge, par une autre porte.
//
// Cette suite tient les deux, séparément, parce que les deux réarmements
// existent pour deux raisons différentes :
//   - les bretelles : la fermeture réarme le bouton qu'elle vient de bloquer ;
//   - la ceinture   : l'ouverture le réarme, quel que soit l'état laissé par
//                     la modale précédente.
// Retirer l'une sans l'autre laisse la page marcher dans la plupart des cas,
// et c'est précisément pour cela qu'aucune ne doit disparaître en silence.

import { EvenementSimule, installerDom } from "./dom-minimal.mjs";
import { bilan, egal, nePorte, porte, verifier } from "./verifier.mjs";

import { closeModal, openModal, bindModal } from "../../mcp_gateway/atelier/web/js/ui/modal.js";

// ── Le banc ──────────────────────────────────────────────────────────────
//
// La modale ne crée pas son propre cadre : elle s'installe dans des nœuds que
// `index.html` a déjà posés et qu'elle retrouve par identifiant. On les
// reconstruit ici à l'identique — mêmes identifiants, même imbrication — sans
// quoi `openModal` chercherait dans le vide.

function element(balise, id, classes = "") {
  const n = document.createElement(balise);
  if (id) n.id = id;
  if (classes) n.className = classes;
  return n;
}

/**
 * Apprend à un nœud la liste de sélecteurs séparés par des virgules.
 *
 * `openModal` donne le focus au premier champ venu, qu'il cherche avec
 * « input, textarea, select ». Le DOM minimal refuse cette forme et le dit
 * franchement, ce qui vaut mieux qu'un `null` silencieux — mais il n'est pas
 * à nous de le modifier : deux autres suites s'en servent. On complète donc
 * ce seul nœud, et seulement pour des noms de balises.
 */
function accepterListeDeSelecteurs(noeud) {
  const natif = noeud.querySelector.bind(noeud);
  noeud.querySelector = (selecteur) => {
    const brut = String(selecteur);
    if (!brut.includes(",")) return natif(brut);
    const balises = brut.split(",").map((s) => s.trim());
    for (const b of balises) {
      if (!/^[a-z]+$/.test(b)) throw new Error(`sélecteur non prévu par le banc : ${brut}`);
    }
    return noeud.descendants().find((n) => balises.includes(n.tagName)) || null;
  };
}

/**
 * Donne au formulaire son `elements`, indexé par nom de champ.
 *
 * C'est par là que la modale relit ce qui a été saisi. Un vrai formulaire
 * l'expose nativement ; ici on le calcule à la demande, pour qu'il suive les
 * champs que chaque ouverture remplace.
 */
function poserElements(form) {
  Object.defineProperty(form, "elements", {
    get() {
      const parNom = {};
      for (const n of form.descendants()) if (n.name) parNom[n.name] = n;
      return parNom;
    },
  });
}

function monterBanc() {
  installerDom();
  // `bindModal` écoute le redimensionnement, et le cadrage lit la largeur de
  // la fenêtre. Rien de tout cela n'est vérifié ici : c'est le décor minimum
  // pour que le module s'installe.
  globalThis.window = {
    innerWidth: 1280,
    innerHeight: 900,
    addEventListener() {},
    removeEventListener() {},
  };

  const backdrop = element("div", "modal-backdrop", "modal-backdrop hidden");
  backdrop.hidden = true;
  backdrop.setAttribute("aria-hidden", "true");
  const modal = element("div", "modal", "modal");
  const head = element("header", "", "modal-head");
  const titre = element("h2", "modal-title", "modal-title");
  const lead = element("p", "modal-lead", "modal-lead");
  lead.hidden = true;
  const fermer = element("button", "modal-close", "ghost modal-close");
  head.appendChild(titre);
  head.appendChild(lead);
  head.appendChild(fermer);

  const form = element("form", "modal-form", "modal-body");
  const champs = element("div", "modal-fields");
  const erreur = element("p", "modal-error", "error");
  erreur.hidden = true;
  const pied = element("footer", "", "modal-foot");
  const annuler = element("button", "modal-cancel", "ghost");
  const submit = element("button", "modal-submit", "primary modal-submit");
  submit.textContent = "Confirmer";
  submit.disabled = false;
  pied.appendChild(annuler);
  pied.appendChild(submit);
  form.appendChild(champs);
  form.appendChild(erreur);
  form.appendChild(pied);

  modal.appendChild(head);
  modal.appendChild(form);
  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  accepterListeDeSelecteurs(champs);
  poserElements(form);

  const state = { modal: null };
  bindModal(state);

  return { state, backdrop, modal, titre, lead, form, champs, erreur, submit, annuler, fermer };
}

/**
 * Un tour de boucle complet.
 *
 * L'envoi est asynchrone et personne ne garde sa promesse : le gestionnaire de
 * `submit` la laisse filer. Un passage par la file des tâches suffit à laisser
 * se dérouler tout ce qui était en attente de résolution.
 */
const tour = () => new Promise((r) => setTimeout(r, 0));

/** Le clic sur « Enregistrer », tel que le navigateur l'annonce au formulaire. */
function soumettre(banc) {
  banc.form.dispatchEvent(new EvenementSimule("submit", { bubbles: true }));
}

/** Ce que la page Connecteurs ouvre : un nom, une adresse, un libellé à elle. */
function modaleConnecteur(banc, onSubmit, { nom = "grist", url = "https://grist.example" } = {}) {
  openModal(banc.state, {
    title: "Ajouter un connecteur",
    submitLabel: "Enregistrer",
    fields: [
      { name: "nom", label: "Nom", value: nom },
      { name: "url", label: "Adresse", value: url },
    ],
    onSubmit,
  });
}

// ── 1. L'envoi en cours, puis le retour à la normale ─────────────────────
//
// Le cœur du défaut. Pendant l'envoi, le bouton doit être mort et le dire ;
// une fois l'envoi réussi, il doit être vivant et ne plus rien dire du tout.
// C'est la deuxième moitié qui manquait.

{
  const banc = monterBanc();
  let debloquer;
  const requete = new Promise((r) => {
    debloquer = r;
  });
  let recu = null;
  modaleConnecteur(banc, (data) => {
    recu = data;
    return requete;
  });

  egal(banc.titre.textContent, "Ajouter un connecteur", "la modale s’ouvre sur son titre");
  egal(banc.submit.textContent, "Enregistrer", "et sur le libellé que l’appelant a demandé");
  verifier(banc.backdrop.hidden === false, "la modale est visible à l’ouverture");
  verifier(banc.submit.disabled === false, "son bouton est prêt");

  soumettre(banc);
  await tour();

  // Pendant l'envoi, le bouton doit être franchement inerte : sans quoi un
  // double clic partirait deux fois.
  verifier(banc.submit.disabled === true, "pendant l’envoi, le bouton est désactivé");
  verifier(
    banc.submit.classList.contains("modal-submit-envoi"),
    "pendant l’envoi, le bouton porte la marque d’envoi",
  );
  egal(banc.submit.textContent, "Envoi…", "pendant l’envoi, le bouton dit ce qu’il fait");
  egal(recu, { nom: "grist", url: "https://grist.example" }, "les champs saisis sont bien transmis");
  verifier(banc.state.modal !== null, "la modale reste ouverte tant que l’envoi n’a pas abouti");

  debloquer();
  await tour();

  // Les bretelles : la fermeture réarme ce qu'elle a bloqué. Sans cette
  // ligne, l'utilisateur ne pouvait plus jamais enregistrer.
  verifier(banc.submit.disabled === false, "après un envoi réussi, le bouton est réarmé");
  verifier(
    !banc.submit.classList.contains("modal-submit-envoi"),
    "après un envoi réussi, la marque d’envoi est retirée — pas de sablier collé",
  );
  nePorte(
    banc.submit.className,
    "modal-submit-envoi",
    "et elle ne traîne nulle part dans les classes du bouton",
  );
  verifier(banc.backdrop.hidden === true, "après un envoi réussi, la modale est fermée");
  egal(banc.state.modal, null, "et l’état ne garde plus de modale ouverte");
  egal(banc.submit.textContent, "Confirmer", "le bouton reprend son libellé neutre");
}

// ── 2. L'échec : la modale reste, pour qu'on puisse réessayer ────────────
//
// Fermer sur une erreur ferait perdre la saisie. Le bouton doit redevenir
// cliquable et reprendre son libellé d'origine, pas rester sur « Envoi… ».

{
  const banc = monterBanc();
  modaleConnecteur(banc, () => {
    throw new Error("Le service n’a pas répondu");
  });

  soumettre(banc);
  await tour();

  verifier(banc.state.modal !== null, "un envoi qui échoue laisse la modale ouverte");
  verifier(banc.backdrop.hidden === false, "et son cadre reste à l’écran");
  verifier(banc.erreur.hidden === false, "l’erreur est montrée");
  porte(banc.erreur.textContent, "Le service n’a pas répondu", "et elle dit ce qui a échoué");
  verifier(banc.submit.disabled === false, "le bouton redevient cliquable pour réessayer");
  verifier(
    !banc.submit.classList.contains("modal-submit-envoi"),
    "et il ne se dit plus en train d’envoyer",
  );
  egal(banc.submit.textContent, "Enregistrer", "il reprend le libellé de cette modale, pas un autre");

  // Réessayer doit marcher, puisque c'est tout l'objet de rester ouvert.
  let secondEssai = false;
  banc.state.modal.onSubmit = () => {
    secondEssai = true;
  };
  soumettre(banc);
  await tour();
  verifier(secondEssai, "le second essai part bel et bien");
  verifier(banc.backdrop.hidden === true, "et il ferme la modale une fois passé");
}

// ── 3. La ceinture : une ouverture réarme, quoi qu’il se soit passé avant ─
//
// Vérifiée à part, et pas seulement à travers le cas 1 : les deux réarmements
// ont été ajoutés pour deux raisons différentes, et l'un peut disparaître sans
// que l'autre le fasse remarquer. Ici on simule exactement ce que laissait le
// défaut : un bouton mort hérité de la modale précédente.

{
  const banc = monterBanc();
  banc.submit.disabled = true;
  banc.submit.textContent = "Envoi…";

  modaleConnecteur(banc, () => {});

  verifier(
    banc.submit.disabled === false,
    "une modale qui s’ouvre a son bouton vivant, même après un bouton laissé mort",
  );
  egal(banc.submit.textContent, "Enregistrer", "et son libellé à elle, pas celui d’avant");

  // Et il faut qu'il agisse, pas seulement qu'il en ait l'air.
  let parti = false;
  banc.state.modal.onSubmit = () => {
    parti = true;
  };
  soumettre(banc);
  await tour();
  verifier(parti, "et il envoie vraiment, au lieu d’avoir seulement l’air prêt");
  egal(banc.state.modal, null, "la modale se referme derrière lui");
}

// ── 4. Deux enregistrements de suite ─────────────────────────────────────
//
// Le scénario exact que l'utilisateur ne pouvait pas faire, et le seul qui
// prouve la correction de bout en bout. Un seul enregistrement réussissait
// déjà avant.

{
  const banc = monterBanc();
  const envois = [];

  modaleConnecteur(banc, (data) => {
    envois.push(data);
  });
  soumettre(banc);
  await tour();
  verifier(banc.backdrop.hidden === true, "le premier enregistrement passe et referme");

  modaleConnecteur(banc, (data) => {
    envois.push(data);
  }, { nom: "grist-2", url: "https://grist2.example" });
  verifier(banc.backdrop.hidden === false, "la seconde modale s’ouvre");
  verifier(banc.submit.disabled === false, "avec un bouton qui n’a pas gardé la mort du premier");

  soumettre(banc);
  await tour();
  egal(envois.length, 2, "deux enregistrements consécutifs partent tous les deux");
  egal(
    envois[1],
    { nom: "grist-2", url: "https://grist2.example" },
    "et le second porte ses propres valeurs",
  );
  verifier(banc.backdrop.hidden === true, "le second referme lui aussi");
  verifier(banc.submit.disabled === false, "et laisse la place propre pour un troisième");
  verifier(
    !banc.submit.classList.contains("modal-submit-envoi"),
    "sans marque d’envoi résiduelle",
  );
}

// ── 5. Pas de reliquat de la modale précédente ───────────────────────────
//
// Libellé, champs, texte d'accroche, erreur : ce qu'on lit doit venir de la
// modale ouverte, jamais de celle d'avant. C'est la même famille de défaut —
// un état qui survit à une fermeture.

{
  const banc = monterBanc();

  openModal(banc.state, {
    title: "Ajouter un connecteur",
    lead: "Indiquez l’adresse du service.",
    submitLabel: "Enregistrer",
    fields: [{ name: "nom", label: "Nom", value: "grist" }],
    onSubmit: () => {
      throw new Error("Adresse injoignable");
    },
  });
  soumettre(banc);
  await tour();
  verifier(banc.erreur.hidden === false, "l’erreur du premier essai est bien affichée");

  closeModal(banc.state);
  openModal(banc.state, {
    title: "Renommer la conversation",
    submitLabel: "Renommer",
    fields: [{ name: "titre", label: "Titre", value: "Essai" }],
    onSubmit: () => {},
  });

  egal(banc.titre.textContent, "Renommer la conversation", "le titre est celui de la modale ouverte");
  egal(banc.submit.textContent, "Renommer", "le libellé aussi, sans reliquat du précédent");
  verifier(banc.erreur.hidden === true, "l’erreur de la modale précédente ne suit pas");
  verifier(banc.lead.hidden === true, "ni son texte d’accroche");
  egal(banc.lead.textContent, "", "qui est bien vidé, pas seulement caché");
  egal(
    document.getElementById("modal-field-nom"),
    null,
    "le champ de la modale précédente a disparu du formulaire",
  );
  verifier(
    document.getElementById("modal-field-titre") !== null,
    "et celui de la modale courante est là",
  );

  let recu = null;
  banc.state.modal.onSubmit = (data) => {
    recu = data;
  };
  soumettre(banc);
  await tour();
  egal(recu, { titre: "Essai" }, "et seul le champ courant est envoyé");
}

{
  // La ceinture ne réarmait que `disabled` : la marque d'envoi, elle, pouvait
  // survivre à une fermeture par un autre chemin qu'un envoi réussi — une
  // fermeture par Échap ou par le fond pendant un envoi en vol. Le bouton
  // rouvrait alors cliquable mais toujours marqué, donc toujours son sablier.
  const banc = monterBanc();
  banc.submit.disabled = true;
  banc.submit.classList.add("modal-submit-envoi");

  openModal(banc.state, {
    title: "Après une fermeture en plein vol",
    submitLabel: "Enregistrer",
    fields: [{ name: "nom", label: "Nom", value: "" }],
    onSubmit: () => {},
  });
  verifier(banc.submit.disabled === false, "l’ouverture réarme le bouton");
  verifier(
    !banc.submit.classList.contains("modal-submit-envoi"),
    "et lui retire la marque d’envoi, quelle qu’en soit la provenance"
  );
}

bilan("modale");
