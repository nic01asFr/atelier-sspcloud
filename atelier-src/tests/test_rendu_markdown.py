"""Le rendu des messages, vérifié depuis la suite Python.

Le rendu vit en JavaScript et n'a pas de banc d'essai à lui. Plutôt que d'en
monter un, on lance le script de vérification avec le node de la machine et
on lit son verdict : la suite reste unique, et un rendu cassé se voit au même
endroit que le reste.

Ce que ça tient : qu'un tableau markdown devienne un tableau. Il arrivait tel
quel dans le message, barres et ligne de séparation comprises, avalé par le
paragraphe fourre-tout du rendu.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
VERIFICATION = RACINE / "tests" / "js" / "rendu_markdown.mjs"
MODULE = RACINE / "mcp_gateway" / "atelier" / "web" / "js" / "ui" / "markdown.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent de la machine")
def test_un_tableau_markdown_devient_un_tableau() -> None:
    proc = subprocess.run(
        ["node", str(VERIFICATION), str(MODULE)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
