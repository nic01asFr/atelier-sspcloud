from __future__ import annotations

from mcp_gateway.catalog import Catalog
from mcp_gateway.meta_tools_defs import META_TOOLS

TOUS_LES_META = frozenset(t["name"] for t in META_TOOLS)


class PlafondDepasse(PermissionError):
    """Un client MCP a demandé un profil plus large que son plafond."""

    def __init__(self, demande: str, plafond: str) -> None:
        self.demande = demande
        self.plafond = plafond
        super().__init__(
            f"Le profil « {demande} » n'est pas accessible depuis une session MCP. "
            f"Profils disponibles ici : {plafond}. Les autres se choisissent depuis "
            f"l'interface, par le propriétaire ; le catalogue en décide avec "
            f"« mcp_ceiling »."
        )


class BundleSession:
    """Bundle actif par session MCP, sous un plafond que le client ne franchit pas.

    Ce fut longtemps « UX, pas plafond sécurité » — et c'était une évasion en
    trois appels : lister les presets, basculer sur le plus large, appeler
    n'importe quel outil. Tous exposés par le profil le plus étroit. Le scénario
    n'est pas celui d'un attaquant mais d'un assistant sous injection de prompt,
    à qui le message d'erreur soufflait la manœuvre.

    Un client peut donc se restreindre — c'est l'usage légitime, ranger son
    contexte — mais jamais ouvrir un serveur ou un méta-outil que son plafond ne
    lui donnait pas. Le propriétaire, lui, passe par l'interface web, qui n'est
    pas soumise au plafond : c'est lui qui le pose.

    Le bundle est aussi mémorisé par *client* : un client MCP qui renégocie sa
    session — ce que fait Claude Code à chaque reconnexion — obtient un nouvel
    identifiant et retombait sinon sur le preset par défaut, perdant le profil
    qu'il venait de choisir. La clé client dérive du jeton porteur, jamais
    stockée en clair (cf. `client_key`).
    """

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._sessions: dict[str, str] = {}
        self._clients: dict[str, str] = {}
        self._session_clients: dict[str, str] = {}

    def get(self, session_id: str | None) -> str:
        if session_id == "web-ui":
            return self._sessions.get("web-ui", self._catalog.default_bundle)
        default = self._catalog.mcp_default_bundle
        if not session_id:
            return default
        return self._sessions.get(session_id, default)

    def mcp_default(self) -> str:
        return self._catalog.mcp_default_bundle

    def set(self, session_id: str, bundle_id: str) -> None:
        if bundle_id not in self._catalog.bundles:
            raise KeyError(f"Unknown bundle: {bundle_id}")
        self._sessions[session_id] = bundle_id
        # Le choix suit le client, pas seulement la session en cours.
        owner = self._session_clients.get(session_id)
        if owner:
            self._clients[owner] = bundle_id

    # ── Plafond ───────────────────────────────────────────────────────────

    def profils_ouverts(self) -> frozenset[str]:
        """Les presets qu'une session MCP peut choisir elle-même.

        Par défaut, ceux que le catalogue destine à l'usage courant
        (`audience: catalog`) : c'est une curation que le propriétaire a déjà
        faite, jusqu'ici lue seulement pour l'affichage. Les presets `advanced`
        — dont `tout`, qui ouvre chaque serveur et chaque méta-outil — restent
        à l'interface. Un catalogue peut en décider autrement avec `mcp_ceiling`.

        Le preset par défaut des sessions MCP y figure toujours : sinon un
        client démarrerait sur un profil qu'il ne peut pas reprendre après en
        avoir changé.
        """
        brut = self._catalog.mcp_ceiling or ""
        if brut.strip():
            noms = {n for n in brut.replace(",", " ").split() if n}
        else:
            noms = {
                nom
                for nom, spec in self._catalog.bundles.items()
                if (spec.audience or "catalog") != "advanced"
            }
        noms.add(self._catalog.mcp_default_bundle)
        return frozenset(n for n in noms if n in self._catalog.bundles)

    def plafond(self) -> str:
        """Ce qu'on nomme dans un refus, pour que l'assistant sache quoi viser."""
        return ", ".join(sorted(self.profils_ouverts()))

    def _ouverture(self, bundle_id: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        """Ce qu'un profil ouvre : serveurs org, serveurs perso, méta-outils.

        Une liste absente ne veut pas dire « rien » mais « tout » — c'est ce que
        font `meta_tools_for_bundle` et `_registry_ids_allowlist`. La confondre
        avec l'ensemble vide ferait passer le profil le plus large pour le plus
        étroit, et le plafond laisserait tout passer.
        """
        spec = self._catalog.bundles.get(bundle_id)
        if spec is None:
            raise KeyError(f"Unknown bundle: {bundle_id}")
        serveurs = frozenset(spec.servers or ())
        registre = (
            frozenset(spec.registry_servers)
            if spec.registry_servers
            else frozenset({"*"})
        )
        metas = (
            frozenset(spec.meta_tools) if spec.meta_tools is not None else TOUS_LES_META
        )
        return serveurs, registre, metas

    def ouverture_maximale(self) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        """Tout ce que les presets atteignables ouvrent, réuni.

        Sert à borner un profil *perso* activé depuis MCP : sans cela, le
        détour est immédiat — créer un profil qui nomme tous les serveurs, puis
        l'activer. Refuser `tout` sans refuser ce détour ne fermerait rien.
        """
        serveurs: set[str] = set()
        registre: set[str] = set()
        metas: set[str] = set()
        for nom in self.profils_ouverts():
            s, r, m = self._ouverture(nom)
            serveurs |= s
            registre |= r
            metas |= m
        return frozenset(serveurs), frozenset(registre), frozenset(metas)

    def ouverture_permise(
        self,
        *,
        serveurs: list[str] | None,
        registre: list[str] | None,
        metas: list[str] | None,
    ) -> bool:
        """Un profil perso tient-il sous le plafond ? `None` vaut « tout »."""
        haut_s, haut_r, haut_m = self.ouverture_maximale()
        veut_s = frozenset(serveurs or ())
        veut_r = frozenset(registre) if registre else frozenset({"*"})
        veut_m = frozenset(metas) if metas is not None else TOUS_LES_META
        if not veut_s <= haut_s:
            return False
        if "*" not in haut_r and not veut_r <= haut_r:
            return False
        return veut_m <= haut_m

    def sous_le_plafond(self, bundle_id: str) -> bool:
        """Ce preset est-il de ceux qu'un client peut choisir ?"""
        return bundle_id in self.profils_ouverts()

    def set_depuis_client(self, session_id: str, bundle_id: str) -> None:
        """Bascule demandée par un client MCP — refusée si elle élargit."""
        if bundle_id not in self._catalog.bundles:
            raise KeyError(f"Unknown bundle: {bundle_id}")
        if not self.sous_le_plafond(bundle_id):
            raise PlafondDepasse(bundle_id, self.plafond())
        self.set(session_id, bundle_id)

    def bind_client(self, session_id: str, client_key: str) -> None:
        """Rattache une session à son client, pour que ses choix lui survivent."""
        if session_id and client_key:
            self._session_clients[session_id] = client_key

    def drop(self, session_id: str) -> bool:
        """Oublie une session terminée (DELETE /mcp)."""
        return self._sessions.pop(session_id, None) is not None

    def remember_for_client(self, client_key: str, bundle_id: str) -> None:
        """Retient le choix pour ce client, au-delà de la session courante."""
        if client_key and bundle_id in self._catalog.bundles:
            self._clients[client_key] = bundle_id

    def restore_for_client(self, client_key: str, session_id: str) -> str | None:
        """Réapplique à une session neuve le dernier bundle choisi par ce client."""
        bundle_id = self._clients.get(client_key or "")
        if bundle_id and session_id:
            self._sessions[session_id] = bundle_id
            return bundle_id
        return None

    def active_server_ids(self, session_id: str | None) -> list[str]:
        bundle_id = self.get(session_id)
        return list(self._catalog.bundles[bundle_id].servers)

    def list_bundles(self) -> list[dict]:
        return [
            {
                "id": b.id,
                "label": b.label,
                "description": b.description,
                "servers": b.servers,
                "meta_tools": b.meta_tools,
                "audience": b.audience,
            }
            for b in self._catalog.bundles.values()
        ]
