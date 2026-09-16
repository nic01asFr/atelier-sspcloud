/** Vue Code — arbre projets / sessions. */

import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { showContextMenu } from "../ui/context-menu.js";

/**
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 * @param {() => void} ctx.writeQuery
 * @param {object} ctx.actions — handlers sessions/projets
 */
export function createCodeTreeView(ctx) {
  const { state, render, writeQuery, actions } = ctx;

  // Contrat de pastilles commun : au repos / en reponse / en erreur.
  function sessionTone(session) {
    // Attendre une autorisation n'est pas répondre : l'agent est arrêté
    // jusqu'à ce qu'on vienne. Cela se voit d'abord, avant tout état.
    if (session?.attend_une_decision) return ["warn", "autorisation demandée"];
    switch (session?.state) {
      case "running":
        return ["busy", "en réponse"];
      case "failed":
      case "timeout":
        return ["err", "en erreur"];
      case "interrupted":
        return ["warn", "interrompue"];
      case "archived":
        return ["off", "archivée"];
      case "created":
        return ["off", "jamais lancée"];
      default:
        return ["ok", "au repos"];
    }
  }

  function renderSessionRow(s, project) {
    const li = document.createElement("li");
    li.className = "session-row";

    // Renommage inline : le champ remplace la ligne, comme pour un projet.
    if (state.editingSessionId === s.session_id) {
      const champ = document.createElement("input");
      champ.type = "text";
      champ.className = "project-title-edit session-title-edit";
      champ.value = S.sessionLabel(s);
      champ.setAttribute("aria-label", "Titre de la conversation");
      let clos = false;
      const valider = () => {
        if (clos) return;
        clos = true;
        actions.commitRenameSession(s, champ.value);
      };
      champ.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          valider();
        } else if (e.key === "Escape") {
          e.preventDefault();
          clos = true;
          actions.cancelRenameSession();
        }
      });
      champ.addEventListener("blur", valider);
      queueMicrotask(() => {
        champ.focus();
        champ.select();
      });
      li.appendChild(champ);
      return li;
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "session-btn";
    btn.classList.toggle("active", s.session_id === state.sessionId);

    const titleRow = document.createElement("span");
    titleRow.className = "session-title-row";
    const [tone, toneLabel] = sessionTone(s);
    const dot = document.createElement("span");
    dot.className = `status-dot status-dot-${tone}`;
    dot.title = toneLabel;
    dot.setAttribute("aria-label", toneLabel);
    const titleSpan = document.createElement("span");
    titleSpan.className = "session-title";
    titleSpan.textContent = S.sessionLabel(s);
    titleRow.appendChild(dot);
    titleRow.appendChild(titleSpan);

    const metaSpan = document.createElement("span");
    metaSpan.className = "meta";
    metaSpan.textContent = S.sessionMetaLine(s);

    btn.appendChild(titleRow);
    btn.appendChild(metaSpan);
    btn.title = `${project?.title || s.slug} · ${s.session_id}`;
    btn.addEventListener("click", () => {
      S.setSlug(state, project?.slug || s.slug);
      actions.selectSession(s.session_id);
    });
    btn.addEventListener("dblclick", (e) => {
      e.preventDefault();
      actions.startRenameSession(s);
    });
    btn.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openSessionMenu(e.clientX, e.clientY, s, project);
    });

    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.className = "ghost session-menu-btn";
    menuBtn.textContent = "⋯";
    menuBtn.title = "Actions session";
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const rect = menuBtn.getBoundingClientRect();
      openSessionMenu(rect.right, rect.bottom, s, project);
    });

    li.appendChild(btn);
    li.appendChild(menuBtn);
    return li;
  }

  function renderProjectBlock(project) {
    const block = document.createElement("div");
    block.className = "project-block";
    block.dataset.slug = project.slug;

    const head = document.createElement("div");
    head.className = "project-head";
    const expanded = state.expandedSlugs.has(project.slug);

    const chevron = document.createElement("button");
    chevron.type = "button";
    chevron.className = "chevron";
    chevron.textContent = expanded ? "▾" : "▸";
    chevron.addEventListener("click", () => {
      S.toggleExpanded(state, project.slug);
      renderProjectTree();
    });

    // Renommage inline : un seul geste, a la creation comme plus tard.
    const enEdition = state.editingProjectSlug === project.slug;
    let titleBtn;
    if (enEdition) {
      titleBtn = document.createElement("input");
      titleBtn.type = "text";
      titleBtn.className = "project-title-edit";
      titleBtn.value = project.title || project.slug;
      titleBtn.setAttribute("aria-label", "Nom du projet");
      let clos = false;
      const valider = () => {
        if (clos) return;
        clos = true;
        actions.commitRenameProject(project, titleBtn.value);
      };
      titleBtn.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          valider();
        } else if (e.key === "Escape") {
          e.preventDefault();
          clos = true;
          actions.cancelRenameProject();
        }
      });
      titleBtn.addEventListener("blur", valider);
      titleBtn.addEventListener("click", (e) => e.stopPropagation());
      queueMicrotask(() => {
        titleBtn.focus();
        titleBtn.select();
      });
    } else {
      titleBtn = document.createElement("button");
      titleBtn.type = "button";
      titleBtn.className = "project-title";
      titleBtn.innerHTML = `<span>&#128193; ${project.title || project.slug}</span>`;
      titleBtn.title = project.path + " (" + project.slug + ")";
      titleBtn.addEventListener("click", () => {
        S.ensureExpanded(state, project.slug);
        S.setSlug(state, project.slug);
        writeQuery();
        render();
      });
      titleBtn.addEventListener("dblclick", (e) => {
        e.preventDefault();
        actions.startRenameProject(project);
      });
      titleBtn.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        openProjectMenu(e.clientX, e.clientY, project);
      });
    }

    const newSession = document.createElement("button");
    newSession.type = "button";
    newSession.className = "ghost project-new";
    newSession.textContent = "+";
    newSession.title = "Nouvelle conversation";
    newSession.addEventListener("click", () => actions.newSessionForSlug(project.slug));

    head.appendChild(chevron);
    head.appendChild(titleBtn);
    head.appendChild(newSession);
    block.appendChild(head);

    if (expanded) {
      const ul = document.createElement("ul");
      ul.className = "session-list";
      const sessions = S.sessionsForSlug(state, project.slug);
      if (!sessions.length) {
        const li = document.createElement("li");
        li.className = "session-empty";
        li.textContent = "Aucune session";
        ul.appendChild(li);
      } else {
        for (const s of sessions) {
          ul.appendChild(renderSessionRow(s, project));
        }
      }
      block.appendChild(ul);
    }
    return block;
  }

  function openSessionMenu(x, y, session, project) {
    const slug = project?.slug || session.slug;
    showContextMenu(state, x, y, [
      {
        label: "Ouvrir dans VS Code",
        action: () => actions.openVscode(slug, session.session_id),
      },
      { label: "Renommer", action: () => actions.startRenameSession(session) },
      {
        label: "Copier l'id",
        action: () => actions.copySessionId(session.session_id),
      },
      { label: "Archiver", action: () => actions.archiveSession(session.session_id) },
      {
        label: "Supprimer",
        danger: true,
        action: () => actions.deleteSession(session.session_id),
      },
    ]);
  }

  function openProjectMenu(x, y, project) {
    showContextMenu(state, x, y, [
      {
        label: "Nouvelle conversation",
        action: () => actions.newSessionForSlug(project.slug),
      },
      {
        label: "Ouvrir VS Code (dossier)",
        action: () => actions.openVscode(project.slug, null),
      },
      { label: "Renommer le projet", action: () => actions.startRenameProject(project) },
      { label: "Archiver le projet", action: () => actions.archiveProject(project) },
      {
        label: "Supprimer le projet",
        danger: true,
        action: () => actions.deleteProject(project),
      },
    ]);
  }

  function renderProjectTree() {
    const root = $("project-tree");
    if (!root) return;
    root.innerHTML = "";

    const headerRow = document.createElement("div");
    headerRow.className = "tree-toolbar";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "ghost tree-add";
    addBtn.textContent = "+ Nouveau projet";
    addBtn.title = "Créer un projet code";
    addBtn.addEventListener("click", () => actions.newProject());
    headerRow.appendChild(addBtn);
    root.appendChild(headerRow);

    const projects = S.codeProjects(state);
    for (const project of projects) {
      root.appendChild(renderProjectBlock(project));
    }

    const orphans = S.orphanCodeSessions(state);
    if (orphans.length) {
      const orphanBlock = document.createElement("div");
      orphanBlock.className = "project-block orphan-block";
      const orphanHead = document.createElement("div");
      orphanHead.className = "orphan-head";
      orphanHead.textContent = "Sessions sans projet";
      orphanBlock.appendChild(orphanHead);
      const ul = document.createElement("ul");
      ul.className = "session-list";
      for (const s of orphans) {
        ul.appendChild(renderSessionRow(s, null));
      }
      orphanBlock.appendChild(ul);
      root.appendChild(orphanBlock);
    }

    if (!projects.length && !orphans.length) {
      const empty = document.createElement("p");
      empty.className = "tree-empty";
      empty.textContent = "Aucun projet code — créez le premier.";
      root.appendChild(empty);
    }
  }

  return { renderProjectTree };
}
