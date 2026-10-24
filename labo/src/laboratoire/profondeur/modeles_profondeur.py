"""Les modèles de profondeur qu'on compare. Chacun rend, pour une vue en perspective, `q` (inverse de la distance radiale) et un masque.

`plan` et `contraste` sont des modèles de test, sans GPU ni poids : le premier connaît la géométrie d'un sol plat, le second ne regarde que la
luminosité. Ils servent à vérifier le laboratoire (un bon modèle doit battre le second sur la cohérence).
"""

from __future__ import annotations

import math
from typing import Any, Protocol

import numpy as np

from laboratoire.profondeur import geometrie as g

H_CAMERA_PLAN = 2.0  # mètres, pour le modèle de test « plan »


class ModeleProfondeur(Protocol):
    nom: str
    metrique: bool  # rend des distances en mètres (sinon : relief à une transformation affine près)
    licence: str

    def charger(self, appareil: str) -> None: ...

    def predire(self, rgb: np.ndarray, fov: float) -> tuple[np.ndarray, np.ndarray]:
        """rgb (H, W, 3) uint8 → (q (H, W) float32, masque (H, W) bool)."""


class Plan:
    nom, metrique, licence = "plan", True, "test"

    def charger(self, appareil: str) -> None:
        pass

    def predire(self, rgb: np.ndarray, fov: float) -> tuple[np.ndarray, np.ndarray]:
        h, w = rgb.shape[:2]
        f = (w / 2) / math.tan(math.radians(fov / 2))
        y = np.repeat((np.arange(h) - h / 2 + 0.5)[:, None], w, axis=1)  # vers le bas
        sous_horizon = y > 1.0
        z = H_CAMERA_PLAN * f / np.where(sous_horizon, y, 1.0)
        q = g.vers_q_depuis_z(z.astype(np.float32), fov)
        return np.where(sous_horizon, q, 0.0).astype(np.float32), sous_horizon


class Contraste:
    nom, metrique, licence = "contraste", False, "test"

    def charger(self, appareil: str) -> None:
        pass

    def predire(self, rgb: np.ndarray, fov: float) -> tuple[np.ndarray, np.ndarray]:
        lum = rgb.astype(np.float32).mean(axis=2)
        return lum / 255.0, np.ones(lum.shape, bool)


class PlanPanorama:
    """Test du chemin « panorama entier » : le sol plat, calculé directement en projection équirectangulaire."""

    nom, metrique, licence, panorama = "plan-panorama", True, "test", True

    def charger(self, appareil: str) -> None:
        pass

    def predire_panorama(self, erp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        he, we = erp.shape[:2]
        lat = (0.5 - (np.arange(he) + 0.5) / he) * math.pi
        sous = lat < -0.02
        r = np.where(sous, H_CAMERA_PLAN / np.maximum(-np.sin(lat), 1e-6), 1.0)
        q = np.where(sous, 1.0 / np.maximum(r, 1e-6), 0.0)
        return np.repeat(q[:, None], we, axis=1).astype(np.float32), np.repeat(sous[:, None], we, axis=1)


class Moge2:
    nom, metrique, licence = "moge2", True, "MIT"

    def __init__(self, identifiant: str = "Ruicheng/moge-2-vitl-normal", fov_connu: bool = False) -> None:
        """`fov_connu` : donner à MoGe-2 le champ de vision réel de la vue (ici : celui qu'on a choisi pour la découper du panorama) au lieu de le lui
        faire deviner. L'échelle métrique, elle, reste celle que le modèle prédit : aucun paramètre ne la fixe."""
        self.identifiant, self.fov_connu, self._modele, self._appareil = identifiant, fov_connu, None, "cpu"

    def charger(self, appareil: str) -> None:
        from moge.model.v2 import MoGeModel  # importe torch et moge : seulement quand on l'utilise

        self._appareil = appareil
        self._modele = MoGeModel.from_pretrained(self.identifiant).to(appareil).eval()

    def predire(self, rgb: np.ndarray, fov: float) -> tuple[np.ndarray, np.ndarray]:
        import torch

        x = torch.tensor(rgb / 255.0, dtype=torch.float32, device=self._appareil).permute(2, 0, 1)
        with torch.no_grad():
            sortie = self._modele.infer(x, fov_x=fov) if self.fov_connu else self._modele.infer(x)
        z = sortie["depth"].float().cpu().numpy()
        masque = sortie["mask"].cpu().numpy().astype(bool) & np.isfinite(z) & (z > 0)
        return g.vers_q_depuis_z(np.where(masque, z, 1.0).astype(np.float32), fov), masque


class DepthAnythingV2:
    metrique, licence = False, "Apache-2.0 (small) ; CC-BY-NC-4.0 (base, large)"

    TAILLES = {
        "da2-small": "depth-anything/Depth-Anything-V2-Small-hf",
        "da2-base": "depth-anything/Depth-Anything-V2-Base-hf",
        "da2-large": "depth-anything/Depth-Anything-V2-Large-hf",
    }

    def __init__(self, nom: str = "da2-small") -> None:
        self.nom, self._pipe = nom, None
        self.licence = "Apache-2.0" if nom == "da2-small" else "CC-BY-NC-4.0"

    def charger(self, appareil: str) -> None:
        from transformers import pipeline

        self._pipe = pipeline("depth-estimation", model=self.TAILLES[self.nom], device=0 if appareil.startswith("cuda") else -1)

    def predire(self, rgb: np.ndarray, fov: float) -> tuple[np.ndarray, np.ndarray]:
        import torch
        from PIL import Image

        h, w = rgb.shape[:2]
        sortie = self._pipe(Image.fromarray(rgb))["predicted_depth"]
        d = torch.nn.functional.interpolate(sortie.reshape(1, 1, *sortie.shape[-2:]).float(), size=(h, w), mode="bilinear", align_corners=False)
        disparite = d[0, 0].cpu().numpy().astype(np.float32)
        return g.vers_q_depuis_disparite(disparite, fov), np.ones((h, w), bool)


def modele(nom: str, reglages: dict[str, Any] | None = None) -> ModeleProfondeur:
    reglages = reglages or {}
    if nom == "plan":
        return Plan()
    if nom == "contraste":
        return Contraste()
    if nom == "plan-panorama":
        return PlanPanorama()
    if nom == "moge2":
        return Moge2(str(reglages.get("moge_id", "Ruicheng/moge-2-vitl-normal")), bool(reglages.get("fov_connu", False)))
    if nom in DepthAnythingV2.TAILLES:
        return DepthAnythingV2(nom)
    if nom == "dap":
        from laboratoire.profondeur.dap import Dap

        return Dap()
    raise ValueError(f"modèle de profondeur inconnu : {nom!r} (connus : {sorted(MODELES)})")


MODELES = ("plan", "plan-panorama", "contraste", "moge2", "da2-small", "da2-base", "da2-large", "dap")
