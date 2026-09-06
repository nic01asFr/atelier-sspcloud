"""VS Code et l'Atelier doivent donner la même boîte à outils.

Mesuré le 6 septembre : la conversation `83f88a57`, ouverte dans VS Code,
y voyait dix connecteurs quand l'Atelier ne lui en donnait que quatre —
`datagouv`, `github`, `gitlab`, `llm`, `n8n` et `qgis` en trop. Le même agent,
sur le même fil, n'avait pas les mêmes outils selon la fenêtre par laquelle on
l'ouvrait, et aucun des deux écrans ne le disait.

L'écart vient de la portée utilisateur : l'Atelier y dépose tout le pool des
connecteurs actifs, et VS Code le sert à toute conversation, sans rien savoir
du périmètre du projet ni du réglage propre au fil. On ne vide pas ce pool —
un projet sans `.mcp.json` en hérite par conception. On masque pour le dossier
que VS Code va ouvrir, avec la liste que le CLI applique lui-même.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.vscode_handoff import accorder_les_connecteurs


def _maison(tmp_path: Path, monkeypatch, pool: list[str], projet: dict | None = None) -> Path:
    """Un HOME jetable portant un pool de connecteurs."""
    faux = tmp_path / "home"
    faux.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    assert Path.home() == faux
    (faux / ".claude.json").write_text(
        json.dumps({"mcpServers": {n: {"url": f"http://{n}"} for n in pool}, "projects": projet or {}}),
        encoding="utf-8",
    )
    return faux


def _masques(maison: Path, dossier: Path) -> list[str]:
    d = json.loads((maison / ".claude.json").read_text(encoding="utf-8"))
    return d["projects"][str(dossier)]["disabledMcpServers"]


def test_ce_que_la_conversation_n_a_pas_est_masque(tmp_path: Path, monkeypatch) -> None:
    maison = _maison(tmp_path, monkeypatch, ["atelier", "qgis", "llm", "wikichat"])
    dossier = tmp_path / "projet"
    dossier.mkdir()

    accorder_les_connecteurs(dossier, {"atelier", "wikichat"})
    assert _masques(maison, dossier) == ["llm", "qgis"]


def test_une_conversation_qui_a_tout_ne_masque_rien(tmp_path: Path, monkeypatch) -> None:
    maison = _maison(tmp_path, monkeypatch, ["atelier", "wikichat"])
    dossier = tmp_path / "projet"
    dossier.mkdir()

    accorder_les_connecteurs(dossier, {"atelier", "wikichat"})
    assert _masques(maison, dossier) == []


def test_le_perimetre_du_projet_compte_aussi(tmp_path: Path, monkeypatch) -> None:
    """VS Code sert le `.mcp.json` du projet en plus du pool.

    Un connecteur qui n'existe que là doit pouvoir être masqué comme un autre,
    sans quoi il resterait visible d'un seul côté.
    """
    maison = _maison(tmp_path, monkeypatch, ["atelier"])
    dossier = tmp_path / "projet"
    dossier.mkdir()
    (dossier / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"maison": {"url": "http://maison"}}}), encoding="utf-8"
    )

    accorder_les_connecteurs(dossier, {"atelier"})
    assert _masques(maison, dossier) == ["maison"]


def test_le_pool_lui_meme_n_est_jamais_touche(tmp_path: Path, monkeypatch) -> None:
    """Un projet sans `.mcp.json` en hérite : le vider casserait ces projets-là."""
    maison = _maison(tmp_path, monkeypatch, ["atelier", "qgis"])
    dossier = tmp_path / "projet"
    dossier.mkdir()

    accorder_les_connecteurs(dossier, {"atelier"})
    d = json.loads((maison / ".claude.json").read_text(encoding="utf-8"))
    assert sorted(d["mcpServers"]) == ["atelier", "qgis"]


def test_le_reste_du_fichier_survit(tmp_path: Path, monkeypatch) -> None:
    """`~/.claude.json` porte l'onboarding, les projets, l'identité machine."""
    maison = _maison(tmp_path, monkeypatch, ["atelier"])
    chemin = maison / ".claude.json"
    d = json.loads(chemin.read_text(encoding="utf-8"))
    d["userID"] = "moi"
    d["projects"]["/ailleurs"] = {"mcpServers": {}}
    chemin.write_text(json.dumps(d), encoding="utf-8")
    dossier = tmp_path / "projet"
    dossier.mkdir()

    accorder_les_connecteurs(dossier, {"atelier"})
    apres = json.loads(chemin.read_text(encoding="utf-8"))
    assert apres["userID"] == "moi"
    assert "/ailleurs" in apres["projects"]


def test_un_fichier_illisible_ne_bloque_pas_l_ouverture(tmp_path: Path, monkeypatch) -> None:
    """Mieux vaut ouvrir VS Code avec trop d'outils que ne pas l'ouvrir."""
    faux = tmp_path / "home"
    faux.mkdir()
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    (faux / ".claude.json").write_text("{ceci n'est pas du json", encoding="utf-8")
    dossier = tmp_path / "projet"
    dossier.mkdir()

    assert accorder_les_connecteurs(dossier, {"atelier"}) == []


def test_un_connecteur_sans_transport_est_ecarte_en_silence() -> None:
    """Le CLI refuse une adresse sans `type`, et ne le dit qu'en diagnostic.

    Relevé sur le pod : « [github] Skipped — MCP server "github" has a "url"
    but no "type" ». Deux connecteurs du pool étaient dans ce cas. Ils
    s'affichaient actifs dans l'Atelier et n'offraient aucun outil — c'est la
    panne que Nicolas décrivait par « ajouté avec sa clé, aucun outil listé ».
    """
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "https://x/mcp"})["type"] == "http"


def test_une_adresse_en_sse_annonce_son_transport() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "http://127.0.0.1:3777/sse"})["type"] == "sse"
    # La requête ne doit pas masquer la terminaison : wikichat porte `?agent=`.
    assert _avec_son_transport({"url": "http://x/sse?agent=moi"})["type"] == "sse"


def test_un_transport_declare_n_est_jamais_reecrit() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "http://x/sse", "type": "http"})["type"] == "http"


def test_un_connecteur_en_commande_n_a_pas_de_transport() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert "type" not in _avec_son_transport({"command": "node", "args": ["s.js"]})
