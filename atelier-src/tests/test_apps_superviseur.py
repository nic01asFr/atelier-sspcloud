"""Le superviseur des applications, éprouvé sur de vrais processus.

Aucun double pour le processus : chaque test lance `app_factice.py`, une
vraie petite application HTTP, et regarde ce qu'elle voit (son
environnement, ses limites) et ce qu'il en reste après coup (`/proc`).

Les primitives employées — sessions, groupes, `killpg`, `/proc`, `RLIMIT` —
sont celles du pod, Linux. Ailleurs, les tests qui en dépendent sont sautés ;
ils se lancent pour de vrai sur le pod.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from mcp_gateway.atelier.apps.manifeste import lire_manifeste
from mcp_gateway.atelier.apps.superviseur import (
    ARRETE,
    DEMARRAGE,
    EN_ECHEC,
    PRET,
    REDEMARRAGE,
    ErreurApplication,
    PlafondAtteint,
    Superviseur,
    meme_commande,
    plage_de_ports,
)
from mcp_gateway.atelier.config import AtelierSettings

APP = Path(__file__).with_name("app_factice.py")
SLUG = "demo"

linux = pytest.mark.skipif(sys.platform != "linux", reason="sessions, killpg et /proc : Linux seulement")


class Horloge:
    """Une horloge qu'on avance à la main."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def reglages(tmp_path: Path) -> AtelierSettings:
    # Une plage à part, tirée du pid, pour ne pas croiser une autre suite qui
    # tournerait en même temps sur la même machine.
    debut = 20000 + (os.getpid() % 200) * 50
    return AtelierSettings(
        work_dir=tmp_path / "work",
        apps_ports=f"{debut}-{debut + 19}",
        apps_public_url="https://atelier-apps.exemple.fr",
    )


NOMS = ("voix", "lente", "morte", "absente", "fragile", "tetue", "une", "deux", "gourmande", "site")


@pytest.fixture()
def projet(tmp_path: Path) -> Path:
    """Un projet et ses dossiers d'artefacts : la commande s'exécute dans le sien."""
    racine = tmp_path / "projet"
    for nom in NOMS:
        (racine / "artifacts" / nom).mkdir(parents=True)
    return racine


def superviseur(reglages: AtelierSettings, **options: object) -> Superviseur:
    options.setdefault("pas_demarrage_s", 0.1)
    options.setdefault("delai_sigkill_s", 2.0)
    options.setdefault("attente_base_s", 0.01)
    return Superviseur(reglages, **options)  # type: ignore[arg-type]


def manifeste(*arguments: str, **champs: object):
    donnees = {
        "version": 1,
        "commande": [sys.executable, str(APP), "--port", "{port}", *arguments],
        "sante": "/health",
        "demarrage_s": 15,
    }
    donnees.update(champs)
    return lire_manifeste(donnees)


def vivant(pid: int) -> bool:
    """Vivant au sens de `/proc` : un zombie ne tient plus rien."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat[stat.rfind(")") + 2] not in "ZX"


async def attendre_mort(pid: int, delai: float = 5.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if not vivant(pid):
            return True
        await asyncio.sleep(0.05)
    return not vivant(pid)


async def lire(port: int, chemin: str) -> dict:
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        reponse = await client.get(f"http://127.0.0.1:{port}{chemin}")
    return reponse.json()


# --- Fonctions pures, partout --------------------------------------------


def test_plage_de_ports() -> None:
    assert plage_de_ports("19000-19099") == range(19000, 19100)
    assert plage_de_ports("19000") == range(19000, 19001)
    for faux in ("", "80-90", "19100-19000", "a-b", "1-2-3", "19000-70000"):
        with pytest.raises(ValueError):
            plage_de_ports(faux)


def test_meme_commande_tolere_le_shebang() -> None:
    lancee = ["uvicorn", "app:app", "--port", "19001"]
    assert meme_commande(lancee, lancee)
    assert meme_commande(["/v/bin/python3", "/v/bin/uvicorn", "app:app", "--port", "19001"], lancee)
    assert not meme_commande(["uvicorn", "app:app", "--port", "19002"], lancee)
    assert not meme_commande(["sleep", "300"], lancee)
    assert not meme_commande(["/v/bin/python3", "/v/bin/gunicorn", "app:app", "--port", "19001"], lancee)


def test_reglages_par_defaut() -> None:
    r = AtelierSettings(work_dir=Path("/tmp/inutilise"))
    assert (r.apps_port, r.apps_ports, r.apps_max, r.apps_idle_minutes) == (8788, "19000-19099", 4, 30)
    assert r.apps_public_url == ""


def test_application_statique_sans_processus(reglages: AtelierSettings, projet: Path) -> None:
    m = lire_manifeste({"version": 1, "type": "statique"})
    with pytest.raises(ErreurApplication, match="statique"):
        asyncio.run(superviseur(reglages).demarrer(SLUG, "site", projet, m))


def test_nom_invalide_refuse(reglages: AtelierSettings, projet: Path) -> None:
    with pytest.raises(ErreurApplication):
        asyncio.run(superviseur(reglages).demarrer("../x", "voix", projet, manifeste()))
    with pytest.raises(ErreurApplication):
        superviseur(reglages).journal(SLUG, "../../etc", 10)


# --- Cycle de vie, sur Linux ---------------------------------------------


@linux
def test_demarre_sur_un_port_attribue_libre(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        premier = sup.ports[0]
        occupant = socket.socket()
        occupant.bind(("127.0.0.1", premier))
        occupant.listen()
        try:
            info = await sup.demarrer(SLUG, "voix", projet, manifeste())
            assert info.etat == PRET, info.raison
            assert info.port in sup.ports and info.port != premier
            assert sup.cible(SLUG, "voix").port == info.port
            assert sup.ports_attribues() == {info.port}
            assert (await lire(info.port, "/health"))["sante"] == "ok"
        finally:
            occupant.close()
            await sup.fermer()
        assert sup.cible(SLUG, "voix") is None
        assert sup.ports_attribues() == set()

    asyncio.run(scenario())


@linux
def test_environnement_construit_sans_rien_du_service(
    reglages: AtelierSettings, projet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATELIER_OWNER_KEY", "cle-du-proprietaire")
    monkeypatch.setenv("ATELIER_LLM_API_KEY", "cle-llm")
    monkeypatch.setenv("ATELIER_GITHUB_TOKEN", "jeton-github")
    monkeypatch.setenv("SECRET_DU_SERVICE", "ne-doit-pas-passer")
    secrets = reglages.secrets_dir / "apps"
    secrets.mkdir(parents=True)
    (secrets / "voix").write_text("valeur-secrete\n")
    os.chmod(secrets / "voix", 0o600)

    async def scenario() -> dict:
        sup = superviseur(reglages)
        m = manifeste(env={"MODELE": "whisper-small"}, secrets={"VOICE_TOKEN": "voix"})
        info = await sup.demarrer(SLUG, "voix", projet, m)
        try:
            env = await lire(info.port, "/env")
            env["_port"] = info.port
            return env
        finally:
            await sup.fermer()

    env = asyncio.run(scenario())
    atelier = {k for k in env if k.startswith("ATELIER_")}
    assert atelier == {"ATELIER_APP_PREFIX", "ATELIER_APP_URL", "ATELIER_APP_NOM"}
    assert "SECRET_DU_SERVICE" not in env
    assert "cle-du-proprietaire" not in json.dumps(env)
    assert env["PORT"] == str(env["_port"])
    assert env["ATELIER_APP_PREFIX"] == "/demo/voix"
    assert env["ATELIER_APP_URL"] == "https://atelier-apps.exemple.fr/demo/voix/"
    assert env["ATELIER_APP_NOM"] == "voix"
    assert env["VOICE_TOKEN"] == "valeur-secrete"
    assert env["MODELE"] == "whisper-small"
    assert env["PYTHONUNBUFFERED"] == "1"


@linux
def test_venv_du_projet_en_tete_du_path(reglages: AtelierSettings, projet: Path) -> None:
    (projet / ".venv" / "bin").mkdir(parents=True)

    async def scenario() -> dict:
        sup = superviseur(reglages)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste())
        try:
            return await lire(info.port, "/env")
        finally:
            await sup.fermer()

    env = asyncio.run(scenario())
    assert env["VIRTUAL_ENV"] == str(projet / ".venv")
    assert env["PATH"].split(os.pathsep)[0] == str(projet / ".venv" / "bin")


@linux
def test_secret_manquant_ou_trop_ouvert(reglages: AtelierSettings, projet: Path) -> None:
    sup = superviseur(reglages)
    m = manifeste(secrets={"VOICE_TOKEN": "voix"})
    with pytest.raises(ErreurApplication, match="secret manquant"):
        asyncio.run(sup.demarrer(SLUG, "voix", projet, m))
    secrets = reglages.secrets_dir / "apps"
    secrets.mkdir(parents=True)
    (secrets / "voix").write_text("x")
    os.chmod(secrets / "voix", 0o644)
    with pytest.raises(ErreurApplication, match="chmod 600"):
        asyncio.run(sup.demarrer(SLUG, "voix", projet, m))
    assert sup.ports_attribues() == set()


@linux
def test_limites_du_processus(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> dict:
        sup = superviseur(reglages, fichiers_ouverts_max=1024)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste())
        try:
            return await lire(info.port, "/limites")
        finally:
            await sup.fermer()

    limites = asyncio.run(scenario())
    assert limites["nofile"] == [1024, 1024]
    assert limites["nice"] == min(19, os.nice(0) + 10)


@linux
def test_journal_et_rotation(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> Superviseur:
        sup = superviseur(reglages, journal_max_octets=8192, journal_copies=2)
        await sup.demarrer(SLUG, "voix", projet, manifeste("--bavard", "400"))
        await sup.fermer()
        return sup

    sup = asyncio.run(scenario())
    chemin = sup.chemin_journal(SLUG, "voix")
    assert chemin == reglages.work_dir / "logs" / "apps" / SLUG / "voix.log"
    copies = sorted(p.name for p in chemin.parent.iterdir())
    assert copies == ["voix.log", "voix.log.1", "voix.log.2"]
    for p in chemin.parent.iterdir():
        assert p.stat().st_size <= 8192
    fin = sup.journal(SLUG, "voix", lignes=3).splitlines()
    assert len(fin) == 3
    assert "arrêt" in fin[-1] or "atelier" in fin[-1]
    assert "ligne 000399" in sup.journal(SLUG, "voix", lignes=200)


@linux
def test_demarrage_trop_long_passe_en_echec(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        debut = time.monotonic()
        info = await sup.demarrer(SLUG, "lente", projet, manifeste("--lent", "60", demarrage_s=1))
        assert time.monotonic() - debut < 6
        assert info.etat == EN_ECHEC
        assert "pas prête après 1 s" in info.raison
        assert info.pid is None and info.port is None
        assert "pas prête" in sup.journal(SLUG, "lente", 20)

    asyncio.run(scenario())


@linux
def test_mort_au_demarrage_passe_en_echec(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        m = lire_manifeste({"version": 1, "commande": [sys.executable, "-c", "raise SystemExit(7)"]})
        info = await sup.demarrer(SLUG, "morte", projet, m)
        assert info.etat == EN_ECHEC
        assert "code 7" in info.raison
        m = lire_manifeste({"version": 1, "commande": ["/nulle/part/programme"]})
        info = await sup.demarrer(SLUG, "absente", projet, m)
        assert info.etat == EN_ECHEC
        assert "lancement impossible" in info.raison

    asyncio.run(scenario())


@linux
def test_demarrage_sans_attendre(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste("--lent", "0.5"), attendre=False)
        assert info.etat == DEMARRAGE
        assert sup.cible(SLUG, "voix") is None
        info = await sup.attendre(SLUG, "voix")
        assert info.etat == PRET
        # Un second démarrage ne relance rien.
        assert (await sup.demarrer(SLUG, "voix", projet, manifeste())).pid == info.pid
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_mort_redemarre_avec_attente_croissante_puis_en_echec(
    reglages: AtelierSettings, projet: Path
) -> None:
    horloge = Horloge()
    attentes: list[float] = []

    async def dormir(s: float) -> None:
        attentes.append(s)

    async def scenario() -> None:
        sup = superviseur(reglages, horloge=horloge, dormir=dormir, attente_base_s=1.0)
        m = manifeste("--mourir-apres", "1.0")
        info = await sup.demarrer(SLUG, "fragile", projet, m)
        pids = {info.pid}
        for _ in range(5):
            assert await attendre_mort(info.pid)
            await asyncio.sleep(0.2)  # le temps que asyncio constate la mort
            await sup.superviser_une_fois()
            assert sup.etat(SLUG, "fragile").etat == REDEMARRAGE
            info = await sup.attendre(SLUG, "fragile")
            assert info.etat == PRET, info.raison
            pids.add(info.pid)
            horloge.t += 10
        assert len(pids) == 6
        assert attentes == [1.0, 2.0, 4.0, 8.0, 16.0]
        # Sixième mort en dix minutes : on n'insiste plus.
        assert await attendre_mort(info.pid)
        await asyncio.sleep(0.2)
        await sup.superviser_une_fois()
        info = await sup.attendre(SLUG, "fragile")
        assert info.etat == EN_ECHEC
        assert "5 redémarrages" in info.raison
        assert sup.cible(SLUG, "fragile") is None
        # Un geste humain la relance, compteur remis à zéro.
        info = await sup.demarrer(SLUG, "fragile", projet, m)
        assert info.etat == PRET
        assert info.redemarrages_recents == 0
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_fenetre_des_redemarrages_glisse(reglages: AtelierSettings, projet: Path) -> None:
    horloge = Horloge()

    async def scenario() -> None:
        sup = superviseur(reglages, horloge=horloge, redemarrages_max=1)
        m = manifeste("--mourir-apres", "1.0")
        info = await sup.demarrer(SLUG, "fragile", projet, m)
        assert await attendre_mort(info.pid)
        await asyncio.sleep(0.2)
        await sup.superviser_une_fois()
        info = await sup.attendre(SLUG, "fragile")
        assert info.etat == PRET
        # Le seul redémarrage permis est vieux de plus de dix minutes.
        horloge.t += 601
        assert await attendre_mort(info.pid)
        await asyncio.sleep(0.2)
        await sup.superviser_une_fois()
        info = await sup.attendre(SLUG, "fragile")
        assert info.etat == PRET, info.raison
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_trois_sondes_echouees_redemarrent(reglages: AtelierSettings, projet: Path, tmp_path: Path) -> None:
    drapeau = tmp_path / "malade"

    async def scenario() -> None:
        sup = superviseur(reglages)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste("--sante-ko-si", str(drapeau)))
        premier = info.pid
        drapeau.touch()
        await sup.superviser_une_fois()
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == PRET
        assert sup.etat(SLUG, "voix").pid == premier
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == REDEMARRAGE
        drapeau.unlink()
        info = await sup.attendre(SLUG, "voix")
        assert info.etat == PRET
        assert info.pid != premier
        assert await attendre_mort(premier)
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_arret_sur_inactivite_sauf_connexion_ouverte(reglages: AtelierSettings, projet: Path) -> None:
    horloge = Horloge()

    async def scenario() -> None:
        sup = superviseur(reglages, horloge=horloge)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste(inactivite_min=1))
        pid = info.pid
        horloge.t += 59
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == PRET
        # Une WebSocket ouverte compte comme activité, aussi longtemps qu'elle dure.
        sup.ouvrir_connexion(SLUG, "voix")
        horloge.t += 3600
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == PRET
        assert sup.etat(SLUG, "voix").connexions == 1
        sup.fermer_connexion(SLUG, "voix")
        horloge.t += 30
        sup.noter_activite(SLUG, "voix")
        horloge.t += 59
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == PRET
        horloge.t += 2
        await sup.superviser_une_fois()
        info = sup.etat(SLUG, "voix")
        assert info.etat == ARRETE
        assert info.raison == "inactivité"
        assert info.port is None
        assert await attendre_mort(pid)

    asyncio.run(scenario())


@linux
def test_inactivite_par_defaut_des_reglages(reglages: AtelierSettings, projet: Path) -> None:
    horloge = Horloge()

    async def scenario() -> None:
        sup = superviseur(reglages, horloge=horloge)
        await sup.demarrer(SLUG, "voix", projet, manifeste())
        with sup.connexion(SLUG, "voix"):
            assert sup.etat(SLUG, "voix").connexions == 1
        horloge.t += reglages.apps_idle_minutes * 60 - 1
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == PRET
        horloge.t += 1
        await sup.superviser_une_fois()
        assert sup.etat(SLUG, "voix").etat == ARRETE

    asyncio.run(scenario())


@linux
def test_arret_tue_tout_le_groupe(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste("--enfant"))
        pids = await lire(info.port, "/pid")
        assert pids["pid"] == info.pid
        assert vivant(pids["enfant"])
        await sup.arreter(SLUG, "voix")
        assert await attendre_mort(pids["pid"])
        assert await attendre_mort(pids["enfant"])
        assert sup.etat(SLUG, "voix").etat == ARRETE

    asyncio.run(scenario())


@linux
def test_sigkill_apres_le_delai(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages, delai_sigkill_s=1.0)
        info = await sup.demarrer(SLUG, "tetue", projet, manifeste("--ignorer-sigterm"))
        debut = time.monotonic()
        await sup.arreter(SLUG, "tetue")
        assert time.monotonic() - debut >= 1.0
        assert await attendre_mort(info.pid, 1)
        assert "SIGKILL" in sup.journal(SLUG, "tetue", 5)

    asyncio.run(scenario())


@linux
def test_plafond_d_applications_simultanees(reglages: AtelierSettings, projet: Path) -> None:
    reglages.apps_max = 1

    async def scenario() -> None:
        sup = superviseur(reglages)
        await sup.demarrer(SLUG, "une", projet, manifeste())
        with pytest.raises(PlafondAtteint):
            await sup.demarrer(SLUG, "deux", projet, manifeste())
        await sup.arreter(SLUG, "une")
        info = await sup.demarrer(SLUG, "deux", projet, manifeste())
        assert info.etat == PRET
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_plafond_de_memoire(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages, plafond_memoire_octets=60 * 2**20)
        info = await sup.demarrer(SLUG, "gourmande", projet, manifeste("--memoire", "120"))
        assert info.etat == PRET
        await sup.superviser_une_fois()
        info = sup.etat(SLUG, "gourmande")
        assert info.etat == REDEMARRAGE
        assert "mémoire" in info.raison
        await sup.fermer()

    asyncio.run(scenario())


@linux
def test_ecoute_sur_un_socket_unix(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        m = lire_manifeste(
            {
                "version": 1,
                "commande": [sys.executable, str(APP), "--socket", "{socket}"],
                "ecoute": "unix",
                "sante": "/health",
                "demarrage_s": 15,
            }
        )
        info = await sup.demarrer(SLUG, "voix", projet, m)
        assert info.etat == PRET, info.raison
        cible = sup.cible(SLUG, "voix")
        assert cible.port is None and cible.socket.exists()
        transport = httpx.AsyncHTTPTransport(uds=str(cible.socket))
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            env = (await client.get("http://app/env")).json()
        assert "PORT" not in env
        await sup.fermer()
        assert not cible.socket.exists()

    asyncio.run(scenario())


@linux
def test_etat_persistant(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages)
        info = await sup.demarrer(SLUG, "voix", projet, manifeste())
        etat = json.loads(sup.fichier_etat.read_text())
        assert sup.fichier_etat == reglages.work_dir / ".atelier-etat" / "apps.json"
        entree = etat["apps"]["demo/voix"]
        assert entree["pid"] == entree["pgid"] == info.pid
        assert entree["port"] == info.port
        assert entree["argv"][-1] == str(info.port)
        await sup.fermer()
        assert json.loads(sup.fichier_etat.read_text())["apps"] == {}

    asyncio.run(scenario())


@linux
def test_orphelins_tues_seulement_s_ils_sont_a_nous(reglages: AtelierSettings, projet: Path) -> None:
    # Un Atelier mort sans rien arrêter : son application tourne encore, dans
    # son groupe, et l'état sur le disque la décrit.
    argv = [sys.executable, str(APP), "--port", str(plage_de_ports(reglages.apps_ports)[5]), "--enfant"]
    orphelin = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL)
    # Un pid recyclé : l'état le décrit, mais la commande n'est plus la même.
    etranger = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        dossier = reglages.work_dir / ".atelier-etat"
        dossier.mkdir(parents=True)
        (dossier / "apps.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "apps": {
                        "demo/voix": {"pid": orphelin.pid, "pgid": orphelin.pid, "argv": argv},
                        "demo/autre": {"pid": etranger.pid, "pgid": etranger.pid, "argv": argv},
                    },
                }
            )
        )
        time.sleep(0.5)
        tues = asyncio.run(superviseur(reglages).nettoyer_orphelins())
        assert tues == [orphelin.pid]
        assert orphelin.wait(timeout=5) is not None
        assert etranger.poll() is None
        assert json.loads((dossier / "apps.json").read_text())["apps"] == {}
    finally:
        for p in (orphelin, etranger):
            if p.poll() is None:
                p.kill()
                p.wait()


@linux
def test_fermer_arrete_tout(reglages: AtelierSettings, projet: Path) -> None:
    async def scenario() -> None:
        sup = superviseur(reglages, intervalle_sonde_s=0.05)
        sup.lancer()
        a = await sup.demarrer(SLUG, "une", projet, manifeste())
        b = await sup.demarrer("autre", "deux", projet, manifeste())
        assert {i.nom for i in sup.lister()} == {"une", "deux"}
        assert [i.nom for i in sup.lister("autre")] == ["deux"]
        await asyncio.sleep(0.3)  # la boucle tourne sans rien casser
        assert sup.etat(SLUG, "une").etat == PRET
        await sup.fermer()
        assert await attendre_mort(a.pid) and await attendre_mort(b.pid)
        assert {i.etat for i in sup.lister()} == {ARRETE}

    asyncio.run(scenario())
