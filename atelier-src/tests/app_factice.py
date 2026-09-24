"""Une petite application HTTP, vraie, pour éprouver le superviseur.

Bibliothèque standard seulement : elle se lance avec n'importe quel Python.
Elle écoute sur `--port` (127.0.0.1) ou `--socket` (Unix) et répond :

- `/health` : 200, ou 500 tant que le fichier `--sante-ko-si` existe ;
- `/env` : son environnement, en JSON ;
- `/limites` : ses limites de fichiers ouverts et sa gentillesse ;
- `/pid` : son pid et celui de son enfant (`--enfant`).

Options de mise en scène : `--lent S` attend avant d'écouter, `--mourir-apres
S` sort d'elle-même, `--ignorer-sigterm` ne se laisse tuer que par SIGKILL,
`--enfant` lance un `sleep` dans son groupe, `--bavard N` écrit N lignes au
démarrage, `--memoire M` garde M Mio en mémoire résidente.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENFANT: list[int] = []


class Gestionnaire(BaseHTTPRequestHandler):
    sante_ko_si = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stdout.write("requete " + (format % args) + "\n")

    def _repondre(self, code: int, corps: object) -> None:
        donnees = json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def do_GET(self) -> None:  # noqa: N802
        chemin = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if chemin == "health":
            if self.sante_ko_si and os.path.exists(self.sante_ko_si):
                self._repondre(500, {"sante": "ko"})
            else:
                self._repondre(200, {"sante": "ok", "chemin": self.path})
        elif chemin == "env":
            self._repondre(200, dict(os.environ))
        elif chemin == "limites":
            import resource

            self._repondre(
                200,
                {"nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)), "nice": os.nice(0)},
            )
        elif chemin == "pid":
            self._repondre(200, {"pid": os.getpid(), "enfant": ENFANT[0] if ENFANT else None})
        else:
            self._repondre(404, {"inconnu": self.path})


class ServeurUnix(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):  # type: ignore[no-untyped-def]
        requete, _ = super().get_request()
        # BaseHTTPRequestHandler attend une adresse indexable.
        return requete, ("unix", 0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int)
    p.add_argument("--socket")
    p.add_argument("--sante-ko-si", default="")
    p.add_argument("--lent", type=float, default=0.0)
    p.add_argument("--mourir-apres", type=float, default=0.0)
    p.add_argument("--ignorer-sigterm", action="store_true")
    p.add_argument("--enfant", action="store_true")
    p.add_argument("--bavard", type=int, default=0)
    p.add_argument("--memoire", type=int, default=0)
    a = p.parse_args()

    if a.ignorer_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if a.enfant:
        ENFANT.append(subprocess.Popen(["sleep", "300"]).pid)
    for i in range(a.bavard):
        print(f"ligne {i:06d} " + "x" * 60)
    lest = bytearray(a.memoire * 2**20)
    for i in range(0, len(lest), 4096):
        lest[i] = 1
    if a.mourir_apres:
        threading.Timer(a.mourir_apres, lambda: os._exit(3)).start()
    time.sleep(a.lent)

    Gestionnaire.sante_ko_si = a.sante_ko_si
    if a.socket:
        serveur = ServeurUnix(a.socket, Gestionnaire)
    else:
        serveur = ThreadingHTTPServer(("127.0.0.1", a.port or int(os.environ["PORT"])), Gestionnaire)
    print(f"ecoute pid={os.getpid()}", flush=True)
    serveur.serve_forever()


if __name__ == "__main__":
    main()
