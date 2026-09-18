"""Servir les artefacts d'un projet — les livrables qu'un agent y dépose.

Un agent qui produit un résultat destiné à être vu — un rapport, une page,
un tableau — n'a nulle part où le montrer : sur ce pod, un port local n'est
jamais exposé. Un agent a passé cent soixante-quatorze tours à chercher une
URL publique pour son serveur maison, sans en trouver. La réponse est
ailleurs : il dépose ses livrables dans un dossier `artifacts/` de son projet,
et l'Atelier les sert derrière sa propre porte, comme il sert déjà VS Code.

Le contenu vient d'un agent, pas de nous. Servi tel quel sur la porte de
l'Atelier, un HTML déposé là tournerait avec le cookie de qui le regarde et
pourrait appeler l'API en son nom. On le rend donc inerte — voir `CSP_SANDBOX`.
"""

from __future__ import annotations

import html
import mimetypes
from dataclasses import dataclass
from pathlib import Path

# Le dossier, dans le projet, où un agent dépose ce qu'il veut montrer.
NOM_DOSSIER = "artifacts"

# Le contenu est produit par un agent. `sandbox` sans `allow-same-origin` met
# le document dans une origine opaque : son script ne lit plus le cookie de
# l'Atelier et ses requêtes ne sont plus créditées. `allow-scripts` laisse
# vivre une page autonome — mais jamais avec `allow-same-origin`, sinon le bac
# à sable ne servirait plus à rien. Un artefact se veut donc autonome, tout en
# lui : c'est aussi ce qu'est un artefact chez Claude.
CSP_SANDBOX = (
    "sandbox allow-scripts allow-forms allow-popups allow-modals; "
    "default-src 'none'; img-src data: blob:; media-src data: blob:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:"
)

# Ce qui exécute du script si on l'ouvre : c'est là que le bac à sable compte.
TYPES_ACTIFS = ("text/html", "image/svg+xml")

# Ce qu'on ne montre pas dans l'index : les serveurs bricolés d'hier, les
# restes de dépendances. L'agent expose du contenu, pas de la plomberie.
CACHES = {"server.mjs", "server.js", "node_modules", ".git", "__pycache__"}


@dataclass
class Entree:
    """Une ligne de l'index : un fichier ou un sous-dossier."""

    nom: str
    chemin: str  # relatif au dossier des artefacts, pour l'URL
    est_dossier: bool
    taille: int


def dossier_des_artefacts(cwd: Path) -> Path:
    """Là où un projet garde ce qu'il montre."""
    return Path(cwd) / NOM_DOSSIER


def _sous(base: Path, rel: str) -> Path | None:
    """Le chemin visé, s'il reste bien sous la base — sinon rien.

    Un artefact ne donne pas le droit de lire tout le disque : `../../secrets`
    dans une URL doit se heurter à un mur, pas remonter l'arborescence.
    """
    base = base.resolve()
    try:
        vise = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    if vise == base or base in vise.parents:
        return vise
    return None


def _humain(taille: int) -> str:
    if taille < 1024:
        return f"{taille} o"
    if taille < 1024 * 1024:
        return f"{taille / 1024:.1f} ko"
    return f"{taille / (1024 * 1024):.1f} Mo"


def _joli_nom(nom: str) -> str:
    tronc = nom.rsplit(".", 1)[0] if "." in nom else nom
    return tronc.replace("_", " ").replace("-", " ").strip() or nom


def lister(base: Path, rel: str = "") -> list[Entree] | None:
    """Le contenu d'un dossier d'artefacts, trié dossiers puis fichiers.

    Rend `None` si le chemin ne désigne pas un dossier existant sous la base.
    """
    cible = _sous(base, rel) if rel else base.resolve()
    if cible is None or not cible.is_dir():
        return None
    entrees: list[Entree] = []
    for enfant in sorted(cible.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if enfant.name in CACHES or enfant.name.startswith("."):
            continue
        rel_enfant = f"{rel}/{enfant.name}".strip("/")
        try:
            taille = enfant.stat().st_size if enfant.is_file() else 0
        except OSError:
            taille = 0
        entrees.append(Entree(enfant.name, rel_enfant, enfant.is_dir(), taille))
    return entrees


def type_du_fichier(chemin: Path) -> str:
    type_devine, _ = mimetypes.guess_type(chemin.name)
    if type_devine:
        return type_devine
    if chemin.suffix.lower() in (".md", ".markdown"):
        return "text/markdown"
    return "application/octet-stream"


def _page(titre: str, corps: str) -> str:
    """Une page autonome : tout le style à l'intérieur, rien à charger.

    L'origine opaque du bac à sable interdit de tirer une feuille de style
    d'ailleurs ; la page doit donc se suffire. Elle suit aussi le thème de qui
    la lit, clair ou sombre, comme le reste de l'Atelier.
    """
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<style>
  :root {{ color-scheme: light dark; --fond:#fff; --encre:#1a1a1a; --doux:#666;
    --trait:#e2e2e2; --lien:#0b66c3; --code:#f5f5f5; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --fond:#1a1a1a; --encre:#e8e8e8;
    --doux:#9aa; --trait:#333; --lien:#5aa9ff; --code:#242424; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--fond); color:var(--encre);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:820px; margin:0 auto; padding:40px 24px 96px; }}
  a {{ color:var(--lien); }}
  h1,h2,h3 {{ line-height:1.25; }}
  h1 {{ font-size:1.7rem; margin:0 0 1.2rem; }}
  pre {{ background:var(--code); padding:14px 16px; border-radius:8px;
    overflow:auto; font-size:.86em; }}
  code {{ background:var(--code); padding:.15em .4em; border-radius:4px;
    font-size:.88em; }}
  pre code {{ background:none; padding:0; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; }}
  th,td {{ border:1px solid var(--trait); padding:8px 12px; text-align:left; }}
  img {{ max-width:100%; height:auto; }}
  blockquote {{ margin:1rem 0; padding:.2rem 1rem; border-left:3px solid var(--trait);
    color:var(--doux); }}
  .liste {{ list-style:none; padding:0; margin:0; }}
  .liste li {{ border-bottom:1px solid var(--trait); }}
  .liste a {{ display:flex; justify-content:space-between; gap:1rem;
    padding:12px 4px; text-decoration:none; }}
  .liste a:hover {{ background:var(--code); }}
  .nom {{ color:var(--encre); }}
  .taille {{ color:var(--doux); font-variant-numeric:tabular-nums; }}
  .vide {{ color:var(--doux); }}
  .fil {{ color:var(--doux); font-size:.9em; margin:0 0 1.5rem; }}
  .fil a {{ color:var(--doux); }}
</style></head><body><main>{corps}</main></body></html>"""


def page_index(base: Path, slug: str, rel: str, entrees: list[Entree]) -> str:
    """La page qui liste un dossier d'artefacts."""
    titre = slug if not rel else rel.rsplit("/", 1)[-1]
    fil = ""
    if rel:
        morceaux = rel.split("/")
        liens = [f'<a href="/v1/artifacts/{html.escape(slug)}/">{html.escape(slug)}</a>']
        cumul = ""
        for m in morceaux[:-1]:
            cumul = f"{cumul}/{m}".strip("/")
            liens.append(
                f'<a href="/v1/artifacts/{html.escape(slug)}/{html.escape(cumul)}/">'
                f"{html.escape(m)}</a>"
            )
        liens.append(html.escape(morceaux[-1]))
        fil = '<p class="fil">' + " / ".join(liens) + "</p>"
    if not entrees:
        corps = f"<h1>{html.escape(titre)}</h1>{fil}<p class=\"vide\">Rien à montrer ici pour le moment.</p>"
        return _page(titre, corps)
    lignes = []
    for e in entrees:
        url = f"/v1/artifacts/{html.escape(slug)}/{html.escape(e.chemin)}"
        if e.est_dossier:
            url += "/"
        etiquette = html.escape(e.nom + ("/" if e.est_dossier else ""))
        droite = "dossier" if e.est_dossier else _humain(e.taille)
        lignes.append(
            f'<li><a href="{url}"><span class="nom">{etiquette}</span>'
            f'<span class="taille">{droite}</span></a></li>'
        )
    corps = (
        f"<h1>{html.escape(titre)}</h1>{fil}"
        f'<ul class="liste">{"".join(lignes)}</ul>'
    )
    return _page(titre, corps)


def rendre_markdown(texte: str, titre: str) -> str:
    """Le Markdown en page autonome. mistune s'il est là, sinon le texte brut.

    On ne fait pas dépendre le service d'une bibliothèque de rendu : sans elle,
    l'artefact reste lisible tel qu'écrit plutôt que de renvoyer une erreur.
    """
    try:
        import mistune  # type: ignore

        corps = mistune.html(texte)
    except Exception:  # noqa: BLE001 — pas de mistune, ou un Markdown qui le fâche
        corps = f"<pre>{html.escape(texte)}</pre>"
    return _page(titre, corps)
