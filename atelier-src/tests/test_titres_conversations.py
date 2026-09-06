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
