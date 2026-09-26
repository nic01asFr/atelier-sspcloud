"""Un faux chrome-devtools-mcp en stdio, pour le filtre du navigateur.

Il tient une liste de pages et répond à `list_pages`, `new_page`,
`select_page`, `close_page` et `navigate_page` dans la forme du serveur 1.10.1
(`McpResponse.js` : une section `## Pages`, une ligne `<id>: <adresse>` par
page, `[selected]` après la page sélectionnée). `FAUX_CHROME_JOURNAL` :
fichier où il note chaque outil reçu. `FAUX_CHROME_MUET=1` : il ne répond
jamais à `list_pages`. `FAUX_CHROME_PROFIL` et `FAUX_CHROME_PORT` : au premier
outil, il écrit `DevToolsActivePort` dans ce profil, comme Chrome quand il
démarre avec un port de débogage.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

pages = ["about:blank"]
selection = 0
journal = os.environ.get("FAUX_CHROME_JOURNAL")
muet = os.environ.get("FAUX_CHROME_MUET") == "1"
profil = os.environ.get("FAUX_CHROME_PROFIL")
port = os.environ.get("FAUX_CHROME_PORT", "9")
chrome_lance = False


def noter(nom: str) -> None:
    if journal:
        with open(journal, "a", encoding="utf-8") as f:
            f.write(nom + "\n")


def lancer_chrome() -> None:
    global chrome_lance
    if chrome_lance or not profil:
        return
    chrome_lance = True
    Path(profil).mkdir(parents=True, exist_ok=True)
    (Path(profil) / "DevToolsActivePort").write_text(
        f"{port}\n/devtools/browser/0f1e2d3c-faux-4b5a\n", encoding="utf-8"
    )


def libelle(url: str) -> str:
    # Le vrai serveur écrit « titre (adresse) » quand la page a un titre.
    if url.startswith("https://titre."):
        return f"Page (avec) titre ({url})"
    return url


def section() -> str:
    return "## Pages\n" + "\n".join(
        f"{i + 1}: {libelle(url)}{' [selected]' if i == selection else ''}" for i, url in enumerate(pages)
    )


def repondre(ident, resultat) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": resultat}) + "\n")
    sys.stdout.flush()


for ligne in sys.stdin:
    message = json.loads(ligne)
    if message.get("method") != "tools/call":
        if "id" in message:
            repondre(message["id"], {})
        continue
    nom = message["params"]["name"]
    args = message["params"].get("arguments") or {}
    noter(nom)
    lancer_chrome()
    if nom == "list_pages" and muet:
        continue
    if nom == "new_page":
        pages.append(args.get("url", "about:blank"))
        selection = len(pages) - 1
    elif nom == "select_page":
        index = int(args.get("pageId", selection + 1)) - 1
        if 0 <= index < len(pages):
            selection = index
    elif nom == "close_page":
        index = int(args.get("pageId", len(pages))) - 1
        if 0 <= index < len(pages) and len(pages) > 1:
            pages.pop(index)
            selection = min(selection, len(pages) - 1)
    elif nom == "navigate_page":
        pages[selection] = args.get("url", pages[selection])
        repondre(message["id"], {"content": [{"type": "text", "text": "Navigated.\n" + section()}]})
        continue
    elif nom == "ouvrir_une_fenetre_surgissante":
        # Une page ouverte par un site, que le client ne voit pas passer.
        pages.append("https://exemple.test/surgie")
        repondre(message["id"], {"content": [{"type": "text", "text": "ok"}]})
        continue
    elif nom == "click":
        repondre(message["id"], {"content": [{"type": "text", "text": "Clicked."}]})
        continue
    repondre(message["id"], {"content": [{"type": "text", "text": section()}]})
