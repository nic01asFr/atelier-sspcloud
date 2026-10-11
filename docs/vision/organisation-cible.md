# L'organisation cible : le pod, les volumes, les plans, et le chemin pour y arriver

> État au 11/10/2026. **Proposition**, non implémentée. Elle s'appuie sur des mesures faites le même
> jour sur le pod `atelier-0` et sur le namespace (lecture seule). Ce qui est **estimé** est dit
> comme tel.

## 1. L'état mesuré

| | Valeur | Remarque |
|---|---|---|
| Pod | `atelier-0`, nœud `boss14` (partagé, charge ≈ 13) | un seul conteneur, image `atelier:latest` (non épinglée) |
| Ressources | CPU 0,5 demandé / 4 plafond ; mémoire 2 Gi demandée / **8 Gi plafond** | classe Burstable ; **aucun quota CPU ni mémoire** sur le namespace |
| Mémoire, à vide | 2,9 Go : 0,45 de processus, 2,4 de cache (libérable) ; pic 4,0 depuis le démarrage | socle mesuré ≈ 0,7 Go (Atelier 213 Mo, wikichat 164, code-server 178, relais 55, gardiens 45) |
| Processus | 63, dont **50 zombies** après 1 h (6 par session du navigateur de l'agent) | PID 1 est l'application Python : elle ne ramasse pas les orphelins |
| Volume | un seul, **10 Gi, plein à 74 %** | projets 2,0 Go, archive de migration 1,8, extensions de code-server 1,7, `.claude` 0,6, transcripts 0,23 (en croissance) |
| Hors volume (perdu à chaque redémarrage) | `~/.wikichat`, profils Chrome (`/tmp`), une partie de `~/.claude` | D-53 |
| Quotas du namespace | pods 31 sur 100, stockage 1,33 Ti sur 2 Ti, GPU 0 sur 1 | assez de marge pour de nouveaux volumes |
| Droits du compte d'exploitation | supprimer un pod, exécuter dans un pod, créer des volumes, modifier un StatefulSet : oui. **Instantanés de volume et tâches planifiées : non** | les sauvegardes passent donc par l'Atelier lui-même |

**Plafonds des charges dynamiques** (config de l'Atelier) : 4 applications de 1,5 Gio, 6 Chrome de 8
onglets, 3 CLI persistants, 3 lancements simultanés, la voix en plus (2,2 Go mesurés). Additionnés
au pire cas : **12 à 15 Gio pour 8 de plafond** (les lignes Chrome et CLI sont des estimations, à
mesurer sous charge). Un dépassement est tué par le noyau ; si c'est PID 1, tout le conteneur
redémarre et le store de wikichat disparaît.

## 2. Les principes de la cible

1. **Chaque donnée a un seul foyer durable**, sauvegardé : jamais dans la couche éphémère.
2. **Le plan de contrôle est séparé du plan d'exécution.** Ce qui décide (API, passerelle, journal,
   « À valider », secrets, gardiens, wikichat) ne partage ni le système de fichiers, ni l'utilisateur
   Unix, ni le domaine de mémoire avec ce qui exécute du code d'agent (CLI, navigateur, applications).
   C'est la réponse structurelle au périmètre des agents : la frontière est physique, pas une consigne.
3. **Un budget global de capacité** gouverne tout ce qui démarre (Chrome, applications, CLI) : on
   refuse ou on met en attente avant d'atteindre le plafond, on n'attend pas que le noyau tue.
4. **Un déploiement ne détruit rien** : arrêt gracieux (les tours en cours passent en veille et
   reprennent), sauvegarde avant arrêt, image épinglée, retour arrière possible.
5. **Ce qui est lourd, public ou à GPU vit dans un pod Onyxia dédié**, déclaré, pas dans l'Atelier.

## 3. La cible

```
Pod « atelier »  (un StatefulSet, deux conteneurs, même nœud, réseau local partagé)
├─ conteneur « controle »   uid 1001, sans sudo, 1 Gi demandé / 2 Gi plafond
│    API + interface + PWA, passerelle et courtier d'outils, relais LLM, notifieur,
│    journal, « À valider », décisions, gardiens, wikichat (Pilote, mémoire),
│    secrets, jetons par conversation
│    ── volume « etat »  (5 Gi, sauvegardé chaque nuit, hors de portée du conteneur d'exécution)
└─ conteneur « execution »  uid 1000, sans sudo, 3 Gi demandés / 10 Gi plafond
     « runner » local (lance les CLI, relaie les flux), agents, Chrome, applications
     servies, code-server, voix ; environnement en liste blanche, aucune clé de l'Atelier
     ── volume « projets »  (30 Gi, extensible)   ·   /tmp en emptyDir borné

Hors du pod :  pods Onyxia dédiés (GPU, services lourds ou publics), pilotés par le MCP Onyxia ;
               stockage objet S3 pour les sauvegardes hors du cluster.
```

Totaux : 4 Gi demandés, 12 Gi plafonnés. La séparation en **deux pods** n'est utile que plus tard
(déploiements indépendants, plusieurs personnes) : l'étape 6.

| Ce que la cible règle | Défaut |
|---|---|
| Le store de wikichat et l'état survivent aux redémarrages | D-53 |
| Un agent ne lit ni la clé du propriétaire, ni le jeton GitHub, ni `sudo` | D-54, D-55 |
| Un Chrome ou une application qui déborde ne tue plus le contrôle | OOM |
| Les zombies sont ramassés | D-59 |
| Un redéploiement ne coupe plus le travail en cours | veille |

## 4. Les étapes

Chaque étape est livrable seule, avec une preuve de réussite et un retour arrière.

### Étape 0 : arrêter la perte (immédiat, sans changement d'infrastructure)
- **Fait** : plus de redémarrage du pod tant que l'étape 1 n'est pas faite.
- Sauvegarde manuelle de `~/.wikichat` vers le volume avant tout redémarrage nécessaire.
- Registre : D-59 (zombies), plafonds incompatibles avec la mémoire.
- **Preuve** : une copie datée existe sur le volume.

### Étape 1 : rendre le store de wikichat durable (D-53)
- Appeler `ensure_wikichat_data_link` au démarrage, **avant** wikichat ; migration non destructive
  (copie de l'existant, puis lien) ; test de redémarrage.
- **Écrit** (`donnees_wikichat.py`, appelé par l'init avant wikichat) : copie vérifiée, ancien
  dossier gardé, lien ; la copie du pod en marche vers le volume reste à faire à la main avant le
  premier redémarrage (registre D-53).
- **Décision de la personne** : c'est une migration de données.
- **Preuve** : un déclencheur créé survit à un redémarrage. **Retour** : retirer le lien, restaurer la copie.

### Étape 2 : hygiène et budget de capacité
- Ramassage des orphelins (`tini` dans l'image, ou `waitpid` dans l'application).
- Contrôle de santé « mémoire » (alerte à 80 % du plafond) et « processus zombies ».
- Budget global : mesure de la mémoire par classe (CLI, Chrome, applications) ; un démarrage qui
  ferait dépasser 85 % est mis en attente avec un message qui dit quoi faire.
- Plafonds revus : `apps_max`, nombre de Chrome et de CLI déduits du budget, pas de la confiance.
- **Preuve** : zéro zombie après 24 h ; un essai de charge (4 applications + 6 Chrome + 3 CLI) ne
  provoque pas d'OOM. **Retour** : revenir aux anciens plafonds.

### Étape 3 : déploiement qui ne détruit rien
- À l'arrêt (SIGTERM) : les tours en cours passent en **veille** (le mécanisme existe), sauvegarde
  de l'état, puis sortie ; `terminationGracePeriodSeconds` de 120 s.
- Sondes de disponibilité et de vivacité ; image épinglée par empreinte ; procédure de déploiement
  écrite (qui remplace le « supprimer le pod » à la main).
- **Preuve** : un redémarrage au milieu d'un tour le reprend après. **Retour** : l'image précédente.

### Étape 4 : séparer l'état des projets, et sauvegarder
- Nouveau volume `etat` (5 Gi) pour le journal, les bases, les décisions, « À valider », le store de
  wikichat, les secrets ; `projets` garde le reste. L'archive de migration (1,8 Go) sort du volume
  (vers S3, avec ton accord).
- Sauvegarde nocturne de `etat` par un automate de l'Atelier vers S3 (le compte d'exploitation ne
  peut ni créer d'instantané ni de tâche planifiée) ; contrôle gardien « dernière sauvegarde < 24 h ».
- Chart 0.4.0 avec les deux volumes ; fenêtre d'arrêt courte.
- **Preuve** : restauration d'essai de `etat` sur un volume vide. **Retour** : ancien chart et copie.

### Étape 5 : séparer les privilèges
- **5a, sans nouveau conteneur** : environnement des agents en **liste blanche** ; droits de groupe
  de `owner_key.txt` retirés ; `sudo` retiré de l'image ou refusé ; jeton par conversation (D1).
  **Décision de la personne** : authentification et image.
- **5b, le gros chantier** : deux conteneurs (contrôle / exécution) avec utilisateurs et volumes
  distincts ; un « runner » local lance les CLI et relaie les flux ; le harnais appelle le runner au
  lieu de lancer lui-même.
- **Preuve** : un agent avec Bash ne peut ni lire l'état, ni la clé, ni modifier le code de l'Atelier.
  **Retour** : l'ancien chart (un conteneur).

### Étape 6 : nettoyer Onyxia et stabiliser l'exploitation
- Suspendre `proj-claude-vscode` (ancienne phase 1, en marche depuis deux semaines) et vérifier son
  exposition (code-server sans authentification) ; supprimer le service et l'ingress
  `proj-claude-code-*` sans pod, les deux ingress `chrome-devtools-mcp` sans service ; décider du
  sort de `kap-mcp` (suspendu).
- MCP Onyxia : une instance de production (le déploiement `mcp`) ; l'instance de développement
  reste pour les essais. L'accès d'exploitation ne dépend plus d'un pod de développement qui se
  suspend tout seul.
- **Ces ressources sont à toi** : rien n'est supprimé sans ton accord, ressource par ressource.

### Étape 7 (option) : deux pods
Contrôle et exécution dans deux pods séparés, pour des déploiements indépendants ou plusieurs
personnes. À ne faire que si le besoin apparaît.

## 5. L'ordre et les dépendances

```
E0 ─▶ E1 ─┬─▶ E2 ─┐
          └─▶ E3 ─┴─▶ E4 ─▶ E5a ─▶ E5b ─▶ (E7)
E6 : à tout moment, avec ton accord ressource par ressource
```

E1 est le seul prérequis dur : tant que le store est éphémère, chaque déploiement des étapes
suivantes détruit des données. E2 et E3 peuvent avancer en parallèle. E5b est le plus lourd et se
prépare par E5a.

## 6. À trancher

1. Valider l'étape 1 (lien du store vers le volume, migration non destructive).
2. Plafond mémoire : 12 Gi au total (4 demandés) ou autre ; il n'y a pas de quota de namespace, la
   limite réelle est celle du nœud partagé.
3. S3 pour les sauvegardes : quel espace, quelle durée de conservation.
4. L'archive de migration de 1,8 Go : la sortir du volume ?
5. Étape 5 : retrait de `sudo`, liste blanche d'environnement, jeton par conversation.
6. Quelles ressources Onyxia anciennes supprimer ou suspendre.
