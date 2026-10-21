/* Page Valider : une image à la fois, tout au clavier. Ce qu'on valide : le nombre de places perçues et la forme du stationnement. */
"use strict";

const FORMES_VALIDATION = [["aucune", "Aucune", "A"], ["bataille", "Bataille", "B"], ["longitudinal", "Longitudinal", "L"]];

function lireStockage(cle, defaut) { try { const v = localStorage.getItem(cle); return v === null ? defaut : v; } catch { return defaut; } }
function ecrireStockage(cle, valeur) { try { localStorage.setItem(cle, valeur); } catch { /* navigation privée : on s'en passe */ } }
const urlImage = (chemin, options = {}) => `api/brut/image?${new URLSearchParams({ chemin, ...options })}`;

async function pageValider(zone) {
  let valideur = lireStockage("labo_valideur", "");
  if (!valideur) return demanderLeNom(zone);
  const files = await api("/api/validation/files");
  let fichier = lireStockage("labo_file", files[0] ? files[0].nom : "audit_classe_1");
  if (!files.some((f) => f.nom === fichier)) fichier = files[0].nom;
  let aveugle = lireStockage("labo_aveugle", "1") === "1";
  let courant = null, file = [], total = 0, faites = 0, stats = null, nombre = null, forme = "aucune", ouvertA = 0, occupe = false;

  const entete = h("div", { class: "entete" });
  const corps = h("div", { class: "valider" });
  const annonce = h("div", { class: "doux", role: "status", "aria-live": "polite", style: "min-height:1.4rem" });
  const note = h("input", { id: "note-validation", type: "text", maxlength: 500, placeholder: "Note (facultatif) — touche N" });

  const charger = async (image) => {
    const p = new URLSearchParams({ type: fichier, validateur: valideur, limite: 3 }); if (image) p.set("image", image);
    const r = await api(`/api/validation/file?${p}`);
    file = r.items; total = r.total; faites = r.faites;
    try { stats = await api(`/api/validation/stats?${new URLSearchParams({ fichier })}`); } catch { stats = null; }
    courant = file[0] || null; nombre = null; forme = "aucune"; ouvertA = Date.now(); note.value = "";
    file.slice(1).forEach((i) => { const im = new Image(); im.src = urlImage(i.image, { largeur: 1000 }); });  // précharge les suivantes
    dessiner();
  };

  const envoyer = async (corps_) => {
    if (occupe || !courant) return;
    occupe = true;
    try {
      await api("/api/validation/decisions", { corps: { image: courant.image, validateur: valideur, fichier, aveugle, duree_ms: Date.now() - ouvertA, note: note.value.trim(), ...corps_ } });
      annonce.textContent = corps_.douteuse ? "Marquée douteuse." : `Enregistré : ${corps_.nombre} place${corps_.nombre > 1 ? "s" : ""}, ${corps_.forme}.`;
      await charger();
    } catch (e) { avis(e.message, true); } finally { occupe = false; }
  };
  const valider = (n, f) => envoyer({ nombre: n, forme: n === 0 ? "aucune" : f });
  const annuler = async () => {
    if (occupe) return;
    occupe = true;
    try {
      const d = (await api(`/api/validation/derniere?${new URLSearchParams({ validateur: valideur })}`)).decision;
      if (!d) { avis("Rien à annuler."); return; }
      await api(`/api/validation/decisions/${d.id}/annuler`, { corps: { validateur: valideur } });
      annonce.textContent = "Décision annulée : l'image revient.";
      occupe = false;
      await charger(d.image);
    } catch (e) { avis(e.message, true); } finally { occupe = false; }
  };

  const touche = (ev) => {
    const cible = ev.target;
    if (cible && (cible.tagName === "INPUT" || cible.tagName === "TEXTAREA" || cible.tagName === "SELECT")) {
      if (cible === note && ev.key === "Escape") { note.blur(); ev.preventDefault(); }
      return;
    }
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const k = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key;
    if (cible && cible.tagName === "BUTTON" && (k === "Enter" || k === " ")) return;  // un bouton activé au clavier agit déjà par son clic
    if (/^[0-9]$/.test(k)) { ev.preventDefault(); if (k === "0") valider(0, "aucune"); else { nombre = +k; dessiner(); } }
    else if (["a", "b", "l"].includes(k) && nombre !== null) { ev.preventDefault(); valider(nombre, { a: "aucune", b: "bataille", l: "longitudinal" }[k]); }
    else if ((k === "Enter" || k === " ") && nombre !== null) { ev.preventDefault(); valider(nombre, forme); }
    else if (k === " " && courant && !aveugle) { ev.preventDefault(); valider(courant.ancien.nombre ?? 0, courant.ancien.forme); }  // confirme l'étiquette d'origine
    else if (k === "d") { ev.preventDefault(); envoyer({ douteuse: true }); }
    else if (k === "z") { ev.preventDefault(); annuler(); }
    else if (k === "v") { ev.preventDefault(); aveugle = !aveugle; ecrireStockage("labo_aveugle", aveugle ? "1" : "0"); dessiner(); }
    else if (k === "n") { ev.preventDefault(); note.focus(); }
    else if (k === "Escape") { nombre = null; dessiner(); }
  };
  document.addEventListener("keydown", touche);

  const bouton = (texte, pressed, onclick, titre) => h("button", { type: "button", "aria-pressed": pressed ? "true" : "false", title: titre || "", onclick }, texte);

  function dessiner() {
    const fichierInfos = files.find((f) => f.nom === fichier);
    const part = total ? Math.round((faites / total) * 100) : 0;
    entete.replaceChildren(
      h("div", {}, h("h1", {}, "Valider"), h("p", { class: "doux" }, "Nombre de places de stationnement perçues, de ce côté de la rue, et forme du stationnement. ", h("a", { href: "#/valider", onclick: (ev) => { ev.preventDefault(); ecrireStockage("labo_valideur", ""); location.reload(); } }, `Vous êtes ${valideur} (changer)`))),
      h("div", { class: "actions" }, h("select", { id: "choix-file", "aria-label": "File à valider", onchange: (ev) => { fichier = ev.target.value; ecrireStockage("labo_file", fichier); charger(); } }, ...files.map((f) => h("option", { value: f.nom, selected: f.nom === fichier }, f.nom.replaceAll("_", " ")))),
        h("button", { type: "button", id: "bascule-aveugle", onclick: () => { aveugle = !aveugle; ecrireStockage("labo_aveugle", aveugle ? "1" : "0"); dessiner(); } }, aveugle ? "Étiquette d'origine cachée" : "Étiquette d'origine visible")));
    if (!courant) {
      corps.replaceChildren(h("div", { class: "carte vide large", style: "grid-column:1/-1" }, h("h2", {}, "File terminée"), h("p", {}, `Vous avez traité les ${total} images de cette file. Merci.`), h("p", { class: "doux" }, fichierInfos ? fichierInfos.description : "")));
      return;
    }
    // La zone à qualifier est la moitié du côté indiqué ; l'autre moitié est assombrie (une voiture de l'autre côté de la rue ne compte pas).
    const hors = h("div", { class: `zone-hors ${courant.cote}`, "aria-hidden": "true" }, h("span", {}, "hors sujet"));
    const concerne = h("div", { class: `zone-concernee ${courant.cote}`, "aria-hidden": "true" }, h("span", {}, `côté ${courant.cote} : à qualifier`));
    const grande = h("figure", {}, h("div", { class: "cadre" }, h("img", { id: "image-courante", alt: `Image à valider, côté ${courant.cote}`, src: urlImage(courant.image, { largeur: 1000 }) }), hors, concerne),
      h("figcaption", {}, h("strong", {}, `On qualifie uniquement le côté ${courant.cote.toUpperCase()} de la rue`), " (zone claire) — la zone assombrie est hors sujet. ", `Collection ${courant.groupe.split("/").slice(-1)[0].slice(0, 12)}…`));
    const vignette = (titre, chemin, options) => h("figure", {}, chemin ? h("img", { alt: titre, src: urlImage(chemin, { largeur: 320, ...options }) }) : h("div", { class: "doux", style: "aspect-ratio:3/2;display:grid;place-items:center;border:1px dashed var(--bord);border-radius:6px" }, "—"), h("figcaption", {}, titre));
    const gauche = h("div", {}, grande, h("div", { class: "vignettes" }, vignette(`La zone claire, agrandie : ce que voit le modèle (côté ${courant.cote})`, courant.image, { rognage: "1" }), vignette("Image précédente de la séquence", courant.avant), vignette("Image suivante", courant.apres)));
    const ancien = aveugle ? null : h("div", { class: "ancien", id: "ancien" }, `Étiquette d'origine : ${courant.ancien.nombre ?? "?"} place(s), forme ${courant.ancien.forme}. `, h("kbd", {}, "Espace"), " la confirme.");
    const droite = h("div", { class: "carte" },
      h("div", {}, h("strong", {}, `${faites} / ${total}`), " images de cette file", h("div", { class: "progression", role: "progressbar", "aria-valuenow": part, "aria-valuemin": 0, "aria-valuemax": 100 }, h("b", { style: `width:${part}%` }))),
      annonce, ancien,
      stats && stats.part_confirmee !== null && stats.decisions >= 10 ? h("p", { class: "doux", id: "part-confirmee" }, `Étiquettes d'origine confirmées par les valideurs : ${Math.round(stats.part_confirmee * 100)} % (${stats.decisions} décisions, ${stats.douteuses} douteuses).`) : null,
      h("h2", {}, `Nombre de places perçues — côté ${courant.cote}`), h("div", { class: "touches", role: "group", "aria-label": "Nombre de places" }, ...Array.from({ length: 10 }, (_, n) => bouton(String(n), nombre === n, () => (n === 0 ? valider(0, "aucune") : (nombre = n, dessiner())), n === 0 ? "0 : validé tout de suite" : `${n} : puis une forme, ou Entrée`))),
      h("h2", {}, "Forme du stationnement"), h("div", { class: "touches", role: "group", "aria-label": "Forme" }, ...FORMES_VALIDATION.map(([v, texte, cle]) => bouton(`${texte} (${cle})`, forme === v, () => (nombre !== null ? valider(nombre, v) : (forme = v, dessiner()))))),
      h("div", { class: "actions", style: "margin-bottom:.8rem" }, h("button", { type: "button", id: "douteuse", onclick: () => envoyer({ douteuse: true }) }, "Douteuse (D)"), h("button", { type: "button", id: "annuler", onclick: annuler }, "Annuler la dernière (Z)")),
      note,
      h("h2", { style: "margin-top:1rem" }, "Touches"),
      h("dl", { class: "aide-touches" }, h("dt", {}, h("kbd", {}, "0")), h("dd", {}, "aucune place, tout de suite"), h("dt", {}, h("kbd", {}, "1…9")), h("dd", {}, "le nombre ; puis A / B / L pour la forme, ou Entrée (aucune)"),
        h("dt", {}, h("kbd", {}, "D")), h("dd", {}, "douteuse (inexploitable)"), h("dt", {}, h("kbd", {}, "Z")), h("dd", {}, "annuler la dernière"), h("dt", {}, h("kbd", {}, "V")), h("dd", {}, "voir / cacher l'étiquette d'origine"), h("dt", {}, h("kbd", {}, "N")), h("dd", {}, "écrire une note")));
    corps.replaceChildren(gauche, droite);
  }

  zone.replaceChildren(entete, corps);
  await charger();
  return () => document.removeEventListener("keydown", touche);
}

async function demanderLeNom(zone) {
  const champNom = h("input", { id: "nom-valideur", type: "text", maxlength: 40, autocomplete: "name", required: true, autofocus: true });
  zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Valider"), h("p", { class: "doux" }, "Chaque décision porte le nom de la personne qui l'a prise.")),
    h("form", { class: "carte formulaire", style: "max-width:28rem", onsubmit: (ev) => { ev.preventDefault(); const nom = champNom.value.trim(); if (!nom) return; ecrireStockage("labo_valideur", nom); render(); } },
      h("div", { class: "champ large" }, h("label", { for: "nom-valideur" }, "Votre nom"), champNom, h("small", {}, "Il s'affiche dans le journal. Ce n'est pas un mot de passe : l'accès reste protégé par le jeton.")),
      h("div", { class: "large actions" }, h("button", { class: "principal", type: "submit" }, "Commencer")))));
  champNom.focus();
}
