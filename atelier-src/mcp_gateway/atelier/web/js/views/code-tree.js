/** Vue Code — arbre projets / sessions. */

import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { showContextMenu } from "../ui/context-menu.js";
import { icone } from "../ui/icones.js";

/**
 * Ce que l'arbre montre, réduit à une chaîne : deux rendus de même empreinte
 * donnent le même arbre, au détail près de la ligne active.
 *
 * L'arbre était reconstruit à chaque rendu — et un tour en cours en déclenche
 * des centaines, la veille de la liste un toutes les quinze secondes. Un clic
 * qui tombait entre l'appui et le relâchement d'une reconstruction était
 * perdu : le bouton pressé n'existait plus au relâchement. Le survol et le
 * focus clavier sautaient de même.
 */
export function empreinteDeLArbre(state, projets, orphelines, sessionsDe) {
  const lignes = [
    state.montrerArchives ? "A" : "",
    state.editingProjectSlug || "",
    state.editingSessionId || "",
    [...state.expandedSlugs].sort().join(","),
  ];
  const session = (x) =>
    [x.session_id, x.title || "", x.state || "", x.turns ?? "", x.attend_une_decision ? 1 : 0].join("~");
  for (const p of projets) {
    lignes.push(["P", p.slug, p.title || "", p.archived ? 1 : 0, p.path || ""].join("~"));
    if (state.expandedSlugs.has(p.slug)) for (const x of sessionsDe(p.slug)) lignes.push(session(x));
  }
  for (const x of orphelines) lignes.push("O" + session(x));
  return lignes.join("|");
}

/**
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 * @param {() => void} ctx.writeQuery
 * @param {object} ctx.actions — handlers sessions/projets
 */
export function createCodeTreeView(ctx) {
  const { state, render, writeQuery, actions } = ctx;

  // Contrat de pastilles commun : au repos / en reponse / en erreur. Le texte
  // vient de la même table que la ligne de dessous, pour qu'ils ne se
  // contredisent jamais.
  function sessionTone(session) {
    // Attendre une autorisation n'est pas répondre : l'agent est arrêté
    // jusqu'à ce qu'on vienne. Cela se voit d'abord, avant tout état.
    if (session?.attend_une_decision) return ["warn", "autorisation demandée"];
    const dit = S.etatLisible(session?.state) || "au repos";
    switch (session?.state) {
      case "running":
        return ["busy", dit];
      case "failed":
      case "timeout":
        return ["err", dit];
      case "interrupted":
        return ["warn", dit];
      case "archived":
      case "created":
        return ["off", dit];
      default:
        return ["ok", dit];
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
    btn.dataset.session = s.session_id;
    btn.classList.toggle("active", s.session_id === state.sessionId);
    if (s.session_id === state.sessionId) btn.setAttribute("aria-current", "true");

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
    // Le titre complet au survol : la ligne le tronque.
    btn.title = `${S.sessionLabel(s)}
${project?.title || s.slug} · ${S.sessionMetaLine(s)}`;
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
    menuBtn.className = "ghost session-menu-btn icon-btn";
    menuBtn.appendChild(icone("points"));
    menuBtn.title = "Actions de la conversation";
    menuBtn.setAttribute("aria-label", `Actions de la conversation « ${S.sessionLabel(s)} »`);
    menuBtn.setAttribute("aria-haspopup", "menu");
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
    chevron.className = "chevron icon-btn";
    chevron.appendChild(icone("chevron-droite"));
    chevron.setAttribute("aria-expanded", expanded ? "true" : "false");
    chevron.setAttribute("aria-label", `${expanded ? "Replier" : "Déplier"} ${project.title || project.slug}`);
    chevron.addEventListener("click", (e) => {
      S.toggleExpanded(state, project.slug);
      renderProjectTree();
      // Le bouton a été reconstruit : au clavier (un clic sans pointeur a
      // `detail` à 0), le focus le suit ; à la souris, on ne l'impose pas.
      if (e.detail === 0) {
        for (const bloc of $("project-tree")?.querySelectorAll(".project-block") || []) {
          if (bloc.dataset.slug === project.slug) bloc.querySelector(".chevron")?.focus();
        }
      }
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
      const range = project.archived ? " · rangé" : "";
      // Le nom passe en texte, jamais en HTML : un projet nommé « <img …> »
      // s'interprétait dans la barre latérale.
      const nom = document.createElement("span");
      nom.className = "project-title-texte";
      nom.textContent = `${project.title || project.slug}${range}`;
      titleBtn.append(icone("dossier", "project-icone"), nom);
      titleBtn.title = `${project.title || project.slug}
${project.path} (${project.slug})`;
      titleBtn.classList.toggle("project-archived", !!project.archived);
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
    newSession.className = "ghost project-new icon-btn";
    newSession.appendChild(icone("plus"));
    newSession.title = "Nouvelle conversation";
    newSession.setAttribute("aria-label", `Nouvelle conversation dans ${project.title || project.slug}`);
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
        li.textContent = "Aucune conversation";
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
      project.archived
        ? { label: "Ressortir le projet", action: () => actions.archiveProject(project, false) }
        : { label: "Ranger le projet", action: () => actions.archiveProject(project, true) },
      {
        label: "Supprimer le projet",
        danger: true,
        action: () => actions.deleteProject(project),
      },
    ]);
  }

  let empreinteRendue = "";

  /** Ne touche que la ligne active : le reste de l'arbre n'a pas bougé. */
  function marquerActive(root) {
    for (const b of root.querySelectorAll(".session-btn")) {
      const active = b.dataset.session === state.sessionId;
      b.classList.toggle("active", active);
      if (active) b.setAttribute("aria-current", "true");
      else b.removeAttribute("aria-current");
    }
  }

  function renderProjectTree({ forcer = false } = {}) {
    const root = $("project-tree");
    if (!root) return;
    const projetsVus = S.codeProjects(state);
    const orphelinesVues = S.orphanCodeSessions(state);
    const empreinte = empreinteDeLArbre(state, projetsVus, orphelinesVues, (slug) =>
      S.sessionsForSlug(state, slug)
    );
    if (!forcer && empreinte === empreinteRendue && root.dataset.arbre === "code") {
      marquerActive(root);
      return;
    }
    empreinteRendue = empreinte;
    root.dataset.arbre = "code";
    root.innerHTML = "";
    // La colonne est la même que celle de l'Assistant, qui la renomme : sans
    // ceci, elle gardait « Conversations de l'Assistant » en revenant en Code.
    root.setAttribute("aria-label", "Projets et conversations");

    const headerRow = document.createElement("div");
    headerRow.className = "tree-toolbar";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "ghost tree-add";
    const ajout = document.createElement("span");
    ajout.textContent = "Nouveau projet";
    addBtn.append(icone("plus"), ajout);
    addBtn.title = "Créer un projet code";
    addBtn.addEventListener("click", () => actions.newProject());
    headerRow.appendChild(addBtn);

    // Ranger ne doit pas vouloir dire perdre : sans ce bouton, un projet rangé
    // — et toutes ses conversations avec lui — disparaissait de l'écran sans
    // aucun moyen de le revoir. Douze projets et cinq conversations étaient
    // dans ce cas.
    const archives = document.createElement("button");
    archives.type = "button";
    archives.className = "ghost tree-archives";
    archives.textContent = state.montrerArchives ? "Masquer les rangés" : "Rangés";
    archives.title = state.montrerArchives
      ? "Ne plus afficher les projets et conversations rangés"
      : "Afficher aussi les projets et conversations rangés";
    archives.setAttribute("aria-pressed", state.montrerArchives ? "true" : "false");
    archives.addEventListener("click", () => actions.basculerArchives());
    headerRow.appendChild(archives);
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
      orphanHead.textContent = "Conversations sans projet";
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
      empty.textContent = state.montrerArchives
        ? "Aucun projet, même rangé."
        : "Aucun projet — créez le premier.";
      root.appendChild(empty);
    }
  }

  return { renderProjectTree };
}
