# Contribuer à l'Atelier

Merci de l'intérêt. Le projet est maintenu par une personne, sur son temps :
une proposition petite, testée et expliquée a toutes les chances d'être lue.

## Avant d'écrire du code

- Lisez [`docs/fonctionnalites.md`](docs/fonctionnalites.md) : il dit ce qui
  existe, où est le code et ce qui manque. Une brique cassée se répare, elle
  ne se double pas.
- Pour un changement de comportement, ouvrez d'abord une issue qui décrit le
  besoin. Pour une faille, **pas d'issue publique** : voir
  [`SECURITY.md`](SECURITY.md).

## Lancer les tests

Python 3.10 ou plus, et `node` 20 ou plus (la suite Python lance aussi les
bancs d'essai JavaScript de l'interface).

```bash
cd atelier-src
pip install -e ".[dev]"
python -m pytest -q -p no:cacheprovider
```

La vitrine, le vérificateur de liens et leurs tests :

```bash
node --test site/generate.test.mjs scripts/verifier-liens.test.mjs
node site/generate.mjs          # écrit site/dist/
node scripts/verifier-liens.mjs # liens relatifs de la documentation
```

Le chart se vérifie avec `helm lint charts/atelier --set ingress.hostname=atelier.example.org` ;
la CI rend en plus chaque configuration (`.github/workflows/release.yml`).

Pour voir l'interface sans pod, un Atelier local tourne avec le harnais
factice, qui n'appelle aucun modèle :

```bash
cd atelier-src
ATELIER_WORK=/tmp/atelier-essai ATELIER_WORK_DIR=/tmp/atelier-essai HOME=/tmp/atelier-maison \
  python -m mcp_gateway.atelier.app --fake
# puis http://127.0.0.1:8787/, clé dans /tmp/atelier-essai/.secrets/atelier_owner_key
```

Donnez-lui toujours un dossier de travail et un `HOME` jetables : l'Atelier
écrit dans `~/.claude.json` et dans son volume.

## Conventions

- **Langue** : le code, les commentaires, la documentation et les messages de
  l'interface sont en français. Les commentaires disent *pourquoi*, pas *quoi*.
- **Commits** : en français, à l'infinitif, un sujet court (« Refuser un
  secret passé en argument »), un corps qui dit la raison.
- **Pas d'emoji**, ni dans le code ni dans l'interface
  (`tests/js/sans-emoji.suite.mjs` y veille).
- **Interface** : aucune couleur hors de `web/css/jetons.css`, deux thèmes,
  contraste AA ; voir [`docs/ui/guide-interface.md`](docs/ui/guide-interface.md).
- **Sûreté** : pas de `pkill -f`, pas d'écoute sur `0.0.0.0` hors du service
  exposé, aucun secret dans un fichier de projet ni dans un argument de
  commande.
- **Une correction vient avec un test** dont on a vérifié qu'il échoue sans
  elle. Un test couvre un comportement réel, pas la présence d'une chaîne.
- **La documentation suit le code** dans le même commit : la section du guide
  concernée, et son statut (en service, intégré, pas fait).

## Proposer un changement

1. Une branche par sujet, partie de `main`.
2. La suite passe, les liens de la documentation aussi.
3. Une demande de fusion qui dit ce qui change, pourquoi, comment c'est vérifié
   (et ce qui ne l'est pas).

En contribuant, vous acceptez que votre contribution soit publiée sous la
licence du dépôt, Apache-2.0 ([`LICENSE`](LICENSE)), et vous suivez le
[code de conduite](CODE_OF_CONDUCT.md).
