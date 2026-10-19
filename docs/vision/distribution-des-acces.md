# Comment l'Atelier distribue les services à ses agents : la structure actuelle

Étude du 16/10/2026, faite en lisant `mcp_sync.py`, `commandes/profils.py`, `commandes/connecteurs.py`, `harness.py`, `env_secrets.py`, `gateway_mcp.py`, `session_mcp.py`, `onyxia_projet.py`, `wikichat_mcp.py`, `navigateur.py`, `lancements.py` et `mcp/gateway.py`, plus les relevés sur le pod de [`acteurs-et-acces.md`](acteurs-et-acces.md) §7. Elle décrit ce qui existe, pas ce qui est visé (voir `acteurs-et-acces.md` §8).

## 1. En une image

```
 SOURCES                              CALCUL                         SORTIES                            AGENT
 ────────                             ──────                         ───────                            ─────
 Pool des connecteurs ──┐                                        ┌─ <projet>/.mcp.json  ─────────────► VS Code, terminal
   gateway.db (SQLite)  │                                        │   (liaison, références ${…})
   + activé / désactivé │                                        │
                        │   configuration_du_profil              ├─ fichier effectif du tour ────────► app (claude -p
 Choix du projet ───────┼─► (settings, profil, cwd)  ───────────►│   mcp_effective_dir/<session>.json   --mcp-config
   .atelier/connecteurs-│   une seule fonction                   │   (+ identité, variables)            --strict-mcp-config)
   choisis.json         │   (mcp_sync.py)                        │
   ou marque « hérite » │                                        └─ ~/.claude.json (portée utilisateur : l'Atelier seul)
                        │
 Sondes ────────────────┤   retire : échecs d'authentification, alias déguisés, amont de la passerelle
 Onyxia déclaré ────────┤   ajoute : Onyxia selon le déploiement (onyxia_pour_projet)
   .atelier/projet.json │            navigateur (lanceur stdio), wikichat (pont stdio), atelier (/mcp)
 Fiche de conversation ─┘   profil : kind=assistant → assistant ; sinon code
 Secrets : ~/work/.secrets/claude-env.sh ──► références ${ATELIER_MCP_…} développées par l'environnement du processus
```

## 2. Les sources de vérité

| Quoi | Où | Qui écrit | Qui lit |
|---|---|---|---|
| **Pool des connecteurs** : déclaration, secrets, activé ou non, clé `atelier` (vues) | `gateway.db`, via `IntegratedMcpStore` | page Connecteurs, `atelier_connecteur_ajouter` (engageante), `_retirer` (réversible), `_accorder` (réservée) | `mcp_sync._pool_enabled`, la passerelle (`UpstreamPool`), l'hôte des applications |
| **Choix des connecteurs d'un projet** | `<projet>/.atelier/connecteurs-choisis.json` ; absence = **hérite**, avec la marque `.atelier/connecteurs-herites` | `atelier_connecteur_choisir` (réversible), `write_project_binding` | `configuration_du_profil` |
| **Déclaration du projet** | `.atelier/projet.json` (`ProjetJson` : `deploiement`, `vues_epinglees`, `creation`, `commandes`, `chemins_proteges`…) | commandes de structure et `atelier_projet_deployer_declarer` | `onyxia_pour_projet`, `project_context`, le panneau |
| **Fiche de conversation** | `sessions/<id>.json` : `kind`, `cwd`, `permission_mode`, `lance_par`, `supervise` ; `mcp_overlay` existe encore mais est **ignoré** | `SessionStore`, `Lancements` | `profil_effectif`, le harnais |
| **Sondes** | `noter_les_sondes` : quels connecteurs répondent 401 ou 403 | démarrage de l'Atelier | `configuration_du_profil` (un connecteur refusé n'est pas distribué) |
| **Secrets** | `~/work/.secrets/` ; `claude-env.sh` est **généré** depuis la clé du propriétaire, le pool et les variables des projets | `env_secrets.ecrire_le_fichier` | le harnais, `~/.bashrc`, code-server, wikichat |

## 3. Le calcul : une fonction, trois sorties

`mcp_sync.configuration_du_profil(settings, profil, cwd)` est le seul endroit où l'on décide ce qu'un dossier reçoit. Étapes, dans l'ordre :

1. **Pool activé.**
2. **Profil `code`** : ∩ choix du projet, ou tout le pool si le projet hérite. **Profil `assistant`** : ∩ les connecteurs choisis pour l'Assistant (les autres passent par les méta-outils de la passerelle).
3. Retrait des **échecs d'authentification**, des alias d'Onyxia déguisés et des amonts qui visent la passerelle elle-même.
4. **Onyxia** : retiré du pool, puis ajouté seulement si `onyxia_pour_projet` le dit (déploiement déclaré pour `code` ; `/mcp/onyxia` pour `assistant`).
5. **Navigateur** et **wikichat** remplacés par leurs lanceurs stdio (un processus par client, identité par l'environnement).
6. **`atelier`** ajouté en tête : `type: http`, adresse locale `/mcp`, en-têtes `Authorization: Bearer ${ATELIER_MCP_KEY}`, `X-Atelier-Conversation`, `X-Atelier-Profil`, `X-Atelier-Projet` (ou `X-Atelier-Dossier` pour l'Assistant), plus un `headersHelper` pour VS Code et le terminal.
7. Chaque valeur secrète devient sa **référence** `${ATELIER_MCP_…}`.

Trois sorties, un seul calcul :

| Sortie | Fonction | Pour qui |
|---|---|---|
| `<projet>/.mcp.json` | `lier_le_projet` (réécrit à chaque changement du pool pour les projets qui **héritent**, `lier_tous_les_projets`) | VS Code, terminal ; approuvé dans `~/.claude.json` et les réglages du dossier |
| Fichier effectif du tour | `materialize_session_mcp` : même calcul + identité de l'agent + variables de conversation ; donné au CLI avec `--mcp-config … --strict-mcp-config` | l'app |
| `~/.claude.json` | `materialize_mcp_config` : la portée utilisateur ne porte que `atelier` | tout `claude` lancé dans le pod |

## 4. Cinq façons de donner un service

| # | Mécanisme | Services | Ce que l'Atelier contrôle | Ce qu'il ne contrôle pas |
|---|---|---|---|---|
| 1 | **Configuration directe** : le CLI se connecte lui-même au service, l'en-tête est une référence résolue par l'environnement | QGIS, Blender, GitLab, Grist, LLM, data.gouv, `filesystem`, n8n, GitHub | **la liste** déclarée à l'agent | tout ce que l'agent fait ensuite : aucun intermédiaire |
| 2 | **Porte de l'Atelier** (`/mcp`, `McpGateway`) : filtre par profil à la liste et à l'appel, classes lecture / réversible / engageante / réservée, journal unique | `atelier_*`, méta-outils `gateway_*`, compositions | les outils, leurs arguments, la confirmation | l'identité : la conversation vient d'un en-tête que l'agent pose lui-même |
| 3 | **Mandataire borné** : un point d'entrée propre au projet, arguments imposés, outils réduits, session imposée | Onyxia (`/mcp/onyxia`, `/mcp/onyxia/projet/<slug>`) | tout l'appel | — |
| 4 | **Pont ou lanceur stdio**, un processus par client | wikichat (`WIKICHAT_AGENT`, `_PROFIL`, `_PROJET`), navigateur (`atelier-chrome`) | l'identité et le profil transmis au service | le filtrage final est celui du service lui-même |
| 5 | **Hors MCP** : `--settings` (règles `allow` / `deny`, `env` imposé), crochets (`garde_navigation`, garde bash), `CLAUDE.md` du socle et du projet | permissions, git, navigateur, contexte | ce qui est demandé ou refusé | ce que l'agent lit dans son propre dossier |

Les services de la mécanique 1 sont la grande majorité du pool, et ce sont ceux qui n'ont **aucun rôle** dans la distribution.

## 5. Les agents qui en reçoivent

- **App et harnais** : `Harness` lance `claude -p … --permission-mode … --settings … --mcp-config <fichier effectif> --strict-mcp-config`, avec l'environnement du processus : `env.update(ecrire_le_fichier(settings))` (toutes les variables du fichier d'environnement), puis celles du projet, puis `ATELIER_SESSION` et `WIKICHAT_AGENT`.
- **Agents lancés** (`Lancements`) : une conversation dans le projet visé, donc le même calcul ; ajoutent `permissions.allow` (liste d'`outils`), `permissions.deny` (branche), le mode, la durée, la copie `git worktree` sur branche.
- **Pilote de wikichat** : un trigger `cron` qui appelle `POST /v1/lancements` avec la clé du lanceur (et non celle du propriétaire).
- **Gardiens** : un démon (port 8791) qui peut demander une réparation par le même chemin.
- **VS Code / terminal** : lisent `<projet>/.mcp.json` et `~/.claude.json` ; l'identité vient du `headersHelper`.

## 6. Ce que la structure a de bien

1. **Une seule fonction de profil**, trois sorties : l'app, VS Code et le terminal ne peuvent pas diverger sur la liste (testé : `test_profils_surfaces.py`, vérificateur de cohérence).
2. **Les secrets sont des références** dans tous les fichiers que lit l'agent ; les valeurs vivent dans un fichier 0600 régénéré.
3. **Le filtrage de `/mcp` porte sur la liste et sur l'appel**, et ne s'élève pas par un en-tête.
4. **Les commandes sont classées** et journalisées (`commandes/catalogue.py`), avec aperçu et jeton pour les engageantes.
5. **Onyxia montre le patron attendu** : déclaration du projet → point d'entrée propre → arguments imposés → contexte rédigé pour l'agent.

## 7. Ce que la structure a de fragile

1. **La distribution est de la configuration, pas de la médiation.** Pour sept services sur neuf, choisir un connecteur ne fait que le *déclarer* ; l'agent s'y connecte seul, avec l'autorité complète du jeton.
2. **Les secrets sont globaux dans l'environnement.** `claude-env.sh` porte onze variables : la clé du propriétaire, les jetons de QGIS, Blender, GitHub, GitLab, Grist (deux), LLM, n8n, **Onyxia**, et `VOICE_TOKEN`. Le harnais les met toutes dans l'environnement de tout agent (`env.update(...)`) et `~/.bashrc` les charge. Un agent d'un projet qui ne reçoit que deux connecteurs détient donc les jetons de tous, dont celui d'Onyxia : il pourrait joindre Onyxia **sans passer par le mandataire**, qui n'est alors qu'une courtoisie. *(Lu dans le code ; non mesuré sur un processus d'agent vivant : aucun n'était en cours au moment du relevé.)*
3. **Le rôle est collé après coup** dans une fonction faite pour distribuer des connecteurs : des branches `if profil == "assistant"`, `est_onyxia`, `est_wikichat`, `est_le_navigateur`, `SERVICE_ATELIER`, répartis dans `mcp_sync.py`. Ajouter un service borné (n8n, QGIS) obligerait à y ajouter un cas de plus.
4. **L'héritage est une réécriture de fichiers**, pas une référence : un projet qui « hérite » est un projet dont `.mcp.json` est recopié à chaque changement du pool, avec une marque. Cela explique les 27 projets sur 40, et rend « refus par défaut » difficile à exprimer.
5. **Quatre sens de « profil »** (accès `code` / `assistant`, profils de la passerelle, profil wikichat, « niveaux » de la page Agents) et deux listes d'outils (celle de `profils.py`, celle du Pilote).
6. **L'identité est une convention.** `X-Atelier-Conversation` et `X-Atelier-Profil` sont posés par la configuration que l'agent peut lire ; la clé qui ouvre `/mcp` est la même pour tous. D'où les 57 outils sans en-tête, et la limite écrite dans `profils.py`.
7. **Du code mort ou à demi-mort** : `mcp_overlay` (ignoré), `_onyxia_bouchon`, le registre `registry.json` « legacy », `compute_binding_merged` appelé par `session_mcp` pour un aperçu qui n'a plus de couche propre.

## 8. Ce qu'il faut retenir pour la suite

- Le bon point d'ancrage existe : **`configuration_du_profil`**. Une matrice acteur × service y remplacerait les branches sans changer les trois sorties.
- Le plus gros trou n'est pas dans la liste des connecteurs mais dans **l'environnement** : tant que tous les jetons sont dans tout processus d'agent, aucun mandataire n'est une frontière. Le correctif structurel : ne donner à un processus que les variables des connecteurs qu'il a **déclarés**, et faire passer le reste par un mandataire qui détient le jeton.
- Les services en mécanique 1 sont ceux qu'il faut faire passer en mécanique 3, un par un, en commençant par ceux dont le jeton est le plus puissant (Onyxia déjà fait côté liste, GitLab, GitHub, n8n).
