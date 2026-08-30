# wikichat, version Atelier

L'Atelier s'appuie sur wikichat pour la coordination, la mémoire et les
agents : ce que la page Agents appelle un agent est un déclencheur wikichat,
et la page Connecteurs expose ses outils. Cette dépendance nous a demandé
quelques ajouts que le wikichat d'origine n'a pas de raison de porter.

Plutôt que de patcher le pod à la main — les correctifs y vivaient sans
versionnement, donc à un redéploiement près de disparaître — cette version
est tenue ici, avec le reste du service. **Le dépôt wikichat d'origine reste
inchangé** : ce dossier est un fork assumé, pas une modification en amont.

## Ce qui change

`src/pilote.mjs`, à partir de la version d'origine, avec trois ajouts :

| ajout | pourquoi |
|---|---|
| `scope.servers` dans `triggerToAgent` | La sélection d'outils y est rendue brute. Sans elle, rééditer un agent reconstruit ses outils depuis des noms nettoyés — et lui fait perdre son périmètre au passage. |
| `system_agents` dans l'aperçu | Le pilote ne retient que les déclencheurs cron qui lancent une session. Les autres agissent quand même : le réveil sur mention relance un agent hors ligne. Les taire rendait leurs effets inexplicables. |
| `params.kind` | Nature d'un agent, transmise à la création et relue à l'affichage. Sert de critère de secours au classement — l'Atelier se fonde d'abord sur l'origine (les agents installés par la plateforme portent un identifiant préfixé `team-`). |

## Déploiement

`deploy-patches/deploy_agent_ui.py` pousse ce fichier vers
`/home/onyxia/work/wikichat/src/src/pilote.mjs` en même temps que le reste du
service, et le vérifie par empreinte. Le service wikichat charge le pilote au
démarrage : un redémarrage est nécessaire pour qu'un changement prenne effet.

## Reprendre une version d'origine plus récente

Repartir du `src/pilote.mjs` d'origine et rejouer les trois ajouts ci-dessus.
Ils sont localisés et sans interaction entre eux : `triggerToAgent` pour deux
d'entre eux, `handlePiloteCreate` pour le troisième.
