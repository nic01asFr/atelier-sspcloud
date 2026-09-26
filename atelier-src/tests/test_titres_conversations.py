"""Un titre doit dire de quoi l'on parle.

Deux conversations du pod s'appelaient « This session is being continued from
a previous conversation ». Ce n'est pas un titre : c'est le préambule qu'un
agent se rédige à lui-même quand sa mémoire a été compactée, et il est le même
pour toutes. Dans la liste, elles devenaient indiscernables.

Le titre se prend sur la première prise de parole du transcript. Celle-là en
porte le rôle « user » sans être de quelqu'un — c'est tout le défaut.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.sessions import SessionStore, titre_utilisable

PREAMBULE = (
    "This session is being continued from a previous conversation that ran "
    "out of context. The summary below covers the earlier portion."
)


def _dire(texte: str) -> str:
    # Sans espace après les deux-points, comme le CLI les écrit : c'est à cette
    # forme-là que la lecture reconnaît une prise de parole.
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": texte}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _transcript(chemin: Path, lignes: list[str]) -> Path:
    chemin.write_text(chr(10).join(lignes) + chr(10), encoding="utf-8")
    return chemin


def test_un_preambule_de_reprise_n_est_pas_un_titre() -> None:
    assert titre_utilisable(PREAMBULE) is False
    assert titre_utilisable("<system-reminder>ceci est du contexte") is False
    assert titre_utilisable("Caveat: The messages below were generated") is False
    assert titre_utilisable("") is False


def test_une_vraie_question_en_est_un() -> None:
    assert titre_utilisable("Répare le build chrome-devtools") is True
    # Le mot « session » n'a rien de suspect en lui-même.
    assert titre_utilisable("Ma session VS Code ne reprend pas") is True


def test_le_titre_saute_le_preambule_et_prend_la_suite(reglages, tmp_path: Path) -> None:
    from mcp_gateway.atelier.harness import FakeHarness

    store = SessionStore(reglages, FakeHarness(reglages))
    source = _transcript(
        tmp_path / "s.jsonl",
        [_dire(PREAMBULE), _dire("Répare le build chrome-devtools")],
    )
    assert store._titre_depuis_claude(source) == "Répare le build chrome-devtools"


def test_un_preambule_tres_long_ne_masque_pas_la_suite(reglages, tmp_path: Path) -> None:
    """Il pèse parfois plus que les 64 ko qu'on lisait d'un coup.

    Le vrai premier message tombait alors hors de portée, et la conversation
    n'avait plus de titre du tout.
    """
    from mcp_gateway.atelier.harness import FakeHarness

    store = SessionStore(reglages, FakeHarness(reglages))
    source = _transcript(
        tmp_path / "s.jsonl",
        [_dire(PREAMBULE + " " + "x" * 90000), _dire("Reprends la migration")],
    )
    assert store._titre_depuis_claude(source) == "Reprends la migration"


def test_un_transcript_sans_rien_de_dit_n_invente_pas_de_titre(
    reglages, tmp_path: Path
) -> None:
    from mcp_gateway.atelier.harness import FakeHarness

    store = SessionStore(reglages, FakeHarness(reglages))
    source = _transcript(tmp_path / "s.jsonl", [_dire(PREAMBULE)])
    assert store._titre_depuis_claude(source) == ""


def _atelier_jetable(reglages, monkeypatch, tmp_path: Path):
    """Un magasin de conversations dont le HOME est jetable, lui aussi.

    La synchronisation lit les transcripts sous `~/.claude` : sans ce
    déplacement, la suite irait fouiller les vraies conversations de qui la
    lance, et pourrait y écrire.
    """
    from mcp_gateway.atelier.harness import FakeHarness

    faux = tmp_path / "faux-home"
    faux.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    assert Path.home() == faux, "le déplacement du HOME n'a pas pris"
    return SessionStore(reglages, FakeHarness(reglages))


def test_une_fiche_deja_mal_nommee_se_repare(reglages, monkeypatch, tmp_path: Path) -> None:
    """Elles ne se seraient jamais renommées seules.

    Le titre est posé une fois, à l'adoption. Corriger la dérivation ne
    corrige pas ce qui porte déjà le préambule : deux conversations du pod
    seraient restées ainsi. La réparation se fait à la synchronisation.
    """
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai", title=PREAMBULE)
    rec.claude_session_id = "cli-1234"
    store.save(rec)

    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    _transcript(
        dossier / "cli-1234.jsonl",
        [_dire(PREAMBULE), _dire("Reprends la migration des connecteurs")],
    )

    store.sync_claude_titles()
    assert store.get(rec.session_id).title == "Reprends la migration des connecteurs"


def test_sans_transcript_a_relire_le_titre_est_laisse_tel_quel(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """Mieux vaut un mauvais titre qu'un titre effacé."""
    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai", title=PREAMBULE)

    store.sync_claude_titles()
    assert store.get(rec.session_id).title == PREAMBULE


def test_l_ide_ne_peut_pas_reposer_un_preambule(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """L'autre source de titres, et le même piège.

    Le nom vient aussi de ce que Claude Code range dans `.claude/sessions`.
    S'il porte le préambule, il réécrirait par la bande le titre qu'on vient
    de retrouver.
    """
    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai", title="Répare le build")
    rec.turns = 3
    store.save(rec)

    sessions = reglages.work_dir / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "x.json").write_text(
        json.dumps({"sessionId": rec.session_id, "name": PREAMBULE, "cwd": rec.cwd}),
        encoding="utf-8",
    )

    store.sync_claude_titles()
    assert store.get(rec.session_id).title == "Répare le build"


def test_nom_provisoire_ecarte(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """« nouveau-projet-6d » ne dit pas de quoi l'on parle.

    Le CLI se nomme ainsi en attendant un vrai nom, qu'il ne pose qu'après un
    premier tour abouti. Une conversation dont le premier tour échouait
    gardait ce nom pour titre ; le premier message, lui, est déjà là.
    """
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai")
    rec.claude_session_id = "cli-1"
    store.save(rec)

    sessions = reglages.work_dir / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "x.json").write_text(
        json.dumps(
            {
                "sessionId": "cli-1",
                "name": "essai-6d",
                "nameSource": "derived",
                "cwd": rec.cwd,
            }
        ),
        encoding="utf-8",
    )
    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    _transcript(dossier / "cli-1.jsonl", [_dire("Pose le bureau Chrome")])

    store.sync_claude_titles()
    assert store.get(rec.session_id).title == "Pose le bureau Chrome"


def test_nom_provisoire_repare(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """Trois conversations du pod le portaient déjà."""
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai", title="essai-d5")
    rec.claude_session_id = "cli-1"
    rec.turns = 16
    store.save(rec)

    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    _transcript(dossier / "cli-1.jsonl", [_dire("Reprends le build")])

    store.sync_claude_titles()
    assert store.get(rec.session_id).title == "Reprends le build"


def test_nom_provisoire_motif_exact(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """Seul le motif exact dossier-deux-hexadécimaux est provisoire."""
    from mcp_gateway.atelier.sessions import _est_un_nom_derive

    assert _est_un_nom_derive("essai-6d", "essai") is True
    assert _est_un_nom_derive("essai-v2", "essai") is False
    assert _est_un_nom_derive("essai-6d4", "essai") is False
    assert _est_un_nom_derive("autre-6d", "essai") is False


def test_une_fiche_ready_se_relit_au_repos(reglages, monkeypatch, tmp_path: Path) -> None:
    """« ready » n'est pas un état de l'Atelier ; la liste l'affichait en anglais."""
    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai")
    chemin = store._path(rec.session_id)
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    donnees["state"] = "ready"
    chemin.write_text(json.dumps(donnees), encoding="utf-8")
    assert store.get(rec.session_id).state == "idle"


def test_une_conversation_de_l_assistant_prend_son_titre_du_premier_message(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    """Essais du 26/09 : « wikichat-memory-a5827138 » pendant tout le premier tour.

    Le titre ne venait que du transcript, relu à la fin du tour. La liste,
    rafraîchie au premier événement du tour, montrait donc l'identifiant. Il
    se prend maintenant sur le premier message, dès l'envoi, pour l'Assistant
    comme pour Code.
    """
    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug=reglages.assistant_slug, kind="assistant")
    assert rec.title == f"{reglages.assistant_slug}-{rec.session_id[:8]}"

    vus: list[str] = []
    store.send(
        rec.session_id,
        "Où en est le projet Lecteur Grist, et qu'est-ce qui attend mon accord ?",
        on_event=lambda ev: vus.append(store.get(rec.session_id).title),
    )
    assert vus, "le faux harnais a émis des événements"
    attendu = "Où en est le projet Lecteur Grist, et qu'est-ce qui attend m"
    assert vus[0] == attendu, "dès le premier événement du tour"
    assert store.get(rec.session_id).title == attendu


def test_le_premier_message_ne_remplace_pas_un_titre_choisi(
    reglages, monkeypatch, tmp_path: Path
) -> None:
    store = _atelier_jetable(reglages, monkeypatch, tmp_path)
    rec = store.create(slug="essai")
    store.patch(rec.session_id, title="Mon titre")
    store.send(rec.session_id, "Répare le build")
    assert store.get(rec.session_id).title == "Mon titre"

    code = store.create(slug="essai")
    store.send(code.session_id, "<!DOCTYPE html><html>")
    assert store.get(code.session_id).title == f"essai-{code.session_id[:8]}", "rien de lisible : défaut"
    store.send(code.session_id, "Répare le build")
    assert store.get(code.session_id).title == f"essai-{code.session_id[:8]}", "seulement au premier tour"
