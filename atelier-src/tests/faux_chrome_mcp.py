"""Un faux chrome-devtools-mcp en stdio, pour le filtre d'onglets.

Il tient une liste de pages et répond à `list_pages`, `new_page`,
`close_page` et `navigate_page` dans la forme du serveur 1.10.1
(`McpResponse.js` : une section `## Pages`, une ligne `<id>: <adresse>` par
page). `FAUX_CHROME_JOURNAL` : fichier où il note chaque outil reçu.
`FAUX_CHROME_MUET=1` : il ne répond jamais à `list_pages`.
"""

from __future__ import annotations

import json
import os
import sys

pages = ["about:blank"]
journal = os.environ.get("FAUX_CHROME_JOURNAL")
muet = os.environ.get("FAUX_CHROME_MUET") == "1"


def noter(nom: str) -> None:
    if journal:
        with open(journal, "a", encoding="utf-8") as f:
            f.write(nom + "\n")


def section() -> str:
    return "## Pages\n" + "\n".join(
        f"{i + 1}: {url}{' [selected]' if i == len(pages) - 1 else ''}" for i, url in enumerate(pages)
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
    if nom == "list_pages" and muet:
        continue
    if nom == "new_page":
        pages.append(args.get("url", "about:blank"))
    elif nom == "close_page":
        index = int(args.get("pageId", len(pages))) - 1
        if 0 <= index < len(pages) and len(pages) > 1:
            pages.pop(index)
    elif nom == "navigate_page":
        pages[-1] = args.get("url", pages[-1])
        repondre(message["id"], {"content": [{"type": "text", "text": "Navigated."}]})
        continue
    elif nom == "ouvrir_une_fenetre_surgissante":
        # Une page ouverte par un site, que le client ne voit pas passer.
        pages.append("https://exemple.test/surgie")
        repondre(message["id"], {"content": [{"type": "text", "text": "ok"}]})
        continue
    repondre(message["id"], {"content": [{"type": "text", "text": section()}]})
