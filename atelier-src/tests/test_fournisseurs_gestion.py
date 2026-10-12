"""Les fournisseurs de modèles vus et réglés depuis l'interface : découverte, ajout, retrait, garde-fous."""

from __future__ import annotations

import ipaddress
import json
import stat
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.atelier import fournisseurs_gestion as g
from mcp_gateway.atelier import models_catalog
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.fournisseurs import charger_fournisseurs

CLE = "sk-test-0123456789abcdef"
BASE = "https://llm.exemple.fr/v1"
PUBLIC = ipaddress.ip_address("93.184.216.34")


@pytest.fixture()
def reglages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AtelierSettings:
    s = AtelierSettings(work_dir=tmp_path / "work")
    s.ensure_dirs()
    s.secrets_dir.mkdir(parents=True, exist_ok=True)
    models_catalog._cache.clear()
    monkeypatch.setattr(g, "_adresses_de", lambda hote: [PUBLIC])
    return s


class _Reseau:
    """Un fournisseur imaginaire : ce que répond `GET <base>/models`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.reponses: dict[str, Any] = {}
        self.appels: list[tuple[str, str]] = []
        monkeypatch.setattr(g, "_lire_json", self._lire)

    def _lire(self, adresse: str, cle: str) -> Any:
        self.appels.append((adresse, cle))
        r = self.reponses.get(adresse)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise urllib.error.HTTPError(adresse, 404, "nf", {}, None)  # type: ignore[arg-type]
        return r


@pytest.fixture()
def reseau(monkeypatch: pytest.MonkeyPatch) -> _Reseau:
    return _Reseau(monkeypatch)


MODELES = {
    "data": [
        {"id": "mistral-small", "type": "text-generation"},
        {"id": "qwen3-coder"},
        {"id": "bge-embed-large", "type": "text-embeddings-inference"},
        {"id": "whisper-large"},
    ]
}


# ── la découverte ────────────────────────────────────────────────────────────


def test_la_decouverte_garde_les_modeles_de_conversation(reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    d = g.decouvrir(BASE, CLE)
    assert d.ok and d.modeles == ["mistral-small", "qwen3-coder"] and d.ecartes == 2
    assert reseau.appels == [(f"{BASE}/models", CLE)]


@pytest.mark.parametrize(
    "reponse, attendu",
    [
        (urllib.error.HTTPError("u", 401, "x", {}, None), "clé est refusée"),
        (urllib.error.HTTPError("u", 403, "x", {}, None), "clé est refusée"),
        (urllib.error.HTTPError("u", 404, "x", {}, None), "finit-elle par /v1"),
        (urllib.error.HTTPError("u", 302, "x", {}, None), "redirige"),
        (urllib.error.HTTPError("u", 500, "x", {}, None), "HTTP 500"),
        (urllib.error.URLError("Connection refused"), "injoignable"),
        (TimeoutError("lent"), "injoignable"),
        (ValueError("pas du json"), "pas du JSON"),
        ({"error": "x"}, "champ « data »"),
        ({"data": [{"id": "bge-embed"}]}, "aucun modèle de conversation"),
    ],
)
def test_une_panne_est_dite_au_lieu_de_rendre_une_liste_vide(reseau: _Reseau, reponse: Any, attendu: str) -> None:
    reseau.reponses[f"{BASE}/models"] = reponse
    d = g.decouvrir(BASE, CLE)
    assert not d.ok and attendu in d.erreur


def test_une_liste_nue_est_acceptee(reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = [{"id": "m1"}, {"id": "m2"}]
    assert g.decouvrir(BASE, CLE).modeles == ["m1", "m2"]


# ── l'adresse : le garde contre le réseau interne ───────────────────────────


@pytest.mark.parametrize(
    "adresse",
    [
        "http://llm.exemple.fr/v1",
        "ftp://llm.exemple.fr/v1",
        "https://user:mdp@llm.exemple.fr/v1",
        "https://llm.exemple.fr/v1?cle=1",
        "https://127.0.0.1:8000/v1",
        "https://localhost/v1",
        "https://10.233.1.5/v1",
        "https://169.254.169.254/latest",
        "https://wikichat:3777/v1",
        "https://2130706433/v1",
        "https://kubernetes.default.svc/v1",
        "",
        "pas une adresse",
    ],
)
def test_une_adresse_interne_ou_non_https_est_refusee(reglages: AtelierSettings, adresse: str) -> None:
    with pytest.raises(g.ErreurFournisseur):
        g.valider_adresse(adresse)


def test_un_nom_public_qui_mene_au_reseau_interne_est_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g, "_adresses_de", lambda hote: [ipaddress.ip_address("10.0.0.7")])
    with pytest.raises(g.ErreurFournisseur, match="réseau interne"):
        g.valider_adresse("https://piege.exemple.fr/v1")


def test_une_adresse_publique_est_acceptee_et_nettoyee(reglages: AtelierSettings) -> None:
    assert g.valider_adresse(" https://llm.exemple.fr/v1/ ") == BASE


# ── l'écriture ───────────────────────────────────────────────────────────────


def test_ajouter_un_fournisseur_ecrit_la_cle_a_part_en_0600(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    ligne = g.enregistrer(reglages, "mon-vllm", nom="Mon vLLM", base_url=BASE, cle=CLE, outils_natifs=["qwen3-coder"])
    assert ligne["etat"] == "ok" and [m["id"] for m in ligne["modeles"]] == ["mistral-small", "qwen3-coder"]
    assert ligne["modeles"][1] == {"id": "qwen3-coder", "public": "claude-mon-vllm-qwen3-coder", "outils_natifs": True}
    declaration = json.loads((reglages.secrets_dir / "fournisseurs.json").read_text(encoding="utf-8"))
    assert declaration == {"mon-vllm": {"nom": "Mon vLLM", "base_url": BASE, "outils_natifs": ["qwen3-coder"]}}
    assert CLE not in json.dumps(declaration), "aucune clé dans fournisseurs.json"
    fichier_cle = reglages.secrets_dir / "mon-vllm_api_key"
    assert fichier_cle.read_text(encoding="utf-8").strip() == CLE
    assert stat.S_IMODE(fichier_cle.stat().st_mode) == 0o600
    assert stat.S_IMODE((reglages.secrets_dir / "fournisseurs.json").stat().st_mode) == 0o600
    # Le relais, lui, voit le fournisseur sans redémarrer.
    assert [f.id for f in charger_fournisseurs(reglages)] == ["mon-vllm"]


def test_la_configuration_ne_rend_jamais_une_cle(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon-vllm", nom="Mon vLLM", base_url=BASE, cle=CLE)
    config = g.configuration(reglages, en_direct=True)
    assert CLE not in json.dumps(config)
    ids = [f["id"] for f in config["fournisseurs"]]
    assert ids[0] == "ssp" and "albert" in ids and "mon-vllm" in ids
    ligne = next(f for f in config["fournisseurs"] if f["id"] == "mon-vllm")
    assert ligne["cle_presente"] is True and ligne["fichier_de_la_cle"] == "~/work/.secrets/mon-vllm_api_key"


def test_albert_est_visible_sans_cle_et_ne_change_que_de_cle(reglages: AtelierSettings, reseau: _Reseau) -> None:
    albert = next(f for f in g.configuration(reglages)["fournisseurs"] if f["id"] == "albert")
    assert albert["etat"] == "sans_cle" and albert["cle_presente"] is False and albert["modifiable"] is False
    assert albert["base_url"] == "https://albert.api.etalab.gouv.fr/v1" and "gpt-oss-120b" in albert["outils_natifs"]
    with pytest.raises(g.ErreurFournisseur, match="que sa clé"):
        g.enregistrer(reglages, "albert", nom="X", base_url=BASE)
    reseau.reponses["https://albert.api.etalab.gouv.fr/v1/models"] = {"data": [{"id": "gpt-oss-120b"}]}
    ligne = g.enregistrer(reglages, "albert", cle=CLE)
    assert ligne["etat"] == "ok" and ligne["modeles"][0]["outils_natifs"] is True
    assert not (reglages.secrets_dir / "fournisseurs.json").exists(), "Albert ne s'écrit pas dans fournisseurs.json"


def test_retirer_un_fournisseur_declare_retire_declaration_et_cle(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon-vllm", nom="Mon vLLM", base_url=BASE, cle=CLE)
    g.enregistrer(reglages, "autre", nom="Autre", base_url="https://autre.exemple.fr/v1", cle=CLE)
    assert g.retirer(reglages, "mon-vllm") == {"retire": "mon-vllm", "reste_propose": False}
    assert not (reglages.secrets_dir / "mon-vllm_api_key").exists()
    assert list(json.loads((reglages.secrets_dir / "fournisseurs.json").read_text())) == ["autre"]


def test_retirer_albert_retire_sa_cle_et_il_reste_propose(reglages: AtelierSettings, reseau: _Reseau) -> None:
    (reglages.secrets_dir / "albert_api_key").write_text(CLE)
    assert g.retirer(reglages, "albert")["reste_propose"] is True
    assert not (reglages.secrets_dir / "albert_api_key").exists()
    assert any(f["id"] == "albert" for f in g.configuration(reglages)["fournisseurs"])


def test_modifier_sans_redonner_la_cle_garde_celle_qui_existe(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon-vllm", nom="Mon vLLM", base_url=BASE, cle=CLE)
    ligne = g.enregistrer(reglages, "mon-vllm", nom="Renommé", base_url=BASE, outils_natifs=[])
    assert ligne["nom"] == "Renommé" and ligne["cle_presente"] is True
    assert (reglages.secrets_dir / "mon-vllm_api_key").read_text().strip() == CLE


@pytest.mark.parametrize(
    "identifiant, motif",
    [("ssp", "réservé"), ("Mon Vllm", "minuscules"), ("1abc", "minuscules"), ("", "minuscules"), ("a" * 40, "minuscules")],
)
def test_un_identifiant_invalide_est_refuse(reglages: AtelierSettings, identifiant: str, motif: str) -> None:
    with pytest.raises(g.ErreurFournisseur, match=motif):
        g.enregistrer(reglages, identifiant, nom="x", base_url=BASE, cle=CLE)


def test_deux_identifiants_dont_l_un_commence_par_l_autre_sont_refuses(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon", nom="A", base_url=BASE, cle=CLE)
    with pytest.raises(g.ErreurFournisseur, match="prête à confusion"):
        g.enregistrer(reglages, "mon-vllm", nom="B", base_url=BASE, cle=CLE)
    with pytest.raises(g.ErreurFournisseur, match="prête à confusion"):
        g.enregistrer(reglages, "albert-bis", nom="C", base_url=BASE, cle=CLE)


@pytest.mark.parametrize("cle", ["court", "avec espace dans la cle", "retour\nligne-0123456789", "é" * 20])
def test_une_cle_invalide_est_refusee(reglages: AtelierSettings, cle: str) -> None:
    with pytest.raises(g.ErreurFournisseur, match="clé"):
        g.enregistrer(reglages, "mon-vllm", nom="x", base_url=BASE, cle=cle)


def test_un_fournisseur_sans_cle_n_est_pas_ajoute(reglages: AtelierSettings) -> None:
    with pytest.raises(g.ErreurFournisseur, match="Il faut une clé"):
        g.enregistrer(reglages, "mon-vllm", nom="x", base_url=BASE)
    assert not (reglages.secrets_dir / "fournisseurs.json").exists()


def test_un_fichier_de_declaration_illisible_n_est_jamais_ecrase(reglages: AtelierSettings) -> None:
    chemin = reglages.secrets_dir / "fournisseurs.json"
    chemin.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(g.ErreurFournisseur, match="pas lisible"):
        g.enregistrer(reglages, "mon-vllm", nom="x", base_url=BASE, cle=CLE)
    assert chemin.read_text(encoding="utf-8") == "{pas du json"
    assert not (reglages.secrets_dir / "mon-vllm_api_key").exists(), "la clé n'est pas écrite si la déclaration ne peut pas l'être"


def test_les_autres_declarations_et_leurs_champs_sont_conserves(reglages: AtelierSettings, reseau: _Reseau) -> None:
    (reglages.secrets_dir / "fournisseurs.json").write_text(
        json.dumps({"ancien": {"nom": "Ancien", "base_url": "https://ancien.exemple.fr/v1", "note": "à garder"}}), encoding="utf-8"
    )
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon-vllm", nom="Mon vLLM", base_url=BASE, cle=CLE)
    lu = json.loads((reglages.secrets_dir / "fournisseurs.json").read_text(encoding="utf-8"))
    assert lu["ancien"]["note"] == "à garder" and "mon-vllm" in lu


# ── tester sans enregistrer ──────────────────────────────────────────────────


def test_tester_ne_garde_rien(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    r = g.tester(reglages, base_url=BASE, cle=CLE)
    assert r["ok"] and r["modeles"] == ["mistral-small", "qwen3-coder"] and "2 modèles" in r["detail"]
    assert list(reglages.secrets_dir.iterdir()) == []


def test_tester_un_fournisseur_existant_reprend_sa_cle_sans_la_rendre(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    g.enregistrer(reglages, "mon-vllm", nom="x", base_url=BASE, cle=CLE)
    reseau.appels.clear()
    r = g.tester(reglages, base_url=BASE, identifiant="mon-vllm")
    assert r["ok"] and CLE not in json.dumps(r)
    assert reseau.appels == [(f"{BASE}/models", CLE)]


def test_tester_dit_pourquoi_ca_ne_marche_pas(reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = urllib.error.HTTPError("u", 401, "x", {}, None)
    r = g.tester(reglages, base_url=BASE, cle=CLE)
    assert r["ok"] is False and "clé est refusée" in r["detail"]
    with pytest.raises(g.ErreurFournisseur, match="Il faut une clé"):
        g.tester(reglages, base_url=BASE)


# ── l'API : la personne règle, la clé lit ────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from mcp_gateway.atelier.api import build_app  # noqa: E402
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME  # noqa: E402

ORIGINE = "http://testserver"


@pytest.fixture()
def client(reglages: AtelierSettings, reseau: _Reseau) -> TestClient:
    return TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE)


def _cle(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.app.state.auth.owner_key}"}


def _personne(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


def test_la_cle_lit_la_configuration_sans_secret(client: TestClient, reglages: AtelierSettings) -> None:
    (reglages.secrets_dir / "albert_api_key").write_text(CLE)
    r = client.get("/v1/fournisseurs", headers=_cle(client))
    assert r.status_code == 200 and CLE not in r.text
    assert [f["id"] for f in r.json()["fournisseurs"]][:2] == ["ssp", "albert"]
    assert next(f for f in r.json()["fournisseurs"] if f["id"] == "albert")["cle_presente"] is True


def test_la_cle_du_proprietaire_ne_regle_rien(client: TestClient, reglages: AtelierSettings) -> None:
    corps = {"nom": "Piège", "base_url": BASE, "cle": CLE}
    for r in (
        client.put("/v1/fournisseurs/piege", json=corps, headers=_cle(client)),
        client.post("/v1/fournisseurs/tester", json={"base_url": BASE, "cle": CLE}, headers=_cle(client)),
        client.delete("/v1/fournisseurs/albert", headers=_cle(client)),
    ):
        assert r.status_code == 403 and "Réservé à la personne" in r.json()["detail"]
    noms = {f.name for f in reglages.secrets_dir.iterdir()}
    assert "fournisseurs.json" not in noms and "piege_api_key" not in noms, "rien n'a été écrit"


def test_la_personne_ajoute_teste_puis_retire(client: TestClient, reglages: AtelierSettings, reseau: _Reseau) -> None:
    reseau.reponses[f"{BASE}/models"] = MODELES
    h = _personne(client)
    t = client.post("/v1/fournisseurs/tester", json={"base_url": BASE, "cle": CLE}, headers=h)
    assert t.status_code == 200 and t.json()["ok"] and t.json()["modeles"] == ["mistral-small", "qwen3-coder"]
    assert not (reglages.secrets_dir / "fournisseurs.json").exists(), "tester n'enregistre rien"

    p = client.put("/v1/fournisseurs/mon-vllm", json={"nom": "Mon vLLM", "base_url": BASE, "cle": CLE}, headers=h)
    assert p.status_code == 200 and p.json()["etat"] == "ok" and CLE not in p.text
    liste = client.get("/v1/fournisseurs", headers=_cle(client)).json()["fournisseurs"]
    assert "mon-vllm" in [f["id"] for f in liste]
    # Le catalogue de modèles de l'interface les voit aussi (préfixe claude-<id>-).
    modeles = [m["id"] for m in client.get("/v1/models", headers=_cle(client)).json()["models"]]
    assert "claude-mon-vllm-qwen3-coder" in modeles

    d = client.delete("/v1/fournisseurs/mon-vllm", headers=h)
    assert d.status_code == 200 and d.json()["retire"] == "mon-vllm"
    assert "mon-vllm" not in [f["id"] for f in client.get("/v1/fournisseurs", headers=_cle(client)).json()["fournisseurs"]]


def test_une_erreur_se_lit_et_les_gestes_sont_au_journal_sans_la_cle(client: TestClient, reglages: AtelierSettings) -> None:
    h = _personne(client)
    r = client.put("/v1/fournisseurs/interne", json={"nom": "x", "base_url": "https://127.0.0.1:8000/v1", "cle": CLE}, headers=h)
    assert r.status_code == 400 and "réseau interne" in r.json()["detail"]
    lignes = client.app.state.journal_unique.lire(commande="fournisseur_enregistrer")
    assert lignes and lignes[0]["resultat"] == "refus" and lignes[0]["acteur"] == "personne"
    assert CLE not in json.dumps(lignes)
    assert lignes[0]["action"]["arguments"]["authentifie"] is True
