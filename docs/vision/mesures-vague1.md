# Mesures de la vague 1

Équipe M, 25/09/2026, sur le pod `proj-claude-code-jupyter-python-0`, CLI 2.1.281.

Ce document lève les hypothèses de `decisions.md` (A-1, A-2, A-8) et de `coherence-croisee.md` §4
avant qu'on construise dessus. Chaque résultat est marqué **mesuré** (observé ici) ou **supposé**
(déduit, ou non essayé).

## 0. Protocole

- **Dossier jetable** : `/tmp/mesures-vague1/`, avec un `CLAUDE_CONFIG_DIR` jetable. Il est
  supprimé depuis. Rien n'a été modifié dans `~/.claude*`, le code ou les services, et rien n'a
  été redémarré.
- **Réglages** : un `--settings` reprend l'`env`, l'`apiKeyHelper`, le `model` et le
  `fallbackModel` du pod. Aucune valeur secrète n'a été lue ni affichée.
- **Assistant d'essai** : un `CLAUDE.md` de rôle de 600 caractères. Ses seuls outils sont les
  **23 outils réellement annoncés par la passerelle de l'Atelier** (`127.0.0.1:8787/mcp`, profil
  `tout` en `tool_exposure: discover`) :
  - 7 méta-outils ;
  - 2 compositions ;
  - 14 `atelier_*`.

  Le lancement se fait avec `--strict-mcp-config` et `--tools ""` : aucun outil natif.
- **Garde** : un hook `PreToolUse` note chaque appel et refuse toute écriture, y compris celles
  qui passeraient par `gateway_call_tool`. Il n'a jamais eu à refuser.
- **Observation** : un mandataire d'observation, placé devant le relais LLM (`:8790`), note par
  requête le modèle, `output_config`, `thinking`, les noms d'en-têtes et la valeur des seuls
  `X-Atelier-*`, ainsi que le temps au premier octet. Il ne note ni contenu ni clé.
- **Budget** : **60 appels `claude -p`**, le plafond, tous consommés. Le plafond n'a pas permis
  3 essais en M1 ni 5 en M2 : les effectifs réels sont indiqués dans chaque tableau. Ce sont des
  indications, pas des statistiques.
- **Biais connu (mesuré)** : un fichier `/tmp/CLAUDE.md` étranger de 12 Ko (les consignes du
  projet Lecteur Grist, daté du 24/09) est chargé par **toute** session Claude Code dont le
  dossier est sous `/tmp`. Il a donc été chargé dans tous les essais. Je l'ai laissé en place
  pour garder M2 et M3 comparables (voir §6).

## 1. Effort `xhigh` contre `medium` (qwen3-6-35b-moe)

### 1.1 Le `xhigh` du pod n'est jamais appliqué

| Configuration | `output_config` reçu au relais | Statut |
|---|---|---|
| Réglages du pod tels quels (`env.CLAUDE_CODE_EFFORT_LEVEL=medium` + `modelSettings` `xhigh`) | `{"effort":"medium"}` | mesuré |
| Mêmes réglages + `--effort xhigh` en ligne de commande | `{"effort":"medium"}` (39 requêtes sur 39) | mesuré |
| Réglages du pod **sans** `CLAUDE_CODE_EFFORT_LEVEL` | `{"effort":"xhigh"}` | mesuré |
| Champ `thinking` | absent dans toutes les requêtes (`MAX_THINKING_TOKENS=0`) | mesuré |
| Même comportement dans l'extension VS Code | même `settings.json`, donc probablement `medium` | supposé |

La variable d'environnement l'emporte sur `modelSettings` et sur `--effort`. **Sur le pod,
toutes les sessions qui lisent `~/.claude/settings.json` tournent en `medium`.** La ligne
`modelSettings` n'a aucun effet et induit en erreur.

### 1.2 Latence et qualité

Méthode :

- **Côté `medium`** : 4 essais par tâche. Ce sont les 20 essais de la première série, qui
  partaient en `medium` effectif (§1.1).
- **Côté `xhigh`** : 2 essais par tâche, obtenus sans la variable, plus 1 étalonnage sur E4.
- **Mesure** : temps depuis le lancement du processus (init du CLI environ 0,5 s), en médiane.

| Tâche | Premier texte, medium | Premier texte, xhigh | Durée totale, medium | Durée totale, xhigh | Qualité, medium | Qualité, xhigh |
|---|---|---|---|---|---|---|
| E1 « Qu'est-ce qui tourne parmi mes créations ? » (attendu : `atelier_artefacts`) | 1,23 s | 1,21 s | 3,24 s | 4,19 s | **0/4** : liste les compositions | **0/2** : une fois `atelier_artefacts` appelé, mais la réponse liste encore les compositions |
| E2 « Quels projets ai-je ? » (`atelier_projets`) | 1,26 s | 1,42 s | 3,28 s | 4,47 s | 4/4 | 2/2 |
| E3 Découper une demande en étapes et dire qui les fait (sans outil) | 2,39 s (une fois 18,8 s) | 3,13 s | 3,13 s (une fois 20,6 s) | 4,50 s | 4/4 acceptables | 1/2 : l'autre confie le code à l'Assistant |
| E4 Choisir quelle délégation traiter d'abord (sans outil) | 1,93 s | 1,71 s | 2,31 s | 2,11 s | 4/4 | 3/3 |
| E5 Trouver un jeu data.gouv (`find` puis `call`) | 1,38 s | 1,34 s | 4,79 s | 5,51 s | 4/4 | 2/2 (un appel en trop) |

Au niveau du relais, sur toutes les requêtes observées :

| | Premier octet (médiane, max) | Durée de requête (médiane, max) |
|---|---|---|
| medium, 71 requêtes | 0,66 s ; 0,99 s | 1,17 s ; 19,99 s |
| xhigh, 22 requêtes | 0,67 s ; 0,79 s | 1,37 s ; 4,34 s |

Tout ce qui suit est **mesuré** sur cet échantillon :

- `xhigh` ne change pas le premier jeton.
- Il allonge la durée de 0,2 à 1,4 s selon la tâche.
- Il n'améliore aucune réponse.
- Les 7,9 s de `assistant-role.md` ne viennent pas de l'effort, puisque le pod est en `medium`.
- Le seul écart de 18,8 s est apparu en `medium`. **Supposé** : c'est un pic de charge du
  service LLM.

**Mesuré aussi, et plus important que l'effort** : E1 échoue 6 fois sur 6. Le mot « créations »
(lexique S2) envoie le modèle vers `gateway_list_compositions`, parce que la description de
`atelier_artefacts` ne parle pas de « créations ».

## 2. Méta-outils réels (profil découverte)

- **Tâches** : 10 tâches, 2 essais chacune (au lieu de 5, à cause du plafond), effort `medium`
  effectif.
- **Réussite** : le bon outil est appelé et la réponse en vient. Pour un piège : au moins une
  recherche, puis une conclusion d'absence sans invention.

| Tâche | Chemin attendu | Réussites | Allers-retours (appels d'outil) | Durée | Remarque |
|---|---|---|---|---|---|
| T1 Jeux data.gouv « qualité de l'air » | `find` puis `datagouv__search_datasets` | 2/2 | 2, 2 | 5,0 s ; 5,2 s | |
| T2 3 derniers commits de `anthropics/claude-code` | `find` puis `github__list_commits` | 2/2 | 2, 2 | 6,8 s ; 6,8 s | |
| T3 Couches du projet QGIS ouvert | `find` puis `qgis__get_project_info` | 2/2 | 2, 2 | **58,8 s** ; 11,1 s | lenteur du service QGIS, pas du modèle |
| T4 Conversations ouvertes | `atelier_conversations` | 2/2 | 1, 1 | 6,2 s ; 7,3 s | |
| T5 Créations du Lecteur Grist et lesquelles tournent | `atelier_artefacts` | 2/2 | 2, 1 | 5,1 s ; 4,8 s | les deux réponses se contredisent sur l'état de l'artefact statique |
| T6 Projets de l'Atelier | `atelier_projets` | 2/2 | 1, 1 | 3,4 s ; 3,9 s | |
| T7 Base de connaissances wikichat sur OAuth | `find` puis `wikichat__search_knowledge` | 1/2 | 2, 3 | 4,3 s ; 8,3 s | essai 1 : deux recherches en français sans remonter `search_knowledge`, conclut à tort que l'outil manque |
| T8 Projets déclarés dans wikichat | `find` puis `wikichat__list_projects` | 1/2 | **0**, 2 | 3,0 s ; 7,5 s | essai 1 : conclut « pas d'outil » **sans chercher** |
| T9 Piège : météo à Marseille | recherche puis « absent » | 2/2 | 2, 2 | 4,0 s ; 3,8 s | renvoie vers Météo-France, sans rien inventer |
| T10 Piège : envoyer un fax | recherche puis « absent » | 1/2 | **0**, 1 | 2,1 s ; 2,7 s | essai 1 : conclusion juste mais **sans chercher** |
| **Total** | | **17/20 (85 %)** | 1 à 3 | | |

Décompte (mesuré) :

- **Réponses données sans chercher** : 2 (T8, T10).
- **Fausse absence après recherche** : 1 (T7).
- **Noms inventés ou refusés** : 0.
- **Appels sans nom** : 0.
- **Distracteurs choisis** : 0.

À comparer avec le mode catalogue indicatif du 25/09 (6/9, 67 %) : le modèle ne fabrique plus de
noms. Le reste des échecs tient à deux causes :

- **la recherche lexicale** : `gateway_find_tools` ne rend rien pour « carte » ou « météo », et
  « wikichat base de connaissances OAuth » ne remonte pas `search_knowledge`, dont la description
  est en anglais (mesuré) ;
- **la conclusion hâtive** : la confusion entre projets wikichat et projets de l'Atelier.

Ce qui passe par la passerelle (mesuré) :

- Le périmètre de recherche compte **231 outils** (connecteurs + wikichat).
- La passerelle annonce 23 outils, soit environ 12 400 caractères de schémas.

## 3. Variante : consigne forte dans le `CLAUDE.md`

Consigne ajoutée : « Ne conclus JAMAIS qu'une capacité manque sans avoir cherché (deux
formulations, dont une en anglais) ; n'appelle `gateway_call_tool` qu'avec un nom exact rendu par
la recherche. »

Faute de budget, la variante n'a été rejouée que sur les trois tâches faibles, 2 essais chacune.

| Tâche | Sans consigne (M2) | Avec consigne (M3) | Allers-retours M3 | Durée M3 |
|---|---|---|---|---|
| T7 Connaissances OAuth | 1/2 | **2/2** (une erreur d'arguments, corrigée seule au tour suivant) | 4, 3 | 8,2 s ; 5,0 s |
| T8 Projets wikichat | 1/2 | 1/2 (essai 2 : `atelier_projets`, puis « aucun » sans chercher dans wikichat) | 3, 1 | 9,1 s ; 4,1 s |
| T10 Piège du fax | 1/2 | **2/2** (2 à 3 recherches, FR puis EN) | 2, 3 | 4,1 s ; 4,8 s |
| **Total** | **3/6** | **5/6** | + 1 recherche par tâche | + 1 à 4 s |

Tout est **mesuré** :

- La consigne fait passer les réponses sans recherche de 2 sur 6 à 1 sur 6.
- Elle corrige la fausse absence de T7, parce que la seconde formulation en anglais trouve l'outil.
- Elle coûte environ un aller-retour et 1 à 4 s.
- Elle ne suffit pas pour la confusion entre projets wikichat et projets de l'Atelier.

La même consigne figure déjà dans les instructions de la passerelle : elle est plus efficace
**répétée dans le `CLAUDE.md`**.

## 4. Latence de l'oral

Le service `nouveau-projet-2/voice_service.py` **tourne déjà** (uvicorn, `127.0.0.1:18920`). Je
l'ai appelé tel quel, avec son jeton, sans le relancer.

Lecture du code (mesuré) :

| Élément | Valeur |
|---|---|
| STT | faster-whisper `small` int8, CPU, `beam_size=1` |
| TTS | Kokoro 82M (onnx) |
| Routes | `POST /tts`, `POST /stt` (énoncé entier), `WS /audio/stream/{id}` |
| Découpage du flux WebSocket | tranches fixes de **3,0 s** (`audio/buffer.py`) |
| Fin de phrase | heuristique sur la ponctuation ; **pas de VAD** (« remplacée par une VAD en 2b ») |

Chronométrage : phrase synthétisée par le TTS du service, puis transcrite 3 fois.

| Phrase | Audio | TTS | STT (3 essais) | Transcription |
|---|---|---|---|---|
| « Qu'est-ce qui attend ma validation ? » (36 car.) | 1,58 s | 0,62 s ; 0,60 s | 1,62 s ; 1,60 s ; 1,52 s | exacte |
| Demande de délégation (94 car.) | 5,67 s | 1,61 s ; 1,35 s | 1,71 s ; 1,21 s ; 1,36 s | « lecteur griste » au lieu de « Grist » |

Le STT prend **1,2 à 1,7 s** par énoncé (mesuré), pas les 0,8 s retenues dans
`assistant-harness.md` §4.9.

Chaîne jusqu'au premier mot, en sommant des mesures :

| Étape | Aujourd'hui (flux WS) | Avec VAD et `/stt` sur l'énoncé entier |
|---|---|---|
| Fin de parole → fin d'audio envoyé | jusqu'à 3,0 s (tranche) | environ 0,3 s (supposé) |
| STT | 1,2 à 1,7 s | 1,2 à 1,7 s |
| Texte → premier jeton (processus vivant) | environ 0,7 s | environ 0,7 s |
| Première phrase (environ 175 jetons/s) | 0,2 à 0,4 s | 0,2 à 0,4 s |
| TTS de la première phrase | 0,6 s | 0,6 s |
| **Premier mot, sans outil** | **environ 4,5 à 6 s** | **environ 3,0 à 3,7 s** |
| **Premier mot, avec un outil** (+1,5 à 2,5 s, cf. E2 et T4) | environ 6 à 8 s | **environ 4,5 à 6 s** |

- Le **premier mot en moins de 3,5 s** n'est tenable que sans outil, avec une VAD : c'est une
  somme de mesures, donc **supposé**.
- Avec un outil, la cible n'est pas tenable.
- L'**accusé en moins de 2 s** n'est tenable que par un son préenregistré. Il dépend alors de la
  VAD, pas du modèle (supposé).

## 5. Vérifications rapides (`coherence-croisee.md` §4)

| # | Affirmation | Résultat | Statut |
|---|---|---|---|
| A5 | Routes `/desktop`, `/canvas`, `/stream/{user_id}` de `blender-remote-mcp` | Elles existent sur `blender-remote-mcp:8100`, lues dans son `/openapi.json` sans jeton : **`/canvas` est un alias de `/desktop`** (bureau plein écran, auth par `?token=` ou cookie `blender_token`, `embed=1` « réservé à un futur hub », contrat d'iframe). **`/stream/{user_id}` est un flux MJPEG** : le porteur doit prouver son identité, l'identifiant du chemin ne suffit pas. noVNC écoute sur `:6080` dans le cluster. L'hôte public `user-nic01asfr-blender-remote-mcp` répond 404 : pas d'Ingress à ce nom | mesuré (contrat) ; rendu non essayé |
| A6 | n8n encadrable | L'éditeur (`user-nic01asfr-n8n…`, titre « n8n.io ») n'envoie **ni `X-Frame-Options` ni `frame-ancestors`**, seulement une `Content-Security-Policy-Report-Only` sans directive de cadre. Il est donc encadrable **sans** `N8N_CONTENT_SECURITY_POLICY`, mais aussi **par n'importe qui**. L'hôte `n8n-mcp` envoie `X-Frame-Options: DENY` | en-têtes mesurés ; iframe réelle dans Chrome et Firefox supposée |
| A8 | Plugins Claude Code dans le CLI 2.1.281 | `claude plugin marketplace add <dépôt git local>`, puis `install` et `list` : OK. La commande `/essai:bonjour` du plugin s'exécute en `-p`. **Avec `--strict-mcp-config`, le serveur MCP du plugin n'est pas chargé** : seule l'entrée de `--mcp-config` l'est. L'installation écrit dans les réglages **utilisateur** du dossier de config | mesuré (CLI) ; extension VS Code supposée |
| A9 | Porte dormante : « la nuit rien » | Sur 7 jours, `routine-runs.jsonl` compte 34 passages (tous `paradox-research`, trigger `cron-routine-4h`), dont **11 entre 0 h et 6 h** (heure de Paris), et 7 en échec. En mode `any-named`, toute session nommée enregistrée garde wikichat actif. La porte n'est **pas** une plage horaire | mesuré |
| A10 | `ANTHROPIC_CUSTOM_HEADERS` reçu au relais | `X-Atelier-Origine: mesure-vague1` est arrivé sur les 2 requêtes, à l'entrée du relais. Le relais le transmet tel quel à l'amont, mais **ne le lit ni ne le journalise** : il ne journalise aucun en-tête | mesuré en `-p` ; VS Code et wikichat supposés (même mécanisme d'env) |
| A12 | `UserPromptSubmit` avec `additionalContext` en `-p` stream-json | Un seul processus vivant, 2 tours, même `session_id` : le hook tourne **à chaque tour** (compteur à 2) et le modèle cite le contexte du tour (ARTICHAUT, puis BETTERAVE) | mesuré en `-p` ; VS Code supposé |
| A13 | Hôte des applications joignable | `https://user-nic01asfr-atelier-apps.user.lab.sspcloud.fr/_sante` renvoie **200** `{"status":"ok","service":"atelier-apps"}` ; `/` renvoie 404 ; écoute locale sur `:8788` | mesuré |

## 6. Ce que cela change

### `decisions.md`

- **A-1 (modèle, effort)**
  - Garder `qwen3-6-35b-moe` en **`medium`**, ce qui est déjà l'effort réel.
  - **Retirer `modelSettings.qwen3-6-35b-moe.effortLevel: xhigh`** du `settings.json` du pod :
    c'est une ligne morte, masquée par `CLAUDE_CODE_EFFORT_LEVEL`, et qui laisse croire à un
    réglage appliqué.
  - La mention « l'effort `xhigh` est mesuré avant tout changement » est levée : aucun gain en
    qualité ni en premier jeton, et +0,2 à 1,4 s de durée.
  - Les lenteurs ponctuelles (18,8 s) relèvent de la charge : l'accusé de l'Assistant ne doit
    pas dépendre du modèle.
- **A-2 (méta-outils)**
  - **Confirmée.** 17/20 avec les vrais méta-outils, zéro nom inventé, et 5/6 sur les cas
    faibles avec la consigne forte.
  - Le chargement par `list_changed` n'est **pas** nécessaire à ce stade.
  - Trois ajouts, par ordre d'effet :
    1. la **consigne forte** dans le `CLAUDE.md` de l'Assistant, formulée « deux formulations,
       dont une en anglais » ;
    2. une **recherche moins lexicale** dans `gateway_find_tools` : synonymes français dans les
       descriptions, ou l'option `qwen3-embedding-8b`, qui devient justifiée ;
    3. les **descriptions `atelier_*` alignées sur le lexique S2** : `atelier_artefacts` doit
       parler de « créations » (E1 : 0/6).
  - Désambiguïser aussi « projets » (Atelier) et « projets wikichat » dans les descriptions.
- **A-8 (voix)**
  - Aucun audio conservé, aucun accord à l'oral : inchangé.
  - Délais à corriger : l'**accusé en moins de 2 s** exige un son préenregistré déclenché par la
    VAD.
  - Le **premier mot en moins de 3,5 s** n'est tenable que **sans outil et avec VAD**. Avec un
    outil, viser **environ 5,5 s** après l'accusé.
  - Le STT pèse 1,2 à 1,7 s, et non 0,8 s.

### Le plan

- **Oral** (vague 3) : la **VAD** est le prérequis n° 1. Il faut remplacer les tranches de 3 s
  (`audio/buffer.py`) par un envoi de l'énoncé entier à la fin de la parole. Le second levier est
  le STT : `base` ou `tiny`, transcription partielle, ou GPU, à mesurer.
- **Passerelle** (vague 2) : recherche multilingue ou sémantique dans `tool_search.py`, et
  descriptions `atelier_*` au lexique S2.
- **Porte dormante** (J-c, A9) : ce n'est pas un garde-fou nocturne. Il faut une **plage horaire
  explicite** ou le plafond `max_per_day` (J-b). La question en attente sur `cron-routine-4h` a
  désormais un fait : 11 passages de nuit en 7 jours.
- **Panneau et hôte des applications** :
  - **A13** : l'hôte est levé, P0 peut s'appuyer dessus.
  - **A5** : pour le bureau Blender, le mandataire pose le cookie `blender_token` côté serveur,
    jamais `?token=` dans l'URL. `/stream` sert pour un aperçu MJPEG.
  - **A6** : n8n s'encadre déjà ; il faut au contraire **restreindre** son `frame-ancestors`
    aux hôtes de l'Atelier (contre le clickjacking), puis faire l'essai d'iframe réel (A7).
- **Extensions** (F6, F9, A8) :
  - un plugin apporte commandes et skills, mais **ses serveurs MCP ne passent pas en
    `--strict-mcp-config`**. Ils doivent entrer par le pool de l'Atelier ;
  - l'installation écrit dans les réglages utilisateur, en conflit avec le lien
    `~/.claude/settings.json` : préférer `--plugin-dir` ou une installation gérée par l'Atelier.
- **Compteur de coût** (G4, A10) : l'en-tête d'origine arrive. Il reste à faire lire et
  journaliser par `relais_llm.py` ce seul en-tête non secret : aujourd'hui, le relais n'en note
  aucun.
- **Contexte de vue** (A12) : le hook `UserPromptSubmit` suffit en `-p` stream-json, à vérifier
  dans VS Code.
- **Hygiène du pod**, hors périmètre de M, à confier aux gardiens :
  - **`/tmp/CLAUDE.md`** (Lecteur Grist, 12 Ko) contamine toute session lancée sous `/tmp`,
    dont les tests et harnais. À supprimer, et à comprendre : qui l'a écrit là le 24/09 ?
  - Note : l'Atelier et l'hôte des applications écoutent sur `0.0.0.0` (`:8787`, `:8788`), ce
    que l'Ingress impose, alors que le socle l'interdit ailleurs.

## 7. Limites

- Les effectifs sont petits : 2 à 4 essais par case, au lieu de 3 et 5 demandés, faute de budget
  sous le plafond de 60 appels.
- M3 n'a été rejouée que sur 3 tâches.
- La qualité d'E3 relève d'un jugement de relecture.
- Tous les essais ont chargé le `/tmp/CLAUDE.md` étranger (environ 3 000 jetons de contexte hors
  sujet).
- VS Code n'a été essayé nulle part : A8, A10 et A12 y restent supposés.
