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

/**
 * Jeton d'un outil précis pour --allowedTools.
 *
 * Les outils du pool sont qualifiés « service__outil » et se préfixent ;
 * les méta-outils de la passerelle et les compositions portent déjà leur
 * nom complet.
 */
export function jetonOutil(nom) {
  const n = String(nom || "");
  if (n.startsWith("gateway_") || n.startsWith("composition_")) return n;
  return "mcp__" + n;
}

/**
 * @param {object} o
 * @param {string[]} o.builtins outils intégrés
 * @param {object} o.catalog catalogue du pool ({ org, personal })
 * @param {Array} o.toolsByService [{ key, count, tools:[{name, short, description}] }]
 * @param {Set<string>} o.selection valeurs cochées (mutée par le composant)
 * @param {() => void} [o.onChange]
 */
export function renderToolPicker({ builtins, catalog, toolsByService, selection, onChange, onPersonnaliser }) {
  const wrap = document.createElement("div");
  wrap.className = "tool-picker";

  const outilsDe = (cle) => (toolsByService || []).find((s) => s.key === cle)?.tools || [];
  const notifier = () => onChange?.();

  /**
   * Portée d'un service monté en local : le chemin qu'il expose.
   *
   * Les outils intégrés travaillent dans le dossier de la session ; un
   * serveur de fichiers, lui, ouvre ce qu'on lui a donné au démarrage — la
   * racine de travail le cas échéant, donc tous les projets. Utile, mais
   * à savoir avant de cocher.
   */
  const porteeDe = (entree) => {
    const args = entree?.config?.args;
    if (!Array.isArray(args)) return "";
    const chemins = args.filter(
      (a) => typeof a === "string" && a.startsWith("/") && !a.endsWith(".js")
    );
    return chemins.length ? chemins[chemins.length - 1] : "";
  };

  const parCle = new Map();
  for (const e of catalog?.personal || []) parCle.set(PREFIXE_SERVICE + e.id, e);
  for (const e of catalog?.org || []) parCle.set(e.id, e);

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
  // Un service éclaté en familles porte des clés « service#famille » : on
  // compare sur la racine, sinon il réapparaîtrait en doublon.
  const declares = new Set(
    (toolsByService || []).map((s) => String(s.key).split("#")[0])
  );
  const services = [
    ...(toolsByService || []).map((s) => ({
      e: { id: s.key, name: s.label || s.key, tools: s.count },
      cle: s.key,
      groupe: s.group || "Mes connecteurs",
    })),
    // Connecteurs présents dans le pool mais dont aucun outil n'est en cache
    // (un service local ne déclare rien tant qu'il n'a pas tourné).
    ...(catalog?.personal || [])
      .filter((e) => !declares.has(PREFIXE_SERVICE + e.id))
      .map((e) => ({ e, cle: PREFIXE_SERVICE + e.id, groupe: "Mes connecteurs" })),
    ...(catalog?.org || [])
      .filter((e) => !declares.has(e.id))
      .map((e) => ({ e, cle: e.id, groupe: "Plateforme" })),
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

    const portee = porteeDe(parCle.get(cle) || e);
    let porteeEl = null;
    if (portee) {
      porteeEl = document.createElement("span");
      porteeEl.className = "tool-service-scope";
      porteeEl.textContent = "accès " + portee;
      porteeEl.title =
        "Ce service ouvre ce chemin, au-delà du dossier de travail de l’agent.";
    }

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
      box.dataset.recherche = sansAccent(
        [outil.label, outil.short, outil.description].filter(Boolean).join(" ")
      );
      const t = document.createElement("span");
      t.className = "tool-chip-name";
      // Libellé lisible en premier ; le nom technique reste visible, c'est
      // lui que l'agent recevra dans --allowedTools.
      t.textContent = outil.label || outil.short;
      label.appendChild(box);
      label.appendChild(t);
      if (outil.label) {
        const technique = document.createElement("span");
        technique.className = "tool-chip-note";
        technique.textContent = outil.short;
        label.appendChild(technique);
      }
      box.addEventListener("change", () => {
        // Un choix fin sort du « service entier » : on éclate la sélection.
        if (cleService && selection.has(cleService)) {
          selection.delete(cleService);
          for (const c of cases) if (c.box !== box) selection.add(c.jeton);
        }
        if (box.checked) selection.add(jeton);
        else selection.delete(jeton);
        rafraichir();
        notifier();
      });
      // On ne fige des paramètres que sur un outil du pool : un méta-outil
      // pilote la passerelle, et une variante en est déjà une.
      const personnalisable = groupe !== "Pilotage" && groupe !== "Compositions";
      if (onPersonnaliser && personnalisable) {
        const perso = document.createElement("button");
        perso.type = "button";
        perso.className = "tool-chip-perso";
        perso.textContent = "⚙";
        perso.title = "Figer des paramètres de cet outil";
        perso.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          onPersonnaliser(outil);
        });
        label.appendChild(perso);
      }
      cases.push({ box, label, jeton });
      corps.appendChild(label);
    }

    // Un regroupement (famille d'un service) n'a pas de jeton utilisable :
    // le cocher revient à cocher chacun de ses outils.
    const cleService = cle.includes("#") ? null : cle;

    /** Réaligne l'état visuel sur la sélection réelle. */
    function rafraichir() {
      const entier = cleService ? selection.has(cleService) : false;
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
      if (cleService) {
        // Un service entier se note d'un seul jeton, plus lisible.
        for (const c of cases) selection.delete(c.jeton);
        selection.add(cleService);
      } else {
        for (const c of cases) selection.add(c.jeton);
      }
      rafraichir();
      notifier();
    };
    const toutDecocher = () => {
      if (cleService) selection.delete(cleService);
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
    if (porteeEl) tete.appendChild(porteeEl);
    tete.appendChild(compteur);
    tete.appendChild(actions);
    ligne.appendChild(tete);
    ligne.appendChild(corps);
    lignes.push({ ligne, cases, corps, chevron });
    rafraichir();
  }

  const ORDRE_GROUPES = [
    "Coordination et mémoire",
    "Accès aux outils",
    "Compositions",
    "Accès aux fichiers",
    "Mes connecteurs",
    "Plateforme",
  ];
  for (const groupe of ORDRE_GROUPES) {
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
