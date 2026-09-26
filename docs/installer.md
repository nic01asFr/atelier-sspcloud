# Installer l'Atelier sur SSPCloud

Un utilisateur SSPCloud lance « Atelier » dans le catalogue Onyxia et obtient
le sien : ses conversations, ses projets, ses connecteurs, sa face VS Code —
sur son propre pod, avec sa propre clé de modèles. Rien à saisir : l'adresse,
la clé du modèle et l'identité git viennent de son profil.

## Par le catalogue Onyxia — le chemin normal

1. **Le profil.** Dans Onyxia, *Mon compte › Assistant IA* : la clé d'API de
   `https://llm.lab.sspcloud.fr` et, si vous voulez, le modèle. *Mon compte ›
   Git* : nom et courriel — ce sont eux qui signeront les commits des projets.
2. **Le catalogue.** Ajoutez, une fois, le dépôt de charts de l'Atelier :
   `https://nic01asfr.github.io/atelier-sspcloud`.
   L'ancienne adresse,
   `https://raw.githubusercontent.com/nic01asFr/atelier-sspcloud/main/helm-repo`,
   est dépréciée : elle reste servie pendant une version de transition, puis
   sera retirée.
3. **Lancer « Atelier ».** Le formulaire est pré-rempli ; la taille du volume
   (10 Go) et les ressources (2 à 8 Go de mémoire) suffisent d'ordinaire.
4. **Ouvrir.** L'adresse est `https://user-<idep>-atelier.user.lab.sspcloud.fr`.
   La page demande la clé owner, lue dans les notes d'installation du service
   (ou, depuis un terminal du pod, `cat ~/work/.secrets/atelier_owner_key`).
5. Écrivez un premier message : le projet naît avec la conversation.

Ce que le chart pose : un pod à partir de l'image `ghcr.io/nic01asfr/atelier`
(même base que le Jupyter du catalogue, avec node, code-server, l'extension
Claude Code, wikichat et l'Atelier déjà dedans), un volume `~/work` qui
survit au service, un Secret pour la clé owner et la clé du modèle, l'ingress
avec les délais longs qu'exigent les flux d'événements, un second ingress pour
l'hôte des applications (`user-<idep>-atelier-apps…`, port 8788 : créations,
bureaux, écran du navigateur ; `apps.enabled`, actif par défaut), et une
NetworkPolicy qui ne laisse entrer que l'ingress. L'ingress n'ajoute aucune
authentification : c'est la clé owner qui garde l'entrée (voir `SECURITY.md`).

Mettre à jour : relancer le service (l'image `latest` est tirée à chaque
démarrage). Le volume garde tout.

## Depuis un terminal, sans le catalogue

Depuis un service Onyxia (Jupyter, VS Code) lancé avec *Kubernetes › accès
depuis le service : oui* et *rôle : edit* :

```bash
curl -fsSL https://nic01asfr.github.io/atelier-sspcloud/install.sh | bash
```

Le script ajoute le dépôt Helm, pose l'adresse
`https://user-<idep>-atelier.user.lab.sspcloud.fr`, reprend l'identité git du
service et, si elle est dans l'environnement, la clé du modèle
(`ATELIER_LLM_API_KEY=... bash install.sh`), puis lance
`helm upgrade --install`. Relancé, il met à jour sans perdre ni la clé owner
ni la clé du modèle. Il finit par les notes d'installation et la clé owner.

À la main, c'est la même chose :

```bash
helm repo add atelier https://nic01asfr.github.io/atelier-sspcloud
helm upgrade --install atelier atelier/atelier \
  --set ingress.hostname=user-<idep>-atelier.user.lab.sspcloud.fr \
  --set-string llm.apiKey=<clé de llm.lab.sspcloud.fr>
```

## Sur un Jupyter du catalogue officiel — le chemin de secours

Pour un pod déjà garni, ou sans le chart :

| Réglage du service *Jupyter python* | Valeur |
|---|---|
| Ressources | 2 CPU, 6 Go de mémoire au moins |
| Volume persistant | activé |
| Réseau → port personnalisé | `8787` — exposé sous `https://user-<idep>-<service>.user.lab.sspcloud.fr` |
| Vault | un chemin contenant `ATELIER_LLM_API_KEY` |
| Init → script personnel | `https://raw.githubusercontent.com/nic01asFr/atelier-sspcloud/main/install/atelier-init.sh` |

Le script est rejoué à chaque démarrage et ne refait que ce qui manque :
node et npm, code-server et l'extension Claude Code, le clone de l'Atelier et
son paquet, wikichat, les secrets, les réglages du CLI, puis les cinq
processus : relais LLM, code-server, wikichat, gardiens et Atelier. Il finit par un bilan et l'endroit où lire la clé owner. Pour le
relancer à la main : `bash ~/work/repos/atelier-sspcloud/install/atelier-init.sh` ;
pour relancer seulement l'Atelier : `~/work/bin/atelier-relancer`.

Ce chemin n'expose que le port 8787 : sans second hôte, il n'y a pas d'hôte des
applications, et « Ouvrir » reste grisé pour les créations et les bureaux.

## Réglages (environnement du pod)

| Variable | Rôle | Défaut |
|---|---|---|
| `ATELIER_LLM_API_KEY` | clé de la passerelle, écrite une fois dans `~/work/.secrets/llm_api_key` | — |
| `ATELIER_OWNER_KEY` | clé owner ; tirée au sort sinon | — |
| `ATELIER_GITHUB_TOKEN` | jeton pour publier un projet sur GitHub | — |
| `ATELIER_GITHUB_OWNER` | compte ou organisation GitHub où publier un projet | — |
| `ATELIER_GARDIENS`, `ATELIER_GARDIENS_PORT` | `0` pour ne pas lancer les gardiens ; port de leur API locale | `1`, `8791` |
| `GIT_USER_NAME`, `GIT_USER_EMAIL` | identité git de la machine, si elle n'en a pas | — |
| `ATELIER_WORK` | le volume | `$HOME/work` |
| `ATELIER_DEPOT`, `ATELIER_BRANCHE` | d'où vient l'Atelier ; vide = déjà dans l'image | ce dépôt, `main` |
| `WIKICHAT_DEPOT`, `ATELIER_SANS_WIKICHAT` | d'où vient wikichat ; `1` pour s'en passer | `github.com/nic01asFr/wikichat`, `0` |
| `ANTHROPIC_BASE_URL` | la passerelle de modèles | `https://llm.lab.sspcloud.fr/api` |
| `ATELIER_RELAIS_LLM_PORT` | port du relais LLM (boucle locale), par qui toutes les surfaces parlent au modèle ; `ATELIER_RELAIS_LLM=0` s'en passe (plus de compaction native) | `8790` |
| `ATELIER_MODELE`, `ATELIER_MODELE_OPUS`, `ATELIER_MODELES_DE_REPLI` | modèle principal, créneau opus, replis (le dernier sert aussi haiku) | `qwen3-6-35b-moe` ; `qwen3-6-35b-moe` ; `qwen3-8-27b` |
| `CODE_SERVER_VERSION`, `NODE_VERSION` | versions épinglées | `4.135.0`, `22.23.2` |

`gemma4-26b-moe` n'est plus proposé à Claude Code (ni créneau opus, ni repli) :
mesuré le 25/09/2026, il échoue dès le premier tour (`'None' has no attribute
'split'`). Un pod installé avant garde son `settings.json` ; l'Atelier l'en
retire à son démarrage (`MODELES_ECARTES`, `write_claude_settings_env`).

Les réglages du service lui-même (`AtelierSettings`, préfixe `ATELIER_`) se
donnent de la même façon : mode de permission par défaut, fenêtre de
compaction, processus gardés, etc.

## Ce que ça ne fait pas

- **Plusieurs personnes sur un même Atelier.** Une clé owner ouvre tout ; c'est
  un pod par personne. Voir `SECURITY.md`.
- **Vos connecteurs.** Un Atelier neuf n'a que ses propres services (dont le
  navigateur des agents, `chrome-devtools-mcp`, déclaré d'office) : les vôtres
  se déclarent dans l'onglet Connecteurs. wikichat tourne sur le pod (`127.0.0.1:3777`) et se
  déclare comme les autres, transport `sse`, adresse `http://127.0.0.1:3777/sse`.
- **La clé du modèle après coup.** Si elle manquait au démarrage, chaque tour
  s'arrête sur « apiKeyHelper script is failing » : renseignez le profil et
  relancez le service, ou écrivez-la dans `~/work/.secrets/llm_api_key`.
