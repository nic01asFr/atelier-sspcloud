"""Les profils d'accès de la porte `atelier` : qui reçoit quels outils.

Contrat : `docs/vision/profils-acces.md`. Deux profils :

- `code` : un agent code. Il ne reçoit que les outils de **son** projet : ses
  créations (`atelier_artefact*`), `atelier_montrer` et
  `atelier_navigateur_ouvrir`. Ni méta-outils de la passerelle, ni
  compositions, ni commandes globales, ni « À valider », ni journal, ni suivi
  d'une autre conversation. Le projet vient de la conversation, jamais d'un
  argument : un `projet` différent est refusé, un `projet` absent est rempli ;
- `assistant` : tout l'Atelier, plus les méta-outils de la passerelle.

**Le profil se déduit de la conversation, côté serveur** (`profil_effectif`) :
la porte `/mcp` et `/v1/commandes` lisent `X-Atelier-Conversation`, trouvent
sa fiche, et c'est elle qui décide : une conversation de l'Assistant
(`kind = assistant`, ou un dossier sous celui de l'Assistant) donne
`assistant`, toute autre donne `code`. Pour une conversation connue,
l'en-tête `X-Atelier-Profil` (posé par la déclaration, équipe S) ne peut que
**restreindre**. Pour une conversation inconnue (VS Code, terminal), l'en-tête
décide, `code` par défaut ; `assistant` exige en plus l'absence de
`X-Atelier-Projet` et un `X-Atelier-Dossier` sous le dossier de l'Assistant.
Une valeur inconnue vaut `code`.

Une requête **sans conversation** garde le comportement d'avant (tout, sauf si
elle annonce `code`) : la passerelle et claude.ai entrent par là. Elle est
journalisée (`noter_un_appel_sans_profil`).

Le filtre s'applique à la liste **et** à l'appel : un nom hors profil est
refusé même s'il est connu. La porte et le catalogue l'appliquent
(`mcp_endpoint.py`, `commandes/routes.py`, `catalogue.py`, `mcp/gateway.py`).

Limite : la clé de la porte est celle du propriétaire, que lisent tous les
agents du pod. Un agent qui omet l'en-tête de conversation garde l'accès
complet. Le fermer demande des capacités courtes par conversation, hors de ce
lot.
"""

from __future__ import annotations

import contextvars
import copy
import logging
import re
import threading
from typing import Any, Iterable

log = logging.getLogger("atelier.profils")

ENTETE_PROFIL = "X-Atelier-Profil"
PROFIL_CODE = "code"
PROFIL_ASSISTANT = "assistant"
PROFILS = (PROFIL_CODE, PROFIL_ASSISTANT)

# Le profil annoncé par l'appel en cours ; vide quand l'appel n'en annonce
# aucun (compatibilité : le comportement d'avant les profils).
PROFIL_APPELANT: contextvars.ContextVar[str] = contextvars.ContextVar("profil_appelant", default="")

# Le projet que la déclaration annonce (`X-Atelier-Projet`, écrit par
# l'Atelier dans le `.mcp.json` du projet). Il ne sert qu'à une conversation
# que l'Atelier ne connaît pas (ouverte dans VS Code ou au terminal), et
# seulement en profil `code` : il ne donne jamais `assistant`, et la fiche
# d'une conversation connue l'emporte toujours.
ENTETE_PROJET = "X-Atelier-Projet"
PROJET_ANNONCE: contextvars.ContextVar[str] = contextvars.ContextVar("projet_annonce", default="")
_SLUG_VALIDE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")

# Les créations du projet, puis ce qui les montre. Rien d'autre.
OUTILS_CREATIONS = (
    "atelier_artefacts",
    "atelier_artefact_creer",
    "atelier_artefact_verifier",
    "atelier_artefact_demarrer",
    "atelier_artefact_arreter",
    "atelier_artefact_journal",
)
# La mémoire des conversations de son projet (fiches de projet, A-7) : le
# projet est cadré comme pour les créations.
OUTILS_MEMOIRE_DU_PROJET = ("atelier_rappel", "atelier_fiche")
OUTILS_DU_PROFIL_CODE = frozenset(
    OUTILS_CREATIONS + ("atelier_montrer", "atelier_navigateur_ouvrir") + OUTILS_MEMOIRE_DU_PROJET
)

# Les commandes de conversation d'avant la délégation (lot D) : l'Assistant
# délègue par `atelier_lancer_agent` et suit par `atelier_lancements`. Elles ne
# sont plus **déclarées** à l'Assistant (environ 2 000 unités de schémas par
# requête, `assistant.py`), mais restent **permises** : `gateway_find_tools`
# les trouve, `gateway_call_tool` les appelle, par les mêmes gardes.
HORS_LISTE_ASSISTANT = frozenset({"atelier_envoyer", "atelier_transcript", "atelier_suivre", "atelier_ouvrir"})

# Un identifiant de conversation : celui de l'Atelier ou celui du CLI. Il
# nomme un fichier du magasin ; rien d'autre ne passe.
_CONVERSATION_VALIDE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")

INSTRUCTIONS_CODE = (
    "Serveur de l'Atelier, profil code : les outils de ton projet seulement. "
    "Tes créations (atelier_artefact_*), atelier_montrer pour les montrer dans le "
    "panneau de ta conversation, atelier_navigateur_ouvrir pour les ouvrir dans ton "
    "navigateur, atelier_rappel et atelier_fiche pour retrouver les conversations "
    "passées de ton projet. Le projet est celui de ta conversation : inutile de le passer. "
    "Pour voir ou faire agir un autre projet, écris à ses agents par wikichat."
)


class HorsProfil(Exception):
    """L'appel sort du profil annoncé ; le message dit pourquoi à l'agent."""


def lire_profil(valeur: str | None) -> str:
    """Le profil d'un en-tête : `code`, `assistant`, ou vide s'il n'y en a pas.

    Une valeur présente mais inconnue vaut `code` : se tromper doit
    restreindre, pas ouvrir.
    """
    brut = (valeur or "").strip().lower()
    if not brut:
        return ""
    if brut in PROFILS:
        return brut
    log.warning("profil inconnu %r : traité comme %s", brut[:40], PROFIL_CODE)
    return PROFIL_CODE


def _est_de_l_assistant(store: Any, fiche: Any) -> bool:
    if str(getattr(fiche, "kind", "") or "") == "assistant":
        return True
    racine = getattr(getattr(store, "settings", None), "assistant_root", None)
    cwd = str(getattr(fiche, "cwd", "") or "")
    if not racine or not cwd:
        return False
    try:
        from pathlib import Path

        Path(cwd).resolve().relative_to(Path(racine).resolve())
    except (ValueError, OSError):
        return False
    return True


def est_de_l_assistant(store: Any, fiche: Any) -> bool:
    """Vrai pour la fiche d'une conversation de l'Assistant (le profil `assistant`)."""
    return _est_de_l_assistant(store, fiche)


ENTETE_DOSSIER = "X-Atelier-Dossier"


def dossier_de_l_assistant(store: Any, dossier: str | None) -> bool:
    """Vrai si `dossier` est un dossier existant sous `assistant_root`."""
    from pathlib import Path

    racine = getattr(getattr(store, "settings", None), "assistant_root", None)
    brut = (dossier or "").strip()
    if not racine or not brut:
        return False
    try:
        chemin = Path(brut).resolve()
        chemin.relative_to(Path(racine).resolve())
    except (ValueError, OSError):
        return False
    return chemin.is_dir()


def profil_effectif(
    entete: str | None,
    conversation: str | None,
    store: Any,
    *,
    projet: str | None = None,
    dossier: str | None = None,
) -> str:
    """Le profil de l'appel, décidé par le serveur.

    - Conversation connue : sa fiche décide (`assistant` pour une conversation
      de l'Assistant, `code` sinon) ; l'en-tête ne peut que restreindre.
    - Conversation inconnue (VS Code, terminal, lancement hors de l'app) :
      l'en-tête de profil, `code` par défaut. `assistant` n'est retenu que
      sans `X-Atelier-Projet` et avec un `X-Atelier-Dossier` sous le dossier
      de l'Assistant ; sinon `code`. C'est la confiance qu'on accorde à la
      configuration écrite par l'Atelier, la même que celle de la clé.
    - Sans conversation : l'en-tête seul, et son absence vaut le comportement
      d'avant (vide).
    """
    annonce = lire_profil(entete)
    c = (conversation or "").strip()
    if not c:
        return PROFIL_CODE if annonce == PROFIL_CODE else ""
    fiche = fiche_de_la_conversation(store, c)
    if fiche is None:
        if annonce != PROFIL_ASSISTANT:
            return PROFIL_CODE
        if not (projet or "").strip() and dossier_de_l_assistant(store, dossier):
            return PROFIL_ASSISTANT
        log.warning(
            "conversation inconnue %s : profil assistant annoncé sans le dossier de l'Assistant "
            "(ou avec un projet), code retenu",
            c[:60],
        )
        return PROFIL_CODE
    deduit = PROFIL_ASSISTANT if _est_de_l_assistant(store, fiche) else PROFIL_CODE
    if annonce == PROFIL_CODE:
        return PROFIL_CODE
    if annonce == PROFIL_ASSISTANT and deduit != PROFIL_ASSISTANT:
        log.warning(
            "conversation %s : profil %s annoncé, %s retenu (l'en-tête ne peut pas élargir)",
            c[:60], annonce, deduit,
        )
    return deduit


def profil_courant() -> str:
    return PROFIL_APPELANT.get()


def est_restreint(profil: str | None = None) -> bool:
    """Vrai si le profil borne les outils (aujourd'hui : `code`)."""
    return (profil if profil is not None else profil_courant()) == PROFIL_CODE


def outil_permis(nom: str, profil: str | None = None) -> bool:
    """Ce nom est-il permis au profil ? Sans profil ou en `assistant` : tout."""
    if not est_restreint(profil):
        return True
    return nom in OUTILS_DU_PROFIL_CODE


def message_hors_profil(nom: str) -> str:
    return (
        f"{nom} n'est pas un outil du profil code. Ici : tes créations "
        "(atelier_artefact_*), atelier_montrer, atelier_navigateur_ouvrir, atelier_rappel, "
        "atelier_fiche, pour ton projet seulement. Ce qui touche un autre projet passe par "
        "ses agents, par wikichat."
    )


# ── Les définitions, telles que le profil les annonce ─────────────────────


def _adapter_au_profil_code(definition: dict[str, Any]) -> dict[str, Any]:
    """Le projet et l'auteur viennent de la conversation : le schéma le dit.

    `projet` reste accepté (une consigne écrite avant les profils le passe),
    mais n'est plus requis ; `auteur` disparaît, le serveur ne l'écoute plus.
    """
    d = copy.deepcopy(definition)
    schema = d.get("inputSchema")
    if not isinstance(schema, dict):
        return d
    proprietes = schema.get("properties")
    if isinstance(proprietes, dict):
        proprietes.pop("auteur", None)
        if "projet" in proprietes:
            proprietes["projet"] = {
                "type": "string",
                "description": (
                    "Facultatif : le projet de ta conversation, seule valeur admise ; "
                    "il est pris par défaut."
                ),
            }
    requis = schema.get("required")
    if isinstance(requis, list):
        schema["required"] = [r for r in requis if r not in ("projet", "auteur")]
        if not schema["required"]:
            schema.pop("required")
    return d


def definitions_du_profil(
    definitions: Iterable[dict[str, Any]],
    profil: str | None = None,
    *,
    pour_la_recherche: bool = False,
) -> list[dict[str, Any]]:
    """Les définitions d'outils que ce profil voit, dans la forme qu'il reçoit.

    `pour_la_recherche` : ce que `gateway_find_tools` peut trouver, qui est
    tout ce que le profil permet ; la liste déclarée de l'Assistant, elle, se
    passe de `HORS_LISTE_ASSISTANT`.
    """
    profil = profil if profil is not None else profil_courant()
    liste = [d for d in definitions if isinstance(d, dict)]
    if not est_restreint(profil):
        if profil == PROFIL_ASSISTANT and not pour_la_recherche:
            return [d for d in liste if str(d.get("name") or "") not in HORS_LISTE_ASSISTANT]
        return liste
    return [_adapter_au_profil_code(d) for d in liste if str(d.get("name") or "") in OUTILS_DU_PROFIL_CODE]


# ── La conversation et son projet ─────────────────────────────────────────


def conversation_valide(conversation: str | None) -> str:
    """L'identifiant s'il a la forme d'un identifiant, sinon vide."""
    c = (conversation or "").strip()
    return c if _CONVERSATION_VALIDE.match(c) else ""


def fiche_de_la_conversation(store: Any, conversation: str | None) -> Any | None:
    """La fiche de l'Atelier d'une conversation, par son identifiant ou celui du CLI.

    Dans un tour de l'Atelier, l'en-tête porte l'identifiant de l'Atelier.
    Hors de l'Atelier (VS Code, terminal), il peut porter celui du CLI
    (`CLAUDE_CODE_SESSION_ID`) : une conversation de l'Atelier reprise dans
    VS Code garde le même, noté dans `claude_session_id`.
    """
    c = conversation_valide(conversation)
    if not c or store is None:
        return None
    try:
        rec = store.get(c)
    except (OSError, ValueError):
        rec = None
    if rec is not None:
        return rec
    lister = getattr(store, "list_sessions", None)
    if lister is None:
        return None
    try:
        fiches = lister(include_archived=True)
    except TypeError:
        fiches = lister()
    except (OSError, ValueError):
        return None
    for fiche in fiches:
        if getattr(fiche, "claude_session_id", "") == c:
            return fiche
    return None


def projet_annonce_valide(store: Any, projet: str | None) -> str:
    """Le slug annoncé s'il nomme un dossier existant sous `projects_dir`, sinon vide."""
    slug = (projet or "").strip()
    settings = getattr(store, "settings", None)
    racine = getattr(settings, "projects_dir", None)
    if not slug or racine is None or not _SLUG_VALIDE.match(slug):
        return ""
    # Le slug de l'Assistant désigne son dossier, jamais un projet de code :
    # un `projects/<slug de l'Assistant>` (reste) donnerait à un agent `code`
    # le projet de l'Assistant.
    masque = getattr(settings, "masque_par_l_assistant", None)
    if callable(masque) and masque(slug):
        return ""
    return slug if (racine / slug).is_dir() else ""


def projet_de_la_conversation(store: Any, conversation: str | None, projet_annonce: str | None = None) -> str:
    """Le slug du projet de la conversation ; `HorsProfil` si on ne le sait pas.

    Une conversation connue : le projet de sa fiche, l'en-tête `X-Atelier-Projet`
    ignoré (et un désaccord journalisé). Une conversation inconnue (VS Code, terminal) :
    le projet annoncé, s'il existe. Réservé au profil `code` : seul
    `cadrer_les_arguments` l'appelle, en profil restreint.
    """
    c = (conversation or "").strip()
    if not c:
        raise HorsProfil(
            "profil code : ta session MCP ne nomme pas sa conversation (en-tête "
            "X-Atelier-Conversation), le projet ne peut pas être établi"
        )
    annonce = (projet_annonce or "").strip()
    rec = fiche_de_la_conversation(store, c) if c != "poste" else None
    if rec is None:
        slug = projet_annonce_valide(store, annonce)
        if slug:
            return slug
        if annonce:
            raise HorsProfil(
                f"profil code : projet annoncé inconnu ({annonce[:60]}), le projet ne peut pas être établi"
            )
        raise HorsProfil(
            f"profil code : conversation inconnue de l'Atelier ({c[:60]}), "
            "le projet ne peut pas être établi"
        )
    slug = str(getattr(rec, "slug", "") or "")
    if not slug:
        raise HorsProfil("profil code : cette conversation n'appartient à aucun projet")
    if annonce and annonce != slug:
        log.warning(
            "conversation %s : projet annoncé %s, projet de la fiche %s retenu",
            c[:60], annonce[:60], slug,
        )
    return slug


def cadrer_les_arguments(
    nom: str,
    arguments: dict[str, Any],
    *,
    store: Any,
    conversation: str | None,
    profil: str | None = None,
    projet_annonce: str | None = None,
) -> dict[str, Any]:
    """Les arguments tels que le profil les permet ; `HorsProfil` sinon.

    Hors profil `code`, rien ne change. En `code` : le nom doit être permis,
    et `projet` est celui de la conversation (rempli s'il manque, refusé s'il
    diffère). `auteur` est retiré : c'est la conversation qui agit.
    """
    profil = profil if profil is not None else profil_courant()
    if not est_restreint(profil):
        return arguments
    if nom not in OUTILS_DU_PROFIL_CODE:
        raise HorsProfil(message_hors_profil(nom))
    slug = projet_de_la_conversation(
        store, conversation, projet_annonce if projet_annonce is not None else PROJET_ANNONCE.get()
    )
    cadres = dict(arguments or {})
    demande = str(cadres.get("projet") or "").strip()
    if demande and demande != slug:
        raise HorsProfil(
            f"projet refusé : {demande}. Ta conversation appartient au projet {slug} et "
            "n'agit que sur lui ; pour un autre projet, écris à ses agents par wikichat."
        )
    cadres["projet"] = slug
    cadres.pop("auteur", None)
    return cadres


# ── Journal de compatibilité ──────────────────────────────────────────────

_SANS_PROFIL_VUS: dict[str, float] = {}
_VERROU = threading.Lock()
_SANS_PROFIL_MAX = 2000
_SANS_PROFIL_RAPPEL_S = 600.0


def noter_un_appel_sans_profil(conversation: str, methode: str, *, profil: str = "") -> bool:
    """Journalise un appel qui garde l'accès d'avant les profils.

    Deux cas : un appel sans conversation (tout, par compatibilité : la
    passerelle, claude.ai), ou une conversation qui n'annonce pas encore son
    profil (le profil déduit s'applique quand même). Une ligne par cas et par
    conversation, rappelée au plus toutes les dix minutes. Rend vrai si la
    ligne a été écrite.
    """
    import time

    cle = f"{conversation or '(sans conversation)'}|{profil}"
    maintenant = time.monotonic()
    with _VERROU:
        derniere = _SANS_PROFIL_VUS.get(cle)
        if derniere is not None and maintenant - derniere < _SANS_PROFIL_RAPPEL_S:
            return False
        if len(_SANS_PROFIL_VUS) >= _SANS_PROFIL_MAX:
            _SANS_PROFIL_VUS.clear()
        _SANS_PROFIL_VUS[cle] = maintenant
    if conversation:
        log.warning(
            "porte atelier sans %s (conversation %s, %s) : profil déduit %s",
            ENTETE_PROFIL, conversation[:60], methode or "?", profil or "?",
        )
    else:
        log.warning(
            "porte atelier sans X-Atelier-Conversation (%s) : tous les outils, par compatibilité",
            methode or "?",
        )
    return True


__all__ = [
    "ENTETE_PROFIL",
    "HorsProfil",
    "INSTRUCTIONS_CODE",
    "OUTILS_DU_PROFIL_CODE",
    "PROFIL_APPELANT",
    "PROFIL_ASSISTANT",
    "PROFIL_CODE",
    "cadrer_les_arguments",
    "definitions_du_profil",
    "est_restreint",
    "fiche_de_la_conversation",
    "lire_profil",
    "message_hors_profil",
    "noter_un_appel_sans_profil",
    "outil_permis",
    "profil_courant",
    "profil_effectif",
    "projet_de_la_conversation",
]
