"""Les gardiens : des contrôles en code, qui regardent sans modèle.

Un processus à part (`python -m mcp_gateway.gardiens`), lancé par
`install/atelier-init.sh` comme le relais LLM, parce qu'un gardien ne vit pas
dans ce qu'il garde (`docs/vision/gardiens.md`, décision J-a).

Ce paquet ne doit rien importer de lourd à son chargement : le hook
`PreToolUse` du socle (`garde_bash`) en fait partie et part à chaque commande
Bash d'un agent.
"""
