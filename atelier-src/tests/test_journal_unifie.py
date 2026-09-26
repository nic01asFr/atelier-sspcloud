"""Une conversation ouverte des deux côtés doit montrer la même histoire.

Mesuré sur le pod avant d'écrire une ligne : sur `a948d684`, quatre messages
tapés dans VS Code — « continue, cherche plutot sur github », « avec les tools
github » — n'existaient que dans le registre du CLI ; l'Atelier n'en avait
aucune trace. Sur `308a22a4`, à l'inverse, les deux premiers tours n'existaient
que chez nous, absents du transcript du CLI sur ses 6 Mo entiers.

Aucun des deux registres n'est donc complet, et il n'y en a pas un à préférer.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.journal import fondre, histoire_unifiee, normaliser


def _ligne(type_: str, texte: str, horodatage: str, uuid: str) -> str:
    return json.dumps(
        {
            "type": type_,
            "uuid": uuid,
            "timestamp": horodatage,
            "message": {"role": type_, "content": [{"type": "text", "text": texte}]},
        },
        ensure_ascii=False,
    )


def _registre(chemin: Path, lignes: list[str]) -> Path:
    chemin.write_text(chr(10).join(lignes) + chr(10), encoding="utf-8")
    return chemin


def test_ce_qui_a_ete_tape_dans_vs_code_remonte(tmp_path: Path) -> None:
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "premier", "10:00", "u1")])
    cli = _registre(
        tmp_path / "c.jsonl",
        [
            _ligne("user", "premier", "10:00", "u1"),
            _ligne("user", "continue, cherche plutot sur github", "10:05", "u2"),
        ],
    )

    dits = [e["message"]["content"][0]["text"] for e in fondre([atelier, cli])]
    assert dits == ["premier", "continue, cherche plutot sur github"]


def test_ce_que_seul_l_atelier_detient_survit(tmp_path: Path) -> None:
    """Le CLI repart sur un fichier neuf à chaque reprise ; il oublie."""
    atelier = _registre(
        tmp_path / "a.jsonl",
        [_ligne("user", "le tout premier tour", "09:00", "u0"), _ligne("user", "b", "10:00", "u1")],
    )
    cli = _registre(tmp_path / "c.jsonl", [_ligne("user", "b", "10:00", "u1")])

    dits = [e["message"]["content"][0]["text"] for e in fondre([atelier, cli])]
    assert dits == ["le tout premier tour", "b"]


def test_l_histoire_se_remet_dans_l_ordre(tmp_path: Path) -> None:
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "a", "10:00", "u1")])
    cli = _registre(
        tmp_path / "c.jsonl",
        [_ligne("user", "avant", "09:00", "u0"), _ligne("user", "apres", "11:00", "u2")],
    )

    dits = [e["message"]["content"][0]["text"] for e in fondre([atelier, cli])]
    assert dits == ["avant", "a", "apres"]


def test_une_meme_entree_n_apparait_qu_une_fois(tmp_path: Path) -> None:
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "bonjour", "10:00", "u1")])
    cli = _registre(tmp_path / "c.jsonl", [_ligne("user", "bonjour", "10:00", "u1")])

    assert len(fondre([atelier, cli])) == 1


def test_deux_graphies_d_un_meme_geste_se_confondent(tmp_path: Path) -> None:
    """`/compact` chez nous, `<command-name>` et codes ANSI chez le CLI.

    Sans cette équivalence, chaque compaction s'afficherait deux fois — c'est
    ce qui gonflait l'écart de comptage entre les deux registres.
    """
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "/compact", "10:00", "u1")])
    cli = _registre(
        tmp_path / "c.jsonl",
        [_ligne("user", "<command-name>/compact</command-name>", "10:00", "u9")],
    )

    fondu = fondre([atelier, cli])
    assert len(fondu) == 1
    assert fondu[0]["message"]["content"][0]["text"] == "/compact", "la graphie de l'Atelier gagne"


def test_les_couleurs_du_terminal_ne_font_pas_deux_messages() -> None:
    assert normaliser("\x1b[2mCompacted \x1b[22m") == normaliser("Compacted")


def test_deux_tours_sans_texte_ne_se_confondent_pas(tmp_path: Path) -> None:
    """Un tour qui n'appelle que des outils n'a pas de texte.

    Les dédoublonner sur un texte vide les réduirait tous à un seul, et la
    conversation perdrait ses appels d'outils.
    """
    def outil(uuid: str, horodatage: str) -> str:
        return json.dumps({
            "type": "assistant", "uuid": uuid, "timestamp": horodatage,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
        })

    reg = _registre(tmp_path / "a.jsonl", [outil("u1", "10:00"), outil("u2", "10:01")])
    assert len(fondre([reg])) == 2


def test_la_mecanique_du_flux_ne_remonte_pas(tmp_path: Path) -> None:
    """Les événements de flux et les opérations de file ne sont pas la conversation."""
    reg = _registre(tmp_path / "a.jsonl", [
        json.dumps({"type": "stream_event", "uuid": "s1"}),
        json.dumps({"type": "queue-operation", "uuid": "q1"}),
        _ligne("user", "bonjour", "10:00", "u1"),
    ])
    assert [e["type"] for e in fondre([reg])] == ["user"]


def test_un_registre_absent_ne_fait_pas_tomber_la_lecture(tmp_path: Path) -> None:
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "seul", "10:00", "u1")])
    assert len(fondre([atelier, tmp_path / "jamais-ecrit.jsonl"])) == 1


def test_une_ligne_illisible_n_emporte_pas_le_reste(tmp_path: Path) -> None:
    reg = _registre(tmp_path / "a.jsonl", ["{ceci n'est pas du json", _ligne("user", "ok", "10:00", "u1")])
    assert len(fondre([reg])) == 1


def test_le_rendu_garde_le_format_de_lignes_attendu(tmp_path: Path) -> None:
    atelier = _registre(tmp_path / "a.jsonl", [_ligne("user", "bonjour", "10:00", "u1")])
    texte = histoire_unifiee([atelier])
    assert texte.endswith(chr(10))
    assert json.loads(texte.strip())["message"]["content"][0]["text"] == "bonjour"


def test_les_entrees_machinales_ne_se_lisent_pas_comme_des_messages(tmp_path: Path) -> None:
    """La fusion les a fait remonter : le CLI se les écrit à lui-même.

    Vu à l'écran après la fusion : `<task-notification>` s'affichait dans le
    fil comme si l'utilisateur l'avait tapé.
    """
    reg = _registre(tmp_path / "a.jsonl", [
        _ligne("user", "<task-notification> <task-id>abc</task-id> </task-notification>", "10:00", "u1"),
        _ligne("user", "<local-command-stdout>Compacted </local-command-stdout>", "10:01", "u2"),
        _ligne("user", "une vraie question", "10:02", "u3"),
    ])
    dits = [e["message"]["content"][0]["text"] for e in fondre([reg])]
    assert dits == ["une vraie question"]


def test_une_interruption_reste_visible(tmp_path: Path) -> None:
    """Elle dit ce que quelqu'un a fait ; l'effacer réécrirait l'histoire."""
    reg = _registre(tmp_path / "a.jsonl", [
        _ligne("user", "[Request interrupted by user for tool use]", "10:00", "u1"),
    ])
    assert len(fondre([reg])) == 1


def test_un_message_qui_cite_une_balise_n_est_pas_ecarte(tmp_path: Path) -> None:
    """Un filtre trop large mangerait du contenu : `<em>`, `<tr>`, `<projet>`
    apparaissent légitimement dans les messages."""
    reg = _registre(tmp_path / "a.jsonl", [
        _ligne("user", "regarde le <projet> dans la table <tr>", "10:00", "u1"),
    ])
    assert len(fondre([reg])) == 1


def test_le_resultat_sans_horodatage_reste_a_la_fin_de_son_tour(tmp_path: Path) -> None:
    # Cas du pod (26/09) : le journal de l'Atelier écrit le `result` du tour
    # sans horodatage ; il remontait juste après la question et l'affichage
    # montrait la réponse deux fois.
    resultat = json.dumps({"type": "result", "subtype": "success", "uuid": "r1", "result": "J'ai listé les fichiers."})
    atelier = _registre(
        tmp_path / "a.jsonl",
        [
            _ligne("user", "liste les fichiers", "2026-09-26T03:42:35", "q1"),
            _ligne("assistant", "J'ai listé les fichiers.", "2026-09-26T03:42:47", "a1"),
            resultat,
        ],
    )
    cli = _registre(
        tmp_path / "c.jsonl",
        [
            _ligne("user", "liste les fichiers", "2026-09-26T03:42:39", "q2"),
            _ligne("assistant", "J'ai listé les fichiers.", "2026-09-26T03:42:47", "a1"),
        ],
    )
    types = [e["type"] for e in fondre([atelier, cli])]
    assert types.index("result") > types.index("assistant")
    assert types[-1] == "result"
