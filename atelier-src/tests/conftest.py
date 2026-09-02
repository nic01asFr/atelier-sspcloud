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


@pytest.fixture()
def reglages(tmp_path: Path) -> AtelierSettings:
    settings = AtelierSettings(work_dir=tmp_path / "work")
    assert tmp_path in settings.work_dir.parents or settings.work_dir.parent == tmp_path
    return settings


@pytest.fixture()
def atelier(reglages: AtelierSettings) -> Iterator[TestClient]:
    with TestClient(build_app(settings=reglages, use_fake=True)) as client:
        yield client


@pytest.fixture()
def cle_du_proprietaire(atelier: TestClient) -> str:
    """La clé créée à la volée par l'Atelier de test, jamais celle du pod."""
    settings = atelier.app.state.settings  # type: ignore[attr-defined]
    return settings.owner_key_path.read_text(encoding="utf-8").strip()
