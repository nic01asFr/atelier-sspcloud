"""Le filet JavaScript, lancé avec le reste.

Le serveur a ses tests ; l'interface n'avait que `node --check`. Les
fonctions pures de l'interface — surlignage, fil d'un tour, file de messages,
lecture du transcript — se testent sans navigateur, avec `node --test`. Ce
test les lance ; sans node sur le poste, il se retire en le disant.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DOSSIER = Path(__file__).parent.parent / "tests-js"


def test_les_tests_javascript_passent() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent du poste")
    fichiers = sorted(str(p) for p in DOSSIER.glob("*.test.mjs"))
    assert fichiers, "aucun test JavaScript trouvé"
    resultat = subprocess.run(
        [node, "--test", *fichiers],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(DOSSIER.parent),
    )
    assert resultat.returncode == 0, resultat.stdout[-3000:] + resultat.stderr[-3000:]
