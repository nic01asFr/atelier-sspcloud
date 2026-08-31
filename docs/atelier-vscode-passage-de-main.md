# Atelier → VS Code : le passage de main

Depuis une conversation de l'Atelier, le lien « VS Code » doit ouvrir la fenêtre
code-server du pod avec **l'extension Claude Code affichant cette
conversation-là**. Ce document décrit le mécanisme et, surtout, pourquoi il est
indirect : plusieurs chemins plus simples ont été essayés et mesurés fermés.

---

## 1. Ce qui ne marche pas, et pourquoi

Ces constats ont été vérifiés sur le pod, avec code-server 4.135 et l'extension
Claude Code 2.1.251. Ils expliquent la forme du mécanisme actuel.

| Piste | Résultat mesuré |
|-------|-----------------|
| `code-server --open-url` | l'option n'existe plus dans cette version |
| `code-server --open-external "vscode://…"` | passe l'adresse au **navigateur**, qui ne connaît pas le schéma `vscode:` — une fenêtre code-server vide s'ouvre par appel |
| Paramètres d'URL du workbench | les seules clés lues sont `openFile`, `gotoLineMode`, `diffFile*`, `mergeFile*` — ouvrir un fichier, rien d'autre |
| `defaultLayout` | option de construction du workbench, non exposée par code-server |
| Réglages `claudeCode.*` | `preferredLocation` dit **où** Claude s'ouvre, pas **qu'il** s'ouvre |
| Tâche `folderOpen` + script shell | un script ne peut pas appeler une commande VS Code |

Il reste une seule voie : une extension, qui appelle
`vscode.commands.executeCommand("claude-vscode.primaryEditor.open", sessionId)`.
L'extension Claude Code enregistre aussi un gestionnaire d'URI
(`vscode://anthropic.claude-code/open?session=…`) qui fait exactement cela, mais
rien ne peut le déclencher depuis le web.

---

## 2. Le filtre qui rendait les conversations invisibles

L'extension écarte de sa liste de sessions tout transcript dont le champ
`entrypoint` vaut `sdk-cli`, `sdk-ts` ou `sdk-py` : la classe qui sert ses
webviews pose `includeProgrammaticSessions = false` en dur. Une conversation
ainsi masquée n'est pas seulement absente de la liste — elle est **irrécupérable**
: le webview répond `restore_declined` et ouvre une conversation neuve à la
place, sans message d'erreur.

Or le CLI écrit `sdk-cli` dès qu'on l'appelle avec `-p`, ce que le harnais de
l'Atelier fait à chaque tour, y compris pour une discussion tenue par quelqu'un.
La variable `CLAUDE_CODE_ENTRYPOINT` ne corrige rien : testée, elle est ignorée
en mode `-p`.

**Correction retenue** (`vscode_handoff.rendre_visible_a_l_extension`) : la
marque est réécrite **sur place et à longueur égale** — `"sdk-cli"` devient
`"cli"` suivi de quatre espaces, que JSON tolère entre deux jetons. Ni
troncature ni réécriture du fichier, donc rien à perdre si `claude` y écrit au
même instant : il n'ajoute qu'en fin, et on ne touche que la tête.

Seule la **première** marque compte : l'extension lit les 65 536 premiers octets
et s'arrête à la première qu'elle rencontre. La correction est donc définitive et
idempotente, quels que soient les tours ajoutés ensuite.

---

## 3. Les pièces du mécanisme

**`GET /v1/vscode/open?slug=…&session=…`** (`api.py`) — la page désigne la
conversation par son identifiant *Atelier* ; le CLI la connaît parfois sous un
autre, notamment pour les conversations nées dans VS Code et adoptées. La porte
résout l'un vers l'autre (`SessionStore.identifiant_claude`), retient le
**dossier de la fiche** — une conversation « assistant » travaille dans son
propre répertoire, pas dans `projects/<slug>` — prépare ce dossier, puis redirige
vers le proxy `/vscode/`.

**`prepare_vscode_handoff`** (`vscode_handoff.py`) — dépose dans ce dossier les
réglages de fenêtre, la marque d'ouverture, et corrige la marque `entrypoint`.
Les secrets ne vont **que** dans les réglages utilisateur : un dossier de projet
se partage et se versionne.

**`.atelier/session.json`** — la consigne : quelle conversation ouvrir. Elle vaut
pour une ouverture, pas pour toutes les suivantes.

**Extension `atelier-ouvre-claude`** (`atelier-src/vscode-extension/`) — s'éveille
sur `onStartupFinished`, lit la consigne **et la supprime**, attend que la
commande de Claude Code existe, ferme les panneaux Claude que VS Code vient de
restituer — restitués, ils reviennent vides — puis ouvre la bonne conversation.
Sans consigne, elle ne touche à rien.

---

## 4. Les deux listes se confondent

Le principe : ce que Code montre, l'extension doit le montrer, et
réciproquement.

**Atelier → extension** : `sync_claude_titles` corrige la marque de chaque fiche,
une fois par conversation.

**Extension → Atelier** : `adopter_conversations_claude` fait entrer les
conversations nées dans VS Code. Elle adopte exactement ce que l'extension
accepte de montrer — un transcript dans le dossier d'un projet connu, réclamé par
aucune fiche, non marqué comme programmatique. Ce dernier point écarte de
lui-même les restes d'essais du harnais. Une conversation supprimée est inscrite
dans un journal de refus, faute de quoi elle reviendrait à la synchronisation
suivante.

**Les noms** : un renommage dans l'Atelier est écrit dans le transcript au format
de l'extension elle-même — une ligne `{"type":"custom-title",…}` ajoutée en fin
de journal, qu'elle relit comme un renommage.

---

## 5. Le journal de conversation

Le transcript de l'Atelier ne conserve que les enregistrements dont l'affichage
se sert — `user`, `assistant`, `result`. Le flux du CLI en contient bien
d'autres : chaque fragment de texte arrive en `stream_event`, et les garder
gonflait le journal d'un facteur dix, que le navigateur retéléchargeait et
relisait à chaque ouverture. L'affichage en direct passe par le canal SSE, pas
par ce fichier.

Le harnais y inscrit aussi **la question posée** : le CLI la reçoit en argument
et ne la réémet pas dans son flux. Sans cette ligne, une conversation relue
ailleurs n'aurait plus que les réponses.

---

## 6. Limites connues

- Une conversation sans session Claude — jamais lancée, ou dont le journal a été
  perdu — ne peut pas s'ouvrir dans VS Code : l'extension en créerait une neuve.
- `dossier_transcripts_claude` ne résout pas les liens symboliques là où
  `vscode_bridge.folder_abs` le fait. Sans lien sur `~/work` les deux coïncident
  ; le jour où l'arborescence en porte un, il faudra traiter ensemble le
  répertoire de travail du harnais, celui de la porte et celui des transcripts.
- Fermer les panneaux Claude restitués ferme aussi une conversation qu'on aurait
  laissée ouverte dans ce dossier. Elle n'est pas perdue — elle reste dans
  l'historique de l'extension.
