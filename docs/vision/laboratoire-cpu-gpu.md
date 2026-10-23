# Le laboratoire sur un pod CPU, l'entraînement sur un pod GPU

Le pod GPU s'éteint seul quand le GPU reste au repos (voir D-81). Le laboratoire — interface, validation, commentaires — ne doit pas s'éteindre avec lui : Mathieu doit pouvoir valider et commenter à toute heure.

## Le partage

| Pod CPU (toujours allumé) : le **laboratoire** | Pod GPU (à la demande) : le **travailleur** |
|---|---|
| file et registre des essais, résultats, test scellé | entraîne un essai à la fois |
| images brutes, construction des jeux de données | garde une copie des jeux qu'il a utilisés |
| validation humaine, commentaires, jetons | ne garde rien d'essentiel |
| `python -m laboratoire --maitre` | `python -m laboratoire.travailleur_gpu` |

Le travailleur **appelle** le laboratoire (un pod éteint ne reçoit rien) : il prend l'essai le plus ancien (`POST /api/travail/prendre`), télécharge le jeu de données si besoin, l'entraîne, donne signe toutes les 15 s (avec les métriques), envoie le journal au fil de l'eau, puis rend les fichiers de l'essai. Le test reste scellé : il arrive avec les fichiers et ne s'ouvre qu'au laboratoire, comptabilisé comme avant.

## Ce qui se passe quand ça tourne mal

- **GPU éteint** : les essais restent « en file » ; l'en-tête dit « GPU éteint · N essai(s) attendent ». Dès que le pod GPU est relancé, son travailleur reprend la file.
- **Réseau coupé en plein entraînement** : l'essai continue, ses fichiers restent sur le pod GPU et partent à la reprise du contact.
- **Pod GPU coupé en plein entraînement** : sans signe depuis 10 minutes, l'essai passe à « interrompu » (il peut être relancé).
- **Arrêt demandé** : transmis au travailleur à son prochain signe ; il arrête l'entraînement et rend ce qu'il a.
- **Adresse du laboratoire changée** (pod CPU relancé) : le fichier `maitre.url` du pod GPU la remplace, sans redémarrer le travailleur.

## Accès

Le jeton du travailleur (rôle « travailleur » dans `valideurs.json`) n'ouvre que `/api/travail/` ; les jetons des personnes n'y ouvrent rien. Une archive reçue ne crée que des fichiers ordinaires, sans chemin qui sorte du dossier de l'essai.
