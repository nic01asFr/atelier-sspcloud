# Le kit de l'Atelier : commandes, hooks et sous-agents communs

*Statut : cadre à valider. Issu des deux études du 02/10/2026 (inventaire du
dépôt, capacités du CLI 2.1.287 en `-p`/stream-json) et d'essais réels sur le
pod. Complète [`outils-profils-et-auto-evolution.md`](outils-profils-et-auto-evolution.md)
et [`../structure-projet.md`](../structure-projet.md).*

## 1. Constat

L'Atelier ne fournit lui-même ni commande, ni skill, ni sous-agent, et un seul
hook de sécurité (`PreToolUse` sur `Bash`). Ce qui existe sur le pod vient de
wikichat (4 commandes, 1 skill, les hooks de session) ou d'un projet
(`nouveau-projet-4` : 7 sous-agents). Résultat : `/verifier`, `/reprendre`,
`/fin-de-lot`, `/proposer` sont annoncées (`structure-projet.md`) et
absentes ; trois documents de vision citent `/verifier` comme acquise.

Mesuré sur le pod (CLI 2.1.287, `-p --input-format stream-json`) :

| Question | Résultat |
|---|---|
| Une commande de projet (`.claude/commands/x.md`) est-elle chargée et exécutée ? | **Oui** : listée dans `slash_commands` à l'initialisation, exécutée. |
| Un skill de projet, un sous-agent de projet ? | **Oui** : listés (`skills`, `agents`). |
| `PostToolUse` se déclenche-t-il avec `--settings` ? | **Oui**, et reçoit `tool_name`. |
| Une commande inconnue (`/verifier`) ? | Traitée comme texte : le modèle répond qu'elle n'existe pas. |
| Les hooks de session sont-ils visibles dans le flux ? | Oui (`hook_started`, `hook_response`). |

Non mesuré : héritage MCP d'un sous-agent (un sous-agent n'hérite ni de
`--settings` ni de `--strict-mcp-config` selon la doc ; à tester avant de lui
confier quoi que ce soit), `--plugin-dir`.

## 2. Principe : un seul kit, posé là où le CLI le lit partout

Le même texte doit valoir dans l'Atelier, dans VS Code et au terminal
(principe déjà tenu pour le contexte du projet). Le kit est donc posé dans
`~/.claude` (`commands/`, `skills/`, `agents/`) et dans le fichier de
réglages unique, par la mécanique qui existe déjà (`claude_home.py` :
fusion des hooks de plusieurs auteurs, recopie `skills`/`commands`), et non
par `--plugin-dir`, qui ne vaudrait que pour les tours de l'Atelier.

- **Source** : un dossier versionné du dépôt, `atelier-src/kit/`
  (`commands/`, `skills/`, `agents/`, `hooks/`), copié dans l'image.
- **Pose** : au démarrage, idempotente, sans jamais écraser un fichier qui
  n'est pas le nôtre. Nos fichiers portent la ligne `<!-- atelier-kit:<version> -->`
  (ou un champ `atelier-kit` dans l'en-tête) ; un fichier sans cette marque
  est celui de la personne ou d'un projet et reste intact.
- **Précédence** : un fichier du projet (`.claude/commands/verifier.md`) l'emporte
  sur celui du kit, ce que le CLI fait déjà ; un projet peut donc adapter.
- **Contrôle** : `coherence.py` vérifie, comme il le fait déjà pour
  `garde_bash`, que chaque élément du kit est présent et que chaque hook
  s'exécute à blanc.

## 3. Contenu

### 3.1 Commandes (lot K1)

Elles lisent `projet.json` (`commandes.preparer|tests|verifier`,
`chemins_proteges`) et les fichiers du gabarit (`ETAT.md`, cahier, décisions).

| Commande | Fait | Ne fait pas |
|---|---|---|
| `/reprendre` | Résume ETAT, cahier, décisions, commits depuis le dernier jalon ; dit la prochaine étape. | Rien d'écrit. |
| `/verifier` | Lance les commandes `verifier` (et `tests`) de `projet.json` ; rend un constat court, avec la sortie utile des échecs. Sans commande déclarée, le dit et propose de la déclarer. | Ne corrige pas : constate. |
| `/fin-de-lot` | Vérifie ; réécrit ETAT ; journal et décisions ; commit local ; étiquette `jalon/<lot>` ; s'arrête. | Ne pousse jamais. |
| `/proposer <artefact>` | Dépose la proposition de mise en production (« À valider »). | Ne promeut pas : c'est la personne. |

### 3.2 Hooks (lot K2)

| Événement | Rôle | Échec |
|---|---|---|
| `PostToolUse` (tous outils) | Une ligne par outil dans `~/work/.atelier/journal-outils/<conversation>.jsonl` : heure, outil, résumé court, succès. Sert la supervision, la traçabilité et la reprise. Ne contient ni sortie d'outil ni secret. | Ne bloque jamais. |
| `PreToolUse` sur `Write`, `Edit`, `MultiEdit`, `NotebookEdit` | Refuse `.secrets`, `.git`, et les `chemins_proteges` du projet. | **Fermé** : doute = refus, avec la raison rendue à l'agent. |
| `PreToolUse` sur `Bash` | Déjà posé (`garde_bash`). Y ajouter les chemins protégés du projet. | Fermé. |
| `Stop` (vérification de fin) | Facultatif, lot ultérieur : si le tour annonce « fini » sans `ETAT.md` à jour, redonne la main une fois. | Ouvert, une seule fois. |

Les hooks du kit ne s'exécutent que dans une conversation de l'Atelier
(variable `ATELIER_SESSION`) ou un projet qui les demande ; ils ne gênent ni
wikichat ni un usage hors Atelier.

### 3.3 Sous-agents (lot K3)

- `relecteur` : lit un diff ou un dossier, rend les défauts classés ; outils
  `Read`, `Grep`, `Glob`.
- `verificateur` : rejoue `/verifier` et rend le constat ; outils `Read`,
  `Bash` borné par les règles du projet.

Ni l'un ni l'autre n'écrit. L'Assistant ne les reçoit pas (il se voit déjà
refuser `Task`/`Agent`). À ne confier qu'après l'essai d'héritage MCP.

## 4. Ordre

1. **K1** : les quatre commandes, la pose idempotente, le contrôle de cohérence.
   Corriger les trois documents qui citent `/verifier` comme acquise.
2. **K2** : `PostToolUse` (journal) et garde d'édition ; les deux sont testés
   à blanc par `coherence.py`.
3. **K3** : sous-agents, après l'essai d'héritage MCP.
4. **K4** : lien avec la supervision (le journal d'outils alimente
   `atelier_lancements`), et `Stop` de vérification.

## 5. Risques et limites

- Un hook qui échoue ouvert sur une garde de sécurité est un faux confort :
  les gardes sont fermées, le journal est ouvert.
- Un fichier du kit modifié à la main est repris à la prochaine pose, sauf si
  la marque a été retirée : c'est voulu, et dit dans le fichier.
- `PostToolUse` ne doit rien contenir de sensible : il n'enregistre pas les
  sorties, et filtre les arguments (`Bash` : la commande tronquée, sans les
  valeurs qui ressemblent à des clés).
- Les commandes sont des consignes au modèle, pas du code : `/verifier` lance
  ce que `projet.json` déclare, mais un modèle peut mal le restituer. Le
  journal d'outils permet de le constater.
