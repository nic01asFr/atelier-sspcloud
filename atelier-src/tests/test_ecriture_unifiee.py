"""Ce qui est écrit ailleurs doit entrer dans notre cahier, pas seulement s'y lire.

La fusion à la lecture montrait la bonne histoire, mais n'en gardait qu'une
moitié : le jour où le registre du CLI est réécrit ou purgé, ce qui n'existait
que là disparaîtrait. L'absorption le recopie chez nous, où l'on ne fait
qu'ajouter.

Le CLI estampille chaque entrée du point d'entrée qui l'a produite — `sdk-cli`
pour les tours que mène l'Atelier, `claude-vscode` pour l'extension, `cli` pour
un terminal. C'est ce qui permet de reprendre ce qui vient d'ailleurs sans
reprendre ce qu'on a déjà écrit soi-même.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.journal import a_absorber, paroles_humaines


def _entree(texte: str, origine: str, uuid: str = "u1", type_: str = "user") -> str:
    return json.dumps(
        {
            "type": type_,
            "uuid": uuid,
            "entrypoint": origine,
            "timestamp": "10:00",
            "message": {"role": type_, "content": [{"type": "text", "text": texte}]},
        },
        ensure_ascii=False,
    )


def _registre(chemin: Path, lignes: list[str]) -> Path:
    chemin.write_text(chr(10).join(lignes) + chr(10), encoding="utf-8")
    return chemin


def test_ce_qui_vient_de_vs_code_est_repris(tmp_path: Path) -> None:
    c = _registre(tmp_path / "cli.jsonl", [_entree("tape dans VS Code", "claude-vscode")])
    entrees, position = a_absorber(c, 0)

    assert [e["message"]["content"][0]["text"] for e in entrees] == ["tape dans VS Code"]
    assert position == c.stat().st_size


def test_une_entree_deja_au_cahier_n_est_pas_reprise(tmp_path: Path) -> None:
    """Le critère est le `uuid`, pas la provenance."""
    c = _registre(tmp_path / "cli.jsonl", [_entree("deja chez nous", "sdk-cli", "u1")])
    entrees, _ = a_absorber(c, 0, {"u1"})

    assert entrees == []


def test_nos_propres_tours_manquants_sont_repris_aussi(tmp_path: Path) -> None:
    """Le premier critère, la provenance, laissait dehors trente-sept entrées.

    Notre harnais ne consigne pas chaque appel d'outil ligne à ligne : il n'en
    garde que le rendu. Ces entrées-là n'existaient donc que dans le registre
    du CLI, et disparaîtraient avec lui.
    """
    c = _registre(tmp_path / "cli.jsonl", [_entree("un tour a nous", "sdk-cli", "u1")])
    entrees, _ = a_absorber(c, 0, set())

    assert [e["message"]["content"][0]["text"] for e in entrees] == ["un tour a nous"]


def test_une_entree_sans_uuid_n_est_jamais_reprise(tmp_path: Path) -> None:
    """On ne saurait pas la reconnaître au passage suivant.

    Mieux vaut manquer une reprise que dédoubler : un doublon ne se retire plus
    d'un journal qui ne fait qu'ajouter.
    """
    ligne = json.dumps({
        "type": "user", "timestamp": "10:00",
        "message": {"role": "user", "content": [{"type": "text", "text": "sans marque"}]},
    })
    c = _registre(tmp_path / "cli.jsonl", [ligne])
    entrees, _ = a_absorber(c, 0, set())

    assert entrees == []


def test_le_meme_uuid_deux_fois_dans_le_fichier_n_entre_qu_une_fois(tmp_path: Path) -> None:
    c = _registre(tmp_path / "cli.jsonl", [
        _entree("un", "claude-vscode", "u1"),
        _entree("un", "claude-vscode", "u1"),
    ])
    entrees, _ = a_absorber(c, 0, set())

    assert len(entrees) == 1


def test_le_compteur_suit_ce_que_le_fil_montre() -> None:
    """Il ne comptait que les tours menés depuis l'Atelier.

    Une conversation travaillée dans VS Code s'annonçait « 2 tour(s) » alors
    que son fil en portait bien davantage.
    """
    entrees = [
        json.loads(_entree("une question", "claude-vscode", "u1")),
        json.loads(_entree("une reponse", "claude-vscode", "u2", type_="assistant")),
        json.loads(_entree("une autre question", "sdk-cli", "u3")),
    ]
    assert paroles_humaines(entrees) == 2


def test_un_retour_d_outil_n_est_pas_une_parole() -> None:
    entree = {
        "type": "user", "uuid": "u1",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "sortie de commande"}]},
    }
    assert paroles_humaines([entree]) == 0


def test_on_ne_reprend_pas_deux_fois_la_meme_chose(tmp_path: Path) -> None:
    c = _registre(tmp_path / "cli.jsonl", [_entree("un", "claude-vscode", "u1")])
    _, position = a_absorber(c, 0)

    with c.open("a", encoding="utf-8") as f:
        f.write(_entree("deux", "claude-vscode", "u2") + chr(10))
    entrees, _ = a_absorber(c, position)

    assert [e["message"]["content"][0]["text"] for e in entrees] == ["deux"]


def test_un_registre_reecrit_se_relit_depuis_le_debut(tmp_path: Path) -> None:
    """S'il a rétréci, reprendre à l'ancien octet lirait au milieu d'une ligne."""
    c = _registre(tmp_path / "cli.jsonl", [_entree("longue histoire " * 20, "claude-vscode", "u1")])
    _, position = a_absorber(c, 0)
    _registre(c, [_entree("court", "claude-vscode", "u2")])

    entrees, _ = a_absorber(c, position)
    assert [e["message"]["content"][0]["text"] for e in entrees] == ["court"]


def test_le_machinal_n_entre_pas_dans_le_cahier(tmp_path: Path) -> None:
    c = _registre(tmp_path / "cli.jsonl", [
        _entree("<task-notification> abc </task-notification>", "claude-vscode", "u1"),
        _entree("une vraie question", "claude-vscode", "u2"),
    ])
    entrees, _ = a_absorber(c, 0)

    assert [e["message"]["content"][0]["text"] for e in entrees] == ["une vraie question"]


def test_un_registre_absent_ne_fait_rien(tmp_path: Path) -> None:
    entrees, position = a_absorber(tmp_path / "jamais.jsonl", 42)
    assert entrees == [] and position == 42


def test_un_tour_en_cours_suspend_l_absorption(atelier) -> None:
    """Deux plumes sur le même fichier couperaient une ligne en deux."""
    from test_canal_decision import _cle

    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Absorption"}
    ).json()["session_id"]
    store = atelier.app.state.sessions if hasattr(atelier.app.state, "sessions") else None
    if store is None:
        from mcp_gateway.atelier.sessions import SessionStore

        store = SessionStore(atelier.app.state.settings, atelier.app.state.harness)
    rec = store.get(sid)
    atelier.app.state.harness._running[sid] = True

    assert store.absorber_le_cli(rec) == 0


def _atelier_court(monkeypatch):
    """Un Atelier aux chemins courts.

    Les transcripts de Claude Code encodent le répertoire de travail dans leur
    nom : sous un `tmp_path` de pytest, le chemin obtenu dépasse la limite de
    Windows. C'est une gêne d'atelier de test, pas un défaut du produit — sur
    le pod les chemins sont courts.
    """
    import tempfile

    from mcp_gateway.atelier.config import AtelierSettings
    from mcp_gateway.atelier.harness import FakeHarness
    from mcp_gateway.atelier.sessions import SessionStore

    racine = Path(tempfile.mkdtemp(prefix="a"))
    faux = racine / "h"
    faux.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("USERPROFILE", str(faux))
    assert Path.home() == faux
    reglages = AtelierSettings(work_dir=racine / "w")
    return SessionStore(reglages, FakeHarness(reglages))


def test_absorber_met_le_compteur_a_jour(monkeypatch) -> None:
    """Le nombre affiché doit dire ce que le fil montre.

    Il ne comptait que les tours menés depuis l'Atelier : `a948d684`
    s'annonçait « 2 tour(s) » avec deux cent soixante-sept entrées au cahier,
    parce que le travail avait eu lieu dans VS Code.
    """
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_court(monkeypatch)
    rec = store.create(slug="e", title="Compteur")
    assert rec.turns == 0

    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    _registre(dossier / f"{rec.session_id}.jsonl", [
        _entree("premiere question", "claude-vscode", "v1"),
        _entree("une reponse", "claude-vscode", "v2", type_="assistant"),
        _entree("deuxieme question", "claude-vscode", "v3"),
        _entree("troisieme question", "claude-vscode", "v4"),
    ])

    reprises = store.absorber_le_cli(rec)
    assert reprises == 4
    assert store.get(rec.session_id).turns == 3, "le compteur ignore ce qui vient d'ailleurs"


def test_le_compteur_ne_recule_jamais(monkeypatch) -> None:
    """Un registre purgé ailleurs ne doit pas effacer nos tours à nous."""
    store = _atelier_court(monkeypatch)
    rec = store.create(slug="e", title="Compteur deux")
    rec.turns = 9
    store.save(rec)

    store.absorber_le_cli(rec)
    assert store.get(rec.session_id).turns == 9


def test_un_changement_de_critere_fait_rebalayer(monkeypatch) -> None:
    """La marque posée sous l'ancienne règle ne vaut plus sous la nouvelle.

    Mesuré sur le pod : quatre conversations rendaient zéro reprise alors qu'il
    leur manquait des dizaines d'entrées — leur marque d'octets avait dépassé
    ce que l'ancien critère écartait, et rien ne serait jamais revenu le
    chercher.
    """
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_court(monkeypatch)
    rec = store.create(slug="e", title="Rebalayage")
    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    registre = _registre(dossier / f"{rec.session_id}.jsonl", [
        _entree("laissee dehors par l ancienne regle", "sdk-cli", "v1"),
    ])

    # L'état d'avant : la marque est au bout du fichier, sous l'ancien critère.
    rec.octets_absorbes = registre.stat().st_size
    rec.critere_absorption = 0
    store.save(rec)

    assert store.absorber_le_cli(store.get(rec.session_id)) == 1
    assert store.get(rec.session_id).critere_absorption == 1


def test_le_rebalayage_ne_se_rejoue_pas(monkeypatch) -> None:
    """Une fois la marque à jour, on ne relit plus tout à chaque passage."""
    from mcp_gateway.atelier.vscode_handoff import dossier_transcripts_claude

    store = _atelier_court(monkeypatch)
    rec = store.create(slug="e", title="Une seule fois")
    dossier = dossier_transcripts_claude(Path(rec.cwd))
    dossier.mkdir(parents=True, exist_ok=True)
    _registre(dossier / f"{rec.session_id}.jsonl", [_entree("une", "claude-vscode", "v1")])

    assert store.absorber_le_cli(store.get(rec.session_id)) == 1
    assert store.absorber_le_cli(store.get(rec.session_id)) == 0
