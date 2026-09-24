# Création d'agents Atelier

Ce projet porte deux choses qu'il ne faut pas confondre :

1. **Un système de recherche multi-agents** (physique fondamentale) :
   `supervisor.md`, `.claude/agents/` (literature, semanticist, formelist,
   contrarian, synthesizer, validator, breakthrough), `teams/`, `pipeline/`
   (validate, score, publish), `tools/`, `findings/`.
2. **Le second cerveau** : `artifacts/cerveau/`, un corpus de notes HTML qui
   est à la fois spécification et implémentation (voir son `LISEZMOI.md`).
   Environ 530 notes au sas, une vingtaine de permanentes.

Le `README.md` de la racine distingue les deux et dit comment lancer une passe.

L'existant est commité depuis le 24/09 (commit « Figer l'existant du projet
avant toute modification »). `.mcp.json`, `tmp_*`, `*.log`, `*.pid` sont
ignorés. Vérifie `git status` en début de session : des fichiers de
`findings/` peuvent avoir été modifiés par une passe lancée ailleurs.

## Le système de recherche

- Il a été conçu comme un daemon « en boucle infinie », relancé par des
  triggers wikichat. **Aucun trigger ne s'enregistre sans accord explicite de
  la personne** : il consomme du modèle en continu, sur le pod de quelqu'un.
  Le mode par défaut est une passe manuelle, une à la fois
  (`/passe-recherche <paradoxe>`, déroulé dans `supervisor.md`), tant que la
  personne n'a pas validé le coût d'une passe. Au 24/09, sept triggers de ce
  système étaient pourtant actifs dans le coordinateur du pod (liste dans
  `triggers-config.md`) : ils n'ont été ni supprimés ni désactivés, c'est à la
  personne de décider. N'en ajoute pas, n'en retire pas.
- Les rôles sont des sous-agents Claude Code dans `.claude/agents/` (en-tête
  `name`, `description`, `tools`) ; `agents/*.md` ne sont que des renvois. Le
  superviseur n'est pas un sous-agent : c'est la session principale qui
  orchestre, un sous-agent ne pouvant pas en lancer d'autres.
- Un résultat n'est « trouvé » qu'après le pipeline complet : validation,
  contradiction par `contrarian`, score. Un calcul symbolique se vérifie par
  `tools/sympy-verify.py run <script>` (script et sortie joints dans
  `verification/` du dossier). Une citation vient d'une source lue par
  `tools/arxiv-research.js --save <dossier>`, qui tient `sources.jsonl`, avec
  son identifiant arXiv ; jamais de référence reconstituée de mémoire.
- Avant le 24/09, `sympy-verify.py` ne calculait rien (formules et
  « confirmed » écrits en dur) et `arxiv-research.js` échouait toujours : les
  findings antérieurs ne s'appuient donc sur aucune vérification outillée.
- Le ton des résultats est celui d'une note de recherche : ce qui est montré,
  sous quelles hypothèses, ce qui ne l'est pas. Pas de « percée ».

## Le second cerveau

- Les règles vivent dans `systeme/controles.js`, et seulement là. Le profil
  (`meta/profil-*.html`) est le noyau ; une note se vérifie contre le profil
  qu'elle déclare.
- Tu passes par l'éditeur et ses contrôles. Tu n'écris pas une note HTML à la
  main en contournant la sérialisation canonique.
- La publication passe par l'onglet Projection, qui écrit `public/`. Ce qui est
  privé n'est pas présent là où on expose : on ne filtre jamais à la lecture.
- Validation en ligne de commande : `npm install` puis
  `node tools/valider-corpus.mjs` (charge `controles.js` tel quel, n'écrit
  rien). Au 24/09 : aucune violation sur les 31 notes atteintes depuis
  `index.html`, mais les 528 captures du sas ne sont pas atteintes par le
  parcours ; vérifiées une à une, 202 portent une arête `source` dans un
  paragraphe trop court pour la justifier (forme produite par
  `tools/scribe.py`, qui écrit ses captures sans passer par `documentNote`).
  Ne corrige pas les notes à la main : c'est au Scribe de changer.

## Montrer ce que le projet produit

- Le corpus est servi par l'Atelier sous
  `/v1/artifacts/nouveau-projet-4/cerveau/` (slash final), qui renvoie vers
  `/v1/artifacts/nouveau-projet-4/@<jeton>/cerveau/`. Depuis le 24/09 il est
  en bac à sable comme tout artefact : la page n'a plus accès ni à la clé
  owner, ni au cookie, ni à l'API ; ses CSS, JS et pages relatifs se chargent
  par le jeton du chemin (règles exactes dans `socle.md`, « Montrer ce que tu
  produis »). Garde toutes les adresses du corpus relatives. Ne crée pas
  d'autre `.corpus` et n'en déplace pas sans que la personne l'ait demandé.
- `outils/serveur.py` (127.0.0.1, port 8770 par défaut, `--port N`) et
  `findings/server.mjs` (127.0.0.1, port 8771 par défaut, `--port N`) sont des
  serveurs locaux, joignables seulement depuis le pod. Ne les présente pas à
  la personne comme une adresse à ouvrir, et n'en lance pas d'autre. Le 8080
  est le port de code-server dans le pod de l'Atelier : c'était l'ancien
  défaut de `serveur.py`.
- Jusqu'au 24/09, `findings/server.mjs` écoutait sur `0.0.0.0:8081` et servait
  tout fichier lisible du pod par un chemin en `..%2F` (`.mcp.json` compris).
  Le code est corrigé ; des instances lancées avant la correction peuvent
  encore tourner avec l'ancien code : ne t'en sers pas.
- Les résultats publiables (`artifacts/findings/`) sont des pages statiques
  autonomes : elles se lisent sans serveur.
- L'éditeur du corpus enregistre par `PUT` relatif à l'adresse de la page
  (voir `socle.md`) : dans `cerveau/` seulement, jamais de point-fichier, et
  avec `If-Match` sur l'`ETag` lu, sinon deux onglets s'écrasent. Ce que ce
  `PUT` ne couvre pas (un traitement côté serveur, un autre dossier) attend le
  mécanisme d'applications de l'Atelier : dis-le, ne le contourne pas par un
  serveur local.
