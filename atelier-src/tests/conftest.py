"""Un Atelier jetable, monté sur un répertoire de travail temporaire.

Toute la configuration découle de `ATELIER_WORK`, que les réglages relisent
à chaque instanciation : il suffit donc de le déplacer pour qu'un test ne
touche ni au PVC ni à l'installation de qui lance la suite. Le harnais
factice évite en plus de démarrer la passerelle et d'appeler un modèle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings


@pytest.fixture()
def atelier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ATELIER_WORK", str(tmp_path / "work"))
    with TestClient(build_app(settings=AtelierSettings(), use_fake=True)) as client:
        yield client


@pytest.fixture()
def cle_du_proprietaire(atelier: TestClient) -> str:
    """La clé créée à la volée par l'Atelier de test, jamais celle du pod."""
    settings = atelier.app.state.settings  # type: ignore[attr-defined]
    return settings.owner_key_path.read_text(encoding="utf-8").strip()
