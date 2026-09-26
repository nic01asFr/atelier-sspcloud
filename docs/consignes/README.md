# Consignes des projets de l'Atelier

Les agents de l'Atelier lisent le `CLAUDE.md` de leur projet, et ceux des
dossiers parents. Jusqu'ici, ces fichiers ne contenaient que la section
`atelier:contexte` posée par l'Atelier : un agent ne savait ni ce qu'était le
projet, ni comment l'Atelier expose ce qu'il produit, ni ce qui lui était
interdit. Les audits du 24 septembre 2026 montrent ce que cela a donné :
serveurs lancés à la main sur des ports que personne ne peut joindre, jetons
commités, documents d'architecture que le code contredit, code qui ne compile
pas et que rien n'importe.

Ce dossier tient ces consignes sous git, sauf le socle, qui vit avec le code.
Elles se posent sur le pod ainsi :

| Fichier | Destination sur le pod |
|---|---|
| [`atelier-src/mcp_gateway/atelier/consignes/socle.md`](../../atelier-src/mcp_gateway/atelier/consignes/socle.md) | `~/work/projects/CLAUDE.md` (lu par tous les projets, en parent), **posé automatiquement** |
| `chrome-devtools-atelier.md` | `~/work/projects/nouveau-projet/CLAUDE.md` |
| `stt-tts-atelier.md` | `~/work/projects/nouveau-projet-2/CLAUDE.md` |
| `creation-agents-atelier.md` | `~/work/projects/nouveau-projet-4/CLAUDE.md` |
| `transcripts-youtube.md` | `~/work/projects/projet-sans-nom-4/CLAUDE.md` |
| `lecteur-grist.md` | `~/work/projects/projet-sans-nom-5/CLAUDE.md` |

Le socle est la règle de conduite des agents code : ce qui revient à la
personne, les secrets, ce qu'il faut savoir pour montrer une création au-delà
de la section générée, le navigateur, les processus, les hooks, la vérité des
documents, git. Ce que la section `<!-- atelier:contexte -->` générée par
l'Atelier (`project_context.py`) dit déjà — liste des outils, manière de
montrer une création, joindre un autre projet, le web — n'y est pas répété :
cette section fait foi. Le socle est lu à chaque tour par chaque agent ; il
tient en 1 300 mots au plus (un test le vérifie).

Il se pose en `~/work/projects/CLAUDE.md`, et pas dans un fichier importé,
parce que Claude Code lit le `CLAUDE.md` du dossier parent sur toutes les
surfaces sans rien demander, alors qu'un import `@` hors du dossier du projet exige une
approbation que l'Atelier ne pose que pour l'Assistant. Le guide complet,
pour les lecteurs du dépôt, est [`../fonctionnalites.md`](../fonctionnalites.md).

**Le socle se pose seul.** Il fait partie du paquet (données du paquet dans
`pyproject.toml`), donc de l'image comme de l'extraction de `atelier-src` sur
un pod. `install/atelier-init.sh` (`python3 -m mcp_gateway.atelier.socle`) et
le démarrage de l'Atelier (donc `atelier-relancer`) le posent
(`atelier/socle.py`) :

- écriture atomique ; rien n'est réécrit quand le texte est déjà le bon ;
- l'empreinte du texte posé est notée dans `~/work/.atelier-etat/socle.json` ;
- un fichier dont l'empreinte n'est pas celle de la dernière pose (modifié à
  la main, ou recopié avant que l'Atelier ne s'en charge) est gardé en copie
  datée sous `~/work/.atelier-etat/socle/`, l'événement va au journal unique
  (acteur `atelier:socle`), puis le socle du code le remplace. Un ajout à
  garder se reporte dans le fichier du paquet, ou dans le `CLAUDE.md` d'un
  projet.

**Les consignes de projet ne se posent pas seules** : elles se recopient à la
main sur le pod après chaque changement.

Dans les `CLAUDE.md` de projet, le texte se place **hors** de la section
`<!-- atelier:contexte -->`, que l'Atelier réécrit. Le reste du fichier lui
appartient au projet.

Quand un mécanisme de l'Atelier change (exposition de services, Chrome,
voix), la consigne concernée change dans le même commit.
