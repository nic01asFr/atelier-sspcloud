/* Page Aide : comment lire les chiffres du laboratoire, et pourquoi le test reste scellé. Texte fixe, aucune donnée du serveur. */
"use strict";

const TEXTES_AIDE = [
  ["Les trois lots d'images", [
    ["Entraînement (train)", "Les images sur lesquelles le modèle apprend."],
    ["Validation (val)", "Les images avec lesquelles on compare et on décide : yolo26n ou yolo26s, quelle préparation d'image, quelle variante. On peut les regarder autant de fois qu'on veut. Tous les chiffres affichés partout sont ceux de la validation."],
    ["Test", "Des images qui n'ont servi à aucun choix. Il est scellé : il ne s'ouvre qu'une fois, à la fin."],
  ]],
  ["Pourquoi garder un test scellé", [
    ["Le risque", "Chaque fois qu'on choisit « le meilleur » en regardant la validation, on s'adapte un peu à ses images. Avec peu d'images, un choix qui semble meilleur peut n'être qu'un coup de chance : la validation devient trop optimiste."],
    ["Ce que protège le test", "Parce qu'il n'a servi à aucun choix, il est le seul à dire ce que vaut le modèle sur des images jamais vues. Le sceller empêche de s'en servir par inadvertance : l'ouverture est volontaire et comptée."],
  ]],
  ["Quand on l'ouvre", [
    ["Une seule fois, à la fin", "Quand les étiquettes sont jugées assez fiables (définition de « place perçue », accord entre annotateurs mesuré), que les données sont arrêtées (corrections décidées, annotation complémentaire intégrée) et que les modèles retenus sont fixés."],
    ["Si on change après l'avoir ouvert", "Le test ne vaut plus rien : il faut alors un nouveau lot. L'ouverture est réservée à l'administrateur."],
    ["Aujourd'hui", "Le test n'a jamais été ouvert. Tous les chiffres du livrable sont des chiffres de validation, donc un peu optimistes."],
  ]],
  ["Lire les mesures", [
    ["Rappel (d'une catégorie)", "Parmi les images de cette catégorie, la part que le modèle a retrouvées."],
    ["Précision (d'une catégorie)", "Parmi les images que le modèle a rangées dans cette catégorie, la part qui y était vraiment."],
    ["Rappel moyen", "La moyenne des rappels, chaque catégorie comptant autant. C'est la mesure principale. À comparer au hasard : 1 ÷ nombre de catégories (0,33 pour 3, 0,50 pour 2)."],
    ["Réponse triviale", "Répondre toujours la catégorie la plus fréquente (par exemple « aucune place »). Le gain est l'écart entre le modèle et cette réponse. Une exactitude qui ne la dépasse pas n'apporte rien."],
    ["Matrice de confusion", "Lignes : la vraie catégorie. Colonnes : celle que le modèle a prédite. La diagonale, ce sont les bonnes réponses ; le reste, ce que le modèle confond avec quoi."],
    ["Catégorie non fiable", "Moins de 20 images dans le lot mesuré : une image de plus déplace le chiffre de 5 points ou plus."],
    ["Graines", "L'entraînement n'est pas reproductible à l'identique. On compare donc des moyennes sur 3 graines ; un écart plus petit que l'écart entre graines est du bruit."],
  ]],
  ["Les mots de l'interface", [
    ["Essai", "Un entraînement : un jeu de données, un modèle, des réglages et une graine."],
    ["Famille", "Le type de modèle : « yolo_cls » entraîne YOLO classify ; « jouet » éprouve la chaîne sans GPU. Les augmentations sont dans les « réglages »."],
    ["yolo26n et yolo26s", "Deux tailles du même modèle (n : petit, s : un peu plus grand). La consigne demande de les comparer."],
    ["Préparation de l'image", "« Rognage » garde la moitié du côté étudié ; « masque » noircit l'autre moitié ; « aucune » garde l'image entière."],
    ["Rééquilibrage", "Des copies d'images de la petite catégorie sont ajoutées au lot d'entraînement seulement, jusqu'à une part (le « rapport ») de la plus grande. Jamais en validation ni en test."],
    ["Où sont le modèle et les données ?", "Le modèle d'un essai : bouton « Télécharger le modèle » sur la page de l'essai. Les modèles retenus, avec leurs listes d'images par lot : onglet Livrable. Les jeux de données : onglet Données (manifeste, recette, contrôles)."],
    ["Mettre à jour les données", "On construit un nouveau jeu depuis l'onglet Données (réservé à l'administrateur), on relance les essais, puis on refait le livrable."],
  ]],
];

function pageAide(zone) {
  zone.replaceChildren(
    h("div", { class: "entete" }, h("div", {}, h("h1", {}, "Aide"), h("p", { class: "doux" }, "Comment lire les chiffres, et pourquoi le lot de test reste scellé."))),
    h("div", { class: "carte aide" }, ...TEXTES_AIDE.flatMap(([titre, termes]) => [h("h2", {}, titre), h("dl", {}, ...termes.flatMap(([t, d]) => [h("dt", {}, t), h("dd", {}, d)]))])));
}
