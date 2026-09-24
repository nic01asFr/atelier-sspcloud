# Consignes des projets de l'Atelier

Les agents de l'Atelier lisent le `CLAUDE.md` de leur projet, et ceux des
dossiers parents. Jusqu'ici, ces fichiers ne contenaient que la section
`atelier:contexte` posée par l'Atelier : un agent ne savait ni ce qu'était le
projet, ni comment l'Atelier expose ce qu'il produit, ni ce qui lui était
interdit. Les audits du 24 septembre 2026 montrent ce que cela a donné :
serveurs lancés à la main sur des ports que personne ne peut joindre, jetons
commités, documents d'architecture que le code contredit, code qui ne compile
pas et que rien n'importe.

Ce dossier tient ces consignes sous git. Elles se posent sur le pod ainsi :

| Fichier ici | Destination sur le pod |
|---|---|
| `socle.md` | `~/work/projects/CLAUDE.md` (lu par tous les projets, en parent) |
| `chrome-devtools-atelier.md` | `~/work/projects/nouveau-projet/CLAUDE.md` |
| `stt-tts-atelier.md` | `~/work/projects/nouveau-projet-2/CLAUDE.md` |
| `creation-agents-atelier.md` | `~/work/projects/nouveau-projet-4/CLAUDE.md` |
| `transcripts-youtube.md` | `~/work/projects/projet-sans-nom-4/CLAUDE.md` |
| `lecteur-grist.md` | `~/work/projects/projet-sans-nom-5/CLAUDE.md` |

Dans les `CLAUDE.md` de projet, le texte se place **hors** de la section
`<!-- atelier:contexte -->`, que l'Atelier réécrit. Le reste du fichier lui
appartient au projet.

Quand un mécanisme de l'Atelier change (exposition de services, Chrome,
voix), la consigne concernée change dans le même commit.
