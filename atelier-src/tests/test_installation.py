"""Ce qui s'installe chez un autre ne porte le nom de personne.

L'Atelier doit s'installer sur le pod de n'importe quel utilisateur SSPCloud
et y fonctionner comme chez son auteur — par le chart du catalogue Onyxia
d'abord, par le script sur un Jupyter sinon. Le script, l'image, le chart, la
recette et les scripts de service ne doivent donc citer ni un compte, ni un
pod, ni un chemin propre à une machine ; tout passe par l'environnement. Les
seules mentions admises sont les adresses des dépôts et de l'image publics.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
CHART = RACINE / "charts" / "atelier"
A_INSTALLER = [
    RACINE / "install" / "atelier-init.sh",
    RACINE / "deploy" / "Dockerfile",
    RACINE / "docs" / "installer.md",
    RACINE / "atelier-src" / "bin" / "atelier-relancer",
    RACINE / "atelier-src" / "bin" / "atelier-figer-le-travail.sh",
    *sorted(CHART.rglob("*")),
    *sorted((RACINE / ".github" / "workflows").glob("*.yml")),
]
# Un nom de compte n'est admis que dans l'adresse d'un dépôt ou d'une image
# publics, ou comme mainteneur du chart ; jamais un pod, un hôte ou un chemin
# de machine. `/home/onyxia` est le foyer de l'utilisateur de l'image, pas un
# poste : seul ce qui s'y accroche (hors `work`, le volume) est personnel.
PERSONNEL = re.compile(
    r"nic01asfr(?!/(?:atelier|wikichat|Qgis)|\s*$)|/home/onyxia(?!/work)(?=\S)|user-[a-z0-9]+-proj-",
    re.I,
)


def test_rien_de_personnel_dans_ce_qui_s_installe() -> None:
    fautes: list[str] = []
    for fichier in A_INSTALLER:
        if not fichier.is_file():
            continue
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if PERSONNEL.search(ligne):
                fautes.append(f"{fichier.relative_to(RACINE)}:{numero}: {ligne.strip()[:80]}")
    assert not fautes, chr(10).join(fautes)


def test_les_pieces_de_l_installation_sont_la() -> None:
    for attendu in (
        RACINE / "install" / "atelier-init.sh",
        RACINE / "deploy" / "Dockerfile",
        RACINE / "docs" / "installer.md",
        CHART / "Chart.yaml",
        CHART / "values.yaml",
        CHART / "values.schema.json",
        CHART / "templates" / "statefulset.yaml",
        CHART / "templates" / "ingress.yaml",
        CHART / "templates" / "secret.yaml",
        CHART / "templates" / "pvc.yaml",
        CHART / "templates" / "NOTES.txt",
        RACINE / ".github" / "workflows" / "image.yml",
        RACINE / ".github" / "workflows" / "helm.yml",
    ):
        assert attendu.is_file(), f"{attendu.relative_to(RACINE)} manque"


def test_le_code_du_service_ne_cite_aucun_poste() -> None:
    """Les chemins viennent de `AtelierSettings` et de `$HOME`, jamais d'un poste."""
    fautes: list[str] = []
    for fichier in (RACINE / "atelier-src" / "mcp_gateway").rglob("*.py"):
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if "/home/onyxia" in ligne and "HOME" not in ligne:
                fautes.append(f"{fichier.relative_to(RACINE)}:{numero}")
    assert not fautes, chr(10).join(fautes)


def test_le_script_d_installation_est_du_bash_valide() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash absent du poste")
    for script in (RACINE / "install" / "atelier-init.sh", RACINE / "atelier-src" / "bin" / "atelier-relancer"):
        resultat = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
        assert resultat.returncode == 0, resultat.stderr


def test_le_script_ne_porte_aucun_secret_et_les_attend_de_l_environnement() -> None:
    texte = (RACINE / "install" / "atelier-init.sh").read_text(encoding="utf-8")
    assert not re.search(r"ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}", texte)
    for variable in ("ATELIER_LLM_API_KEY", "ATELIER_OWNER_KEY", "ATELIER_GITHUB_TOKEN", "GIT_USER_EMAIL"):
        assert variable in texte, f"{variable} doit venir de l'environnement"
    assert "openssl rand" in texte, "la clé owner se tire au sort à défaut"
    assert "ATELIER_AVANT_PLAN" in texte, "le conteneur tient l'Atelier au premier plan"


def test_le_chart_dit_a_onyxia_quoi_injecter() -> None:
    """Le formulaire Onyxia remplit l'adresse, la clé du modèle et l'identité git."""
    schema = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
    proprietes = schema["properties"]
    hote = proprietes["ingress"]["properties"]["hostname"]["x-onyxia"]["overwriteDefaultWith"]
    assert hote == "user-{{user.username}}-atelier.{{k8s.domain}}"
    llm = proprietes["llm"]["properties"]
    assert llm["apiKey"]["x-onyxia"]["overwriteDefaultWith"] == "user.profile.aiAssistant.apiKey"
    assert llm["apiKey"]["x-onyxia"]["hidden"] is True, "une clé ne s'affiche pas dans un formulaire"
    assert llm["provider"]["properties"]["apiKey"]["x-onyxia"]["overwriteDefaultWith"] == "{{ai.activeProvider.apiKey}}"
    git = proprietes["git"]["properties"]
    assert git["email"]["x-onyxia"]["overwriteDefaultWith"] == "{{git.email}}"
    assert git["token"]["x-onyxia"]["hidden"] is True


def test_le_pod_recoit_ses_secrets_par_le_secret_pas_par_les_values() -> None:
    statefulset = (CHART / "templates" / "statefulset.yaml").read_text(encoding="utf-8")
    for cle in ("ATELIER_OWNER_KEY", "ATELIER_LLM_API_KEY", "ATELIER_GITHUB_TOKEN"):
        assert cle in statefulset
        bloc = statefulset.split(f"name: {cle}", 1)[1][:200]
        assert "secretKeyRef" in bloc, f"{cle} doit venir d'un Secret"
    assert "mountPath: /home/onyxia/work" in statefulset
    assert "/v1/health" in statefulset, "les sondes visent la santé de l'Atelier"


def test_le_chart_passe_helm_lint_si_helm_est_la() -> None:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm absent du poste")
    resultat = subprocess.run([helm, "lint", str(CHART)], capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
