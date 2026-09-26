"""Une seule version pour le service, le paquet et le chart.

Le service rendait 0.1.0 par `/v1/health`, le paquet déclarait 0.2.0 et le
chart publié aussi (audit de publication, §6). La version vit désormais dans
`mcp_gateway/atelier/__init__.py` : le paquet la lit par `dynamic` et le
chart doit porter la même, ce que ce test tient.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from mcp_gateway.atelier import __version__

SRC = Path(__file__).resolve().parent.parent
DEPOT = SRC.parent


def test_la_version_est_semantique() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_le_paquet_lit_la_version_du_service() -> None:
    projet = tomllib.loads((SRC / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in projet["project"], "la version ne s'écrit qu'à un endroit"
    assert "version" in projet["project"]["dynamic"]
    assert projet["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "mcp_gateway.atelier.__version__"}


def test_le_chart_porte_la_version_du_service() -> None:
    chart = (DEPOT / "charts" / "atelier" / "Chart.yaml").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*\"?([^\"\s]+)\"?\s*$", chart, re.MULTILINE)
    assert m, "version introuvable dans Chart.yaml"
    assert m.group(1) == __version__


def test_le_journal_nomme_la_version_courante() -> None:
    journal = (DEPOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## .*\b{re.escape(__version__)}\b", journal, re.MULTILINE), (
        f"CHANGELOG.md n'a pas d'entrée pour {__version__}"
    )


def test_health_rend_la_version(atelier) -> None:
    r = atelier.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["version"] == __version__
