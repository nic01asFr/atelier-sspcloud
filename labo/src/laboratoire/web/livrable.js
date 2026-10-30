/* Page Livrable : les modèles retenus, avec leurs chiffres, et de quoi les télécharger (un fichier, ou tout en une archive). */
"use strict";

const taille = (octets) => (octets >= 1e6 ? `${(octets / 1e6).toFixed(1).replace(".", ",")} Mo` : `${Math.max(1, Math.round(octets / 1e3))} Ko`);
const lienFichier = (nom, libelle, existants) =>
  existants.has(nom) ? h("a", { href: `api/livrable/fichier?nom=${encodeURIComponent(nom)}`, download: nom }, libelle) : h("span", { class: "doux" }, "—");

async function pageLivrable(zone) {
  const l = await api("/api/livrable");
  if (!l.existe) {
    zone.replaceChildren(h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Livrable"))), h("div", { class: "carte vide" }, "Aucun livrable n'a été constitué pour ce projet."));
    return;
  }
  const noms = new Set(l.fichiers.map((f) => f.nom));
  const n = (x) => Number(String(x).replace(",", "."));
  const lignes = l.synthese.map((r) => {
    const g = r.groupe;
    return h("tr", {},
      h("th", {}, g.replaceAll("_", " ")),
      h("td", {}, r.modele.replace("-cls", "")),
      h("td", {}, r.essai_livre),
      h("td", { class: "num" }, `${r.train} · ${r.val} · ${r.test}`),
      h("td", { class: "num" }, nb(n(r.rappel_moyen), 2), h("div", { class: "doux" }, `3 graines : ${nb(n(r.rappel_moyen_3_graines), 2)} ± ${nb(n(r.ecart_3_graines), 2)}`)),
      h("td", { class: "num" }, nb(n(r.hasard), 2)),
      h("td", { class: "num" }, `${pct(n(r.exactitude))} / ${pct(n(r.reponse_triviale))}`),
      h("td", {}, lienFichier(`${g}.pt`, "modèle", noms), " · ", lienFichier(`${g}_lots.csv`, "images", noms), " · ", lienFichier(`${g}_mesures.json`, "mesures", noms), " · ", lienFichier(`${g}_confusion_validation.csv`, "confusion", noms)));
  });
  zone.replaceChildren(
    h("div", { class: "entete" },
      h("div", {}, h("h1", {}, "Livrable"),
        h("p", { class: "doux" }, "Un modèle par groupe, la liste de ses images d'entraînement, de validation et de test, ses mesures et sa matrice de confusion.")),
      h("div", { class: "actions" }, h("a", { class: "bouton principal", href: "api/livrable/archive", download: "livrable.zip" }, `Tout télécharger (zip, ${taille(l.taille_totale)})`))),
    h("div", { class: "carte" },
      h("p", {}, h("strong", {}, "Toutes les mesures sont celles du lot de validation. "), "Le lot de test est scellé : il n'a pas été ouvert."),
      h("p", { class: "doux" }, "Le fichier du modèle est celui de la graine 0 ; « 3 graines » donne la moyenne et l'écart des trois entraînements, qui est la mesure à retenir. Rappel moyen : moyenne des rappels de chaque catégorie. Hasard : le rappel moyen d'un modèle qui répondrait au hasard. Exactitude / réponse triviale : part d'images bien classées, et ce qu'obtiendrait « toujours la catégorie la plus fréquente ».")),
    h("div", { class: "defile" }, h("table", {},
      h("thead", {}, h("tr", {}, ...["Groupe", "Modèle", "Essai", "Images (train · val · test)", "Rappel moyen", "Hasard", "Exactitude / triviale", "Fichiers"].map((t, i) => h("th", { class: i >= 3 && i <= 6 ? "num" : "" }, t)))),
      h("tbody", {}, ...lignes))),
    h("p", { class: "doux" }, l.fichiers.length, " fichiers · ", taille(l.taille_totale), " · ", lienFichier("synthese.csv", "tableau (CSV)", noms)));
}
