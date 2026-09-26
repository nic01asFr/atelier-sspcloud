/*
 * Le thème, posé avant le premier rendu.
 *
 * Chargé de façon bloquante dans <head>, avant les feuilles de style : la page
 * s'affiche d'emblée dans le bon thème, sans éclair du thème par défaut. La
 * préférence fait foi côté service (`ui.theme`, voir `controllers/theme.js`) ;
 * ce navigateur en garde une copie pour l'appliquer ici, avant même d'être
 * connecté. Sans copie, ou si le stockage est refusé : le système décide.
 */
(function () {
  try {
    var choix = window.localStorage.getItem("atelier.theme");
    if (choix === "clair" || choix === "sombre") {
      document.documentElement.setAttribute("data-theme", choix);
    }
  } catch (e) {
    /* stockage indisponible : le thème du système */
  }
})();
