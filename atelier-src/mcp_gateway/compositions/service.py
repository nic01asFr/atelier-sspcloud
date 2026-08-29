from __future__ import annotations

import inspect
import json
import logging
import re
import sqlite3
import uuid
from typing import Any

from mcp_gateway.compositions.executor import (
    CompositionDefinition,
    DurableCompositionExecutor,
    RunState,
    SyncCompositionExecutor,
    ToolCaller,
    new_run_id,
    tool_name_for_composition,
)
from mcp_gateway.compositions.validate import validate_for_promotion
from mcp_gateway.db import log_audit

log = logging.getLogger(__name__)


def _apercu_resultat(resultat: object, limite: int = 130) -> str:
    """Ce qu'une étape a produit, réduit à ce qui tient dans une bannière.

    Une approbation posée seule — « Publier la synthèse ? » — demande de
    trancher sans rien montrer. La question est pourtant toujours *à propos*
    de ce que les étapes précédentes ont produit ; sans cet aperçu, on répond
    au hasard ou l'on va ouvrir l'application pour rien.
    """
    brut: object = resultat
    if isinstance(resultat, dict):
        if resultat.get("image"):
            return "Une image a été produite."
        brut = resultat.get("text")
        donnees = resultat.get("structured")
        # Un outil sérialise souvent son objet dans « text » : on le récupère
        # pour le dire en clair plutôt que de montrer ses accolades.
        if donnees is None and isinstance(brut, str) and brut[:1] in "{[":
            try:
                donnees = json.loads(brut)
            except json.JSONDecodeError:
                donnees = None
        if isinstance(donnees, dict):
            plat = _en_clair(donnees)
            if plat:
                return _borner(plat, limite)
            donnees = None
        if brut is None:
            brut = json.dumps(donnees if donnees is not None else resultat, ensure_ascii=False)
    elif resultat is None:
        return ""

    if not isinstance(brut, str):
        brut = json.dumps(brut, ensure_ascii=False)
    return _borner(brut, limite)


def _en_clair(obj: dict[str, Any]) -> str:
    """Un objet dit en français, sans sa ponctuation de machine.

    On ne garde que les valeurs simples : un sous-objet ne tient pas dans une
    bannière, et le montrer tronqué à mi-accolade renseigne moins que de
    l'omettre. Le détail complet reste dans le panneau du run.
    """
    morceaux = []
    for cle, valeur in obj.items():
        if isinstance(valeur, (dict, list)) or valeur is None:
            continue
        if isinstance(valeur, bool):
            valeur = "oui" if valeur else "non"
        morceaux.append(f"{_lisible(str(cle))} : {valeur}")
    return ", ".join(morceaux)


def _borner(texte: str, limite: int) -> str:
    plat = re.sub(r"\s+", " ", str(texte)).strip()
    if len(plat) > limite:
        plat = plat[: limite - 1].rstrip(" ,;:") + "…"
    return plat


def _apercu_derniere_etape(state_obj: dict[str, Any]) -> dict[str, str] | None:
    """La dernière étape aboutie, nommée et résumée — ou rien à montrer.

    On remonte depuis la fin : c'est presque toujours l'étape qui précède
    immédiatement la question qui la motive.
    """
    resultats = state_obj.get("step_results") or {}
    statuts = state_obj.get("step_status") or {}
    if not isinstance(resultats, dict) or not isinstance(statuts, dict):
        return None
    for sid in reversed(list(resultats)):
        if statuts.get(sid) not in (None, "succeeded"):
            continue
        texte = _apercu_resultat(resultats[sid])
        if texte:
            return {"etape": _lisible(sid), "texte": texte}
    return None


def _lisible(identifiant: str) -> str:
    """Un identifiant technique rendu au langage courant.

    Les noms circulent en snake_case parce que ce sont aussi des noms d'outils
    MCP. Affichés tels quels dans une notification — « publier_apres_accord » —
    ils signalent qu'on lit la plomberie du service plutôt que son propos.
    L'interface web fait déjà cette traduction ; la bannière la doit aussi.
    """
    mots = (identifiant or "").replace("_", " ").replace("-", " ").strip()
    return mots[:1].upper() + mots[1:] if mots else ""


def _single_view(step_result: object) -> object:
    """Une seule représentation du résultat d'étape.

    Le moteur en conserve trois pour le chaînage — `content` (format MCP),
    `text` (sérialisation) et `structured` (objet) — soit trois copies des
    mêmes données. Les renvoyer toutes triplait le poids de la réponse. On
    préfère l'objet, exploitable tel quel, et on retombe sur le texte sinon.
    Le détail complet reste lisible via gateway_composition_run_status.
    """
    if not isinstance(step_result, dict):
        return step_result
    if step_result.get("structured") is not None:
        return step_result["structured"]
    if step_result.get("text"):
        return step_result["text"]
    return step_result.get("content") or step_result


class CompositionService:
    def __init__(self, db: sqlite3.Connection, call_tool: ToolCaller):
        self.db = db
        self._call_tool = call_tool
        self._sync = SyncCompositionExecutor(call_tool)
        self._durable = DurableCompositionExecutor(call_tool)

    def _appelant(self, session_id: str | None):
        """Lie la session à l'appelant d'outils, pour que le garde de profil sache.

        Une étape de composition passait par `internal=True`, qui court-circuite
        le contrôle entièrement : enregistrer une composition appelant
        `compute__exec` puis la lancer suffisait à sortir de son profil. Elle
        s'exécute donc sous celui de qui l'a lancée.

        Tous les appelants ne savent pas recevoir une session — les doubles des
        épreuves n'ont que deux paramètres. On ne la transmet qu'à qui l'accepte,
        plutôt que de faire dépendre le moteur d'une signature.
        """
        if session_id is None:
            return self._call_tool
        try:
            params = inspect.signature(self._call_tool).parameters
        except (TypeError, ValueError):
            return self._call_tool
        variadique = any(
            p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in params.values()
        )
        if len(params) < 3 and not variadique:
            return self._call_tool

        async def lie(nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return await self._call_tool(nom, arguments, session_id)

        return lie

    def bind_call_tool(self, call_tool: ToolCaller) -> None:
        """Rebranche le routeur MCP complet (meta-outils + upstream)."""
        self._call_tool = call_tool
        self._sync = SyncCompositionExecutor(call_tool)
        self._durable = DurableCompositionExecutor(call_tool)

    def list_compositions(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.execute(
                "SELECT * FROM compositions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM compositions ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_summary(dict(r)) for r in rows]

    def get_composition(self, comp_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM compositions WHERE id = ?", (comp_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_detail(dict(row))

    def _load_definition(self, comp_id: str) -> CompositionDefinition:
        row = self.db.execute(
            "SELECT definition_json FROM compositions WHERE id = ?", (comp_id,)
        ).fetchone()
        if not row:
            raise KeyError(comp_id)
        return CompositionDefinition.from_dict(json.loads(row["definition_json"]))

    def create_composition(self, definition: dict[str, Any]) -> dict[str, Any]:
        comp = CompositionDefinition.from_dict(definition)
        if comp.has_suspending_steps():
            comp.validate_durable()
        else:
            comp.validate_sync()
        comp_id = uuid.uuid4().hex[:12]
        self.db.execute(
            """INSERT INTO compositions (id, name, status, definition_json)
               VALUES (?, ?, ?, ?)""",
            (comp_id, comp.name, comp.status, json.dumps(comp.to_dict(), ensure_ascii=False)),
        )
        self.db.commit()
        log_audit(self.db, "composition.create", {"id": comp_id, "name": comp.name})
        return self.get_composition(comp_id)  # type: ignore[return-value]

    def create_from_steps(
        self,
        *,
        nom: str,
        description: str = "",
        etapes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Enregistre un enchaînement décrit par un assistant.

        L'assistant vient d'exécuter ces appels ; il connaît les outils et les
        valeurs. Ce qu'il ne sait pas formuler sans y penser, c'est le schéma
        d'entrée : on le déduit des ${input.x} qu'il a écrits, plutôt que de
        lui demander de le déclarer deux fois et de risquer l'écart.
        """
        etapes = etapes or []
        if not nom.strip():
            raise ValueError("Un nom est nécessaire.")
        if not etapes:
            raise ValueError("Au moins une étape est nécessaire.")

        steps: list[dict[str, Any]] = []
        vus: set[str] = set()
        for i, brute in enumerate(etapes, start=1):
            outil = str(brute.get("tool") or "").strip()
            if not outil:
                raise ValueError(f"Étape {i} : le nom de l'outil manque.")
            libelle = str(brute.get("label") or "").strip() or outil.split("__")[-1]
            step_id = _slug(libelle) or f"etape{i}"
            base = step_id
            n = 2
            while step_id in vus:
                step_id = f"{base}{n}"
                n += 1
            vus.add(step_id)
            steps.append(
                {
                    "step_id": step_id,
                    "label": libelle,
                    "type": "tool",
                    "tool": outil,
                    "parameters": brute.get("parameters") or {},
                }
            )

        entrees = _entrees_referencees(steps)
        definition = {
            "name": nom.strip(),
            "description": description.strip(),
            "status": "temporary",
            "input_schema": {
                "type": "object",
                "properties": {k: {"type": "string", "title": k} for k in entrees},
                "required": sorted(entrees),
            },
            "steps": steps,
        }
        return self.create_composition(definition)

    def update_composition(self, comp_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT status FROM compositions WHERE id = ?", (comp_id,)
        ).fetchone()
        if not row:
            raise KeyError(comp_id)
        comp = CompositionDefinition.from_dict(definition)
        comp.status = str(row["status"])
        if comp.has_suspending_steps():
            comp.validate_durable()
        else:
            comp.validate_sync()
        self.db.execute(
            "UPDATE compositions SET name = ?, definition_json = ? WHERE id = ?",
            (comp.name, json.dumps(comp.to_dict(), ensure_ascii=False), comp_id),
        )
        self.db.commit()
        log_audit(self.db, "composition.update", {"id": comp_id, "name": comp.name})
        return self.get_composition(comp_id)  # type: ignore[return-value]

    def validate(self, comp_id: str, mark: bool = True) -> dict[str, Any]:
        definition = self._load_definition(comp_id)
        if definition.has_suspending_steps():
            definition.validate_durable()
        else:
            definition.validate_sync()
        errors = validate_for_promotion(definition)
        ok = not errors
        if ok and mark:
            definition.status = "validated"
            self.db.execute(
                """UPDATE compositions SET status = ?, definition_json = ?
                   WHERE id = ?""",
                (
                    "validated",
                    json.dumps(definition.to_dict(), ensure_ascii=False),
                    comp_id,
                ),
            )
            self.db.commit()
            log_audit(self.db, "composition.validate", {"id": comp_id})
        return {"ok": ok, "errors": errors, "status": "validated" if ok and mark else None}

    def promote(self, comp_id: str, status: str = "production") -> dict[str, Any]:
        definition = self._load_definition(comp_id)
        if definition.has_suspending_steps():
            definition.validate_durable()
        else:
            definition.validate_sync()
        errors = validate_for_promotion(definition)
        if errors:
            raise ValueError("Promotion refusée : " + "; ".join(errors))
        definition.status = status
        self.db.execute(
            """UPDATE compositions SET status = ?, definition_json = ?, promoted_at = datetime('now')
               WHERE id = ?""",
            (status, json.dumps(definition.to_dict(), ensure_ascii=False), comp_id),
        )
        self.db.commit()
        log_audit(self.db, "composition.promote", {"id": comp_id, "status": status})
        return self.get_composition(comp_id)  # type: ignore[return-value]

    def demote(self, comp_id: str) -> dict[str, Any]:
        """Retire une composition des outils de l'assistant, sans la détruire.

        Activer était jusqu'ici sans retour : pour qu'un assistant cesse de voir
        une composition, il fallait la supprimer — et perdre du même coup sa
        définition et son historique. Elle redescend en « Testé » : elle reste
        là, s'exécute encore depuis l'écran, mais ne figure plus dans les outils.

        La définition n'est pas revalidée : on ne refuse pas de retirer quelque
        chose parce qu'il est devenu invalide, ce serait exactement le moment où
        l'on veut le retirer.
        """
        row = self.db.execute(
            "SELECT status, definition_json FROM compositions WHERE id = ?", (comp_id,)
        ).fetchone()
        if not row:
            raise KeyError(comp_id)
        definition = CompositionDefinition.from_dict(json.loads(row["definition_json"]))
        definition.status = "validated"
        self.db.execute(
            """UPDATE compositions SET status = 'validated', definition_json = ?,
                                       promoted_at = NULL
               WHERE id = ?""",
            (json.dumps(definition.to_dict(), ensure_ascii=False), comp_id),
        )
        self.db.commit()
        log_audit(self.db, "composition.demote", {"id": comp_id})
        return self.get_composition(comp_id)  # type: ignore[return-value]

    def delete_composition(self, comp_id: str) -> bool:
        row = self.db.execute(
            "SELECT id, name FROM compositions WHERE id = ?", (comp_id,)
        ).fetchone()
        if not row:
            return False
        self.db.execute("DELETE FROM composition_runs WHERE composition_id = ?", (comp_id,))
        self.db.execute("DELETE FROM compositions WHERE id = ?", (comp_id,))
        self.db.commit()
        log_audit(self.db, "composition.delete", {"id": comp_id, "name": row["name"]})
        return True

    def promoted_tools(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, name, definition_json FROM compositions WHERE status = 'production'"
        ).fetchall()
        tools: list[dict[str, Any]] = []
        for row in rows:
            definition = CompositionDefinition.from_dict(json.loads(row["definition_json"]))
            tool_name = tool_name_for_composition(row["name"])
            tools.append(
                {
                    "name": tool_name,
                    "description": definition.description or f"Composition: {definition.name}",
                    "inputSchema": definition.input_schema,
                    "_composition_id": row["id"],
                }
            )
        return tools

    def composition_id_for_tool(self, tool_name: str) -> str | None:
        if not tool_name.startswith("composition_"):
            return None
        rows = self.db.execute(
            "SELECT id, name FROM compositions WHERE status = 'production'"
        ).fetchall()
        for row in rows:
            if tool_name_for_composition(row["name"]) == tool_name:
                return row["id"]
        return None

    async def execute(
        self,
        comp_id: str,
        inputs: dict[str, Any] | None = None,
        persist: bool = True,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        definition = self._load_definition(comp_id)
        run_id = new_run_id()
        if persist:
            self._insert_run(run_id, comp_id, "running", RunState(inputs=dict(inputs or {})))

        appelant = self._appelant(session_id)
        if definition.has_suspending_steps():
            outcome = await DurableCompositionExecutor(appelant).run(definition, inputs)
            state = outcome.state
            status = outcome.status
        else:
            state = await SyncCompositionExecutor(appelant).run(definition, inputs)
            status = "failed" if state.error else "completed"

        if persist:
            self._update_run(run_id, status, state)
            log_audit(
                self.db,
                "composition.run",
                {"run_id": run_id, "composition_id": comp_id, "status": status},
            )

        return self._run_result(run_id, comp_id, status, state)

    async def resume(
        self, run_id: str, response: Any, session_id: str | None = None
    ) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM composition_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            raise KeyError(run_id)
        if row["status"] != "suspended":
            raise RuntimeError(f"Run {run_id} n'est pas suspendu (status={row['status']})")

        comp_id = row["composition_id"]
        definition = self._load_definition(comp_id)
        state = RunState.from_dict(json.loads(row["state_json"]))

        self._update_run(run_id, "running", state)
        outcome = await DurableCompositionExecutor(self._appelant(session_id)).resume(
            definition, state, response
        )
        self._update_run(run_id, outcome.status, outcome.state)
        log_audit(
            self.db,
            "composition.resume",
            {"run_id": run_id, "composition_id": comp_id, "status": outcome.status},
        )
        return self._run_result(run_id, comp_id, outcome.status, outcome.state)

    def list_runs(
        self, *, status: str | None = None, limit: int = 30, include_state: bool = False
    ) -> list[dict[str, Any]]:
        """Liste les runs. Par défaut sans state_json (évite de charger des Mo de step_results)."""
        limit = max(1, min(limit, 100))
        # Ne pas SELECT state_json sauf include_state — colonnes lourdes (sorties QGIS).
        cols = (
            "r.id, r.composition_id, r.status, r.created_at, r.updated_at, "
            "c.name AS composition_name"
        )
        if include_state:
            cols += ", r.state_json"
        if status:
            rows = self.db.execute(
                f"""SELECT {cols}
                   FROM composition_runs r
                   JOIN compositions c ON c.id = r.composition_id
                   WHERE r.status = ?
                   ORDER BY r.updated_at DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                f"""SELECT {cols}
                   FROM composition_runs r
                   JOIN compositions c ON c.id = r.composition_id
                   ORDER BY r.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            if include_state:
                raw_state = data.pop("state_json", None)
                data["state"] = json.loads(raw_state) if raw_state else {}
            elif data.get("status") == "suspended":
                # Charger uniquement la suspension pour l'inbox
                raw = self.db.execute(
                    "SELECT state_json FROM composition_runs WHERE id = ?",
                    (data["id"],),
                ).fetchone()
                susp = None
                state_obj: Any = None
                if raw and raw["state_json"]:
                    try:
                        state_obj = json.loads(raw["state_json"])
                        susp = state_obj.get("suspension") if isinstance(state_obj, dict) else None
                    except json.JSONDecodeError:
                        susp = None
                data["state"] = {"suspension": susp} if susp else {}
                # Un aperçu de ce que la composition a produit, pas les
                # résultats : la boîte de réception doit dire sur quoi porte la
                # demande — on n'approuve pas à l'aveugle — sans rapatrier pour
                # autant la sortie d'un rendu cartographique.
                if susp and isinstance(state_obj, dict):
                    apercu = _apercu_derniere_etape(state_obj)
                    if apercu:
                        data["apercu"] = apercu
            else:
                data["state"] = {}
            out.append(data)
        return out

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        # Le nom de la composition accompagne le run : seule la liste le
        # joignait, si bien qu'un run ouvert seul s'affichait sous son
        # identifiant — l'utilisateur cliquait « Zone etude QGIS » et lisait
        # « 968983409ac2 ».
        row = self.db.execute(
            """SELECT r.*, c.name AS composition_name
               FROM composition_runs r
               LEFT JOIN compositions c ON c.id = r.composition_id
               WHERE r.id = ?""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["state"] = json.loads(data.pop("state_json"))
        # Lancer un run et le relire donnaient deux formes différentes du même
        # objet : le lancement renvoie « output », la relecture seulement
        # « state ». L'écran, qui sert les deux chemins, ne trouvait le résultat
        # que dans un cas — et affichait un dépliant technique dans l'autre.
        etapes = list(data["state"].get("step_results") or {})
        derniere = etapes[-1] if etapes else None
        data["output"] = (
            _single_view(data["state"]["step_results"][derniere]) if derniere else None
        )
        data["output_step"] = derniere
        return data

    def _insert_run(
        self, run_id: str, comp_id: str, status: str, state: RunState
    ) -> None:
        self.db.execute(
            """INSERT INTO composition_runs (id, composition_id, status, state_json)
               VALUES (?, ?, ?, ?)""",
            (run_id, comp_id, status, json.dumps(state.to_dict(), ensure_ascii=False)),
        )
        self.db.commit()

    def abandon_run(self, run_id: str, reason: str = "") -> dict[str, Any] | None:
        """Renonce à un run suspendu.

        Sans ce geste, une exécution mise en attente ne peut plus que reprendre :
        elle reste dans la liste des choses à traiter, et dans le compteur, sans
        limite de temps. Quiconque lance une composition par curiosité et tombe
        sur une question qu'il ne comprend pas garde la trace pour toujours.
        """
        row = self.get_run(run_id)
        if not row:
            return None
        if row["status"] not in ("suspended", "running"):
            raise ValueError("Seule une exécution en attente peut être abandonnée.")
        state = RunState.from_dict(row.get("state") or {})
        state.suspension = None
        state.current_step_id = None
        state.error = reason or "Abandonnée."
        self._update_run(run_id, "abandoned", state)
        return self.get_run(run_id)

    def _update_run(self, run_id: str, status: str, state: RunState) -> None:
        precedent = self.db.execute(
            "SELECT status FROM composition_runs WHERE id = ?", (run_id,)
        ).fetchone()
        self.db.execute(
            """UPDATE composition_runs SET status = ?, state_json = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (status, json.dumps(state.to_dict(), ensure_ascii=False), run_id),
        )
        self.db.commit()
        avant = precedent["status"] if precedent else None
        if status == "suspended" and avant != "suspended":
            # Au passage en attente seulement : une exécution reprise puis
            # suspendue de nouveau préviendra, mais une simple réécriture d'état
            # ne doit pas faire sonner le téléphone une seconde fois.
            self._prevenir_attente(run_id, state)
        elif avant == "suspended" and status != "suspended":
            self._clore_attente(run_id, status, state)

    def _clore_attente(self, run_id: str, status: str, state: RunState) -> None:
        """Retirer du téléphone une demande à laquelle on a déjà répondu.

        Une bannière d'approbation reste affichée jusqu'à ce qu'on la touche.
        Si l'exécution s'est terminée entre-temps — reprise depuis un autre
        appareil, abandonnée, expirée — la bannière survit et n'invite plus qu'à
        un geste voué à échouer. C'est exactement ce qui s'est produit à
        l'épreuve : « approuver » sur une demande morte, et un message d'erreur
        pour toute réponse.

        On ne peut pas fermer une notification à distance ; on peut la
        remplacer. Un même `tag` écrase la précédente, donc cet envoi occupe la
        place de la demande et dit ce qu'elle est devenue, sans bouton.
        """
        try:
            from mcp_gateway.notifications import prevenir

            ligne = self.db.execute(
                """SELECT c.name FROM composition_runs r
                   JOIN compositions c ON c.id = r.composition_id
                   WHERE r.id = ?""",
                (run_id,),
            ).fetchone()
            nom = _lisible(ligne["name"] if ligne else "") or "Une composition"
            etat = {
                "completed": "terminée",
                "failed": "échec",
                "abandoned": "abandonnée",
            }.get(status, status)
            corps = {
                "completed": "Terminée.",
                "failed": (state.error or "").strip()[:180] or "L'exécution a échoué.",
                "abandoned": "Demande abandonnée.",
            }.get(status, f"Exécution {status}.")
            prevenir(
                self.db,
                f"{nom} — {etat}",
                corps,
                url="/#gateway",
                tag=f"run-{run_id}",
                # Sans run_id, pas de bouton : il n'y a plus rien à décider.
                run_id="",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Notification de clôture non envoyée : %s", exc)

    def _prevenir_attente(self, run_id: str, state: RunState) -> None:
        """Dire qu'une exécution attend, sans jamais la faire échouer pour autant.

        C'est ici que le service cesse d'attendre qu'on vienne le regarder. Le
        pod tourne forcément à cet instant — il est en train d'attendre — donc
        la notification part toujours d'un service vivant.
        """
        try:
            from mcp_gateway.notifications import prevenir

            suspension = getattr(state, "suspension", None) or {}
            raison = suspension.get("reason", "")
            corps = {
                "approval": "Une composition demande votre approbation.",
                "elicit": "Une composition attend une réponse de votre part.",
                "wait_until": "Une composition reprend et attend une échéance.",
            }.get(raison, "Une composition attend votre réponse.")
            message = suspension.get("message")
            if message:
                corps = str(message)[:150]

            # Ce que la composition a produit jusqu'ici, sous la question. Une
            # bannière repliée n'en montre rien ; dépliée, elle donne de quoi
            # trancher sans ouvrir l'application, ce qui est tout l'intérêt de
            # pouvoir répondre depuis le téléphone.
            apercu = _apercu_derniere_etape(
                {
                    "step_results": getattr(state, "step_results", None) or {},
                    "step_status": getattr(state, "step_status", None) or {},
                }
            )
            if apercu:
                corps = corps + "\n\n" + apercu["etape"] + " : " + apercu["texte"]

            # Le nom de la composition dans le titre : « une composition
            # attend » ne dit pas laquelle, et l'on en a plusieurs.
            ligne = self.db.execute(
                """SELECT c.name FROM composition_runs r
                   JOIN compositions c ON c.id = r.composition_id
                   WHERE r.id = ?""",
                (run_id,),
            ).fetchone()
            nom = _lisible(ligne["name"] if ligne else "") or "Une composition"

            # Android replie la bannière sur une ligne quand elle porte des
            # boutons : le titre est parfois tout ce qu'on lit avant de décider.
            # Il doit donc nommer l'étape, pas seulement la composition.
            etape = _lisible(suspension.get("step_id") or "")
            titre = f"{nom} — {etape}" if etape else f"{nom} attend votre réponse"

            prevenir(
                self.db,
                titre,
                corps,
                url="/#gateway",
                tag=f"run-{run_id}",
                # Répondre depuis la bannière, sans ouvrir l'application. Seules
                # les approbations s'y prêtent : une question ouverte demande un
                # écran, deux boutons n'y suffisent pas.
                run_id=run_id if raison == "approval" else "",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Notification d'attente non envoyée : %s", exc)

    @staticmethod
    def _run_result(
        run_id: str, comp_id: str, status: str, state: RunState
    ) -> dict[str, Any]:
        """Résultat d'un run, taillé pour un client MCP.

        L'état complet renvoyait trois fois les mêmes données (`state`,
        `outputs`, et `step_results` dans les deux) : un run de six livrables
        atteignait 122 Ko, au-delà de ce qu'un client accepte. On ne renvoie
        donc que la sortie de la dernière étape ; le détail par étape reste en
        base, accessible via gateway_composition_run_status.
        """
        step_ids = list(state.step_results)
        last_id = step_ids[-1] if step_ids else None
        return {
            "run_id": run_id,
            "composition_id": comp_id,
            "status": status,
            "suspension": state.suspension,
            "steps": state.step_status,
            "error": state.error,
            "output": _single_view(state.step_results.get(last_id)) if last_id else None,
            "output_step": last_id,
            # Les étapes intermédiaires ne sont pas incluses : les relire via
            # gateway_composition_run_status(run_id).
            "truncated_steps": [s for s in step_ids[:-1]] if len(step_ids) > 1 else [],
        }

    @staticmethod
    def _row_to_summary(row: dict[str, Any]) -> dict[str, Any]:
        definition = CompositionDefinition.from_dict(json.loads(row["definition_json"]))
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "description": definition.description,
            "input_schema": definition.input_schema,
            "steps": len(definition.steps),
            "durable": definition.has_suspending_steps(),
            "variant": definition.is_tool_variant(),
            "source_tool": definition.source_tool(),
            "tool_name": tool_name_for_composition(row["name"]),
            "created_at": row["created_at"],
            "promoted_at": row.get("promoted_at"),
        }

    @staticmethod
    def _row_to_detail(row: dict[str, Any]) -> dict[str, Any]:
        summary = CompositionService._row_to_summary(row)
        summary["definition"] = json.loads(row["definition_json"])
        return summary


_REF_ENTREE = re.compile(r"\$\{input\.([A-Za-z_][\w]*)\}")


def _entrees_referencees(steps: list[dict[str, Any]]) -> list[str]:
    """Les entrées d'une composition sont celles que ses étapes citent."""
    trouvees: set[str] = set()
    for step in steps:
        trouvees.update(_REF_ENTREE.findall(json.dumps(step, ensure_ascii=False)))
    return sorted(trouvees)


def _slug(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texte.lower()).strip("_")
