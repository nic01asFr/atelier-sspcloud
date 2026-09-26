"""Un `claude -p` de carton, pour éprouver le harnais sans passerelle.

Il lit des messages `stream-json` sur son entrée et répond à chacun comme le
vrai : une ligne `system/init` au premier, puis `assistant` et `result`. Il
signe ses réponses de son PID — c'est ainsi qu'un test sait si deux tours ont
été servis par le même processus. Il vit tant que son entrée reste ouverte,
exactement comme le vrai.

Mots reconnus dans le message : `crash` écrit une erreur sur la sortie
d'erreur ; `dors N` met N secondes à répondre ; `bavard N` écrit N réponses
d'affilée avant de conclure, pour éprouver ce qui compte le poids d'un tour ;
`mode ?` répond le mode de permission en vigueur (celui de `--permission-mode`,
changé par un `control_request` `set_permission_mode`, que le faux consigne
dans `FAUX_CLAUDE_CONTROLES` s'il est posé).
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


def _mode_de_depart(argv: list[str]) -> str:
    for a, b in zip(argv, argv[1:]):
        if a == "--permission-mode":
            return b
    return "?"


def main() -> None:
    premier = True
    # Le mode du processus : celui de sa ligne de commande, puis ce qu'un
    # `set_permission_mode` lui dit, comme le vrai (2.1.282, entrée stream-json).
    mode = _mode_de_depart(sys.argv[1:])
    for ligne in sys.stdin:
        try:
            entree = json.loads(ligne)
        except ValueError:
            continue
        if entree.get("type") == "control_request":
            requete = entree.get("request") or {}
            trace = os.environ.get("FAUX_CLAUDE_CONTROLES")
            if trace:
                with open(trace, "a", encoding="utf-8") as f:
                    f.write(json.dumps(requete) + chr(10))
            if requete.get("subtype") == "set_permission_mode":
                mode = str(requete.get("mode") or mode)
            print(
                json.dumps(
                    {"type": "control_response", "response": {"subtype": "success", "request_id": entree.get("request_id"), "response": {"mode": mode}}},
                    separators=(",", ":"),
                )
            )
            sys.stdout.flush()
            continue
        if entree.get("type") != "user":
            continue
        texte = _texte((entree.get("message") or {}).get("content"))
        if texte == "mode ?":
            texte = f"mode:{mode}"
        if premier:
            print(json.dumps({"type": "system", "subtype": "init", "mcp_servers": []}))
            premier = False
        if texte.startswith("dors "):
            time.sleep(float(texte.split()[1]))
        if texte.startswith("bavard "):
            # De quoi faire grossir la conversation sans jamais conclure :
            # c'est ainsi qu'on éprouve le plafond de contexte.
            for numero in range(int(texte.split()[1])):
                print(
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "text", "text": str(numero) + " " + "x" * 400}
                                ]
                            },
                        },
                        separators=(",", ":"),
                    )
                )
                sys.stdout.flush()
                time.sleep(0.01)
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
