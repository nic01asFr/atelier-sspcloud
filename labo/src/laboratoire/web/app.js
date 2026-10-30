/* Laboratoire d'essais — page unique, sans dépendance, sans CDN.
   Le DOM est construit avec h() et textContent : aucune donnée du serveur n'est jamais interprétée comme du HTML. */
"use strict";

// ── outils ────────────────────────────────────────────────────────────────

function h(balise, props, ...enfants) {
  const el = document.createElement(balise);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const e of enfants.flat(Infinity)) {
    if (e === null || e === undefined || e === false) continue;
    el.append(e instanceof Node ? e : document.createTextNode(String(e)));
  }
  return el;
}
const NS = "http://www.w3.org/2000/svg";
function s(balise, props, ...enfants) {
  const el = document.createElementNS(NS, balise);
  for (const [k, v] of Object.entries(props || {})) el.setAttribute(k, String(v));
  for (const e of enfants.flat(Infinity)) if (e !== null && e !== undefined) el.append(e instanceof Node ? e : document.createTextNode(String(e)));
  return el;
}
const nb = (x, d = 3) => (x === null || x === undefined || Number.isNaN(x) ? "—" : Number(x).toFixed(d).replace(".", ","));
const pct = (x) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(1).replace(".", ",")} %`);
function duree(debut, fin) {
  if (!debut) return "—";
  const t = Math.max(0, Math.round((fin || Date.now() / 1000) - debut));
  return t < 60 ? `${t} s` : t < 3600 ? `${Math.floor(t / 60)} min ${t % 60} s` : `${Math.floor(t / 3600)} h ${Math.floor((t % 3600) / 60)} min`;
}
const quand = (t) => (t ? new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const LIBELLES = { en_file: "en file", en_cours: "en cours", termine: "terminé", echoue: "échoué", arrete: "arrêté", interrompu: "interrompu" };
const badge = (etat) => h("span", { class: `badge ${etat}` }, LIBELLES[etat] || etat);

function avis(texte, erreur = false) {
  const zone = document.getElementById("avis");
  const el = h("div", { class: erreur ? "erreur" : "" }, texte);
  zone.append(el);
  setTimeout(() => el.remove(), erreur ? 9000 : 4000);
}

async function api(chemin, options = {}) {
  const r = await fetch(chemin.replace(/^\//, ""), {  // relatif : la page peut vivre derrière un préfixe (relais de l'Atelier)
    headers: options.corps ? { "Content-Type": "application/json" } : {},
    method: options.methode || (options.corps ? "POST" : "GET"),
    body: options.corps ? JSON.stringify(options.corps) : undefined,
    credentials: "same-origin",
  });
  let donnees = null;
  try { donnees = await r.json(); } catch { /* corps vide */ }
  if (!r.ok) {
    const msg = donnees && (donnees.erreur || donnees.detail) ? (typeof (donnees.erreur || donnees.detail) === "string" ? (donnees.erreur || donnees.detail) : JSON.stringify(donnees.erreur || donnees.detail)) : `erreur ${r.status}`;
    const e = new Error(msg); e.statut = r.status; throw e;
  }
  return donnees;
}

// ── graphiques (SVG à la main) ────────────────────────────────────────────

function courbes(series, { largeur = 520, hauteur = 190, titre = "" } = {}) {
  const m = { g: 44, d: 10, h: 10, b: 24 };
  const pts = series.flatMap((x) => x.points);
  if (!pts.length) return h("p", { class: "doux" }, "Pas encore de mesure par époque.");
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) === x0 ? x0 + 1 : Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys); if (y1 === y0) { y1 = y0 + 1; }
  const X = (x) => m.g + ((x - x0) / (x1 - x0)) * (largeur - m.g - m.d);
  const Y = (y) => hauteur - m.b - ((y - y0) / (y1 - y0)) * (hauteur - m.b - m.h);
  const svg = s("svg", { viewBox: `0 0 ${largeur} ${hauteur}`, width: "100%", role: "img", "aria-label": titre });
  svg.append(s("line", { class: "axe", x1: m.g, x2: largeur - m.d, y1: hauteur - m.b, y2: hauteur - m.b }), s("line", { class: "axe", x1: m.g, x2: m.g, y1: m.h, y2: hauteur - m.b }));
  for (const y of [y0, (y0 + y1) / 2, y1]) svg.append(s("text", { x: m.g - 6, y: Y(y) + 4, "text-anchor": "end" }, nb(y, 2)));
  for (const x of [x0, x1]) svg.append(s("text", { x: X(x), y: hauteur - 6, "text-anchor": "middle" }, String(Math.round(x))));
  series.forEach((serie, i) => {
    const couleur = ["var(--course)", "var(--ok)", "var(--alerte)", "var(--mal)"][i % 4];
    svg.append(s("polyline", { class: "serie", stroke: couleur, points: serie.points.map((p) => `${X(p[0])},${Y(p[1])}`).join(" ") }));
    svg.append(s("text", { x: largeur - m.d - 4, y: m.h + 12 + i * 14, "text-anchor": "end", style: `fill:${couleur}` }, serie.nom));
  });
  return svg;
}

function barreValeur(valeur, trivial) {
  const piste = h("div", { class: "piste" }, h("b", { style: `width:${Math.max(0, Math.min(1, valeur || 0)) * 100}%` }));
  if (trivial !== null && trivial !== undefined) piste.append(h("u", { style: `left:${trivial * 100}%`, title: `réponse triviale : ${nb(trivial, 2)}` }));
  return h("div", { class: "barre-valeur" }, piste, h("span", {}, nb(valeur, 2)));
}

// ── état du pod (en-tête) ─────────────────────────────────────────────────

async function majPod() {
  const zone = document.getElementById("pod");
  try {
    const p = await api("/api/pod");
    const items = [];
    if (p.gpu) {
      const util = p.gpu.utilisation_pct;
      items.push(h("span", { class: `pastille ${util > 5 ? "vert" : "orange"}`, title: p.gpu.nom }, h("i"), `GPU ${util} % · ${Math.round(p.gpu.memoire_utilisee_mo / 100) / 10}/${Math.round(p.gpu.memoire_totale_mo / 100) / 10} Go`));
    } else if (p.maitre) {
      // Laboratoire sur le pod CPU : l'entraînement se fait sur un pod GPU qui s'éteint quand il n'a rien à faire.
      const attente = p.essais_en_file > 0 && !p.travailleur.connecte;
      items.push(h("span", { class: `pastille ${p.travailleur.connecte ? "vert" : attente ? "orange" : ""}`,
        title: "Le GPU n'est allumé que pour entraîner : il s'éteint seul quand il n'y a plus d'essai. La validation et les commentaires n'en ont pas besoin." },
        h("i"), p.travailleur.connecte ? "GPU connecté" : attente ? `GPU éteint · ${p.essais_en_file} essai(s) attendent` : "GPU éteint (au repos)"));
    } else items.push(h("span", { class: "pastille" }, h("i"), "pas de GPU visible"));
    items.push(h("span", { class: `pastille ${p.essais_en_cours ? "vert" : ""}` }, h("i"), `${p.essais_en_cours} en cours · ${p.essais_en_file} en file`));
    items.push(h("span", { class: `pastille ${p.disque.libre_go < 2 ? "rouge" : ""}` }, h("i"), `disque libre ${nb(p.disque.libre_go, 1)} Go`));
    if (p.battement_actif) items.push(h("span", { class: "pastille", title: "Le GPU travaille un instant toutes les deux minutes tant qu'un essai tourne, pour que le serveur ne coupe pas le pod (contournement de D-81)." }, h("i"), "battement"));
    zone.replaceChildren(...items);
  } catch (e) { zone.replaceChildren(h("span", { class: "pastille rouge" }, h("i"), "service injoignable")); }
}

// ── page Essais ───────────────────────────────────────────────────────────

const selection = new Set();

async function pageEssais(zone) {
  let filtre = "";
  const corps = h("tbody");
  const boutonComparer = h("button", { disabled: true, onclick: () => { location.hash = `#/comparer?ids=${[...selection].join(",")}`; } }, "Comparer");
  const choix = h("select", { "aria-label": "Filtrer par état", onchange: (e) => { filtre = e.target.value; rafraichir(); } },
    h("option", { value: "" }, "Tous les états"), ...Object.entries(LIBELLES).map(([k, v]) => h("option", { value: k }, v)));
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Essais"), h("p", { class: "doux" }, "Le rappel moyen compte chaque classe pour autant, quel que soit son effectif ; le trait gris est la réponse triviale. L'exactitude seule est trompeuse.")),
      h("div", { class: "actions" }, choix, boutonComparer, h("a", { class: "bouton principal", href: "#/lancer" }, "Lancer un essai"))),
    h("div", { class: "carte defile" }, h("table", {}, h("thead", {}, h("tr", {},
      h("th", {}, ""), h("th", {}, "Essai"), h("th", {}, "État"), h("th", {}, "Jeu"), h("th", {}, "Modèle"), h("th", { class: "num" }, "Résolution"), h("th", { class: "num" }, "Graine"),
      h("th", {}, "Rappel moyen (validation)"), h("th", { class: "num" }, "Exactitude"), h("th", {}, "Test"), h("th", { class: "num" }, "Durée"), h("th", {}, "Créé"))), corps)),
  );
  async function rafraichir() {
    const essais = await api(`/api/essais${filtre ? `?etat=${filtre}` : ""}`);
    boutonComparer.disabled = selection.size < 2 || selection.size > 6;
    if (!essais.length) { corps.replaceChildren(h("tr", {}, h("td", { colspan: 12, class: "vide" }, "Aucun essai pour l'instant. ", h("a", { href: "#/lancer" }, "Lancer le premier.")))); return; }
    corps.replaceChildren(...essais.map((e) => h("tr", { "data-cible": `essai:${e.id}` },
      h("td", {}, h("input", { type: "checkbox", "aria-label": `Sélectionner ${e.id}`, checked: selection.has(e.id), onchange: (ev) => { ev.target.checked ? selection.add(e.id) : selection.delete(e.id); boutonComparer.disabled = selection.size < 2 || selection.size > 6; } })),
      h("td", {}, h("a", { href: `#/essais/${e.id}`, class: "mono" }, e.id)), h("td", {}, badge(e.etat)), h("td", { class: "mono" }, e.jeu), h("td", {}, `${e.famille} · ${e.modele}`),
      h("td", { class: "num" }, e.imgsz), h("td", { class: "num" }, e.graine),
      h("td", {}, e.rappel_moyen_val === null ? "—" : barreValeur(e.rappel_moyen_val, null)), h("td", { class: "num doux" }, e.exactitude_val === null ? "—" : nb(e.exactitude_val, 2)),
      h("td", {}, e.rappel_moyen_test !== null ? nb(e.rappel_moyen_test, 2) : e.etat === "termine" ? h("span", { class: "doux", title: "Scellé : il s'ouvre depuis la page de l'essai, et l'ouverture est comptée." }, "🔒 scellé") : "—"),
      h("td", { class: "num" }, duree(e.debut, e.fin)), h("td", { class: "doux" }, quand(e.cree_le)))));
  }
  await rafraichir();
  return setInterval(() => { if (document.hidden) return; rafraichir().catch(() => {}); }, 4000);
}

// ── page Un essai ─────────────────────────────────────────────────────────

function tableauParClasse(rapport, triviales) {
  const triv = triviales && triviales.majoritaire;
  return h("div", { class: "defile" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Classe"), h("th", { class: "num" }, "Images"), h("th", {}, "Rappel"), h("th", { class: "num" }, "Précision"), h("th", { class: "num" }, "F1"), h("th", {}, "Fiabilité"))),
    h("tbody", {}, ...rapport.classes.map((c) => { const p = rapport.par_classe[c]; return h("tr", {},
      h("td", {}, c), h("td", { class: "num" }, p.n), h("td", {}, p.rappel === null ? "—" : barreValeur(p.rappel, null)), h("td", { class: "num" }, nb(p.precision, 2)), h("td", { class: "num" }, nb(p.f1, 2)),
      h("td", {}, p.n === 0 ? "—" : p.fiable ? h("span", { class: "badge fiable" }, "fiable") : h("span", { class: "badge nonfiable", title: "Moins de 20 images : un seul exemple de plus déplace ce chiffre de plusieurs points." }, `non fiable (${p.n})`))); }))));
}

function matriceConfusion(rapport) {
  const max = Math.max(1, ...rapport.confusion.flat());
  return h("div", { class: "defile" }, h("table", { class: "confusion" }, h("thead", {}, h("tr", {}, h("th", {}, "réel ↓ / prédit →"), ...rapport.classes.map((c) => h("th", {}, c)))),
    h("tbody", {}, ...rapport.classes.map((c, i) => h("tr", {}, h("th", {}, c), ...rapport.confusion[i].map((v, j) => h("td", { class: i === j ? "diag" : "", style: `background:color-mix(in srgb, ${i === j ? "var(--ok)" : "var(--mal)"} ${Math.round((v / max) * 55)}%, transparent)` }, v)))))));
}

function tuile(etiquette, valeur, detail) {
  return h("div", { class: "tuile" }, h("div", { class: "etiquette" }, etiquette), h("div", { class: "valeur" }, valeur), detail ? h("div", { class: "detail" }, detail) : null);
}

async function pageEssai(zone, id) {
  const d = await api(`/api/essais/${id}`);
  const e = d.essai, r = d.resultats;
  const actif = e.etat === "en_cours" || e.etat === "en_file";
  const boutons = [h("a", { class: "bouton", href: "#/essais" }, "← Essais"), h("a", { class: "bouton", href: `#/lancer?depuis=${id}` }, "Rejouer avec…")];
  if (actif) boutons.push(h("button", { class: "danger", onclick: async () => { if (!confirm(`Arrêter ${id} ?`)) return; try { await api(`/api/essais/${id}/arreter`, { methode: "POST" }); avis(`${id} arrêté.`); render(); } catch (x) { avis(x.message, true); } } }, "Arrêter"));
  const zoneTest = h("div", {});
  const entete = h("div", { class: "entete", "data-cible": `essai:${id}` }, h("div", {}, h("h1", {}, `Essai ${id} `, badge(e.etat)), h("p", { class: "doux" }, `${e.famille} · ${e.modele} · résolution ${e.imgsz} · jeu `, h("span", { class: "mono" }, e.jeu), ` · graine ${e.graine} · ${duree(e.debut, e.fin)}`)), h("div", { class: "actions" }, boutons));
  const contenu = [entete];
  if (e.erreur && (e.etat === "echoue" || e.etat === "interrompu" || e.etat === "arrete")) contenu.push(h("div", { class: "carte", style: "border-color:var(--mal)" }, h("h2", {}, "Pourquoi"), h("pre", { class: "journal", style: "max-height:10rem" }, e.erreur)));
  if (r) {
    const rap = r.rapport, ic = r.intervalle_rappel_moyen, gain = r.gain_sur_trivial.majoritaire;
    contenu.push(h("div", { class: "tuiles", "data-cible": `essai:${id}/indicateurs` },
      tuile("Rappel moyen (validation)", nb(rap.rappel_moyen, 3), ic && ic.bas !== null ? `intervalle à 95 % : ${nb(ic.bas, 2)} – ${nb(ic.haut, 2)} (${ic.groupes} collections)` : "intervalle impossible : moins de deux collections"),
      tuile("Gain sur la réponse triviale", gain === null ? "—" : `${gain >= 0 ? "+" : ""}${nb(gain, 3)}`, `toujours « ${r.triviales.majoritaire.classe} » : ${nb(r.triviales.majoritaire.rappel_moyen, 3)} de rappel moyen`),
      tuile("Exactitude", nb(rap.exactitude, 3), `réponse triviale : ${nb(r.triviales.majoritaire.exactitude, 3)} — flatteuse si une classe domine`),
      tuile("Classes non fiables", rap.classes_non_fiables.length ? rap.classes_non_fiables.join(", ") : "aucune", "moins de 20 images en validation")));
    contenu.push(h("div", { class: "grille" },
      h("div", { class: "carte", "data-cible": `essai:${id}/par-classe` }, h("h2", {}, "Par classe (validation)"), tableauParClasse(rap, r.triviales)),
      h("div", { class: "carte", "data-cible": `essai:${id}/confusion` }, h("h2", {}, "Matrice de confusion (validation)"), matriceConfusion(rap))));
  } else if (e.etat === "termine") contenu.push(h("p", { class: "doux" }, "Pas de résultats lisibles."));
  // test scellé
  if (e.etat === "termine" && d.test.scelle) {
    const rendre = (t) => {
      zoneTest.replaceChildren(h("div", { class: "carte" }, h("h2", {}, `Test ouvert (${t.consultations} consultation${t.consultations > 1 ? "s" : ""})`),
        h("p", { class: "doux" }, "Le test confirme, il ne sert pas à choisir. Chaque ouverture est comptée."),
        h("div", { class: "tuiles" }, tuile("Rappel moyen (test)", nb(t.rapport.rappel_moyen, 3), `réponse triviale : ${nb(t.triviales.majoritaire.rappel_moyen, 3)}`), tuile("Exactitude (test)", nb(t.rapport.exactitude, 3))),
        h("div", { class: "grille" }, tableauParClasse(t.rapport, t.triviales), matriceConfusion(t.rapport))));
    };
    if (d.test.consultations > 0 && e.rappel_moyen_test !== null) {
      zoneTest.append(h("div", { class: "carte" }, h("h2", {}, `Test déjà ouvert ${d.test.consultations} fois`), h("button", { onclick: ouvrir }, "Relire le test")));
    } else {
      zoneTest.append(h("div", { class: "carte" }, h("h2", {}, "🔒 Test scellé"), h("p", { class: "doux" }, "Le jeu de test ne sert pas à choisir un réglage ou un modèle : on le regarde une fois, pour confirmer. L'ouverture est comptée."), h("button", { onclick: ouvrir }, "Ouvrir le test")));
    }
    async function ouvrir() {
      if (!confirm("Ouvrir le test ? Il ne sert pas à choisir, et cette ouverture sera comptée.")) return;
      try { rendre(await api(`/api/essais/${id}/ouvrir-test`, { corps: { confirmer: true } })); } catch (x) { avis(x.message, true); }
    }
    contenu.push(zoneTest);
  }
  if (d.metriques.length) {
    const colonnes = Object.keys(d.metriques[0]).filter((k) => k !== "epoque" && k !== "images");
    contenu.push(h("div", { class: "carte" }, h("h2", {}, "Courbes par époque"), courbes(colonnes.map((c) => ({ nom: c, points: d.metriques.filter((m) => typeof m[c] === "number").map((m) => [m.epoque, m[c]]) })), { titre: "Courbes par époque" })));
  }
  if (d.erreurs.length) {
    const classes = [...new Set(d.erreurs.map((x) => x.vrai))].sort();
    const corps = h("tbody"); let f = "";
    const tracer = () => corps.replaceChildren(...d.erreurs.filter((x) => !f || x.vrai === f).slice(0, 200).map((x) => h("tr", {}, h("td", { class: "mono" }, x.fichier), h("td", {}, x.vrai), h("td", {}, x.predit), h("td", { class: "mono" }, x.groupe))));
    tracer();
    contenu.push(h("div", { class: "carte" }, h("div", { class: "entete", style: "margin-bottom:.4rem" }, h("h2", {}, `Images de validation mal classées (${d.erreurs.length})`),
      h("select", { "aria-label": "Filtrer par classe vraie", onchange: (ev) => { f = ev.target.value; tracer(); } }, h("option", { value: "" }, "Toutes les classes"), ...classes.map((c) => h("option", { value: c }, `vraie : ${c}`)))),
      h("div", { class: "defile" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Fichier"), h("th", {}, "Vraie"), h("th", {}, "Prédite"), h("th", {}, "Collection"))), corps))));
  }
  contenu.push(h("div", { class: "carte", "data-cible": `essai:${id}/configuration` }, h("h2", {}, "Configuration"), h("dl", { class: "cle-valeur" }, ...Object.entries(aplatir(e.config)).flatMap(([k, v]) => [h("dt", {}, k), h("dd", { class: "mono" }, String(v))]))));
  const pre = h("pre", { class: "journal", "aria-label": "Journal de l'essai" });
  contenu.push(h("div", { class: "carte" }, h("h2", {}, "Journal"), pre));
  zone.replaceChildren(...contenu);
  let curseur = 0, minuteur;
  async function suivre() {
    try {
      const j = await api(`/api/essais/${id}/journal?depuis=${curseur}`);
      if (j.texte) { const bas = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30; pre.append(document.createTextNode(j.texte)); curseur = j.suivant; if (bas) pre.scrollTop = pre.scrollHeight; }
      const actuel = (await api(`/api/essais/${id}`)).essai.etat;
      if (actuel !== e.etat) { render(); return; }
    } catch { /* on réessaie */ }
    if (actif) minuteur = setTimeout(suivre, 2000);
  }
  await suivre();
  return () => clearTimeout(minuteur);
}
function aplatir(o, prefixe = "") {
  return Object.entries(o).reduce((a, [k, v]) => (v && typeof v === "object" && !Array.isArray(v) ? { ...a, ...aplatir(v, `${prefixe}${k}.`) } : { ...a, [`${prefixe}${k}`]: typeof v === "string" ? v : JSON.stringify(v) }), {});
}

// ── page Comparer ─────────────────────────────────────────────────────────

async function pageComparer(zone, requete) {
  const ids = (new URLSearchParams(requete).get("ids") || "").split(",").filter(Boolean);
  const lot = await api(`/api/comparer?ids=${ids.join(",")}`);
  const classes = [...new Set(lot.flatMap((x) => (x.resultats ? x.resultats.rapport.classes : [])))];
  const plats = lot.map((x) => aplatir(x.essai.config));
  const cles = [...new Set(plats.flatMap((p) => Object.keys(p)))].filter((k) => k !== "note");
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Comparer"), h("p", { class: "doux" }, "Les différences de configuration sont surlignées. Une différence de rappel n'est réelle que si elle dépasse le bruit : voir les intervalles sur la page de chaque essai.")), h("a", { class: "bouton", href: "#/essais" }, "← Essais")),
    h("div", { class: "carte defile" }, h("h2", {}, "Rappel par classe (validation)"), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), ...lot.map((x) => h("th", {}, h("a", { href: `#/essais/${x.essai.id}`, class: "mono" }, x.essai.id))))),
      h("tbody", {}, h("tr", {}, h("th", {}, "Rappel moyen"), ...lot.map((x) => h("td", {}, x.resultats ? barreValeur(x.resultats.rapport.rappel_moyen, x.resultats.triviales.majoritaire.rappel_moyen) : "—"))),
        h("tr", {}, h("th", {}, "Exactitude"), ...lot.map((x) => h("td", { class: "doux" }, x.resultats ? nb(x.resultats.rapport.exactitude, 3) : "—"))),
        ...classes.map((c) => h("tr", {}, h("th", {}, `rappel « ${c} »`), ...lot.map((x) => { const p = x.resultats && x.resultats.rapport.par_classe[c]; return h("td", {}, p && p.rappel !== null ? [barreValeur(p.rappel, null), p.fiable ? null : h("small", { class: "doux" }, `non fiable (${p.n} images)`)] : "—"); }))))) ),
    h("div", { class: "carte defile" }, h("h2", {}, "Configuration"), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), ...lot.map((x) => h("th", {}, x.essai.id)))),
      h("tbody", {}, ...cles.map((k) => { const valeurs = plats.map((p) => p[k] ?? "—"); const diff = new Set(valeurs).size > 1; return h("tr", { class: diff ? "diff" : "" }, h("th", {}, k), ...valeurs.map((v) => h("td", { class: "mono" }, v))); })))));
}

// ── page Lancer ───────────────────────────────────────────────────────────

const AIDE = {
  jeu: "La variante de jeu de données. Ses effectifs sont rappelés ci-dessous : une classe rare rend le résultat peu fiable.",
  famille: "La famille de modèle. « jouet » sert à éprouver la chaîne sans GPU ; « yolo_cls » entraîne YOLO classify.",
  modele: "Le nom du modèle, par exemple yolo26n-cls (petit) ou yolo26s-cls (plus grand).",
  imgsz: "Côté de l'image donnée au modèle. Plus grand : plus de détail mais plus lent. 64 est très grossier pour une scène de rue.",
  epochs: "Nombre de passages sur le jeu d'entraînement. Il n'y a pas d'arrêt anticipé : on mesure le dernier poids.",
  batch: "Images traitées ensemble.",
  graine: "Fixe le hasard. Deux essais de même configuration et de même graine se ressemblent ; changez-la pour mesurer le bruit.",
  reglages: "Réglages de la famille, en JSON, par exemple {\"fliplr\": 0, \"lr0\": 0.005}. Un réglage inconnu est refusé, pas ignoré.",
};
function champ(nom, etiquette, saisie) { return h("div", { class: "champ" }, h("label", { for: nom }, etiquette), saisie, h("small", {}, AIDE[nom] || "")); }

async function pageLancer(zone, requete) {
  const variantes = await api("/api/variantes");
  const depuis = new URLSearchParams(requete).get("depuis");
  let base = { jeu: "", methode: { famille: "yolo_cls", modele: "yolo26n-cls", imgsz: 224, epochs: 40, batch: 32, reglages: {} }, graine: 0, note: "" };
  if (depuis) { try { base = (await api(`/api/essais/${depuis}`)).essai.config; } catch { /* repart des défauts */ } }
  const sel = h("select", { id: "jeu" }, ...variantes.filter((v) => !v.invalide).map((v) => h("option", { value: v.id, selected: v.id === base.jeu }, v.id)));
  const resume = h("div", { class: "doux" });
  const maj = () => { const v = variantes.find((x) => x.id === sel.value); resume.replaceChildren(v ? `classes : ${v.classes.join(", ")} — train ${Object.values(v.effectifs.train).reduce((a, b) => a + b, 0)} · val ${Object.values(v.effectifs.val).reduce((a, b) => a + b, 0)} · test ${Object.values(v.effectifs.test).reduce((a, b) => a + b, 0)}` : "aucune variante"); };
  sel.addEventListener("change", maj); maj();
  const f = (id, type, valeur, extra = {}) => h("input", { id, type, value: valeur, ...extra });
  const famille = h("select", { id: "famille" }, ...["yolo_cls", "jouet"].map((x) => h("option", { value: x, selected: x === base.methode.famille }, x)));
  const champs = { modele: f("modele", "text", base.methode.modele), imgsz: f("imgsz", "number", base.methode.imgsz, { min: 8, max: 2048 }), epochs: f("epochs", "number", base.methode.epochs, { min: 1, max: 1000 }), batch: f("batch", "number", base.methode.batch, { min: 1 }), graine: f("graine", "number", base.graine),
    reglages: h("textarea", { id: "reglages", spellcheck: "false" }, JSON.stringify(base.methode.reglages || {}, null, 2)), note: h("textarea", { id: "note", style: "font-family:inherit" }, base.note || "") };
  const envoyer = h("button", { class: "principal", type: "submit" }, "Mettre en file");
  const formulaire = h("form", { class: "carte formulaire", onsubmit: async (ev) => {
    ev.preventDefault();
    let reglages; try { reglages = JSON.parse(champs.reglages.value || "{}"); } catch { avis("Les réglages ne sont pas du JSON valide.", true); return; }
    envoyer.disabled = true;
    try {
      const r = await api("/api/essais", { corps: { jeu: sel.value, methode: { famille: famille.value, modele: champs.modele.value, imgsz: +champs.imgsz.value, epochs: +champs.epochs.value, batch: +champs.batch.value, reglages }, graine: +champs.graine.value, note: champs.note.value } });
      avis(`${r.id} mis en file.`); location.hash = `#/essais/${r.id}`;
    } catch (x) { avis(x.message, true); envoyer.disabled = false; }
  } },
    champ("jeu", "Jeu de données", sel), h("div", { class: "champ large" }, resume), champ("famille", "Famille", famille), champ("modele", "Modèle", champs.modele), champ("imgsz", "Résolution", champs.imgsz), champ("epochs", "Époques", champs.epochs), champ("batch", "Lot", champs.batch), champ("graine", "Graine", champs.graine),
    h("div", { class: "champ large" }, h("label", { for: "reglages" }, "Réglages de la famille"), champs.reglages, h("small", {}, AIDE.reglages)), h("div", { class: "champ large" }, h("label", { for: "note" }, "Note"), champs.note, h("small", {}, "Ce que vous voulez vérifier. La note ne change pas l'identité de l'essai.")),
    h("div", { class: "large actions" }, envoyer, h("a", { class: "bouton", href: "#/essais" }, "Annuler")));
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, depuis ? `Rejouer ${depuis}` : "Lancer un essai"), h("p", { class: "doux" }, "L'essai entre dans la file ; un seul tourne à la fois. Sa configuration est gardée telle quelle : on peut toujours le rejouer."))), variantes.length ? formulaire : h("div", { class: "carte vide" }, "Aucun jeu de données. Il en faut un avant de lancer un essai."));
}

// ── routeur ───────────────────────────────────────────────────────────────

let nettoyage = null, numero = 0;
async function render() {
  const mon = ++numero;
  if (typeof nettoyage === "function") nettoyage();
  nettoyage = null;
  const [chemin, requete = ""] = location.hash.replace(/^#/, "").split("?");
  const morceaux = chemin.split("/").filter(Boolean);
  const section = morceaux[0] || (TACHE.tache === "profondeur" ? "juger" : "essais");
  document.querySelectorAll("[data-nav]").forEach((a) => (a.dataset.nav === section || (section === "comparer" && a.dataset.nav === "essais") ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const zone = document.getElementById("contenu");
  try {
    let n;
    if (section === "essais" && morceaux[1]) n = await pageEssai(zone, morceaux[1]);
    else if (section === "essais") n = await pageEssais(zone);
    else if (section === "comparer") n = await pageComparer(zone, requete);
    else if (section === "lancer") n = await pageLancer(zone, requete);
    else if (section === "valider") n = await pageValider(zone);
    else if (section === "juger") n = await pageJuger(zone);
    else if (section === "classement") n = await pageClassement(zone);
    else if (section === "panoramas") n = await pagePanoramas(zone, morceaux[1]);
    else if (section === "traitements") n = await pageTraitements(zone);
    else if (section === "donnees") n = await pageDonnees(zone, morceaux[1]);
    else if (section === "livrable") n = await pageLivrable(zone);
    else zone.replaceChildren(h("div", { class: "carte vide" }, "Page inconnue. ", h("a", { href: "#/essais" }, "Retour aux essais.")));
    if (mon === numero) nettoyage = typeof n === "number" ? () => clearInterval(n) : n;
    else if (typeof n === "number") clearInterval(n);
  } catch (e) {
    zone.replaceChildren(h("div", { class: "carte" }, h("h1", {}, e.statut === 404 ? "Introuvable" : "Erreur"), h("p", {}, e.message), h("a", { href: "#/essais" }, "Retour aux essais")));
  }
}
window.addEventListener("hashchange", render);
majPod(); setInterval(() => { if (!document.hidden) majPod(); }, 5000);
chargerTache().finally(render);
