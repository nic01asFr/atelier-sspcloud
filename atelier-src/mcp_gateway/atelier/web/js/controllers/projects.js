/** Actions projets code — création directe et renommage inline. */

import * as api from "../api.js";
import * as S from "../state.js";
import { refreshProjects, refreshSessions } from "../services/catalog.js";
import { openModal } from "../ui/modal.js";
import { nettoyerLeNom, verifierLeNom, LONGUEUR_MAX } from "../ui/nouveau-projet.js";

/**
 * @param {object} ctx
 */
export function createProjectActions(ctx) {
  const { state, render, writeQuery } = ctx;

  /**
   * Une fenêtre demande le nom ; rien n'est créé avant sa validation. Le projet
   * créé s'ouvre avec le composeur prêt : le premier message y fait naître la
   * conversation.
   */
  function newProject() {
    S.setError(state, "");
    openModal(state, {
      title: "Nouveau projet",
      lead: "Donnez un nom à votre projet. Vous pourrez écrire à l’agent juste après.",
      size: "md",
      submitLabel: "Créer le projet",
      fields: [
        {
          name: "nom",
          label: "Nom du projet",
          placeholder: "Par exemple : Atlas des écoles",
          required: true,
          full: true,
          maxlength: LONGUEUR_MAX,
        },
      ],
      onSubmit: async (data) => {
        const titre = nettoyerLeNom(data.nom);
        const erreur = verifierLeNom(titre, state.projects);
        if (erreur) throw new Error(erreur);
        const slug = S.uniqueProjectSlug(state, S.slugifyProjectName(titre) || "projet");
        await api.createProject(state.token, { slug, kind: "code", title: titre });
        await refreshProjects(state);
        S.setView(state, "code");
        S.ensureExpanded(state, slug);
        S.setSlug(state, slug);
        S.setSessionId(state, null);
        S.setMessages(state, []);
        S.setSessionMcp(state, null);
        S.setPendingProjectSlug(state, slug);
        writeQuery();
        render();
        // Le composeur est prêt : la personne écrit tout de suite.
        setTimeout(() => document.getElementById("composer-input")?.focus(), 0);
      },
    });
  }

  /** Ouvre le champ de renommage dans la liste laterale. */
  function startRename(project) {
    S.setEditingProjectSlug(state, project.slug);
    render();
  }

  function cancelRename() {
    S.setEditingProjectSlug(state, null);
    render();
  }

  /**
   * Seul le titre change : le slug reste le nom du dossier sur le pod, donc
   * renommer n'a aucun effet de bord.
   */
  async function commitRename(project, nom) {
    const titre = (nom || "").trim();
    S.setEditingProjectSlug(state, null);
    if (!titre || titre === (project.title || project.slug)) {
      render();
      return;
    }
    try {
      await api.patchProject(state.token, project.slug, { title: titre });
      await refreshProjects(state);
      await refreshSessions(state);
    } catch (err) {
      S.setError(state, err.message || String(err));
    }
    render();
  }

  /** Montrer ou cacher ce qui a été rangé, projets et conversations ensemble. */
  async function basculerArchives() {
    S.setMontrerArchives(state, !state.montrerArchives);
    try {
      await refreshProjects(state);
      await refreshSessions(state);
    } catch (err) {
      S.setError(state, err.message || String(err));
    }
    render();
  }

  /** Le projet sort de la liste ; son dossier et son code restent intacts. */
  async function archiveProject(project, ranger = true) {
    try {
      await api.patchProject(state.token, project.slug, { archived: ranger });
      if (ranger && state.slug === project.slug) {
        S.setSessionId(state, null);
        S.setMessages(state, []);
        S.setPendingProjectSlug(state, null);
      }
      await refreshProjects(state);
    } catch (err) {
      S.setError(state, err.message || String(err));
    }
    render();
  }

  /**
   * Suppression definitive — le serveur refuse tant qu'il reste une
   * conversation ou un fichier, et renvoie alors de quoi l'expliquer.
   */
  async function deleteProject(project) {
    const nom = project.title || project.slug;
    if (!confirm(`Supprimer définitivement le projet « ${nom} » ?`)) return;
    try {
      await api.deleteProject(state.token, project.slug);
      if (state.slug === project.slug) {
        S.setSlug(state, "");
        S.setSessionId(state, null);
        S.setMessages(state, []);
        S.setPendingProjectSlug(state, null);
      }
      await refreshProjects(state);
      writeQuery();
    } catch (err) {
      S.setError(
        state,
        err.status === 409
          ? `${err.message} — vous pouvez l’archiver à la place.`
          : err.message || String(err)
      );
    }
    render();
  }

  return {
    newProject,
    startRename,
    cancelRename,
    commitRename,
    archiveProject,
    basculerArchives,
    deleteProject,
  };
}
