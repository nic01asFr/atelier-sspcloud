"""Un Atelier jetable, monté sur un répertoire de travail temporaire.

Le répertoire est passé au constructeur, pas par l'environnement. La variable
`ATELIER_WORK` est lue à l'import du module de configuration, et le champ
`work_dir` répond de son côté à `ATELIER_WORK_DIR` : poser l'une pendant que
le code attend l'autre donne un Atelier qui croit être ailleurs et écrit dans
le vrai dossier de travail de qui lance la suite. C'est arrivé. Le passage
explicite ne laisse pas cette place au doute, et l'assertion la referme.

Le harnais factice évite en plus de démarrer la passerelle et d'appeler un
modèle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings


@pytest.fixture(autouse=True)
def _maison_jetable(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Un HOME à soi pour chaque test.

    L'Atelier écrit dans `~/.claude.json` à chaque liaison de projet (et donc
    à chaque tour) : sans cela, la suite réécrirait celui de qui la lance.
    """
    maison = tmp_path_factory.mktemp("maison")
    monkeypatch.setenv("HOME", str(maison))
    monkeypatch.setenv("USERPROFILE", str(maison))
    return maison


def _port_sans_personne() -> int:
    """Un port où rien n'écoute : le relais LLM y est « absent »."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def reglages(tmp_path: Path) -> AtelierSettings:
    settings = AtelierSettings(work_dir=tmp_path / "work")
    assert tmp_path in settings.work_dir.parents or settings.work_dir.parent == tmp_path
    # Le relais LLM du pod écoute sur 8790 : lancée là, la suite le verrait et
    # changerait de comportement. Chaque test a le sien, absent sauf s'il en
    # démarre un.
    settings.relais_llm_port = _port_sans_personne()
    return settings


@pytest.fixture()
def atelier(reglages: AtelierSettings) -> Iterator[TestClient]:
    # En HTTPS, comme le service l'est derrière son ingress : le cookie de
    # session est posé `Secure`, et un client qui se croit en clair ne le
    # renverrait jamais — on testerait alors une authentification qui marche
    # en production et pas ici, ou l'inverse.
    with TestClient(
        build_app(settings=reglages, use_fake=True), base_url="https://testserver"
    ) as client:
        yield client


@pytest.fixture()
def cle_du_proprietaire(atelier: TestClient) -> str:
    """La clé créée à la volée par l'Atelier de test, jamais celle du pod."""
    settings = atelier.app.state.settings  # type: ignore[attr-defined]
    return settings.owner_key_path.read_text(encoding="utf-8").strip()
