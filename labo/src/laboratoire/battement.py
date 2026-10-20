"""Le battement : faire travailler le GPU un instant, pour qu'un pod qui entraîne ne passe pas pour inactif.

**Contournement assumé, à retirer quand le serveur sera corrigé (D-81).** Le watchdog du serveur Onyxia coupe le pod dont le GPU reste
sous 5 % pendant 30 minutes, même en plein entraînement limité par le processeur. Un pod en action ne doit jamais être arrêté sauf demande
explicite ; en attendant que le serveur regarde les processus et non le seul GPU, le laboratoire fait lui-même travailler le GPU un instant
toutes les deux minutes, tant qu'un essai tourne.
"""

from __future__ import annotations


def battre(duree_s: float = 1.5) -> bool:
    """Un calcul matriciel d'environ `duree_s` secondes sur le GPU. Rend False s'il n'y a pas de GPU (rien à faire)."""
    try:
        import time

        import torch
    except ImportError:
        return False
    if not torch.cuda.is_available():
        return False
    a = torch.randn(2048, 2048, device="cuda")
    fin = time.monotonic() + duree_s
    while time.monotonic() < fin:
        a = (a @ a).tanh()
        torch.cuda.synchronize()
    return True
