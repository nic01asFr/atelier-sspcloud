# Refaire les captures de la vitrine

Les captures de `site/assets/captures/` viennent d'une instance locale de
l'Atelier, avec le harnais factice (aucun modèle appelé) et des données de
démonstration inventées. Tout passe par les vraies routes et commandes du
service : projets, créations, « À valider », journal, gardiens. Seuls les
transcrits des tours sont écrits à la main, au format du CLI.

Il faut Python avec le paquet de l'Atelier (`pip install -e "atelier-src[dev]"`),
Playwright et Chromium (`pip install playwright && playwright install chromium`)
et Pillow pour la conversion en WebP.

1. Un dossier de travail et un `HOME` jetables, puis l'Atelier, avec un hôte
   des applications sur le même site (127.0.0.1, autre port) pour que le
   panneau puisse encadrer les créations :

   ```bash
   export DEMO_WORK=/tmp/atelier-demo/work HOME=/tmp/atelier-demo/maison USERPROFILE=/tmp/atelier-demo/maison
   export ATELIER_WORK=$DEMO_WORK ATELIER_WORK_DIR=$DEMO_WORK ATELIER_FAKE_HARNESS=1
   export ATELIER_PUBLIC_URL=http://127.0.0.1:8787 ATELIER_APPS_PUBLIC_URL=http://127.0.0.1:8788
   export ATELIER_RELAIS_LLM=0 ATELIER_RELAIS_LLM_PORT=18790
   mkdir -p $DEMO_WORK $HOME
   python -m mcp_gateway.atelier.app --fake &
   ```

2. Les données : `python docs/publication/captures/semer.py`.

3. Les gardiens, sans geste ni hook, sur une déclaration réduite aux contrôles
   qui ont un sens hors d'un pod (santé des services, sécurité des ports et des
   secrets, cohérence, entretien ; sans `securite.droits`, `sante.disque`,
   `sante.image-main` ni `sante.ci-main`, qui mesureraient la machine locale) :

   ```bash
   ATELIER_GARDIENS_GESTES=0 ATELIER_GARDIENS_HOOKS=0 ATELIER_GARDIENS_REPARATIONS=0 \
     python -m mcp_gateway.gardiens --declaration <déclaration réduite>.json &
   ```

4. Les captures, dans les deux thèmes, à 1440 px et 390 px :
   `python docs/publication/captures/capturer.py <sortie> code assistant a-valider agents journal mobile`.
   Avant chaque capture, le script vérifie qu'aucun chemin de la machine ni la
   clé de l'instance n'est à l'écran.

5. La conversion en WebP (qualité 86) vers `site/assets/captures/<nom>-<thème>.webp`,
   puis `node site/generate.mjs`.

Les vues Connecteurs et Ma mémoire ne sont pas capturées : la passerelle MCP
n'est pas démarrée avec le harnais factice, et « Ma mémoire » lit wikichat,
absent de l'instance locale.
