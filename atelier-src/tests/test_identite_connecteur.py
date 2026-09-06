"""Un connecteur peut demander à savoir à quelle conversation il parle.

Le service du navigateur en a besoin : c'est par cet identifiant qu'il saura
quel contexte Chrome rendre à quel fil, et donc quelles pages et quels cookies.
Sans lui, il ne peut ni retrouver une conversation d'un tour à l'autre — le CLI
repart d'un processus neuf à chaque fois — ni cloisonner deux conversations.

L'Atelier est le seul à pouvoir le renseigner : le fichier de configuration est
reconstruit à chaque tour, et il connaît alors la conversation. Mais il ne le
donne qu'à qui le demande dans son adresse : l'ajouter partout enverrait
l'identité de vos conversations à des services tiers qui n'en ont que faire.
"""

from __future__ import annotations

from mcp_gateway.atelier.mcp_sync import resoudre_les_variables


def _url(brute: str, **kw: str) -> str:
    return resoudre_les_variables({"url": brute}, **kw)["url"]  # type: ignore[arg-type]


def test_la_conversation_se_nomme_dans_l_adresse() -> None:
    rendu = _url(
        "http://navigateur:3000/mcp?atelier=${ATELIER_SESSION}",
        session="s-123",
        agent="essai",
    )
    assert rendu == "http://navigateur:3000/mcp?atelier=s-123"


def test_le_nom_de_l_agent_aussi() -> None:
    rendu = _url("http://x/sse?agent=${ATELIER_AGENT}", session="s", agent="projet-42")
    assert rendu == "http://x/sse?agent=projet-42"


def test_un_connecteur_qui_ne_demande_rien_ne_recoit_rien() -> None:
    """Sinon l'identité de vos conversations partirait chez des tiers."""
    brute = "https://mcp.data.gouv.fr/mcp"
    assert _url(brute, session="s-123", agent="essai") == brute


def test_l_identifiant_est_echappe() -> None:
    """Il finit dans une adresse : ce qui s'y glisse doit y rester inoffensif."""
    rendu = _url("http://x/mcp?a=${ATELIER_SESSION}", session="a b&c=d", agent="")
    assert rendu == "http://x/mcp?a=a%20b%26c%3Dd"


def test_une_valeur_de_repli_sert_quand_l_atelier_ne_sait_pas() -> None:
    rendu = _url("http://x/sse?agent=${ATELIER_AGENT:-anonyme}", session="s", agent="")
    assert rendu == "http://x/sse?agent=anonyme"


def test_une_variable_inconnue_reste_visible() -> None:
    """Une adresse fautive se répare ; une adresse vidée en silence, non.

    Effacer la variable donnerait un service qui reçoit tout le monde sous la
    même identité — deux conversations mélangées, sans que rien ne le signale.
    """
    brute = "http://x/mcp?k=${CE_QUE_JE_NE_CONNAIS_PAS}"
    assert _url(brute, session="s", agent="a") == brute


def test_une_commande_locale_n_est_pas_touchee() -> None:
    """Tous les connecteurs ne sont pas des adresses."""
    stdio = {"command": "/home/onyxia/work/bin/node", "args": ["serveur.js"]}
    assert resoudre_les_variables(stdio, session="s", agent="a") == stdio
