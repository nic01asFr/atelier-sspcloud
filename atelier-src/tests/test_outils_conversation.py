"""Conduire une conversation de l'Atelier depuis un client MCP.

La passerelle donnait déjà le pool : un client distant appelait les outils de
tous les connecteurs du pod, et ne pouvait rien faire de l'Atelier lui-même.
Ces outils ferment cet écart. Ce que ces tests tiennent :

- une conversation ouverte par l'outil est **la même** que celle de
  l'interface — sans quoi on aurait deux mondes parallèles, et l'humain ne
  pourrait pas reprendre la main sur ce que l'agent distant a lancé ;
- `envoyer` rend la main tout de suite : un tour peut durer quarante-cinq
  minutes, un appel d'outil qui l'attend serait coupé bien avant ;
- `suivre` dit ce qui s'est produit, et surtout qu'un tour **attend une
  autorisation** — sinon on le croit lent alors qu'il est arrêté ;
- ces outils passent avant la résolution de profil dans la passerelle, sans
  quoi ils seraient refusés comme « hors périmètre ».
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.outils_conversation import OutilsAtelier


def outils_de(atelier: TestClient) -> OutilsAtelier:
    etat = atelier.app.state
    return OutilsAtelier(store=etat.store, projects=etat.projects, harness=etat.harness)


def appeler(outils: OutilsAtelier, nom: str, **arguments):
    """Le résultat déballé — les outils rendent du JSON dans du texte MCP."""
    reponse = asyncio.run(outils.appeler(nom, arguments))
    assert reponse is not None, f"{nom} n'a pas été reconnu"
    charge = json.loads(reponse["content"][0]["text"])
    return charge, bool(reponse.get("isError"))


def attendre_la_fin(outils: OutilsAtelier, conversation: str, limite_s: float = 15.0):
    """Suit jusqu'à ce que le tour soit fini, comme le ferait un appelant."""
    curseur = 0
    blocs: list[dict] = []
    fin = time.time() + limite_s
    while time.time() < fin:
        vu, _ = appeler(
            outils, "atelier_suivre", conversation=conversation, curseur=curseur, attendre_s=2
        )
        blocs += vu.get("blocs") or []
        curseur = vu.get("curseur", curseur)
        if vu.get("fini"):
            return vu, blocs
    raise AssertionError("le tour n'a pas fini dans le temps imparti")


# ── Voir ────────────────────────────────────────────────────────────────


def test_les_projets_se_voient(atelier: TestClient, cle_du_proprietaire: str) -> None:
    entete = {"Authorization": f"Bearer {cle_du_proprietaire}"}
    atelier.post("/v1/projects", json={"slug": "chantier", "kind": "code"}, headers=entete)
    charge, erreur = appeler(outils_de(atelier), "atelier_projets")
    assert not erreur
    assert "chantier" in [p["slug"] for p in charge["projets"]]


def test_une_conversation_ouverte_ici_est_celle_de_l_interface(
    atelier: TestClient, cle_du_proprietaire: str
) -> None:
    """Le point entier de ce lot : un seul monde, pas deux.

    Si l'outil créait sa propre conversation dans son coin, l'humain ne
    pourrait ni la regarder ni reprendre la main — ce serait un agent lâché
    sans fenêtre, exactement ce que l'Atelier existe pour éviter.
    """
    entete = {"Authorization": f"Bearer {cle_du_proprietaire}"}
    atelier.post("/v1/projects", json={"slug": "chantier", "kind": "code"}, headers=entete)
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="chantier", titre="Mené à distance")

    vues = atelier.get("/v1/sessions", headers=entete).json()["sessions"]
    fiche = next((s for s in vues if s["session_id"] == ouverte["id"]), None)
    assert fiche is not None, "la conversation n'apparaît pas dans l'interface"
    assert fiche["title"] == "Mené à distance"
    assert fiche["slug"] == "chantier"

    listees, _ = appeler(outils, "atelier_conversations", projet="chantier")
    assert ouverte["id"] in [c["id"] for c in listees["conversations"]]


def test_ouvrir_dans_un_projet_inconnu_dit_lesquels_existent(atelier: TestClient) -> None:
    charge, erreur = appeler(outils_de(atelier), "atelier_ouvrir", projet="nexiste-pas")
    assert erreur
    assert "projet inconnu" in charge["erreur"]
    # Un refus qui n'aide pas force un aller-retour de plus.
    assert "default" in charge["erreur"]


# ── Conduire ────────────────────────────────────────────────────────────


class _MagasinQuiTraine:
    """Un magasin dont le tour ne finit que lorsqu'on le décide.

    Mesurer une durée ne prouverait rien : le harnais factice répond en
    quelques millisecondes, si bien qu'un envoi resté bloquant passerait le
    test. Ici le tour ne peut pas finir tant que le test ne l'a pas relâché —
    si `envoyer` l'attendait, l'appel ne reviendrait jamais.
    """

    def __init__(self) -> None:
        self.relache = threading.Event()
        self.commence = threading.Event()
        self.settings = SimpleNamespace(default_slug="default")
        self.fiche = SimpleNamespace(session_id="conv", state="running", slug="default")

    def get(self, session_id: str):
        return self.fiche if session_id == "conv" else None

    def send(self, session_id, message, on_event=None, **_):
        self.commence.set()
        on_event(AtelierEvent(kind="texte", session_id=session_id, text="je commence"))
        if not self.relache.wait(timeout=10):
            raise AssertionError("le tour n'a jamais été relâché")
        return SimpleNamespace(text="fini", events=[])


def test_envoyer_rend_la_main_sans_attendre_le_tour() -> None:
    magasin = _MagasinQuiTraine()
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)

    charge, erreur = appeler(outils, "atelier_envoyer", conversation="conv", message="va")
    assert not erreur
    assert charge["etat"] == "parti"
    assert charge["curseur"] == 0
    assert magasin.commence.wait(timeout=5), "le tour n'a pas démarré"

    # Le tour travaille toujours : on voit déjà ce qu'il a dit, et on sait
    # qu'il n'a pas fini. C'est exactement ce qu'un client distant doit
    # pouvoir constater sans attendre.
    vu, _ = appeler(outils, "atelier_suivre", conversation="conv", curseur=0)
    assert vu["blocs"] == [{"genre": "texte", "texte": "je commence"}]
    assert not vu.get("fini")

    magasin.relache.set()
    for _ in range(100):
        vu, _ = appeler(outils, "atelier_suivre", conversation="conv", curseur=vu["curseur"])
        if vu.get("fini"):
            break
        time.sleep(0.05)
    assert vu.get("fini") is True
    assert vu.get("texte") == "fini"


def test_un_tour_qui_echoue_ne_reste_pas_en_cours() -> None:
    """Sinon `suivre` dirait « il travaille » pour toujours."""
    magasin = _MagasinQuiTraine()

    def casser(session_id, message, on_event=None, **_):
        raise RuntimeError("le harnais a lâché")

    magasin.send = casser  # type: ignore[assignment]
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)
    appeler(outils, "atelier_envoyer", conversation="conv", message="va")
    for _ in range(100):
        vu, _ = appeler(outils, "atelier_suivre", conversation="conv")
        if vu.get("fini"):
            break
        time.sleep(0.05)
    assert vu.get("fini") is True
    assert "le harnais a lâché" in vu.get("erreur", "")


def test_suivre_rend_ce_que_le_tour_a_produit(atelier: TestClient) -> None:
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    appeler(outils, "atelier_envoyer", conversation=ouverte["id"], message="retiens 42")
    fin, blocs = attendre_la_fin(outils, ouverte["id"])
    assert fin["fini"] is True
    assert "mémorisé" in (fin.get("texte") or "")
    assert any(b["genre"] == "texte" for b in blocs), blocs
    assert fin["etat"] in ("idle", "failed")


def test_le_curseur_ne_rend_pas_deux_fois_la_meme_chose(atelier: TestClient) -> None:
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    appeler(outils, "atelier_envoyer", conversation=ouverte["id"], message="retiens 7")
    fin, blocs = attendre_la_fin(outils, ouverte["id"])
    encore, _ = appeler(
        outils, "atelier_suivre", conversation=ouverte["id"], curseur=fin["curseur"]
    )
    assert encore["blocs"] == []
    assert encore["curseur"] == fin["curseur"]


def test_le_fil_garde_les_deux_tours(atelier: TestClient) -> None:
    """Conduire, c'est enchaîner : le second tour doit voir le premier."""
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    appeler(outils, "atelier_envoyer", conversation=ouverte["id"], message="retiens 42")
    attendre_la_fin(outils, ouverte["id"])
    appeler(outils, "atelier_envoyer", conversation=ouverte["id"], message="quel nombre ?")
    fin, _ = attendre_la_fin(outils, ouverte["id"])
    assert "42" in (fin.get("texte") or ""), fin


def test_suivre_une_conversation_menee_ailleurs_le_dit(atelier: TestClient) -> None:
    """Sans cette note, une liste de blocs vide se lirait « il ne fait rien »."""
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    vu, erreur = appeler(outils, "atelier_suivre", conversation=ouverte["id"])
    assert not erreur
    assert vu["blocs"] == []
    assert "note_suivi" in vu
    assert "transcript" in vu["note_suivi"]


def test_le_transcript_se_lit_et_se_tronque(atelier: TestClient) -> None:
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    appeler(outils, "atelier_envoyer", conversation=ouverte["id"], message="retiens 42")
    attendre_la_fin(outils, ouverte["id"])
    entier, _ = appeler(outils, "atelier_transcript", conversation=ouverte["id"])
    assert "retiens 42" in entier["transcript"]
    assert entier["tronque"] is False
    court, _ = appeler(outils, "atelier_transcript", conversation=ouverte["id"], derniers=200)
    assert court["tronque"] is True
    assert len(court["transcript"]) <= 200


def test_interrompre_une_conversation_connue(atelier: TestClient) -> None:
    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    charge, erreur = appeler(outils, "atelier_interrompre", conversation=ouverte["id"])
    assert not erreur
    assert charge["conversation"] == ouverte["id"]


@pytest.mark.parametrize(
    "nom", ["atelier_envoyer", "atelier_suivre", "atelier_transcript", "atelier_interrompre"]
)
def test_une_conversation_inconnue_est_refusee(atelier: TestClient, nom: str) -> None:
    charge, erreur = appeler(outils_de(atelier), nom, conversation="jamais-vue", message="bonjour")
    assert erreur
    assert "conversation inconnue" in charge["erreur"]


# ── Décider ─────────────────────────────────────────────────────────────


def test_une_demande_inconnue_est_refusee(atelier: TestClient) -> None:
    charge, erreur = appeler(
        outils_de(atelier), "atelier_decider", demande="jamais-posee", decision="allow"
    )
    assert erreur
    assert "demande inconnue" in charge["erreur"]


def test_une_decision_doit_etre_allow_ou_deny(atelier: TestClient) -> None:
    charge, erreur = appeler(
        outils_de(atelier), "atelier_decider", demande="peu-importe", decision="peut-etre"
    )
    assert erreur
    assert "allow" in charge["erreur"]


def test_suivre_annonce_une_autorisation_attendue(atelier: TestClient) -> None:
    """Un tour qui attend n'est pas un tour lent : il est arrêté.

    Sans cette remontée, un client distant attendrait indéfiniment des blocs
    qui ne viendront pas, sans savoir qu'il tient lui-même la clé.
    """
    from mcp_gateway.atelier.decisions import Demande

    outils = outils_de(atelier)
    ouverte, _ = appeler(outils, "atelier_ouvrir", projet="default")
    registre = atelier.app.state.harness.decisions
    demande = Demande(
        request_id="dem-1",
        session_id=ouverte["id"],
        outil="Bash",
        affichage="Bash",
        raison="commande hors des règles retenues",
    )
    # `poser` est le chemin réel : c'est ce que fait le harnais quand le CLI
    # demande une autorisation. Il rend le signal que le tour attendrait.
    registre.poser(demande)

    vu, _ = appeler(outils, "atelier_suivre", conversation=ouverte["id"])
    attendues = vu.get("autorisations_attendues") or []
    assert [a["demande"] for a in attendues] == ["dem-1"]
    assert attendues[0]["outil"] == "Bash"
    assert "hors des règles" in attendues[0]["pourquoi"]
    assert "atelier_decider" in vu["note"]


# ── La passerelle ───────────────────────────────────────────────────────


def test_la_passerelle_annonce_et_route_ces_outils(atelier: TestClient) -> None:
    """Ils doivent passer AVANT la résolution de profil.

    Ils n'appartiennent à aucun profil ni à aucun serveur amont : passés par
    le chemin normal, ils seraient refusés comme « hors périmètre ».
    """
    from mcp_gateway.mcp.gateway import McpGateway

    outils = outils_de(atelier)
    passerelle = McpGateway(
        catalog=None,
        bundles=None,
        pool=SimpleNamespace(db=None),
        compositions=None,
        outils_locaux=outils,
    )
    annonces = {d["name"] for d in passerelle._definitions_locales()}
    assert "atelier_ouvrir" in annonces and "atelier_suivre" in annonces
    assert annonces == outils.noms

    reponse = asyncio.run(passerelle.tools_call("atelier_projets", {}, None))
    charge = json.loads(reponse["content"][0]["text"])
    assert "projets" in charge


def test_un_nom_qui_n_est_pas_a_nous_passe_son_chemin(atelier: TestClient) -> None:
    """Sinon la famille avalerait des appels destinés au pool."""
    assert asyncio.run(outils_de(atelier).appeler("qgis__list_files", {})) is None
    assert asyncio.run(outils_de(atelier).appeler("atelier_inconnu", {})) is None


def test_chaque_outil_annonce_de_quoi_etre_appele(atelier: TestClient) -> None:
    for definition in outils_de(atelier).definitions():
        assert definition["name"].startswith("atelier_")
        assert len(definition["description"]) > 40, definition["name"]
        assert definition["inputSchema"]["type"] == "object"


# ── Ce que le flux rend lisible ─────────────────────────────────────────


def test_le_texte_debite_en_jetons_est_recolle() -> None:
    """Mesuré sur le pod : un tour rend « pr », « êt », « . ».

    Des centaines de blocs de deux caractères, entrelacés de marqueurs
    systèmes répétés. Rendus tels quels, ils coûtent cher et se lisent mal.
    """
    from mcp_gateway.atelier.outils_conversation import fondre

    brut = [
        {"genre": "systeme", "texte": "thinking_tokens"},
        {"genre": "texte", "texte": "pr"},
        {"genre": "systeme", "texte": "thinking_tokens"},
        {"genre": "systeme", "texte": "thinking_tokens"},
        {"genre": "texte", "texte": "êt"},
        {"genre": "texte", "texte": "."},
        {"genre": "outil_debut", "outil": "Bash"},
        {"genre": "texte", "texte": "fait"},
    ]
    assert fondre(brut) == [
        {"genre": "systeme", "texte": "thinking_tokens"},
        {"genre": "texte", "texte": "pr"},
        {"genre": "systeme", "texte": "thinking_tokens"},
        {"genre": "texte", "texte": "êt."},
        {"genre": "outil_debut", "outil": "Bash"},
        {"genre": "texte", "texte": "fait"},
    ]


def test_fondre_ne_touche_pas_a_la_source() -> None:
    """La fonte est une lecture : deux suivis doivent rendre la même chose."""
    from mcp_gateway.atelier.outils_conversation import fondre

    brut = [{"genre": "texte", "texte": "a"}, {"genre": "texte", "texte": "b"}]
    assert fondre(brut) == [{"genre": "texte", "texte": "ab"}]
    assert brut == [{"genre": "texte", "texte": "a"}, {"genre": "texte", "texte": "b"}]


def test_le_curseur_compte_les_blocs_bruts(atelier: TestClient) -> None:
    """Sinon la fonte ferait sauter ou relire des morceaux du tour."""
    magasin = _MagasinQuiTraine()

    def bavard(session_id, message, on_event=None, **_):
        magasin.commence.set()
        for morceau in ("pr", "êt", "."):
            on_event(AtelierEvent(kind="texte", session_id=session_id, text=morceau))
        magasin.relache.wait(timeout=5)
        return SimpleNamespace(text="prêt.", events=[])

    magasin.send = bavard  # type: ignore[assignment]
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)
    appeler(outils, "atelier_envoyer", conversation="conv", message="va")
    assert magasin.commence.wait(timeout=5)

    vu, _ = appeler(outils, "atelier_suivre", conversation="conv", curseur=0)
    assert vu["blocs"] == [{"genre": "texte", "texte": "prêt."}]
    assert vu["curseur"] == 3, "trois blocs ont été consommés, pas un"
    encore, _ = appeler(outils, "atelier_suivre", conversation="conv", curseur=vu["curseur"])
    assert encore["blocs"] == []
    magasin.relache.set()


def test_suivre_rapporte_un_paragraphe_pas_un_mot() -> None:
    """Sans repos, `suivre` revient au premier bloc venu.

    Le tour continue d'écrire ; l'appelant se retrouve à repasser pour chaque
    morceau, ce qui coûte un aller-retour par mot.
    """
    magasin = _MagasinQuiTraine()

    def lent(session_id, message, on_event=None, **_):
        magasin.commence.set()
        for morceau in ("Premier point. ", "Deuxième point. ", "Troisième point."):
            on_event(AtelierEvent(kind="texte", session_id=session_id, text=morceau))
            time.sleep(0.08)
        magasin.relache.wait(timeout=5)
        return SimpleNamespace(text="fini", events=[])

    magasin.send = lent  # type: ignore[assignment]
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)
    appeler(outils, "atelier_envoyer", conversation="conv", message="va")
    vu, _ = appeler(outils, "atelier_suivre", conversation="conv", curseur=0, attendre_s=5)
    magasin.relache.set()
    assert vu["blocs"] == [
        {"genre": "texte", "texte": "Premier point. Deuxième point. Troisième point."}
    ], vu["blocs"]


def test_les_fragments_et_le_raisonnement_ne_remontent_pas() -> None:
    """La même phrase arrive trois fois ; on n'en suit qu'une.

    Mesuré sur le pod : « prêt. » arrivait en plus de soixante blocs.
    """
    from mcp_gateway.atelier.outils_conversation import suivre_ce_bloc

    complet = AtelierEvent(kind="texte", session_id="s", text="prêt.")
    fragment = AtelierEvent(kind="texte", session_id="s", text="pr", raw_type="text_delta")
    pensee = AtelierEvent(kind="texte", session_id="s", text="hmm", raw_type="thinking_delta")
    battement = AtelierEvent(kind="heartbeat", session_id="s")
    outil = AtelierEvent(kind="outil_debut", session_id="s", tool="Bash")
    assert suivre_ce_bloc(complet) and suivre_ce_bloc(outil)
    assert not suivre_ce_bloc(fragment)
    assert not suivre_ce_bloc(pensee)
    assert not suivre_ce_bloc(battement)


def test_la_meme_phrase_n_est_suivie_qu_une_fois() -> None:
    """Mesuré sur le pod : « prêt. » revenait trois fois dans un seul tour.

    Elle arrive en bloc complet, puis dans la ligne de résultat. Un modèle qui
    suit croirait l'agent bègue, et paierait trois fois la même phrase.
    """
    from mcp_gateway.atelier.outils_conversation import fondre

    brut = [
        {"genre": "systeme", "texte": "init"},
        {"genre": "outil_fin"},
        {"genre": "texte", "texte": "\n\nprêt."},
        {"genre": "outil_fin"},
        {"genre": "texte", "texte": "\n\nprêt."},
        {"genre": "fin"},
    ]
    assert fondre(brut) == [
        {"genre": "systeme", "texte": "init"},
        {"genre": "texte", "texte": "\n\nprêt."},
        {"genre": "fin"},
    ]


def test_un_bloc_qui_ne_dit_rien_ne_remonte_pas() -> None:
    from mcp_gateway.atelier.outils_conversation import fondre

    assert fondre([{"genre": "outil_fin"}]) == []
    assert fondre([{"genre": "outil_fin", "outil": "Bash"}]) == [
        {"genre": "outil_fin", "outil": "Bash"}
    ]
    # La fin d'un tour se dit même nue : c'est elle qui clôt le suivi.
    assert fondre([{"genre": "fin"}]) == [{"genre": "fin"}]


def test_ouvrir_dans_un_projet_range_est_refuse(
    atelier: TestClient, cle_du_proprietaire: str
) -> None:
    """Mesuré sur le pod : le projet par défaut s'y trouvait rangé.

    Quatre conversations ouvertes par l'outil y ont disparu de la vue sans que
    rien ne le signale. Tout ce lot tient à ce que l'humain puisse regarder et
    reprendre la main : ouvrir un fil invisible le vide de son sens.
    """
    entete = {"Authorization": f"Bearer {cle_du_proprietaire}"}
    atelier.post("/v1/projects", json={"slug": "remise", "kind": "code"}, headers=entete)
    atelier.post("/v1/projects", json={"slug": "visible", "kind": "code"}, headers=entete)
    atelier.patch("/v1/projects/remise", json={"archived": True}, headers=entete)

    charge, erreur = appeler(outils_de(atelier), "atelier_ouvrir", projet="remise")
    assert erreur
    assert "projet rangé" in charge["erreur"]
    # Le refus doit dire où aller, sinon il coûte un aller-retour de plus.
    assert "visible" in charge["erreur"]


def test_le_tour_part_avec_un_interlocuteur() -> None:
    """Sinon il part en bypass et ne demande jamais rien.

    Mesuré sur le pod : une commande Bash s'est exécutée sans qu'une seule
    autorisation soit demandée, et `atelier_decider` n'avait donc aucun moyen
    de servir. Le service choisit le mode d'après ce drapeau
    (`sessions.py` : sans interlocuteur, mode sans demande).
    """
    magasin = _MagasinQuiTraine()
    vus: dict = {}

    def noter(session_id, message, on_event=None, **kw):
        vus.update(kw)
        magasin.commence.set()
        return SimpleNamespace(text="ok", events=[])

    magasin.send = noter  # type: ignore[assignment]
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)
    appeler(outils, "atelier_envoyer", conversation="conv", message="va")
    assert magasin.commence.wait(timeout=5)
    assert vus.get("peut_attendre") is True


def test_la_meme_phrase_ne_revient_pas_d_un_suivi_a_l_autre() -> None:
    """La phrase tombait de part et d'autre de deux appels — mesuré sur le pod.

    Chaque appel dédupliquait pour lui seul, donc la répétition passait entre
    les mailles : l'appelant voyait l'agent bégayer.
    """
    from mcp_gateway.atelier.outils_conversation import fondre

    memoire: set[str] = set()
    premier = fondre([{"genre": "texte", "texte": "voici le résultat"}], memoire)
    assert premier == [{"genre": "texte", "texte": "voici le résultat"}]
    second = fondre(
        [{"genre": "texte", "texte": "voici le résultat"}, {"genre": "fin"}], memoire
    )
    assert second == [{"genre": "fin"}]


def test_un_message_mis_en_file_le_dit() -> None:
    """Sinon `envoyer` dit « parti » et `suivre` dit « fini », sans un bloc.

    Mesuré en conduisant un vrai projet : le message attendait derrière un
    tour en cours, et l'appelant en concluait que le tour n'avait rien
    produit. La parole avalée en silence.
    """
    magasin = _MagasinQuiTraine()

    def en_file(session_id, message, on_event=None, **_):
        magasin.commence.set()
        return SimpleNamespace(
            text="",
            events=[
                AtelierEvent(
                    kind="systeme", session_id=session_id, cause="message_en_file", text=message
                )
            ],
        )

    magasin.send = en_file  # type: ignore[assignment]
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)
    appeler(outils, "atelier_envoyer", conversation="conv", message="la suite")
    assert magasin.commence.wait(timeout=5)
    for _ in range(50):
        vu, _ = appeler(outils, "atelier_suivre", conversation="conv")
        if vu.get("fini"):
            break
        time.sleep(0.05)
    assert vu.get("mis_en_file") is True
    assert "attend derrière" in vu.get("note", "")
    assert any(b.get("cause") == "message_en_file" for b in vu["blocs"]), vu["blocs"]
