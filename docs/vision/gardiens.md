# Les gardiens : garder l'écosystème cohérent et fiable, sans boîte noire

Vision du 25/09/2026, équipe « Agents gardiens et fiabilité continue ».
**À valider.** S'appuie sur `docs/vision/cadre.md`, `docs/atelier-hebergement.md`
(§5 Entretien), `docs/coherence-projet.md` (lots A à H),
`docs/structure-projet.md` (harnais par participant) et sur le coordinateur
wikichat (branche `atelier-coherence` : `triggers.mjs`, `routines.mjs`,
`dormant.mjs`, `lancement.mjs`, `lanceur-atelier.mjs`, `repo-audit.mjs`).

## État (vague 1, 25/09/2026, branche `gardiens`)

**Existe, testé en local, non déployé.** Ce qui suit la section « En une phrase »
reste la vision ; cette section dit ce qui en est construit.

| Pièce | Où | État |
|---|---|---|
| Exécuteur (ordonnanceur `toutes_les_min` et `cron`, un fil par gardien, délai borné par contrôle, une alerte par empreinte, homme mort au redémarrage et en cours de route, journal JSONL en ajout seul filtré des secrets, 0 jeton) | `atelier-src/mcp_gateway/gardiens/` (`python -m mcp_gateway.gardiens`) | testé (fixtures, et vrai processus contre des services factices) |
| Déclaration | `mcp_gateway/gardiens/gardiens.json` (schéma `id, gardien, portee, quand, commande, delai_s, si_constat, geste`, plus `params`, `actif`, `proposer` lu mais pas servi) ; `ATELIER_GARDIENS_DECLARATION` ou `~/work/projects/atelier-gardiens/gardiens.json` la remplacent | testé |
| Lancement | `install/atelier-init.sh`, `demarrer_gardiens` (détaché, `nice 10`, `~/work/logs/gardiens.log`) | écrit, non exécuté sur un pod |
| Interrupteurs | `ATELIER_GARDIENS=0` (ne démarre pas), `ATELIER_GARDIENS_GESTES=0` (aucun geste), `ATELIER_GARDIENS_HOOKS=0` (pas de pose du hook), un contrôle `"actif": false` | testé |
| G0 inventaire | `controles/automates.py` : triggers, routines et `routine-runs.jsonl` de wikichat, créations du superviseur, démons connus, tout autre processus qui écoute, contrôles des gardiens ; `sans_declaration` = trigger ou routine actif sans `budget`, ou processus qui écoute sans déclaration ; `absent` = démon connu qui n'écoute pas | testé |
| G1 santé | Atelier, relais, wikichat (sondes) ; créations (`GET /v1/apps`) ; CI de `main` (`gh` ou API, jeton jamais journalisé) ; code en service comparé à `main` (`ATELIER_COMMIT`, `/opt/atelier/VERSION`, git) ; disque | testé |
| Geste « relancer » | `gestes.py` : `relancer_atelier` (`atelier-relancer`, après 2 échecs **et** 5 min de silence), `relancer_wikichat` (`start_wikichat.sh`), `relancer_relais` (module du relais, détaché) ; 2 échecs de suite, 3 relances par heure au plus, avant et après au journal | testé avec un faux script |
| G2 sécurité | écoutes sur toutes les interfaces hors liste ; valeurs connues (`claude-env.sh`, `~/work/.secrets/`) cherchées dans `~/.claude.json`, réglages de code-server, `~/.claude/settings.json`, `mcp/*.json`, `mcp/effective/*.json`, `.mcp.json` et `.git/config` des projets, fichiers suivis des dépôts (motifs forts seulement) ; droits 0600 ; `claude` en bypass sans fiche | testé (droits : sous POSIX seulement) |
| Hook `PreToolUse` du socle | `garde_bash.py`, posé par l'exécuteur (`docs/consignes/socle.md`, « Hooks du socle ») | testé |
| API de lecture | `127.0.0.1:8791` (`ATELIER_GARDIENS_PORT`), GET seulement | testé |

**Contrat de l'API de lecture** (pour la page Gardiens, vague 2 ; tout en JSON,
horodatages ISO UTC `…Z`, aucune valeur secrète) :

| Route | Rend |
|---|---|
| `GET /sante` | `{ok, demarre_a, declaration, controles, interrupteurs: {gardiens, gestes, a_blanc}}` |
| `GET /etat` | `{controles: [{id, gardien, portee, quand, commande, delai_s, si_constat, geste, proposer, actif, source, derniere, prochaine, etat, secondes, echecs_consecutifs, en_cours}], alertes_ouvertes: [Alerte], interrupteurs}` |
| `GET /alertes[?toutes=1]` | `{alertes: [Alerte]}`, où Alerte = `{empreinte, controle, gardien, portee, objet, resume, preuve, niveau (attention\|alerte), depuis, vu_le, compte, ouverte, resolue_le?}` ; les alertes « homme mort » ont `controle: "gardiens.homme-mort"` et `objet` = le contrôle en retard |
| `GET /echeances` | `{echeances: [{id, gardien, prochaine, derniere, en_retard}]}`, par date |
| `GET /resultats?controle=<id>&n=<1..500>` | `{lignes: [Ligne]}` ; Ligne = une ligne du journal : `{quand, gardien, controle, portee, etat, constats: [{empreinte, objet, resume, preuve, niveau}], alertes: {nouvelles, resolues}, cout: {jetons: 0, secondes}, donnees?, action?: {type: "geste", nom, avant: {etat, preuve}, apres?: {etat, preuve}, script?: {script, code, sortie, secondes}, refuse?}}` |
| `GET /resultats/<id>` | `{controle, resultat: {etat, constats, donnees?}}` (le dernier, complet) |
| `GET /automates` | `{controle, lu_a, automates: [Automate], par_etat}` ; Automate au schéma de `coherence-croisee.md` §1.2, `etat` ∈ `actif\|coupe\|sans_declaration\|absent` (`absent` : démon connu qui n'écoute pas) ; champs en plus selon le genre : `titre`, `action`, `plafond_par_jour`, `lancements`, `etapes`, `dernier_resultat`, `ports`, `pid` |

Toute autre méthode : 405, sauf `POST /pilotage` (vague 2, ci-dessous). L'API
n'écoute qu'en `127.0.0.1` ; l'Atelier la lit côté serveur.

**Vague 2 (équipe V, branche `v2-vue-agents`) : les gardiens dans la vue Agents.**
Décision J-i : pas de page Gardiens. Chaque gardien est un agent spécifique de
la vue Agents (section « Gardiens » de la liste, fiche au clic) :

| Pièce | Où | État |
|---|---|---|
| Pilotage à chaud : lancer maintenant, couper, réactiver (un gardien entier ou un contrôle) ; une coupure survit au redémarrage (`coupes.json`) et ferme l'homme mort du contrôle ; un contrôle déclaré `"actif": false` ne se réactive pas d'ici | `executeur.py` (`lancer_maintenant`, `couper`, `reactiver`), `GET /etat` rend `actif` (effectif), `actif_declare`, `coupe` | testé |
| `POST /pilotage` `{action: lancer\|couper\|reactiver, gardien?\|controle?, par?}` : jeton `Authorization: Bearer` écrit par l'exécuteur à son démarrage (`<état>/pilotage.jeton`, 0600) ; refusé avec un `Origin` (navigateur) ou un `Host` non local ; 503 sans jeton (à blanc) | `api.py`, `__main__.py` | testé |
| Relais de l'Atelier : `GET /v1/gardiens` (un agent par gardien : état, contrôles, alertes ouvertes, derniers constats, échéances, gestes récents lus au journal unique), `GET /v1/automates` (gardiens, triggers et routines de wikichat, créations servies : dernière, prochaine, plafond, état), `POST /v1/automates/action` `{id, geste}` | `mcp_gateway/atelier/automates.py` | testé, vérifié dans Chrome contre un exécuteur factice |
| Droits : couper un gardien et activer une tâche automatique sont réservés à la personne (session de l'interface) ; lancer et réactiver, non ; chaque geste va au journal unique (`source: automate`) avec son acteur, refus compris | `automates.py` | testé |

**Exécution à blanc sur le pod (25/09, 20 h UTC, lecture seule).** L'exécuteur
n'est pas sur le pod ; les mêmes lectures ont été faites par des commandes
équivalentes, sans rien écrire ni afficher de valeur :

- G0 : 14 triggers wikichat, dont 8 actifs **sans budget** (`sans_declaration` :
  trois `spawn_session` quotidiens à `max_per_day` 24, `evt-wake-any`,
  `mention-supervisor`, `channel-insights`, `veille-depots-cron` sans
  expression cron, et `cron-routine-4h`) et 6 coupés ; la routine
  `paradox-research` (14 étapes, **27 passes en 7 jours**) sans budget ; pas
  de crontab ; aucune création supervisée en cours ; processus qui écoutent sans
  déclaration : `artifacts/cerveau/outils/serveur.py` (8082, lancé à la main,
  hors superviseur), le service voix (`uvicorn`, 18920), deux `http.server`
  (9999 et un port éphémère), tous en `127.0.0.1`.
- G1 : Atelier, relais et wikichat répondent 200 ; disque de `~/work` à 74 % ;
  CI de `main` **illisible depuis le pod** (dépôt privé, ni `gh` ni jeton
  GitHub sur le pod) ; commit en service **inconnu** (pod du catalogue Jupyter,
  `~/work/atelier-src` copié sans `.git` ni `VERSION`).
- G2 : `0.0.0.0:8000` (`ipykernel_launcher`) hors liste ; **une valeur connue en
  clair** (`ATELIER_MCP_N8N_AUTHORIZATION`) dans un fichier effectif
  `~/work/mcp/effective/394226a3-….json` (0644, du 25/09 13 h 55) ; **un jeton
  `ghp_` dans l'adresse du remote `origin`** de `projects/nouveau-projet`
  (`.git/config`) ; 20 dépôts, 1 070 fichiers suivis : rien ;
  `~/.claude/settings.json.avant-compaction` en 0644 ; aucun `claude` en
  bypass (une session `acceptEdits`, avec fiche).

**Reste** : G3 (cohérence), G4 (coût, origine au relais), G5 (propositions,
après le lot D), G6 (amélioration) ; le projet système `atelier-gardiens` (J-g) qui portera la
déclaration ; la routine « homme mort » côté wikichat (l'exécuteur vérifie
wikichat, pas encore l'inverse) ; les gestes « régénérer une configuration »
et « couper un automate » (côté gardien ; la personne le fait depuis la vue
Agents) ; fermer ou marquer les alertes d'un contrôle coupé (elles restent
ouvertes, figées) ; un geste « retenu » (gestes coupés) est journalisé à chaque
passage, ce qui charge le journal unique ; le recopiage de `routine-runs.jsonl` dans le
journal unique (§2 de `coherence-croisee.md`) ; les sondes `initialize` des
connecteurs, la tendance des fils, Ingress du namespace ; hooks git
pre-commit et pre-push.

## En une phrase

Un **gardien** est du code qui regarde, pas un agent qui réfléchit : quatre
gardiens (Santé, Sécurité, Cohérence, Entretien) font tourner des contrôles
déterministes, gratuits en modèle, écrivent tout dans un journal lisible, ne
font seuls qu'une liste fermée de gestes réversibles, et, quand il faut
réparer, **ouvrent une conversation ordinaire dans le projet, sur une
branche**, que la personne voit, plafonne et tranche.

---

## 1. Le problème, vu par la personne

Ce qui est arrivé ces dix derniers jours, et que personne n'a vu à temps :

| # | Ce qui s'est passé | Combien de temps sans que personne le voie |
|---|---|---|
| S1 | **Cinq déclencheurs de recherche** tournaient toutes les 30 minutes (48 lancements par jour chacun, sous le plafond par défaut de 100) ; désactivés à la main le 24/09 | des jours ; découverts par hasard |
| S2 | **Sessions relancées hors de l'Atelier** : un réveil wikichat reprenait une conversation par `claude -p --resume` en `bypassPermissions` codé en dur, sans fiche, sans secrets, et réécrivait le `.mcp.json` du projet, ce qui amputait les connecteurs des tours suivants | permanent jusqu'à la branche `atelier-coherence` |
| S3 | **États désynchronisés** : consigne du Lecteur Grist en retard de cinq lots sur le pod ; wikichat affichant « Projet sans nom » ; `nouveau-projet-2` marqué archivé alors que sa conversation vivait ; deux copies de travail poste/pod sans remote ; deux fiches pour un même fil | semaines |
| S4 | **Jetons en clair** : en-têtes `Authorization` recopiés dans les `.mcp.json` ; jeton n8n dans `args` ; PAT `ghp_` dans l'adresse d'un remote ; jeton de passerelle poussé sur GitHub ; après un redémarrage, l'ancien Atelier a réécrit `~/.claude.json` avec le pool en clair | jusqu'à l'audit manuel du 24/09 |
| S5 | **Services ouverts** : service voix sans authentification, WebTools sur `0.0.0.0`, serveurs montés par des agents (`findings/server.mjs`), `uvicorn` de la passerelle sur `0.0.0.0:8080` | jamais inventoriés |
| S6 | **CI de l'image cassée du 16 au 24/09** sur `main` (dépendance `mistune` non déclarée, test d'installation désaligné) : l'image publiée ne correspondait plus au code | neuf jours |
| S7 | **wikichat tué** par un `pkill -f "server.mjs"` d'agent (18/09) ; **Atelier bloqué** par 91 139 fils (17/09) ; **trigger de réveil muet 24 h** parce que les tests avaient épuisé son quota ; **n8n** affiché « local · N outils » alors que son jeton était refusé | heures à jours, toujours en silence |

Trois scénarios, vus par Nicolas :

1. *« Mardi matin, je trouve le pod lent. »* Rien ne lui dit que cinq
   automates lancent chacun 48 agents par jour. Il faut ouvrir
   `~/.wikichat/triggers.json` pour le découvrir. Il n'a aucune idée de ce que
   cela a coûté.
2. *« J'ai demandé la révocation d'un jeton hier ; est-il encore quelque part
   en clair ? »* Personne ne peut répondre sans un audit à la main de dix
   fichiers sur deux machines.
3. *« Ce que j'ai déployé hier, c'est bien ce qui est sur `main` ? »* La CI
   était rouge depuis neuf jours ; le déploiement se faisait en extrayant le
   code de l'image. Rien ne comparait les deux.

Le fil commun : **toutes ces pannes étaient silencieuses**, et presque toutes
étaient **détectables par une ligne de code** — sans modèle.

## 2. Ce qui existe déjà

### Dans l'Atelier et wikichat

| Brique | Ce qu'elle fait déjà | Ce qui lui manque pour être un gardien |
|---|---|---|
| Superviseur des applications (`apps/superviseur.py`) | sonde toutes les 30 s, trois échecs → redémarrage à attente doublée, `en_echec` après cinq redémarrages en dix minutes, plafond mémoire, orphelins tués après vérification de `cmdline` | journal hors de l'application, vue d'ensemble, alerte |
| `bin/atelier-verifier-coherence` | lance le vrai `claude` sur les trois surfaces, compare connecteurs et identifiants, sort 0 ou 1 | planification ; pas encore exécuté sur le pod |
| `mcp_secrets` | convertit en références, **signale** ce qu'il ne sait pas convertir (`<service>.args[N]`) | un endroit où ce signalement arrive |
| Relais LLM (`relais_llm.py`, `127.0.0.1:8790`) | voit passer **tous** les appels au modèle de toutes les surfaces, ne journalise que des nombres | savoir *qui* appelle (origine), cumuler |
| Triggers wikichat | cron avec rattrapage, `cooldown_s`, `max_per_day` compté sur les succès, `fire_count`, `last_fired`, interrupteur `WIKICHAT_TRIGGERS_DISABLED` | propriétaire, budget, coût, résultat, visibilité ; plafond par défaut (100/jour) trop haut |
| Routines wikichat | étapes, idempotence, journal `routine-runs.jsonl`, mode de permission lu dans la définition | coût, affichage |
| Dormant gate | ne tire rien sans session nommée | a produit l'effet inverse de la sobriété : la nuit rien, le jour tout, sans que personne ne sache pourquoi |
| `repo-audit.mjs`, `daemon-lifecycle.mjs`, `resilience.mjs` | santé d'un dépôt (git), réconciliation des démons, veilleur de sessions | ne remontent nulle part de visible |
| `publish-memory.mjs` | refuse de publier si un secret est détecté | le seul contrôle de secret automatique existant |
| `artefact.json` → `entretien` (proposé) | santé, tests, sauvegarde, dépendances, CI, `en_cas_d_echec` (`signaler` ou `proposer`) | l'exécuteur, le journal, le tableau |
| Harnais par participant | « Routine d'entretien : tests sur le brouillon, sonde de production, conversation sur une branche ; jamais `main` » | la même règle pour tout l'écosystème, pas seulement les artefacts |

### Standards et produits comparables

- **Sondes Kubernetes et boucle de réconciliation** : un état voulu déclaré,
  un contrôleur qui compare et converge. On reprend l'idée (déclaré → observé
  → écart), pas la convergence automatique.
- **Dependabot / Renovate** : proposent une PR, ne fusionnent jamais seuls.
  C'est exactement notre principe « proposer ».
- **GitHub secret scanning et push protection, gitleaks** : bloquer au
  moment du commit plutôt que chercher après.
- **Healthchecks.io, Uptime Kuma** : « homme mort » — un contrôle qui ne
  s'est pas exécuté quand il devait est lui-même une alerte.
- **Hooks natifs de Claude Code** (`SessionStart`, `PreToolUse`, `Stop`) :
  contrôles en ligne, sans modèle, identiques sur toutes les surfaces.
- **Budgets d'erreur (SRE)** : on ne cherche pas le zéro défaut, on rend le
  défaut visible et on borne sa durée.

## 3. La proposition

### 3.1 Trois règles qui empêchent la boîte noire

1. **Détecter, c'est du code ; réparer, c'est une conversation.** Un contrôle
   est un exécutable déterministe qui rend un JSON. Le modèle n'intervient
   jamais dans la détection ; il n'intervient que dans une **proposition**,
   qui est une conversation ordinaire du projet, visible dans l'Atelier, avec
   un plafond affiché.
2. **Tout automate est déclaré, affiché, et se coupe d'un geste.** Contrôle, trigger,
   routine, démon : s'il n'apparaît pas au tableau avec sa dernière
   exécution, son résultat, son coût et sa prochaine échéance, il n'a pas le
   droit de tourner. Un automate trouvé sans déclaration est lui-même un
   constat.
3. **Un constat = une alerte, pas un flot.** Chaque constat porte une
   empreinte (contrôle + objet + nature). Le même problème vu cinquante fois
   est une alerte avec un compteur, pas cinquante messages.

### 3.2 Les quatre gardiens

Le moins possible : quatre, parce que chacun a une **source de vérité
différente** et un **geste autorisé différent**. « Coût » et « réconciliation
des dépôts » ne sont pas des gardiens à part : le coût est une propriété de
tout automate (tenue par Entretien), la réconciliation des dépôts est un cas
de cohérence.

| Gardien | Question qu'il pose | Sources | Geste seul autorisé |
|---|---|---|---|
| **Santé** | Ce qui doit tourner tourne-t-il, et répond-il ? | sondes HTTP, superviseur, `ps`, `/proc`, API GitHub, Kubernetes du namespace | relancer par son script officiel un service tombé |
| **Sécurité** | Qu'est-ce qui est ouvert, en clair, ou plus permissif que déclaré ? | `ss -ltn`, empreintes des secrets du pool, fichiers de configuration, `.git/config`, Ingress, arguments des processus `claude` | régénérer une configuration depuis sa source ; arrêter une application *supervisée* qui s'expose sans déclaration |
| **Cohérence** | Les copies disent-elles la même chose que la source ? | `atelier-verifier-coherence`, `projet.json`, `ETAT.md`, empreinte du socle, fiches de conversation, `project-state.json` wikichat, remotes git | régénérer ce qui est **généré** (`contexte.md`, état wikichat dérivé) |
| **Entretien** | Qu'est-ce qui vieillit, grossit ou coûte ? | inventaire des automates, relais LLM, audits de dépendances, disque, journaux | couper un automate qui dépasse son budget |

#### Santé — contrôles, fréquence, budget

| Contrôle | Fréquence | Modèle |
|---|---|---|
| Atelier, relais LLM (`/_relais/sante`), wikichat (`/api/health`), passerelle MCP : répondent-ils ? | 1 min | 0 |
| Tendance fils, mémoire, descripteurs de ces processus (le 17/09 : 91 139 fils) | 5 min, alerte sur la pente, pas sur l'instant | 0 |
| Applications : lecture de l'état du superviseur, `en_echec` → alerte | 1 min | 0 |
| Connecteurs : `initialize` + `tools/list` sur chaque serveur du pool, stdio compris | 1 h et à chaque changement du pool | 0 |
| CI de `main` de chaque dépôt ayant un remote | 30 min | 0 |
| Image déployée = commit de `main` ? | quotidien et après déploiement | 0 |
| Dernière sauvegarde des `donnees/` de moins de 26 h | quotidien | 0 |
| Services du namespace (répliques, hôtes qui répondent 404) | 1 h | 0 |
| Triggers de service (réveil) : ont-ils encore du quota ? | 15 min | 0 |

#### Sécurité — contrôles, fréquence, budget

| Contrôle | Fréquence | Modèle |
|---|---|---|
| Écoutes réseau comparées à la liste déclarée (8787, 8788 ; 3777, 8790 et plage des applications en `127.0.0.1` seulement) | 5 min | 0 |
| **Valeurs connues** du pool et de `claude-env.sh`, cherchées par empreinte dans `~/.claude.json`, `mcp/effective/*.json`, `.mcp.json` des projets, réglages de code-server, `.git/config` | 15 min et après chaque liaison | 0 |
| Motifs de jetons (`ghp_`, `Bearer `, clés) dans l'index git | hook pre-commit et pre-push de chaque projet | 0 |
| Droits des fichiers de secrets (0600) | 1 h | 0 |
| Processus `claude` lancés en `bypassPermissions` sans déclaration | 5 min | 0 |
| Ingress et services publics du namespace comparés aux expositions déclarées | 1 h | 0 |
| Jetons signalés « à faire tourner » encore valides (n8n, Onyxia) | quotidien, rappel | 0 |

Le contrôle par **valeurs connues** est la pièce maîtresse : l'Atelier
détient la liste des secrets ; en chercher l'empreinte ailleurs ne donne
aucun faux positif et n'expose aucune valeur (on compare des hachages, on
n'affiche que le fichier et la clé).

#### Cohérence — contrôles, fréquence, budget

| Contrôle | Fréquence | Modèle |
|---|---|---|
| `atelier-verifier-coherence` (vrai binaire, surfaces comparées) | quotidien et après déploiement | 0 |
| Toute conversation vivante a une fiche ; une seule fiche par fil ; aucun `claude` lancé hors Atelier | 5 min | 0 |
| Projet : `CLAUDE.md` suivi, `ETAT.md` pas plus vieux que le dernier commit de code de N jours, empreinte du socle à jour, `contexte.md` récent | quotidien | 0 |
| wikichat dit du projet ce que dit le dépôt (titre, décisions, état) | quotidien | 0 |
| Dépôts : commits non poussés depuis plus de 3 jours, copie sale depuis plus de 3 jours, projet sans remote, branches divergentes poste/pod (vues **par le remote**, seul canal entre les deux) | quotidien | 0 |
| Registre des projets : archivé avec une conversation vivante, projet vide depuis 30 jours | quotidien | 0 |

#### Entretien — contrôles, fréquence, budget

| Contrôle | Fréquence | Modèle |
|---|---|---|
| Inventaire des automates (triggers, routines, démons wikichat, crons, contrôles) : chacun a propriétaire, budget, dernière exécution | 15 min | 0 |
| Consommation par origine, lue au relais LLM ; plafond par automate, par gardien, global | continu | 0 |
| Tour d'agent anormal (plus de 100 000 jetons dans un tour : la dérive du 17/09) | continu | 0 |
| Dépendances : `pip-audit`, `npm audit`, alertes Dependabot, versions du CLI par surface | hebdomadaire | 0 |
| Disque du PVC, journaux qui grossissent (`librarian.log` à 269 Mo) | quotidien | 0 |
| Résumé de la semaine | lundi 8 h | 0 (gabarit en code) |

**Le seul usage du modèle** dans toute la strate : les propositions (§3.3),
plafonnées par défaut à **3 par jour, une à la fois par projet, 150 000 jetons
chacune**, le petit modèle pour un diagnostic, le grand pour une correction
de code. Au-delà du plafond, une proposition redescend en simple signalement.

### 3.3 Le principe d'action : une échelle, jamais sautée

```
  observer ──► signaler ──► geste réversible ──► proposer ──► la personne décide
  (toujours)   (toujours,     (liste fermée,       (branche +      (promouvoir, fusionner,
               une alerte     déclaré par          conversation    révoquer, exposer,
               par empreinte) contrôle)            dans le projet) accorder, couper)
```

- **Observer** : chaque exécution écrit une ligne au journal, même « rien à
  signaler ».
- **Signaler** : une alerte au tableau, dans `.atelier/contexte.md` du projet
  concerné (l'agent la voit au prochain `SessionStart`), et une note wikichat
  sur le canal du projet. Couleurs : *attention* (se dégrade), *alerte* (cassé
  ou exposé).
- **Geste réversible** : seulement ceux de la liste ci-dessous, seulement si
  le contrôle le déclare, toujours journalisé avec l'état avant et après.
- **Proposer** : le gardien ouvre, **par l'Atelier** (`atelier_ouvrir` /
  `atelier_envoyer`, lot D), une conversation dans le projet concerné, sur une
  branche `gardien/<gardien>/<AAAA-MM-JJ>-<sujet>`, avec un brief court : le
  constat, la preuve (extrait de journal, sans secret), ce qui est attendu,
  la commande de vérification. L'agent corrige, lance `/verifier`, s'arrête.
  La proposition apparaît dans la file des propositions (hébergement, lot 3).
- **La personne décide** : fusionner, promouvoir, révoquer, ignorer (avec
  motif et échéance).

#### Ce qu'un gardien a le droit de faire seul (liste fermée)

| Geste | Pourquoi c'est sûr |
|---|---|
| Relancer wikichat, le relais LLM, une application supervisée, par **leur script officiel** (`start_wikichat.sh`, `python -m …relais_llm`, superviseur), après N sondes ratées | le service est déjà mort ; le script est le même qu'à l'installation |
| Relancer l'Atelier (`atelier-relancer`) s'il ne répond plus depuis 5 min | il ne sert déjà plus personne ; les tours en cours sont perdus de toute façon |
| Régénérer une configuration depuis sa source (`materialize_mcp_config`, `claude-env.sh`, `contexte.md`, état wikichat dérivé) | la source fait foi ; l'opération est idempotente ; c'est ce qui a réparé le `~/.claude.json` réécrit en clair |
| Couper (désactiver, pas supprimer) un automate qui dépasse son budget ou n'a pas de déclaration | réversible d'un geste ; le coût s'arrête |
| Arrêter une application **lancée par le superviseur** qui écoute hors de ce qui est déclaré | le superviseur sait que c'est la sienne |
| Mettre un projet en tête de file « à relire » | aucun effet sur le code |

#### Ce qu'un gardien n'a jamais le droit de faire

- écrire sur `main`, pousser, fusionner, promouvoir, revenir en arrière ;
- exposer, retirer une exposition déclarée, accorder ou retirer une capacité ;
- révoquer ou faire tourner un jeton (il prépare la liste ; la personne agit) ;
- supprimer quoi que ce soit : projet, branche, données, conversation, fichier ;
- tuer un processus qu'il n'a pas lancé ou que le superviseur ne connaît pas,
  et jamais par motif (`pkill -f`) : c'est ainsi que wikichat est mort ;
- lire, afficher ou journaliser la valeur d'un secret (empreintes seulement) ;
- lancer quoi que ce soit en `bypassPermissions` ;
- modifier une consigne, un gabarit, un hook ou un autre gardien autrement
  que par une proposition ;
- relever son propre budget ou sa propre fréquence.

Ces interdits sont **tenus par construction**, pas par consigne : les gestes
sont des fonctions nommées de l'exécuteur ; un contrôle ne rend qu'un JSON et
n'a aucun moyen d'agir lui-même.

### 3.4 Où ça vit

```
             ┌──────────────── projet « atelier-gardiens » (dépôt git, projet Atelier ordinaire) ───────────────┐
             │ gardiens.json        déclaration des contrôles transverses (pod, Atelier, wikichat, dépôts)      │
             │ controles/*.py|mjs   un exécutable par contrôle, testé ; rend {etat, constats[]}                  │
             │ ETAT.md              l'état du parc, réécrit par le résumé hebdomadaire                            │
             │ docs/decisions/      alertes acceptées (« ignorer jusqu'au … parce que … »)                        │
             └───────────────┬──────────────────────────────────────────────────────────────────────────────────┘
                             │ lu par                              projets : artefact.json « entretien »
                             ▼                                     et .atelier/projet.json ──┐ (même schéma,
  ┌────────────────── exécuteur des gardiens (processus à part, comme le relais) ──────────┐ │  dérivé par
  │ ordonnanceur · exécute les contrôles · applique la liste fermée de gestes ·            │◄┘  l'Atelier)
  │ dédoublonne par empreinte · écrit le journal · homme mort                              │
  └──┬───────────────┬──────────────────┬──────────────────────┬───────────────────────────┘
     │ journal        │ alertes           │ propositions           │ surveille et est surveillé
     ▼                ▼                   ▼                        ▼
  ~/work/.atelier-   Atelier : tableau   Atelier : atelier_ouvrir  wikichat (routine « homme mort »
  etat/gardiens/     « Gardiens »,       sur branche gardien/…,    vérifie l'exécuteur ;
  journal/*.jsonl    contexte.md,        file de propositions      l'exécuteur vérifie wikichat)
                     note wikichat
     En ligne, sans exécuteur :  hooks Claude Code (SessionStart : alertes ; PreToolUse : refus de
     `pkill -f`, d'écriture d'un secret connu, de bind 0.0.0.0 dans une commande) · hooks git
     (pre-commit, pre-push : secrets) · CI GitHub (tests, image, analyse de secrets)
```

- **Déclarer.** Un seul schéma, deux endroits. Les contrôles transverses vivent
  dans le projet dédié **`atelier-gardiens`**, un projet Atelier ordinaire
  (dépôt, `ETAT.md`, tests, branches) : les gardiens s'améliorent par le même
  processus que tout le reste. Les contrôles d'un projet sont **dérivés** de
  ce qu'il déclare déjà (`entretien` de `artefact.json`, commandes de
  `projet.json`) : un projet n'écrit pas de `gardiens.json`.

  ```json
  {
    "id": "securite.ecoutes",
    "gardien": "securite",
    "portee": "pod",
    "quand": {"toutes_les_min": 5},
    "commande": ["python3", "controles/ecoutes.py"],
    "delai_s": 20,
    "si_constat": "signaler",
    "geste": "arreter_application_supervisee",
    "proposer": null
  }
  ```
  ```json
  {
    "id": "sante.ci-main",
    "gardien": "sante",
    "portee": "depots",
    "quand": {"toutes_les_min": 30},
    "commande": ["python3", "controles/ci.py"],
    "si_constat": "signaler",
    "proposer": {"apres_h": 24, "modele": "grand", "budget_jetons": 150000}
  }
  ```

  Contrat d'un contrôle : un exécutable, sortie JSON
  `{"etat": "ok|attention|alerte", "constats": [{"empreinte", "objet", "resume", "preuve"}]}`,
  aucun effet de bord, délai borné. Il se teste comme n'importe quel code, y
  compris par mutation (« ce contrôle aurait-il vu S4 ? »).

- **Exécuter.** Un petit processus à part, `atelier-gardien`, lancé par
  `install/atelier-init.sh` comme le relais LLM, parce que **le gardien ne
  doit pas vivre dans ce qu'il garde** : le 17/09 l'Atelier ne répondait
  plus, le 18/09 wikichat était mort. Il n'est **pas soumis à la dormant
  gate** : un contrôle en code ne coûte rien, et c'est la nuit que les
  services tombent. Les propositions, elles, passent par l'Atelier.
- **Ce qui reste à wikichat** : les routines qui ont besoin d'agents
  (équipes de recherche, capitalisation), désormais **lancées par l'Atelier**
  (lot D, `WIKICHAT_LANCEUR=atelier`), donc visibles comme des conversations,
  et **inventoriées** par Entretien. Et une routine « homme mort » qui vérifie
  que l'exécuteur a bien écrit au journal dans les 10 dernières minutes.
- **Ce qui reste aux hooks et à la CI** : ce qui doit être bloqué *avant*
  plutôt que constaté *après* (secret dans un commit, `pkill -f`, écoute sur
  `0.0.0.0` dans une commande d'agent). Coût nul, même comportement sur
  toutes les surfaces.

- **Voir.** Une page **Gardiens** dans l'Atelier, lue aux mêmes sources que
  l'exécuteur :

  | Contrôle | Gardien | Portée | Dernière exécution | Résultat | Coût (semaine) | Prochaine | |
  |---|---|---|---|---|---|---|---|
  | Écoutes réseau | Sécurité | pod | il y a 2 min | ok | 0 | dans 3 min | Lancer · Couper · Journal |
  | CI de `main` (atelier-sspcloud) | Santé | dépôts | il y a 12 min | **alerte** depuis 9 j | 0 | dans 18 min | … |
  | Veille recherche (trigger `r-…`) | Entretien | wikichat | il y a 4 min | 48 lancements/jour, **sans budget** | 1,2 M jetons | dans 26 min | … |

  Au-dessus : les **alertes ouvertes** (une ligne par empreinte, depuis quand,
  combien de fois) et les **propositions en attente**. Un onglet **Automates**
  liste tout ce qui tourne tout seul, gardiens compris, avec les mêmes
  colonnes — c'est la réponse à S1.

- **Couper.** Trois niveaux, tous réversibles et journalisés : un contrôle,
  un gardien, tout (`ATELIER_GARDIENS=0`, sur le modèle de
  `WIKICHAT_TRIGGERS_DISABLED`). Un gardien coupé depuis plus de 7 jours est
  rappelé dans le résumé de la semaine. « Ignorer » une alerte exige un motif
  et une échéance, et devient une décision dans `atelier-gardiens/docs/decisions/`.

### 3.5 Le journal et la confiance

Une ligne par exécution, dans `~/work/.atelier-etat/gardiens/journal/AAAA-MM.jsonl`
(ajout seul, hors git, sauvegardé avec les `donnees/`) :

```json
{"quand":"2026-09-18T07:49:40Z","gardien":"sante","controle":"sante.wikichat",
 "portee":"pod","etat":"alerte","empreinte":"sante.wikichat:down",
 "preuve":"GET 127.0.0.1:3777/api/health : connexion refusée (3 sondes)",
 "action":{"type":"geste","nom":"relancer_wikichat","avant":"arrêté","apres":"répond 200"},
 "cout":{"jetons":0,"secondes":4.1}}
```

- **Traçable** : chaque geste a son avant/après ; chaque proposition a sa
  conversation, sa branche, ses commits (`Agent: gardien-sante`,
  `Conversation: …`, comme le prévoit `structure-projet.md`).
- **Sans secret** : les preuves passent par le même filtre que le relais (des
  nombres, des chemins, des noms de clés, jamais une valeur).
- **Homme mort** : un contrôle qui n'a pas écrit quand il devait est une
  alerte ; l'exécuteur et wikichat se surveillent l'un l'autre.
- **Résumable** : le résumé de la semaine est un gabarit rempli par le code,
  écrit dans `atelier-gardiens/ETAT.md`, affiché en tête de la page Gardiens
  et posté sur le canal wikichat de la personne. Exemple, sur la semaine
  du 15 au 21/09 :

  > **Cette semaine, vos gardiens ont** fait 14 212 contrôles (0 jeton).
  > Ils ont vu 4 problèmes : wikichat arrêté vendredi 7 h 48, **relancé seul en
  > 50 s** ; jeton n8n en clair dans 5 `.mcp.json`, **configurations
  > régénérées**, jeton encore valide : **à faire tourner par vous** ; CI de
  > `atelier-sspcloud` rouge depuis mercredi, **une proposition vous attend**
  > (branche `gardien/sante/2026-09-17-ci-main`, 62 000 jetons) ; `ETAT.md` du
  > Lecteur Grist en retard de 5 lots, signalé. Automates : 7 actifs, 212
  > lancements, 1,4 M jetons, dont 1,2 M pour « veille recherche » (aucun
  > budget déclaré : **coupé mercredi**, à réactiver ou supprimer).
  > Rien n'est coupé d'autre. Prochaine vérification complète : lundi.

### 3.6 L'auto-amélioration

Un gardien qui revoit le même *genre* de problème ne se contente pas de
signaler plus fort : il propose de le rendre impossible.

- **Détection de récurrence** (code) : une même *classe* d'empreinte (le
  contrôle, sans l'objet) vue sur **trois objets différents** ou pendant
  **deux semaines**, ou une alerte rouverte après une correction.
- **Proposition au bon endroit**, par la même voie (branche + conversation) :

  | Récurrence | Où va la proposition |
  |---|---|
  | Même erreur d'agent dans plusieurs projets | le **socle** des consignes (dépôt de l'Atelier) |
  | Même oubli à la création des projets | le **gabarit** de projet (`git_repos.py`) |
  | Même geste dangereux | un **hook** `PreToolUse` du socle |
  | Même panne qu'aucun contrôle n'a vue venir | un **nouveau contrôle** dans `atelier-gardiens` |
  | Alerte ignorée trois fois (faux positif) | le **seuil** ou la définition du contrôle lui-même |

- **Règle de clôture d'incident** : une correction n'est pas finie tant
  qu'elle n'apporte pas le contrôle ou le test qui l'aurait vue. C'est la
  leçon du 17/09 (« mesurer ce qui se dégrade avec le temps ») rendue
  systématique : chaque incident laisse un contrôle derrière lui.
- **Le gardien ne s'améliore jamais seul** : il ne touche ni à ses seuils,
  ni à ses consignes ; il propose, avec les occurrences en preuve.

### 3.7 Ce que voit l'agent

- Au démarrage (`SessionStart`), dans `.atelier/contexte.md` : les alertes
  **de son projet** (« `ETAT.md` en retard de 5 lots », « jeton en clair dans
  `.mcp.json` ») — il peut les traiter s'il est dans le sujet.
- Un outil en lecture, `atelier_gardiens_etat(projet)` : alertes, dernières
  exécutions, propositions ouvertes.
- Un outil `atelier_signaler(resume, preuve)` : un agent qui voit un problème
  hors de son sujet le dépose au journal au lieu de le corriger en passant.
- Il ne peut ni faire taire une alerte, ni couper un contrôle.
- Quand il *est* une proposition : un brief court (constat, preuve, attendu,
  commande de vérification), une branche, un plafond de jetons, et l'arrêt
  après `/verifier`.

## 4. Parcours types

**P1 — wikichat tombe pendant la nuit.** 7 h 48 : un agent lance
`pkill -f "server.mjs"`. Avec la strate, le hook `PreToolUse` refuse la
commande (motif non ancré) et l'agent reçoit « nomme le pid de ton propre
processus ». Si wikichat tombe quand même : trois sondes ratées → relance par
`start_wikichat.sh` → répond en 50 s → une ligne au journal. Nicolas le lit
dans le résumé du lundi ; il n'a rien eu à faire.

**P2 — un jeton réapparaît en clair.** L'Atelier redémarre sur une ancienne
version et réécrit `~/.claude.json` avec le pool. Dans les 15 minutes, le
contrôle des valeurs connues trouve l'empreinte d'un jeton dans ce fichier :
alerte rouge, régénération depuis la source (geste autorisé), second passage
propre. L'alerte reste ouverte avec « le jeton a été lisible en clair de
10 h 02 à 10 h 14 : à faire tourner ». Nicolas fait tourner le jeton et ferme
l'alerte.

**P3 — la CI casse.** Mercredi 16/09, 21 h 47, `image.yml` échoue sur `main`. 22 h 15 :
alerte au tableau et dans le contexte de toutes les conversations du dépôt de
l'Atelier. Jeudi 22 h : toujours rouge → le gardien ouvre une conversation
dans le projet, branche `gardien/sante/…-ci-main`, brief : « le job échoue sur
`ModuleNotFoundError: mistune` ; attendu : CI verte, rien d'autre ». L'agent
ajoute la dépendance, `/verifier`, s'arrête. Vendredi matin, Nicolas voit la
proposition, fusionne. Neuf jours deviennent un.

**P4 — un automate s'emballe.** Un agent de recherche enregistre cinq
triggers cron toutes les 30 minutes. Au quart d'heure suivant, l'inventaire
les trouve : pas de budget déclaré → attention au tableau, avec leur coût
réel lu au relais. Au premier dépassement du plafond global des automates →
coupés, alerte « réactiver avec un budget ou supprimer ». Rien n'a été
supprimé ; tout se réactive d'un clic.

**P5 — une session part hors de l'Atelier.** Un réveil lance
`claude -p --resume … --permission-mode bypassPermissions` sans fiche. Le
contrôle des processus le voit (identifiant de session sans fiche, bypass
non déclaré) : alerte avec le nom du déclencheur responsable. Après le lot D,
ce cas n'arrive plus ; le contrôle reste, pour prouver qu'il n'arrive plus.

**P6 — Nicolas lit son lundi.** Il ouvre l'Atelier : en tête, le résumé de la
semaine ; trois alertes ouvertes, deux propositions. Il en fusionne une,
ignore l'autre « jusqu'au 15/10, parce que le service voix est en refonte »
(décision enregistrée), coupe un contrôle trop bavard. Cinq minutes.

### Comment la strate aurait évité ce qui est arrivé

| Incident | Contrôle ou hook | Délai de détection | Suite |
|---|---|---|---|
| S1 triggers invisibles | Entretien : inventaire des automates + coût au relais | 15 min | coupé au dépassement, décision à la personne |
| S2 sessions hors Atelier en bypass | Cohérence : processus sans fiche ; Sécurité : bypass non déclaré | 5 min | alerte nommant le déclencheur ; le lot D proposé avec les occurrences |
| S3 états désynchronisés | Cohérence : `ETAT.md` vs commits, socle, wikichat vs dépôt, archivé-vivant, dépôt sans remote | 1 jour | régénération du dérivé ; proposition pour le reste |
| S4 jetons en clair | Sécurité : valeurs connues par empreinte ; pre-commit/pre-push | 15 min, ou bloqué avant le push | régénération ; rotation préparée pour la personne |
| S5 services ouverts | Sécurité : écoutes vs déclarées ; hook sur `0.0.0.0` | 5 min | arrêt si supervisé ; sinon alerte avec le processus et le projet |
| S6 CI rouge neuf jours | Santé : CI de `main` ; image déployée vs `main` | 30 min | proposition après 24 h |
| S7 wikichat tué | Santé : sonde ; hook `pkill -f` | 1 min, ou bloqué avant | relance seule |
| S7 Atelier 91 139 fils | Santé : tendance des fils | avant la saturation | alerte, puis relance s'il ne répond plus |
| S7 réveil muet 24 h | Santé : quota des triggers de service | 15 min | alerte ; proposition « les tests n'utilisent pas le trigger de production » |
| S7 n8n « local » mais refusé | Santé : sonde `initialize` des connecteurs | 1 h | alerte « jeton refusé » à la personne |
| Dérive d'agent à 105 000 jetons | Entretien : tour anormal au relais | pendant le tour | alerte dans la conversation |

## 5. Ce qu'il faut construire, par étapes démontrables

| Étape | Contenu | Démonstration | Dépend de |
|---|---|---|---|
| **G0 Inventaire** | projet `atelier-gardiens` ; format de journal ; exécuteur minimal (ordonnanceur, homme mort, interrupteur) ; onglet **Automates** qui lit `triggers.json`, `routines.json`, `spawn_registry.json`, crons | les cinq triggers de recherche réactivés sur un pod d'essai apparaissent avec 48 lancements/jour | — |
| **G1 Santé** | sondes Atelier, relais, wikichat, passerelle ; lecture du superviseur ; sonde des connecteurs ; CI et image vs `main` ; gestes de relance | `pkill` de wikichat sur le pod d'essai → relancé en moins de 2 min, une ligne au journal | G0 |
| **G2 Sécurité** | écoutes ; valeurs connues par empreinte ; droits ; bypass ; Ingress ; hooks pre-commit/pre-push et `PreToolUse` du socle ; geste de régénération | rejouer le `~/.claude.json` en clair et le jeton n8n dans `args` → alerte + régénération ; un `git push` d'un `ghp_` refusé | G0, lot A |
| **G3 Cohérence** | `atelier-verifier-coherence` planifié ; sessions sans fiche ; `ETAT.md`, socle, wikichat vs dépôt ; remotes et divergences | la liste D1–D15 du Lecteur Grist retrouvée automatiquement | G0, lots B et C pour la moitié des contrôles |
| **G4 Coût** | origine des appels au relais (`X-Atelier-Origine` : conversation, routine, gardien) ; plafonds ; tour anormal ; résumé de la semaine | le résumé de la semaine du pod réel, chiffres vérifiés à la main | G0, relais |
| **G5 Propositions** | branche + conversation par l'Atelier ; brief court ; plafonds ; file de propositions | CI cassée volontairement → proposition verte le lendemain, fusionnée par la personne | lot D (lancements par l'Atelier), hébergement lot 3 |
| **G6 Amélioration** | récurrence par classe d'empreinte ; propositions au socle, au gabarit, aux hooks, aux contrôles ; règle de clôture d'incident | trois projets sans `ETAT.md` → une proposition au gabarit | G5 |

G0 à G2 ne demandent **aucun modèle** et couvrent S1, S4, S5, S6 et S7.
C'est l'ordre recommandé : la visibilité d'abord, la sécurité ensuite, la
réparation assistée en dernier.

## 6. Risques, limites, questions à trancher

### Risques et limites

- **Fatigue d'alerte.** Une strate qui crie trop est ignorée, ce qui revient
  à ne pas en avoir. Parades : une alerte par empreinte, deux niveaux
  seulement, « ignorer » avec échéance, et l'auto-amélioration qui vise en
  premier les faux positifs.
- **Le gardien comme surface d'attaque.** Il lit tout et peut relancer des
  services. Parades : pas de modèle dans la détection (rien à injecter), des
  gestes nommés et fermés, les preuves filtrées comme au relais, le contenu
  des projets traité comme donnée dans les briefs de proposition.
- **Le gardien comme panne.** Un contrôle lent ou bloqué ne doit rien
  bloquer d'autre : délai borné par contrôle, `nice`, un contrôle à la fois
  par gardien, et l'homme mort.
- **Relances en boucle.** Une relance qui échoue trois fois s'arrête et
  devient une alerte, comme le fait déjà le superviseur (`en_echec`).
- **Un processus de plus** sur le pod. Justifié par le 17/09 : un gardien
  logé dans l'Atelier serait tombé avec lui.
- **Le poste local** (Windows, wikichat local, dépôts locaux) n'est vu qu'à
  travers les remotes git ; c'est cohérent avec l'architecture (« Git comme
  seul canal ») mais ne voit pas une copie jamais poussée.
- **Ce que la strate ne remplace pas** : la revue humaine avant exposition
  publique, la décision de révoquer, le jugement sur une promotion.

### Questions à trancher par Nicolas

1. **Où tourne l'exécuteur** : processus à part (recommandé, comme le relais),
   dans l'Atelier (plus simple, tombe avec lui), ou dans wikichat (existe
   déjà, mais c'est lui qui a été tué et il dort la nuit) ?
2. **La liste des gestes seuls** (§3.3) : en particulier la relance de
   l'Atelier et l'arrêt d'une application supervisée qui s'expose.
3. **Plafonds par défaut** : 3 propositions par jour, 150 000 jetons chacune ;
   plafond global des automates wikichat ; et abaisser `max_per_day` par
   défaut des triggers (100 aujourd'hui) avec un budget obligatoire à la
   création ?
4. **Un trigger créé par un agent naît-il désactivé**, en attente d'un clic ?
5. **La dormant gate** : la garder pour les routines à agents seulement, et en
   sortir les contrôles en code ?
6. **Notification hors de l'Atelier** pour une alerte rouge (sécurité,
   service de production tombé) : rien aujourd'hui ; faut-il un canal
   (courriel, notification mobile) ou le résumé suffit-il ?
7. **Le projet `atelier-gardiens`** : dépôt à part, ou dossier du dépôt de
   l'Atelier ? (À part : il vit au rythme de ses contrôles et sert d'exemple
   de projet entretenu.)

## 7. Évaluation

**Désirable.** Pour Nicolas d'abord : chacun des incidents de la semaine a
coûté des heures de diagnostic et aurait été vu en minutes. Pour un futur
utilisateur de l'Atelier installé depuis le catalogue : c'est ce qui rend
« héberger en production dans son pod » crédible — une application qui tombe
la nuit est relancée, un jeton en clair est vu, et on le lui dit en cinq
lignes le lundi. Pour les agents : ils reçoivent les alertes de leur projet
au démarrage et cessent de redécouvrir les mêmes pannes.

**Faisable.** Presque tout existe en pièces : superviseur, vérificateur de
cohérence, conversion des secrets, relais LLM qui voit tous les appels,
triggers et routines avec plafonds et journal, `repo-audit.mjs`, hooks
natifs, API GitHub, droits Kubernetes du namespace. Le neuf est petit : un
ordonnanceur, un format de journal, une dizaine de contrôles en Python, une
page. Les propositions attendent le lot D (lancements par l'Atelier) et la
file de propositions de l'hébergement.

**Viable.** Coût modèle de la détection : **zéro**. Coût de la réparation :
plafonné, affiché, et chaque jeton dépensé correspond à une proposition
visible. Coût pod : quelques secondes de CPU par cinq minutes. Maintenance :
les contrôles sont du code testé dans un projet ordinaire, et la règle de
clôture d'incident les fait grandir là où les pannes ont réellement eu lieu,
pas par anticipation.

**Cohérente avec les autres thèmes.** Même vocabulaire (projet, artefact,
production, proposition) ; même schéma `entretien` que l'hébergement ; mêmes
sources que la cohérence des surfaces (`projet.json`, `.mcp.json`,
`contexte.md`), et les lots A à D y deviennent des contrôles qui prouvent
qu'ils tiennent ; même harnais par participant (la « routine d'entretien »
de `structure-projet.md` est ici généralisée à l'écosystème) ; production
séparée du brouillon (un gardien ne touche jamais la production, il propose
sur une branche) ; sobriété (plafonds affichés, principe 6 du cadre).
