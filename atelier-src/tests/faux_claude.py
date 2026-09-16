"""Un `claude -p` de carton, pour éprouver le harnais sans passerelle.

Il lit des messages `stream-json` sur son entrée et répond à chacun comme le
vrai : une ligne `system/init` au premier, puis `assistant` et `result`. Il
signe ses réponses de son PID — c'est ainsi qu'un test sait si deux tours ont
été servis par le même processus. Il vit tant que son entrée reste ouverte,
exactement comme le vrai.

Mots reconnus dans le message : `crash` écrit une erreur sur la sortie
d'erreur ; `dors N` met N secondes à répondre.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _texte(contenu: object) -> str:
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        for bloc in contenu:
            if isinstance(bloc, dict) and bloc.get("type") == "text":
                return str(bloc.get("text") or "")
    return ""


def main() -> None:
    premier = True
    for ligne in sys.stdin:
        try:
            entree = json.loads(ligne)
        except ValueError:
            continue
        if entree.get("type") != "user":
            continue
        texte = _texte((entree.get("message") or {}).get("content"))
        if premier:
            print(json.dumps({"type": "system", "subtype": "init", "mcp_servers": []}))
            premier = False
        if texte.startswith("dors "):
            time.sleep(float(texte.split()[1]))
        if texte == "crash":
            sys.stderr.write("Error: boom" + chr(10))
            sys.stderr.flush()
        reponse = f"pid:{os.getpid()} echo:{texte}"
        # Compact, comme le vrai : le harnais reconnaît ses lignes à la lettre.
        print(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": reponse}]},
                },
                separators=(",", ":"),
            )
        )
        print(
            json.dumps(
                {"type": "result", "subtype": "success", "result": reponse},
                separators=(",", ":"),
            )
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
