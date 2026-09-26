# Vision de l'Atelier — cadre de la réflexion

Document de cadrage du 25/09/2026, commun aux équipes de réflexion.

## L'idée

L'Atelier devient un écosystème personnel qui se construit avec lui-même :
on y crée des apps, des artefacts interactifs, des services MCP et des
extensions de l'Atelier ; on les voit et les manipule directement à côté de la
conversation ; on les publie en production et on continue de les piloter
depuis l'Atelier ; elles peuvent se servir de l'Atelier (outils, compositions,
agents) ; une couche d'agents gardiens (routines, wikichat) garde l'ensemble
cohérent et fiable.

## Principes communs (toutes les équipes)

1. **Simple et lisible d'abord** : une personne non technicienne doit pouvoir
   comprendre ce qu'elle voit et ce qu'elle fait. Peu de mots, les mêmes
   partout (projet, artefact, application, service, production…).
2. **Natif et standard** : réutiliser les mécanismes de Claude Code et les
   standards (MCP, MCP Apps, iframes isolées, OAuth) avant d'inventer.
3. **Un seul modèle, plusieurs usages** : chercher la structure unique qui
   couvre le cas simple et le cas riche, plutôt qu'une solution par cas.
4. **Construire sur l'existant** : artefacts page/serveur et hôte des
   applications, superviseur, relais, secrets par référence, passerelle MCP et
   compositions, wikichat, lecteur Grist comme application témoin
   (`docs/atelier-applications.md`, `docs/atelier-hebergement.md`,
   `docs/structure-projet.md`, `docs/archives/chantiers/coherence-projet.md`,
   `docs/archives/chantiers/lecteur-grist-application.md`).
5. **Sûr par construction** : isolation d'origine pour tout contenu d'agent,
   consentement explicite pour ce qu'une app peut faire au nom de la personne,
   production séparée du brouillon, secrets jamais visibles.
6. **Sobre** : pas de consommation de modèle ou de ressources sans nécessité
   visible ; plafonds affichés.

## Format de rendu (chaque équipe)

Un document `docs/vision/<theme>.md` :

1. Le problème, vu par la personne (2-3 scénarios concrets).
2. Ce qui existe déjà (Atelier, standards, produits comparables).
3. La proposition : le modèle, ses éléments, comment ils s'emboîtent
   (schéma texte), ce que voit la personne, ce que voit l'agent.
4. Parcours types, du point de vue de la personne.
5. Ce qu'il faut construire, par étapes livrables et démontrables.
6. Risques, limites, questions à trancher par Nicolas.
7. Évaluation : désirable (pour qui, pourquoi), faisable (avec quoi), viable
   (coût, maintenance), cohérente avec les autres thèmes.
