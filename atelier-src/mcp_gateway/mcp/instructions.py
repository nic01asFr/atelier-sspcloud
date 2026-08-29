"""Consignes MCP (InitializeResult.instructions) depuis le profil actif."""
from __future__ import annotations

from typing import Any

from mcp_gateway.profiles import ResolvedProfile

_MAX_LEN = 12_000


def build_mcp_instructions(
    profile: ResolvedProfile,
    production_compositions: list[dict[str, Any]] | None = None,
    tool_exposure: str = "full",
) -> str:
    parts: list[str] = [
        f"Passerelle — profil actif : {profile.label} ({profile.kind}/{profile.id}).",
    ]
    # Le texte destine au modele, ou la description a defaut : un profil
    # personnel n'ecrit qu'une phrase, qui sert aux deux lecteurs.
    consignes = (profile.mcp_instructions or profile.description).strip()
    if consignes:
        parts.append("")
        parts.append(consignes)

    # En mode découverte, la liste d'outils ne montre qu'une fraction du
    # périmètre : sans cette consigne, l'assistant conclut que le reste n'existe pas.
    if tool_exposure == "discover":
        parts.append("")
        parts.append(
            "IMPORTANT — les outils métier ne sont pas listés ici : la liste ne contient "
            "que le pilotage et les compositions. Pour toute autre action, appelez d'abord "
            "gateway_find_tools en décrivant l'intention (ex. « exporter une carte en PDF »), "
            "puis exécutez l'outil trouvé avec gateway_call_tool en respectant son schéma. "
            "Ne concluez jamais qu'une capacité est absente sans avoir cherché."
        )

    comps = production_compositions or []
    if comps:
        parts.append("")
        parts.append("Compositions en production (outils composition_*) :")
        for c in comps[:20]:
            tool = c.get("tool_name") or f"composition_{c.get('name', '')}"
            desc = (c.get("description") or c.get("name") or tool).strip()
            parts.append(f"- {tool} — {desc}")

    parts.append("")
    parts.append(
        "Pilotage : gateway_status, gateway_list_compositions, gateway_run_composition, "
        "gateway_resume_composition (workflows elicit). "
        "Profils (si exposés) : gateway_list_profiles, gateway_get_profile, gateway_use_profile, "
        "gateway_create_profile, gateway_update_profile. "
        "Consigne aussi via prompt MCP active_profile et ressource profile://active."
    )
    text = "\n".join(parts).strip()
    if len(text) > _MAX_LEN:
        return text[: _MAX_LEN - 3] + "..."
    return text


__all__ = ["build_mcp_instructions"]
