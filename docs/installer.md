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
   `https://raw.githubusercontent.com/nic01asFr/atelier-sspcloud/main/helm-repo`.
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
avec les délais longs qu'exigent les flux d'événements, et une NetworkPolicy
qui ne laisse entrer que l'ingress.

Mettre à jour : relancer le service (l'image `latest` est tirée à chaque
démarrage). Le volume garde tout.

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
son paquet, wikichat, les secrets, les réglages du CLI, puis les trois
processus. Il finit par un bilan et l'endroit où lire la clé owner. Pour le
relancer à la main : `bash ~/work/repos/atelier-sspcloud/install/atelier-init.sh` ;
pour relancer seulement l'Atelier : `~/work/bin/atelier-relancer`.

## Réglages (environnement du pod)

| Variable | Rôle | Défaut |
|---|---|---|
| `ATELIER_LLM_API_KEY` | clé de la passerelle, écrite une fois dans `~/work/.secrets/llm_api_key` | — |
| `ATELIER_OWNER_KEY` | clé owner ; tirée au sort sinon | — |
| `ATELIER_GITHUB_TOKEN` | jeton pour publier un projet sur GitHub | — |
| `GIT_USER_NAME`, `GIT_USER_EMAIL` | identité git de la machine, si elle n'en a pas | — |
| `ATELIER_WORK` | le volume | `$HOME/work` |
| `ATELIER_DEPOT`, `ATELIER_BRANCHE` | d'où vient l'Atelier ; vide = déjà dans l'image | ce dépôt, `main` |
| `WIKICHAT_DEPOT`, `ATELIER_SANS_WIKICHAT` | d'où vient wikichat ; `1` pour s'en passer | `github.com/nic01asFr/wikichat`, `0` |
| `ANTHROPIC_BASE_URL` | la passerelle de modèles | `https://llm.lab.sspcloud.fr/api` |
| `ATELIER_MODELE`, `ATELIER_MODELES_DE_REPLI` | modèles | `qwen3-6-35b-moe` ; `gemma4-26b-moe,qwen3-8-27b` |
| `CODE_SERVER_VERSION`, `NODE_VERSION` | versions épinglées | `4.135.0`, `22.23.2` |

Les réglages du service lui-même (`AtelierSettings`, préfixe `ATELIER_`) se
donnent de la même façon : mode de permission par défaut, fenêtre de
compaction, processus gardés, etc.

## Ce que ça ne fait pas

- **Plusieurs personnes sur un même Atelier.** Une clé owner ouvre tout ; c'est
  un pod par personne. Voir `SECURITY.md`.
- **Vos connecteurs.** Un Atelier neuf n'en a aucun : ils se déclarent dans
  l'onglet Connecteurs. wikichat tourne sur le pod (`127.0.0.1:3777`) et se
  déclare comme les autres, transport `sse`, adresse `http://127.0.0.1:3777/sse`.
- **La clé du modèle après coup.** Si elle manquait au démarrage, chaque tour
  s'arrête sur « apiKeyHelper script is failing » : renseignez le profil et
  relancez le service, ou écrivez-la dans `~/work/.secrets/llm_api_key`.
