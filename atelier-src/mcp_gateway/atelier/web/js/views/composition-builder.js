/**
 * Fabrique d'une composition.
 *
 * Une variante fige les paramètres d'un seul outil ; une composition en
 * enchaîne plusieurs, et c'est là que la valeur apparaît — le résultat d'un
 * appel devient l'argument du suivant. Cela demande de désigner ces valeurs,
 * donc de les nommer.
 *
 * Deux notations, et une seule chose à retenir : `${input.x}` pour ce qu'on
 * demandera au moment de l'appel, `${etape.champ}` pour ce qu'une étape
 * précédente a produit. On ne les fait pas taper : les références connues
 * s'insèrent d'un clic, parce qu'une faute de frappe dans un nom d'étape ne
 * se voit qu'à l'exécution.
 *
 * Le schéma d'entrée n'est pas déclaré à part : il se déduit des `${input.x}`
 * écrits, pour qu'il ne puisse pas diverger de ce que les étapes réclament.
 */

import { $ } from "../core/dom.js";

const TYPES = {
  tool: { titre: "Outil", aide: "Appelle un outil et retient son résultat." },
  elicit: { titre: "Demander", aide: "Suspend l’exécution et demande une valeur." },
  approval: { titre: "Approbation", aide: "Suspend l’exécution jusqu’à votre accord." },
  wait_until: { titre: "Attendre", aide: "Suspend l’exécution pendant une durée." },
};

export function etapeVierge(type = "tool") {
  return { type, tool: "", label: "", parametersTexte: "{}", message: "", wait_seconds: 60 };
}

function champTexte(label, valeur, oninput, opts = {}) {
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
  input.type = opts.type || "text";
  input.value = valeur ?? "";
  input.placeholder = opts.placeholder || "";
  input.addEventListener("input", () => oninput(input.value));
  wrap.appendChild(input);
  return wrap;
}

function lien(texte, titre, actif, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "linklike";
  b.textContent = texte;
  b.title = titre;
  b.disabled = !actif;
  b.addEventListener("click", onclick);
  return b;
}

/** Les outils appelables, groupés par service, pour une liste déroulante. */
function selecteurOutil(etape, i, state, actions) {
  const wrap = document.createElement("label");
  wrap.className = "field";
  const span = document.createElement("span");
  span.textContent = "Outil utilisé";
  wrap.appendChild(span);

  const select = document.createElement("select");
  const vide = document.createElement("option");
  vide.value = "";
  vide.textContent = "— choisir un outil —";
  select.appendChild(vide);

  let connu = !etape.tool;
  for (const svc of state.toolsByService || []) {
    if (String(svc.key).startsWith("meta:compositions")) continue;
    const groupe = document.createElement("optgroup");
    groupe.label = svc.label || svc.key;
    for (const t of svc.tools || []) {
      const opt = document.createElement("option");
      opt.value = t.name;
      opt.textContent = t.label || t.short || t.name;
      if (t.name === etape.tool) {
        opt.selected = true;
        connu = true;
      }
      groupe.appendChild(opt);
    }
    if (groupe.children.length) select.appendChild(groupe);
  }
  // Un outil enregistré mais absent du pool du jour ne doit pas disparaître
  // du formulaire : le taire ferait perdre l'étape à l'enregistrement.
  if (!connu) {
    const opt = document.createElement("option");
    opt.value = etape.tool;
    opt.textContent = etape.tool + " (absent du pool)";
    opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", () => actions.majEtape(i, { tool: select.value }, true));
  wrap.appendChild(select);
  return wrap;
}

/** Références disponibles à cet endroit de l'enchaînement. */
function pastillesReferences(draft, i, zone, actions) {
  const dispo = [];
  const texte = JSON.stringify(draft.steps || []);
  for (const nom of new Set(texte.match(/\$\{input\.([a-zA-Z0-9_]+)\}/g) || [])) {
    dispo.push(nom);
  }
  for (const e of (draft.steps || []).slice(0, i)) {
    const id = (e.label || e.tool || "").trim();
    if (id) dispo.push("${" + id.toLowerCase().replace(/[^a-z0-9]+/g, "_") + ".text}");
  }
  if (!dispo.length && i === 0) dispo.push("${input.sujet}");

  const barre = document.createElement("div");
  barre.className = "composition-refs";
  const titre = document.createElement("span");
  titre.className = "composition-refs-label";
  titre.textContent = "Insérer :";
  barre.appendChild(titre);
  for (const ref of [...new Set(dispo)]) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "composition-ref";
    b.textContent = ref;
    b.title = ref.startsWith("${input.")
      ? "Valeur demandée au moment de l’appel"
      : "Résultat d’une étape précédente";
    b.addEventListener("click", () => {
      const pos = zone.selectionStart ?? zone.value.length;
      zone.value = zone.value.slice(0, pos) + ref + zone.value.slice(pos);
      zone.focus();
      zone.selectionStart = zone.selectionEnd = pos + ref.length;
      actions.majEtape(i, { parametersTexte: zone.value });
    });
    barre.appendChild(b);
  }
  return barre;
}

function renderEtape(etape, i, draft, state, actions) {
  const bloc = document.createElement("div");
  bloc.className = "composition-step";

  const entete = document.createElement("div");
  entete.className = "composition-step-head";
  const rang = document.createElement("strong");
  rang.textContent = (i + 1) + " · " + (TYPES[etape.type]?.titre || etape.type);
  entete.appendChild(rang);

  const barre = document.createElement("div");
  barre.className = "composition-step-actions";
  const total = (draft.steps || []).length;
  barre.appendChild(lien("Monter", "Exécuter plus tôt", i > 0, () => actions.deplacerEtape(i, -1)));
  barre.appendChild(
    lien("Descendre", "Exécuter plus tard", i < total - 1, () => actions.deplacerEtape(i, 1))
  );
  barre.appendChild(lien("Retirer", "Supprimer cette étape", total > 1, () => actions.retirerEtape(i)));
  entete.appendChild(barre);
  bloc.appendChild(entete);

  bloc.appendChild(
    champTexte("Nom de l’étape", etape.label, (v) => actions.majEtape(i, { label: v }), {
      placeholder: etape.tool ? etape.tool.split("__").pop() : "sert à désigner son résultat",
      hint: "C’est par ce nom qu’une étape suivante désignera ce qu’elle a produit.",
    })
  );

  if (etape.type === "tool") {
    bloc.appendChild(selecteurOutil(etape, i, state, actions));
    const params = document.createElement("div");
    params.className = "field composition-step-params";
    const titre = document.createElement("span");
    titre.textContent = "Paramètres, en JSON";
    params.appendChild(titre);
    const zone = document.createElement("textarea");
    zone.rows = 4;
    zone.spellcheck = false;
    zone.placeholder = '{"query": "${input.sujet}"}';
    zone.value = etape.parametersTexte ?? "{}";
    zone.addEventListener("input", () => actions.majEtape(i, { parametersTexte: zone.value }));
    params.appendChild(zone);
    params.appendChild(pastillesReferences(draft, i, zone, actions));
    bloc.appendChild(params);
  } else if (etape.type === "wait_until") {
    bloc.appendChild(
      champTexte(
        "Durée, en secondes",
        etape.wait_seconds,
        (v) => actions.majEtape(i, { wait_seconds: v }),
        { type: "number", hint: TYPES.wait_until.aide }
      )
    );
  } else {
    bloc.appendChild(
      champTexte("Message", etape.message, (v) => actions.majEtape(i, { message: v }), {
        placeholder:
          etape.type === "elicit" ? "Quelle valeur demander ?" : "Ce qu’il faut approuver",
        hint: TYPES[etape.type]?.aide || "",
      })
    );
  }

  if (etape.erreur) {
    const err = document.createElement("p");
    err.className = "composition-step-erreur";
    err.textContent = etape.erreur;
    bloc.appendChild(err);
  }
  return bloc;
}

export function renderCompositionBuilder(state, actions) {
  const body = $("connectors-detail-body");
  const draft = state.compositionDraft;
  if (!body || !draft) return;
  body.innerHTML = "";

  const head = document.createElement("header");
  head.className = "agent-detail-head";
  const h = document.createElement("h2");
  h.className = "connectors-title";
  h.textContent = draft.id ? "Modifier la composition" : "Nouvelle composition";
  const lead = document.createElement("p");
  lead.className = "connectors-lead";
  lead.textContent = draft.id
    ? "Les corrections prennent effet à la prochaine exécution."
    : "Un enchaînement d’appels, enregistré comme un outil. Il part en brouillon : vous l’activerez après l’avoir essayé.";
  head.appendChild(h);
  head.appendChild(lead);
  body.appendChild(head);

  const ident = document.createElement("section");
  ident.className = "agent-section";
  ident.appendChild(
    champTexte("Nom", draft.name, (v) => actions.majBrouillon({ name: v }), {
      placeholder: "Ex. Relever puis résumer",
    })
  );
  ident.appendChild(
    champTexte("Description", draft.description, (v) => actions.majBrouillon({ description: v }), {
      placeholder: "Ce que fait l’enchaînement, en une phrase",
    })
  );
  body.appendChild(ident);

  // Ce que la composition réclamera à l'appel, tel qu'on peut le lire des
  // étapes. Affiché, jamais saisi : le déclarer à part le ferait diverger.
  const entrees = [
    ...new Set(
      (JSON.stringify(draft.steps || []).match(/\$\{input\.([a-zA-Z0-9_]+)\}/g) || []).map((r) =>
        r.slice(8, -1)
      )
    ),
  ];
  const recoit = document.createElement("p");
  recoit.className = "composition-entrees";
  recoit.innerHTML = "<strong>Cette composition reçoit :</strong> ";
  if (entrees.length) {
    for (const e of entrees) {
      const pastille = document.createElement("span");
      pastille.className = "composition-entree";
      pastille.textContent = e;
      recoit.appendChild(pastille);
    }
  } else {
    const rien = document.createElement("span");
    rien.className = "composition-refs-label";
    rien.textContent = "rien pour l’instant — écrivez ${input.nom} dans un paramètre.";
    recoit.appendChild(rien);
  }
  body.appendChild(recoit);

  const sec = document.createElement("section");
  sec.className = "agent-section";
  const h3 = document.createElement("h3");
  h3.className = "connectors-sub";
  h3.textContent = "Étapes";
  sec.appendChild(h3);
  (draft.steps || []).forEach((etape, i) => {
    sec.appendChild(renderEtape(etape, i, draft, state, actions));
  });

  const ajouts = document.createElement("div");
  ajouts.className = "composition-ajouts";
  for (const [type, def] of Object.entries(TYPES)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ghost btn-sm";
    b.textContent = "+ " + def.titre;
    b.title = def.aide;
    b.addEventListener("click", () => actions.ajouterEtape(type));
    ajouts.appendChild(b);
  }
  sec.appendChild(ajouts);
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
  valider.textContent = draft.id ? "Enregistrer les modifications" : "Enregistrer en brouillon";
  valider.disabled = !String(draft.name || "").trim() || !(draft.steps || []).length;
  valider.addEventListener("click", () => actions.enregistrerComposition());
  barre.appendChild(annuler);
  barre.appendChild(valider);
  body.appendChild(barre);
}
