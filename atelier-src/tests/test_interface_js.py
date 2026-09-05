"""Les suites de l'interface, lancées depuis la suite Python.

L'interface vit en JavaScript et n'a pas de banc à elle. Plutôt que d'en
monter un — ce qui coûterait npm, un `package.json` et des dépendances dans un
dépôt Python —, on écrit des scripts autonomes que le node de la machine sait
lancer, et on lit leur verdict ici.

Ce fichier ne connaît aucune suite en particulier : il ramasse tout fichier
`tests/js/*.suite.mjs`. Écrire une suite de plus ne demande donc pas de
toucher au Python, et en renommer une ne la fait pas disparaître en silence —
le premier test veille à ce qu'il en reste au moins une.

Ce que ça tient : quatre défauts d'affichage se sont logés dans le fil de
conversation sans qu'aucun test ne les voie — ils ont été trouvés à l'œil, un
par un. Le socle est là pour que le suivant se voie ici.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "tests" / "js"
SUITES = sorted(DOSSIER.glob("*.suite.mjs"))

sans_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node absent de la machine"
)


def test_les_suites_js_sont_trouvees() -> None:
    """Un ramassage qui ne ramasse rien passerait au vert sans rien vérifier."""
    assert SUITES, f"aucune suite *.suite.mjs dans {DOSSIER}"


@sans_node
@pytest.mark.parametrize("suite", SUITES, ids=lambda p: p.name.removesuffix(".suite.mjs"))
def test_suite_js(suite: Path) -> None:
    proc = subprocess.run(
        ["node", str(suite)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(RACINE),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
