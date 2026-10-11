# Cadrer les agents : espaces, intentions, communication, périmètre

> État au 11/10/2026. **Proposition**, non implémentée. Elle rassemble l'étude du jour (docs de vision,
> code, pod, expériences, décisions de permission, journal, projets réels) et prolonge
> [`harnais-et-serveur-mcp.md`](harnais-et-serveur-mcp.md). Les points **[à prouver]** sont lus mais
> pas essayés sur le pod.

## 1. Le constat

Presque tout ce qu'il faut existe, dans le code comme dans les docs : le catalogue de commandes, les
classes d'action, le superviseur d'applications, le navigateur de l'agent, la veille, les gardiens, le
mandataire Onyxia, les lancements bornés, la file « À valider ». Ce qui manque est **la mise en
œuvre à l'échelle de l'intention** : pour publier une page, l'agent assemble cinq appels, ignore que
le serveur ne redémarre pas seul après une modification, et choisit au jugé entre une application
locale et un pod. Pour appeler l'agent d'un autre projet, il n'y a pas de geste unique, ni de réponse
qui revienne. Les chiffres du journal le disent : 24 % de refus ou d'erreurs sur les commandes,
`montrer` en échec 13 fois sur 13, un jeton de confirmation périmé 14 fois de suite.

La règle de ce document : **l'agent ne devrait jamais avoir à assembler**. Le harnais lui donne, au
moment où la demande de la personne le justifie, le mode d'emploi, les limites et le geste en une
étape.

## 2. Les cinq structures à cadrer

### 2.1 Les espaces : dossier, dépôt, projet, session

Claude Code s'organise autour du dossier de travail : la chaîne des `CLAUDE.md` parents, les réglages
(`.claude/settings*.json`), les agents, skills et commandes du dossier, le `.mcp.json`, et la session
(son répertoire courant). L'Atelier et wikichat s'y adossent déjà. Voici ce qui est posé et ce qui
devrait l'être, **par type d'agent**.

| | Assistant | Agent de projet | Agent lancé | Agent plateforme |
|---|---|---|---|---|
| **Dossier de travail** | `wikichat-memory/assistant/sessions/<id>/` (sous-dossier par session) | `projects/<slug>/` | le même, ou un `git worktree` sous `.atelier/reparations/` | un projet système sous git (`atelier-gardiens`, `atelier-savoir`…) |
| **Chaîne `CLAUDE.md`** | `wikichat-memory/CLAUDE.md` + imports `@atelier/*.md`. **Le socle n'en fait pas partie** (cousin de `projects/`) | projet → socle `projects/CLAUDE.md` | idem, mais le `CLAUDE.md` du projet peut être chargé deux fois (à vérifier) | à définir |
| **Contexte généré** | `atelier/{consignes,outils,carte,a-valider}.md`, régénérés à chaque tour | `.atelier/contexte.md` : profil, outils, Onyxia, identité. **Statique** : sans l'état des artefacts, des apps, de l'hôte | idem + bloc « cette copie de travail » | à définir |
| **Skills, commandes, agents** (`.claude/…`) | aucun posé par l'Atelier | **aucun posé** : le kit (`/verifier`, `/reprendre`…) n'est pas livré | aucun | à définir |
| **Réglages** | `allow` étroit, `deny` de 19 outils natifs ; écriture limitée à `notes/**` | réglages du pod, `permissions.allow` du fil | `deny` de `git push`, `merge`, `rebase` | à définir |
| **MCP** | `atelier` (profil `assistant`), pont wikichat (profil `assistant`), navigateur | `atelier` (profil `code`, projet), pont wikichat (profil `code`), navigateur, connecteurs choisis, Onyxia s'il est déclaré | copié du projet | à définir |
| **Mémoire wikichat** | tout, en lecture ; propose dans « À valider » ; écrit dans `notes/` | la connaissance commune + celle de son projet | idem | écrit des propositions seulement |

**Ce qu'il faut ajouter.** Un générateur unique, à partir de `projet.json` et du type d'agent, qui
pose **tous** ces niveaux et seulement eux :
- les **skills** natives du projet (`publier`, `app`, `tester`, `demander`, `memoire`, `deployer`) ;
- quelques **sous-agents** natifs par défaut (`relecteur`, `explorateur`) avec leurs outils fermés ;
- un **contexte vivant** : état des artefacts, des applications (2 sur 4), de l'hôte des applications,
  de ce qui attend la personne ;
- pour l'Assistant, l'accès au socle (ou un équivalent), le nom wikichat de la session, et une règle
  explicite sur ce qu'il lit des projets.

L'Assistant respecte son dossier (c'est son dépôt) tout en ayant toute la mémoire de wikichat : il
l'a déjà par le pont. Il manque seulement que ce soit **dit** dans son contexte, avec l'annuaire des
projets et de leurs agents.

### 2.2 Les intentions : ce que l'agent doit savoir sans tâtonner

Chaque intention est un **guide chargé à la demande** (skill, indice, ou réponse d'un outil), jamais
une consigne permanente. Elle porte : le déclencheur, la règle de décision, les étapes, les limites,
les échecs et leur remède.

| Intention | Étapes aujourd'hui | Limites à dire | Échecs à prévenir | Geste unique à créer |
|---|---|---|---|---|
| **Publier une page** | `artefact_creer` → écrire `index.html` → `verifier` → `montrer` | privé au propriétaire ; liens relatifs ; pas de CDN, ni WebAssembly, ni `localStorage` ; écriture ≤ 5 Mio | ressource externe, chemin absolu | `/montrer` : vérifier, (démarrer), montrer, capturer, lire la console |
| **Créer une application locale** | `creer(mode=serveur)` → compléter `artefact.json` → `verifier` → `demarrer` → `montrer` | 4 apps au plus, 1,5 Gio, arrêt après 30 min d'inactivité, port attribué, même utilisateur Unix que les agents | **modification du backend sans effet** tant qu'on n'arrête pas puis redémarre (non documenté) ; chemins absolus sous préfixe ; `ATELIER_APPS_PUBLIC_URL` vide | `redemarrer` ; `demarrer` qui dit « déjà lancée, code modifié depuis » |
| **Tester, naviguer** | `navigateur_ouvrir` → `navigate_page` (code d'entrée à usage unique, 120 s) | 8 onglets par conversation, 6 Chrome en tout ; jamais `file://` ni `127.0.0.1` | permission restée sans réponse jusqu'à 1 h | hook `PreToolUse` sur la navigation ; renvoi vers `navigateur_ouvrir` |
| **Chercher sur le web** | `WebSearch` refusé → DuckDuckGo en HTML, lire avec `evaluate_script` | `take_snapshot` peut peser 1,5 M caractères | résultats énormes | skill `web` |
| **Retrouver l'information d'un projet** | `atelier_rappel` puis `atelier_fiche` ; `search_knowledge` ; `ETAT.md` | `rappel` : 5 fiches ; l'`ETAT.md` est souvent resté au gabarit | fiches sans résumé | `ETAT.md` calculé ; fiches résumées |
| **Poser une note** | `add_project_note` (projet), `remember` (conversation), `memoire_proposer` (personne) | trois portées différentes, trois outils | confondre les portées | skill `memoire` qui choisit |
| **Déployer sur pod** | déclaration par la personne → `project_start` → `exec(background)` → `job_poll` | `exec` synchrone ≤ 40 s ; un seul slot GPU ; exposition publique réservée à la personne | pod à démarrer mais non déclarable (D-30) ; yml de service inaccessible à l'agent | `deployer_lancer` (voir §2.3) |

### 2.3 Le placement : application locale ou pod Onyxia

L'agent doit décider seul, avec une grille et non au jugé. Le défaut de l'Atelier est **local
d'abord**.

| Critère | Seuil | Choix |
|---|---|---|
| GPU, inférence ML | tout besoin CUDA | pod, `gpu:true` |
| Mémoire résidente | > 1,5 Gio (la voix en mesure 2,18) | pod |
| Dépendances lourdes, build de plusieurs minutes | torch, modèles de centaines de Mo | pod |
| Processus long | > 40 s en synchrone | local s'il est léger et supervisé ; sinon pod |
| Accès par un tiers, URL publique | — | pod ; `expose_public` par la personne |
| Isolation, code non fiable, secrets | — | pod (le local partage l'utilisateur Unix) |
| Base de données serveur, gros volumes | > SQLite, Go | pod |
| Prototype, outil personnel, page | — | local |

Le pod coûte : déclaration par la personne (commande engageante), pod à l'état `Running`, pont
instable, pas de public sans la personne. D'où un **seul geste** `atelier_projet_deployer_lancer`
(aperçu et accord uniques ; défauts : `cible` calculée, `gpu:false`, `exposer:false`, port 8000), qui
enchaîne `list_pods`, `project_start`, la déclaration et, au besoin, `gpu_switch` sans préemption. Il
suppose de corriger D-30 (accepter un pod « à démarrer ») et d'ouvrir à l'agent de projet la
**demande** à la personne, pas l'action.

### 2.4 La communication : le contrat de requête et de réponse

Aujourd'hui : `lancer_agent` (engageante, asynchrone, jeton qui expire), `ouvrir` + `envoyer` +
`suivre` (Assistant seulement), le courrier wikichat (lu à la prochaine invite), les sous-agents natifs
(refusés à l'Assistant, aucun ne vise un autre projet). Rien ne relie une requête à sa réponse, et
l'agent lancé ne sait pas qui l'a lancé.

**Un geste unique : `atelier_demander(cible, message, attendre_s)`**, où `cible` est un projet, un
agent ou un sous-agent.
1. Le serveur retrouve ou ouvre la conversation de la cible, avec **sa** surface (jamais plus large
   que celle de l'appelant, §2.6).
2. Il injecte la **provenance** (qui demande, pourquoi, id de requête) et la consigne de réponse dans
   le tour de la cible.
3. Il attend `attendre_s`, ou s'endort : la veille et les notifications existent déjà.
4. La **réponse est persistée** (texte final, conclusion, branche éventuelle) et **délivrée** à
   l'appelant : au tour suivant par le hook `UserPromptSubmit`, ou par réveil pour l'Assistant.
5. Il applique les plafonds et le journal unique ; les questions d'autorisation de la cible remontent
   à l'appelant, puis à la personne.

Un sous-agent de son propre projet passe par le natif (`.claude/agents`), un sous-agent d'un autre
projet par `demander`. Cela remplace le jeton de confirmation de `lancer_agent` pour la délégation
courante.

### 2.5 La mémoire

| Portée | Outil | Qui écrit |
|---|---|---|
| conversation | `remember`, `recall` | l'agent (privé à l'identité de la conversation) |
| projet | `add_project_note`, `ETAT.md`, fiches | l'agent (note), le code (`ETAT.md` calculé) |
| personne | `memoire_proposer` → « À valider » | proposition seulement ; la personne retient |
| transverse | connaissance commune de wikichat | agents plateforme, par proposition |

Prérequis : **le store de wikichat doit survivre au redémarrage** (D-53) ; sans cela, routines,
déclencheurs et registre se perdent à chaque déploiement.

### 2.6 Le périmètre

Chaque agent reçoit une **surface** sur quatre axes : Atelier, Onyxia, local, budget. Trois règles :
- **Pas d'escalade par délégation** : la surface du lancé est incluse dans celle du lanceur.
- **Le plan de contrôle est hors de portée de tous** : `~/work/.atelier-etat`, `~/work/gateway`, le
  code de l'Atelier, les réglages de Claude, le store de wikichat, les secrets, les pods de l'Atelier
  et de la passerelle, le port 8787 avec la clé du propriétaire.
- **Les cinq niveaux** de la page Agents (Observateur, Assistant, Automate de routine, Agent de
  projet, Agent plateforme) sont des préréglages de ces axes, affichés en clair (« cet agent peut
  toucher : … »).

Aujourd'hui la porte de l'accès local est ouverte : l'environnement d'un agent est une copie de celui
de l'Atelier (clé du propriétaire, jeton GitHub, clé du modèle), `owner_key.txt` est lisible par le
groupe, `sudo` marche sans mot de passe et `kubectl` est dans le pod (D-54, D-55).

### 2.7 Les connexions

| Lien | Porte | Identité | Échecs connus |
|---|---|---|---|
| Atelier → Claude Code | `claude -p` en `stream-json`, `--settings`, `--mcp-config`, hooks | `ATELIER_SESSION` | CLI non épinglé ; formats internes lus à la main |
| Agent → Atelier | `/mcp` (outils `atelier_*`, passerelle) | en-têtes `X-Atelier-*`, clé du propriétaire | en-tête non prouvé (D1) ; 70 appels `call_tool` mal formés |
| Agent → wikichat | pont stdio (`WIKICHAT_AGENT`, profil, projet) | par conversation | store éphémère ; mode « dormant » |
| Agent → Onyxia | mandataire par projet | `session_id` imposé | déclaration, cercle D-30, délais |
| Agent → agent | `demander` (à créer), courrier wikichat | provenance (à créer) | pas de réponse liée |
| Atelier → personne | PWA, notifications, « À valider » | jeton de décision par question | 49 propositions sans réponse |

## 3. Ce qui existe et ce qui manque

- **Présent** : le catalogue de commandes et ses classes, les lancements bornés, la veille, les
  gardiens, le mandataire Onyxia, le navigateur de l'agent, le superviseur d'applications, la
  mémoire en couches, la passerelle à profils et à compositions.
- **Absent** : aucun fichier `.claude/skills|agents|commands` posé nulle part ; un contexte sans
  état ; pas de requête-réponse entre agents ; pas de règle de placement ; pas de plan de contrôle
  protégé ; pas de mesure des décisions de permission ; un store de wikichat éphémère.
- **Documents en retard sur le code** : `attendre-sans-refuser.md` §2, `gardiens.md` « Reste »,
  `architecture-transverse.md` §1.1, §1.2, §1.4, `assistant-synthese.md` (en-tête), `panneau.md` §2.1,
  `atelier-applications.md` « Écarts », `structure-projet.md` (champs du manifeste v2, commandes).

## 4. Mise en œuvre, par lots

**Lot 0, essais sur le pod (lecture)** : une skill posée dans `.claude/skills` d'un projet est-elle
chargée en `-p` avec `--strict-mcp-config` ; l'`additionalContext` d'un hook `SessionStart` atteint-il
le modèle derrière le relais ; les sous-agents natifs héritent-ils du MCP ; `permissionDecision:
defer` ; politique gérée lue en `-p`.

**Lot A, sans risque** : le générateur de harnais par type d'agent (skills, sous-agents, contexte
vivant), les guides d'intention, `redemarrer` et l'indice « code modifié depuis le lancement »,
hooks de navigation, `call_tool` tolérant aux appels mal formés, jeton de `lancer_agent` qui ne
périme plus, journal des réponses de permission (outil, projet, délai), documents remis à jour.

**Lot B** : `atelier_demander` avec provenance, réponse persistée et remise ; annuaire des agents
pour l'Assistant ; `deployer_lancer` et correction de D-30.

**Lot C, à valider avec la personne avant tout code** : le lien du store de wikichat vers le volume
(migration de données), l'environnement des agents en liste blanche, le jeton par conversation (D1),
le retrait de `sudo`, les droits de `owner_key.txt`, la confirmation liée à un humain (D-02).

## 5. Décisions à soumettre

1. Valider le lien du store de wikichat vers le volume (D-53) et la procédure : sauvegarde, lien,
   migration, redémarrage.
2. Valider l'environnement des agents en liste blanche et le jeton par conversation.
3. Retirer `sudo` de l'utilisateur des agents, ou le refuser par la politique.
4. Choisir les cinq niveaux d'agent et leurs noms.
5. Ne plus redémarrer le pod avant le point 1 : chaque redémarrage vide le store.
