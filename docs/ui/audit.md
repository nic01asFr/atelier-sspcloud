# Audit de l'interface de l'Atelier

Équipe interface, 26 septembre. Audit fait sur l'Atelier déployé
(`main` = `20e6235`), en lecture seule, dans le Chrome de Nicolas : à 1440 px,
1024 px et 390 px (mobile), avec les temps réseau (`performance`), l'arbre
d'accessibilité et la console. Les corrections sont sur la branche
`v4-interface`. Elles ont été vérifiées sur une instance locale de l'Atelier
(harnais factice, transcrits réels en fixtures) : les captures « après » en
viennent.

Captures : `docs/ui/avant/` (le pod), `docs/ui/apres/` (l'instance locale).
Le numéro d'une capture renvoie au même écran dans les deux dossiers.

> **Incident pendant l'audit.** Des onglets ouverts par cette équipe ont été
> fermés à plusieurs reprises pendant la mission, et le Chrome piloté est
> alors revenu sur l'onglet de Nicolas. Un script destiné à l'instance locale
> s'est ainsi exécuté sur le pod : il a envoyé le message « Montre-moi la
> structure du projet » dans la conversation « Essai du navigateur : ouvre ».
> Le tour a été arrêté aussitôt (session « interrompue », aucune autorisation
> accordée, l'outil demandé — lister un dossier — ne s'est pas exécuté). Le
> message reste dans l'historique de cette conversation. Depuis, chaque
> script vérifie l'hôte et un marqueur posé sur l'onglet de l'équipe avant
> d'agir.

## Synthèse

| Gravité | Nombre | Corrigés |
|---|---|---|
| Bloque ou trompe l'usage | 10 | 10 |
| Gênant | 21 | 16 |
| Cosmétique | 12 | 10 |
| Compositions (§ 5) | 10 : 1 bloquant, 7 gênants, 2 cosmétiques | 8 |
| Thèmes et contrastes (§ 5 bis) | 8 : 7 gênants, 1 cosmétique | 8 |

Plus la présentation du fil en étapes (§ 4), demandée en cours de mission.

---

## 1. Bloque ou trompe l'usage

### B1. Un clic sur une conversation ne l'ouvre pas (tout de suite)
*Vue Code, barre latérale.* Capture `avant/01`, `avant/02`.

Mesuré : le clic lance `GET /sessions/<id>` puis `GET …/transcript`
(3,3 s pour la conversation « Lecteur .grist » de 24 tours), puis une relecture
de toute la liste (`GET /sessions?sync_titles`, 0,5 s) ; l'écran ne change
qu'après les trois. Pendant 4 s, le fil reste sur « Nouvelle conversation » :
on croit le clic perdu, on reclique.

*Cause* : `controllers/sessions.js`, `selectSession` attend tout avant le
premier `render()`. Deux clics rapprochés se croisent aussi : la lecture la
plus lente gagne et rend la conversation précédente.

*Correctif* : la conversation connue de la liste ouvre le fil tout de suite
(titre, ligne active, squelette de chargement) ; transcrit et fiche sont lus en
parallèle ; la liste se relit après, sans retenir l'écran ; un rang
d'ouverture écarte une lecture dépassée. Mesuré en local : 25 ms entre le clic
et le fil ouvert. **Corrigé.**

### B2. Une ouverture en cours ramène l'écran en arrière
*Vue Code.* Trouvé en local : ouvrir une conversation neuve (« + » d'un
projet) pendant qu'une autre se charge — au démarrage, par l'adresse —
laissait la lecture en retard reprendre l'écran, et le premier message partait
dans l'ancienne conversation. *Cause* : même fonction, rien n'annulait la
lecture. *Correctif* : `abandonnerLOuverture()` sur toute nouvelle
conversation, sur « Conversations » (mobile) et dans l'Assistant. **Corrigé.**

### B3. La liste des conversations se reconstruit sous le pointeur
*Vue Code et Assistant.* `code-tree.js` refaisait tout l'arbre (`innerHTML = ""`)
à chaque rendu : des centaines de fois par tour en cours, et toutes les 15 s
par la veille de la liste. Un clic dont l'appui et le relâchement encadrent
une reconstruction est perdu ; survol et focus clavier sautent. *Correctif* :
empreinte de l'arbre, reconstruction seulement si elle change, sinon mise à
jour de la seule ligne active. **Corrigé.**

### B4. La fiche ouverte se refait toutes les 15 secondes, quelle que soit la vue
*Connecteurs, Agents, formulaires.* La veille des conversations
(`services/catalog.js`) appelle le rendu complet : sur Connecteurs, la fiche
ou le formulaire d'une composition étaient reconstruits en pleine saisie
(focus, curseur, recherche perdus). *Correctif* : la veille ne redessine que
l'écran des conversations. Mesuré : 0 reconstruction en 20 s sur Connecteurs.
**Corrigé.**

### B5. « Autoriser » ne répond pas pendant plusieurs secondes
*Fil, carte d'autorisation.* Le clic attendait la réponse du service avant de
refermer la carte. *Correctif* : retour optimiste — la carte se referme sur le
choix au clic, et se rouvre avec un message si le service refuse (un 409 « ce
tour n'attend plus » la laisse close). **Corrigé**, testé
(`cartes.suite.mjs`).

### B6. « Prendre la main » reste muet
*Écran du navigateur de l'agent* (`apps/page_ecran`). Le bouton attendait
l'état suivant du serveur sans rien dire. *Correctif* : « Prise de la main… »,
désactivé, jusqu'à l'état suivant (ou 2 s). **Corrigé**, testé
(`ecran.suite.mjs`).

### B7. L'image du navigateur de l'agent entourée de bandes noires
*Panneau, onglet « Navigateur de l'agent ».* Capture `avant/07`. *Cause* :
`ecran.css`, l'image remplit toute la scène en `object-fit: contain`. Une page
plus large que haute laisse deux bandes au-dessus et au-dessous.
*Correctif* : l'image prend la taille exacte qui tient dans la scène
(`tailleAjustee`), calée en haut ; ses proportions étant celles de l'image,
les coordonnées des gestes restent justes. **Corrigé**, testé. *À vérifier
après déploiement* : l'instance locale n'a pas de navigateur d'agent.

### B8. Le fil déborde quand le panneau est ouvert (1024 px)
*Vue Code + panneau.* Capture `avant/16` : 765 px de contenu dans 482 px de
fil, la réponse est coupée à droite, une barre de défilement horizontale
apparaît. *Cause* : `min-width` implicite des éléments flex/grille (message,
blocs de code, tableaux). *Correctif* : `min-width: 0` à chaque niveau, fil et
composeur resserrés quand le panneau est ouvert. **Corrigé.**

### B9. La navigation mobile se chevauche
*Toutes vues, 390 px.* Capture `avant/18` : « À valider », collé à droite,
recouvre « Connecteurs » (« Cc À valider »). *Correctif* : la navigation passe
sur sa propre ligne, pleine largeur ; « À valider » reste collé au bout avec
un fondu. **Corrigé.**

### B10. Le nom d'un projet est injecté en HTML
*Barre latérale.* `code-tree.js` : `innerHTML = "<span>📁 " + titre + "</span>"`.
Un projet nommé `<img onerror=…>` s'exécutait. *Correctif* : `textContent`.
**Corrigé.**

---

## 2. Gênant

### Fil de conversation

- **G1. Le fil montre le brut des outils** (`avant/04`, `avant/06`, `avant/08`).
  Nom technique (`mcp__chrome-devtools-mcp__take_snapshot`), paramètres JSON,
  résultat entier : la réponse se perd dessous. *Correctif* : présentation en
  étapes, comme l'extension VS Code (voir § 4). **Corrigé.**
- **G2. « USER » / « ASSISTANT » en anglais** dans chaque bulle. *Correctif* :
  la mise en page dit qui parle (la personne à droite, l'agent à gauche) ;
  « Vous » / « Claude » / « Assistant » restent pour le lecteur d'écran.
  **Corrigé.**
- **G3. Un message long de la personne tient des écrans** (`avant/03` : un
  fichier HTML collé, 16 000 px). *Correctif* : replié au-delà de 1 200
  caractères ou 14 lignes, « Afficher tout » / « Réduire ». **Corrigé.**
- **G4. Les résultats d'outil défilent de côté.** *Correctif* : retour à la
  ligne (`pre-wrap`, `overflow-wrap: anywhere`). **Corrigé.**
- **G5. « exit_143 » en bandeau d'erreur** après « Arrêter ». *Correctif* :
  « Tour arrêté. », sans bandeau ; un autre code : « Le tour s'est arrêté sur
  une erreur (code N). ». **Corrigé**, testé.
- **G6. Pas d'heure, pas de « Relancer ».** *Correctif* : pied de réponse
  « 14:05 · Copier · Relancer » ; « Copier » prend la réponse seule ;
  « Relancer » repose la question dans une conversation qui reprend d'avant
  elle (le même mécanisme que « Modifier »). **Corrigé.**
- **G7. Aucun retour pendant le chargement d'un fil.** *Correctif* :
  squelette. **Corrigé.**
- **G8. Le texte de réponse s'étale sur 1 500 px** à 1440 px. *Correctif* :
  colonne de lecture centrée (52 rem), réponse de l'agent sans bulle,
  paragraphes à 72 caractères. **Corrigé.**
- **G9. « None » apparaît seul entre deux outils** (`avant/04`). C'est le
  texte écrit par le modèle, tel quel dans le transcrit : il devient une
  narration d'étape, repliée. *Non corrigé à la source* (donnée).

### Barre latérale et barre de conversation

- **G10. Titres tronqués sans moyen de les lire.** *Correctif* : titre complet
  au survol (liste et barre de conversation), titre sur une ligne avec
  ellipse. **Corrigé.**
- **G11. La ligne active et la ligne survolée se confondent** (cadre contre
  fond). *Correctif* : fond d'accent et trait à gauche pour l'active.
  **Corrigé.**
- **G12. L'ordre de la liste saute à l'ouverture d'une conversation** : la
  conversation ouverte remonte en tête (tri par dernière activité côté
  service). *Non corrigé* : proposition au § 6.
- **G13. Titres de conversation tirés du HTML collé** (« Lecteur .grist G
  Lecteur .grist Déposez un document Grist — »). Le titre vient du premier
  message. *Non corrigé* (service) : proposition au § 6.

### Composeur

- **G14. Le mode « Sans garde-fou — rien n'est demandé » est coupé** dans la
  liste. *Correctif* : libellés courts (« Plan · ne modifie rien »,
  « Demande · chaque geste », « Édite · demande le reste », « Sans
  garde-fou »), explications en infobulle comme avant. **Corrigé.**
- **G15. « Défaut du projet » deux fois côte à côte** (option et bouton).
  *Correctif* : le bouton dit « Retenir pour le projet » ; dans l'Assistant,
  l'option dit « Mode par défaut ». **Corrigé.**
- **G16. « Envoyer » désactivé ressemble à un bouton actif** (or boueux) et
  « Arrêter » est rouge sur rouge. *Correctif* : un bouton principal éteint
  prend la surface neutre ; « Arrêter » est un bouton au mot rouge.
  **Corrigé.**

### Autres vues

- **G17. Agents : la description répète le nom** (« Agent Qgis complet /
  Agent Qgis complet », « Relance l'audit… · Relance l'audit… »), `avant/11`.
  *Correctif* : une description identique au nom n'est plus affichée.
  **Corrigé.**
- **G18. Boutons d'action qui ressemblent à du texte** (« Désactiver »,
  « Accorder un secret », « Lancer », « Couper », « Suspendre »),
  `avant/11`, `avant/21`. *Correctif* : bouton secondaire bordé, destructif au
  mot rouge. **Corrigé.**
- **G19. Journal : acteurs illisibles** (`automate:wikichat:memoire a utilisé
  « memoire vecteurs »`, répété dix fois), `avant/14`. *Non corrigé* :
  proposition au § 6 (regroupement et noms d'acteur côté service).
- **G20. Ma mémoire : noms de projet techniques** (« nouveau-projet-2 » au lieu
  du titre), `avant/15`. *Non corrigé* : le texte vient du service.
- **G21. Cartes non atteignables au clavier** : « Compositions », « Accès aux
  outils » dans Connecteurs, lignes de la liste des compositions. *Correctif* :
  `rendreActivable`. **Corrigé.**

---

## 3. Cosmétique

- **C1. Icônes emoji** (dossier, trombone, sablier, coche, loupe, engrenage,
  crayon, `⌘` pour Bash), rendu variable selon le système, insensibles au
  thème. *Correctif* : un jeu SVG au trait (`ui/icones.js`), une suite qui
  empêche leur retour (`sans-emoji.suite.mjs`). **Corrigé.**
- **C2. Polices incohérentes** : les onglets d'« À valider » en Arial,
  « Quitter » et « Rangés » à 15 px à côté de libellés à 12 px, tailles
  flottantes (12,3 px, 12,75 px, 13,5 px). *Correctif* : `font-family:
  inherit` sur les champs et boutons, échelle de tailles en jetons.
  **Corrigé.**
- **C3. `--mono` employé sans être défini** : le code des agents et des
  gardiens tombait en police proportionnelle. **Corrigé.**
- **C4. États vides en grand serif centré** (« Rien encore. », « Aucune
  préférence retenue. », trois fois de suite dans Ma mémoire). *Correctif* :
  texte courant, aligné à gauche. **Corrigé.**
- **C5. Chevrons `▸ ▾` minuscules** (cible de 12 px). *Correctif* : icône
  SVG, cible de 28 px (40 px au doigt). **Corrigé.**
- **C6. Point d'état d'un titre sur deux lignes centré verticalement** dans les
  cartes d'agent. **Corrigé.**
- **C7. Badge d'erreur qui déborde de sa carte** (chemin entier), Connecteurs.
  *Correctif* : tronqué, texte complet au survol. **Corrigé.**
- **C8. Onglet actif de la navigation encadré d'or** comme un bouton.
  *Correctif* : fond d'accent et soulignement. **Corrigé.**
- **C9. Focus clavier peu visible ou absent** selon les composants.
  *Correctif* : `:focus-visible` commun. **Corrigé.**
- **C10. « Compte perso — clé owner du pod »** sur l'écran de connexion
  (anglais). *Non corrigé* : écran non retouché.
- **C11. Pages « À valider » et « Journal » vides** : un grand vide sous le
  titre, sans indication de ce qui y apparaîtra. *Non corrigé* : l'état vide
  reste sobre ; un exemple de ce qui arrive là serait un plus.
- **C12. Mouvement** : les animations (pulsation, squelette) ignoraient
  `prefers-reduced-motion`. **Corrigé.**

---

## 4. Le fil en étapes (demande de Nicolas, relayée par le coordinateur)

Modèle : le chat de l'agent QGIS, et l'extension VS Code. Captures
`apres/02`, `apres/04`, `apres/04b`, `apres/06`, `apres/10`,
`apres/11`.

- Un tour : le message de la personne ; puis « Voir les étapes (n) » replié ;
  puis la réponse, lisible ; en pied l'heure, « Copier », « Relancer ».
- Une étape par appel d'outil, dite en une phrase (`ui/etapes.js`, table
  testée) : description de `Bash` et de `Task`, plan coché pour `TodoWrite`,
  verbe et fichier pour `Read`/`Edit`/`Write`/`Grep`/`Glob`, table pour le
  navigateur (`chrome-devtools`), les fichiers (`filesystem`) et les commandes
  `atelier_*` (la carte d'action rendue fait foi), serveur et nom humanisé pour
  tout outil inconnu. Le méta-outil `gateway_call_tool` se dit par l'outil
  qu'il appelle.
- Le texte écrit entre deux outils est la narration des étapes ; le texte qui
  suit le dernier geste est la réponse.
- Ne se replient jamais : demandes d'autorisation et questions, étapes en
  erreur ou refusées (marquées, rouges ou ambrées), cartes d'action de
  l'Assistant, messages du système.
- Pendant le flux : la ligne vivante dit l'étape en cours (« Lecture de la
  page… »), le compte se met à jour, rien ne saute ; un pli ouvert le reste.
- « Détails techniques » (engrenage de la barre de conversation) : « Montrer
  le raisonnement de l'agent », « Montrer les actions et leurs résultats
  bruts », décochés par défaut, retenus par le service (`PUT /v1/meta`,
  `fil_raisonnement`, `fil_actions` dans `ui.json`), identiques en Code et dans
  l'Assistant. Note : « Masqués par défaut pour garder la conversation lisible.
  Ils restent dans "Voir les étapes" sous chaque réponse. »
- Aucune donnée ne change : même transcrit, même flux ; le détail brut d'un
  outil se construit quand on déplie son étape.

## 5. Compositions (demande de Nicolas, relayée par le coordinateur)

Captures `avant/20`, `avant/21`, `avant/22` ; `apres/20`, `apres/22`.
Audit en lecture seule : aucune composition n'a été enregistrée, modifiée ou
supprimée.

| # | Gravité | Constat | Correctif | État |
|---|---|---|---|---|
| K1 | Bloque | La fiche et le formulaire se reconstruisent toutes les 15 s (voir B4) : focus et saisie de la recherche perdus. | Veille limitée à l'écran des conversations. | Corrigé |
| K2 | Gênant | Plusieurs centaines d'outils dans une seule liste déroulante (`avant/22`), sans recherche. | Champ « Chercher un outil » (libellé, nom technique, connecteur ; accents et casse ignorés), compte des résultats, groupes vides masqués, description de l'outil choisi sous la liste. | Corrigé, testé |
| K3 | Gênant | « Des outils fabriqués ici : un appel aux paramètres figés… » ne dit ni à quoi sert une composition ni quand en créer une. | Une phrase sans jargon : ce que c'est, quand s'en servir. | Corrigé |
| K4 | Gênant | L'état (active, testée, brouillon) n'apparaît que dans un tableau de la fiche. | Pastille d'état dans la liste et à côté du titre. | Corrigé |
| K5 | Gênant | « Appelable comme composition_x », `datagouv__search_datasets` : le technique au premier plan. | Nom d'outil sous « Détails techniques » ; chaque étape dite en clair, le nom technique en petit à côté. | Corrigé |
| K6 | Gênant | Lignes de la liste et carte « Compositions » inaccessibles au clavier. | `rendreActivable`, focus visible. | Corrigé |
| K7 | Cosmétique | « Monter / Descendre / Retirer » en liens pâles ; « + Outil + Demander… » en texte. | Boutons d'icône nommés (40 px au doigt) ; ajouts en boutons secondaires. | Corrigé |
| K8 | Cosmétique | La liste des outils s'affiche en barre grise sans bordure. | Tous les champs d'un formulaire prennent la même allure. | Corrigé |
| K9 | Gênant | Paramètres en JSON brut quand le schéma de l'outil est inconnu. | — | Ouvert : § 6 |
| K10 | Gênant | Pas d'essai dans le formulaire : il faut enregistrer, ouvrir la fiche, « Lancer ». | — | Ouvert : § 6 |

## 5 bis. Thèmes et contrastes (demande de Nicolas, relayée par le coordinateur)

« Le thème sombre est peu lisible parfois. » Les contrastes nominaux du thème
sombre étaient presque tous AA ; ce qui gênait la lecture était ailleurs :

| # | Gravité | Constat | Correctif | État |
|---|---|---|---|---|
| T1 | Gênant | Texte discret en 10 à 11,7 px (`0.68rem` à `0.78rem`, 22 règles) : AA sur le papier, pénible à l'écran. | Rien sous 12 px : les tailles passent aux jetons `--t-xs` (12 px) à `--t-m` (14 px). | Corrigé |
| T2 | Gênant | Texte estompé par opacité (0,5 à 0,85) : descriptions de connecteurs, citations, cartes d'autorisation closes, projets rangés. Un texte discret à 0,7 tombe sous AA. | Le retrait passe par la couleur (`--texte-2`, `--texte-3`), dont le contraste est mesuré. | Corrigé |
| T3 | Gênant | Bordures de champ à 1,3:1 : on ne voit pas où cliquer (WCAG 1.4.11 demande 3:1). | `--bordure-champ` à 3,4:1 (sombre), 3,3:1 (clair) sur tous les champs. | Corrigé |
| T4 | Gênant | Surfaces trop proches (page, cartes, barres) : les cartes se fondent. | Quatre surfaces nettement étagées (`--surface-0` à `--surface-3`), sans noir pur. | Corrigé |
| T5 | Gênant | 110 couleurs écrites en dur dans `app.css`, dont des repli `var(--x, #…)` d'un autre thème : un thème clair aurait laissé du texte clair sur fond clair. | Toutes les couleurs dans `css/jetons.css`, une table générée pour les deux thèmes ; `app.css` n'en contient plus aucune (`jetons.suite.mjs` échoue sinon). | Corrigé, testé |
| T6 | Gênant | Pas de thème clair. | Thème clair complet, mêmes jetons : panneau, blocs de code, coloration, badges, cartes d'action, bandeaux, écran de connexion. | Corrigé |
| T7 | Gênant | Pas de choix de thème. | « Affichage » dans l'en-tête : suivre le système (défaut), clair, sombre ; retenu par personne par le service (`ui.theme`), appliqué avant le premier rendu par `js/theme-initial.js` (copie locale), donc sans éclair. | Corrigé, testé |
| T8 | Cosmétique | Placeholder à 4:1, focus à 4:1 d'un or terne. | Placeholder au texte discret (6,8:1), anneau de focus à 12,5:1. | Corrigé |

**Contrastes mesurés** (rapport WCAG ; *avant* : thème sombre déployé ;
*après* : `css/jetons.css`). Texte courant du fil visé en AAA (7:1), le reste
en AA (4,5:1 pour le texte, 3:1 pour les bordures et le focus).

| Paire | Seuil visé | Sombre avant | Sombre après | Clair |
|---|---|---|---|---|
| Texte courant du fil / page | 7:1 | 15.4 | 15.9 | 15.0 |
| Texte courant / carte | 7:1 | 13.9 | 14.2 | 16.4 |
| Texte secondaire / carte | 4.5:1 | 5.6 | 9.4 | 9.3 |
| Texte discret / page | 4.5:1 | 6.2 | 7.6 | 5.4 |
| Texte discret / barre latérale | 4.5:1 | 6.4 | 7.9 | 4.9 |
| Texte discret / bulle de la personne | 4.5:1 | 4.5 | 5.7 | 5.0 |
| Lien, accent / page | 4.5:1 | 7.8 | 8.9 | 5.2 |
| Texte sur bouton principal | 4.5:1 | 7.8 | 8.9 | 5.7 |
| Erreur / carte | 4.5:1 | 5.1 | 6.1 | 6.0 |
| Succès / carte | 4.5:1 | 4.8 | 7.3 | 5.3 |
| Attention / carte | 4.5:1 | 6.8 | 8.3 | 5.4 |
| Badge « connecté » | 4.5:1 | 7.0 | 8.3 | 5.7 |
| Badge « local » | 4.5:1 | 7.7 | 8.4 | 6.5 |
| Badge « erreur » | 4.5:1 | 7.0 | 8.0 | 6.2 |
| Badge « à surveiller » | 4.5:1 | 7.0 | 8.2 | 5.8 |
| Code et résultats d'outil | 7:1 | 15.1 | 16.8 | 14.2 |
| Coloration : mot-clé | 4.5:1 | 8.5 | 10.2 | 5.6 |
| Coloration : chaîne | 4.5:1 | 10.8 | 12.0 | 4.6 |
| Placeholder / champ | 4.5:1 | 4.0 | 6.8 | 5.8 |
| Bordure d'un champ / carte | 3:1 | 1.3 | 3.4 | 3.3 |
| Anneau de focus / page | 3:1 | 4.0 | 12.5 | 5.2 |
| Bandeau d'erreur | 4.5:1 | 10.3 | 10.4 | 7.3 |

Les valeurs « avant » supposent le texte à pleine opacité : avec l'opacité
de 0,7 qui s'y appliquait souvent (T2), le texte discret tombait sous 4,5:1.

**Pages hors de l'application.** L'écran du navigateur de l'agent
(`apps/page_ecran`) est servi par l'hôte des applications, une autre origine :
il ne lit pas le choix de l'Atelier et suit `prefers-color-scheme` (déjà en
jetons, lisible dans les deux). Les pages d'erreur de l'hôte des
applications suivent aussi le système. Les pages OAuth de la passerelle
(`oauth.py`, accord d'un client distant) restent claires et lisibles
(texte 14:1) ; hors du périmètre de cette équipe.

Captures des deux thèmes : `apres/30` à `apres/34` (`-sombre`, `-clair`).

## 6. Ce qui a été corrigé / reste ouvert

### Corrigé et vérifié

Tout ce qui est marqué **Corrigé** ci-dessus. Vérifications :

- suites JavaScript (`tests/js/*.suite.mjs`, lancées par pytest) : toutes
  vertes, dont trois nouvelles : `etapes.suite.mjs` (106 vérifications :
  table des libellés, regroupement d'un tour, ce qui ne se replie jamais,
  étape vivante, réglages, message long, heure, raccourcis, arbre,
  compositions, thème), `jetons.suite.mjs` (aucune couleur en dur hors de
  `css/jetons.css`, chaque jeton sombre a son pendant clair) et
  `sans-emoji.suite.mjs` ; `ecran.suite.mjs` étendue (taille de l'image,
  bouton « Prendre la main ») ; `cartes`, `reutilisation`, `assistant`
  adaptées au fil en étapes ;
- test Python `test_reglages_fil.py` (réglages du fil et thème retenus,
  effacés quand on revient au défaut, thème inconnu refusé) ;
- instance locale (`build_app` + harnais factice « lent » qui joue un tour
  réaliste, transcrits réels en fixtures) : ouverture d'une conversation,
  tour en direct (étape vivante, compte), fil long, message replié, réglages,
  Assistant, Connecteurs et compositions, 1024 px, 390 px ; captures
  `apres/` prises par Playwright ;
- mesures : ouverture d'une conversation 25 ms (contre 4 s), 0 reconstruction
  de fiche en 20 s sur Connecteurs, une seule lecture de `/v1/meta` au
  démarrage (contre deux), projets et conversations lus ensemble.

### À vérifier après déploiement

- l'écran du navigateur de l'agent (B6, B7) : pas de navigateur d'agent en
  local ;
- les cartes d'autorisation en vrai tour (B5) : vérifiées par les suites et
  en lecture, pas sur un tour réel en attente ;
- le cache : l'index charge `app.css` et `app.js` en `?v=20260926-interface`,
  mais la page de l'écran (`page_ecran`) n'a pas de version ; un rechargement
  forcé peut être nécessaire la première fois.

### Reste ouvert (propositions pour Nicolas)

1. **Transcrit paginé** (service). La lecture d'une conversation de 24 tours
   coûte 3,3 s au service (2,9 Mo de transcrit). Le fil s'ouvre désormais tout
   de suite, mais se remplit au même rythme. Servir les derniers tours d'abord
   (`GET …/transcript?depuis=`) rendrait l'ouverture instantanée.
2. **Ordre stable de la liste** (service). Ouvrir une conversation la fait
   remonter en tête (G12). Trier par dernier *message*, pas par dernière
   *lecture*.
3. **Titres de conversation** (service). Le premier message fait le titre,
   même quand c'est un fichier collé (G13). Tronquer au premier paragraphe de
   prose, ou laisser l'agent proposer un titre après le premier tour.
4. **Journal regroupé** (service ou interface). Dix lignes « automate:… a
   utilisé « memoire vecteurs » » d'affilée : regrouper les répétitions et
   nommer les acteurs comme ailleurs (G19).
5. **Compositions** : un formulaire de paramètres tiré du schéma de l'outil
   même quand il n'est pas encore chargé (K9), et un bouton « Essayer » dans
   le formulaire, qui lance le brouillon sans quitter l'écran (K10) — il
   faudrait une exécution « à blanc » côté service.
6. **Structure** : la vue Agents mêle agents planifiés, gardiens, tâches
   automatiques et lancements en une seule page très longue ; des onglets
   (« Agents », « Gardiens », « Tâches ») la rendraient lisible sans changer
   la navigation principale.
7. **Écran du navigateur dans le thème choisi** : il suit le système, pas le
   choix fait dans l'Atelier (autre origine). Passer le thème dans l'adresse
   de l'écran (`/v1/ecran/<id>/ouvrir?theme=`) le lui dirait.
8. **Emplacement du micro** : réservé dans le composeur, à gauche d'« Envoyer »
   (commentaire dans `index.html`, icône `micro` prête) ; rien d'implémenté.
