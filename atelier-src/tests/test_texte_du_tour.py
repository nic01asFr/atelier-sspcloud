"""Ce qu'un tour rend comme texte, dit une fois.

Mesuré le 18 septembre sur le pod, avec le vrai CLI : « Le fichier a1.txt
contient 120 lignes. » revenait trois fois dans le résultat du tour. La même
phrase nous arrive en effet trois fois — en fragments pendant qu'elle
s'écrit, en bloc quand elle est finie, puis dans la ligne de résultat — et
nous les additionnions toutes. Ce texte est ce qu'un agent piloté rend à qui
l'a lancé : le tripler, c'est tripler la réponse.
"""

from __future__ import annotations

from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.harness import retenir_le_texte


def _dire(texte: str, raw_type: str) -> AtelierEvent:
    return AtelierEvent(kind="texte", session_id="s", text=texte, raw_type=raw_type)


def test_le_texte_arrive_trois_fois_et_ne_compte_qu_une() -> None:
    retenus: list[str] = []
    for fragment in ("Le fichier ", "a1.txt contient ", "120 lignes."):
        retenir_le_texte(retenus, _dire(fragment, "content_block_delta"))
    retenir_le_texte(retenus, _dire("Le fichier a1.txt contient 120 lignes.", "assistant"))
    retenir_le_texte(retenus, _dire("Le fichier a1.txt contient 120 lignes.", "result_text"))
    assert "".join(retenus) == "Le fichier a1.txt contient 120 lignes."


def test_deux_paroles_successives_se_suivent() -> None:
    """Ne pas dédoubler ne doit pas revenir à n'en garder qu'une."""
    retenus: list[str] = []
    retenir_le_texte(retenus, _dire("Je regarde. ", "assistant"))
    retenir_le_texte(retenus, _dire("Voilà.", "assistant"))
    assert "".join(retenus) == "Je regarde. Voilà."


def test_sans_bloc_complet_la_ligne_de_resultat_sauve_le_texte() -> None:
    """Un CLI qui n'émet rien en cours de route ne doit pas rendre le vide."""
    retenus: list[str] = []
    retenir_le_texte(retenus, _dire("tout ce qu'il a dit", "result_text"))
    assert "".join(retenus) == "tout ce qu'il a dit"


def test_le_raisonnement_ne_passe_pas_pour_de_la_parole() -> None:
    retenus: list[str] = []
    retenir_le_texte(retenus, _dire("je me demande si", "thinking"))
    retenir_le_texte(retenus, _dire("je me dem", "thinking_delta"))
    assert retenus == []
