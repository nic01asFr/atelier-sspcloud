/**
 * Sélecteur d'outils — composant partagé.
 *
 * Deux niveaux, comme la création de profil de la passerelle :
 *   - le service entier, coché d'un geste ;
 *   - ou, en dépliant, les outils un par un.
 *
 * Le même pool sert l'agent, la conversation Code et l'assistant ; seul le
 * stockage diffère. Le composant ne connaît qu'un pool et une sélection.
 *
 * Valeurs produites, dans le format attendu par le pilote :
 *   - outil intégré  → "Bash", "Read", …
 *   - service entier → "registry:<id>"
 *   - outil précis   → "mcp__<service>__<outil>"
 */

const PREFIXE_SERVICE = "registry:";

/** Comparaison insensible aux accents : « memoris » trouve « Mémoriser ». */
function sansAccent(t) {
  return String(t || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

/** Jeton d'un outil précis pour --allowedTools. */
export function jetonOutil(qualifiedName) {
  return "mcp__" + qualifiedName;
}

/**
 * @param {object} o
 * @param {string[]} o.builtins outils intégrés
 * @param {object} o.catalog catalogue du pool ({ org, personal })
 * @param {Array} o.toolsByService [{ key, count, tools:[{name, short, description}] }]
 * @param {Set<string>} o.selection valeurs cochées (mutée par le composant)
 * @param {() => void} [o.onChange]
 */
export function renderToolPicker({ builtins, catalog, toolsByService, selection, onChange }) {
  const wrap = document.createElement("div");
  wrap.className = "tool-picker";

  const outilsDe = (cle) => (toolsByService || []).find((s) => s.key === cle)?.tools || [];
  const notifier = () => onChange?.();

  // ---- Outils intégrés -------------------------------------------------
  if ((builtins || []).length) {
    const bloc = document.createElement("div");
    bloc.className = "tool-picker-group";
    const titre = document.createElement("p");
    titre.className = "tool-picker-title";
    titre.textContent = "Outils intégrés";
    bloc.appendChild(titre);
    const grille = document.createElement("div");
    grille.className = "tool-picker-grid";
    for (const nom of builtins) {
      const label = document.createElement("label");
      label.className = "tool-chip";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selection.has(nom);
      label.classList.toggle("tool-chip-on", box.checked);
      box.addEventListener("change", () => {
        if (box.checked) selection.add(nom);
        else selection.delete(nom);
        label.classList.toggle("tool-chip-on", box.checked);
        notifier();
      });
      const t = document.createElement("span");
      t.className = "tool-chip-name";
      t.textContent = nom;
      label.appendChild(box);
      label.appendChild(t);
      grille.appendChild(label);
    }
    bloc.appendChild(grille);
    wrap.appendChild(bloc);
  }

  // ---- Services, avec affinage outil par outil -------------------------
  const services = [
    ...(catalog?.personal || []).map((e) => ({ e, cle: PREFIXE_SERVICE + e.id, groupe: "Mes connecteurs" })),
    ...(catalog?.org || []).map((e) => ({ e, cle: e.id, groupe: "Plateforme" })),
  ];

  const recherche = document.createElement("input");
  recherche.type = "search";
  recherche.className = "tool-picker-search-input";
  recherche.placeholder = "Rechercher un outil…";
  if (services.some((s) => outilsDe(s.cle).length)) wrap.appendChild(recherche);

  const lignes = [];

  for (const { e, cle, groupe } of services) {
    const outils = outilsDe(cle);
    const ligne = document.createElement("div");
    ligne.className = "tool-service";
    ligne.dataset.groupe = groupe;

    const tete = document.createElement("div");
    tete.className = "tool-service-head";

    const chevron = document.createElement("button");
    chevron.type = "button";
    chevron.className = "chevron";
    chevron.textContent = "▸";
    chevron.disabled = !outils.length;
    chevron.title = outils.length ? "Voir les outils" : "Aucun outil connu";

    const boxService = document.createElement("input");
    boxService.type = "checkbox";
    boxService.setAttribute("aria-label", "Tout le service " + (e.name || e.id));

    const nom = document.createElement("strong");
    nom.className = "tool-service-name";
    nom.textContent = e.name || e.id;

    const compteur = document.createElement("span");
    compteur.className = "tool-service-count";

    const actions = document.createElement("span");
    actions.className = "tool-service-actions";
    const btnTout = document.createElement("button");
    btnTout.type = "button";
    btnTout.className = "ghost btn-sm";
    btnTout.textContent = "Tout";
    const btnAucun = document.createElement("button");
    btnAucun.type = "button";
    btnAucun.className = "ghost btn-sm";
    btnAucun.textContent = "Aucun";
    actions.appendChild(btnTout);
    actions.appendChild(btnAucun);

    const corps = document.createElement("div");
    corps.className = "tool-service-tools";
    corps.hidden = true;

    const cases = [];
    for (const outil of outils) {
      const jeton = jetonOutil(outil.name);
      const label = document.createElement("label");
      label.className = "tool-chip tool-chip-sm";
      label.title = outil.description || "";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.dataset.recherche = sansAccent(outil.short + " " + (outil.description || ""));
      const t = document.createElement("span");
      t.className = "tool-chip-name";
      t.textContent = outil.short;
      label.appendChild(box);
      label.appendChild(t);
      box.addEventListener("change", () => {
        // Un choix fin sort du « service entier » : on éclate la sélection.
        if (selection.has(cle)) {
          selection.delete(cle);
          for (const c of cases) if (c.box !== box) selection.add(c.jeton);
        }
        if (box.checked) selection.add(jeton);
        else selection.delete(jeton);
        rafraichir();
        notifier();
      });
      cases.push({ box, label, jeton });
      corps.appendChild(label);
    }

    /** Réaligne l'état visuel sur la sélection réelle. */
    function rafraichir() {
      const entier = selection.has(cle);
      for (const c of cases) {
        c.box.checked = entier || selection.has(c.jeton);
        c.label.classList.toggle("tool-chip-on", c.box.checked);
      }
      const coches = entier ? cases.length : cases.filter((c) => selection.has(c.jeton)).length;
      boxService.checked = entier || (cases.length > 0 && coches === cases.length);
      boxService.indeterminate = !boxService.checked && coches > 0;
      compteur.textContent = cases.length
        ? coches + "/" + cases.length
        : e.tools
          ? e.tools + " outils"
          : "local";
      tete.classList.toggle("tool-service-on", boxService.checked || coches > 0);
    }

    const toutCocher = () => {
      for (const c of cases) selection.delete(c.jeton);
      selection.add(cle);
      rafraichir();
      notifier();
    };
    const toutDecocher = () => {
      selection.delete(cle);
      for (const c of cases) selection.delete(c.jeton);
      rafraichir();
      notifier();
    };

    boxService.addEventListener("change", () => {
      if (boxService.checked) toutCocher();
      else toutDecocher();
    });
    btnTout.addEventListener("click", toutCocher);
    btnAucun.addEventListener("click", toutDecocher);
    chevron.addEventListener("click", () => {
      corps.hidden = !corps.hidden;
      chevron.textContent = corps.hidden ? "▸" : "▾";
    });

    tete.appendChild(chevron);
    tete.appendChild(boxService);
    tete.appendChild(nom);
    tete.appendChild(compteur);
    tete.appendChild(actions);
    ligne.appendChild(tete);
    ligne.appendChild(corps);
    lignes.push({ ligne, cases, corps, chevron });
    rafraichir();
  }

  for (const groupe of ["Mes connecteurs", "Plateforme"]) {
    const dedans = lignes.filter((l) => l.ligne.dataset.groupe === groupe);
    if (!dedans.length) continue;
    const bloc = document.createElement("div");
    bloc.className = "tool-picker-group";
    const h = document.createElement("p");
    h.className = "tool-picker-title";
    h.textContent = groupe;
    bloc.appendChild(h);
    for (const l of dedans) bloc.appendChild(l.ligne);
    wrap.appendChild(bloc);
  }

  // La recherche déplie les services qui contiennent une correspondance.
  recherche.addEventListener("input", () => {
    const q = sansAccent(recherche.value.trim());
    for (const l of lignes) {
      let visibles = 0;
      for (const c of l.cases) {
        const match = !q || c.box.dataset.recherche.includes(q);
        c.label.hidden = !match;
        if (match) visibles += 1;
      }
      if (q) {
        l.ligne.hidden = visibles === 0;
        l.corps.hidden = visibles === 0;
        l.chevron.textContent = visibles ? "▾" : "▸";
      } else {
        l.ligne.hidden = false;
        l.corps.hidden = true;
        l.chevron.textContent = "▸";
      }
    }
  });

  if (!wrap.children.length) {
    const vide = document.createElement("p");
    vide.className = "empty-hint";
    vide.textContent = "Aucun outil disponible — ajoutez un connecteur.";
    wrap.appendChild(vide);
  }
  return wrap;
}
