"""Le plafond d'onglets par conversation (`bin/atelier-chrome-onglets.mjs`).

Le filtre se place entre le client MCP et chrome-devtools-mcp. On le lance
devant un faux serveur (`faux_chrome_mcp.py`) qui tient ses pages dans la forme
du vrai (1.10.1), et on vérifie ce que le client reçoit et ce que le serveur
reçoit. Le vrai Chrome n'est pas lancé ici.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node absent")

FILTRE = Path(__file__).resolve().parents[1] / "bin" / "atelier-chrome-onglets.mjs"
FAUX = Path(__file__).with_name("faux_chrome_mcp.py")


class Session:
    def __init__(self, tmp_path: Path, **env: str) -> None:
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
                **env,
            },
        )
        self.suivant = 0

    def envoyer(self, outil: str, **arguments: Any) -> int:
        self.suivant += 1
        corps = {"jsonrpc": "2.0", "id": self.suivant, "method": "tools/call",
                 "params": {"name": outil, "arguments": arguments}}
        self.p.stdin.write(json.dumps(corps) + "\n")
        self.p.stdin.flush()
        return self.suivant

    def lire(self) -> dict[str, Any]:
        ligne = self.p.stdout.readline()
        assert ligne, self.p.stderr.read()
        return json.loads(ligne)

    def appeler(self, outil: str, **arguments: Any) -> dict[str, Any]:
        ident = self.envoyer(outil, **arguments)
        reponse = self.lire()
        assert reponse["id"] == ident
        return reponse["result"]

    def recus(self) -> list[str]:
        return self.journal.read_text(encoding="utf-8").splitlines() if self.journal.exists() else []

    def fermer(self) -> int:
        self.p.stdin.close()
        return self.p.wait(10)


def _texte(resultat: dict[str, Any]) -> str:
    return resultat["content"][0]["text"]


def test_au_dela_du_plafond_new_page_est_refuse_avec_un_message_clair(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="3")
    try:
        assert not s.appeler("new_page", url="https://a.test").get("isError")
        assert not s.appeler("new_page", url="https://b.test").get("isError")
        refus = s.appeler("new_page", url="https://c.test")
        assert refus["isError"] is True
        assert "3 onglets ouverts" in _texte(refus) and "pour 3 permis" in _texte(refus)
        assert "Ferme un onglet" in _texte(refus) and "close_page" in _texte(refus)
        assert s.recus().count("new_page") == 2, "le troisième n'a jamais atteint le serveur"
        # Un onglet fermé libère la place.
        s.appeler("close_page", pageId=2)
        assert not s.appeler("new_page", url="https://c.test").get("isError")
    finally:
        assert s.fermer() == 0


def test_le_compte_vient_du_serveur_pages_ouvertes_par_un_site_comprises(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="2")
    try:
        s.appeler("ouvrir_une_fenetre_surgissante")
        assert s.appeler("new_page", url="https://a.test")["isError"] is True
    finally:
        s.fermer()


def test_la_question_du_filtre_ne_parvient_pas_au_client(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="5")
    try:
        resultat = s.appeler("new_page", url="https://a.test")
        assert "https://a.test" in _texte(resultat)
        # Le client reçoit exactement ses réponses, dans l'ordre, sans celle de list_pages.
        premier = s.envoyer("new_page", url="https://b.test")
        second = s.envoyer("navigate_page", url="https://c.test")
        assert [s.lire()["id"], s.lire()["id"]] == [premier, second]
        assert s.recus() == ["list_pages", "new_page", "list_pages", "new_page", "navigate_page"]
    finally:
        s.fermer()


def test_zero_retire_le_plafond(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="0")
    try:
        for i in range(10):
            assert not s.appeler("new_page", url=f"https://{i}.test").get("isError")
        assert "list_pages" not in s.recus(), "sans plafond, aucune question en plus"
    finally:
        s.fermer()


def test_le_plafond_par_defaut_est_huit(tmp_path: Path) -> None:
    s = Session(tmp_path)
    try:
        for i in range(7):
            assert not s.appeler("new_page", url=f"https://{i}.test").get("isError"), i
        assert s.appeler("new_page", url="https://9.test")["isError"] is True
    finally:
        s.fermer()


def test_un_serveur_muet_ne_bloque_pas_l_agent(tmp_path: Path) -> None:
    """Sans réponse à list_pages, le filtre tranche au délai sur le dernier compte vu."""
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="2", FAUX_CHROME_MUET="1", ATELIER_CHROME_ONGLETS_DELAI_MS="300")
    try:
        # Aucun compte connu : il laisse passer.
        assert "https://a.test" in _texte(s.appeler("new_page", url="https://a.test"))
        # La réponse de new_page portait 2 pages : le suivant est refusé.
        assert s.appeler("new_page", url="https://b.test")["isError"] is True
    finally:
        s.fermer()


def test_la_fin_du_client_ferme_le_serveur(tmp_path: Path) -> None:
    s = Session(tmp_path, ATELIER_CHROME_ONGLETS_MAX="3")
    s.appeler("list_pages")
    assert s.fermer() == 0


def test_l_etat_du_navigateur_dit_ses_plafonds(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_gateway.atelier.navigateur import plafond_d_onglets, plafond_de_navigateurs

    monkeypatch.delenv("ATELIER_CHROME_ONGLETS_MAX", raising=False)
    monkeypatch.delenv("ATELIER_CHROME_MAX", raising=False)
    assert (plafond_d_onglets(), plafond_de_navigateurs()) == (8, 6)
    monkeypatch.setenv("ATELIER_CHROME_ONGLETS_MAX", "3")
    assert plafond_d_onglets() == 3
    monkeypatch.setenv("ATELIER_CHROME_ONGLETS_MAX", "beaucoup")
    assert plafond_d_onglets() == 8
