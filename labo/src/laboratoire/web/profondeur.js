/* Tâche « profondeur » : juger deux cartes de profondeur à l'aveugle, lire le classement, parcourir les panoramas, lancer des traitements.
   Les fonctions de app.js (h, api, nb, badge…) sont utilisées à l'appel, pas au chargement. */
"use strict";

let TACHE = { tache: "classification", auteur: "", role: "admin" };

async function chargerTache() {
  try { TACHE = await api("/api/tache"); } catch { /* ancien service : tâche de classification */ }
  if (TACHE.tache !== "profondeur") return;
  document.title = "Laboratoire — profondeur";
  const marque = document.querySelector(".marque");
  if (marque) marque.replaceChildren(h("span", { class: "logo", "aria-hidden": "true" }, "◧"), " Laboratoire — profondeur");
  const nav = document.querySelector(".onglets");
  const onglets = TACHE.role === "valideur" ? [["juger", "Juger"]] : [["juger", "Juger"], ["classement", "Classement"], ["panoramas", "Panoramas"], ["traitements", "Traitements"]];
  nav.replaceChildren(...onglets.map(([k, t]) => h("a", { href: `#/${k}`, "data-nav": k }, t)));
  if (!location.hash || location.hash === "#/" || location.hash === "#/valider" || location.hash === "#/essais") location.hash = "#/juger";
}

const jeuxProfondeur = async () => (await api("/api/profondeur/jeux")).filter((j) => j.essais.length >= 1);
const choixJeu = async (surChangement) => {
  const jeux = await jeuxProfondeur();
  const memo = lireStockage("labo_jeu_profondeur", "");
  const sel = h("select", { "aria-label": "Jeu de panoramas", onchange: (e) => { ecrireStockage("labo_jeu_profondeur", e.target.value); surChangement(e.target.value); } },
    ...jeux.map((j) => h("option", { value: j.id, selected: j.id === memo }, `${j.id} (${j.panoramas} panoramas)`)));
  return { jeux, sel, courant: () => (jeux.some((j) => j.id === sel.value) ? sel.value : (jeux[0] || {}).id) };
};

// ── Juger ─────────────────────────────────────────────────────────────────

const AIDE_COULEURS = "Rouge : proche · bleu : loin · gris foncé : zone que le modèle écarte (le ciel).";

async function pageJuger(zone) {
  let jeu = lireStockage("labo_jeu_profondeur", "");  // fixé par la première paire reçue : une personne qui vote n'a pas la liste des jeux
  let paire = null, ouvertA = 0, occupe = false, dernierVote = null, annonce = h("div", { class: "doux", role: "status", "aria-live": "polite", style: "min-height:1.4rem" });
  const note = h("input", { id: "note-vote", type: "text", maxlength: 500, placeholder: "Note (facultatif) — touche N" });
  const corps = h("div");
  let essaye = false;
  const url = (cote) => `api/profondeur/paire/${paire.jeton}/${cote}.jpg`;

  const charger = async () => {
    try { paire = await api(`/api/profondeur/paire${jeu ? `?jeu=${encodeURIComponent(jeu)}` : ""}`); jeu = paire.jeu; ecrireStockage("labo_jeu_profondeur", jeu); }
    catch (e) {
      if (jeu && (e.statut === 409 || e.statut === 404) && !essaye) { essaye = true; jeu = ""; return charger(); }  // le jeu mémorisé n'existe plus
      paire = null; corps.replaceChildren(h("div", { class: "carte vide" }, e.statut === 404 ? "Plus aucune paire à juger : vous avez tout vu. Merci !" : e.statut === 409 ? "Il n'y a pas encore deux modèles à comparer : revenez plus tard." : e.message)); return;
    }
    essaye = false; ouvertA = Date.now(); note.value = ""; dessiner();
  };
  const voter = async (choix) => {
    if (occupe || !paire) return;
    occupe = true;
    try {
      const r = await api(`/api/profondeur/paire/${paire.jeton}/vote`, { corps: { choix, duree_ms: Date.now() - ouvertA, note: note.value.trim() } });
      dernierVote = r.vote;
      annonce.textContent = { gauche: "Gauche préférée.", droite: "Droite préférée.", egal: "Égalité enregistrée.", indecidable: "Passée (impossible à juger)." }[choix];
      await charger();
    } catch (e) { avis(e.message, true); } finally { occupe = false; }
  };
  const annuler = async () => {
    if (occupe) return;
    let id = dernierVote;
    try { if (!id) id = (await api(`/api/profondeur/votes/moi?jeu=${encodeURIComponent(jeu)}`)).dernier; } catch { /* rien */ }
    if (!id) { avis("Rien à annuler."); return; }
    try { await api(`/api/profondeur/votes/${id}/annuler`, { corps: {} }); dernierVote = null; annonce.textContent = "Dernier vote annulé."; await charger(); } catch (e) { avis(e.message, true); }
  };
  const bouton = (choix, texte, touche, extra = "") => h("button", { type: "button", class: extra, onclick: () => voter(choix), title: `Touche ${touche}` }, texte, " ", h("kbd", {}, touche));

  const dessiner = () => {
    const cible = (c) => `profondeur:${jeu}/${paire.panorama}/${paire.vue}/${c}`;
    corps.replaceChildren(
      h("div", { class: "carte" },
        h("p", {}, h("strong", {}, "Laquelle des deux cartes rend le mieux le relief de la scène ?"), " Regardez ce qui est proche et ce qui est loin : sol continu, bords nets, objets à leur place. Les couleurs n'ont pas d'importance, seulement la forme du relief."),
        h("div", { class: "trio" },
          h("figure", { "data-cible": cible("source") }, h("img", { src: url("source"), alt: "Vue de la scène", id: "vue-source" }), h("figcaption", {}, "La scène")),
          h("figure", { "data-cible": cible("gauche") }, h("img", { src: url("gauche"), alt: "Carte de gauche" }), h("figcaption", {}, "Gauche")),
          h("figure", { "data-cible": cible("droite") }, h("img", { src: url("droite"), alt: "Carte de droite" }), h("figcaption", {}, "Droite"))),
        h("p", { class: "doux" }, AIDE_COULEURS),
        h("div", { class: "touches" }, bouton("gauche", "Gauche mieux", "←", "principal"), bouton("egal", "Égales", "="), bouton("droite", "Droite mieux", "→", "principal"), bouton("indecidable", "Impossible à juger", "I")),
        h("div", { class: "champ large" }, note)));
  };
  const surTouche = (ev) => {
    const cible = ev.target; if (cible && (cible.tagName === "INPUT" || cible.tagName === "TEXTAREA") && ev.key !== "Escape") return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key;
    if (k === "ArrowLeft" || k === "1") voter("gauche");
    else if (k === "ArrowRight" || k === "2") voter("droite");
    else if (k === "=" || k === "e" || k === "E" || k === "0") voter("egal");
    else if (k === "i" || k === "I") voter("indecidable");
    else if (k === "z" || k === "Z") annuler();
    else if (k === "n" || k === "N") { ev.preventDefault(); note.focus(); }
    else return;
    if (k !== "n" && k !== "N") ev.preventDefault();
  };
  document.addEventListener("keydown", surTouche);
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Juger"), h("p", { class: "doux" }, "Deux cartes de profondeur de la même scène, de deux modèles que vous ne connaissez pas. Votre jugement est le critère qui compte : aucune mesure automatique ne remplace un œil humain ici.")),
    h("div", { class: "actions" }, h("button", { type: "button", onclick: annuler, title: "Touche Z" }, "Annuler le dernier vote ", h("kbd", {}, "Z")))), annonce, corps,
    h("div", { class: "carte" }, h("details", {}, h("summary", {}, "Touches"), h("dl", { class: "aide-touches" },
      h("dt", {}, h("kbd", {}, "←"), " ", h("kbd", {}, "→")), h("dd", {}, "la carte de gauche / de droite est meilleure"), h("dt", {}, h("kbd", {}, "="), " ou ", h("kbd", {}, "E")), h("dd", {}, "aussi bonnes l'une que l'autre"),
      h("dt", {}, h("kbd", {}, "I")), h("dd", {}, "impossible à juger (scène illisible)"), h("dt", {}, h("kbd", {}, "Z")), h("dd", {}, "annuler le dernier vote"), h("dt", {}, h("kbd", {}, "N")), h("dd", {}, "ajouter une note")))));
  await charger();
  return () => document.removeEventListener("keydown", surTouche);
}

// ── Classement ────────────────────────────────────────────────────────────

const LIB_MESURES = {
  incoherence_mediane: ["Incohérence", "Quand deux vues se recouvrent, voient-elles la même scène ? 0 : parfaitement cohérent, 1 : sans rapport. Plus c'est bas, mieux c'est."],
  derive_echelle_mediane: ["Dérive d'échelle", "Pour les modèles qui donnent des mètres : l'échelle change-t-elle d'une vue à l'autre ? 0 : stable."],
  temps_par_vue_s: ["Temps par vue (s)", "Durée médiane d'une vue sur le GPU."],
  vram_crete_mo: ["Mémoire GPU (Mo)", "Pic de mémoire pendant le traitement."],
};

async function pageClassement(zone) {
  const corps = h("div");
  const { jeux, sel, courant } = await choixJeu(() => charger());
  const charger = async () => {
    const jeu = courant();
    if (!jeu) { corps.replaceChildren(h("div", { class: "carte vide" }, "Aucun jeu avec un traitement terminé.")); return; }
    const s = await api(`/api/profondeur/synthese?jeu=${encodeURIComponent(jeu)}`);
    const c = s.classement;
    const lignes = s.modeles.map((m) => {
      const k = c && c.modeles[m.modele];
      return h("tr", {}, h("td", {}, k ? `${k.rang}` : "—"), h("td", {}, h("strong", {}, m.modele)),
        h("td", {}, k ? `${nb(k.force, 2)}${k.intervalle ? ` [${nb(k.intervalle[0], 2)} ; ${nb(k.intervalle[1], 2)}]` : ""}` : "—"),
        h("td", { class: "num" }, k ? `${k.victoires} / ${k.egalites} / ${k.defaites}` : "—"),
        h("td", { class: "num" }, nb(m.incoherence_mediane, 3)), h("td", { class: "num" }, m.metrique ? nb(m.derive_echelle_mediane, 3) : "—"),
        h("td", { class: "num" }, nb(m.temps_par_vue_s, 2)), h("td", { class: "num" }, m.vram_crete_mo ?? "—"), h("td", {}, m.licence || "—"),
        h("td", {}, h("a", { href: `#/essais/${m.essai}` }, m.essai)));
    });
    const noms = s.modeles.map((m) => m.modele);
    const matrice = noms.length > 1 ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), ...noms.map((n) => h("th", {}, n)))),
      h("tbody", {}, ...noms.map((a) => h("tr", {}, h("th", {}, a), ...noms.map((b) => { const v = a === b ? null : (s.accord[`${a}|${b}`] ?? s.accord[`${b}|${a}`]); return h("td", { class: "num" }, a === b ? "·" : nb(v, 2)); }))))) : null;
    corps.replaceChildren(
      !c || !c.fiable ? h("div", { class: "ancien" }, `Classement encore fragile : ${s.votes.total} jugement${s.votes.total > 1 ? "s" : ""} sur ${c ? c.panoramas : 0} panorama${c && c.panoramas > 1 ? "s" : ""}. Il en faut au moins 30, sur au moins 10 panoramas différents, pour s'y fier.`) : null,
      h("div", { class: "carte defile" }, h("h2", {}, "Ce que les personnes ont jugé"),
        h("p", { class: "doux" }, "Force : une force de plus de 1 point de différence ≈ « presque toujours préféré ». L'intervalle (90 %) vient d'un rééchantillonnage des panoramas : si deux intervalles se recouvrent, on ne peut pas départager les modèles. Colonne « V / É / D » : victoires, égalités, défaites."),
        h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Rang"), h("th", {}, "Modèle"), h("th", {}, "Force [intervalle]"), h("th", { class: "num" }, "V / É / D"),
          ...Object.values(LIB_MESURES).map(([t, aide]) => h("th", { class: "num", title: aide }, t)), h("th", {}, "Licence"), h("th", {}, "Essai"))), h("tbody", {}, ...lignes))),
      h("div", { class: "carte" }, h("h2", {}, "Ce que le laboratoire mesure seul"), h("p", { class: "doux" }, "Il n'y a pas de profondeur de référence : ces mesures disent la cohérence d'un modèle avec lui-même, pas son exactitude. Un modèle peut être cohérent et se tromper ; il ne peut pas être incohérent et avoir raison partout.")),
      matrice ? h("div", { class: "carte defile" }, h("h2", {}, "Accord entre modèles"), h("p", { class: "doux" }, "Corrélation du relief, vue par vue (médiane). 1 : même relief ; 0 : aucun rapport. Deux modèles en désaccord ne peuvent pas avoir tous les deux raison : les paires les plus en désaccord sont celles à regarder en priorité."), matrice) : null,
      h("div", { class: "carte" }, h("h2", {}, "Qui a voté"), h("p", {}, Object.entries(s.votes.par_votant).map(([n, k]) => `${n} : ${k}`).join(" · ") || "Personne pour l'instant."), h("p", { class: "doux" }, `${s.votes.indecidables} paire(s) jugée(s) impossible(s) à départager.`),
        TACHE.role === "admin" ? h("a", { class: "bouton", href: `api/profondeur/votes/export?jeu=${encodeURIComponent(jeu)}`, download: "votes.csv" }, "Exporter les votes (CSV)") : null));
  };
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Classement"), h("p", { class: "doux" }, "Quel modèle de profondeur rend le mieux le relief des panoramas, d'après les jugements humains, et ce que les mesures automatiques en disent.")), h("div", { class: "actions" }, sel)), corps);
  await charger();
}

// ── Panoramas ─────────────────────────────────────────────────────────────

async function pagePanoramas(zone, morceau) {
  const { jeux, sel, courant } = await choixJeu(() => location.hash = "#/panoramas");
  const jeu = courant();
  if (!jeu) { zone.replaceChildren(h("div", { class: "carte vide" }, "Aucun jeu de panoramas.")); return; }
  const liste = await api(`/api/profondeur/jeu/${encodeURIComponent(jeu)}/panoramas`);
  const detail = h("div");
  const meta = (p) => `${p.producteur || "—"} · ${p.licence} · ${(p.date || "").slice(0, 10)} · ${nb(p.lat, 4)}, ${nb(p.lon, 4)}`;
  const montrer = async (p) => {
    const essais = (jeux.find((j) => j.id === jeu) || { essais: [] }).essais;
    const synth = await api(`/api/profondeur/synthese?jeu=${encodeURIComponent(jeu)}`);
    const vues = ["c000_t00", "c090_t00", "c180_t00", "c270_t00", "c045_t15", "c225_t15"];
    let vueChoisie = vues[0];
    const grille = h("div", { class: "grille-profondeur" });
    const dessiner = () => grille.replaceChildren(
      h("figure", { "data-cible": `profondeur:${jeu}/${p.item}/${vueChoisie}/source` }, h("img", { src: `api/profondeur/jeu/${encodeURIComponent(jeu)}/vue/${p.item}/${vueChoisie}.jpg`, alt: "La scène" }), h("figcaption", {}, "La scène")),
      ...synth.modeles.map((m) => h("figure", { "data-cible": `profondeur:${jeu}/${p.item}/${vueChoisie}/${m.modele}` }, h("img", { src: `api/profondeur/essai/${m.essai}/apercu/${p.item}/${vueChoisie}.jpg`, alt: `Carte ${m.modele}`, loading: "lazy" }), h("figcaption", {}, m.modele))));
    detail.replaceChildren(h("div", { class: "carte" }, h("h2", {}, p.item), h("p", { class: "doux" }, meta(p)),
      h("img", { class: "erp", src: `api/profondeur/jeu/${encodeURIComponent(jeu)}/panorama/${p.item}.jpg?largeur=1400`, alt: "Panorama 360°", "data-cible": `profondeur:${jeu}/${p.item}/panorama` }),
      h("div", { class: "touches" }, ...vues.map((v) => h("button", { type: "button", "aria-pressed": v === vueChoisie ? "true" : "false", onclick: (ev) => { vueChoisie = v; ev.target.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === ev.target ? "true" : "false")); dessiner(); } }, v.replace("_", " · ")))), h("p", { class: "doux" }, AIDE_COULEURS), grille));
    dessiner(); detail.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Panoramas"), h("p", { class: "doux" }, `${liste.length} panoramas 360° de Panoramax (licences ouvertes ; chaque image garde sa licence et son producteur).`)), h("div", { class: "actions" }, sel)),
    h("div", { class: "galerie" }, ...liste.map((p) => h("button", { type: "button", class: "vignette", title: meta(p), onclick: () => montrer(p) }, h("img", { src: `api/profondeur/jeu/${encodeURIComponent(jeu)}/panorama/${p.item}.jpg?largeur=320`, alt: p.item, loading: "lazy" }), h("span", {}, p.item.slice(0, 8))))), detail);
}

// ── Traitements ───────────────────────────────────────────────────────────

const MODELES_PROFONDEUR = [["moge2", "MoGe-2 (MIT) — mètres"], ["da2-small", "Depth Anything V2 Small (Apache-2.0) — relatif"], ["da2-base", "Depth Anything V2 Base (CC-BY-NC) — relatif"], ["da2-large", "Depth Anything V2 Large (CC-BY-NC) — relatif"], ["dap", "DAP, Depth Any Panorama (CC-BY-NC) — panorama entier"], ["plan", "plan (modèle de test)"], ["contraste", "contraste (modèle de test)"]];

async function pageTraitements(zone) {
  const [jeux, essais, pod] = await Promise.all([api("/api/profondeur/jeux").catch(() => []), api("/api/essais?limite=200"), api("/api/pod")]);
  const traitements = essais.filter((e) => e.famille === "profondeur");
  const selJeu = h("select", { id: "jeu" }, ...jeux.map((j) => h("option", { value: j.id }, `${j.id} (${j.panoramas} panoramas)`)));
  const cases = MODELES_PROFONDEUR.map(([k, t]) => h("label", { class: "case" }, h("input", { type: "checkbox", value: k, checked: ["moge2", "da2-small"].includes(k) }), " ", t));
  const maxPano = h("input", { id: "max", type: "number", min: 0, value: 0 });
  const envoyer = h("button", { class: "principal", type: "submit" }, "Mettre en file");
  const form = h("form", { class: "carte formulaire", onsubmit: async (ev) => {
    ev.preventDefault();
    const choisis = cases.map((c) => c.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (!choisis.length) { avis("Choisissez au moins un modèle.", true); return; }
    envoyer.disabled = true;
    try {
      for (const m of choisis) await api("/api/essais", { corps: { jeu: selJeu.value, methode: { famille: "profondeur", modele: m, reglages: { panoramas_max: +maxPano.value } }, note: "" } });
      avis(`${choisis.length} traitement${choisis.length > 1 ? "s" : ""} mis en file.`); render();
    } catch (x) { avis(x.message, true); envoyer.disabled = false; }
  } }, h("div", { class: "champ large" }, h("label", { for: "jeu" }, "Jeu de panoramas"), selJeu), h("div", { class: "champ large" }, h("label", {}, "Modèles"), h("div", { class: "cases" }, ...cases),
    h("small", {}, "Les modèles « CC-BY-NC » ne s'emploient pas à des fins commerciales : vérifiez avant tout usage au-delà de la comparaison.")),
    h("div", { class: "champ" }, h("label", { for: "max" }, "Panoramas (0 : tous)"), maxPano), h("div", { class: "large actions" }, envoyer));
  const gpu = pod.travailleur && !pod.travailleur.connecte && pod.essais_en_file > 0 ? h("div", { class: "ancien" }, `Le GPU est éteint : ${pod.essais_en_file} traitement(s) attendent. Ils partiront dès que le pod GPU sera relancé.`) : null;
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Traitements"), h("p", { class: "doux" }, "Un traitement = un modèle sur tous les panoramas d'un jeu. Aucun entraînement : on fait tourner des modèles existants."))), gpu,
    jeux.length ? form : h("div", { class: "carte vide" }, "Aucun jeu de panoramas. Il faut en constituer un (voir la documentation)."),
    h("div", { class: "carte defile" }, h("h2", {}, "Historique"), h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Essai"), h("th", {}, "État"), h("th", {}, "Modèle"), h("th", {}, "Jeu"), h("th", {}, "Créé"))),
      h("tbody", {}, ...traitements.map((e) => h("tr", {}, h("td", {}, h("a", { href: `#/essais/${e.id}` }, e.id)), h("td", {}, badge(e.etat)), h("td", {}, e.modele), h("td", { class: "mono" }, e.jeu), h("td", {}, quand(e.cree_le))))))));
}
