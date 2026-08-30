/**
 * Fige des paramètres d'un outil pour en faire une variante réutilisable.
 *
 * La passerelle représente cela comme une composition à une étape : on suit
 * le même chemin (créer, valider, promouvoir). Le formulaire vit ici plutôt
 * que dans un écran, parce que la même opération se lance depuis la fiche
 * d'un agent comme depuis la page des connecteurs.
 */

import * as api from "../api.js";
import * as S from "../state.js";
import { openModal } from "./modal.js";
import { refreshPiloteOverview } from "../services/catalog.js";

export async function ouvrirVariante({ state, outil, render, onCreated }) {
  // Les suggestions viennent de l'état : si la liste des agents n'a pas
  // encore été chargée, le champ retomberait en saisie libre.
  if (!state.piloteOverview) {
    try {
      await refreshPiloteOverview(state);
    } catch {
      /* on proposera la saisie libre */
    }
  }
  let infos;
  try {
    infos = await api.mcpToolSchema(state.token, outil.name);
  } catch (err) {
    S.setError(state, err.message || String(err));
    render?.();
    return;
  }
  const props = infos.schema?.properties || {};
  const requis = new Set(infos.schema?.required || []);

  // Ce que l'Atelier sait déjà : inutile de faire taper un identifiant
  // d'agent ou un nom de projet qu'il a sous la main.
  const suggestions = {
    projets: (state.projects || [])
      .filter((p) => p.kind !== "assistant")
      .map((p) => ({ value: p.slug, label: p.title || p.slug })),
    chemins: (state.projects || []).map((p) => ({ value: p.path, label: p.title || p.slug })),
    agents: (state.piloteOverview?.agents || []).map((a) => ({
      value: a.id,
      label: `${a.name || a.id} (${a.id})`,
    })),
  };

  /** Contrôle adapté à un paramètre : liste fermée, nombre, oui/non, suggestions. */
  const champPour = (cle, def) => {
    const base = {
      name: cle,
      label: cle + (requis.has(cle) ? " *" : ""),
      hint: def?.description ? String(def.description).slice(0, 120) : "",
      full: true,
    };
    if (Array.isArray(def?.enum) && def.enum.length) {
      return {
        ...base,
        type: "select",
        options: [{ value: "", label: "— laisser libre —" }].concat(
          def.enum.map((v) => ({ value: String(v), label: String(v) }))
        ),
      };
    }
    if (def?.type === "boolean") {
      return {
        ...base,
        type: "select",
        options: [
          { value: "", label: "— laisser libre —" },
          { value: "true", label: "oui" },
          { value: "false", label: "non" },
        ],
      };
    }
    if (def?.type === "number" || def?.type === "integer") {
      return { ...base, type: "number", placeholder: "nombre" };
    }
    if (/^(project|current_project)$/.test(cle)) {
      return { ...base, datalist: suggestions.projets, placeholder: "projet" };
    }
    if (/^(repo_path|repo)$/.test(cle)) {
      return { ...base, datalist: suggestions.chemins, placeholder: "dossier du projet" };
    }
    if (cle === "id" && /trigger/.test(infos.short || "")) {
      return { ...base, datalist: suggestions.agents, placeholder: "agent" };
    }
    if (def?.type === "array") {
      return { ...base, placeholder: "valeurs séparées par des virgules" };
    }
    return { ...base, placeholder: cle };
  };

  const champs = [
    { name: "__nom", label: "Nom affiché", placeholder: "Ex. Mémo de projet", required: true },
    { name: "__desc", label: "Description (optionnel)", placeholder: "Ce que fait cette variante" },
    { type: "section", label: "Paramètres à figer" },
    ...Object.entries(props).map(([cle, def]) => champPour(cle, def)),
  ];
  if (!Object.keys(props).length) {
    champs.push({ type: "section", label: "Cet outil ne prend aucun paramètre." });
  }

  /** Le JSON attend des types, pas des chaînes. */
  const valeurTypee = (cle, brut) => {
    const def = props[cle] || {};
    if (def.type === "boolean") return brut === "true";
    if (def.type === "number" || def.type === "integer") {
      const n = Number(brut);
      return Number.isFinite(n) ? n : undefined;
    }
    if (def.type === "array") {
      const items = brut.split(",").map((v) => v.trim()).filter(Boolean);
      return items.length ? items : undefined;
    }
    return brut;
  };

  openModal(state, {
    title: "Personnaliser un outil",
    lead: `Basé sur : ${infos.short || outil.short} — les champs laissés vides restent libres.`,
    size: "lg",
    submitLabel: "Enregistrer et activer",
    fields: champs,
    onSubmit: async (data) => {
      const nom = String(data.__nom || "").trim();
      if (!nom) throw new Error("Un nom est nécessaire.");
      const parameters = {};
      for (const cle of Object.keys(props)) {
        const v = String(data[cle] ?? "").trim();
        if (!v) continue;
        const valeur = valeurTypee(cle, v);
        if (valeur !== undefined) parameters[cle] = valeur;
      }
      if (!Object.keys(parameters).length) {
        throw new Error("Figez au moins un paramètre, sinon la variante n’apporte rien.");
      }
      const creee = await api.createToolVariant(state.token, {
        tool: outil.name,
        name: nom,
        description: String(data.__desc || "").trim(),
        parameters,
      });
      await onCreated?.(creee);
    },
  });
}
