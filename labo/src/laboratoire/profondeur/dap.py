"""DAP — Depth Any Panorama (Insta360 Research, 2025), un modèle de profondeur qui travaille sur le **panorama entier** (ERP 512×1024).

Licence du code et des poids : CC BY-NC 4.0 (usage non commercial). Le code d'inférence n'est pas un paquet : on le clone au premier usage
(`DAP_DIR`, par défaut `~/work/DAP`) et on prend les poids sur Hugging Face (`Insta360-Research/DAP-weights`, fichier `model.pth`).

Rend, pour un panorama, `q` (inverse de la distance radiale, en 1/m) et le masque que le modèle juge valide (hors ciel).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

DEPOT = "https://github.com/Insta360-Research-Team/DAP"
POIDS = ("Insta360-Research/DAP-weights", "model.pth")
LARGEUR, HAUTEUR = 1024, 512
METRES_PAR_UNITE = 100.0  # la sortie du modèle est en centaines de mètres (le script d'origine affiche « 100m » pour 1,0)


class Dap:
    nom, metrique, licence = "dap", True, "CC-BY-NC-4.0"
    panorama = True  # prend le panorama entier, pas une vue en perspective

    def __init__(self) -> None:
        self._modele, self._appareil = None, "cpu"

    def charger(self, appareil: str) -> None:
        import torch
        from huggingface_hub import hf_hub_download

        dossier = Path(os.environ.get("DAP_DIR", "~/work/DAP")).expanduser()
        if not (dossier / "networks").is_dir():
            subprocess.run(["git", "clone", "--depth", "1", DEPOT, str(dossier)], check=True, capture_output=True)  # noqa: S603,S607
        chemin_poids = hf_hub_download(*POIDS)
        sys.path.insert(0, str(dossier))
        ancien = os.getcwd()
        os.chdir(dossier)  # le dépôt cherche son backbone par un chemin relatif
        try:
            from networks.models import make

            m = make({"name": "dap", "args": {"midas_model_type": "vitl", "fine_tune_type": "hypersim", "min_depth": 0.01, "max_depth": 1.0, "train_decoder": True}})
        finally:
            os.chdir(ancien)
        etat = torch.load(chemin_poids, map_location=appareil)
        etat = {(k[7:] if k.startswith("module.") else k): v for k, v in etat.items()}
        propres = m.state_dict()
        manquantes = [k for k in propres if k not in etat]
        if len(manquantes) > 0.2 * len(propres):
            raise RuntimeError(f"poids DAP inattendus : {len(manquantes)} paramètres sur {len(propres)} absents")
        m.load_state_dict({k: v for k, v in etat.items() if k in propres}, strict=False)
        self._modele, self._appareil = m.to(appareil).eval(), appareil

    def predire(self, rgb: np.ndarray, fov: float):  # pragma: no cover - un modèle de panorama ne regarde pas de vues
        raise NotImplementedError("DAP prend le panorama entier : predire_panorama")

    def predire_panorama(self, erp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """erp (H, W, 3) uint8 → (q (h, w) float32, masque (h, w) bool), en projection équirectangulaire."""
        import torch
        from PIL import Image

        image = np.asarray(Image.fromarray(erp).resize((LARGEUR, HAUTEUR), Image.BICUBIC), np.float32) / 255.0
        x = torch.from_numpy(image.transpose(2, 0, 1)).unsqueeze(0).to(self._appareil)
        with torch.inference_mode():
            sortie = self._modele(x)
        profondeur = sortie["pred_depth"][0].detach().float().cpu().squeeze().numpy() * METRES_PAR_UNITE
        masque = np.ones(profondeur.shape, bool)
        if "pred_mask" in sortie:
            masque = (1 - sortie["pred_mask"][0].detach().float().cpu().squeeze().numpy()) > 0.5
        masque &= np.isfinite(profondeur) & (profondeur > 0.01)
        q = 1.0 / np.maximum(profondeur, 0.01)
        return q.astype(np.float32), masque
