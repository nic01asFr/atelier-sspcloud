"""Le dossier de l'Assistant : ce que l'Atelier y écrit, et le contexte C1 qu'il en tire.

Contrat : `docs/vision/assistant-synthese.md` (A4), `assistant-contexte.md`
(couches C0 à C3), `assistant-role.md` (§3.2 les cinq conditions, §3.5 le bon
de commande), `mesures-vague1.md` (§3, la consigne forte) et `decisions.md`
(A-2, A-6, S6).

Le dossier de l'Assistant (`settings.assistant_root`, `~/work/wikichat-memory`
sur le pod) **n'est pas un dépôt** (S6) : c'est de la mémoire de session. Ses
conversations vivent dans `assistant/sessions/<id>/`, chacune son dossier de
travail. Claude Code lit les `CLAUDE.md` du dossier de travail **et de ses
parents** : le `CLAUDE.md` de la racine vaut donc pour toutes les
conversations, dans l'Atelier, VS Code et au terminal.

Tout est généré ici, rien n'est saisi à la main :

```
wikichat-memory/
├── CLAUDE.md               imports @ de la couche C1, puis `# Compact instructions`
├── atelier/
│   ├── consignes.md        le rôle, court (assistant-role.md)
│   ├── outils.md           méta-outils, consigne forte, délégation
│   ├── carte.md            vue synthétique de la carte (atelier_carte), avant chaque tour
│   └── a-valider.md        « À valider » en cours, avant chaque tour
├── notes/                  le seul endroit où l'Assistant écrit (A-6)
├── .claude/settings.json   refus et autorisations du profil `assistant`
└── assistant/sessions/<id>/.claude/settings.json   la même chose : le CLI ne lit
                            les réglages de projet que dans son dossier de travail
```

Les `.mcp.json` sont ceux de `mcp_sync.configuration_du_profil` (profil
`assistant`), écrits par `lier_le_projet` : ce module n'y touche pas.

Pourquoi des imports `@` et pas le hook `SessionStart` : un import est relu
après compaction, et il n'a pas la coupe à 10 000 caractères du contexte
additionnel d'un hook (`assistant-contexte.md` §3.1). Le hook de wikichat ne
porte que le delta (C2).

`enregistrer_l_assistant(app)` est la ligne à appeler depuis `api.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("atelier.assistant")

# ── Ce qui est écrit ─────────────────────────────────────────────────────────

MARQUE = "<!-- atelier:assistant -->"
DOSSIER_C1 = "atelier"
CONSIGNES = "consignes.md"
OUTILS = "outils.md"
CARTE = "carte.md"
A_VALIDER = "a-valider.md"
FICHIERS_C1 = (CONSIGNES, OUTILS, CARTE, A_VALIDER)
DOSSIER_NOTES = "notes"
REGLAGE_ACCUEIL = "accueil_assistant"

# Un caractère vaut environ 1/3,4 d'unité de modèle (la même estimation que la
# carte, `carte.unites_estimees`).
CARACTERES_PAR_UNITE = 3.4
# Le budget de ce qui est toujours là (C0 et C1), `assistant-synthese.md` §3.
BUDGET_FIXE_UNITES = 20_000
# La part de C1 : consignes, outils, carte au plafond (2 400), « À valider ».
PLAFOND_C1_UNITES = 6_000
PLAFOND_A_VALIDER_CARACTERES = 2_000
# Combien on attend la carte avant un tour : au-delà, le tour part avec la
# carte précédente, qui dit son heure.
DELAI_CARTE_S = 8.0


def unites(texte: str) -> int:
    return int(-(-len(texte) // CARACTERES_PAR_UNITE))


def dossier_c1(settings: Any) -> Path:
    return Path(settings.assistant_root) / DOSSIER_C1


# ── Le gabarit ───────────────────────────────────────────────────────────────


def texte_du_claude_md() -> str:
    """Le `CLAUDE.md` de la racine : les imports, puis la consigne de compaction."""
    imports = "\n".join(f"@{DOSSIER_C1}/{nom}" for nom in FICHIERS_C1)
    return f"""{MARQUE}
<!-- Fichier écrit par l'Atelier, réécrit à chaque démarrage : ne pas l'éditer.
     Pour changer une consigne, proposez-la dans « À valider ». -->
# L'Assistant de l'Atelier

{imports}

{texte_de_compaction()}
"""


def texte_de_compaction() -> str:
    return """# Compact instructions

Le résumé est celui d'une conversation de l'Assistant. Garde :
- chaque demande de la personne et son statut : faite (titre de la carte d'action et son
  identifiant, pour « Annuler »), confiée à un agent (identifiant `lc-…`, projet, ce qui est
  attendu), en attente d'un « Oui » (commande et projet de l'aperçu), en attente de sa réponse ;
- les objets créés ou modifiés, par leur nom ;
- les décisions prises, et les préférences exprimées (pas encore validées) ;
- les questions encore ouvertes, et le canal en cours (écrit ou voix).
Ne garde pas : la carte, « À valider », tes consignes et le mode d'emploi des outils (ils sont
relus après la compaction) ; les résultats d'outils bruts ; les transcripts ; aucun secret."""


def texte_des_consignes() -> str:
    """Le rôle, court (`assistant-role.md` §3.1 à §3.8)."""
    return """# Ton rôle

Tu es l'Assistant de l'Atelier de la personne, sa porte d'entrée. Tu comprends son Atelier :
projets, créations, connecteurs, agents, tâches automatiques et leurs liens. Tu règles ses objets
par les commandes de l'Atelier. Tu confies le travail dans les projets aux agents code, tu le
suis et tu en rends compte.

## Faire toi-même, ou confier

Tu agis toi-même seulement si les cinq conditions sont réunies :
1. une commande de l'Atelier existe pour ce geste ;
2. elle touche un objet de l'Atelier (projet, agent, connecteur, création, tâche automatique),
   pas le contenu d'un projet ;
3. elle tient en quelques appels, sans essai ni erreur ;
4. elle a une inverse (« Annuler ») ;
5. elle dit elle-même si elle a réussi.

Sinon tu confies le travail à un agent code (voir « Confier un travail »). Écrire du code, une
page ou des données, tester, corriger, itérer : toujours un agent.

## Les trois classes d'action, tenues par les commandes

- **réversible** : tu agis ; la commande rend une carte d'action avec « Voir » et « Annuler ».
- **engageante** : la commande rend un aperçu et ne fait rien. Dis-le en une phrase ; la
  personne répond « Oui » à l'écran.
- **réservée** (installer, partager, fusionner, pousser, accorder, supprimer, activer un agent) :
  tu ne peux pas. Dis où la personne le fait : « À valider » ou l'écran d'accord.

Au-delà de trois actions à la suite, présente d'abord un plan.

## Ce que tu ne fais jamais

- écrire dans un projet : tes outils d'écriture ne valent que dans ton dossier `notes/` ;
- accepter une proposition d'« À valider » : tu peux la refuser, avec un motif, jamais
  l'accepter ;
- dire « vérifié » sans preuve (une carte d'action, un état lu par une commande) ;
- demander, lire ou répéter un secret ; aucun accord ne se donne à la voix.

## Un refus n'est pas un résultat

Un appel refusé ou en échec ne s'est **pas** produit. N'annonce jamais un résultat qu'une carte
d'action ou une preuve n'a pas rendu. Dis « refusé » (et pourquoi), ou « en attente de votre
Oui » pour un aperçu. À l'écran, un « fait » ou un « créé » sans carte est marqué « non vérifié ».

## Le ton

- Court, la réponse d'abord, cinq lignes au plus. Une question au plus, avec une réponse
  proposée.
- Ton degré de certitude : « vérifié », « d'après l'agent », « d'après la carte de 14:05 »,
  « je ne sais pas, je regarde ».
- Les mots de l'écran : projet, création, panneau, montrer, brouillon, installer, partager,
  connecteur, autorisation, tâche automatique, gardien, à valider. Jamais : artefact, vue,
  extension, famille, gabarit, composition, MCP, jeton, production.
- Un compte rendu tient en trois lignes : ce qui est fait ; vérifié par quoi ; ce qui revient
  à la personne.
"""


def texte_des_outils() -> str:
    """Le mode d'emploi des méta-outils et la consigne forte (`mesures-vague1.md` §3)."""
    return """# Tes outils

## Chercher avant de conclure

Ne conclus JAMAIS qu'une capacité manque sans avoir cherché : appelle `gateway_find_tools` avec
deux formulations, dont une en anglais. N'appelle `gateway_call_tool` qu'avec un nom exact rendu
par la recherche, et des arguments conformes au schéma rendu.

## Où chercher

- **L'état de l'Atelier** : la carte ci-dessous d'abord. Si elle suffit, réponds sans outil et
  cite son heure. Le détail d'un projet : `atelier_carte(forme="projet", projet="<slug>")`.
- **Les commandes de l'Atelier** (`atelier_*`) sont déclarées : appelle-les par leur nom.
- **Tout le reste** (connecteurs de la personne, wikichat, Onyxia) : `gateway_find_tools`, puis
  `gateway_call_tool(name, arguments)`.
- « Projets » veut dire les projets de l'Atelier (la carte, `atelier_projets`). Le registre de
  wikichat (`list_projects`) est plus large : il compte aussi des dossiers hors de l'Atelier.

| Demande | Commande |
|---|---|
| où en est le projet X | la carte, puis `atelier_carte(forme="projet", projet="x")` |
| crée un projet | `atelier_projet_creer(titre, objectif, gabarit)` : la structure type est posée par la commande |
| quels agents tournent | `atelier_lancements(etat="en_cours")`, `atelier_conversations` |
| relie X et Y | `atelier_projets_lier(projet, vers, type)` |
| qu'est-ce qui attend mon accord | la section « À valider » ci-dessous ; détail : `atelier_a_valider` |
| refuse cette proposition | `atelier_a_valider_refuser(id, motif)` |
| annule | `atelier_annuler(action)`, avec l'identifiant de la carte d'action |
| un agent qui revient chaque lundi | `atelier_agent_creer(...)` : il naît désactivé, la personne l'active |

## Montrer une création

Tu n'as pas de projet à toi et tu n'écris que dans `notes/` : tu ne crées pas de pages. Pour que la
personne voie la création d'un projet : `atelier_montrer(projet, nom)`, le panneau s'ouvre chez elle
sans geste de sa part (il n'existe aucun bouton « exposer »). Pour en faire une, délègue à un agent code,
puis montre-la. `atelier_artefact_verifier(projet, nom)` rend les `avertissements` d'une page (fichier
absent, chemin absolu, ressource externe) : lis-les avant d'annoncer que c'est prêt.

## Confier un travail à un agent code

1. `atelier_lancer_agent(projet, message)`. Le `message` est le bon de commande, en sept
   lignes : objectif ; fini quand ; périmètre (ce projet, en brouillon) ; hors périmètre
   (installer, partager, pousser) ; plafond de durée ; attendu à la fin (`ETAT.md` à jour, un
   message `done`) ; si l'agent est bloqué (une question dans « À décider », puis arrêt).
2. La commande est engageante : le premier appel rend un aperçu et ne lance rien. Résume
   l'aperçu en une phrase. La personne clique « Oui » sur l'aperçu, ou te répond « oui » : alors
   seulement, rappelle la même commande avec les mêmes arguments et `confirmation`.
   Pour un travail qui modifie des fichiers, passe `branche="agent/<sujet>"` (l'agent travaille
   dans une copie, la personne fusionne) ; sans branche, il modifie le projet directement, et
   l'aperçu te le dit.
3. Suis le travail par `atelier_lancements(projet="…")` : en cours, fini, échec, délai, arrêté.
   Ne lis pas le transcript entier.
   Avec `supervise=true`, l'agent te pose ses demandes d'autorisation au lieu d'être refusé : elles
   sont dans `en_attente`. Pour chacune marquée `au_lanceur`, réponds par `atelier_decider(demande,
   decision)` (refuse avec un `motif` si elle sort de sa mission). Celles marquées `pour_la_personne`
   restent posées dans l'Atelier : dis-le, ne cherche pas à les contourner.
4. Rends compte depuis la carte d'action et l'état du lancement, en trois lignes.
"""


def texte_de_la_carte(synthese: dict[str, Any] | None, *, erreur: str = "") -> str:
    """`atelier/carte.md` : la forme synthétique de la carte, datée."""
    if not synthese or not isinstance(synthese.get("texte"), str):
        motif = f" ({erreur})" if erreur else ""
        return (
            "# L'Atelier maintenant\n\n"
            f"La carte n'a pas pu être calculée{motif}. Lis-la par `atelier_carte` avant de "
            "répondre sur l'état de l'Atelier.\n"
        )
    quand = _heure(str(synthese.get("calcule_le") or ""))
    return f"# L'Atelier maintenant (carte de {quand})\n\n{synthese['texte'].strip()}\n"


def texte_d_a_valider(propositions: list[dict[str, Any]] | None, *, erreur: str = "") -> str:
    """`atelier/a-valider.md` : la file « À valider », résumée et bornée."""
    if propositions is None:
        motif = f" ({erreur})" if erreur else ""
        return f"# À valider\n\nLa file n'a pas pu être lue{motif} : `atelier_a_valider`.\n"
    if not propositions:
        return "# À valider\n\nRien n'attend l'accord de la personne.\n"
    tete = f"# À valider ({len(propositions)} en attente)\n\n"
    lignes: list[str] = []
    taille = len(tete)
    for rang, p in enumerate(propositions):
        titre = " ".join(str(p.get("titre") or "sans titre").split())[:140]
        ou = ", ".join(x for x in (str(p.get("source") or ""), str(p.get("projet") or "")) if x)
        ligne = f"- `{p.get('id', '?')}` {titre}" + (f" ({ou})" if ou else "")
        if taille + len(ligne) + 1 > PLAFOND_A_VALIDER_CARACTERES:
            lignes.append(f"- … et {len(propositions) - rang} autres : `atelier_a_valider`.")
            break
        lignes.append(ligne)
        taille += len(ligne) + 1
    return tete + "\n".join(lignes) + "\n\nTu peux refuser (avec un motif), jamais accepter.\n"


def _heure(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
    except ValueError:
        return iso or "?"


# Les outils natifs que le profil refuse. Les trois premiers tiennent la
# frontière (écrire hors de son dossier, simuler une recherche) ; les autres
# ne servent pas l'Assistant, qui délègue par `atelier_lancer_agent`, et
# pesaient 13 000 unités par requête (mesuré sur le pod, CLI 2.1.282 :
# 29 006 unités d'entrée avec eux, 16 015 sans). Un nom qu'une version du CLI
# n'a pas est sans effet.
NATIFS_REFUSES = (
    "Bash",
    "NotebookEdit",
    "WebSearch",
    "Task",
    "Agent",
    "Skill",
    "Workflow",
    "CronCreate",
    "CronDelete",
    "CronList",
    "ScheduleWakeup",
    "EnterWorktree",
    "ExitWorktree",
    "ListAgents",
    "SendMessage",
    "TaskStop",
    "ReportFindings",
    "BashOutput",
    "KillShell",
)


def reglages_du_profil(settings: Any) -> dict[str, Any]:
    """`.claude/settings.json` : ce que le profil `assistant` refuse et laisse passer.

    Les refus l'emportent sur tout mode, bypass compris : c'est le harnais qui
    tient la frontière (`assistant-role.md` §6), pas la consigne. Chemins en
    absolu (`//…`) : les réglages sont copiés dans chaque dossier de
    conversation, où un chemin relatif changerait de sens.
    """
    racine = Path(settings.assistant_root).resolve().as_posix().lstrip("/")
    travail = Path(settings.work_dir).resolve().as_posix().lstrip("/")
    ecrire_permis = f"//{racine}/{DOSSIER_NOTES}/**"
    interdits = [
        f"//{travail}/projects/**",
        f"//{travail}/bin/**",
        f"//{travail}/mcp/**",
        f"//{travail}/sessions/**",
        f"//{travail}/wikichat/**",
        f"//{travail}/.secrets/**",
        f"//{travail}/secrets/**",
        f"//{travail}/.atelier-etat/**",
        f"//{racine}/CLAUDE.md",
        f"//{racine}/{DOSSIER_C1}/**",
        f"//{racine}/.claude/**",
        f"//{racine}/assistant/sessions/*/.claude/**",
        f"//{racine}/**/.mcp.json",
        "~/.claude/**",
        "~/.claude.json",
    ]
    return {
        "permissions": {
            "allow": [
                "Read",
                "Glob",
                "Grep",
                "TodoWrite",
                "mcp__atelier",
                "mcp__wikichat",
                f"Edit({ecrire_permis})",
                f"Write({ecrire_permis})",
            ],
            "deny": [
                *NATIFS_REFUSES,
                *[f"Edit({c})" for c in interdits],
                *[f"Write({c})" for c in interdits],
            ],
        },
    }


# ── L'écriture ───────────────────────────────────────────────────────────────


def _ecrire_si_change(chemin: Path, contenu: str) -> bool:
    try:
        if chemin.is_file() and chemin.read_text(encoding="utf-8") == contenu:
            return False
        chemin.parent.mkdir(parents=True, exist_ok=True)
        provisoire = chemin.with_name(chemin.name + ".tmp")
        provisoire.write_text(contenu, encoding="utf-8")
        provisoire.replace(chemin)
    except OSError as exc:
        log.warning("%s non écrit : %s", chemin, exc)
        return False
    return True


def _json(donnees: dict[str, Any]) -> str:
    return json.dumps(donnees, indent=2, ensure_ascii=False) + "\n"


def dans_le_dossier(settings: Any, cwd: Path | str) -> bool:
    """Le dossier est-il la racine de l'Assistant, ou l'un de ses sous-dossiers ?"""
    try:
        Path(cwd).resolve().relative_to(Path(settings.assistant_root).resolve())
    except (OSError, ValueError):
        return False
    return True


def _retirer_l_ancienne_section(dossier: Path) -> bool:
    """Le bloc que `project_context` écrivait dans le dossier d'une conversation.

    Il disait moins que le `CLAUDE.md` de la racine, qui vaut désormais pour
    toutes les conversations : le garder ferait lire deux consignes.
    """
    from mcp_gateway.atelier.project_context import DEBUT, FIN

    chemin = dossier / "CLAUDE.md"
    try:
        texte = chemin.read_text(encoding="utf-8") if chemin.is_file() else ""
    except OSError:
        return False
    if DEBUT not in texte or FIN not in texte:
        return False
    avant, _, reste = texte.partition(DEBUT)
    _, _, apres = reste.partition(FIN)
    nouveau = (avant.rstrip() + "\n" + apres.lstrip()).strip()
    try:
        if nouveau:
            chemin.write_text(nouveau + "\n", encoding="utf-8")
        else:
            chemin.unlink()
    except OSError:
        return False
    return True


# Ce que `~/.claude.json` doit dire de chaque dossier de l'Assistant (mesuré
# sur le pod, CLI 2.1.282) :
# - `hasTrustDialogAccepted` : sans lui, Claude Code ignore les `allow` du
#   `.claude/settings.json` d'un dossier (« this workspace has not been
#   trusted ») ; chaque commande `atelier_*` était refusée en `-p`, et
#   demandée une à une ailleurs. Les refus (`deny`), eux, valent toujours ;
# - `hasClaudeMdExternalIncludes*` : le `CLAUDE.md` de la racine est lu depuis
#   le dossier d'une conversation (Claude Code remonte les parents), mais ses
#   imports sont hors de ce dossier : sans approbation, ils sont ignorés, et
#   l'Assistant n'a ni sa carte ni ses consignes.
# Les fichiers qu'on approuve ainsi sont tous écrits par l'Atelier.
APPROBATIONS = {
    "hasTrustDialogAccepted": True,
    "hasClaudeMdExternalIncludesApproved": True,
    "hasClaudeMdExternalIncludesWarningShown": True,
}


def approuver_les_imports(dossier: Path) -> bool:
    """Pose `APPROBATIONS` pour ce dossier dans `~/.claude.json`. Rend vrai si le fichier a changé.

    Rien d'autre n'est touché ; un fichier illisible n'est pas écrasé (il porte
    l'identité de la machine et l'historique des projets).
    """
    from mcp_gateway.atelier.mcp_sync import _ecrire_claude_json

    chemin = Path.home() / ".claude.json"
    donnees: dict[str, Any] = {}
    if chemin.is_file():
        try:
            lu = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(lu, dict):
            return False
        donnees = lu
    projets = donnees.setdefault("projects", {})
    if not isinstance(projets, dict):
        return False
    entree = projets.setdefault(str(dossier), {})
    if not isinstance(entree, dict):
        return False
    if all(entree.get(cle) is valeur for cle, valeur in APPROBATIONS.items()):
        return False
    entree.update(APPROBATIONS)
    try:
        _ecrire_claude_json(chemin, donnees)
    except OSError as exc:
        log.warning("dossier de l'Assistant non approuvé (%s) : %s", dossier, exc)
        return False
    return True


def ecrire_le_dossier(settings: Any, dossier_de_session: Path | None = None) -> bool:
    """Pose le gabarit : `CLAUDE.md`, consignes, outils, réglages ; la carte si elle manque.

    Idempotent : rien n'est réécrit quand le contenu est déjà le bon. Un
    `CLAUDE.md` qui n'est pas le nôtre est d'abord mis de côté
    (`CLAUDE.md.avant-atelier`), jamais écrasé en silence. Rend vrai si un
    fichier a changé.
    """
    racine = Path(settings.assistant_root)
    racine.mkdir(parents=True, exist_ok=True)
    change = False
    claude_md = racine / "CLAUDE.md"
    try:
        existant = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
    except OSError:
        existant = ""
    if existant and MARQUE not in existant:
        sauvegarde = racine / "CLAUDE.md.avant-atelier"
        if not sauvegarde.exists():
            try:
                claude_md.replace(sauvegarde)
            except OSError as exc:
                log.warning("CLAUDE.md de l'Assistant non mis de côté : %s", exc)
                return False
    change |= _ecrire_si_change(claude_md, texte_du_claude_md())
    c1 = dossier_c1(settings)
    change |= _ecrire_si_change(c1 / CONSIGNES, texte_des_consignes())
    change |= _ecrire_si_change(c1 / OUTILS, texte_des_outils())
    for nom, defaut in ((CARTE, texte_de_la_carte(None, erreur="pas encore calculée")),
                        (A_VALIDER, texte_d_a_valider(None, erreur="pas encore lue"))):
        if not (c1 / nom).is_file():
            change |= _ecrire_si_change(c1 / nom, defaut)
    (racine / DOSSIER_NOTES).mkdir(parents=True, exist_ok=True)
    reglages = _json(reglages_du_profil(settings))
    dossiers = [racine]
    sessions = Path(settings.assistant_sessions_dir)
    if dossier_de_session is not None:
        dossiers.append(Path(dossier_de_session))
    elif sessions.is_dir():
        dossiers += [
            d for d in sorted(sessions.iterdir()) if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
        ]
    for dossier in dossiers:
        change |= _ecrire_si_change(dossier / ".claude" / "settings.json", reglages)
        if dossier != racine:
            change |= _retirer_l_ancienne_section(dossier)
        # L'approbation vit hors du dossier : elle ne compte pas comme un
        # changement du dossier.
        approuver_les_imports(dossier)
    return change


async def rafraichir(app: Any) -> bool:
    """Réécrit `carte.md` et `a-valider.md` depuis la carte de l'Atelier. Rend vrai si l'un a changé."""
    settings = app.state.settings
    carte = getattr(app.state, "carte", None)
    c1 = dossier_c1(settings)
    if carte is None:
        return False
    try:
        synthese = await carte.forme("synthetique")
        texte_carte = texte_de_la_carte(synthese)
    except Exception as exc:  # noqa: BLE001 — une carte en panne ne bloque pas un tour
        log.info("carte de l'Assistant non calculée : %s", exc)
        texte_carte = texte_de_la_carte(None, erreur=type(exc).__name__)
    try:
        complete = await carte.obtenir()
        sources = complete.get("sources") or {}
        etat = (sources.get("a_valider") or {}).get("etat")
        propositions = complete.get("a_valider") if etat == "ok" else None
        texte_file = texte_d_a_valider(propositions, erreur="" if etat == "ok" else str(etat or "absente"))
    except Exception as exc:  # noqa: BLE001
        texte_file = texte_d_a_valider(None, erreur=type(exc).__name__)
    change = _ecrire_si_change(c1 / CARTE, texte_carte)
    change |= _ecrire_si_change(c1 / A_VALIDER, texte_file)
    return change


# ── Avant un tour, à la création d'une conversation ─────────────────────────

_SOURCE: dict[str, Any] = {}
_VERROU = threading.Lock()


def _rafraichir_depuis_un_fil() -> None:
    """Rafraîchit la carte depuis le fil d'un tour, en attendant au plus `DELAI_CARTE_S`.

    Les tours se jouent dans des fils (route synchrone, flux, outil de
    conversation) ; la carte, elle, se calcule dans la boucle du service. Depuis
    la boucle elle-même, attendre la bloquerait : on garde alors la carte
    précédente, qui porte son heure.
    """
    with _VERROU:
        app = _SOURCE.get("app")
        boucle = _SOURCE.get("boucle")
    if app is None or boucle is None or boucle.is_closed():
        return
    try:
        if asyncio.get_running_loop() is boucle:
            return
    except RuntimeError:
        pass
    try:
        asyncio.run_coroutine_threadsafe(rafraichir(app), boucle).result(timeout=DELAI_CARTE_S)
    except Exception as exc:  # noqa: BLE001 — délai ou panne : la carte d'avant reste
        log.info("carte de l'Assistant gardée telle quelle avant le tour : %s", type(exc).__name__)


def preparer_le_tour(settings: Any, cwd: Path | str) -> bool:
    """Avant un tour d'une conversation de l'Assistant : gabarit, réglages, carte fraîche.

    Appelé par `project_context.ecrire_contexte` pour le dossier de l'Assistant.
    Rien n'est écrit hors de ce dossier. Rend vrai si un fichier a changé.
    """
    if not dans_le_dossier(settings, cwd):
        return False
    ici = Path(cwd).resolve()
    racine = Path(settings.assistant_root).resolve()
    change = ecrire_le_dossier(settings, None if ici == racine else ici)
    _rafraichir_depuis_un_fil()
    return change


def preparer_la_session(settings: Any, cwd: Path | str) -> None:
    """Une conversation d'Assistant qui naît : son dossier reçoit ses réglages tout de suite.

    VS Code et le terminal peuvent l'ouvrir avant qu'un tour de l'Atelier ait
    eu lieu : ils doivent y trouver les mêmes refus.
    """
    if dans_le_dossier(settings, cwd):
        ecrire_le_dossier(settings, Path(cwd))


# ── Le budget ────────────────────────────────────────────────────────────────


def mesurer_c1(settings: Any) -> dict[str, Any]:
    """Ce que pèse la couche C1 telle qu'elle est écrite : par fichier, et au total."""
    racine = Path(settings.assistant_root)
    fichiers = [racine / "CLAUDE.md", *(dossier_c1(settings) / nom for nom in FICHIERS_C1)]
    detail = []
    total_car = 0
    for chemin in fichiers:
        try:
            texte = chemin.read_text(encoding="utf-8")
        except OSError:
            texte = ""
        total_car += len(texte)
        detail.append({"fichier": chemin.relative_to(racine).as_posix(), "caracteres": len(texte),
                       "unites": unites(texte)})
    total = unites("x" * total_car)
    return {
        "fichiers": detail,
        "caracteres": total_car,
        "unites": total,
        "plafond_c1_unites": PLAFOND_C1_UNITES,
        "budget_fixe_unites": BUDGET_FIXE_UNITES,
        "dans_le_plafond": total <= PLAFOND_C1_UNITES,
    }


# ── Le réglage d'accueil ─────────────────────────────────────────────────────


def accueil_sur_l_assistant(settings: Any) -> bool:
    """« Ouvrir l'Atelier sur l'Assistant » : désactivé par défaut pendant la transition (A-3)."""
    from mcp_gateway.atelier.ui_settings import load_ui_settings

    return load_ui_settings(settings).get(REGLAGE_ACCUEIL) is True


def regler_l_accueil(settings: Any, actif: bool) -> bool:
    from mcp_gateway.atelier.ui_settings import save_ui_settings

    # `None` retire la clé : désactivé, c'est l'absence de réglage.
    save_ui_settings(settings, {REGLAGE_ACCUEIL: True if actif else None})
    return accueil_sur_l_assistant(settings)


# ── Les routes et l'enregistrement ───────────────────────────────────────────


class CorpsReglages(BaseModel):
    accueil_assistant: bool


def etat_de_l_assistant(settings: Any) -> dict[str, Any]:
    return {
        "dossier": str(settings.assistant_root),
        "slug": settings.assistant_slug,
        "accueil_assistant": accueil_sur_l_assistant(settings),
        "c1": mesurer_c1(settings),
    }


def construire_le_routeur(app: Any) -> APIRouter:
    from mcp_gateway.atelier.auth import ENTETE_INTERFACE
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
    from mcp_gateway.auth import bearer_from_header

    router = APIRouter(prefix="/v1/assistant")

    def proprietaire(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
        return app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )

    def personne(qui: str = Depends(proprietaire)) -> str:
        # Où s'ouvre l'Atelier est un choix de la personne, à l'écran : la clé
        # du propriétaire, que lisent les agents du pod, ne le change pas.
        if qui != "session":
            raise HTTPException(403, "réglage de la personne, depuis l'interface")
        return qui

    @router.get("")
    def lire(_qui: str = Depends(proprietaire)) -> dict[str, Any]:
        return etat_de_l_assistant(app.state.settings)

    @router.put("/reglages")
    def regler(corps: CorpsReglages, _qui: str = Depends(personne)) -> dict[str, Any]:
        regler_l_accueil(app.state.settings, corps.accueil_assistant)
        return etat_de_l_assistant(app.state.settings)

    @router.post("/rafraichir")
    async def rafraichir_maintenant(_qui: str = Depends(proprietaire)) -> dict[str, Any]:
        await asyncio.to_thread(ecrire_le_dossier, app.state.settings)
        await rafraichir(app)
        return etat_de_l_assistant(app.state.settings)

    return router


class _NoterLaBoucle:
    """Retient la boucle du service au premier passage (démarrage compris).

    Le service a son propre `lifespan` ; un crochet `startup` n'y serait pas
    appelé. Ce mince intermédiaire ASGI note la boucle, puis lance le premier
    calcul de la carte de l'Assistant, et ne fait plus rien ensuite.
    """

    def __init__(self, app: Any, app_atelier: Any) -> None:
        self.app = app
        self.app_atelier = app_atelier

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if _SOURCE.get("app") is not self.app_atelier:
            boucle = asyncio.get_running_loop()
            with _VERROU:
                _SOURCE["app"] = self.app_atelier
                _SOURCE["boucle"] = boucle
            if not getattr(self.app_atelier.state, "use_fake", False):
                boucle.create_task(rafraichir(self.app_atelier))
        await self.app(scope, receive, send)


def enregistrer_l_assistant(app: Any) -> None:
    """Routes, gabarit au démarrage, carte rafraîchie au démarrage et avant chaque tour.

    Pas après chaque action : la carte, invalidée par l'action, se recalcule
    à la lecture suivante ; la recalculer d'office doublerait les appels à
    wikichat et aux gardiens. VS Code et le terminal lisent donc la carte du
    dernier tour de l'Atelier (datée), ou `POST /v1/assistant/rafraichir`.
    """
    settings = app.state.settings
    app.include_router(construire_le_routeur(app))
    try:
        ecrire_le_dossier(settings)
    except OSError as exc:
        log.warning("dossier de l'Assistant non préparé : %s", exc)

    app.add_middleware(_NoterLaBoucle, app_atelier=app)


__all__ = [
    "BUDGET_FIXE_UNITES",
    "FICHIERS_C1",
    "PLAFOND_C1_UNITES",
    "REGLAGE_ACCUEIL",
    "accueil_sur_l_assistant",
    "ecrire_le_dossier",
    "enregistrer_l_assistant",
    "mesurer_c1",
    "preparer_la_session",
    "preparer_le_tour",
    "rafraichir",
    "reglages_du_profil",
    "regler_l_accueil",
    "texte_d_a_valider",
    "texte_de_la_carte",
    "texte_des_consignes",
    "texte_des_outils",
    "texte_du_claude_md",
]
