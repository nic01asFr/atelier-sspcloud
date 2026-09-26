"""L'écran contre un vrai Chrome et le vrai chrome-devtools-mcp (essai sur demande).

Sauté sauf si l'on donne :

- `ATELIER_ESSAI_CHROME` : un Chrome (ou chrome-headless-shell) ;
- `ATELIER_ESSAI_CDM` : `chrome-devtools-mcp.js` (1.10.1 mesuré) ;
- `ATELIER_ESSAI_LANCEUR=1` (Linux) : passer par le vrai lanceur
  `bin/atelier-chrome`, rôle « navigateur » compris.

La chaîne est celle d'une conversation : filtre -> serveur MCP -> Chrome par
son tube, plus le port de débogage en boucle locale ; puis l'hôte des
applications, l'écran (`ecran.Ecrans`) et une page qui regarde par le
WebSocket. Sans le lanceur (Windows, où puppeteer ne sait pas lancer un
script bash pour Chrome), le port est demandé par `--chromeArg` : puppeteer
garde alors son tube, puisqu'il voit `--remote-debugging-pipe` parmi les
arguments.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

CHROME = os.environ.get("ATELIER_ESSAI_CHROME", "")
CDM = os.environ.get("ATELIER_ESSAI_CDM", "")
pytestmark = pytest.mark.skipif(
    not (CHROME and CDM and Path(CHROME).exists() and Path(CDM).exists()),
    reason="essai réel : ATELIER_ESSAI_CHROME et ATELIER_ESSAI_CDM",
)

from test_ecran import Monte, Spectateur, entrer_ecran, flux  # noqa: E402
from test_bureaux import Serveur, port_libre  # noqa: E402

from mcp_gateway.atelier.apps.serveur import construire_app_apps  # noqa: E402
from mcp_gateway.atelier.apps.service import ServiceApps  # noqa: E402
from mcp_gateway.atelier.config import AtelierSettings  # noqa: E402
from mcp_gateway.atelier.ecran import Ecrans, lire_fiche  # noqa: E402

FILTRE = Path(__file__).resolve().parents[1] / "bin" / "atelier-chrome-onglets.mjs"
LANCEUR = Path(__file__).resolve().parents[1] / "bin" / "atelier-chrome"
PAR_LE_LANCEUR = os.environ.get("ATELIER_ESSAI_LANCEUR") == "1"
ATELIER = "https://atelier.test"
# Le HOME du poste, lu avant que `conftest` n'en donne un vide à chaque test :
# sous Windows, Chrome ne démarre pas avec un USERPROFILE vide (mesuré).
MAISON = {k: os.environ[k] for k in ("HOME", "USERPROFILE") if k in os.environ}


def page(titre: str, corps: str) -> str:
    return "data:text/html," + quote(f"<title>{titre}</title><body style='margin:0'>{corps}</body>")


class Mcp:
    """Un client MCP en stdio : le rôle du CLI d'une conversation."""

    def __init__(self, racine: Path, profil: Path, conversation: str) -> None:
        journal = racine.parent / "journal-mcp.txt"
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("ATELIER_CHROME_")},
            **MAISON,
            "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
            "ATELIER_CHROME_RACINE": str(racine),
            "ATELIER_CHROME_ECRAN_INTERVALLE_MS": "200",
            "ATELIER_CHROME_MAIN_INTERVALLE_MS": "200",
        }
        if PAR_LE_LANCEUR:
            # Le lanceur choisit tout : profil de la conversation, port en
            # boucle locale (rôle « navigateur »), filtre, options.
            commande = [str(LANCEUR)]
            env.update({
                "ATELIER_SESSION": conversation,
                "ATELIER_CHROME_BIN": CHROME,
                "ATELIER_CHROME_MCP_JS": CDM,
                "ATELIER_CHROME_JOURNAL": str(journal),
                "ATELIER_WORK": str(racine.parent / "work"),
                "ATELIER_NODE": shutil.which("node") or "node",
            })
        else:
            commande = [
                "node", str(FILTRE), "node", CDM,
                "--headless", "--userDataDir", str(profil), "--executablePath", CHROME,
                "--viewport", "1280x720", "--no-usage-statistics", "--no-performance-crux", "--no-page-id-routing",
                "--no-category-performance", "--no-category-memory", "--no-category-emulation",
                "--chromeArg=--remote-debugging-pipe", "--chromeArg=--remote-debugging-port=0",
                "--chromeArg=--remote-debugging-address=127.0.0.1",
                "--logFile", str(journal),
            ]
            env.update({"ATELIER_CHROME_CONVERSATION": conversation, "ATELIER_CHROME_PROFIL": str(profil)})
        self.p = subprocess.Popen(
            commande,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.journal = racine.parent / "journal-mcp.txt"
        self.suivant = 0
        self.reponses: dict[int, Any] = {}
        threading.Thread(target=self._lire, daemon=True).start()
        self.demander("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "essai", "version": "1"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def _lire(self) -> None:
        for ligne in self.p.stdout:
            try:
                message = json.loads(ligne)
            except ValueError:
                continue
            if "id" in message:
                self.reponses[message["id"]] = message

    def envoyer(self, methode: str, params: dict[str, Any]) -> int:
        self.suivant += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.suivant, "method": methode, "params": params}) + "\n")
        self.p.stdin.flush()
        return self.suivant

    def attendre(self, ident: int, delai: float = 60.0) -> dict[str, Any]:
        fin = time.monotonic() + delai
        while ident not in self.reponses:
            if time.monotonic() > fin:
                journal = self.journal.read_text(encoding="utf-8", errors="replace") if self.journal.exists() else ""
                lignes = [l for l in journal.splitlines() if "ERROR:" not in l]
                raise AssertionError(f"pas de réponse à {ident} ; journal : " + " | ".join(lignes[-15:]))
            time.sleep(0.05)
        return self.reponses[ident]

    def demander(self, methode: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.attendre(self.envoyer(methode, params))

    def outil(self, nom: str, **arguments: Any) -> dict[str, Any]:
        return self.demander("tools/call", {"name": nom, "arguments": arguments})["result"]

    def fermer(self) -> int:
        self.p.stdin.close()
        return self.p.wait(30)


def test_de_bout_en_bout_contre_un_vrai_chrome(tmp_path: Path) -> None:
    racine = tmp_path / "racine"
    profil = racine / "conversation.conv-a" if PAR_LE_LANCEUR else tmp_path / "profil"
    mcp = Mcp(racine, profil, "conv-a")
    port = port_libre()
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url=f"http://127.0.0.1:{port}", public_url=ATELIER)
    settings.ensure_dirs()
    service = ServiceApps(settings)
    service.ecrans = Ecrans(racine, cadence=10)
    service.ecrans.connue = lambda c: c == "conv-a"
    hote = Serveur(construire_app_apps(service, origine_atelier=lambda: ATELIER, secret_artefacts=lambda: b"s"), port)
    m = Monte(service, hote, None, racine)  # type: ignore[arg-type]
    bouton = ("<button style='position:fixed;inset:0;width:100%;height:100%;font-size:60px' "
              "onclick=\"document.title='Clique'\">UN</button>")
    try:
        resultat = mcp.outil("new_page", url=page("Un", bouton))
        assert not resultat.get("isError"), resultat
        fin = time.monotonic() + 15
        while lire_fiche(racine, "conv-a") is None:
            assert time.monotonic() < fin, "le filtre n'a jamais publié le port de Chrome"
            time.sleep(0.1)
        fiche = lire_fiche(racine, "conv-a")
        assert fiche.page and fiche.page["titre"] == "Un"
        if Path("/proc/net/tcp").exists():
            # Le port de débogage n'écoute qu'en boucle locale (IPv4 127.0.0.1).
            ecoutes = []
            for table in ("/proc/net/tcp", "/proc/net/tcp6"):
                try:
                    lignes = Path(table).read_text(encoding="ascii").splitlines()[1:]
                except OSError:
                    continue
                for ligne in lignes:
                    champs = ligne.split()
                    adresse, port_hex = champs[1].rsplit(":", 1)
                    if champs[3] == "0A" and int(port_hex, 16) == fiche.port:
                        ecoutes.append(adresse)
            assert ecoutes and all(a == "0100007F" for a in ecoutes), ecoutes
        cookie = entrer_ecran(m)

        async def scenario() -> None:
            async with flux(m, cookie) as ws:
                s = Spectateur(ws)
                await s.jusqua(lambda s: bool(s.images) and s.images[-1][:2] == b"\xff\xd8", delai=30)
                await s.jusqua(lambda s: s.dernier_etat().get("titre") == "Un")
                # L'agent ouvre un second onglet : l'écran le suit.
                await asyncio.to_thread(mcp.outil, "new_page", url=page("Deux", "<h1>DEUX</h1>"))
                await s.jusqua(lambda s: s.dernier_etat().get("titre") == "Deux", delai=30)
                # Puis revient au premier (select_page) : l'écran aussi.
                liste = await asyncio.to_thread(mcp.outil, "list_pages")
                ligne = next(l for l in liste["content"][0]["text"].splitlines() if "(data:" in l and "Un" in l)
                await asyncio.to_thread(mcp.outil, "select_page", pageId=int(ligne.split(":", 1)[0]))
                await s.jusqua(lambda s: s.dernier_etat().get("titre") == "Un", delai=30)
                # La personne prend la main : l'agent attend, le clic arrive à la page.
                await s.envoyer({"type": "main", "prendre": True})
                await s.jusqua(lambda s: s.dernier_etat().get("main") is True)
                retenu = await asyncio.to_thread(mcp.envoyer, "tools/call", {"name": "list_pages", "arguments": {}})
                await asyncio.sleep(1.0)
                assert retenu not in mcp.reponses, "l'agent attend pendant que la personne a la main"
                for action in ("presse", "relache"):
                    await s.envoyer({"type": "souris", "action": action, "x": 0.5, "y": 0.5, "bouton": "gauche", "clics": 1})
                await s.jusqua(lambda s: s.dernier_etat().get("titre") == "Clique", delai=15)
                await s.envoyer({"type": "main", "prendre": False})
                reponse = await asyncio.to_thread(mcp.attendre, retenu, 15)
                textes = [b["text"] for b in reponse["result"]["content"] if b.get("type") == "text"]
                assert textes[-1].startswith("Note de l'Atelier") and "Clique" in textes[-1]

        asyncio.run(scenario())
    finally:
        code = mcp.fermer()
        hote.fermer()
    assert code == 0
    time.sleep(0.5)
    assert not (racine / "ecrans" / "conv-a.json").exists(), "la fiche part avec le filtre"
    assert lire_fiche(racine, "conv-a") is None
    if PAR_LE_LANCEUR:
        # Le profil de la conversation reste (connexions gardées) ; le port, non.
        assert profil.is_dir() and not (profil / "DevToolsActivePort").exists()
        restants = subprocess.run(["pgrep", "-f", str(profil)], capture_output=True, text=True).stdout.split()
        assert not restants, f"processus restants : {restants}"
    print("essai réel :", sys.platform, Path(CHROME).name, "ok")
