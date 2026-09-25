"""Les défauts d'interface relevés le 25/09 (lot H), côté service et flux.

- un demi-emoji (substitut isolé) faisait échouer l'écriture du journal et du
  flux vers le navigateur ;
- un premier message qui colle du HTML devenait le titre de la conversation ;
- deux lectures simultanées de la liste créaient deux fiches pour un même fil ;
- le `systemMessage` d'un hook (relance de wikichat) ne se voyait pas.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from mcp_gateway.atelier.events import parse_stream_json_line, sans_substituts, texte_sur
from mcp_gateway.atelier.sessions import SessionStore, titre_lisible, titre_utilisable

DEMI = "\\ud83d"  # la moitié haute d'un emoji, telle que le JSON du CLI l'écrit


# ── Substituts isolés ──────────────────────────────────────────────────


def test_un_demi_emoji_du_flux_s_ecrit_en_utf8() -> None:
    ligne = (
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":"voilà ' + DEMI + '"}}}'
    )
    [ev] = parse_stream_json_line("s", ligne)
    assert ev.text == "voil\u00e0 \ufffd"
    ev.as_sse().encode("utf-8")  # levait « surrogates not allowed »


def test_deux_moities_voisines_se_recollent() -> None:
    assert texte_sur("\ud83d\ude00") == "\U0001F600"
    assert texte_sur("sans rien") == "sans rien"
    assert sans_substituts({"a": ["\ud83d"], "b": 1}) == {"a": ["\ufffd"], "b": 1}


def test_l_absorption_d_un_transcript_a_demi_emoji_ne_tombe_plus(monkeypatch) -> None:
    import shutil
    import tempfile

    from mcp_gateway.atelier.config import AtelierSettings
    from mcp_gateway.atelier.harness import FakeHarness
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    # Des chemins courts : sous Windows, le dossier du CLI encode tout le
    # chemin du projet et dépasse vite les 260 caractères.
    racine = Path(tempfile.mkdtemp(prefix="lh"))
    try:
        (racine / "h").mkdir()
        monkeypatch.setenv("HOME", str(racine / "h"))
        monkeypatch.setenv("USERPROFILE", str(racine / "h"))
        reglages = AtelierSettings(work_dir=racine / "w")
        store = SessionStore(reglages, FakeHarness(reglages))
        rec = store.create(slug="e")
        dossier = dossier_transcripts_claude(Path(rec.cwd))
        dossier.mkdir(parents=True, exist_ok=True)
        ligne = (
            '{"type":"assistant","uuid":"u-1","message":{"role":"assistant",'
            '"content":[{"type":"text","text":"ok ' + DEMI + '"}]}}'
        )
        (dossier / f"{rec.session_id}.jsonl").write_text(ligne + chr(10), encoding="utf-8")
        assert store.absorber_le_cli(rec) == 1
        assert "ok \ufffd" in Path(rec.transcript_path).read_text(encoding="utf-8")
    finally:
        shutil.rmtree(racine, ignore_errors=True)


# ── Titres ─────────────────────────────────────────────────────────────


def test_du_html_colle_n_est_pas_un_titre() -> None:
    page = '<!DOCTYPE html> <html lang="fr"><head><style>h1{}</style></head><body><h1>Carte des parcelles</h1>'
    assert titre_utilisable(page) is False
    assert titre_utilisable('{"cle": 1}') is False
    assert titre_utilisable("```python\nprint(1)\n```") is False
    assert titre_lisible(page) == "Carte des parcelles"
    assert titre_lisible("```\nx = 1\n```") == ""
    assert titre_lisible("Corrige <b>ce</b> tableau") == "Corrige ce tableau"


def test_une_fiche_titree_en_html_se_repare(reglages, monkeypatch, tmp_path: Path) -> None:
    from mcp_gateway.atelier.harness import FakeHarness
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    faux = tmp_path / "h"
    faux.mkdir()
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    store = SessionStore(reglages, FakeHarness(reglages))
    rec = store.create(slug="essai", title='<!DOCTYPE html> <html lang="fr">')
    rec.claude_session_id = "cli-9"
    store.save(rec)
    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    message = '<!DOCTYPE html><html><body><h1>Tableau des loyers</h1><p>Rends-le triable</p></body></html>'
    (dossier / "cli-9.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": message}}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    store.sync_claude_titles()
    assert store.get(rec.session_id).title == "Tableau des loyers Rends-le triable"


# ── Une fiche par fil ──────────────────────────────────────────────────


def test_deux_lectures_simultanees_n_adoptent_qu_une_fois(reglages, monkeypatch, tmp_path: Path) -> None:
    from mcp_gateway.atelier.harness import FakeHarness
    from mcp_gateway.atelier.projects import ProjectStore
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    faux = tmp_path / "h"
    faux.mkdir()
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    projet = ProjectStore(reglages).create("essai", kind="code")
    dossier = dossier_transcripts_claude(Path(projet.path))
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = [
        {"type": "user", "entrypoint": "claude-vscode", "uuid": "a", "sessionId": "fil-vscode",
         "message": {"role": "user", "content": "Ajoute un filtre par commune"}},
        {"type": "assistant", "uuid": "b", "sessionId": "fil-vscode",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "fait"}]}},
    ]
    (dossier / "fil-vscode.jsonl").write_text(
        "\n".join(json.dumps(x, separators=(",", ":")) for x in lignes) + "\n", encoding="utf-8"
    )

    store = SessionStore(reglages, FakeHarness(reglages))
    depart = threading.Barrier(6)

    def lire() -> None:
        depart.wait()
        SessionStore(reglages, FakeHarness(reglages)).sync_claude_titles()

    fils = [threading.Thread(target=lire) for _ in range(6)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(30)
    fiches = [r for r in store.list_sessions(include_archived=True) if r.claude_session_id == "fil-vscode"]
    assert len(fiches) == 1, [r.session_id for r in fiches]


# ── Ce que wikichat dit dans le flux ───────────────────────────────────


def test_le_message_d_un_hook_devient_un_evenement_lisible() -> None:
    texte = "wikichat : tour prolongé — réponse attendue par gardien (relance 1/3)."
    for ligne in (
        {"type": "system", "subtype": "informational", "content": texte},
        {"type": "system", "subtype": "hook_response", "output": json.dumps({"systemMessage": texte})},
        {"type": "system", "systemMessage": texte},
    ):
        [ev] = parse_stream_json_line("s", json.dumps(ligne, ensure_ascii=False))
        assert (ev.kind, ev.cause, ev.text) == ("systeme", "message_systeme", texte), ligne
    # Une ligne système ordinaire reste ce qu'elle était.
    [ev] = parse_stream_json_line("s", json.dumps({"type": "system", "subtype": "init"}))
    assert ev.cause == "" and ev.text == "init"
