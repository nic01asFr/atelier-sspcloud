/** Modales formulaire — hints, sections, tailles, selects soignés. */

import * as S from "../state.js";
import { $ } from "../core/dom.js";

export function closeModal(state) {
  S.setModal(state, null);
  const backdrop = $("modal-backdrop");
  if (backdrop) {
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
  if (submit) submit.textContent = "Confirmer";
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
export function openModal(state, { title, lead, size, submitLabel, fields, onSubmit }) {
  S.setModal(state, { title, lead, size, submitLabel, fields, onSubmit });
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
  if (submit) submit.textContent = submitLabel || "Confirmer";

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
    const el = form.elements[field.name];
    data[field.name] = el?.value?.trim() || "";
  }
  const submit = $("modal-submit");
  if (submit) {
    submit.disabled = true;
    submit.textContent = "Création…";
  }
  try {
    await modal.onSubmit(data);
    closeModal(state);
  } catch (err) {
    $("modal-error").hidden = false;
    $("modal-error").textContent = err.message || String(err);
    if (submit) {
      submit.disabled = false;
      submit.textContent = modal.submitLabel || "Confirmer";
    }
  }
}

export function bindModal(state) {
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
