# Archives

Ce dossier garde des traces de travail qui ont servi à construire l'Atelier
mais ne décrivent plus son état. On ne les met pas à jour : elles restent
lisibles pour comprendre d'où vient une décision. Pour l'état actuel, lire
[`../fonctionnalites.md`](../fonctionnalites.md) ; pour les décisions en
vigueur, [`../vision/decisions.md`](../vision/decisions.md).

| Dossier | Ce que c'est | Remplacé par |
|---|---|---|
| [`shell-unifie-2026-08/`](shell-unifie-2026-08/) | le cahier de conception et le plan d'implémentation du « shell unifié » (fin août 2026), première interface à vues | l'interface actuelle, décrite dans [`../fonctionnalites.md`](../fonctionnalites.md) et [`../ui/guide-interface.md`](../ui/guide-interface.md) |
| [`captures-interface-v1/`](captures-interface-v1/) | les captures de la première interface (v1) à quatre onglets (Code, Assistant, Connecteurs, Agents) et les conversations fictives qui ont servi à les prendre | les captures de [`../ui/apres/`](../ui/apres/) et celles de la vitrine ([`site/assets/captures/`](../../site/assets/captures/)) |
| [`mcp/`](mcp/) | le cadrage du registre MCP unifié, son plan d'août et la spécification d'alignement avec wikichat, écrits avant l'interface à sept vues et les profils d'accès | [`../fonctionnalites.md`](../fonctionnalites.md) §9 et §10, [`../vision/architecture-transverse.md`](../vision/architecture-transverse.md) |
| [`chantiers/`](chantiers/) | journaux de chantier : l'audit de cohérence des outils (25/09), le journal des lots A à H et des déploiements des 25 et 26/09 (procédures pod et retour arrière comprises), la conception de l'application Lecteur Grist, projet d'exemple | [`../fonctionnalites.md`](../fonctionnalites.md) §14, [`../installer.md`](../installer.md) |
| [`vision/`](vision/) | les documents de préparation de la vision (cadrages de l'Assistant, harnais, contexte, relecture grand public, cohérence croisée, mesures de la vague 1) et le plan d'implémentation par vagues avec son suivi | [`../vision/assistant-synthese.md`](../vision/assistant-synthese.md), [`../vision/decisions.md`](../vision/decisions.md), [`../../CHANGELOG.md`](../../CHANGELOG.md) |
| [`consignes/`](consignes/) | la consigne d'un fork HTTP de `chrome-devtools-mcp`, abandonné au profit du navigateur des agents intégré à l'Atelier | [`../navigateur-atelier.md`](../navigateur-atelier.md) |
| [`filtre-depot-memoire/`](filtre-depot-memoire/) | `filtre.mjs`, garde-fou d'un dépôt de mémoire de wikichat, produit par un agent lors d'un essai du 22/08/2026 ; il n'est importé nulle part dans l'Atelier et était resté à la racine par erreur | à porter dans le dépôt qu'il protège, puis à retirer d'ici |

Ces documents peuvent citer des chemins, des noms de vues ou des étapes qui
n'existent plus. Le code fait foi.
