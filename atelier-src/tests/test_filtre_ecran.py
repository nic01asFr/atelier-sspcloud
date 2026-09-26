"""Le filtre du navigateur (`bin/atelier-chrome-onglets.mjs`) : écran et main de la personne.

Le filtre se place entre le client MCP et chrome-devtools-mcp. On le lance
devant le faux serveur (`faux_chrome_mcp.py`), qui écrit `DevToolsActivePort`
dans le profil au premier outil, comme Chrome lancé avec un port de débogage.
On vérifie :

- la fiche publiée pour l'Atelier (port, page sélectionnée, attente), en
  0600, retirée à la sortie ;
- la pause de l'agent : main prise, ses appels attendent sans atteindre le
  serveur ; main rendue, ils repartent dans l'ordre, le premier avec la note ;
- que le plafond d'onglets tient toujours, main prise ou non.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node absent")

FILTRE = Path(__file__).resolve().parents[1] / "bin" / "atelier-chrome-onglets.mjs"
FAUX = Path(__file__).with_name("faux_chrome_mcp.py")
PORT = "45123"


class Session:
    def __init__(self, tmp_path: Path, conversation: str = "conv-a", **env: str) -> None:
        self.racine = tmp_path / "racine"
        self.profil = tmp_path / "profil"
        self.conversation = conversation
        self.journal = tmp_path / "recus"
        self.p = subprocess.Popen(
            ["node", str(FILTRE), sys.executable, str(FAUX)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("ATELIER_CHROME_")},
                "FAUX_CHROME_JOURNAL": str(self.journal),
                "FAUX_CHROME_PROFIL": str(self.profil),
                "FAUX_CHROME_PORT": PORT,
                "ATELIER_CHROME_CONVERSATION": conversation,
                "ATELIER_CHROME_RACINE": str(self.racine),
                "ATELIER_CHROME_PROFIL": str(self.profil),
                "ATELIER_CHROME_ECRAN_INTERVALLE_MS": "100",
                "ATELIER_CHROME_MAIN_INTERVALLE_MS": "100",
                **env,
            },
        )
        self.suivant = 0
        self.lignes: list[dict[str, Any]] = []
        self._lecteur = threading.Thread(target=self._lire, daemon=True)
        self._lecteur.start()

    def _lire(self) -> None:
        for ligne in self.p.stdout:
            self.lignes.append(json.loads(ligne))

    @property
    def fiche(self) -> Path:
        return self.racine / "ecrans" / f"{self.conversation}.json"

    @property
    def main(self) -> Path:
        return self.racine / "main" / f"{self.conversation}.json"

    def envoyer(self, outil: str, **arguments: Any) -> int:
        self.suivant += 1
        corps = {"jsonrpc": "2.0", "id": self.suivant, "method": "tools/call",
                 "params": {"name": outil, "arguments": arguments}}
        self.ecrire(corps)
        return self.suivant

    def ecrire(self, corps: dict[str, Any]) -> None:
        self.p.stdin.write(json.dumps(corps) + "\n")
        self.p.stdin.flush()

    def reponse(self, ident: int, delai: float = 10.0) -> dict[str, Any]:
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            for ligne in list(self.lignes):
                if ligne.get("id") == ident:
                    return ligne["result"]
            time.sleep(0.02)
        raise AssertionError(f"pas de réponse à {ident}")

    def sans_reponse(self, ident: int, pendant: float = 0.6) -> None:
        time.sleep(pendant)
        assert not any(l.get("id") == ident for l in self.lignes), "l'appel devait attendre"

    def appeler(self, outil: str, **arguments: Any) -> dict[str, Any]:
        return self.reponse(self.envoyer(outil, **arguments))

    def recus(self) -> list[str]:
        return self.journal.read_text(encoding="utf-8").splitlines() if self.journal.exists() else []

    def lire_fiche(self, condition: Any = lambda f: True, delai: float = 5.0) -> dict[str, Any]:
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                fiche = json.loads(self.fiche.read_text(encoding="utf-8"))
                if condition(fiche):
                    return fiche
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        raise AssertionError("fiche jamais conforme : " + (self.fiche.read_text(encoding="utf-8") if self.fiche.exists() else "absente"))

    def poser_la_main(self, **contenu: Any) -> None:
        self.main.parent.mkdir(parents=True, exist_ok=True)
        self.main.write_text(json.dumps(contenu), encoding="utf-8")

    def fermer(self) -> int:
        self.p.stdin.close()
        return self.p.wait(10)


def _textes(resultat: dict[str, Any]) -> list[str]:
    return [b["text"] for b in resultat.get("content") or [] if b.get("type") == "text"]


# ── La fiche de l'écran ─────────────────────────────────────────────────


def test_le_filtre_publie_le_port_et_la_page_selectionnee(tmp_path: Path) -> None:
    s = Session(tmp_path)
    try:
        assert not s.fiche.exists(), "rien avant que Chrome ne démarre"
        s.appeler("new_page", url="https://titre.exemple/")
        fiche = s.lire_fiche(lambda f: (f.get("page") or {}).get("url") == "https://titre.exemple/")
        assert fiche["port"] == int(PORT) and fiche["chemin"].startswith("/devtools/browser/")
        assert fiche["conversation"] == "conv-a" and fiche["version"] == 1 and fiche["attente"] == 0
        assert fiche["page"]["titre"] == "Page (avec) titre", "le titre peut porter des parenthèses"
        assert fiche["pid"] != os.getpid()
        if os.name == "posix":
            assert oct(s.fiche.stat().st_mode & 0o777) == "0o600"
        # L'agent change d'onglet : la fiche suit.
        s.appeler("select_page", pageId=1)
        s.lire_fiche(lambda f: f["page"]["url"] == "about:blank")
        s.appeler("navigate_page", url="https://autre.exemple/")
        s.lire_fiche(lambda f: f["page"]["url"] == "https://autre.exemple/")
    finally:
        assert s.fermer() == 0
    assert not s.fiche.exists(), "la fiche part avec le filtre"


def test_sans_conversation_le_filtre_ne_publie_rien(tmp_path: Path) -> None:
    s = Session(tmp_path, conversation="../hors")
    try:
        s.appeler("new_page", url="https://a.exemple/")
        time.sleep(0.4)
        assert not (s.racine / "ecrans").exists()
    finally:
        s.fermer()


def test_zero_onglet_avec_ecran_ne_pose_aucune_question_en_plus(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="0")
    try:
        for i in range(4):
            assert not s.appeler("new_page", url=f"https://{i}.exemple/").get("isError")
        assert "list_pages" not in s.recus()
        s.lire_fiche(lambda f: f["page"]["url"] == "https://3.exemple/")
    finally:
        s.fermer()


# ── La main de la personne ─────────────────────────────────────────────


def test_main_prise_l_agent_attend_puis_reprend_avec_la_note(tmp_path: Path) -> None:
    s = Session(tmp_path)
    try:
        s.appeler("new_page", url="https://a.exemple/")
        s.poser_la_main(prise=True, depuis=int(time.time() * 1000))
        premier = s.envoyer("click", uid="1_2")
        second = s.envoyer("list_pages")
        s.sans_reponse(premier)
        assert "click" not in s.recus(), "rien n'a touché le navigateur"
        s.lire_fiche(lambda f: f["attente"] == 2)
        s.poser_la_main(prise=False, note="Note de l'Atelier : la page a changé.")
        resultat = s.reponse(premier)
        assert _textes(resultat) == ["Clicked.", "Note de l'Atelier : la page a changé."]
        assert "Note" not in " ".join(_textes(s.reponse(second))), "la note ne part qu'une fois"
        assert s.recus()[-2:] == ["click", "list_pages"], "dans l'ordre"
        assert not s.main.exists(), "la note consommée, le fichier part"
        s.lire_fiche(lambda f: f["attente"] == 0)
        assert _textes(s.appeler("click", uid="1_3")) == ["Clicked."]
    finally:
        s.fermer()


def test_une_note_sans_appel_retenu_attend_le_prochain(tmp_path: Path) -> None:
    s = Session(tmp_path)
    try:
        s.appeler("list_pages")
        s.poser_la_main(prise=False, note="Note de l'Atelier : reprise.")
        assert _textes(s.appeler("click", uid="x"))[-1] == "Note de l'Atelier : reprise."
        assert len(_textes(s.appeler("click", uid="x"))) == 1
    finally:
        s.fermer()


def test_une_main_gardee_trop_longtemps_libere_l_agent_avec_une_erreur(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_MAIN_MAX_S="1")
    try:
        s.appeler("list_pages")
        s.poser_la_main(prise=True, depuis=int(time.time() * 1000))
        ident = s.envoyer("click", uid="1")
        resultat = s.reponse(ident, delai=5)
        assert resultat["isError"] is True and "demande-lui où elle en est" in _textes(resultat)[0]
        assert "click" not in s.recus()
        # Une main posée il y a plus longtemps que le plafond est une main oubliée.
        s.poser_la_main(prise=True, depuis=int(time.time() * 1000) - 5000)
        assert _textes(s.appeler("click", uid="2")) == ["Clicked."]
    finally:
        s.fermer()


def test_un_appel_retenu_annule_ne_part_pas(tmp_path: Path) -> None:
    s = Session(tmp_path)
    try:
        s.appeler("list_pages")
        s.poser_la_main(prise=True, depuis=int(time.time() * 1000))
        annule = s.envoyer("click", uid="1")
        garde = s.envoyer("list_pages")
        s.ecrire({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": annule}})
        s.lire_fiche(lambda f: f["attente"] == 1)
        s.poser_la_main(prise=False)
        s.reponse(garde)
        assert "click" not in s.recus()
    finally:
        s.fermer()


def test_le_plafond_d_onglets_tient_main_rendue(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="2")
    try:
        assert not s.appeler("new_page", url="https://a.exemple/").get("isError")
        s.poser_la_main(prise=True, depuis=int(time.time() * 1000))
        ident = s.envoyer("new_page", url="https://b.exemple/")
        s.sans_reponse(ident)
        s.poser_la_main(prise=False, note="Note de l'Atelier : reprise.")
        refus = s.reponse(ident)
        assert refus["isError"] is True
        textes = _textes(refus)
        assert "Plafond d'onglets atteint" in textes[0] and textes[-1] == "Note de l'Atelier : reprise."
        assert s.recus().count("new_page") == 1, "le refus n'a pas atteint le serveur"
    finally:
        s.fermer()
