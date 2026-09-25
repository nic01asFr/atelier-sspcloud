"""Un envoi ne se rejoue pas quand EventSource se reconnecte avec la même adresse."""

from mcp_gateway.atelier.api import _EnvoisRecus


def test_un_meme_envoi_n_est_accepte_qu_une_fois() -> None:
    reg = _EnvoisRecus()
    assert reg.premier("s1", "e1") is True
    assert reg.premier("s1", "e1") is False
    # Un autre envoi, ou le même identifiant dans une autre conversation, passe.
    assert reg.premier("s1", "e2") is True
    assert reg.premier("s2", "e1") is True


def test_un_envoi_redevient_possible_apres_la_duree(monkeypatch) -> None:
    import mcp_gateway.atelier.api as api

    t = {"v": 1000.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: t["v"])
    reg = _EnvoisRecus(duree_s=10)
    assert reg.premier("s", "e")
    t["v"] += 11
    assert reg.premier("s", "e")


def test_le_registre_reste_borne() -> None:
    reg = _EnvoisRecus(duree_s=0.0, maximum=10)
    for i in range(50):
        reg.premier("s", f"e{i}")
    assert len(reg._vus) <= 11


def test_un_substitut_isole_du_transcrit_ne_casse_pas_la_lecture(tmp_path) -> None:
    import json

    from mcp_gateway.atelier.journal import fondre

    chemin = tmp_path / "t.jsonl"
    # Chaîne brute : le fichier porte l'échappement JSON, comme le transcrit du CLI.
    ligne = r'{"type":"assistant","uuid":"u1","timestamp":"2026-09-25T10:00:00Z","message":{"role":"assistant","content":[{"type":"text","text":"coupé \ud83d ici"}]}}'
    chemin.write_text(ligne + "\n", encoding="utf-8")
    entrees = fondre([chemin])
    assert entrees
    json.dumps(entrees, ensure_ascii=False).encode("utf-8")  # ne lève plus
