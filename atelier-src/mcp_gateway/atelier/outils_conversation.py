"""Les verbes de l'Atelier, offerts à un client MCP distant.

La passerelle donnait déjà accès au pool : un client distant pouvait appeler
les outils de tous les connecteurs du pod. Il ne pouvait rien faire de
l'Atelier lui-même — ni voir ses conversations, ni en ouvrir une, ni y
envoyer un tour, ni répondre à une autorisation. Autrement dit il voyait *à
travers* l'Atelier sans jamais le voir *lui*.

Ce module ferme cet écart, et rien de plus. Il ne réimplémente aucune règle :
il appelle les mêmes magasins que les routes `/v1`, dans le même processus.
Ce que l'un fait, l'autre le voit — une conversation ouverte d'ici s'affiche
dans l'onglet comme n'importe quelle autre, et c'est le but : qu'on puisse la
reprendre à la main sans rien défaire.

**Un tour ne se joue pas dans un appel d'outil.** `store.send` rend la main
quand le tour est fini, ce qui peut prendre quarante-cinq minutes ; un client
MCP aurait lâché depuis longtemps. Les verbes vont donc par deux : `envoyer`
part et rend la main aussitôt, `suivre` dit ce qui s'est produit depuis. Le
journal du tour reste la vérité ; ce qu'on garde ici n'est qu'une fenêtre sur
le tour en cours.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from mcp_gateway.atelier.decisions import (
    permissions_a_retenir,
    regles_suggerees,
    reponse_autorisee,
    reponse_aux_questions,
    reponse_refusee,
)
from mcp_gateway.atelier.events import AtelierEvent
from mcp_gateway.atelier.harness import FRAGMENTS, REFLEXION

log = logging.getLogger("atelier.outils")

# La conversation dont vient l'appel en cours, telle que sa session MCP la
# déclare (`X-Atelier-Conversation`, posé par la porte `/mcp`). Vide quand
# l'appel ne le dit pas.
CONVERSATION_APPELANTE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "conversation_appelante", default=""
)

# L'appel vient-il d'un client où quelqu'un peut répondre ? Posé par la porte
# `/mcp` : vrai pour un jeton OAuth (un client distant, claude.ai, derrière
# lequel une personne lit), faux pour la clé du propriétaire, celle que portent
# les agents du pod et wikichat — des automates, que personne ne regarde.
# Défaut vrai : l'ancien comportement pour qui ne passe pas par la porte.
APPEL_INTERACTIF: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "appel_interactif", default=True
)

# Les modes qu'un appelant peut demander pour un tour, dans ses mots et dans
# ceux du harnais. `default` est le nom du CLI pour ce que l'Atelier appelle
# `manual`.
MODES_DEMANDABLES = {
    "plan": "plan",
    "default": "manual",
    "manual": "manual",
    "acceptEdits": "acceptEdits",
    "bypassPermissions": "bypassPermissions",
}
BYPASS = "bypassPermissions"

# Ce qu'un `suivre` accepte d'attendre avant de rendre la main, même si rien
# ne bouge. Assez pour qu'une conduite normale n'ait pas à repasser dix fois,
# assez peu pour qu'aucun client ne raccroche : les passerelles coupent
# couramment à soixante secondes.
ATTENTE_MAX_S = 30.0
# Au-delà, on ne garde plus les blocs d'un tour en mémoire. Un tour long en
# produit des milliers ; les retenir tous ferait grossir le service sans fin,
# et le transcript, lui, garde tout.
BLOCS_RETENUS = 400
# Le temps qu'on laisse au tour pour finir sa phrase avant de rendre la main à
# qui suit. Sans ce repos, un `suivre` revient au premier bloc venu et rapporte
# un mot ; avec, il rapporte un paragraphe et un appel d'outil.
REPOS_S = 0.4


@dataclass
class _Suivi:
    """La fenêtre sur un tour : ce qu'il a produit, et s'il est fini."""

    blocs: list[dict[str, Any]] = field(default_factory=list)
    fini: bool = False
    # Le message n'a pas lancé un tour : il attend derrière celui qui
    # travaille. Dire « fini » sans le dire ferait croire à un tour vide.
    en_file: bool = False
    texte: str = ""
    erreur: str = ""
    # Ce qui a déjà été rendu à qui suit. Porté par le tour, pas par
    # l'appel : la même phrase arrivait deux fois quand elle tombait de
    # part et d'autre de deux `suivre` — mesuré sur le pod.
    deja_dit: set[str] = field(default_factory=set)
    demarre_a: float = field(default_factory=time.time)
    reveil: threading.Event = field(default_factory=threading.Event)


def fondre(
    blocs: list[dict[str, Any]], deja_dit: set[str] | None = None
) -> list[dict[str, Any]]:
    """Recolle ce que le flux a débité, sans rien perdre ni rien inventer.

    Mesuré sur le pod : un tour rend son texte jeton par jeton — « pr », « êt »,
    « . » — entrelacé de marqueurs systèmes répétés. Un tour ordinaire produit
    ainsi des centaines de blocs de deux caractères. Rendus tels quels à un
    modèle qui suit, ils coûtent cher et se lisent mal.

    La fonte se fait à la lecture, jamais à l'écriture : le curseur compte
    toujours les blocs bruts, donc suivre deux fois de suite ne rend ni deux
    fois la même chose, ni un morceau en moins.
    """
    fondus: list[dict[str, Any]] = []
    deja_dit = set() if deja_dit is None else deja_dit
    for bloc in blocs:
        dernier = fondus[-1] if fondus else None
        genre = bloc.get("genre")
        # Un bloc qui ne porte ni texte, ni outil, ni cause ne dit rien : la
        # fin d'un outil dont on n'a pas le nom n'apprend rien à qui suit.
        if genre != "fin" and not any(bloc.get(c) for c in ("texte", "outil", "cause")):
            continue
        if genre == "texte":
            texte = bloc.get("texte") or ""
            # La même phrase arrive en bloc complet puis dans la ligne de
            # résultat. Le service tranche déjà ainsi pour le texte qu'il
            # retient : mesuré, « prêt. » revenait trois fois.
            if texte in deja_dit:
                continue
            if dernier is not None and dernier.get("genre") == "texte":
                dernier["texte"] = (dernier.get("texte") or "") + texte
                deja_dit.add(dernier["texte"])
                continue
            deja_dit.add(texte)
        # Les marqueurs systèmes se répètent à l'identique — le premier dit
        # quelque chose, les suivants ne disent que le premier.
        if dernier is not None and genre == "systeme" and bloc == dernier:
            continue
        fondus.append(dict(bloc))
    return fondus


def suivre_ce_bloc(ev: AtelierEvent) -> bool:
    """Ce qu'un spectateur distant a intérêt à recevoir.

    La même phrase arrive trois fois : en fragments pendant qu'elle s'écrit,
    en bloc quand elle est finie, puis dans la ligne de résultat. Le service
    tranche déjà cette question pour le texte qu'il retient (`retenir_le_texte`)
    — on suit la même règle, pour la même raison.

    Mesuré sur le pod avant de la poser : un « prêt. » de six caractères
    arrivait en plus de soixante blocs, dont « pr », « êt » et « . », chacun
    coûtant un aller-retour à qui suit. Le raisonnement en fragments passe
    par le même chemin.
    """
    if ev.raw_type in FRAGMENTS or ev.raw_type in REFLEXION:
        return False
    # Le battement de cœur dit que la connexion vit ; il ne dit rien du tour.
    return ev.kind != "heartbeat"


def _bloc(ev: AtelierEvent) -> dict[str, Any]:
    """Un événement du tour, réduit à ce qu'un modèle distant peut lire."""
    sortie: dict[str, Any] = {"genre": ev.kind}
    for champ, valeur in (
        ("texte", ev.text),
        ("outil", ev.tool),
        ("cause", ev.cause),
    ):
        if valeur:
            sortie[champ] = valeur
    return sortie


class OutilsAtelier:
    """La famille `atelier_*`, branchée sur les magasins du service."""

    def __init__(self, *, store: Any, projects: Any, harness: Any, apps: Any = None) -> None:
        self.store = store
        self.projects = projects
        self.harness = harness
        # Les applications des projets (`apps.service.ServiceApps`) : absentes,
        # les outils `atelier_app*` ne sont pas annoncés.
        self.apps = apps
        self._suivis: dict[str, _Suivi] = {}
        self._verrou = threading.Lock()

    # ── Ce que la passerelle annonce ────────────────────────────────────

    def definitions(self) -> list[dict[str, Any]]:
        conversation = {
            "type": "string",
            "description": "Identifiant de la conversation.",
        }
        return [
            {
                "name": "atelier_projets",
                "description": (
                    "Les projets de l'Atelier : leur slug, leur titre, leur dossier. "
                    "Ce sont les espaces de travail du pod, distincts des projets wikichat."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ranges": {
                            "type": "boolean",
                            "description": "Inclure aussi les projets rangés.",
                        }
                    },
                },
            },
            {
                "name": "atelier_conversations",
                "description": (
                    "Les conversations, la plus récemment active d'abord : état, nombre de "
                    "tours, titre, dernier texte. Filtrer par projet avec `projet`."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "projet": {"type": "string", "description": "Slug du projet."},
                        "limite": {"type": "integer", "description": "Défaut 20."},
                    },
                },
            },
            {
                "name": "atelier_ouvrir",
                "description": (
                    "Ouvre une conversation dans un projet et rend son identifiant. "
                    "Elle apparaît dans l'interface comme toute autre : l'humain peut "
                    "la regarder et reprendre la main à tout moment."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "projet": {"type": "string", "description": "Slug du projet."},
                        "titre": {"type": "string"},
                        "modele": {"type": "string", "description": "Vide = celui du service."},
                    },
                    "required": ["projet"],
                },
            },
            {
                "name": "atelier_envoyer",
                "description": (
                    "Envoie un tour dans une conversation et REND LA MAIN AUSSITÔT : "
                    "un tour peut durer des dizaines de minutes. Le travail commence, "
                    "il ne se termine pas dans cet appel. Utilisez ensuite atelier_suivre "
                    "avec le curseur rendu. Si un tour travaille déjà, le message est mis "
                    "en file et partira à sa suite."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation": conversation,
                        "message": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["plan", "default", "acceptEdits", "bypassPermissions"],
                            "description": (
                                "Mode de permission de ce tour. Vide = celui de la conversation. "
                                "bypassPermissions n'est accepté que si la conversation ou le "
                                "projet l'ont déjà : l'appelant ne peut pas l'accorder seul."
                            ),
                        },
                        "peut_attendre": {
                            "type": "boolean",
                            "description": (
                                "Vrai : une autorisation demandée attend une réponse "
                                "(atelier_suivre la montre, atelier_decider y répond). Faux : "
                                "elle est refusée d'office, et reste visible dans l'interface. "
                                "Défaut : faux pour un agent ou un automate (clé du "
                                "propriétaire), vrai pour un client où quelqu'un lit."
                            ),
                        },
                    },
                    "required": ["conversation", "message"],
                },
            },
            {
                "name": "atelier_suivre",
                "description": (
                    "Ce que le tour a produit depuis `curseur` : textes, outils appelés, "
                    "fin. Rend aussi les autorisations en attente — un tour qui attend "
                    "une réponse ne progresse plus tant qu'on ne lui en donne pas une. "
                    f"`attendre_s` (max {int(ATTENTE_MAX_S)}) laisse l'appel patienter "
                    "qu'il se passe quelque chose plutôt que de rendre une liste vide."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation": conversation,
                        "curseur": {"type": "integer", "description": "Défaut 0."},
                        "attendre_s": {"type": "number"},
                    },
                    "required": ["conversation"],
                },
            },
            {
                "name": "atelier_interrompre",
                "description": "Arrête le tour en cours. Ce qui est écrit reste écrit.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"conversation": conversation},
                    "required": ["conversation"],
                },
            },
            {
                "name": "atelier_transcript",
                "description": (
                    "Le fil d'une conversation, tel qu'il est écrit. `derniers` limite "
                    "aux N derniers caractères — un transcript entier dépasse vite ce "
                    "qu'on peut lire."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "conversation": conversation,
                        "derniers": {"type": "integer", "description": "Défaut 4000."},
                    },
                    "required": ["conversation"],
                },
            },
            {
                "name": "atelier_decider",
                "description": (
                    "Répond à une autorisation demandée par un tour : `allow` ou `deny`. "
                    "Un refus doit porter un `motif` — il revient au modèle, qui le lit. "
                    "`portee` vaut « une_fois » ou « toujours » (retient la règle pour "
                    "cette conversation). Pour une question, donnez `reponses`."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "demande": {"type": "string", "description": "request_id."},
                        "decision": {"type": "string", "enum": ["allow", "deny"]},
                        "motif": {"type": "string"},
                        "portee": {"type": "string", "enum": ["une_fois", "toujours"]},
                        "reponses": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                            "description": "Une entrée par question posée.",
                        },
                    },
                    "required": ["demande", "decision"],
                },
            },
        ] + (self._definitions_apps() if self.apps is not None else [])

    def _definitions_apps(self) -> list[dict[str, Any]]:
        artefact = {
            "projet": {"type": "string", "description": "Slug du projet."},
            "nom": {
                "type": "string",
                "description": "Nom de l'artefact : le dossier artifacts/<nom>/ (minuscules, chiffres, tirets).",
            },
        }
        forcer = {
            "type": "boolean",
            "description": "Agir sur l'artefact d'une autre conversation. À ne passer qu'en connaissance de cause.",
        }
        auteur = {
            "type": "string",
            "description": (
                "Qui agit : ton nom d'agent ($WIKICHAT_AGENT). Inutile quand ta session MCP "
                "porte déjà l'en-tête X-Atelier-Conversation."
            ),
        }
        return [
            {
                "name": "atelier_artefacts",
                "description": (
                    "Les artefacts d'un projet : un dossier artifacts/<nom>/ = une adresse sur l'hôte "
                    "des applications. Rend nom, mode (autonome : fichiers en bac à sable ; serveur : "
                    "processus déclaré par artefact.json), état, adresse, auteur."
                ),
                "inputSchema": {"type": "object", "properties": {"projet": artefact["projet"]}},
            },
            {
                "name": "atelier_artefact_creer",
                "description": (
                    "Crée artifacts/<nom>/ d'un seul geste et refuse un nom déjà pris : aucune "
                    "conversation n'écrit par-dessus une autre. `mode` : autonome (défaut ; déposez-y "
                    "vos fichiers) ou serveur (un artefact.json à compléter est posé : commande avec "
                    "{port}, sante, protocoles)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        **artefact,
                        "mode": {"type": "string", "enum": ["autonome", "serveur"]},
                        "auteur": auteur,
                    },
                    "required": ["projet", "nom"],
                },
            },
            {
                "name": "atelier_artefact_demarrer",
                "description": (
                    "Démarre un artefact serveur et attend qu'il réponde à sa sonde (`attendre`, défaut "
                    "vrai). L'Atelier choisit le port. Refusé sur l'artefact d'une autre conversation "
                    "sans `forcer`."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {**artefact, "attendre": {"type": "boolean"}, "forcer": forcer, "auteur": auteur},
                    "required": ["projet", "nom"],
                },
            },
            {
                "name": "atelier_artefact_arreter",
                "description": "Arrête un artefact serveur (son groupe de processus entier).",
                "inputSchema": {
                    "type": "object",
                    "properties": {**artefact, "forcer": forcer, "auteur": auteur},
                    "required": ["projet", "nom"],
                },
            },
            {
                "name": "atelier_artefact_journal",
                "description": "Les dernières lignes du journal d'un artefact serveur (défaut 200).",
                "inputSchema": {
                    "type": "object",
                    "properties": {**artefact, "lignes": {"type": "integer"}},
                    "required": ["projet", "nom"],
                },
            },
            {
                "name": "atelier_artefact_verifier",
                "description": (
                    "Vérifie les artefact.json d'un projet sans rien lancer : ce qui est valide, ce qui "
                    "ne l'est pas et pourquoi. Avec `nom`, dit aussi si l'artefact tourne et répond à "
                    "sa sonde."
                ),
                "inputSchema": {"type": "object", "properties": artefact, "required": ["projet"]},
            },
            # catalogue: reversible — déjà déclaré par l'équipe F (commandes/existants.py) ;
            # inverse : fermer l'onglet (DELETE /v1/panneau/{conversation}/vues/{id}).
            {
                "name": "atelier_montrer",
                "description": (
                    "Montre une création de ton projet dans le panneau de ta conversation, à côté "
                    "du fil : le panneau s'ouvre seul chez la personne. À appeler dès qu'une page "
                    "ou une application est prête, ou après l'avoir modifiée, au lieu de demander "
                    "d'ouvrir un onglet. `nom` : le dossier artifacts/<nom>/ ; `chemin` : une page "
                    "sous elle (facultatif)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nom": artefact["nom"],
                        "chemin": {"type": "string", "description": "Page sous la création, ex. rapport.html."},
                        "titre": {"type": "string", "description": "Titre de l'onglet (défaut : le nom)."},
                        "projet": {
                            "type": "string",
                            "description": "Slug du projet ; défaut et seule valeur admise : celui de ta conversation.",
                        },
                    },
                    "required": ["nom"],
                },
            },
            # catalogue: reversible — déjà déclaré par l'équipe F (commandes/existants.py) ;
            # sans inverse : le code expire seul en deux minutes, la session en une heure.
            {
                "name": "atelier_navigateur_ouvrir",
                "description": (
                    "Donne à ton navigateur (outils chrome) l'accès aux créations de ton projet, "
                    "pour les vérifier. Rend une adresse d'entrée à usage unique, valable deux "
                    "minutes : ouvre-la aussitôt avec ton outil de navigation. Elle ne vaut que "
                    "pour le projet de ta conversation, jamais pour l'Atelier lui-même."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "projet": {
                            "type": "string",
                            "description": "Slug du projet ; défaut et seule valeur admise : celui de ta conversation.",
                        },
                        "chemin": {
                            "type": "string",
                            "description": "Où arriver, sous le projet : ex. carte/ ou carte/index.html (défaut : l'index).",
                        },
                    },
                },
            },
        ]

    @property
    def noms(self) -> set[str]:
        return {d["name"] for d in self.definitions()}

    # ── Appel ───────────────────────────────────────────────────────────

    async def appeler(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Le résultat au format MCP, ou None si ce nom n'est pas à nous."""
        gestionnaire = getattr(self, f"_outil_{nom[len('atelier_'):]}", None)
        if not nom.startswith("atelier_") or gestionnaire is None:
            return None
        try:
            resultat = gestionnaire(arguments or {})
            if inspect.isawaitable(resultat):
                resultat = await resultat
            return _rendre(resultat)
        except _Refus as refus:
            return _rendre({"erreur": str(refus)}, erreur=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("outil %s", nom)
            return _rendre({"erreur": f"{type(exc).__name__}: {exc}"}, erreur=True)

    # ── Les verbes ──────────────────────────────────────────────────────

    def _outil_projets(self, args: dict[str, Any]) -> Any:
        ranges = bool(args.get("ranges"))
        projets = self.projects.list_projects(include_archived=ranges)
        return {
            "projets": [
                {
                    "slug": p.slug,
                    "titre": getattr(p, "title", "") or p.slug,
                    "genre": getattr(p, "kind", ""),
                    "range": bool(getattr(p, "archived", False)),
                }
                for p in projets
            ]
        }

    def _outil_conversations(self, args: dict[str, Any]) -> Any:
        projet = (args.get("projet") or "").strip() or None
        limite = max(1, min(int(args.get("limite") or 20), 100))
        fiches = self.store.list_sessions(projet)[:limite]
        return {
            "conversations": [
                {
                    "id": r.session_id,
                    "projet": r.slug,
                    "titre": r.title,
                    "etat": r.state,
                    "tours": r.turns,
                    "modifiee": r.updated_at,
                    "dernier_texte": (r.last_text or "")[:200],
                }
                for r in fiches
            ]
        }

    def _outil_ouvrir(self, args: dict[str, Any]) -> Any:
        projet = (args.get("projet") or "").strip()
        if not projet:
            raise _Refus("projet requis")
        # Un projet doit exister pour qu'on y ouvre un fil. La route de
        # l'interface, elle, crée le dossier à la volée : une faute de frappe
        # y fabriquait un projet fantôme, défaut déjà corrigé côté écran. On
        # ne le réintroduit pas par cette porte. Le projet par défaut du
        # service reste toujours acceptable : il est le point de chute.
        tous = self.projects.list_projects(include_archived=True)
        connus = {p.slug for p in tous}
        connus.add(self.store.settings.default_slug)
        if projet not in connus:
            raise _Refus(
                f"projet inconnu : {projet}. Ceux qui existent : {', '.join(sorted(connus))}"
            )
        # Un projet rangé ne s'affiche plus : une conversation ouverte là est
        # invisible de l'humain. Or tout ce lot tient à ce qu'il puisse
        # regarder et reprendre la main — mesuré sur le pod, où le projet par
        # défaut se trouvait rangé et où quatre conversations ont disparu de
        # la vue sans que rien ne le signale.
        if any(p.slug == projet and getattr(p, "archived", False) for p in tous):
            visibles = sorted(p.slug for p in tous if not getattr(p, "archived", False))
            raise _Refus(
                f"projet rangé : {projet}. Une conversation ouverte là ne s'afficherait "
                "pas ; ressortez le projet, ou choisissez-en un autre — "
                f"{', '.join(visibles) or 'aucun projet visible'}"
            )
        rec = self.store.create(
            slug=projet,
            model=(args.get("modele") or "").strip() or None,
            title=(args.get("titre") or "").strip() or None,
        )
        return {
            "id": rec.session_id,
            "projet": rec.slug,
            "titre": rec.title,
            "dossier": rec.cwd,
            "etat": rec.state,
        }

    def _outil_envoyer(self, args: dict[str, Any]) -> Any:
        identifiant = (args.get("conversation") or "").strip()
        message = args.get("message") or ""
        if not message.strip():
            raise _Refus("message vide")
        rec = self.store.get(identifiant)
        if rec is None:
            raise _Refus(f"conversation inconnue : {identifiant}")
        mode = self._mode_du_tour(rec, args.get("mode"))
        # Qui peut répondre à une autorisation ? Un tour lancé par un automate
        # (wikichat, un agent) attendait indéfiniment une réponse que personne
        # ne donnerait : par défaut, il refuse désormais d'office.
        if isinstance(args.get("peut_attendre"), bool):
            peut_attendre = bool(args["peut_attendre"])
        else:
            peut_attendre = APPEL_INTERACTIF.get()

        suivi = _Suivi()
        with self._verrou:
            self._suivis[identifiant] = suivi

        def au_fil(ev: AtelierEvent) -> None:
            if not suivre_ce_bloc(ev):
                return
            if len(suivi.blocs) < BLOCS_RETENUS:
                suivi.blocs.append(_bloc(ev))
            suivi.reveil.set()

        def jouer() -> None:
            try:
                # Ce canal a un interlocuteur : `atelier_suivre` montre la
                # question, `atelier_decider` y répond. Sans le dire, le tour
                # partait sans interlocuteur — donc en mode bypass, sans jamais
                # rien demander, et `atelier_decider` ne pouvait pas servir.
                # Mesuré sur le pod : une commande Bash s'exécutait sans qu'une
                # seule autorisation soit demandée.
                #
                # La contrepartie tient à celui qui conduit : un tour qui
                # attend n'avance plus. À lui de répondre, ou d'interrompre.
                resultat = self.store.send(
                    identifiant, message, on_event=au_fil, peut_attendre=peut_attendre, mode=mode
                )
                suivi.texte = resultat.text or ""
                # Ce que le tour rend sans passer par le flux — au premier chef
                # la mise en file quand un tour travaille déjà. Sans cela,
                # `envoyer` disait « parti » et `suivre` « fini », sans un
                # bloc : l'appelant en concluait que le tour n'avait rien
                # produit, alors que son message attendait son tour.
                for ev in resultat.events or []:
                    if ev.cause == "message_en_file":
                        suivi.en_file = True
                    if suivre_ce_bloc(ev) and len(suivi.blocs) < BLOCS_RETENUS:
                        suivi.blocs.append(_bloc(ev))
            except Exception as exc:  # noqa: BLE001
                # Le tour meurt dans son fil : sans cette trace, `suivre`
                # dirait « en cours » pour toujours.
                suivi.erreur = f"{type(exc).__name__}: {exc}"
                log.exception("tour distant %s", identifiant)
            finally:
                suivi.fini = True
                suivi.reveil.set()

        threading.Thread(target=jouer, name=f"tour-mcp-{identifiant}", daemon=True).start()
        return {
            "conversation": identifiant,
            "etat": "parti",
            "curseur": 0,
            "mode": mode,
            "peut_attendre": peut_attendre,
            "suite": "atelier_suivre pour voir ce qu'il produit",
        }

    def _mode_du_tour(self, rec: Any, demande: Any) -> str:
        """Le mode du tour : demandé, sinon celui de la conversation, sinon du service.

        Jamais `bypassPermissions` que ni la conversation ni le projet
        n'accordaient : l'appelant ne l'obtient pas en le demandant. Et plus
        de repli silencieux sur le bypass quand personne ne peut répondre —
        c'était le défaut d'un tour sans interlocuteur.
        """
        propre = str(getattr(rec, "permission_mode", "") or "")
        autorise_bypass = propre == BYPASS or _mode_du_projet(getattr(rec, "cwd", "") or "") == BYPASS
        texte = str(demande or "").strip()
        if texte:
            if texte not in MODES_DEMANDABLES:
                raise _Refus(f"mode inconnu : {texte} ({', '.join(sorted(MODES_DEMANDABLES))})")
            voulu = MODES_DEMANDABLES[texte]
            if voulu == BYPASS and not autorise_bypass:
                raise _Refus(
                    "bypassPermissions refusé : ni la conversation ni le projet ne l'accordent. "
                    "Seule la personne peut le régler, dans l'Atelier."
                )
            return voulu
        if propre:
            return propre
        defaut = str(getattr(self.store.settings, "permission_mode", "") or "acceptEdits")
        if defaut == BYPASS and not autorise_bypass:
            return "acceptEdits"
        return defaut

    def _outil_suivre(self, args: dict[str, Any]) -> Any:
        identifiant = (args.get("conversation") or "").strip()
        rec = self.store.get(identifiant)
        if rec is None:
            raise _Refus(f"conversation inconnue : {identifiant}")
        curseur = max(0, int(args.get("curseur") or 0))
        attendre = min(float(args.get("attendre_s") or 0), ATTENTE_MAX_S)

        with self._verrou:
            suivi = self._suivis.get(identifiant)

        limite = time.time() + attendre
        while suivi is not None and attendre > 0:
            if suivi.fini or self._demandes(identifiant):
                break
            if len(suivi.blocs) > curseur:
                # Rendre la main au tout premier bloc rendrait un mot par
                # appel. On laisse au tour le temps de finir sa phrase : ce
                # court repos est ce qui fait la différence entre suivre un
                # travail et le harceler.
                time.sleep(min(REPOS_S, max(0.0, limite - time.time())))
                break
            reste = limite - time.time()
            if reste <= 0:
                break
            suivi.reveil.clear()
            suivi.reveil.wait(min(reste, 1.0))

        bruts = suivi.blocs[curseur:] if suivi else []
        fiche = self.store.get(identifiant)
        sortie: dict[str, Any] = {
            "conversation": identifiant,
            "etat": fiche.state if fiche else "inconnu",
            # Le curseur compte les blocs bruts, pas les fondus : c'est ce qui
            # garantit qu'on ne relit ni ne saute rien d'un appel à l'autre.
            "curseur": (curseur + len(bruts)) if suivi else curseur,
            "blocs": fondre(bruts, suivi.deja_dit if suivi else None),
        }
        demandes = self._demandes(identifiant)
        if demandes:
            sortie["autorisations_attendues"] = demandes
            sortie["note"] = (
                "Le tour attend une réponse et ne progresse plus. "
                "Répondez avec atelier_decider."
            )
        if suivi is not None and suivi.en_file:
            sortie["mis_en_file"] = True
            sortie["note"] = (
                "Un tour travaillait déjà : votre message attend derrière lui et "
                "partira à sa suite. Ce qui se joue en ce moment n'est pas le vôtre."
            )
        if suivi is not None and suivi.fini:
            sortie["fini"] = True
            if suivi.texte:
                sortie["texte"] = suivi.texte
            if suivi.erreur:
                sortie["erreur"] = suivi.erreur
        elif suivi is None:
            # Un tour lancé ailleurs — l'interface, VS Code — n'a pas de
            # fenêtre ici. On rend l'état, pas un flux qu'on n'a pas.
            sortie["note_suivi"] = (
                "Aucun tour lancé depuis ce canal pour cette conversation ; "
                "l'état vient de sa fiche. atelier_transcript pour lire le fil."
            )
        return sortie

    def _outil_interrompre(self, args: dict[str, Any]) -> Any:
        identifiant = (args.get("conversation") or "").strip()
        if self.store.get(identifiant) is None:
            raise _Refus(f"conversation inconnue : {identifiant}")
        rec = self.store.interrupt(identifiant)
        return {"conversation": identifiant, "etat": rec.state}

    def _outil_transcript(self, args: dict[str, Any]) -> Any:
        identifiant = (args.get("conversation") or "").strip()
        if self.store.get(identifiant) is None:
            raise _Refus(f"conversation inconnue : {identifiant}")
        derniers = max(200, min(int(args.get("derniers") or 4000), 40000))
        texte = self.store.transcript_text(identifiant) or ""
        coupe = len(texte) > derniers
        return {
            "conversation": identifiant,
            "tronque": coupe,
            "transcript": texte[-derniers:] if coupe else texte,
        }

    def _outil_decider(self, args: dict[str, Any]) -> Any:
        request_id = (args.get("demande") or "").strip()
        choix = (args.get("decision") or "").strip().lower()
        if choix not in ("allow", "deny"):
            raise _Refus("decision doit valoir allow ou deny")
        registre = self.harness.decisions
        demande = registre.demande(request_id)
        vivante = demande is not None
        if demande is None:
            demande = registre.demande_tracee(request_id)
        if demande is None:
            raise _Refus(f"demande inconnue : {request_id}")

        pour_toujours = (
            demande.genre != "question"
            and choix == "allow"
            and (args.get("portee") or "") == "toujours"
        )
        if demande.genre == "question":
            reponse = reponse_aux_questions(demande, args.get("reponses") or [])
        elif choix == "allow":
            reponse = reponse_autorisee(
                None, permissions_a_retenir(demande) if pour_toujours else None
            )
        else:
            reponse = reponse_refusee(args.get("motif") or "")

        retenues: list[dict[str, Any]] = []
        if pour_toujours:
            for regle in regles_suggerees(demande):
                registre.retenir(regle)
                retenues.append(regle.to_dict())

        repris = registre.repondre(request_id, reponse) if vivante else False
        if not repris:
            registre.clore(request_id)
        return {
            "demande": request_id,
            "decision": choix,
            "regles_retenues": retenues,
            # Faux veut dire que plus aucun tour n'attendait : la décision est
            # prise, mais elle ne débloque rien.
            "tour_repris": repris,
        }

    # ── Les artefacts ───────────────────────────────────────────────────
    #
    # Les mêmes gestes que le panneau « Applications » et les routes
    # `/v1/apps`, sur le même service : ce qu'un agent démarre ici, l'humain
    # le voit démarré là, et peut l'arrêter. Une règle de voisinage en plus :
    # un agent n'agit pas sur l'artefact d'une autre conversation sans
    # `forcer` (voir `ServiceApps.verifier_auteur`).

    def _service_apps(self) -> Any:
        if self.apps is None:
            raise _Refus("les artefacts ne sont pas disponibles ici")
        return self.apps

    @staticmethod
    def _artefact(args: dict[str, Any]) -> tuple[str, str]:
        projet = (args.get("projet") or "").strip()
        nom = (args.get("nom") or "").strip()
        if not projet or not nom:
            raise _Refus("projet et nom requis")
        return projet, nom

    @staticmethod
    def _auteur(args: dict[str, Any]) -> str:
        """La conversation qui appelle : l'en-tête de sa session MCP, sinon ce qu'elle dit."""
        return CONVERSATION_APPELANTE.get() or str(args.get("auteur") or "").strip()

    def _outil_artefacts(self, args: dict[str, Any]) -> Any:
        service = self._service_apps()
        projet = (args.get("projet") or "").strip()
        try:
            fiches = service.lister(projet) if projet else service.lister_tout()
        except LookupError as exc:
            raise _Refus(str(exc)) from None
        return {"hote": service.origine or None, "artefacts": fiches}

    def _outil_artefact_creer(self, args: dict[str, Any]) -> Any:
        service = self._service_apps()
        projet, nom = self._artefact(args)
        try:
            fiche = service.creer(projet, nom, (args.get("mode") or "autonome").strip(), self._auteur(args))
        except (LookupError, ValueError, OSError) as exc:
            raise _Refus(str(exc)) from None
        fiche["suite"] = (
            "Complétez artifacts/%s/artefact.json (commande avec {port}, sante), puis "
            "atelier_artefact_verifier et atelier_artefact_demarrer." % nom
            if fiche["mode"] == "serveur" or (args.get("mode") or "") == "serveur"
            else "Déposez vos fichiers dans artifacts/%s/ : index.html s'ouvre à l'adresse rendue." % nom
        )
        return fiche

    async def _outil_artefact_demarrer(self, args: dict[str, Any]) -> Any:
        service = self._service_apps()
        projet, nom = self._artefact(args)
        attendre = args.get("attendre")
        try:
            fiche = await service.demarrer(
                projet,
                nom,
                attendre=True if attendre is None else bool(attendre),
                auteur=self._auteur(args),
                forcer=bool(args.get("forcer")),
            )
        except (LookupError, ValueError, RuntimeError, PermissionError) as exc:
            raise _Refus(str(exc)) from None
        if fiche.get("etat") == "en_echec":
            # L'échec se lit dans le journal : le rendre évite un aller-retour.
            fiche["journal"] = service.journal(projet, nom, 40)
        return fiche

    async def _outil_artefact_arreter(self, args: dict[str, Any]) -> Any:
        service = self._service_apps()
        projet, nom = self._artefact(args)
        try:
            return await service.arreter(
                projet, nom, auteur=self._auteur(args), forcer=bool(args.get("forcer"))
            )
        except (LookupError, ValueError, RuntimeError, PermissionError) as exc:
            raise _Refus(str(exc)) from None

    def _outil_artefact_journal(self, args: dict[str, Any]) -> Any:
        service = self._service_apps()
        projet, nom = self._artefact(args)
        lignes = max(1, min(int(args.get("lignes") or 200), 2000))
        try:
            return {"projet": projet, "nom": nom, "journal": service.journal(projet, nom, lignes)}
        except (LookupError, ValueError, RuntimeError) as exc:
            raise _Refus(str(exc)) from None

    async def _outil_artefact_verifier(self, args: dict[str, Any]) -> Any:
        import httpx

        from mcp_gateway.atelier.apps.manifeste import lister_artefacts

        service = self._service_apps()
        projet = (args.get("projet") or "").strip()
        try:
            racine = service.racine_projet(projet)
        except LookupError as exc:
            raise _Refus(str(exc)) from None
        valides, erreurs = lister_artefacts(racine)
        sortie: dict[str, Any] = {
            "projet": projet,
            "serveurs": sorted(n for n, m in valides.items() if m is not None and m.service),
            "autonomes": sorted(n for n, m in valides.items() if m is None or not m.service),
            "erreurs": erreurs,
            "hote": service.origine or None,
        }
        nom = (args.get("nom") or "").strip()
        if nom:
            fiche = service.fiche(projet, nom, valides.get(nom), erreurs.get(nom, ""))
            cible = service.superviseur.cible(projet, nom)
            m = valides.get(nom)
            if cible is not None and cible.port and m is not None:
                chemin = m.sante or "/"
                try:
                    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                        r = await client.get(f"http://127.0.0.1:{cible.port}{chemin}")
                    fiche["sonde"] = {"chemin": chemin, "statut": r.status_code}
                except httpx.HTTPError as exc:
                    fiche["sonde"] = {"chemin": chemin, "erreur": str(exc)}
            sortie["artefact"] = fiche
        return sortie

    # ── Panneau et navigateur de l'agent ─────────────────────────────────
    # Les deux outils agissent pour la conversation qui appelle, et elle seule :
    # sans l'en-tête `X-Atelier-Conversation`, ils refusent. Un en-tête n'est
    # pas une preuve (voir `mcp_endpoint`), mais la portée reste bornée au
    # projet de la conversation nommée.

    def _conversation_appelante(self) -> Any:
        conversation = CONVERSATION_APPELANTE.get()
        if not conversation:
            raise _Refus(
                "conversation inconnue : ta session MCP ne porte pas l'en-tête X-Atelier-Conversation"
            )
        rec = self.store.get(conversation)
        if rec is None:
            raise _Refus(f"conversation inconnue : {conversation}")
        return rec

    @staticmethod
    def _projet_de(rec: Any, args: dict[str, Any]) -> str:
        projet = (args.get("projet") or "").strip() or rec.slug
        if projet != rec.slug:
            raise _Refus(
                f"projet refusé : {projet}. Ta conversation appartient au projet {rec.slug}, "
                "et n'agit que sur lui."
            )
        return projet

    def _outil_montrer(self, args: dict[str, Any]) -> Any:
        from mcp_gateway.atelier.panneau import VueInvalide

        service = self._service_apps()
        panneau = getattr(service, "panneau", None)
        if panneau is None:
            raise _Refus("le panneau n'est pas disponible ici")
        rec = self._conversation_appelante()
        projet = self._projet_de(rec, args)
        nom = (args.get("nom") or "").strip()
        try:
            # Une création qui n'existe pas ne s'ouvre pas : on le dit à l'agent
            # plutôt que d'ouvrir chez la personne un onglet sur une page 404.
            service.manifeste(projet, nom)
        except LookupError as exc:
            raise _Refus(str(exc)) from None
        except ValueError:
            pass  # un manifeste invalide se montre quand même : la page le dira
        try:
            vue = panneau.montrer(
                rec.session_id,
                projet=projet,
                nom=nom,
                chemin=str(args.get("chemin") or ""),
                titre=str(args.get("titre") or ""),
            )
        except VueInvalide as exc:
            raise _Refus(str(exc)) from None
        log.info("montrer : agent:%s montre %s/%s", rec.session_id, projet, nom)
        return {"vue": vue, "suite": "Le panneau de la conversation s'ouvre sur cette création."}

    def _outil_navigateur_ouvrir(self, args: dict[str, Any]) -> Any:
        from urllib.parse import quote

        from mcp_gateway.atelier.apps.passage import DUREE_CODE_AGENT_S, PREFIXE_AGENT
        from mcp_gateway.atelier.panneau import VueInvalide, chemin_valide

        service = self._service_apps()
        if not service.expose:
            raise _Refus("pas d'hôte des applications sur cette installation")
        rec = self._conversation_appelante()
        projet = self._projet_de(rec, args)
        try:
            chemin = chemin_valide(str(args.get("chemin") or ""))
        except VueInvalide as exc:
            raise _Refus(str(exc)) from None
        acteur = PREFIXE_AGENT + rec.session_id
        try:
            code = service.passage.emettre_code_agent(acteur, projet, f"/{projet}/{chemin}")
        except ValueError as exc:
            raise _Refus(str(exc)) from None
        log.info("navigateur : %s reçoit un code de passage pour %s/%s", acteur, projet, chemin)
        return {
            "adresse": f"{service.origine}/_atelier/entree?code={quote(code, safe='')}",
            "valable_s": DUREE_CODE_AGENT_S,
            "portee": projet,
            "suite": "Ouvre cette adresse maintenant avec ton outil de navigation ; elle ne sert qu'une fois.",
        }

    # ── Outillage ───────────────────────────────────────────────────────

    def _demandes(self, session_id: str) -> list[dict[str, Any]]:
        try:
            demandes = self.harness.decisions.en_attente(session_id)
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "demande": d.request_id,
                "genre": d.genre,
                "outil": d.affichage or d.outil,
                # Ce que le CLI dit lui-même du blocage : la raison d'abord,
                # la description ensuite. Rien n'est déduit ici.
                "pourquoi": (d.raison or d.description or "")[:400],
                "arguments": _abreger(d.arguments),
            }
            for d in demandes
        ]


def _mode_du_projet(cwd: Any) -> str:
    """Le mode par défaut que le projet s'est donné (`.claude/settings.local.json`)."""
    from pathlib import Path

    if not cwd:
        return ""
    try:
        donnees = json.loads((Path(cwd) / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    permissions = donnees.get("permissions") if isinstance(donnees, dict) else None
    return str(permissions.get("defaultMode") or "") if isinstance(permissions, dict) else ""


def _abreger(arguments: Any, taille: int = 300) -> Any:
    """Les arguments de l'outil, assez pour décider, pas de quoi noyer.

    Une autorisation porte parfois le contenu entier d'un fichier. Le rendre
    tel quel coûterait des milliers de jetons pour une question qui se tranche
    sur la commande et son chemin.
    """
    if not isinstance(arguments, dict):
        return {}
    court: dict[str, Any] = {}
    for cle, valeur in arguments.items():
        texte = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False, default=str)
        court[cle] = texte[:taille] + "…" if len(texte) > taille else texte
    return court


class _Refus(Exception):
    """Ce que l'appelant a demandé n'existe pas, ou n'a pas de sens."""


def _rendre(charge: Any, *, erreur: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(charge, ensure_ascii=False, default=str)}],
        "isError": erreur,
    }


__all__ = ["OutilsAtelier", "ATTENTE_MAX_S"]
