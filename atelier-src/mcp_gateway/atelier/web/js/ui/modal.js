/** Modales formulaire — hints, sections, tailles, selects soignés. */

import * as S from "../state.js";
import { $ } from "../core/dom.js";

export function closeModal(state) {
  S.setModal(state, null);
  porteeCourante = null;
  const backdrop = $("modal-backdrop");
  if (backdrop) {
    backdrop.style.inset = "";
    backdrop.classList.remove("modal-backdrop-scoped");
    backdrop.hidden = true;
    backdrop.classList.add("hidden");
    backdrop.setAttribute("aria-hidden", "true");
  }
  const err = $("modal-error");
  if (err) err.hidden = true;
  const fields = $("modal-fields");
  if (fields) fields.innerHTML = "";
  const modal = $("modal");
  if (modal) {
    modal.classList.remove("modal-lg", "modal-md");
  }
  const submit = $("modal-submit");
  if (submit) {
    submit.textContent = "Confirmer";
    // Le bouton est désactivé le temps de l'envoi, et la modale se ferme
    // ensuite sans jamais le réarmer : il restait mort pour toutes les
    // modales suivantes, avec son libellé juste et un curseur d'attente
    // trompeur. Un enregistrement réussi bloquait donc tous les suivants,
    // jusqu'au rechargement de la page.
    //
    // La marque d'envoi se retire ici aussi : elle n'était ôtée qu'en cas
    // d'erreur, si bien qu'après un succès le bouton gardait son curseur
    // d'attente — le même mensonge, par une autre porte.
    submit.disabled = false;
    submit.classList.remove("modal-submit-envoi");
  }
  const lead = $("modal-lead");
  if (lead) {
    lead.hidden = true;
    lead.textContent = "";
  }
}

/**
 * @param {object} state
 * @param {{
 *   title: string,
 *   lead?: string,
 *   size?: "md" | "lg",
 *   submitLabel?: string,
 *   fields: Array<object>,
 *   onSubmit: (data: Record<string, string>) => Promise<void> | void,
 * }} opts
 */
/**
 * Circonscrit la modale à la zone d'où elle est ouverte.
 *
 * Une question posée depuis une conversation porte sur cette conversation :
 * couvrir l'écran entier la détacherait de son contexte et masquerait ce
 * qu'on est en train de lire. Sur mobile, où la conversation occupe déjà
 * tout, le cadrage n'a plus d'objet.
 */
function cadrerModale(portee) {
  const backdrop = $("modal-backdrop");
  if (!backdrop) return;
  const cible = portee ? document.querySelector(portee) : null;
  if (!cible || window.innerWidth < 720 || cible.offsetParent === null) {
    backdrop.style.inset = "";
    backdrop.classList.remove("modal-backdrop-scoped");
    return;
  }
  const r = cible.getBoundingClientRect();
  backdrop.style.inset = `${Math.round(r.top)}px ${Math.round(
    window.innerWidth - r.right
  )}px ${Math.round(window.innerHeight - r.bottom)}px ${Math.round(r.left)}px`;
  backdrop.classList.add("modal-backdrop-scoped");
}

let porteeCourante = null;

export function openModal(
  state,
  { title, lead, size, submitLabel, fields, onSubmit, scope }
) {
  S.setModal(state, { title, lead, size, submitLabel, fields, onSubmit, scope });
  porteeCourante = scope || null;
  cadrerModale(porteeCourante);
  $("modal-title").textContent = title;

  const modal = $("modal");
  if (modal) {
    modal.classList.toggle("modal-lg", size === "lg");
    modal.classList.toggle("modal-md", size !== "lg");
  }

  const leadEl = $("modal-lead");
  if (leadEl) {
    if (lead) {
      leadEl.hidden = false;
      leadEl.textContent = lead;
    } else {
      leadEl.hidden = true;
      leadEl.textContent = "";
    }
  }

  const submit = $("modal-submit");
  if (submit) {
    submit.textContent = submitLabel || "Confirmer";
    // Ceinture et bretelles : une modale qui s'ouvre a toujours son bouton
    // vivant, quel que soit l'état laissé par la précédente — et sans la
    // marque d'envoi, qui pourrait avoir survécu à une fermeture par un autre
    // chemin qu'un envoi réussi.
    submit.disabled = false;
    submit.classList.remove("modal-submit-envoi");
  }

  const container = $("modal-fields");
  container.innerHTML = "";
  for (const field of fields) {
    if (field.type === "section") {
      const sec = document.createElement("p");
      sec.className = "modal-section";
      sec.textContent = field.label || "";
      container.appendChild(sec);
      continue;
    }

    if (field.type === "checklist") {
      // Une liste de cases n'est pas un champ de saisie : elle a son propre
      // conteneur, et sa valeur se relit dans le DOM au moment d'envoyer.
      const bloc = document.createElement("div");
      bloc.className = "field modal-field modal-field-full modal-checklist";
      const titre = document.createElement("span");
      titre.className = "modal-label";
      titre.textContent = field.label || "";
      bloc.appendChild(titre);
      if (field.hint) {
        const hint = document.createElement("span");
        hint.className = "modal-hint";
        hint.textContent = field.hint;
        bloc.appendChild(hint);
      }
      const ul = document.createElement("ul");
      ul.className = "modal-checklist-list";
      for (const opt of field.options || []) {
        const li = document.createElement("li");
        const lab = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = String(opt.value);
        cb.checked = !!opt.checked;
        cb.disabled = !!opt.disabled;
        cb.dataset.checklist = field.name;
        const nom = document.createElement("span");
        nom.className = "modal-checklist-name";
        nom.textContent = opt.label;
        lab.appendChild(cb);
        lab.appendChild(nom);
        li.appendChild(lab);
        if (opt.hint) {
          const h = document.createElement("span");
          h.className = "modal-checklist-hint";
          h.textContent = opt.hint;
          li.appendChild(h);
        }
        ul.appendChild(li);
      }
      bloc.appendChild(ul);
      container.appendChild(bloc);
      continue;
    }

    const wrap = document.createElement("label");
    wrap.className = "field modal-field";
    if (field.full) wrap.classList.add("modal-field-full");

    const span = document.createElement("span");
    span.className = "modal-label";
    span.textContent = field.label;
    wrap.appendChild(span);

    if (field.hint) {
      const hint = document.createElement("span");
      hint.className = "modal-hint";
      hint.textContent = field.hint;
      wrap.appendChild(hint);
    }

    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = field.rows || 3;
    } else if (field.type === "select") {
      input = document.createElement("select");
      for (const opt of field.options || []) {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        if (String(opt.value) === String(field.value ?? "")) o.selected = true;
        input.appendChild(o);
      }
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      // Liste de suggestions : on propose ce qui existe sans interdire de
      // saisir autre chose — taper un identifiant de mémoire n'a pas de sens.
      if (Array.isArray(field.datalist) && field.datalist.length) {
        const dl = document.createElement("datalist");
        dl.id = `modal-list-${field.name}`;
        for (const opt of field.datalist) {
          const o = document.createElement("option");
          o.value = String(opt.value ?? opt);
          if (opt.label && opt.label !== opt.value) o.label = opt.label;
          dl.appendChild(o);
        }
        input.setAttribute("list", dl.id);
        wrap.appendChild(dl);
      }
    }
    input.id = `modal-field-${field.name}`;
    input.name = field.name;
    if (field.type !== "select") {
      input.value = field.value || "";
    }
    input.placeholder = field.placeholder || "";
    if (field.required) input.required = true;
    if (field.maxlength) input.maxLength = field.maxlength;
    if (field.pattern) input.pattern = field.pattern;
    if (field.autocomplete) input.autocomplete = field.autocomplete;
    wrap.appendChild(input);
    container.appendChild(wrap);
  }
  $("modal-error").hidden = true;
  const backdrop = $("modal-backdrop");
  backdrop.hidden = false;
  backdrop.classList.remove("hidden");
  backdrop.setAttribute("aria-hidden", "false");
  const first = container.querySelector("input, textarea, select");
  if (first) first.focus();
}

async function onModalSubmit(state, ev) {
  ev.preventDefault();
  const modal = state.modal;
  if (!modal?.onSubmit) return;
  const form = $("modal-form");
  const data = {};
  for (const field of modal.fields) {
    if (field.type === "section" || !field.name) continue;
    if (field.type === "checklist") {
      data[field.name] = [
        ...form.querySelectorAll(`input[data-checklist="${field.name}"]:checked`),
      ].map((cb) => cb.value);
      continue;
    }
    const el = form.elements[field.name];
    data[field.name] = el?.value?.trim() || "";
  }
  const submit = $("modal-submit");
  if (submit) {
    submit.disabled = true;
    submit.classList.add("modal-submit-envoi");
    submit.textContent = "Envoi…";
  }
  try {
    await modal.onSubmit(data);
    closeModal(state);
  } catch (err) {
    $("modal-error").hidden = false;
    $("modal-error").textContent = err.message || String(err);
    if (submit) {
      submit.disabled = false;
      submit.classList.remove("modal-submit-envoi");
      submit.textContent = modal.submitLabel || "Confirmer";
    }
  }
}

export function bindModal(state) {
  window.addEventListener("resize", () => {
    if (state.modal) cadrerModale(porteeCourante);
  });
  $("modal-form").addEventListener("submit", (ev) => onModalSubmit(state, ev));
  $("modal-cancel").addEventListener("click", () => closeModal(state));
  $("modal-close").addEventListener("click", () => closeModal(state));
  $("modal-backdrop").addEventListener("click", (e) => {
    if (e.target === $("modal-backdrop")) closeModal(state);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.modal) closeModal(state);
  });
}
