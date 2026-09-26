# Guide de l'interface

Les règles retenues par le refine de l'interface (v4), pour que les équipes
suivantes restent cohérentes. L'audit qui les motive est dans
`docs/ui/audit.md`. Le code : `atelier-src/mcp_gateway/atelier/web/`.

## Principes

1. **Le geste se voit tout de suite.** Un clic change l'écran dans l'image qui
   suit : on ouvre, on referme, on grise, puis le service confirme. Si le
   service refuse, on revient en arrière et on dit pourquoi. On n'attend
   jamais une réponse réseau avant le premier retour visuel.
2. **On ne reconstruit que ce qui change.** Un rendu qui refait un nœud sous
   le pointeur perd le clic, le survol et le focus. Liste : empreinte, puis
   mise à jour ciblée (`empreinteDeLArbre`, `synchroniserNoeuds`). Aucune
   veille périodique ne redessine une vue qu'elle ne concerne pas.
3. **Le clair d'abord, le technique en dépliant.** Une phrase en français au
   premier plan ; le nom d'outil, le JSON, le code de sortie sous « Détails
   techniques » ou dans un pli. Rien ne disparaît : tout reste accessible.
4. **Une seule façon de faire chaque chose** : un bouton principal par zone,
   les mêmes badges d'état, les mêmes icônes, les mêmes confirmations.

## Jetons

**Couleurs : `css/jetons.css`, et nulle part ailleurs.** Ce fichier est
généré depuis une table (nom, valeur sombre, valeur claire) : les deux thèmes
ont exactement les mêmes jetons. `app.css` n'écrit aucune couleur —
`tests/js/jetons.suite.mjs` échoue sinon, et vérifie que chaque jeton sombre a
son pendant clair. Pour une couleur neuve : l'ajouter aux deux thèmes, en
mesurer le contraste, le consigner dans l'audit.

**Le reste (`css/app.css`, `:root`)** : espacements, rayons, tailles de
texte, polices, durées. Les anciens noms de couleur (`--bg`, `--text`,
`--muted`, `--danger`…) sont des alias des jetons, gardés pour les règles qui
les emploient.

| Famille | Jetons | Usage |
|---|---|---|
| Surfaces | `--surface-0` (barres), `--surface-1` (page), `--surface-2` (cartes, champs), `--surface-3` (bulle, menus) ; `--surface-survol`, `--surface-active` | du plus bas au plus haut |
| Texte | `--texte-1` (principal), `--texte-2` (secondaire), `--texte-3` (discret) ; `--sur-accent`, `--sur-erreur` | tous AA sur toutes les surfaces |
| États | `--ok`, `--attention`, `--erreur`, `--info`, `--focus` ; `--accent` pour l'action principale ; `--x-fond` / `--x-texte` pour les badges | pastilles, badges, bordures |
| Divers couleurs | `--line`, `--bordure-champ` (3:1), `--code-fond`, `--hl-*` (coloration), `--voile`, `--bandeau-fond` / `-texte`, `--ombre-1`, `--ombre-2` | |
| Espacements | `--esp-1` à `--esp-6` (4, 8, 12, 16, 24, 32 px) | marges, écarts |
| Rayons | `--rayon-1` (4), `--rayon-2` (6, boutons et champs), `--rayon-3` (10, cartes), `--rayon-4` (14, bulles), `--rayon-rond` | |
| Tailles | `--t-xs` 12 px, `--t-s` 13 px, `--t-m` 14 px, `--t-base` 15 px, `--t-l`, `--t-xl` | pas d'autre taille, rien sous 12 px |
| Polices | `--font` (IBM Plex Sans), `--display` (Fraunces, titres de page seulement), `--mono` (code, noms techniques) | |
| Divers | `--duree` (120 ms), `--colonne-fil` (52 rem) | |

**Thèmes.** Trois choix, retenus par personne (« Affichage » dans
l'en-tête, `ui.theme` côté service) : suivre le système (défaut, pas
d'attribut), clair (`<html data-theme="clair">`), sombre
(`data-theme="sombre"`). `js/theme-initial.js`, chargé de façon bloquante
avant les feuilles de style, pose l'attribut depuis la copie locale : aucun
éclair au chargement.

**Contrastes visés.** Texte courant du fil : AAA (7:1). Tout autre texte :
AA (4,5:1). Bordures de champ, focus, icônes porteuses de sens : 3:1. Le
retrait d'un texte passe par `--texte-2` ou `--texte-3`, jamais par
l'opacité. Rien sous 12 px.

## Composants

**Boutons.** `primary` (action principale, une par zone), `ghost btn-sm`
(secondaire, bordé), `ghost btn-sm danger` ou classe dédiée pour détruire (mot
rouge, bordure rouge atténuée), `icon-btn` (icône seule, 28 px, 40 px au
doigt, toujours avec `aria-label`), `linklike` (lien dans une phrase). Un
bouton principal désactivé prend la surface neutre, jamais une opacité.

**Champs.** Dans un `.field` : libellé au-dessus (`--texte-2`, `--t-s`), aide
en dessous (`.modal-hint`), 34 px de haut, `--rayon-2`, `--surface-1`.
Listes, zones de texte et recherches ont la même allure. Une liste de plus
d'une vingtaine d'entrées a un champ de recherche (voir `filtrerOutils`).

**Cartes et lignes.** Une ligne cliquable qui porte ses propres boutons reste
un `<li>` rendu activable (`rendreActivable` : rôle, tabulation, Entrée,
Espace). Élément actif : `--surface-active` et trait d'accent à gauche.

**Badges d'état.** `mcp-badge` + `-ok` / `-stdio` (info) / `-warn` / `-err` /
`-off`, en français (« active », « brouillon », « connecté »). Un badge ne
déborde pas : tronqué, texte complet en `title`. Pastilles de liste :
`status-dot-ok|busy|warn|err|off`.

**Icônes.** Uniquement `ui/icones.js` (`icone(nom)` ou `svgIcone(nom)` pour
du HTML statique) : tracés SVG au trait de 2, `currentColor`, taille `1em`,
toujours `aria-hidden`. **Aucun emoji** dans l'interface
(`tests/js/sans-emoji.suite.mjs` y veille). Pour une icône neuve : l'ajouter à
la table, sur une grille de 24.

**Plis.** `<details>` avec un `<summary>` sans marqueur natif, chevron
`chevron-droite` tourné de 90° quand ouvert. Un pli garde l'état que la
personne lui a donné d'un rendu à l'autre.

**Menus et panneaux flottants.** `.popover` : `--surface-3`, `--rayon-3`,
`--ombre-2`. Ils se referment par Échap (le focus revient au bouton qui les a
ouverts), par un clic ailleurs, ou par leur bouton (`aria-expanded`).

**États vides, chargement, erreur.** Vide : une phrase qui dit ce qui
apparaîtra là, en texte courant, alignée à gauche. Chargement de plus de
200 ms : squelette (`.fil-squelette`) ou ligne « Lecture de … ». Erreur : dite
en français, jamais un code brut (`causeLisible`) ; bandeau pour ce qui
bloque, message dans le fil pour ce qui concerne un tour.

## Le fil de conversation

- Un tour : message de la personne (bulle à droite) ; « Voir les étapes (n) »
  replié ; ce qui ne se replie jamais ; la réponse (texte de la page, sans
  bulle) ; pied « heure · Copier · Relancer ».
- Une étape par appel d'outil, libellée par `libelleEtape` (`ui/etapes.js`).
  Un outil neuf ou un connecteur connu : ajouter sa ligne à la table, avec son
  test dans `etapes.suite.mjs`. Un libellé tient en une phrase courte, verbe
  d'abord (« Lecture de api.py », « Clic sur un élément »).
- Ne se replient jamais : autorisations, questions, étapes en erreur ou
  refusées, cartes d'action, messages du système.
- Pendant le flux, la ligne vivante dit l'étape en cours ; rien ne saute.
- « Détails techniques » : deux réglages de la personne, retenus par le
  service (`fil_raisonnement`, `fil_actions` dans `/v1/meta`).

## Clavier et accessibilité

| Touche | Effet |
|---|---|
| `/` | aller au composeur (hors d'un champ de saisie) |
| `Alt+N` | nouvelle conversation (Code ou Assistant) |
| `Échap` | refermer le panneau ou le menu ouvert (« Affichage », « Détails techniques ») |
| `Entrée` / `Maj+Entrée` | envoyer / aller à la ligne, dans le composeur |
| `Entrée` / `Espace` | activer une ligne ou une carte ayant le focus |

Focus visible au clavier (`:focus-visible`, `--focus`), jamais à la souris.
Cibles de 28 px au moins, 40 px au doigt. Contraste AA : n'employer que les
jetons de texte. `prefers-reduced-motion` coupe les animations. Qui parle
dans le fil se dit au lecteur d'écran (« Vous », « Claude », « Assistant »).

## Mise en page

- Grand écran : colonne de lecture de 52 rem pour le fil et le composeur ;
  les fiches plafonnent à 60 rem.
- De 721 à 1280 px avec le panneau ouvert : la liste des conversations se
  retire, fil et panneau se partagent l'écran ; tout niveau accepte de se
  réduire (`min-width: 0`).
- Téléphone (≤ 720 px) : navigation sur sa propre ligne, défilante ; bascule
  liste / détail ; le panneau en feuille plein écran.

## Réservé

Le futur bouton micro (dictée) se place à gauche d'« Envoyer », au gabarit de
la pièce jointe (`composer-tool-btn`, icône `micro`). L'emplacement est noté
dans `index.html` ; l'étude est dans `docs/vision/voix.md`.
