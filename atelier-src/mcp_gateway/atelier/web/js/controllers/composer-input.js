/** Composer — auto-grow textarea, pièces jointes, arrêt génération. */

import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { bindAutoGrowTextarea, syncAutoGrowTextarea } from "../ui/auto-grow-textarea.js";
import { noteDuMode } from "../ui/mode-processus.js";
import { optionsDuModele } from "../ui/choix-du-modele.js";
import { tourDeLaConversation } from "../ui/etat-du-tour.js";

const MAX_TEXTAREA_PX = 160;
const MAX_ATTACHMENTS = 8;

function formatSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * @param {object} ctx
 */
export function createComposerInputController(ctx) {
  const { state, render } = ctx;
  let grow = null;

  function syncGrow() {
    syncAutoGrowTextarea($("composer-input"));
  }

  function resetGrow() {
    grow?.reset();
  }

  function clearAttachments() {
    state.composerAttachments = [];
    renderAttachments();
  }

  function renderAttachments() {
    const strip = $("composer-attachments");
    if (!strip) return;
    const files = state.composerAttachments || [];
    strip.innerHTML = "";
    if (!files.length) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    for (const f of files) {
      const chip = document.createElement("span");
      chip.className = "composer-attach-chip";
      const label = document.createElement("span");
      label.className = "composer-attach-chip-label";
      label.textContent = `${f.name} (${formatSize(f.size)})`;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "composer-attach-chip-remove";
      rm.setAttribute("aria-label", `Retirer ${f.name}`);
      rm.textContent = "×";
      rm.addEventListener("click", async () => {
        // Un fichier encore côté écran n'a rien déposé sur le pod : rien à retirer.
        if (!f.local && state.token && state.sessionId && f.id) {
          try {
            await api.deleteSessionAttachment(state.token, state.sessionId, f.id);
          } catch {
            /* ignore stale */
          }
        }
        state.composerAttachments = state.composerAttachments.filter((x) => x !== f);
        renderAttachments();
        syncGrow();
      });
      chip.append(label, rm);
      strip.appendChild(chip);
    }
  }

  async function onStop() {
    if (!state.token || !state.sessionId || !tourDeLaConversation(state).enCours) return;
    // La conversation visée est celle qu'on regarde au moment du clic, et
    // seulement elle : une autre qui tourne ne s'arrête pas par ce bouton.
    const visee = state.sessionId;
    try {
      await api.interruptSession(state.token, visee);
    } catch (err) {
      S.setError(state, err.message || String(err));
      render();
      return;
    }
    // L'arrêt abandonne ce qui attendait, mais le service le fait un instant
    // après avoir répondu : on relit à deux reprises plutôt que de garder à
    // l'écran des messages qui ne partiront plus.
    for (const delai of [0, 700]) {
      if (delai) await new Promise((r) => setTimeout(r, delai));
      try {
        const file = await api.fileDesMessages(state.token, visee);
        if (state.sessionId === visee) S.setEnFile(state, file?.messages || []);
      } catch {
        /* relue à la prochaine ouverture */
      }
      render();
    }
  }

  function onAttachClick(e) {
    e.preventDefault();
    const input = $("composer-attach-input");
    if (input && !input.disabled) input.click();
  }

  async function onAttachFiles(e) {
    const input = e.target;
    const files = input?.files;
    if (!files?.length || !state.token) return;
    const pending = state.composerAttachments || [];
    if (pending.length >= MAX_ATTACHMENTS) {
      S.setError(state, `Maximum ${MAX_ATTACHMENTS} fichiers par message.`);
      render();
      input.value = "";
      return;
    }
    S.setError(state, "");
    for (const file of files) {
      if (pending.length >= MAX_ATTACHMENTS) break;
      if (!state.sessionId) {
        // Premier message : la conversation n'existe pas encore. Le fichier
        // reste côté écran, et part dès qu'elle naît.
        state.composerAttachments.push({ local: true, file, name: file.name, size: file.size });
        continue;
      }
      try {
        const meta = await api.uploadSessionAttachment(
          state.token,
          state.sessionId,
          file
        );
        state.composerAttachments.push(meta);
      } catch (err) {
        S.setError(state, err.message || String(err));
        break;
      }
    }
    input.value = "";
    renderAttachments();
    syncGrow();
    render();
  }

  /**
   * Dépose sur la conversation les fichiers choisis avant qu'elle existe.
   * Rend la liste complète des pièces jointes déposées ; lève si un dépôt
   * échoue (les autres restent à l'écran, rien n'est perdu).
   */
  async function deposerLesFichiersEnAttente() {
    const liste = state.composerAttachments || [];
    if (!state.sessionId || !liste.some((a) => a.local)) return liste;
    const deposees = [];
    for (const a of liste) {
      if (!a.local) {
        deposees.push(a);
        continue;
      }
      try {
        deposees.push(await api.uploadSessionAttachment(state.token, state.sessionId, a.file));
      } catch (err) {
        state.composerAttachments = [...deposees, ...liste.slice(deposees.length)];
        renderAttachments();
        throw new Error(`${a.name} : ${err.message || err}`);
      }
    }
    state.composerAttachments = deposees;
    return deposees;
  }

  // -- le modèle de la conversation (`/model` de Claude Code) -----------------

  /** Le catalogue du service, lu une fois ; on réessaie au plus une fois par minute. */
  async function chargerLesModeles() {
    if (!state.token || state.modelsCatalog || state.modelsCatalogEnCours) return;
    const maintenant = Date.now();
    if (state.modelsCatalogEssai && maintenant - state.modelsCatalogEssai < 60000) return;
    state.modelsCatalogEssai = maintenant;
    state.modelsCatalogEnCours = true;
    try {
      S.setModelsCatalog(state, await api.listModels(state.token));
    } catch {
      /* le sélecteur garde « Modèle par défaut » */
    } finally {
      state.modelsCatalogEnCours = false;
    }
    if (state.modelsCatalog) render();
  }

  /** Remplit le sélecteur ; ne reconstruit les options que si elles ont changé. */
  function remplirLesModeles(select, valeur) {
    chargerLesModeles();
    const options = optionsDuModele(state.modelsCatalog, valeur);
    const signature = options.map((o) => `${o.value}\u0000${o.label}`).join("\u0001");
    if (select.dataset.signature !== signature) {
      select.replaceChildren(
        ...options.map((o) => {
          const opt = document.createElement("option");
          opt.value = o.value;
          opt.textContent = o.label;
          return opt;
        })
      );
      select.dataset.signature = signature;
    }
    if (select.value !== valeur) select.value = valeur;
  }

  /** Pose le modèle sur la conversation, ou le retient jusqu'au premier message. */
  async function appliquerModele(modele) {
    if (!state.sessionId) {
      state.modeleEnAttente = modele;
      render();
      return true;
    }
    try {
      const rec = await api.patchSession(state.token, state.sessionId, { model: modele });
      const i = (state.sessions || []).findIndex((x) => x.session_id === rec.session_id);
      if (i >= 0) state.sessions[i] = rec;
      S.setError(state, "");
      render();
      return true;
    } catch (err) {
      S.setError(state, `Modèle non appliqué : ${err.message}`);
      render();
      return false;
    }
  }

  async function onModelChange(ev) {
    await appliquerModele(ev.target.value);
  }

  function bind() {
    const input = $("composer-input");
    grow = bindAutoGrowTextarea(input, { maxHeight: MAX_TEXTAREA_PX });

    $("btn-stop")?.addEventListener("click", onStop);
    $("btn-composer-attach")?.addEventListener("click", onAttachClick);
    $("composer-attach-input")?.addEventListener("change", onAttachFiles);
    $("composer-model")?.addEventListener("change", onModelChange);
    $("composer-mode")?.addEventListener("change", onModeChange);
    $("btn-mode-projet")?.addEventListener("click", onModeProjet);
  }

  const AVERTISSEMENT_BYPASS =
    "Sans garde-fou : l’agent agira sans rien demander — modifier ou supprimer des " +
    "fichiers, lancer des commandes, y compris hors du projet. Ce choix vaut aussi " +
    "dans VS Code et au terminal pour cette conversation.\n\nContinuer ?";

  function slugCourant() {
    const courante = state.sessions?.find((x) => x.session_id === state.sessionId);
    return state.slug || courante?.slug || state.pendingProjectSlug || "";
  }

  /** Le mode de travail se pose sur la conversation, pas sur le message. */
  async function onModeChange(ev) {
    const mode = ev.target.value;
    if (mode === "bypassPermissions" && !window.confirm(AVERTISSEMENT_BYPASS)) {
      // Refusé : le sélecteur reprend la valeur d'avant au prochain rendu.
      render();
      return;
    }
    if (!state.sessionId) {
      // Conversation pas encore née : le choix attend le premier message.
      state.modeEnAttente = mode;
      render();
      return;
    }
    try {
      const rec = await api.patchSession(state.token, state.sessionId, {
        permission_mode: mode,
      });
      // La liste porte l'état des conversations : sans cette mise à jour, le
      // sélecteur reviendrait à sa valeur d'avant au prochain rendu.
      const i = (state.sessions || []).findIndex((x) => x.session_id === rec.session_id);
      if (i >= 0) state.sessions[i] = rec;
      render();
      await direCeQueVautLeMode(rec.session_id);
    } catch (err) {
      S.setError(state, `Mode non appliqué : ${err.message}`);
      render();
    }
  }

  /**
   * Un onglet VS Code ouvert garde son mode jusqu'à sa fermeture : on le dit
   * près du sélecteur, et l'écart s'il agit plus librement que le choix.
   */
  async function direCeQueVautLeMode(sessionId) {
    try {
      const processus = await api.processusDeLaConversation(sessionId);
      state.modeProcessus = { sessionId, note: noteDuMode(processus) };
    } catch {
      state.modeProcessus = null;
    }
    render();
  }

  /** Le mode affiché devient le défaut du projet (conversations sans choix propre). */
  async function onModeProjet() {
    const slug = slugCourant();
    const mode = $("composer-mode")?.value || "";
    if (!slug || !mode) return;
    if (mode === "bypassPermissions" && !window.confirm(
      "Sans garde-fou pour tout le projet : chaque conversation sans choix propre agira " +
      "sans rien demander, dans l’Atelier, dans VS Code et au terminal.\n\nContinuer ?",
    )) return;
    try {
      await api.setProjectMode(state.token, slug, mode);
      S.setError(state, "");
    } catch (err) {
      S.setError(state, `Défaut du projet non appliqué : ${err.message}`);
    }
    render();
  }

  return {
    bind,
    syncGrow,
    resetGrow,
    renderAttachments,
    clearAttachments,
    deposerLesFichiersEnAttente,
    remplirLesModeles,
    appliquerModele,
  };
}
