"""Définitions des meta-tools gateway (partagées API / MCP / widget).

`description` s'adresse à l'assistant : quand appeler, avec quoi, ce que
la réponse contient. `summary` s'adresse à la personne devant l'écran :
ce que l'outil fait pour elle, en quelques mots. Les confondre affichait
« Statut gateway : bundle actif, upstreams, version » dans l'interface.
"""
from __future__ import annotations

META_TOOLS = [
    {
        "name": "gateway_list_bundles",
        "summary": "Voir les profils proposés",
        "description": "Liste les presets bundle (lecture, etude_territoire, terrain, ops, createur, tout).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "gateway_use_bundle",
        "summary": "Changer de profil pour cette conversation",
        "description": "Active un preset bundle pour cette session MCP (filtre tools/list).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Identifiant bundle : lecture | etude_territoire | terrain | ops | createur | tout",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "gateway_list_profiles",
        "summary": "Voir vos profils",
        "description": "Liste les profils org (presets institutionnels) et perso, avec le profil actif.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "gateway_get_profile",
        "summary": "Détail d'un profil",
        "description": "Détail d'un profil : consigne MCP, services, compositions en production. Sans argument = profil actif.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "org | custom — optionnel si profil actif",
                    "enum": ["org", "custom"],
                },
                "id": {"type": "string", "description": "Identifiant profil"},
            },
        },
    },
    {
        "name": "gateway_use_profile",
        "summary": "Activer un profil",
        "description": "Active un profil org ou perso (widget + consigne MCP). Profil org : aligne aussi la session MCP courante.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["org", "custom"],
                    "description": "org = preset institutionnel, custom = profil perso",
                },
                "id": {"type": "string", "description": "Identifiant profil"},
            },
            "required": ["kind", "id"],
        },
    },
    {
        "name": "gateway_create_profile",
        "summary": "Créer un profil",
        "description": "Crée un profil perso (services, meta-tools, consigne). Option activate pour l'activer ensuite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nom affiché (requis)"},
                "id": {
                    "type": "string",
                    "description": "Identifiant slug optionnel (sinon dérivé du nom)",
                },
                "description": {
                    "type": "string",
                    "description": "Consigne courte pour l'assistant",
                },
                "org_servers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ids serveurs org catalogue (qgis, compute, wikichat…)",
                },
                "registry_servers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ids connecteurs registre perso (datagouv…)",
                },
                "tool_allowlist": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste blanche d'outils (vide = tous les outils des services)",
                },
                "meta_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Meta-tools gateway autorisés",
                },
                "activate": {
                    "type": "boolean",
                    "description": "Si true, active le profil après création",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "gateway_update_profile",
        "summary": "Modifier un profil",
        "description": "Met à jour un profil perso. Champs omis = inchangés. Option activate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Identifiant profil perso"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "org_servers": {"type": "array", "items": {"type": "string"}},
                "registry_servers": {"type": "array", "items": {"type": "string"}},
                "tool_allowlist": {"type": "array", "items": {"type": "string"}},
                "meta_tools": {"type": "array", "items": {"type": "string"}},
                "activate": {
                    "type": "boolean",
                    "description": "Si true, active le profil après mise à jour",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "gateway_status",
        "summary": "Voir si les services répondent",
        "description": "Statut gateway : bundle actif, upstreams, version.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "gateway_list_compositions",
        "summary": "Voir vos compositions",
        "description": "Liste les compositions enregistrées (SQLite).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filtrer : temporary | production",
                }
            },
        },
    },
    {
        "name": "gateway_save_composition",
        "summary": "Enregistrer un enchaînement pour le refaire plus tard",
        "description": (
            "Enregistre une suite d'appels d'outils sous un nom, pour la rejouer "
            "plus tard sans la redécrire. Utile quand l'utilisateur vient de faire "
            "un travail qui a abouti et souhaite le retrouver : « garde ça sous le "
            "nom cadrage d'étude ». "
            "Écrivez ${input.nom} dans un paramètre pour ce qui devra changer à "
            "chaque exécution — la commune, une date : ces entrées sont déduites, "
            "n'ayez pas à les déclarer. La composition est enregistrée en brouillon ; "
            "elle devient un outil à part entière une fois activée depuis l'écran "
            "Compositions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nom lisible, en langage courant (ex. « Cadrage d'étude »).",
                },
                "description": {
                    "type": "string",
                    "description": "Ce que fait cet enchaînement, en une phrase.",
                },
                "steps": {
                    "type": "array",
                    "description": "Les appels d'outils, dans l'ordre.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Nom de l'étape."},
                            "tool": {"type": "string", "description": "Nom exact de l'outil."},
                            "parameters": {
                                "type": "object",
                                "description": (
                                    "Arguments de l'outil. ${input.x} pour une entrée "
                                    "variable, ${step_<étape>.structured} pour reprendre "
                                    "le résultat d'une étape précédente."
                                ),
                            },
                        },
                        "required": ["tool"],
                    },
                },
            },
            "required": ["name", "steps"],
        },
    },
    {
        "name": "gateway_run_composition",
        "summary": "Lancer une composition",
        "description": "Exécute une composition sync (tool steps) par id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "composition_id": {"type": "string"},
                "inputs": {"type": "object"},
            },
            "required": ["composition_id"],
        },
    },
    {
        "name": "gateway_composition_run_status",
        "summary": "Voir où en est une exécution",
        "description": "Statut d'un run composition (composition_runs).",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "gateway_resume_composition",
        "summary": "Répondre à une composition en attente",
        "description": "Reprend un run composition suspendu (elicit / wait_until).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "response": {"description": "Réponse utilisateur (elicit) ou null (wait_until)"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "gateway_find_tools",
        "summary": "Chercher un outil",
        "description": (
            "Liste ou cherche les outils du profil actif. "
            "Sans argument : inventaire des noms et descriptions, SANS schémas — "
            "un aperçu de ce qui existe. "
            "Avec query, kind ou server : les outils correspondants AVEC leur "
            "inputSchema complet, prêts à l'appel. Décrivez l'intention "
            "(« exporter une carte en PDF ») plutôt qu'un nom d'outil, et groupez "
            "vos besoins en une seule recherche large plutôt qu'en plusieurs. "
            "Exécutez ensuite via gateway_call_tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Intention ou mots-clés. Omis : inventaire complet, sans troncature."
                    ),
                },
                "kind": {
                    "type": "string",
                    "description": "Filtre par nature d'outil.",
                    "enum": ["meta", "upstream", "composition"],
                },
                "server": {
                    "type": "string",
                    "description": "Filtre par service d'origine (qgis, compute, wikichat…).",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum de résultats. Défaut : 10 pour une recherche, "
                        "illimité pour un inventaire."
                    ),
                },
            },
        },
    },
    {
        "name": "gateway_call_tool",
        "summary": "Utiliser un outil",
        "description": (
            "Exécute n'importe quel outil du profil actif, qu'il figure ou non "
            "dans la liste d'outils. Les arguments doivent respecter son "
            "inputSchema, obtenu via gateway_find_tools. En cas d'échec, la "
            "réponse rend le schéma ou des noms proches : corrigez et rappelez, "
            "sans refaire de recherche. Les outils hors du profil sont refusés."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nom exact de l'outil."},
                "arguments": {
                    "type": "object",
                    "description": "Arguments conformes à l'inputSchema de l'outil.",
                },
            },
            "required": ["name"],
        },
    },
]
