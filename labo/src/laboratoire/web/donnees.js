/* Page Données : le brut, les recettes (aperçu immédiat, rien n'est écrit), les variantes construites, l'explorateur d'images. */
"use strict";

const GRAVITE = { bloquant: "bloquant", avertissement: "à savoir" };
const somme = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);

function constats(liste) {
  if (!liste || !liste.length) return h("p", { class: "doux" }, h("span", { class: "badge sain" }, "aucun problème"), " Les contrôles n'ont rien trouvé.");
  return h("div", {}, ...liste.map((c) => h("div", { class: `constat ${c.gravite}` }, h("strong", {}, GRAVITE[c.gravite] || c.gravite, " · "), c.message)));
}

function tableauEffectifs(classes, effectifs, groupes) {
  return h("div", { class: "defile" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Jeu"), groupes ? h("th", { class: "num" }, "Collections") : null, ...classes.map((c) => h("th", { class: "num" }, c)), h("th", { class: "num" }, "Total"))),
    h("tbody", {}, ...["train", "val", "test"].map((j) => h("tr", {}, h("th", {}, j), groupes ? h("td", { class: "num" }, groupes[j]) : null,
      ...classes.map((c) => { const n = (effectifs[j] || {})[c] || 0; return h("td", { class: "num", title: j !== "train" && n < 20 ? "moins de 20 images : rappel peu fiable" : "" }, n, j !== "train" && n < 20 ? " ⚠" : ""); }), h("td", { class: "num" }, somme(effectifs[j])))))));
}

async function pageDonnees(zone, sous) {
  if (sous === "nouvelle") return pageRecette(zone);
  if (sous) return pageVariante(zone, sous);
  const [brut, variantes] = await Promise.all([api("/api/brut"), api("/api/variantes")]);
  const r = brut.resume;
  const tuile = (v, e, d) => h("div", { class: "tuile" }, h("div", { class: "valeur" }, v), h("div", { class: "etiquette" }, e), d ? h("div", { class: "detail" }, d) : null);
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Données"), h("p", { class: "doux" }, "Le brut ne change jamais. Une variante est le brut passé par une recette : changer la recette, c'est changer la structure du jeu.")),
      h("div", { class: "actions" }, h("a", { class: "bouton principal", href: "#/donnees/nouvelle" }, "Nouvelle variante"))),
    h("div", { class: "tuiles" }, tuile(r.images, "images brutes", brut.dossier), tuile(r.collections, "collections"), tuile(Object.entries(r.par_cote).map(([k, v]) => `${k} ${v}`).join(" · "), "par côté"),
      tuile(r.panoramiques, "panoramiques"), tuile(r.anomalies, "anomalies", r.anomalies ? "voir ci-dessous" : "")),
    h("div", { class: "grille" },
      h("div", { class: "carte" }, h("h2", {}, "Nombre de places"), h("p", {}, Object.entries(r.par_nombre).map(([k, v]) => `${k} : ${v}`).join(" · "))),
      h("div", { class: "carte" }, h("h2", {}, "Formes"), h("p", {}, Object.entries(r.par_forme).map(([k, v]) => `${k} : ${v}`).join(" · ")))),
    brut.anomalies.length ? h("div", { class: "carte" }, h("h2", {}, "Anomalies du brut (non classées, jamais ignorées en silence)"), h("ul", {}, ...brut.anomalies.slice(0, 30).map((a) => h("li", { class: "mono" }, a)))) : null,
    h("h2", {}, "Variantes"),
    ...(variantes.length ? variantes.map((v) => v.invalide ? h("div", { class: "carte", style: "border-color:var(--mal)" }, h("h2", {}, v.id), h("p", {}, "Inutilisable : ", v.invalide)) :
      h("div", { class: "carte" }, h("h2", {}, h("a", { href: `#/donnees/${v.id}` }, v.id)), tableauEffectifs(v.classes, v.effectifs, v.groupes))) : [h("div", { class: "carte vide" }, "Aucune variante pour l'instant. ", h("a", { href: "#/donnees/nouvelle" }, "Créer la première."))]));
}

const OPTIONS = {
  cote: [["droite", "droite"], ["gauche", "gauche"]],
  tache: [["nombre", "nombre de places"], ["forme", "forme (bataille / longitudinal)"]],
  preparation: [["rognage", "rognage : moitié du côté étudié"], ["masque", "masque : l'autre moitié noircie"], ["aucune", "image entière"]],
  panoramiques: [["inclure", "inclure"], ["exclure", "exclure"], ["seulement", "seulement"]],
};

async function pageRecette(zone) {
  const sel = (id, opts, valeur) => h("select", { id }, ...opts.map(([v, t]) => h("option", { value: v, selected: v === valeur }, t)));
  const champs = {
    cote: sel("cote", OPTIONS.cote, "droite"), tache: sel("tache", OPTIONS.tache, "nombre"), preparation: sel("preparation", OPTIONS.preparation, "rognage"), panoramiques: sel("panoramiques", OPTIONS.panoramiques, "inclure"),
    plafond: h("input", { id: "plafond", type: "number", min: 1, value: 2 }), graine: h("input", { id: "graine", type: "number", value: 7 }),
    train: h("input", { id: "p-train", type: "number", step: "0.05", min: 0.05, max: 0.9, value: 0.7 }), val: h("input", { id: "p-val", type: "number", step: "0.05", min: 0.05, max: 0.9, value: 0.15 }),
    reeq: h("input", { id: "reeq", type: "checkbox", checked: true }), rapport: h("input", { id: "rapport", type: "number", step: "0.1", min: 0.1, max: 1, value: 0.5 }),
    corr: h("input", { id: "corr", type: "checkbox", checked: true }), nom: h("input", { id: "nom", type: "text", placeholder: "facultatif, ex. droite-rognage" }),
  };
  const lire = () => {
    const train = +champs.train.value, val = +champs.val.value;
    return { cote: champs.cote.value, tache: champs.tache.value, plafond_nombre: champs.plafond.value ? +champs.plafond.value : null, preparation: champs.preparation.value, panoramiques: champs.panoramiques.value,
      decoupage: { proportions: [train, val, Math.round((1 - train - val) * 1e6) / 1e6], graine: +champs.graine.value }, reequilibrage: { actif: champs.reeq.checked, rapport: +champs.rapport.value }, corrections: champs.corr.checked, nom: champs.nom.value.trim() };
  };
  const resultat = h("div", { "aria-live": "polite" }, h("p", { class: "doux" }, "Calcul de l'aperçu…"));
  const construire = h("button", { class: "principal", type: "button", disabled: true }, "Construire la variante");
  let minuteur = null, courant = 0;
  const apercu = async () => {
    const n = ++courant;
    try {
      const d = await api("/api/variantes/apercu", { corps: lire() });
      if (n !== courant) return;
      construire.disabled = !d.constructible || d.existe;
      construire.textContent = d.existe ? "Cette variante existe déjà" : "Construire la variante";
      construire.dataset.id = d.id;
      resultat.replaceChildren(
        h("p", {}, "Identité : ", h("span", { class: "mono" }, d.id), d.existe ? [" — ", h("a", { href: `#/donnees/${d.id}` }, "ouvrir")] : ""),
        tableauEffectifs(d.classes, d.effectifs, d.groupes),
        h("p", { class: "doux" }, "Hors copies de rééquilibrage : train ", somme(d.effectifs_sans_copies.train), " · val ", somme(d.effectifs_sans_copies.val), " · test ", somme(d.effectifs_sans_copies.test),
          Object.keys(d.ecartes).length ? ` — écartées : ${Object.entries(d.ecartes).map(([k, v]) => `${v} ${k}`).join(", ")}` : ""),
        h("h2", {}, "Contrôles"), constats(d.controles));
    } catch (e) { if (n === courant) { construire.disabled = true; resultat.replaceChildren(h("div", { class: "constat bloquant" }, e.message)); } }
  };
  const declencher = () => { clearTimeout(minuteur); minuteur = setTimeout(apercu, 250); };
  Object.values(champs).forEach((c) => { c.addEventListener("input", declencher); c.addEventListener("change", declencher); });
  construire.addEventListener("click", async () => {
    construire.disabled = true;
    try {
      const r = await api("/api/variantes", { corps: lire() });
      avis(`Construction de ${r.id}…`);
      const suivre = async () => {
        const d = await api(`/api/variantes/${r.id}`);
        if (d.classes) { avis("Variante construite."); location.hash = `#/donnees/${r.id}`; return; }
        if (d.construction && d.construction.erreur) { avis(d.construction.erreur, true); construire.disabled = false; return; }
        if (d.construction) construire.textContent = `Construction… ${d.construction.fait || 0}/${d.construction.total || "?"}`;
        setTimeout(suivre, 700);
      };
      suivre();
    } catch (e) { avis(e.message, true); construire.disabled = false; }
  });
  const champ2 = (id, t, saisie, aide) => h("div", { class: "champ" }, h("label", { for: id }, t), saisie, aide ? h("small", {}, aide) : null);
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Nouvelle variante"), h("p", { class: "doux" }, "Chaque réglage change la structure du jeu ; l'aperçu se met à jour sans écrire une seule image. Les collections ne sont jamais coupées entre train, val et test.")),
      h("div", { class: "actions" }, h("a", { class: "bouton", href: "#/donnees" }, "Retour"))),
    h("div", { class: "grille" },
      h("div", { class: "carte formulaire" },
        champ2("cote", "Côté de la rue", champs.cote), champ2("tache", "Ce qu'on prédit", champs.tache), champ2("plafond", "Plafond du nombre de places", champs.plafond, "2 : classes 0, 1 et « 2 et plus ». Vide : une classe par nombre."),
        champ2("preparation", "Préparation de l'image", champs.preparation), champ2("panoramiques", "Vues panoramiques", champs.panoramiques),
        champ2("p-train", "Part du train", champs.train), champ2("p-val", "Part de val (le reste va au test)", champs.val), champ2("graine", "Graine du découpage", champs.graine),
        h("div", { class: "champ" }, h("label", {}, champs.reeq, " Rééquilibrer le train par copies"), champs.rapport, h("small", {}, "Part de la plus grande classe visée. Jamais dans val ni test.")),
        h("div", { class: "champ" }, h("label", {}, champs.corr, " Appliquer les corrections d'étiquettes"), h("small", {}, "Écartées ou rectifiées dans corrections.csv ; le brut n'est jamais modifié.")),
        champ2("nom", "Nom", champs.nom), h("div", { class: "large actions" }, construire)),
      h("div", { class: "carte" }, h("h2", {}, "Aperçu"), resultat)));
  apercu();
  return () => { clearTimeout(minuteur); courant++; };
}

async function pageVariante(zone, ident) {
  const v = await api(`/api/variantes/${ident}`);
  if (!v.classes) { zone.replaceChildren(h("div", { class: "carte" }, h("h1", {}, ident), h("p", {}, "Construction en cours…"))); return; }
  const etat = { jeu: "train", classe: "", decalage: 0 };
  const galerie = h("div", { class: "galerie" }), pied = h("p", { class: "doux" });
  const jeu = h("select", { id: "f-jeu" }, ...["train", "val", "test"].map((j) => h("option", { value: j }, j)));
  const classe = h("select", { id: "f-classe" }, h("option", { value: "" }, "toutes"), ...v.classes.map((c) => h("option", { value: c }, c)));
  const prec = h("button", { type: "button" }, "←"), suiv = h("button", { type: "button" }, "→");
  const LOT = 48;
  const charger = async () => {
    const p = new URLSearchParams({ jeu: jeu.value, decalage: etat.decalage, limite: LOT }); if (classe.value) p.set("classe", classe.value);
    const d = await api(`/api/variantes/${ident}/images?${p}`);
    galerie.replaceChildren(...d.images.map((i) => h("figure", { title: `${i.groupe} · ${i.fichier}` }, h("img", { loading: "lazy", alt: `classe ${i.classe}`, src: `api/variantes/${ident}/image?${new URLSearchParams({ fichier: i.fichier, largeur: 240 })}` }), h("figcaption", {}, `classe ${i.classe} · ${i.groupe.split("/").pop()}`))));
    pied.textContent = d.total ? `${etat.decalage + 1}–${Math.min(etat.decalage + LOT, d.total)} sur ${d.total}` : "Aucune image.";
    prec.disabled = etat.decalage === 0; suiv.disabled = etat.decalage + LOT >= d.total;
  };
  const refiltrer = () => { etat.decalage = 0; charger().catch((e) => avis(e.message, true)); };
  jeu.addEventListener("change", refiltrer); classe.addEventListener("change", refiltrer);
  prec.addEventListener("click", () => { etat.decalage = Math.max(0, etat.decalage - LOT); charger(); });
  suiv.addEventListener("click", () => { etat.decalage += LOT; charger(); });
  const r = v.recette || {};
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, v.id), h("p", { class: "doux" }, "Variante construite : elle ne change plus. Pour une autre structure, une autre recette.")), h("div", { class: "actions" }, h("a", { class: "bouton principal", href: "#/lancer" }, "Lancer un essai"), h("a", { class: "bouton", href: "#/donnees" }, "Retour"))),
    h("div", { class: "grille" }, h("div", { class: "carte" }, h("h2", {}, "Effectifs"), tableauEffectifs(v.classes, v.effectifs, Object.fromEntries(Object.entries(v.groupes).map(([j, g]) => [j, g.length])))),
      h("div", { class: "carte" }, h("h2", {}, "Recette"), h("dl", { class: "cle-valeur" }, ...Object.entries(r).filter(([k]) => k !== "nom").flatMap(([k, x]) => [h("dt", {}, k), h("dd", { class: "mono" }, typeof x === "object" ? JSON.stringify(x) : String(x))])))),
    h("div", { class: "carte" }, h("h2", {}, "Contrôles"), constats(v.controles)),
    h("div", { class: "carte" }, h("h2", {}, "Images"), h("div", { class: "filtres" }, h("div", { class: "champ" }, h("label", { for: "f-jeu" }, "Jeu"), jeu), h("div", { class: "champ" }, h("label", { for: "f-classe" }, "Classe"), classe), h("div", { class: "actions" }, prec, suiv)), galerie, pied));
  charger().catch((e) => avis(e.message, true));
}
