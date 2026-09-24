"""Exposer les artefacts d'un projet, sans exposer le reste.

Un agent qui produit un livrable à montrer — un rapport, une page — n'avait
nulle part où le poser : sur ce pod, un port local n'est jamais public. Un
agent a passé cent soixante-quatorze tours à chercher une URL, en vain. Il
dépose désormais dans `artifacts/`, et l'Atelier sert ce dossier derrière sa
porte. Le contenu venant d'un agent, chaque réponse est rendue inerte — corpus
compris : un corpus servi hors bac à sable lisait la clé propriétaire que
l'interface gardait dans le navigateur.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.config import AtelierSettings


def _porteur(cle: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {cle}"}


def _csp_inerte(csp: str) -> bool:
    """Le seul critère qui compte : bac à sable, et jamais la même origine."""
    return "sandbox" in csp and "allow-scripts" in csp and "allow-same-origin" not in csp


# ── le module ──────────────────────────────────────────────────────────

def test_un_chemin_ne_remonte_pas_hors_du_dossier(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    base.mkdir()
    (tmp_path / "secret.txt").write_text("clé", encoding="utf-8")
    assert art._sous(base, "../secret.txt") is None
    assert art._sous(base, "sous/../../secret.txt") is None
    assert art._sous(base, "page.html") == (base / "page.html").resolve()


def test_l_index_cache_la_plomberie_et_les_fichiers_points(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    (base / "node_modules").mkdir(parents=True)
    base.joinpath("server.mjs").write_text("x", encoding="utf-8")
    base.joinpath(".secret").write_text("x", encoding="utf-8")
    base.joinpath(".corpus").write_text("", encoding="utf-8")
    # Un provisoire d'écriture resté orphelin, à l'ancienne ou à la nouvelle.
    base.joinpath("note.html.en-cours").write_text("x", encoding="utf-8")
    base.joinpath(".note.html.abc.en-cours").write_text("x", encoding="utf-8")
    base.joinpath("rapport.md").write_text("# Titre", encoding="utf-8")
    (base / "detail").mkdir()
    noms = [e.nom for e in art.lister(base) or []]
    assert noms == ["detail", "rapport.md"]  # dossiers d'abord, plomberie masquée


def test_un_dossier_absent_ne_se_liste_pas(tmp_path: Path) -> None:
    assert art.lister(tmp_path / "artifacts") is None


def test_le_markdown_se_rend_en_page_autonome(tmp_path: Path) -> None:
    page = art.rendre_markdown("# Bonjour\n\ntexte", "Rapport")
    assert "<!DOCTYPE html>" in page
    assert "Bonjour" in page
    # Autonome : le style est dedans (aucune feuille externe à charger depuis
    # une origine opaque, où « rien » ne se référencerait plus).
    assert "<style>" in page
    assert "<link" not in page


def test_les_deux_csp_sont_des_bacs_a_sable_sans_meme_origine() -> None:
    # `allow-same-origin` rendrait le bac à sable inutile : il ne doit y être
    # ni pour un artefact ordinaire, ni pour un corpus.
    assert _csp_inerte(art.CSP_SANDBOX)
    assert _csp_inerte(art.CSP_CORPUS)
    assert "form-action 'none'" in art.CSP_CORPUS


def test_un_worker_ne_vient_que_du_code_de_la_page() -> None:
    # Une carte MapLibre dessine dans un worker `blob:` ; rien d'autre n'est
    # admis, et le réseau reste fermé à l'artefact ordinaire.
    assert "worker-src blob:" in art.CSP_SANDBOX
    assert "worker-src 'self' blob:" in art.CSP_CORPUS
    assert "connect-src" not in art.CSP_SANDBOX
    assert "default-src 'none'" in art.CSP_SANDBOX


def test_les_liens_de_l_index_sont_encodes_pas_echappes() -> None:
    """`#` et `?` dans un nom coupaient le lien : `html.escape` n'y touche pas."""
    page = art.page_index("p", "", [art.Entree("a #b?.html", "a #b?.html", False, 3)])
    assert 'href="a%20%23b%3F.html"' in page


def test_un_texte_latin1_n_est_pas_reencode() -> None:
    texte, jeu = art.decoder("café".encode("latin-1"))
    assert jeu is None  # on ne devine pas : le navigateur lira <meta charset>
    assert texte == "café"
    assert art.decoder("café".encode("utf-8")) == ("café", "utf-8")


def test_un_slug_n_est_qu_un_nom() -> None:
    for bon in ("recherche", "wikichat-memory", "HexTokenizer", "a_b.c"):
        assert art.slug_valide(bon), bon
    for mauvais in ("", ".", "..", ".cache", "a/b", "a\\b", "a b", "é"):
        assert not art.slug_valide(mauvais), mauvais


# ── le jeton de lecture ────────────────────────────────────────────────

SECRET = art.secret_des_jetons("cle-de-test")


def test_un_jeton_se_relit_pour_son_slug_et_rien_d_autre() -> None:
    brut = art.signer_jeton(SECRET, "recherche", "cerveau")
    j = art.lire_jeton(SECRET, brut, "recherche")
    assert j is not None and j.racine == "cerveau" and not j.perime()
    assert art.lire_jeton(SECRET, brut, "autre") is None
    assert art.lire_jeton(art.secret_des_jetons("autre-cle"), brut, "recherche") is None
    # Une charge retouchée ne garde pas sa signature.
    charge, mac = brut.split(".")
    faux = art._b64(b"recherche\n\n9999999999") + "." + mac
    assert art.lire_jeton(SECRET, faux, "recherche") is None
    assert art.lire_jeton(SECRET, "n'importe quoi", "recherche") is None


def test_un_jeton_ne_couvre_que_son_corpus() -> None:
    j = art.Jeton("recherche", "cerveau", 0)
    assert j.couvre("cerveau") and j.couvre("cerveau/systeme/x.css")
    assert not j.couvre("cerveau2/x.html")
    assert not j.couvre("page.html")


def test_un_jeton_perime_se_sait_perime() -> None:
    brut = art.signer_jeton(SECRET, "recherche", "cerveau", duree=-1)
    j = art.lire_jeton(SECRET, brut, "recherche")
    assert j is not None and j.perime()


# ── l'écriture, dans la fonction ───────────────────────────────────────

def _corpus_nu(tmp_path: Path) -> Path:
    base = tmp_path / "projet" / "artifacts"
    (base / "cerveau").mkdir(parents=True)
    (base / "cerveau" / ".corpus").write_text("", encoding="utf-8")
    (base / "cerveau" / "note.html").write_text("v1", encoding="utf-8")
    return base


def test_le_mur_tient_dans_la_fonction_pas_seulement_dans_l_url(tmp_path: Path) -> None:
    """Un chemin qui remonte doit se heurter au mur, pas à un hasard.

    Passer par une URL ne prouve rien : le client et le routeur normalisent
    `../..` avant que le service le voie. Le mur doit tenir là où il est posé.
    """
    base = _corpus_nu(tmp_path)
    dehors = tmp_path / "projet" / "CLAUDE.md"
    dehors.write_text("intact", encoding="utf-8")

    for chemin in ("../CLAUDE.md", "cerveau/../../CLAUDE.md", "/etc/passwd", "", "."):
        with pytest.raises(art.Refus):
            art.ecrire(base, chemin, b"contenu")
    assert dehors.read_text(encoding="utf-8") == "intact"

    # Et ce qui reste dans le corpus passe, y compris dans un sous-dossier neuf.
    ecrit, etag = art.ecrire(base, "cerveau/neuf/page.html", b"<p>ok</p>")
    assert ecrit.read_bytes() == b"<p>ok</p>"
    assert etag == art.etag_des_octets(b"<p>ok</p>")


def test_on_n_ecrit_ni_point_fichier_ni_marqueur(tmp_path: Path) -> None:
    """Écrire `.corpus` ailleurs ferait passer un autre dossier en corpus."""
    base = _corpus_nu(tmp_path)
    (base / "autre").mkdir()
    for chemin in ("cerveau/.corpus", "autre/.corpus", "cerveau/.git/config", "cerveau/.cache"):
        with pytest.raises(art.Refus) as exc:
            art.ecrire(base, chemin, b"x")
        assert exc.value.statut == 403
    assert not (base / "autre" / ".corpus").exists()


def test_on_n_ecrit_que_dans_un_corpus(tmp_path: Path) -> None:
    base = _corpus_nu(tmp_path)
    (base / "rapport.html").write_text("intact", encoding="utf-8")
    with pytest.raises(art.Refus) as exc:
        art.ecrire(base, "rapport.html", b"x")
    assert exc.value.statut == 403
    assert (base / "rapport.html").read_text(encoding="utf-8") == "intact"
    # Le jeton borne encore : racine « cerveau », rien au-dessus.
    with pytest.raises(art.Refus):
        art.ecrire(base, "cerveau/x.html", b"x", racine="ailleurs")


def test_sans_dossier_artifacts_on_ne_cree_rien(tmp_path: Path) -> None:
    """On créait un *fichier* nommé artifacts à la racine du projet."""
    projet = tmp_path / "projet"
    projet.mkdir()
    base = projet / "artifacts"
    with pytest.raises(art.Refus) as exc:
        art.ecrire(base, "page.html", b"x")
    assert exc.value.statut == 404
    assert not base.exists()


def test_un_lien_symbolique_ne_mene_nulle_part(tmp_path: Path) -> None:
    base = _corpus_nu(tmp_path)
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    try:
        os.symlink(ailleurs, base / "cerveau" / "lien", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques indisponibles sur cette machine")
    with pytest.raises(art.Refus) as exc:
        art.ecrire(base, "cerveau/lien/x.html", b"x")
    assert exc.value.statut == 403
    assert not list(ailleurs.iterdir())


def test_if_match_refuse_une_version_qu_on_n_a_pas_lue(tmp_path: Path) -> None:
    base = _corpus_nu(tmp_path)
    lue = art.etag_du_fichier(base / "cerveau" / "note.html")
    _, neuve = art.ecrire(base, "cerveau/note.html", b"v2", si_correspond=lue)
    with pytest.raises(art.Conflit):
        art.ecrire(base, "cerveau/note.html", b"v3", si_correspond=lue)
    assert (base / "cerveau" / "note.html").read_bytes() == b"v2"
    art.ecrire(base, "cerveau/note.html", b"v3", si_correspond=neuve)
    with pytest.raises(art.Conflit):
        art.ecrire(base, "cerveau/note.html", b"v4", si_absent=True)


def test_des_ecritures_simultanees_ne_se_marchent_pas_dessus(tmp_path: Path) -> None:
    """Un même `.en-cours` pour tous : le second `replace` levait, soit un 500."""
    base = _corpus_nu(tmp_path)
    erreurs: list[BaseException] = []

    def ecrire(i: int) -> None:
        try:
            art.ecrire(base, "cerveau/note.html", f"version {i}".encode() * 2000)
        except BaseException as exc:  # noqa: BLE001
            erreurs.append(exc)

    fils = [threading.Thread(target=ecrire, args=(i,)) for i in range(16)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert not erreurs
    assert (base / "cerveau" / "note.html").read_bytes().startswith(b"version ")
    assert not [p for p in (base / "cerveau").iterdir() if p.name.endswith(".en-cours")]


# ── les routes ─────────────────────────────────────────────────────────

def _depose(reglages: AtelierSettings, slug: str) -> Path:
    base = reglages.projects_dir / slug / "artifacts"
    base.mkdir(parents=True, exist_ok=True)
    base.joinpath("rapport.md").write_text("# Résultat\n\nAlpha beta.", encoding="utf-8")
    base.joinpath("page.html").write_text(
        "<!doctype html><h1>Autonome</h1>", encoding="utf-8"
    )
    (base / "detail").mkdir(exist_ok=True)
    (reglages.projects_dir / slug / "secret.txt").write_text("clé", encoding="utf-8")
    return base


def _depose_corpus(reglages: AtelierSettings, slug: str) -> Path:
    base = reglages.projects_dir / slug / "artifacts" / "cerveau"
    (base / "systeme").mkdir(parents=True, exist_ok=True)
    base.joinpath(".corpus").write_text("", encoding="utf-8")
    base.joinpath("systeme", "cerveau.css").write_text("body{color:red}", encoding="utf-8")
    base.joinpath("index.html").write_text(
        '<!doctype html><link rel="stylesheet" href="systeme/cerveau.css"><h1>Corpus</h1>',
        encoding="utf-8",
    )
    base.joinpath("note.html").write_text(
        '<!doctype html><link rel="stylesheet" href="systeme/cerveau.css"><h1>Une note</h1>',
        encoding="utf-8",
    )
    return base


def _jeton_de(reponse) -> str:  # type: ignore[no-untyped-def]
    """Le segment `@…` de l'adresse où l'on a été renvoyé."""
    segment = next(s for s in reponse.url.path.split("/") if s.startswith("@"))
    return segment[1:]


def test_l_index_liste_les_artefacts(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche/", headers=_porteur(cle_du_proprietaire))
    assert r.status_code == 200
    assert "rapport.md" in r.text and "page.html" in r.text
    assert 'href="detail/"' in r.text  # relatif : le jeton suivrait
    assert _csp_inerte(r.headers["content-security-policy"])


def test_un_dossier_sans_barre_finale_est_redirige(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Sans la barre, `href="note.html"` se résolvait un cran trop haut."""
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche", headers=_porteur(cle_du_proprietaire), follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == "/v1/artifacts/recherche/"
    # Un sous-dossier est un artefact : lu sous son jeton, barre finale comprise.
    r = atelier.get(
        "/v1/artifacts/recherche/detail", headers=_porteur(cle_du_proprietaire), follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("/v1/artifacts/recherche/@")
    assert r.headers["location"].endswith("/detail/")


def test_un_markdown_arrive_rendu(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche/rapport.md", headers=_porteur(cle_du_proprietaire))
    assert r.status_code == 200
    assert "<h1>Résultat</h1>" in r.text
    assert _csp_inerte(r.headers["content-security-policy"])


def test_un_html_est_servi_en_bac_a_sable(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche/page.html", headers=_porteur(cle_du_proprietaire))
    assert r.status_code == 200
    assert "Autonome" in r.text
    assert _csp_inerte(r.headers["content-security-policy"])
    assert r.headers["referrer-policy"] == "no-referrer"


def test_un_texte_est_servi_octet_pour_octet(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    base = _depose(reglages, "recherche")
    base.joinpath("vieux.txt").write_bytes("café".encode("latin-1"))
    r = atelier.get("/v1/artifacts/recherche/vieux.txt", headers=_porteur(cle_du_proprietaire))
    assert r.content == "café".encode("latin-1")
    assert "utf-8" not in r.headers["content-type"]


def test_aucune_reponse_d_artefact_ne_sort_du_bac_a_sable(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Toutes les formes de réponse, corpus compris, et même les erreurs."""
    _depose(reglages, "recherche")
    _depose_corpus(reglages, "recherche")
    for adresse in (
        "/v1/artifacts/recherche/",
        "/v1/artifacts/recherche/rapport.md",
        "/v1/artifacts/recherche/page.html",
        "/v1/artifacts/recherche/absent.html",
        "/v1/artifacts/recherche/cerveau/",
        "/v1/artifacts/recherche/cerveau/note.html",
        "/v1/artifacts/recherche/cerveau/systeme/cerveau.css",
        "/v1/artifacts/recherche/cerveau/systeme/",
    ):
        r = atelier.get(adresse, headers=_porteur(cle_du_proprietaire))
        assert r.status_code in (200, 404), adresse
        assert _csp_inerte(r.headers.get("content-security-policy", "")), adresse


def test_on_ne_remonte_pas_hors_des_artefacts(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche/..%2Fsecret.txt", headers=_porteur(cle_du_proprietaire))
    assert "clé" not in r.text
    assert r.status_code in (404, 400)


def _asgi(atelier: TestClient, methode: str, chemin_brut: bytes, entetes: dict[str, str]) -> tuple[int, bytes]:
    """Appelle l'application sans client HTTP : l'adresse arrive telle quelle.

    httpx et le client de test normalisent `../` avant l'envoi ; un test de
    traversée qui passe par eux ne prouve rien. Ici `raw_path` est ce qu'un
    ingress laisserait passer, et `path` ce qu'uvicorn en décode.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "https",
        "path": unquote(chemin_brut.decode("latin-1")),
        "raw_path": chemin_brut,
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")]
        + [(k.lower().encode(), v.encode()) for k, v in entetes.items()],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 443),
    }
    recu: dict[str, object] = {"corps": b""}

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            recu["statut"] = message["status"]
        elif message["type"] == "http.response.body":
            recu["corps"] = recu["corps"] + message.get("body", b"")  # type: ignore[operator]

    asyncio.run(atelier.app(scope, receive, send))
    return int(recu["statut"]), recu["corps"]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "chemin",
    [
        b"/v1/artifacts/recherche/../secret.txt",
        b"/v1/artifacts/recherche/..%2Fsecret.txt",
        b"/v1/artifacts/recherche/%2E%2E/secret.txt",
        b"/v1/artifacts/recherche/detail/..%2F..%2Fsecret.txt",
        b"/v1/artifacts/%2E%2E/recherche/secret.txt",
        b"/v1/artifacts/%2E%2E/",
    ],
)
def test_la_traversee_brute_se_heurte_au_mur(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str, chemin: bytes
) -> None:
    _depose(reglages, "recherche")
    statut, corps = _asgi(atelier, "GET", chemin, _porteur(cle_du_proprietaire))
    assert "clé".encode() not in corps
    assert statut in (400, 403, 404), (chemin, statut)


def test_un_projet_sans_artefacts_le_dit_sans_casser(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    (reglages.projects_dir / "vide").mkdir(parents=True, exist_ok=True)
    r = atelier.get("/v1/artifacts/vide/", headers=_porteur(cle_du_proprietaire))
    assert r.status_code == 200
    assert "Rien à montrer" in r.text


def test_un_projet_inconnu_est_un_404(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    r = atelier.get("/v1/artifacts/fantome/", headers=_porteur(cle_du_proprietaire))
    assert r.status_code == 404


def test_sans_la_porte_rien_ne_sort(atelier: TestClient, reglages: AtelierSettings) -> None:
    _depose(reglages, "recherche")
    assert atelier.get("/v1/artifacts/recherche/").status_code == 401
    assert atelier.get("/v1/artifacts/recherche/page.html").status_code == 401


# ── le mode corpus ─────────────────────────────────────────────────────

def test_un_corpus_se_lit_sous_jeton_en_bac_a_sable(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Le corpus n'est plus servi dans l'origine de l'Atelier.

    Il était servi hors bac à sable pour que sa feuille de style se charge ;
    son script lisait alors la clé que l'interface gardait. Il est désormais
    en origine opaque comme le reste, et lu sous un jeton de chemin.
    """
    _depose_corpus(reglages, "recherche")
    r = atelier.get(
        "/v1/artifacts/recherche/cerveau/note.html",
        headers=_porteur(cle_du_proprietaire),
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("/v1/artifacts/recherche/@")
    assert r.headers["location"].endswith("/cerveau/note.html")

    suivie = atelier.get(r.headers["location"])  # sans clé ni cookie
    assert suivie.status_code == 200
    csp = suivie.headers["content-security-policy"]
    assert _csp_inerte(csp)
    assert "default-src 'self'" in csp  # 'self' = l'origine de l'adresse, mesuré
    assert "<h1>Une note</h1>" in suivie.text


def test_le_css_du_corpus_se_charge_sans_cookie(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Ce que fait le navigateur : sous-ressource relative, sans cookie."""
    _depose_corpus(reglages, "recherche")
    page = atelier.get("/v1/artifacts/recherche/cerveau/", headers=_porteur(cle_du_proprietaire))
    assert "<h1>Corpus</h1>" in page.text  # l'index du corpus, pas notre listing
    jeton = _jeton_de(page)
    atelier.cookies.clear()
    r = atelier.get(f"/v1/artifacts/recherche/@{jeton}/cerveau/systeme/cerveau.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "color:red" in r.text
    assert r.headers["access-control-allow-origin"] == "null"


def test_un_jeton_n_ouvre_que_son_corpus(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    _depose_corpus(reglages, "recherche")
    page = atelier.get("/v1/artifacts/recherche/cerveau/", headers=_porteur(cle_du_proprietaire))
    jeton = _jeton_de(page)
    atelier.cookies.clear()
    assert atelier.get(f"/v1/artifacts/recherche/@{jeton}/page.html").status_code == 403
    statut, corps = _asgi(
        atelier, "GET", f"/v1/artifacts/recherche/@{jeton}/cerveau/../../secret.txt".encode(), {}
    )
    assert statut in (403, 404) and "clé".encode() not in corps
    # Le même jeton, présenté pour un autre projet, ne vaut rien.
    (reglages.projects_dir / "voisin" / "artifacts").mkdir(parents=True)
    assert atelier.get(f"/v1/artifacts/voisin/@{jeton}/").status_code == 401
    assert atelier.get("/v1/artifacts/recherche/@faux.jeton/cerveau/").status_code == 401


def test_un_jeton_perime_se_renouvelle_avec_le_cookie_seulement(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    perime = art.signer_jeton(
        art.secret_des_jetons(cle_du_proprietaire), "recherche", "cerveau", duree=-5
    )
    adresse = f"/v1/artifacts/recherche/@{perime}/cerveau/note.html"
    assert atelier.get(adresse).status_code == 401

    atelier.post("/v1/auth/cookie", headers=_porteur(cle_du_proprietaire))
    r = atelier.get(adresse, follow_redirects=False)
    assert r.status_code == 302
    r = atelier.get(adresse)  # la navigation va au bout, jeton neuf
    assert r.status_code == 200 and "Une note" in r.text
    assert _jeton_de(r) != perime


def test_un_jeton_tombe_avec_la_cle(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    jeton = _jeton_de(
        atelier.get("/v1/artifacts/recherche/cerveau/", headers=_porteur(cle_du_proprietaire))
    )
    atelier.post("/v1/auth/rotate", headers=_porteur(cle_du_proprietaire))
    atelier.cookies.clear()
    assert atelier.get(f"/v1/artifacts/recherche/@{jeton}/cerveau/").status_code == 401


# ── Écrire dans un corpus ───────────────────────────────────────────────
#
# Un artefact n'était que servi. Une page d'édition déposée là ne pouvait rien
# enregistrer : elle appelait un serveur que l'agent s'était bricolé sur un
# port du pod — mesuré, il écoutait bien sur 127.0.0.1:8082 — que le navigateur
# de son propriétaire ne joint pas. Elle écrit désormais à l'adresse même où
# elle est lue, par le jeton de son chemin, et nulle part ailleurs.


def _adresse_a_jeton(atelier: TestClient, cle: str) -> str:
    page = atelier.get("/v1/artifacts/recherche/cerveau/", headers=_porteur(cle))
    atelier.cookies.clear()
    return f"/v1/artifacts/recherche/@{_jeton_de(page)}/cerveau"


def test_ce_que_la_page_ecrit_se_relit_a_la_meme_adresse(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Lire et écrire à la même adresse : c'est tout le contrat."""
    _depose_corpus(reglages, "recherche")
    racine = _adresse_a_jeton(atelier, cle_du_proprietaire)
    url = f"{racine}/permanentes/neuve.html"

    r = atelier.put(url, content="<h1>écrite par la page</h1>".encode(), headers={"Origin": "null"})
    assert r.status_code == 200, r.text
    assert r.json()["octets"] > 0
    assert r.headers["access-control-allow-origin"] == "null"

    relu = atelier.get(url)
    assert relu.status_code == 200
    assert "écrite par la page" in relu.text
    assert relu.headers["etag"] == r.headers["etag"]


def test_la_requete_prealable_d_une_page_opaque_est_acceptee(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    racine = _adresse_a_jeton(atelier, cle_du_proprietaire)
    r = atelier.options(
        f"{racine}/note.html",
        headers={"Origin": "null", "Access-Control-Request-Method": "PUT"},
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "null"
    assert "PUT" in r.headers["access-control-allow-methods"]
    # Sans jeton, rien n'est ouvert à une autre origine.
    r = atelier.options("/v1/artifacts/recherche/cerveau/note.html", headers={"Origin": "null"})
    assert "access-control-allow-origin" not in r.headers


def test_if_match_perime_donne_412(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    racine = _adresse_a_jeton(atelier, cle_du_proprietaire)
    url = f"{racine}/note.html"
    lue = atelier.get(url).headers["etag"]
    assert atelier.put(url, content=b"<p>deux</p>", headers={"If-Match": lue}).status_code == 200
    r = atelier.put(url, content=b"<p>trois</p>", headers={"If-Match": lue})
    assert r.status_code == 412
    assert atelier.get(url).text == "<p>deux</p>"
    dossier = reglages.projects_dir / "recherche" / "artifacts" / "cerveau"
    assert not [p for p in dossier.iterdir() if p.name.endswith(".en-cours")]


def test_la_page_n_ecrit_ni_marqueur_ni_point_fichier_ni_hors_corpus(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    _depose_corpus(reglages, "recherche")
    racine = _adresse_a_jeton(atelier, cle_du_proprietaire)
    jeton_seg = racine.split("/")[4]
    for url, attendus in (
        (f"{racine}/.corpus", (403, 404)),
        (f"{racine}/systeme/.cache", (403, 404)),
        (f"/v1/artifacts/recherche/{jeton_seg}/page.html", (403,)),
        (f"/v1/artifacts/recherche/{jeton_seg}/detail/.corpus", (403, 404)),
    ):
        r = atelier.put(url, content=b"x")
        assert r.status_code in attendus, (url, r.status_code)
    base = reglages.projects_dir / "recherche" / "artifacts"
    assert (base / "page.html").read_text(encoding="utf-8") == "<!doctype html><h1>Autonome</h1>"
    assert not (base / "detail" / ".corpus").exists()
    assert (base / "cerveau" / ".corpus").read_text(encoding="utf-8") == ""


def test_la_cle_n_ecrit_pas_hors_d_un_corpus(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.put(
        "/v1/artifacts/recherche/page.html", content=b"x", headers=_porteur(cle_du_proprietaire)
    )
    assert r.status_code == 403


def test_on_n_ecrit_pas_hors_de_l_artefact(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    """Le mur de la lecture vaut pour l'écriture — avec une adresse brute."""
    _depose_corpus(reglages, "recherche")
    temoin = reglages.projects_dir / "recherche" / "CLAUDE.md"
    temoin.write_text("intact", encoding="utf-8")
    for chemin in (
        b"/v1/artifacts/recherche/cerveau/../../CLAUDE.md",
        b"/v1/artifacts/recherche/cerveau/..%2F..%2FCLAUDE.md",
    ):
        statut, _ = _asgi(atelier, "PUT", chemin, _porteur(cle_du_proprietaire))
        assert statut in (400, 403, 404), chemin
    assert temoin.read_text(encoding="utf-8") == "intact"


def test_un_slug_inconnu_ne_cree_rien(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    r = atelier.put(
        "/v1/artifacts/fantome/cerveau/x.html", content=b"x", headers=_porteur(cle_du_proprietaire)
    )
    assert r.status_code == 404
    assert not (reglages.projects_dir / "fantome").exists()


def test_un_contenu_trop_gros_est_refuse_avec_sa_raison(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    r = atelier.put(
        "/v1/artifacts/recherche/cerveau/enorme.html",
        content=b"x" * (art.POIDS_MAX_ECRITURE + 1),
        headers=_porteur(cle_du_proprietaire),
    )
    assert r.status_code == 413
    # Un refus se lit : la page doit pouvoir le montrer à qui a cliqué.
    assert "trop gros" in r.json()["detail"]


def test_l_ecriture_est_gardee(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose_corpus(reglages, "recherche")
    url = "/v1/artifacts/recherche/cerveau/x.html"
    assert atelier.put(url, content=b"a").status_code == 401
    # Le cookie seul n'écrit pas : ni formulaire, ni fetch d'une autre page.
    atelier.post("/v1/auth/cookie", headers=_porteur(cle_du_proprietaire))
    assert atelier.put(url, content=b"a", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 401
    assert atelier.put(url, content=b"a", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
