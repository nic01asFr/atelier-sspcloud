/**
 * Fabrique d'une composition à plusieurs étapes.
 *
 * Une variante fige les paramètres d'un seul outil ; une composition en
 * enchaîne plusieurs, et c'est là que la valeur apparaît — le résultat d'un
 * appel devient l'argument du suivant. Cela demande de désigner ces valeurs,
 * donc de les nommer.
 *
 * Deux notations, et une seule chose à retenir : `${input.x}` pour ce qu'on
 * demandera au moment de l'appel, `${etape.champ}` pour ce qu'une étape
 * précédente a produit. Le schéma d'entrée n'est pas déclaré à part : il se
 * déduit des `${input.x}` écrits, pour qu'il ne puisse pas diverger de ce que
 * les étapes réclament réellement.
 */

import { $ } from "../core/dom.js";

/** Une étape neuve, telle que l'écran la manipule. */
export function etapeVierge() {
  return { tool: "", label: "", parametersTexte: "{}" };
}

function champ(label, valeur, oninput, opts = {}) {
  const wrap = document.createElement("label");
  wrap.className = "field";
  const span = document.createElement("span");
  span.textContent = label;
  wrap.appendChild(span);
  if (opts.hint) {
    const h = document.createElement("span");
    h.className = "modal-hint";
    h.textContent = opts.hint;
    wrap.appendChild(h);
  }
  const input = document.createElement("input");
  input.type = "text";
  input.value = valeur || "";
  input.placeholder = opts.placeholder || "";
  if (opts.datalistId) input.setAttribute("list", opts.datalistId);
  input.addEventListener("input", () => oninput(input.value));
  wrap.appendChild(input);
  return wrap;
}

function bouton(texte, titre, actif, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "linklike";
  b.textContent = texte;
  b.title = titre;
  b.disabled = !actif;
  b.addEventListener("click", onclick);
  return b;
}

function renderEtape(etape, i, draft, actions) {
  const bloc = document.createElement("div");
  bloc.className = "composition-step";

  const entete = document.createElement("div");
  entete.className = "composition-step-head";
  const rang = document.createElement("strong");
  rang.textContent = "Étape " + (i + 1);
  entete.appendChild(rang);

  const barre = document.createElement("div");
  barre.className = "composition-step-actions";
  const total = (draft.steps || []).length;
  barre.appendChild(
    bouton("Monter", "Exécuter cette étape plus tôt", i > 0, () => actions.deplacerEtape(i, -1))
  );
  barre.appendChild(
    bouton("Descendre", "Exécuter cette étape plus tard", i < total - 1, () =>
      actions.deplacerEtape(i, 1)
    )
  );
  barre.appendChild(
    bouton("Retirer", "Supprimer cette étape", total > 1, () => actions.retirerEtape(i))
  );
  entete.appendChild(barre);
  bloc.appendChild(entete);

  bloc.appendChild(
    champ("Outil", etape.tool, (v) => actions.majEtape(i, { tool: v }), {
      datalistId: "composition-outils",
      placeholder: "nom de l’outil",
      hint: "Tapez pour filtrer parmi les outils disponibles.",
    })
  );
  bloc.appendChild(
    champ("Nom de l’étape", etape.label, (v) => actions.majEtape(i, { label: v }), {
      placeholder: etape.tool ? etape.tool.split("__").pop() : "sert à désigner son résultat",
      hint: "C’est par ce nom qu’une étape suivante désignera ce qu’elle a produit.",
    })
  );

  const params = document.createElement("div");
  params.className = "field composition-step-params";
  const titre = document.createElement("span");
  titre.textContent = "Paramètres";
  params.appendChild(titre);
  const zone = document.createElement("textarea");
  zone.rows = 3;
  zone.spellcheck = false;
  zone.placeholder = '{"sujet": "${input.sujet}"}';
  zone.value = etape.parametersTexte ?? "{}";
  zone.addEventListener("input", () => actions.majEtape(i, { parametersTexte: zone.value }));
  params.appendChild(zone);
  if (etape.erreur) {
    const err = document.createElement("p");
    err.className = "composition-step-erreur";
    err.textContent = etape.erreur;
    params.appendChild(err);
  }
  bloc.appendChild(params);
  return bloc;
}

/**
 * @param {object} state
 * @param {object} actions majBrouillon, majEtape, ajouterEtape, retirerEtape,
 *   deplacerEtape, enregistrerComposition, annulerComposition
 */
export function renderCompositionBuilder(state, actions) {
  const body = $("connectors-detail-body");
  const draft = state.compositionDraft;
  if (!body || !draft) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = "Nouvelle composition";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent =
    "Un enchaînement d’appels, enregistré comme un outil. Il part en brouillon : vous l’activerez après l’avoir essayé.";
  head.appendChild(h);
  head.appendChild(lead);
  body.appendChild(head);

  // Les outils appelables, une seule fois pour toutes les étapes. Les
  // compositions déjà faites en sont exclues : en composer une sur une autre
  // n'ajouterait qu'un niveau d'indirection.
  const dl = document.createElement("datalist");
  dl.id = "composition-outils";
  for (const svc of state.toolsByService || []) {
    if (String(svc.key).startsWith("meta:compositions")) continue;
    for (const t of svc.tools || []) {
      const opt = document.createElement("option");
      opt.value = t.name;
      opt.label = (t.label || t.short) + " — " + (svc.label || svc.key);
      dl.appendChild(opt);
    }
  }
  body.appendChild(dl);

  const ident = document.createElement("section");
  ident.className = "agent-section";
  ident.appendChild(
    champ("Nom", draft.name, (v) => actions.majBrouillon({ name: v }), {
      placeholder: "Ex. Relever puis résumer",
    })
  );
  ident.appendChild(
    champ("Description", draft.description, (v) => actions.majBrouillon({ description: v }), {
      placeholder: "Ce que fait l’enchaînement, en une phrase",
    })
  );
  body.appendChild(ident);

  const sec = document.createElement("section");
  sec.className = "agent-section";
  const h3 = document.createElement("h3");
  h3.className = "connectors-sub";
  h3.textContent = "Étapes";
  const aide = document.createElement("p");
  aide.className = "agent-section-hint";
  aide.textContent =
    "Dans un paramètre : ${input.nom} pour une valeur demandée au moment de l’appel, ${etape.champ} pour le résultat d’une étape précédente. Ce que vous laissez en ${input.…} devient une entrée de la composition.";
  sec.appendChild(h3);
  sec.appendChild(aide);

  (draft.steps || []).forEach((etape, i) => {
    sec.appendChild(renderEtape(etape, i, draft, actions));
  });

  const ajouter = document.createElement("button");
  ajouter.type = "button";
  ajouter.className = "ghost btn-sm";
  ajouter.textContent = "+ Ajouter une étape";
  ajouter.addEventListener("click", () => actions.ajouterEtape());
  sec.appendChild(ajouter);
  body.appendChild(sec);

  if (draft.erreur) {
    const err = document.createElement("p");
    err.className = "composition-step-erreur";
    err.textContent = draft.erreur;
    body.appendChild(err);
  }

  const barre = document.createElement("div");
  barre.className = "agent-form-actions";
  const annuler = document.createElement("button");
  annuler.type = "button";
  annuler.className = "ghost btn-sm";
  annuler.textContent = "Annuler";
  annuler.addEventListener("click", () => actions.annulerComposition());
  const valider = document.createElement("button");
  valider.type = "button";
  valider.className = "primary btn-sm";
  valider.textContent = "Enregistrer en brouillon";
  valider.disabled =
    !String(draft.name || "").trim() ||
    !(draft.steps || []).some((e) => String(e.tool || "").trim());
  valider.addEventListener("click", () => actions.enregistrerComposition());
  barre.appendChild(annuler);
  barre.appendChild(valider);
  body.appendChild(barre);
}
