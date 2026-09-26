# L'Atelier comme hébergement de ce que l'on produit

> **État au 26/09/2026.** Non construit (jalon J8) : `atelier_artefact_proposer` et `/v1/capacites` n'existent pas. Ce qui existe des créations : [`atelier-applications.md`](atelier-applications.md) et [`fonctionnalites.md`](fonctionnalites.md) §7.

Proposition du 25/09/2026, **à valider**. Elle prolonge
`docs/atelier-applications.md` (artefacts autonomes et serveur, déjà en
service) et `docs/archives/chantiers/lecteur-grist-application.md` (première application
complète).

## L'idée en une phrase

Un projet de l'Atelier est un dépôt git qui contient du code **et ce que ce
code fait tourner** : pages, applications, services. L'Atelier les héberge, les
garde en vie, les sauvegarde, les fait entretenir par des agents et des
routines, et leur prête ses capacités (outils, compositions) — sans jamais
confondre ce qu'un agent est en train d'écrire avec ce qui est en production.

## 1. Un seul vocabulaire

| Mot | Ce que c'est | Où ça vit |
|---|---|---|
| **Projet** | un dépôt git | `~/work/projects/<projet>/` |
| **Artefact** | ce que le projet montre : une adresse | `artifacts/<nom>/` + `artefact.json` |
| — *page* | des fichiers, sans processus | le dossier lui-même |
| — *service* | un processus que l'Atelier lance et relaie | code dans le projet, déclaré par `artefact.json` |
| **Données** | ce que l'artefact produit en tournant | `artifacts/<nom>/donnees/`, hors git, sauvegardé |
| **Version** | l'état du code qui tourne en production | une étiquette git `prod/<nom>/<n>` |
| **Entretien** | ce qui vérifie et soigne l'artefact | routines déclarées dans `artefact.json` |
| **Capacités** | ce que l'artefact peut demander à l'Atelier | liste déclarée, accordée par la personne |

Tout le reste (ports, processus, cookies, hôtes) est l'affaire de l'Atelier.

## 2. Brouillon et production : la règle qui rend tout viable

Aujourd'hui un artefact serveur tourne **depuis l'arbre de travail** : un agent
qui modifie le code modifie ce qui tourne. Pour de la production, c'est
intenable. D'où deux états :

- **Brouillon** : l'artefact tourne depuis l'arbre de travail. C'est ce que les
  agents utilisent pour développer et tester. Adresse
  `…/<projet>/<nom>/~brouillon/`.
- **Production** : l'artefact tourne depuis une **copie figée** du dépôt, prise
  à l'étiquette `prod/<nom>/<n>` (worktree git en lecture seule,
  `~/work/.atelier-prod/<projet>/<nom>/<n>/`). Adresse `…/<projet>/<nom>/`.
  Ses **données** ne sont pas dans la copie : elles restent dans
  `artifacts/<nom>/donnees/`, partagées d'une version à l'autre.

**Promouvoir** = créer l'étiquette suivante et basculer la production dessus,
après les vérifications déclarées (tests, santé du brouillon). **Revenir en
arrière** = rebasculer sur l'étiquette précédente, en une action. Les données
sont sauvegardées avant chaque bascule.

Qui promeut : **la personne**, depuis l'interface. Un agent peut *proposer* une
promotion (elle apparaît avec son résumé et ses résultats de tests), jamais la
faire. Une routine peut être autorisée explicitement à promouvoir un
artefact précis si tous ses contrôles passent — c'est un choix, pas le défaut.

## 3. Deux niveaux d'hébergement

La même déclaration `artefact.json` sert aux deux ; seul l'endroit change.

| | **Dans l'Atelier** | **Service dédié** |
|---|---|---|
| Où | le pod de l'Atelier, processus supervisé | un pod à lui (release Helm dans le namespace), volume à lui |
| Pour | outils personnels, prototypes, apps d'usage courant | production sérieuse, exposition publique, charge |
| Isolation | celle d'un processus : même utilisateur Unix que les agents | celle d'un pod : ni les fichiers ni les secrets de l'Atelier |
| Adresse | `…-atelier-apps…/<projet>/<nom>/` | son propre hôte `…-<nom>.user.lab.sspcloud.fr` |
| Accès | le propriétaire, derrière l'Atelier | selon l'application (ACL, OIDC), ou derrière l'Atelier |
| Coût | aucun pod de plus ; arrêt sur inactivité | un pod qui tourne |

Passer de l'un à l'autre est une action de l'interface (« Héberger à part ») :
l'Atelier produit la release (image générique Python/Node + code de la version
+ volume), la déploie avec ses droits Kubernetes, et garde l'artefact dans son
panneau. C'est aussi la réponse honnête à la limite actuelle : **dans le pod de
l'Atelier, une application peut lire les fichiers du pod** ; tout ce qui doit
être isolé, partagé ou public va en service dédié.

## 4. Capacités : quand une application se sert de l'Atelier

Une application peut vouloir lancer une composition, appeler un outil d'un
connecteur, demander une tâche à un agent. Elle ne reçoit **jamais** la clé
owner. Elle déclare ce dont elle a besoin :

```json
"capacites": [
  {"type": "composition", "nom": "relancer_la_veille"},
  {"type": "outil", "nom": "grist__list_records", "limite_par_heure": 120},
  {"type": "agent", "projet": "creso", "consigne_max": 2000}
]
```

- À la première promotion (ou à tout changement de la liste), l'Atelier montre
  un **écran de consentement** : cette application demande ceci. La personne
  accorde tout, une partie, ou rien. Rien n'est accordé d'office.
- L'Atelier donne à l'application un **jeton de capacité** (variable
  `ATELIER_APP_JETON`, jamais écrit sur disque dans le projet), valable pour
  cet artefact, cette version et cette liste. Il se renouvelle à chaque
  démarrage et se révoque depuis l'interface.
- L'application appelle `ATELIER_APP_API` (`/v1/capacites/…` sur l'adresse
  locale de l'Atelier) ; chaque appel est vérifié contre la liste, limité en
  débit, et **journalisé** (qui, quoi, quand, résultat), consultable dans le
  panneau.
- En service dédié, même principe, par l'adresse interne de l'Atelier et
  une NetworkPolicy qui n'ouvre que ce chemin.

Pour un agent, c'est une ligne dans `artefact.json` ; pour la personne, c'est
une page qui dit en clair ce que l'application peut faire en son nom.

## 5. Entretien : agents et routines

Chaque artefact déclare son entretien ; l'Atelier l'exécute avec les routines
qu'il a déjà (coordinateur wikichat) :

```json
"entretien": {
  "sante": {"toutes_les_min": 5},
  "tests": {"commande": ["pytest", "-q"], "avant_promotion": true},
  "sauvegarde": {"quotidienne": true, "garder": 14, "vers": "s3"},
  "dependances": {"hebdomadaire": true},
  "github": {"ci": true, "alertes_securite": true},
  "en_cas_d_echec": "proposer"
}
```

- **Santé** : sondée ; trois échecs → redémarrage ; l'historique s'affiche.
- **Tests** : lancés sur le brouillon avant toute promotion ; une promotion
  refusée dit pourquoi.
- **Sauvegardes** des données vers le stockage S3 du SSPCloud (MinIO), pas
  seulement le volume du pod ; restauration depuis l'interface.
- **Dépendances et GitHub** : état de la CI du dépôt, alertes Dependabot,
  dépendances en retard.
- **En cas d'échec** : `signaler` (une alerte dans l'Atelier) ou `proposer`
  (l'Atelier ouvre une conversation d'agent sur une **branche**, qui corrige et
  propose une promotion). Jamais de correction directe en production.

Les routines coûtent du modèle : chacune a un plafond (nombre de passes par
jour) et apparaît dans le panneau avec sa dernière exécution. C'est la leçon
des triggers de recherche qui tournaient toutes les 30 minutes sans que
personne ne le voie.

## 6. Exposition : trois gestes, jamais implicites

1. **Privé** (défaut) : le propriétaire seul, derrière l'Atelier.
2. **Partagé** : des personnes nommées. Soit l'application gère ses comptes
   (comme le lecteur Grist et ses ACL), soit l'Atelier gère des invités
   (évolution future de l'Atelier).
3. **Public** : service dédié, hôte propre, authentification de l'application
   (OIDC) ou lecture anonyme déclarée. Revue de sécurité exigée avant le
   premier passage public.

L'exposition est une action de la personne, avec un rappel de ce qui devient
accessible. Aucun agent ne l'active ; aucun outil ne publie un port sans
authentification (`onyxia__expose_public` reste interdit aux agents).

## 7. Ce que voit la personne

Un panneau **Applications** par projet, et une vue d'ensemble :

- une carte par artefact : type, état (brouillon / production v3), adresse,
  santé, dernière sauvegarde, CI, entretien, capacités accordées, niveau
  d'exposition ;
- actions : Ouvrir, Promouvoir, Revenir en arrière, Arrêter, Journal,
  Capacités, Héberger à part, Exposer ;
- une file de **propositions** des agents : promotion, correction, nouvelle
  capacité — chacune avec son résumé et ses preuves (tests, captures).

## 8. Ce que sait un agent

Dans le socle des consignes, une section courte :

- créer, faire tourner et tester en **brouillon** : `atelier_artefact_creer`,
  `_demarrer`, `_verifier`, `_journal` (existent) ;
- **proposer** : `atelier_artefact_proposer(nom, resume)` (promotion,
  correction, capacité) — nouvel outil ;
- déclarer l'entretien et les capacités dans `artefact.json` ;
- ne jamais promouvoir, exposer, accorder une capacité, ni toucher aux
  données de production ; lire les journaux de production pour diagnostiquer.

## 9. Sécurité : ce qui tient, ce qui reste

Tient : origine séparée pour tout contenu d'agent, garde anti-CSRF entre pods,
secrets par référence, environnement construit, ports attribués, capacités
consenties et journalisées, production figée par étiquette, données
sauvegardées hors du pod, exposition par geste explicite, service dédié pour
l'isolation.

Reste, et se dit :
- **dans le pod de l'Atelier**, applications et agents partagent l'utilisateur
  Unix : un artefact peut lire `~/work`. Remède : service dédié ;
- les routines et agents consomment du modèle : plafonds visibles ;
- un pod SSPCloud n'est pas un hébergement à haute disponibilité : une
  réplique, redémarrages possibles ; les sauvegardes S3 bornent la perte.

## 10. Ce qui existe déjà et ce qui manque

Existe : artefacts page et service, superviseur, relais HTTP/WS/SSE, hôte des
applications, outils `atelier_artefact_*`, secrets par référence, routines
wikichat, compositions et outils de la passerelle, droits Kubernetes du
namespace, première application complète (lecteur Grist).

Manque, par lots :

1. **Brouillon / production** : worktree figé par étiquette, promotion,
   retour arrière, sauvegarde avant bascule, adresses `~brouillon`.
2. **Données et sauvegardes** : `donnees/` hors git, sauvegardes S3 et
   restauration.
3. **Panneau et propositions** : cartes, file de propositions,
   `atelier_artefact_proposer`.
4. **Capacités** : déclaration, consentement, jeton, `/v1/capacites`,
   journal, limites.
5. **Entretien** : santé suivie, tests avant promotion, CI GitHub, dépendances,
   routines plafonnées, « proposer » sur branche.
6. **Service dédié** : image générique, release Helm, volume, NetworkPolicy,
   hôte propre, capacités par l'adresse interne.
7. **Exposition partagée et publique** : invités, OIDC, revue de sécurité (ici
   rejoint le lot L7 du lecteur Grist et la question d'un hôte séparé pour les
   widgets).

Ordre proposé : 1 → 2 → 3 d'abord (c'est ce qui rend la production sûre et
visible), puis 4 et 5, puis 6 et 7.
