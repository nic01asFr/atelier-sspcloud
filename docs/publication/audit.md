# Audit du dépôt avant publication

Équipe « publication », 26 septembre 2026, branche `v4-publication` (partie
d'`integration-v4`). Objet : un dépôt propre, documenté et sans fuite, prêt à
passer public. **Rien n'a été poussé, publié ni rendu public** : ce sont des
décisions du mainteneur, listées au §9.

## 1. Synthèse

| Sujet | État avant | Fait | Reste à décider |
|---|---|---|---|
| Secrets dans l'historique | inconnu | scan complet (gitleaks et motifs) : **aucun secret réel**, 6 + 8 faux positifs, tous des valeurs de test | rien sur les secrets ; l'adresse de l'auteur est dans les métadonnées des commits (§9) |
| Données personnelles | chemins de la machine, adresses de pod nominatives, employeur, captures | neutralisées dans les documents vivants et les captures | le prénom de l'auteur dans les documents de vision, les exemples de projets réels (§9) |
| Structure racine | fichiers égarés, traces mêlées | `filtre.mjs` et traces rangés, `install.sh` dans `install/` | retirer `deploy-patches/`, `wikichat-atelier/`, `helm-repo/` (§9) |
| `docs/` | 30 documents à plat, sans index, dont la moitié périmés | index par usage, 13 traces en archives, bandeaux d'état, 9 contradictions avec le code corrigées | réécrire en profondeur les documents de vision marqués « partiel » (§4) |
| Sécurité | `SECURITY.md` faux sur deux points de fond | réécrit sur le code actuel, signalement privé | activer le signalement privé sur GitHub (§9) |
| Hygiène | licence et sécurité seulement | `CONTRIBUTING.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `.editorconfig`, métadonnées du paquet | — |
| CI | image sans permissions par défaut, pas de test des demandes de fusion | lecture seule par défaut, tests sur les demandes de fusion, vérification des liens | épingler les actions par empreinte (§8) |
| README | français, liste de fichiers | refait, FR et EN, capture, schéma, état honnête | — |
| Vitrine | provisoire, captures de l'interface v1 | refaite : capacités, cas d'usage, associations, schéma, captures réelles dans les deux thèmes | — |

Vérifications : suite Python **1 468 réussis, 74 sautés** ; tests de la
vitrine et du vérificateur de liens **16 réussis** ; **0 lien relatif cassé**
sur les fichiers Markdown suivis ; vitrine rendue sans débordement, sans
erreur de console, sans contraste insuffisant (§7).

## 2. Structure racine

| Élément | Rôle | Avis |
|---|---|---|
| `README.md`, `README.en.md` | présentation | refaits |
| `LICENSE` | Apache-2.0, « Copyright 2026 Nicolas Laval » | cohérente (§6) |
| `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md` | hygiène | ajoutés ou réécrits |
| `.gitignore`, `.gitattributes`, `.editorconfig` | réglages | `.editorconfig` ajouté |
| `.github/workflows/` | CI | voir §8 |
| `atelier-src/` | le service, l'interface, la passerelle, les gardiens, les tests | à garder |
| `charts/atelier/` | le chart Helm | à garder |
| `deploy/Dockerfile` | l'image | à garder |
| `install/` | `atelier-init.sh` (point d'entrée de l'image, chemin de secours) et désormais `install.sh` (déploiement par Helm) | **déplacé** : `install.sh` était seul à la racine ; l'adresse publiée (`…/install.sh` sur Pages) ne change pas, la CI le copie toujours |
| `site/` | la vitrine | refaite (§7) |
| `scripts/` | vérificateur de liens | **ajouté** |
| `docs/` | documentation | réorganisée (§4) |
| `filtre.mjs` | garde-fou d'un dépôt mémoire de wikichat, produit par un agent le 22/08, importé nulle part | **rangé** dans `docs/archives/filtre-depot-memoire/` avec une note ; à porter dans le dépôt qu'il protège puis à supprimer |
| `deploy-patches/deploy_agent_ui.py` | outil de l'auteur : pousser l'arbre vers un pod par le MCP Onyxia | **à supprimer (proposé)** : dernier changement le 11/09, vise l'ancienne organisation (`/home/onyxia/work/atelier-src`, session `proj-claude-code`), une adresse de pod nominative par défaut, et pousse encore `wikichat-atelier/src/pilote.mjs` (ligne suivante) ; l'installation passe par l'image |
| `wikichat-atelier/` | version de travail de `pilote.mjs` de wikichat | **à supprimer (proposé)** : la branche `atelier-coherence` de wikichat contient ses trois ajouts **et davantage** (le mode de permission des agents) ; ni l'image ni `atelier-init.sh` ne le posent, et `deploy_agent_ui.py` le pousserait par-dessus une version plus récente. Supprimer les deux ensemble |
| `helm-repo/` | miroir de transition du dépôt Helm (`raw.githubusercontent.com`), repoussé par la CI | **à supprimer (proposé)** à la version suivante du chart, comme le prévoit `release.yml` ; retirer alors le pas « Miroir » et la permission `contents: write` |

## 3. Secrets

**Méthode.** Clone miroir de toutes les références du dépôt local (331 révisions, les
48 branches locales et les 14 branches distantes comprises), puis :

1. **gitleaks** (image Docker `zricethezav/gitleaks`, règles par défaut, sortie
   masquée) sur tout l'historique : 302 commits, 6,1 Mo analysés ;
2. un balayage de motifs sur le texte complet des 331 révisions
   (`git log --all -p`) : jetons GitHub (`ghp_`, `github_pat_`), GitLab,
   `sk-…`, AWS, JWT, clés privées, Hugging Face, Slack, Google, identifiants
   dans une URL, `Bearer` longs, affectations `key|token|secret|password` ;
3. la liste des fichiers **supprimés** de l'historique, relus un à un
   (`helm.yml`, `atelier-vscode-handoff.sh`, `chrome_proxy.py`,
   `docs/consignes/socle.md`) ;
4. les captures d'écran, relues une à une (§5).

**Résultat : aucun secret réel.** Toutes les trouvailles sont des valeurs de
test écrites pour ça :

| Fichier | Commit | Type signalé | Nature |
|---|---|---|---|
| `atelier-src/tests/test_memoire.py` | `3a5667fb` | generic-api-key | valeur fictive d'un test du filtre |
| `atelier-src/tests/test_commandes_connecteurs.py` | `ad5f7b46` | generic-api-key (2), identifiants dans une URL | valeurs fictives, hôte `.invalid` |
| `atelier-src/tests/test_commandes_catalogue.py` | `d62ada64` | generic-api-key, `sk-…` | valeur fictive |
| `atelier-src/tests/test_secrets_arguments.py` | `557433a7` | generic-api-key | en-tête fictif vers `tiers.exemple` |
| `.github/workflows/release.yml` | `c24789ec` | generic-api-key | clé factice du rendu du chart |
| `atelier-src/tests/test_gardiens_*.py`, `test_garde_endpoint_interne.py`, `web/js/controllers/accords.js` | divers | affectations `SECRET = …` | valeurs fictives ou nom de commande |
| `atelier-src/tests/test_bureaux.py` (historique) | — | identifiants dans une URL | `user:mdp@blender`, fictif |

Rien n'est donc à réécrire dans l'historique pour des secrets. Deux points à
surveiller, hors de ce dépôt :

- l'ancienne consigne archivée `docs/archives/consignes/chrome-devtools-atelier.md`
  dit qu'un commit **d'un autre dépôt** (le fork de `chrome-devtools-mcp`) et
  un de ses remotes portaient des jetons en clair : s'ils n'ont pas été
  révoqués, le faire ;
- `SECURITY.md` rappelle qu'une clé de modèle écrite dans `settings.json`
  avant le correctif du 02/09 doit être renouvelée.

**Si un secret devait un jour être retiré de l'historique** : le révoquer
d'abord (c'est la seule vraie protection), puis `git filter-repo
--replace-text` sur un clone miroir, vérification par un nouveau scan, poussée
forcée de toutes les branches, et demande à GitHub de purger les vues en
cache. Ce n'est pas nécessaire aujourd'hui.

## 4. Documentation

**Index.** [`docs/README.md`](../README.md) range tout par usage : utiliser,
installer et exploiter, contribuer, conception et vision, décisions,
historique.

**Rangés en archives** (avec une ligne « ce que c'est, remplacé par » dans
[`docs/archives/README.md`](../archives/README.md)) : le cahier du shell
unifié, les captures v1, les trois documents MCP d'août, l'audit de
cohérence des outils, le journal de chantier des lots A à H, la conception de
l'application Lecteur Grist, la consigne du fork Chrome abandonné, et sept
documents de préparation de la vision (cadrages de l'Assistant, harnais,
contexte, cohérence croisée, relecture, mesures de la vague 1, plan
d'implémentation). Les liens et les commentaires du code qui les citaient
suivent.

**Corrigés contre le code :**

| Document | Écart | Code |
|---|---|---|
| `SECURITY.md` | « l'ingress authentifié d'Onyxia » : l'ingress du chart n'ajoute aucune authentification | `charts/atelier/templates/ingress.yaml` |
| `SECURITY.md` | « le harnais lance `claude` en `bypassPermissions` » : le défaut est `acceptEdits` | `config.py`, `harness.py` |
| `SECURITY.md` | OAuth de `/mcp`, cookie de session, hôte des applications, clé lisible par les agents, secrets `atelier_lanceur_key`, `github_token`, `claude-env.sh`, `apps/` : absents | `auth.py`, `oauth.py`, `apps/passage.py`, `env_secrets.py`, `lancements.py` |
| `fonctionnalites.md`, `vision/decisions.md`, `vision/architecture-transverse.md` | résumé de mémoire plafonné à 800 jetons ; c'est 1 200 | `memoire_modele.py`, `SORTIE_MAX_JETONS` |
| `fonctionnalites.md` | `bin/node-relais` absent du §18, lien vers la consigne abandonnée | `atelier-src/bin/` |
| `installer.md` | « les trois processus » : cinq ; second ingress absent ; `ATELIER_GITHUB_OWNER`, `ATELIER_GARDIENS(_PORT)` absents ; chemin de secours sans hôte des applications ; `chrome-devtools-mcp` déclaré d'office | `install/atelier-init.sh`, `values.yaml`, `config.py`, `gateway_runtime.py` |
| `navigateur-atelier.md` | « l'Assistant, à venir » | `assistant.py` |
| `onyxia-projet.md` | lien vers une note privée hors dépôt | — |
| 8 documents de vision et de conception | « proposition non implémentée », « page Gardiens » : bandeau d'état en tête qui dit ce qui existe (décision J-i, vagues 1 à 3) | `docs/fonctionnalites.md` |

**Encore partiels** (bandeau posé, réécriture à faire) :
`vision/architecture-transverse.md`, `vision/assistant-role.md`,
`vision/assistant-synthese.md`, `vision/synthese.md`, `vision/gardiens.md`,
`vision/panneau.md` (§3.5 recommande une architecture Chrome inverse de celle
livrée), `vision/profils-acces.md` (27 commandes listées pour 53),
`atelier-applications.md` (« État de la mise en œuvre » périmé),
`atelier-mcp-distant.md` (comptes d'outils d'août), `ui/audit.md` (numéro de
version du cache). `docs/consignes/lecteur-grist.md` et
`creation-agents-atelier.md` sont des consignes de projets du pod d'origine :
les garder comme exemples ou les sortir du dépôt public (§9).

**Liens** : [`scripts/verifier-liens.mjs`](../../scripts/verifier-liens.mjs)
vérifie chaque lien relatif et chaque ancre des fichiers Markdown suivis (slug
de GitHub, accents compris) ; 0 lien cassé, et un workflow le relance à chaque
modification.

## 5. Données personnelles et adresses internes

| Trouvé | Où | Fait |
|---|---|---|
| chemins de la machine de l'auteur (`C:/Users/…`) | 3 documents | retirés |
| adresses de pod nominatives (`user-<identifiant>-…`) | 9 documents, 1 test, 1 commentaire | remplacées par `user-<idep>-…` ou `user-jdupont` |
| identifiant de namespace dans un commentaire de `config.py` | 1 | neutralisé |
| employeur (nom, adresse `@…`) | `onyxia-projet.md`, un document de vision, la spec archivée | neutralisé |
| adresse de pod et chemin local **dans des captures** | `docs/ui/apres/02, 09, 20, 22, 34-*`, `docs/ui/avant/02` | zones floutées (vérifiées à l'œil) |
| captures « avant » de l'audit d'interface | `docs/ui/avant/` | noms de projets personnels réels visibles (liste de projets du pod d'origine), aucun secret : **à décider** (§9) |
| prénom de l'auteur | 17 documents de vision, le guide, l'audit d'interface, des consignes | laissé : c'est le mainteneur et le décideur nommé du registre ; **à décider** (§9) |
| noms de jeux de données de travail (CRESO, communes) | consignes et conception du Lecteur Grist | laissé en exemples ; **à décider** |
| nom et adresse de courriel de l'auteur | métadonnées des 332 commits | **à décider** (§9) |
| `bearer_ceremadoc`, mots-clés du chart (`cerema`) | `mcp_gateway/config.py`, `Chart.yaml`, `helm-repo/index.yaml` | laissé : nom d'un connecteur réel et affiliation d'usage ; **à décider** |

Les **nouvelles captures** (vitrine, README) viennent d'une instance locale
aux données inventées ; le script de capture refuse de photographier un écran
qui montre un chemin de la machine ou la clé de l'instance, et chacune a été
relue à l'œil. Procédure : [`captures/README.md`](captures/README.md).

## 6. Licence et dépendances

Apache-2.0 est compatible avec les dépendances Python déclarées (FastAPI,
Starlette, Pydantic, httpx, PyYAML, mistune, uvicorn : MIT ou BSD), avec
wikichat (MIT, même auteur ; `wikichat-atelier/` en est une version modifiée
par lui), code-server (MIT) et `chrome-devtools-mcp` (Apache-2.0). Les
modèles cités (Qwen, Gemma) ne sont pas distribués : ils sont appelés par la
passerelle du SSPCloud.

Deux points relèvent de l'**image**, pas du dépôt : elle embarque **Google
Chrome** (paquet officiel, licence propriétaire de Google) et **l'extension
Claude Code** (conditions d'Anthropic), installés à sa construction. Le
README le dit désormais (« ce dépôt ne contient pas Claude Code ; l'image
l'installe »). Publier l'image sur un registre public revient à redistribuer
ces deux logiciels : à vérifier contre leurs conditions (§9).

Métadonnées : `pyproject.toml` déclare maintenant sa licence et ses
adresses ; la version du service (`mcp_gateway/atelier/__init__.py`, 0.1.0,
rendue par `/health`) diffère de celle du paquet (0.2.0) et de celle du chart
(0.2.0) : à aligner à la prochaine version.

## 7. Vitrine

Refaite dans `site/` :

- **contenu** (`site/vitrine.json`, bilingue) : promesse, quinze capacités en
  trois familles avec leur statut et un lien vers leur section du guide, visite
  de six vues et du téléphone, cinq cas d'usage pas à pas (briques, étapes,
  limite honnête), huit associations entre briques, schéma d'architecture,
  installation, état et limites, versions ;
- **identité** : les couleurs sont les jetons de l'interface
  (`web/css/jetons.css`), lus à la génération, dans leurs deux thèmes ; même
  typographie ; un bouton Système / Clair / Sombre, retenu localement ;
- **ce qui se lit dans le code n'est plus recopié** : version du chart, nombre
  et noms des vues (`web/index.html`), nombre de contrôles des gardiens
  (`gardiens.json`) ;
- **captures réelles** dans les deux thèmes (`site/assets/captures/`, WebP,
  900 Ko en tout), montrées selon le thème courant ;
- **accessibilité** : lien d'évitement, repères, titres hiérarchisés, texte de
  remplacement détaillé pour chaque capture, schéma titré, focus visible,
  animations absentes ; **aucun texte sous le contraste AA** dans les deux
  thèmes (mesuré dans le navigateur sur chaque élément de texte), navigation
  au clavier vérifiée ;
- **responsive** : aucun débordement horizontal à 1440 et à 390 px ;
- **dépendances** : aucune, sauf les polices de l'interface (Google Fonts, avec
  repli système), comme l'Atelier lui-même.

Les tests (`site/generate.test.mjs`) vérifient les traductions, les statuts,
les sections et les ancres du menu, les deux thèmes, les chiffres lus dans le
code, la présence de chaque capture citée, le texte de remplacement de chaque
image, l'absence de français sur la page anglaise (hors noms de vues de
l'interface) et la résistance du script de thème à un stockage indisponible.

Rendus : [`vitrine/`](vitrine/) — pages complètes en clair et en sombre, à
1440 px (`vitrine-fr-clair-1440.webp`, `vitrine-fr-sombre-1440.webp`) et à
390 px (en deux parties), et le haut de la page anglaise.

## 8. Intégration continue

| Workflow | Avant | Après |
|---|---|---|
| `image.yml` | pas de `permissions` au niveau du workflow (le job de tests héritait du défaut du dépôt) ; ne tournait pas sur les demandes de fusion | `contents: read` par défaut, `packages: write` pour le seul job qui pousse ; tests sur les demandes de fusion, sans jamais pousser d'image |
| `release.yml` | propre : `contents: read` par défaut, écriture limitée au job de publication sur `main` | suit `install/install.sh` et les fichiers dont la vitrine lit ses chiffres et ses couleurs |
| `docs.yml` | — | nouveau : teste le vérificateur et vérifie les liens de la documentation |

Aucun secret n'est utilisé hors de `GITHUB_TOKEN` ; aucun déclencheur
`pull_request_target`. Recommandations restantes : épingler les actions tierces
par empreinte de commit plutôt que par étiquette (`docker/*`, `azure/setup-helm`,
`helm/kind-action`) ; retirer `contents: write` de `release.yml` avec le
miroir `helm-repo/`.

## 9. Décisions pour le mainteneur

Avant de rendre le dépôt public :

1. **Historique et identité.** Les 332 commits portent le nom et l'adresse de
   courriel personnelle de l'auteur. Publier tel quel, ou réécrire l'auteur
   vers une adresse `noreply` de GitHub (`git filter-repo --mailmap`, poussée
   forcée) — ou publier un historique neuf. Le dépôt distant porte aussi
   14 branches de travail (`integration-*`, `deploiement-26-09`…) qui
   deviendront visibles : les supprimer ou les garder ; les autres branches
   locales (48 en tout) ne sont pas poussées.
2. **Supprimer `deploy-patches/` et `wikichat-atelier/`** ensemble (§2) : le
   second est en retard sur `atelier-coherence` et le premier le pousserait sur
   un pod.
3. **Supprimer `helm-repo/`** à la prochaine version du chart, avec le pas
   « Miroir » de `release.yml`.
4. **Faire suivre wikichat par l'image** : le `Dockerfile` clone wikichat sur
   `main`, qui a 23 commits de retard sur `atelier-coherence`, la branche dont
   l'Atelier dépend (lot W, profils, mémoire). Fusionner `atelier-coherence`
   dans `main` de wikichat, ou poser `WIKICHAT_REF=atelier-coherence`. Sans
   cela, une installation neuve par le catalogue n'a pas ce que la vitrine
   décrit.
5. **Activer le signalement privé des failles** (Settings › Code security ›
   Private vulnerability reporting), que `SECURITY.md` désigne désormais.
6. **Image publique** : vérifier que redistribuer Google Chrome et l'extension
   Claude Code dans `ghcr.io/nic01asfr/atelier` est permis par leurs
   conditions, ou les faire installer au premier démarrage.
7. **Prénom dans les documents de vision** : garder (c'est l'auteur et le
   décideur nommé), ou remplacer par « le mainteneur ».
8. **Captures `docs/ui/avant/`** : elles montrent la liste de projets du pod
   d'origine (noms de projets personnels). Garder, recadrer ou ranger en
   archives.
9. **Consignes de projets réels** (`docs/consignes/lecteur-grist.md`,
   `creation-agents-atelier.md`) et conception du Lecteur Grist archivée :
   garder comme exemples ou sortir du dépôt public.
10. **Mot-clé `cerema`** du chart et connecteur `ceremadoc` dans la
    configuration : les garder signale une affiliation ; les retirer si le
    projet se présente comme indépendant.
11. **Version** : aligner la version du service (0.1.0) sur celle du paquet et
    du chart, et monter le chart à la prochaine publication (0.3.0) : son
    contenu a changé depuis la 0.2.0 publiée.
12. **Réécrire les documents de vision partiels** (§4) ou les ranger en
    archives une fois leurs décisions reportées dans `decisions.md`.

Pour publier ensuite : pousser la branche, vérifier la CI (image, chart,
vitrine, liens), rendre le dépôt public, puis activer GitHub Pages si ce n'est
pas déjà fait — la vitrine se publie alors à chaque modification de `site/`.
