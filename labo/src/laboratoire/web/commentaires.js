/* Commentaires — module autonome, sans dépendance, sans CDN. Voir docs/vision/commentaires-sur-tout.md.

   Il ajoute à n'importe quelle page un bouton « Commenter » : on pointe un élément ou on dessine un rectangle (sur la page ou sur une image), on écrit, et le commentaire
   s'accroche à sa cible. Les commentaires déjà faits s'affichent en repères numérotés ; un clic ouvre le fil (réponses, statut).

   Ce qu'il demande à la page :
   - un serveur qui parle le contrat de api_commentaires.py, à l'adresse window.COMMENTAIRES_CONFIG.endpoint (défaut : « api/commentaires », relative) ;
   - rien d'autre. La convention data-cible="type:identifiant" sur un élément le rend retrouvable de façon stable ; sans elle, le texte et le chemin CSS servent.

   Tout texte venant du serveur est mis avec textContent : jamais interprété comme du HTML. */
(function () {
  "use strict";
  if (window.__commentaires) return;
  window.__commentaires = true;

  const CFG = Object.assign({ endpoint: "api/commentaires", application: "laboratoire" }, window.COMMENTAIRES_CONFIG || {});
  const NATURES = [["remarque", "Remarque"], ["question", "Question"], ["anomalie", "Anomalie"], ["idee", "Idée"]];
  const STATUTS = [["ouvert", "ouvert"], ["pris_en_compte", "pris en compte"], ["traite", "traité"], ["ecarte", "écarté"]];
  const LIBELLE_STATUT = Object.fromEntries(STATUTS);

  const FEUILLE = `
  [data-cm] { font: 14px/1.45 var(--police, system-ui, sans-serif); color: var(--texte, #1c2330); box-sizing: border-box; }
  [data-cm] *, [data-cm] *::before, [data-cm] *::after { box-sizing: border-box; }
  .cm-racine { position: absolute; left: 0; top: 0; width: 0; height: 0; z-index: 2147483000; }
  .cm-bouton { position: fixed; right: 1rem; bottom: 1rem; z-index: 2147483001; display: flex; gap: .4rem; align-items: center; padding: .5rem .8rem; border-radius: 999px; border: 1px solid var(--bord, #d9dde3);
    background: var(--carte, #fff); box-shadow: 0 2px 10px #0003; cursor: pointer; }
  .cm-bouton[aria-pressed="true"] { background: var(--accent, #2354d6); color: #fff; border-color: transparent; }
  .cm-bouton b { background: var(--accent-fond, #e8eefc); color: var(--accent, #2354d6); border-radius: 999px; padding: 0 .45rem; font-weight: 600; }
  .cm-mode, .cm-mode * { cursor: crosshair !important; }
  .cm-mode [data-cm], .cm-mode [data-cm] * { cursor: auto !important; }
  .cm-survol { position: fixed; z-index: 2147483000; pointer-events: none; outline: 2px solid var(--accent, #2354d6); background: #2354d622; }
  .cm-trace { position: fixed; z-index: 2147483000; pointer-events: none; border: 2px dashed var(--accent, #2354d6); background: #2354d633; }
  .cm-zone { position: absolute; pointer-events: none; border: 2px dashed var(--accent, #2354d6); background: #2354d61a; }
  .cm-zone.actif, .cm-element.actif { outline: 3px solid var(--alerte, #a15c00); }
  .cm-element { position: absolute; pointer-events: none; }
  .cm-pin { position: absolute; width: 24px; height: 24px; margin: -12px 0 0 -12px; border-radius: 50% 50% 50% 0; transform: rotate(-45deg); border: 2px solid #fff; background: var(--accent, #2354d6); color: #fff;
    cursor: pointer; display: grid; place-items: center; font-size: 11px; font-weight: 700; padding: 0; box-shadow: 0 1px 6px #0006; }
  .cm-pin span { transform: rotate(45deg); }
  .cm-pin.traite, .cm-pin.ecarte { background: var(--doux, #5b6677); opacity: .75; }
  .cm-pin.actif { background: var(--alerte, #a15c00); }
  .cm-carte { position: fixed; z-index: 2147483002; background: var(--carte, #fff); border: 1px solid var(--bord, #d9dde3); border-radius: 8px; box-shadow: 0 6px 24px #0004; padding: .8rem; }
  .cm-formulaire { width: min(22rem, calc(100vw - 1.5rem)); }
  .cm-formulaire textarea, .cm-fil textarea { width: 100%; min-height: 5rem; resize: vertical; font: inherit; color: inherit; background: var(--fond, #f6f7f9); border: 1px solid var(--bord, #d9dde3); border-radius: 6px; padding: .4rem; }
  .cm-carte select, .cm-carte input { font: inherit; color: inherit; background: var(--fond, #f6f7f9); border: 1px solid var(--bord, #d9dde3); border-radius: 6px; padding: .25rem .4rem; }
  .cm-carte button { font: inherit; padding: .3rem .7rem; border-radius: 6px; border: 1px solid var(--bord, #d9dde3); background: var(--carte, #fff); color: inherit; cursor: pointer; }
  .cm-carte button.principal { background: var(--accent, #2354d6); color: #fff; border-color: transparent; }
  .cm-carte .doux { color: var(--doux, #5b6677); font-size: 12px; }
  .cm-rangee { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; margin-top: .5rem; }
  .cm-tiroir { top: 0; right: 0; bottom: 0; width: min(24rem, 100vw); border-radius: 0; border-width: 0 0 0 1px; overflow: auto; padding-bottom: 5rem; }
  .cm-tiroir h3 { margin: 0 0 .4rem; font-size: 15px; }
  .cm-onglets { display: flex; gap: .3rem; margin-bottom: .6rem; }
  .cm-onglets button[aria-pressed="true"] { background: var(--accent-fond, #e8eefc); border-color: var(--accent, #2354d6); }
  .cm-item { display: block; width: 100%; text-align: left; margin: 0 0 .4rem; padding: .45rem .55rem !important; }
  .cm-item .doux { display: block; }
  .cm-texte { white-space: pre-wrap; overflow-wrap: anywhere; margin: .3rem 0; }
  .cm-evt { border-top: 1px solid var(--bord, #d9dde3); padding-top: .4rem; margin-top: .4rem; }
  .cm-badge { display: inline-block; font-size: 11px; padding: 0 .4rem; border-radius: 999px; background: var(--accent-fond, #e8eefc); color: var(--accent, #2354d6); }
  .cm-toast { position: fixed; left: 50%; bottom: 4.5rem; transform: translateX(-50%); z-index: 2147483003; background: var(--texte, #1c2330); color: var(--carte, #fff); padding: .4rem .8rem; border-radius: 6px; }
  `;

  // ── petits outils ─────────────────────────────────────────────────────────

  function el(balise, props, ...enfants) {
    const e = document.createElement(balise);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (k === "value") e.value = v;
      else e.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of enfants.flat(Infinity)) if (c !== null && c !== undefined && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return e;
  }
  const marque = (e) => { e.setAttribute("data-cm", ""); return e; };
  const quand = (t) => new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  const page = () => location.hash.replace(/^#/, "").split("?")[0] || "/";
  const borne = (x) => Math.max(0, Math.min(1, x));

  async function appel(chemin, options = {}) {
    const r = await fetch(`${CFG.endpoint}${chemin}`, {
      method: options.corps ? "POST" : "GET", credentials: "same-origin",
      headers: options.corps ? { "Content-Type": "application/json" } : {}, body: options.corps ? JSON.stringify(options.corps) : undefined,
    });
    let d = null;
    try { d = await r.json(); } catch { /* corps vide */ }
    if (!r.ok) {
      const m = d && (d.erreur || d.detail);
      throw new Error(typeof m === "string" ? m : m ? JSON.stringify(m) : `erreur ${r.status}`);
    }
    return d;
  }

  function toast(texte) {
    const t = marque(el("div", { class: "cm-toast", role: "status" }, texte));
    document.body.append(t);
    setTimeout(() => t.remove(), 3500);
  }

  // ── cibles : retrouver un élément, décrire un élément ────────────────────

  const dansNotreInterface = (n) => !!(n && n.closest && n.closest("[data-cm]"));
  const echapper = (v) => v.replace(/["\\]/g, "\\$&");

  function idImage(img) {
    if (!img) return null;
    const d = img.getAttribute("data-cible");
    if (d && d.startsWith("image:")) return d.slice(6);
    try { return new URL(img.src, location.href).searchParams.get("chemin"); } catch { return null; }
  }

  function cheminCss(e) {
    const morceaux = [];
    for (let n = e; n && n.nodeType === 1 && n !== document.body && morceaux.length < 6; n = n.parentElement) {
      if (n.id) { morceaux.unshift(`#${CSS.escape(n.id)}`); break; }
      const frere = n.parentElement ? [...n.parentElement.children].filter((x) => x.tagName === n.tagName) : [n];
      morceaux.unshift(`${n.tagName.toLowerCase()}${frere.length > 1 ? `:nth-of-type(${frere.indexOf(n) + 1})` : ""}`);
    }
    return morceaux.join(" > ");
  }

  /** L'élément auquel un commentaire s'accroche : une image elle-même, sinon le plus proche élément qui porte data-cible, sinon l'élément pointé. */
  function ancre(e) {
    if (e.tagName === "IMG") return e;
    return e.closest("[data-cible]") || e;
  }

  function reperes(a) {
    const r = [];
    if (a.hasAttribute("data-cible")) r.push({ type: "cible", valeur: a.getAttribute("data-cible").slice(0, 300) });
    const t = (a.innerText || "").trim().replace(/\s+/g, " ").slice(0, 80);
    if (t) r.push({ type: "texte", valeur: t });
    const css = cheminCss(a).slice(0, 300);
    if (css) r.push({ type: "css", valeur: css });
    return r;
  }

  function donneeDe(a) {
    const e = a;
    const v = e.getAttribute("data-cible");
    if (v && v.includes(":")) { const i = v.indexOf(":"); return { type: v.slice(0, i).slice(0, 40), id: v.slice(i + 1).slice(0, 300) }; }
    const id = e.tagName === "IMG" ? idImage(e) : null;  // une image sans data-cible : son fichier est sa donnée
    return id ? { type: "image", id: id.slice(0, 300) } : null;
  }

  /** L'élément d'un commentaire, s'il est à l'écran. Un commentaire sur une donnée ne se rattache jamais par le texte ou le chemin : il ne doit pas tomber sur une autre image. */
  function retrouver(c) {
    const cible = c.cible || {};
    for (const rep of cible.elements || []) {
      if (rep.type === "cible") { const e = document.querySelector(`[data-cible="${echapper(rep.valeur)}"]`); if (e) return e; }
    }
    if (cible.donnee && cible.donnee.type === "image") return [...document.images].find((i) => idImage(i) === cible.donnee.id) || null;
    if (cible.donnee) return null;
    for (const rep of cible.elements || []) {
      if (rep.type === "css") { try { const e = document.querySelector(rep.valeur); if (e) return e; } catch { /* sélecteur invalide */ } }
    }
    return null;
  }

  function elementSous(x, y) {
    return document.elementsFromPoint(x, y).find((e) => !dansNotreInterface(e) && e !== document.documentElement && e !== document.body) || document.body;
  }

  // ── état ─────────────────────────────────────────────────────────────────

  let moi = { auteur: "", role: "", version: "" };
  let mode = false, liste = [], ouvertId = null, formulaire = null, tiroir = null, depart = null, trace = null, survol = null, onglet = "page";
  const racine = marque(el("div", { class: "cm-racine" }));
  const bouton = marque(el("button", { class: "cm-bouton", type: "button", "aria-pressed": "false", title: "Pointer un élément ou dessiner une zone, puis écrire", onclick: () => (tiroir ? fermerTiroir() : ouvrirListe()) }));

  function majBouton() {
    const n = liste.filter((c) => c.cible && c.cible.page === page()).length;
    bouton.setAttribute("aria-pressed", mode ? "true" : "false");
    bouton.replaceChildren(...["💬 ", mode ? "Cliquez ou dessinez… (Échap)" : "Commentaires", n && !mode ? el("b", {}, n) : null].filter((x) => x !== null));
  }

  async function actualiser() {
    try { liste = await appel(""); } catch { liste = []; }
    placer(); majBouton();
    if (tiroir && onglet !== "fil") dessinerTiroir();
  }

  // ── mode « commenter » ───────────────────────────────────────────────────

  function activer(on) {
    if (on && tiroir) fermerTiroir();  // pour pointer, il faut toute la page
    mode = on;
    document.documentElement.classList.toggle("cm-mode", on);
    if (!on) { retirerSurvol(); retirerTrace(); depart = null; }
    majBouton();
  }
  function retirerSurvol() { if (survol) { survol.remove(); survol = null; } }
  function retirerTrace() { if (trace) { trace.remove(); trace = null; } }
  function poserRect(noeud, r) { Object.assign(noeud.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` }); }

  function surPointeurBas(ev) {
    if (!mode || ev.button !== 0 || dansNotreInterface(ev.target)) return;
    ev.preventDefault(); ev.stopPropagation();
    depart = { x: ev.clientX, y: ev.clientY };
  }
  function surPointeurBouge(ev) {
    if (!mode || dansNotreInterface(ev.target) || formulaire) return;
    if (depart) {
      if (Math.hypot(ev.clientX - depart.x, ev.clientY - depart.y) < 6 && !trace) return;
      retirerSurvol();
      if (!trace) { trace = marque(el("div", { class: "cm-trace" })); document.body.append(trace); }
      poserRect(trace, { left: Math.min(depart.x, ev.clientX), top: Math.min(depart.y, ev.clientY), width: Math.abs(ev.clientX - depart.x), height: Math.abs(ev.clientY - depart.y) });
      return;
    }
    const e = elementSous(ev.clientX, ev.clientY);
    if (!survol) { survol = marque(el("div", { class: "cm-survol" })); document.body.append(survol); }
    poserRect(survol, e.getBoundingClientRect());
  }
  function surPointeurHaut(ev) {
    if (!mode || !depart) return;
    ev.preventDefault(); ev.stopPropagation();
    const d = depart; depart = null;
    const rect = { left: Math.min(d.x, ev.clientX), top: Math.min(d.y, ev.clientY), right: Math.max(d.x, ev.clientX), bottom: Math.max(d.y, ev.clientY) };
    const glisse = Math.hypot(ev.clientX - d.x, ev.clientY - d.y) >= 6;
    retirerTrace();
    const centre = glisse ? { x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 } : d;
    const e = elementSous(glisse ? d.x : centre.x, glisse ? d.y : centre.y);
    ouvrirFormulaire(e, glisse ? rect : null, { x: ev.clientX, y: ev.clientY });
  }
  function bloquerClic(ev) {
    if (mode && !dansNotreInterface(ev.target)) { ev.preventDefault(); ev.stopPropagation(); }
  }
  function surTouche(ev) {
    if (dansNotreInterface(ev.target)) { ev.stopPropagation(); if (ev.key === "Escape" && formulaire) { fermerFormulaire(); } return; }  // taper dans un champ ne déclenche pas les raccourcis de la page
    if (!mode) return;
    if (ev.key === "Escape") { ev.stopPropagation(); ev.preventDefault(); if (formulaire) fermerFormulaire(); else activer(false); return; }
    if (ev.key !== "Tab") { ev.stopPropagation(); ev.preventDefault(); }
  }

  // ── créer un commentaire ─────────────────────────────────────────────────

  function zoneRelative(rect, a) {
    let repere = "page", base;
    if (a.tagName === "IMG") { repere = "image"; base = a.getBoundingClientRect(); }
    else if (a !== document.body && a.id !== "contenu") { repere = "element"; base = a.getBoundingClientRect(); }
    else { base = { left: -scrollX, top: -scrollY, width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }; }
    if (!base.width || !base.height) return null;
    const x0 = borne((rect.left - base.left) / base.width), y0 = borne((rect.top - base.top) / base.height);
    const x1 = borne((rect.right - base.left) / base.width), y1 = borne((rect.bottom - base.top) / base.height);
    if (x1 - x0 < 0.005 || y1 - y0 < 0.005) return null;
    const arrondi = (v) => Math.round(v * 10000) / 10000;
    return { repere, x: arrondi(x0), y: arrondi(y0), l: arrondi(x1 - x0), h: arrondi(y1 - y0) };
  }

  function ouvrirFormulaire(pointe, rect, point) {
    fermerFormulaire();
    const e = ancre(pointe);
    const zone = rect ? zoneRelative(rect, e) : null;
    const cible = { application: CFG.application, page: page().slice(0, 300), version: (moi.version || "").slice(0, 40), elements: e === document.body ? [] : reperes(e), fenetre: [innerWidth, innerHeight] };
    if (zone) cible.zone = zone;
    const donnee = e === document.body ? null : donneeDe(e);
    if (donnee) cible.donnee = donnee;
    const decrit = donnee ? `${donnee.type} ${donnee.id}` : (e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 60) || e.tagName.toLowerCase();
    const nature = el("select", { "aria-label": "Nature du commentaire" }, ...NATURES.map(([v, t]) => el("option", { value: v }, t)));
    const texte = el("textarea", { "aria-label": "Votre commentaire", placeholder: "Qu'est-ce qui vous frappe ? Une question, une anomalie, une idée…", maxlength: 4000 });
    const envoyer = el("button", { class: "principal", type: "submit" }, "Envoyer");
    const f = marque(el("form", { class: "cm-carte cm-formulaire", onsubmit: async (ev) => {
      ev.preventDefault();
      if (!texte.value.trim()) { texte.focus(); return; }
      envoyer.disabled = true;
      try {
        const r = await appel("", { corps: { texte: texte.value, nature: nature.value, cible } });
        fermerFormulaire(); activer(false); toast("Commentaire envoyé."); await actualiser(); ouvrirFil(r.id);
      } catch (x) { envoyer.disabled = false; toast(x.message); }
    } },
      el("div", { class: "doux" }, `${zone ? "Zone" : "Cible"} : `, decrit),
      el("div", { class: "cm-rangee" }, nature), el("div", { class: "cm-rangee" }, texte),
      el("div", { class: "cm-rangee" }, envoyer, el("button", { type: "button", onclick: fermerFormulaire }, "Annuler"))));
    document.body.append(f);
    const w = f.offsetWidth, hh = f.offsetHeight;
    f.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, point.x + 12))}px`;
    f.style.top = `${Math.max(8, Math.min(innerHeight - hh - 8, point.y + 12))}px`;
    formulaire = f; texte.focus();
  }
  function fermerFormulaire() { if (formulaire) { formulaire.remove(); formulaire = null; } }

  // ── repères sur la page ──────────────────────────────────────────────────

  const placees = new Set();
  function placer() {
    for (const n of placees) n.remove();
    placees.clear();
    const ici = liste.filter((c) => c.cible && c.cible.page === page());
    let sansCible = 0, numero = 0;  // le numéro compte les repères dessinés
    const doc = { w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight };
    for (const c of ici) {
      const e = retrouver(c);
      const zone = c.cible.zone;
      let x, y;
      if (e) {
        const r = e.getBoundingClientRect();
        const base = { left: r.left + scrollX, top: r.top + scrollY, width: r.width, height: r.height };
        if (zone && zone.repere !== "page") {
          const z = el("div", { class: `cm-zone${c.id === ouvertId ? " actif" : ""}`, "data-cm-id": c.id });
          Object.assign(z.style, { left: `${base.left + zone.x * base.width}px`, top: `${base.top + zone.y * base.height}px`, width: `${zone.l * base.width}px`, height: `${zone.h * base.height}px` });
          marque(z); racine.append(z); placees.add(z);
          x = base.left + zone.x * base.width; y = base.top + zone.y * base.height;
        } else { x = base.left + base.width; y = base.top; }
      } else if (zone && zone.repere === "page") {
        const z = el("div", { class: `cm-zone${c.id === ouvertId ? " actif" : ""}` });
        Object.assign(z.style, { left: `${zone.x * doc.w}px`, top: `${zone.y * doc.h}px`, width: `${zone.l * doc.w}px`, height: `${zone.h * doc.h}px` });
        marque(z); racine.append(z); placees.add(z);
        x = zone.x * doc.w; y = zone.y * doc.h;
      } else if (!(c.cible.elements || []).length && !c.cible.donnee) {
        x = doc.w - 20; y = 90 + sansCible * 28; sansCible += 1;  // commentaire sur la page entière
      } else continue;  // son élément n'est pas affiché (autre image, autre état de la page) : il reste dans la liste
      numero += 1;
      const pin = marque(el("button", { class: `cm-pin ${c.statut}${c.id === ouvertId ? " actif" : ""}`, type: "button", title: `${c.auteur} : ${c.texte.slice(0, 80)}`, "aria-label": `Commentaire ${c.id} de ${c.auteur}`, onclick: () => ouvrirFil(c.id) }, el("span", {}, String(numero))));
      Object.assign(pin.style, { left: `${x}px`, top: `${y}px` });
      racine.append(pin); placees.add(pin);
    }
  }

  // ── tiroir : liste et fil ────────────────────────────────────────────────

  function fermerTiroir() { if (tiroir) { tiroir.remove(); tiroir = null; } ouvertId = null; placer(); }
  function creerTiroir() {
    if (!tiroir) { tiroir = marque(el("aside", { class: "cm-carte cm-tiroir", "aria-label": "Commentaires" })); document.body.append(tiroir); }
    return tiroir;
  }

  function ouvrirListe() { ouvertId = null; onglet = "page"; dessinerTiroir(); placer(); }

  function dessinerTiroir() {
    const t = creerTiroir();
    const ici = liste.filter((c) => c.cible && c.cible.page === page());
    const cles = { page: ici, tous: liste, ouverts: liste.filter((c) => c.statut === "ouvert" || c.statut === "pris_en_compte") };
    const onglets = el("div", { class: "cm-onglets" }, ...[["page", "Cette page"], ["ouverts", "À traiter"], ["tous", "Tous"]].map(([k, nom]) =>
      el("button", { type: "button", "aria-pressed": onglet === k ? "true" : "false", onclick: () => { onglet = k; dessinerTiroir(); } }, `${nom} (${cles[k].length})`)));
    const items = cles[onglet].map((c) => el("button", { type: "button", class: "cm-item", onclick: () => aller(c) },
      el("span", { class: "doux" }, `${c.auteur} · ${quand(c.cree_le)} · `, el("span", { class: "cm-badge" }, LIBELLE_STATUT[c.statut] || c.statut), c.reponses ? ` · ${c.reponses} réponse${c.reponses > 1 ? "s" : ""}` : ""),
      el("span", { class: "cm-texte" }, c.texte.length > 140 ? `${c.texte.slice(0, 140)}…` : c.texte)));
    t.replaceChildren(
      el("div", { class: "cm-rangee", style: "justify-content:space-between;margin:0 0 .5rem" }, el("h3", {}, "Commentaires"), el("button", { type: "button", onclick: fermerTiroir, "aria-label": "Fermer" }, "✕")),
      el("div", { class: "cm-rangee", style: "margin:0 0 .6rem" }, el("button", { class: "principal", type: "button", onclick: () => activer(true) }, "＋ Nouveau commentaire"),
        moi.role === "admin" ? el("a", { href: `${CFG.endpoint}/export?statut=tous`, target: "_blank", rel: "noopener" }, "Exporter") : null),
      onglets, ...(items.length ? items : [el("p", { class: "doux" }, "Aucun commentaire ici.")]),
      el("p", { class: "doux" }, `Vous êtes ${moi.auteur || "—"}${moi.role ? ` (${moi.role})` : ""}.`));
  }

  function aller(c) {
    if (c.cible.page === page()) { ouvrirFil(c.id); return; }
    try { sessionStorage.setItem("cm_ouvrir", String(c.id)); } catch { /* pas de stockage : on arrive sur la page sans ouvrir le fil */ }
    const p = c.cible.page || "";
    if (p.startsWith("/")) location.hash = `#${p}`; else if (p) location.href = p;
  }

  async function ouvrirFil(id) {
    ouvertId = id; onglet = "fil";
    const t = creerTiroir();
    let c;
    try { c = await appel(`/${id}`); } catch (x) { toast(x.message); return; }
    placer();
    const rep = el("textarea", { "aria-label": "Votre réponse", placeholder: "Répondre…", maxlength: 4000 });
    const evts = c.evenements.map((e) => el("div", { class: "cm-evt" },
      el("div", { class: "doux" }, `${e.auteur} (${e.role}) · ${quand(e.cree_le)}`),
      e.type === "statut" ? el("div", {}, "Statut : ", el("span", { class: "cm-badge" }, LIBELLE_STATUT[e.statut] || e.statut), e.lien ? ` — ${e.lien}` : "") : el("div", { class: "cm-texte" }, e.texte)));
    const zone = c.cible.zone ? `, zone ${c.cible.zone.repere}` : "";
    const lignes = [
      el("div", { class: "cm-rangee", style: "justify-content:space-between;margin:0 0 .5rem" }, el("button", { type: "button", onclick: () => { ouvertId = null; onglet = "page"; dessinerTiroir(); placer(); } }, "← Liste"), el("button", { type: "button", onclick: fermerTiroir, "aria-label": "Fermer" }, "✕")),
      el("div", { class: "cm-fil" },
        el("div", { class: "doux" }, `${c.auteur} (${c.role}) · ${quand(c.cree_le)} · ${c.nature}${zone} · `, el("span", { class: "cm-badge" }, LIBELLE_STATUT[c.statut] || c.statut)),
        el("div", { class: "cm-texte" }, c.texte),
        el("div", { class: "doux" }, `Page ${c.cible.page || "—"}${c.cible.donnee ? ` · ${c.cible.donnee.type} ${c.cible.donnee.id}` : ""}${c.cible.version ? ` · version ${c.cible.version}` : ""}`),
        ...evts,
        el("div", { class: "cm-rangee" }, rep),
        el("div", { class: "cm-rangee" }, el("button", { class: "principal", type: "button", onclick: async () => {
          if (!rep.value.trim()) { rep.focus(); return; }
          try { await appel(`/${id}/reponses`, { corps: { texte: rep.value } }); await actualiser(); ouvrirFil(id); } catch (x) { toast(x.message); }
        } }, "Répondre"))),
    ];
    if (moi.role === "admin") {
      const statut = el("select", { "aria-label": "Nouveau statut" }, ...STATUTS.map(([v, n]) => el("option", { value: v, selected: v === c.statut }, n)));
      const lien = el("input", { type: "text", placeholder: "lien de la correction (facultatif)", maxlength: 300, "aria-label": "Lien de la correction", style: "flex:1;min-width:8rem" });
      lignes.push(el("div", { class: "cm-evt" }, el("div", { class: "doux" }, "Statut (réservé à la personne qui administre)"),
        el("div", { class: "cm-rangee" }, statut, lien, el("button", { type: "button", onclick: async () => {
          try { await appel(`/${id}/statut`, { corps: { statut: statut.value, lien: lien.value } }); await actualiser(); ouvrirFil(id); } catch (x) { toast(x.message); }
        } }, "Changer"))));
    }
    t.replaceChildren(...lignes);
    const e = retrouver(c);
    if (e && e.scrollIntoView) e.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  // ── démarrage ────────────────────────────────────────────────────────────

  function demarrer() {
    const style = marque(el("style", {}, FEUILLE));
    document.head.append(style);
    document.body.append(racine, bouton);
    window.addEventListener("pointerdown", surPointeurBas, true);
    window.addEventListener("pointermove", surPointeurBouge, true);
    window.addEventListener("pointerup", surPointeurHaut, true);
    window.addEventListener("click", bloquerClic, true);
    window.addEventListener("keydown", surTouche, true);
    let minuteur = 0;
    const replacer = () => { clearTimeout(minuteur); minuteur = setTimeout(placer, 250); };
    window.addEventListener("resize", replacer);
    window.addEventListener("load", replacer, true);  // une image qui finit de charger déplace ce qui la suit
    new MutationObserver((m) => { if (m.some((x) => !dansNotreInterface(x.target))) replacer(); }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src", "data-cible"] });
    window.addEventListener("hashchange", () => { ouvertId = null; if (tiroir && onglet === "fil") { onglet = "page"; dessinerTiroir(); } activer(false); fermerFormulaire(); placer(); majBouton(); apresNavigation(); });
    appel("/moi").then((m) => { moi = m; majBouton(); }).catch(() => {});
    actualiser().then(apresNavigation);
    setInterval(() => { if (!document.hidden) actualiser(); }, 20000);
  }
  function apresNavigation() {
    let id = null;
    try { id = sessionStorage.getItem("cm_ouvrir"); sessionStorage.removeItem("cm_ouvrir"); } catch { /* pas de stockage */ }
    if (id) setTimeout(() => ouvrirFil(Number(id)), 400);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer); else demarrer();
})();
