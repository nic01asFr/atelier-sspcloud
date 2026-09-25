"""La politique de cadrage de l'hôte des applications, prise seule."""

from __future__ import annotations

from mcp_gateway.atelier.apps import cadrage


def test_seule_l_origine_de_l_atelier_encadre() -> None:
    assert cadrage.politique("https://atelier.test/chemin/") == "frame-ancestors https://atelier.test"
    assert cadrage.politique("http://atelier.app.localhost:8787") == "frame-ancestors http://atelier.app.localhost:8787"


def test_sans_atelier_connu_rien_n_encadre() -> None:
    assert cadrage.politique("") == "frame-ancestors 'none'"
    # Une adresse qui glisserait une directive n'est pas une origine.
    assert cadrage.politique("https://a.test; script-src *") == "frame-ancestors 'none'"
    assert cadrage.politique("javascript:alert(1)") == "frame-ancestors 'none'"


def test_imposer_retire_x_frame_options_et_tout_autre_frame_ancestors() -> None:
    sortie = cadrage.imposer(
        [
            ("X-Frame-Options", "SAMEORIGIN"),
            ("Content-Security-Policy", "default-src 'self'; FRAME-ANCESTORS *"),
            ("Content-Security-Policy", "frame-ancestors 'self'"),
            ("Content-Type", "text/html"),
        ],
        "https://atelier.test",
    )
    noms = [k.lower() for k, _ in sortie]
    assert "x-frame-options" not in noms
    csp = [v for k, v in sortie if k.lower() == "content-security-policy"]
    assert csp == ["default-src 'self'", "frame-ancestors https://atelier.test"]


def test_une_reponse_sans_entete_recoit_la_restriction() -> None:
    from mcp_gateway.atelier.apps import proxy as px

    sortie = px.entetes_vers_client(
        [], prefixe="/demo/n8n", chemin_retire=True, amont="http://n8n:5678",
        origine_apps="https://apps.test", origine_atelier="https://atelier.test",
    )
    csp = [v.decode() for k, v in sortie if k == b"content-security-policy"]
    assert csp == ["frame-ancestors https://atelier.test"]
