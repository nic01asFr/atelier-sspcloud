"""Le choix des modèles ajoute ceux que l'API du modèle annonce."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from mcp_gateway.atelier import models_catalog as mc


@pytest.fixture(autouse=True)
def _cache_vide(monkeypatch, tmp_path, reglages):
    mc._cache.clear()
    monkeypatch.setenv("HOME", str(tmp_path / "maison"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")
    yield
    mc._cache.clear()


def _api(monkeypatch, data=None, erreur=None):
    appels = []

    def faux(requete, timeout):
        appels.append(requete.full_url)
        if erreur:
            raise erreur
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(mc.urllib.request, "urlopen", faux)
    return appels


ANNONCE = {
    "data": [
        {"id": "qwen3-6-35b-moe"},
        {"id": "albert-large"},
        {"id": "gemma4-26b-moe"},
        {"id": "bge-embedding"},
        {"id": "un-prereglage", "preset": True},
    ]
}


def _ids(reglages, **kw):
    return [m["id"] for m in mc.list_available_models(reglages, **kw)["models"]]


def test_les_modeles_de_l_api_s_ajoutent_sans_les_ecartes(reglages, monkeypatch) -> None:
    _api(monkeypatch, ANNONCE)
    assert _ids(reglages, en_direct=True) == ["qwen3-6-35b-moe", "albert-large"]


def test_sans_en_direct_le_reseau_n_est_pas_touche(reglages, monkeypatch) -> None:
    appels = _api(monkeypatch, ANNONCE)
    assert _ids(reglages) == []
    assert appels == []


def test_le_cache_sert_de_nouveau_sans_appel(reglages, monkeypatch) -> None:
    appels = _api(monkeypatch, ANNONCE)
    _ids(reglages, en_direct=True)
    _ids(reglages, en_direct=True)
    assert len(appels) == 1
    assert "albert-large" in _ids(reglages)  # sans en_direct : le cache seul


def test_une_panne_garde_la_derniere_liste(reglages, monkeypatch) -> None:
    _api(monkeypatch, ANNONCE)
    _ids(reglages, en_direct=True)
    for base in mc._cache:
        mc._cache[base] = (0.0, mc._cache[base][1])  # périmé
    _api(monkeypatch, erreur=urllib.error.URLError("coupé"))
    assert "albert-large" in _ids(reglages, en_direct=True)


def test_une_panne_sans_cache_ne_casse_rien(reglages, monkeypatch) -> None:
    _api(monkeypatch, erreur=urllib.error.URLError("coupé"))
    assert mc.list_available_models(reglages, en_direct=True)["models"] == []


def test_une_reponse_illisible_ne_casse_rien(reglages, monkeypatch) -> None:
    _api(monkeypatch, data=["pas", "un", "objet"])
    assert _ids(reglages, en_direct=True) == []


def test_albert_s_ajoute_prefixe_et_sans_ses_modeles_non_conversationnels(reglages, monkeypatch) -> None:
    (reglages.secrets_dir / "albert_api_key").write_text("k", encoding="utf-8")
    albert = {
        "data": [
            {"id": "deepseek-flash", "type": "text-generation"},
            {"id": "vision", "type": "image-text-to-text"},
            {"id": "embeddings-large", "type": "text-embeddings-inference"},
            {"id": "voix", "type": "automatic-speech-recognition"},
        ]
    }

    def faux(requete, timeout):
        return io.BytesIO(json.dumps(albert if "albert" in requete.full_url else {"data": [{"id": "qwen3-6-35b-moe"}]}).encode())

    monkeypatch.setattr(mc.urllib.request, "urlopen", faux)
    modeles = mc.list_available_models(reglages, en_direct=True)["models"]
    ids = [m["id"] for m in modeles]
    assert ids == ["qwen3-6-35b-moe", "claude-albert-deepseek-flash", "claude-albert-vision"]
    assert modeles[1]["label"] == "Albert API · deepseek-flash"
