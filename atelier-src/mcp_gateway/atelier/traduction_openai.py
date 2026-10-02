"""Anthropic `/v1/messages` ⇄ OpenAI `/chat/completions`.

Claude Code parle le format Anthropic ; Albert, comme beaucoup de fournisseurs,
ne parle que le format OpenAI. Le relais traduit au passage : requête, réponse
entière et flux SSE, appels d'outils compris.

Fonctions pures, sans réseau : le relais les appelle, les tests les rejouent.
"""

from __future__ import annotations

import json
from typing import Any

# Outil factice des modèles dont l'analyse native des appels d'outils échoue
# chez le fournisseur : on les force à toujours appeler un outil (`required`,
# que le fournisseur tient par décodage guidé) ; `repondre` leur laisse la
# possibilité de parler. Le relais le reconvertit en texte.
OUTIL_REPONDRE = "repondre"
_CONSIGNE_REPONDRE = (
    f"Pour parler à la personne, ou quand tu as fini et qu'aucun autre outil n'est nécessaire, "
    f"appelle l'outil `{OUTIL_REPONDRE}` avec ton texte."
)
_OUTIL_REPONDRE = {
    "type": "function",
    "function": {
        "name": OUTIL_REPONDRE,
        "description": "Répond à la personne en texte : à utiliser quand aucun autre outil n'est nécessaire.",
        "parameters": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
    },
}

_ARRETS = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use", "function_call": "tool_use"}


def _texte(contenu: Any) -> str:
    """Le texte d'un contenu Anthropic : chaîne, ou blocs `text`."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "".join(str(b.get("text") or "") for b in contenu if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _outil(entree: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": entree.get("name", ""),
            "description": entree.get("description", ""),
            "parameters": entree.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def _choix_d_outil(choix: Any) -> Any:
    genre = choix.get("type") if isinstance(choix, dict) else None
    if genre == "any":
        return "required"
    if genre == "none":
        return "none"
    if genre == "tool":
        return {"type": "function", "function": {"name": choix.get("name", "")}}
    return "auto" if genre == "auto" else None


def _message_utilisateur(blocs: list[Any]) -> list[dict[str, Any]]:
    """Un tour « user » Anthropic : résultats d'outils d'abord, puis le reste."""
    sortie: list[dict[str, Any]] = []
    parties: list[dict[str, Any]] = []
    for bloc in blocs:
        if not isinstance(bloc, dict):
            continue
        genre = bloc.get("type")
        if genre == "text":
            parties.append({"type": "text", "text": str(bloc.get("text") or "")})
        elif genre == "image":
            source = bloc.get("source") or {}
            if source.get("type") == "base64":
                url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
            else:
                url = str(source.get("url") or "")
            if url:
                parties.append({"type": "image_url", "image_url": {"url": url}})
        elif genre == "tool_result":
            texte = _texte(bloc.get("content"))
            if bloc.get("is_error"):
                texte = f"Erreur : {texte}"
            sortie.append({"role": "tool", "tool_call_id": bloc.get("tool_use_id", ""), "content": texte})
    if parties:
        simple = all(p["type"] == "text" for p in parties)
        sortie.append({"role": "user", "content": "".join(p["text"] for p in parties) if simple else parties})
    return sortie


def _message_assistant(blocs: list[Any]) -> dict[str, Any]:
    texte = _texte(blocs)  # le raisonnement (`thinking`) ne repart pas
    appels = [
        {
            "id": b.get("id", ""),
            "type": "function",
            "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)},
        }
        for b in blocs
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    message: dict[str, Any] = {"role": "assistant", "content": texte or None}
    if appels:
        message["tool_calls"] = appels
    return message


def vers_openai(corps: dict[str, Any], modele: str, *, contraint: bool = False) -> dict[str, Any]:
    """La requête OpenAI équivalente à une requête `/v1/messages`.

    `contraint` : voir `OUTIL_REPONDRE`. Sans effet quand la requête n'a pas
    d'outils, ou quand l'appelant impose déjà son choix d'outil. Le flux est
    alors coupé : l'appel d'un outil ne se diffuse pas comme du texte, le relais
    rejoue la réponse entière.
    """
    outils_presents = any(isinstance(o, dict) for o in corps.get("tools") or [])
    choix_demande = _choix_d_outil(corps.get("tool_choice"))
    contraint = contraint and outils_presents and choix_demande in (None, "auto")
    messages: list[dict[str, Any]] = []
    consigne = _texte(corps.get("system"))
    if contraint:
        consigne = f"{consigne}\n\n{_CONSIGNE_REPONDRE}".strip()
    if consigne:
        messages.append({"role": "system", "content": consigne})
    for message in corps.get("messages") or []:
        if not isinstance(message, dict):
            continue
        contenu = message.get("content")
        if isinstance(contenu, str):
            messages.append({"role": message.get("role", "user"), "content": contenu})
        elif isinstance(contenu, list) and message.get("role") == "assistant":
            messages.append(_message_assistant(contenu))
        elif isinstance(contenu, list):
            messages.extend(_message_utilisateur(contenu))
    sortie: dict[str, Any] = {"model": modele, "messages": messages}
    if corps.get("max_tokens"):
        sortie["max_tokens"] = corps["max_tokens"]
    for cle in ("temperature", "top_p"):
        if corps.get(cle) is not None:
            sortie[cle] = corps[cle]
    if corps.get("stop_sequences"):
        sortie["stop"] = corps["stop_sequences"]
    outils = [_outil(o) for o in corps.get("tools") or [] if isinstance(o, dict)]
    if outils:  # une liste vide serait refusée par certains amonts
        if contraint:
            outils.append(_OUTIL_REPONDRE)
        sortie["tools"] = outils
        choix = "required" if contraint else choix_demande
        if choix is not None:
            sortie["tool_choice"] = choix
    if corps.get("stream") and not contraint:
        sortie["stream"] = True
        sortie["stream_options"] = {"include_usage": True}
    return sortie


def _raisonnement(delta_ou_message: dict[str, Any]) -> str:
    return str(delta_ou_message.get("reasoning_content") or delta_ou_message.get("reasoning") or "")


def _usage(donnees: Any) -> tuple[int, int]:
    donnees = donnees if isinstance(donnees, dict) else {}
    return int(donnees.get("prompt_tokens") or 0), int(donnees.get("completion_tokens") or 0)


def _texte_de_repondre(arguments: str) -> str:
    try:
        lu = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return arguments  # un modèle qui oublie le JSON parle quand même
    return str(lu.get("texte") or "") if isinstance(lu, dict) else str(lu)


def reponse_vers_anthropic(donnees: dict[str, Any], modele: str) -> dict[str, Any]:
    """Un message Anthropic à partir d'une réponse `/chat/completions` entière.

    L'outil factice `repondre` redevient du texte.
    """
    choix = (donnees.get("choices") or [{}])[0]
    message = choix.get("message") or {}
    contenu: list[dict[str, Any]] = []
    pensee = _raisonnement(message)
    if pensee:
        contenu.append({"type": "thinking", "thinking": pensee, "signature": ""})
    if message.get("content"):
        contenu.append({"type": "text", "text": str(message["content"])})
    for appel in message.get("tool_calls") or []:
        fonction = appel.get("function") or {}
        if fonction.get("name") == OUTIL_REPONDRE:
            parole = _texte_de_repondre(fonction.get("arguments") or "")
            if parole:
                contenu.append({"type": "text", "text": parole})
            continue
        try:
            entree = json.loads(fonction.get("arguments") or "{}")
        except json.JSONDecodeError:
            entree = {}
        contenu.append(
            {"type": "tool_use", "id": appel.get("id", ""), "name": fonction.get("name", ""), "input": entree}
        )
    entree_jetons, sortie_jetons = _usage(donnees.get("usage"))
    arret = _ARRETS.get(choix.get("finish_reason") or "stop", "end_turn")
    if arret == "tool_use" and not any(b["type"] == "tool_use" for b in contenu):
        arret = "end_turn"  # il n'a appelé que `repondre`
    return {
        "id": donnees.get("id") or "msg_relais",
        "type": "message",
        "role": "assistant",
        "model": modele,
        "content": contenu or [{"type": "text", "text": ""}],
        "stop_reason": arret,
        "stop_sequence": None,
        "usage": {"input_tokens": entree_jetons, "output_tokens": sortie_jetons},
    }


def flux_depuis_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Les événements SSE d'un message déjà entier (réponse rejouée en flux)."""
    debut = {**message, "content": [], "stop_reason": None, "usage": {"input_tokens": message["usage"]["input_tokens"], "output_tokens": 0}}
    evenements: list[dict[str, Any]] = [{"type": "message_start", "message": debut}]
    for index, bloc in enumerate(message["content"]):
        if bloc["type"] == "text":
            ouvert, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": bloc["text"]}
        elif bloc["type"] == "thinking":
            ouvert = {"type": "thinking", "thinking": "", "signature": ""}
            delta = {"type": "thinking_delta", "thinking": bloc["thinking"]}
        else:
            ouvert = {**bloc, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(bloc.get("input") or {}, ensure_ascii=False)}
        evenements.append({"type": "content_block_start", "index": index, "content_block": ouvert})
        evenements.append({"type": "content_block_delta", "index": index, "delta": delta})
        evenements.append({"type": "content_block_stop", "index": index})
    evenements.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
            "usage": message["usage"],
        }
    )
    evenements.append({"type": "message_stop"})
    return evenements


class TraducteurDeFlux:
    """Rejoue un flux SSE OpenAI en événements Anthropic, ligne à ligne.

    `ligne()` rend les événements (dicts) que cette ligne déclenche ; `fin()`
    ferme ce qui est ouvert. Rien n'est retenu au-delà du bloc courant.
    """

    def __init__(self, modele: str) -> None:
        self.modele = modele
        self._demarre = False
        self._termine = False
        self._index = -1
        self._genre: str | None = None  # bloc ouvert : thinking | text | tool
        self._appels: dict[int, int] = {}  # index OpenAI de l'appel -> index de bloc
        self._arret = "end_turn"
        self._entree = 0
        self._sortie = 0

    def _ouvrir(self, genre: str, bloc: dict[str, Any]) -> list[dict[str, Any]]:
        evenements = self._fermer()
        self._index += 1
        self._genre = genre
        return evenements + [{"type": "content_block_start", "index": self._index, "content_block": bloc}]

    def _fermer(self) -> list[dict[str, Any]]:
        if self._genre is None:
            return []
        self._genre = None
        return [{"type": "content_block_stop", "index": self._index}]

    def _debut(self) -> list[dict[str, Any]]:
        if self._demarre:
            return []
        self._demarre = True
        return [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_relais",
                    "type": "message",
                    "role": "assistant",
                    "model": self.modele,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            }
        ]

    def ligne(self, ligne: str) -> list[dict[str, Any]]:
        if self._termine or not ligne.startswith("data:"):
            return []
        charge = ligne[5:].strip()
        if charge == "[DONE]":
            return self.fin()
        try:
            morceau = json.loads(charge)
        except json.JSONDecodeError:
            return []
        if not isinstance(morceau, dict):
            return []
        evenements = self._debut()
        if morceau.get("usage"):
            self._entree, self._sortie = _usage(morceau["usage"])
        for choix in morceau.get("choices") or []:
            delta = choix.get("delta") or {}
            pensee = _raisonnement(delta)
            if pensee:
                if self._genre != "thinking":
                    evenements += self._ouvrir("thinking", {"type": "thinking", "thinking": "", "signature": ""})
                evenements.append(
                    {"type": "content_block_delta", "index": self._index, "delta": {"type": "thinking_delta", "thinking": pensee}}
                )
            if delta.get("content"):
                if self._genre != "text":
                    evenements += self._ouvrir("text", {"type": "text", "text": ""})
                evenements.append(
                    {"type": "content_block_delta", "index": self._index, "delta": {"type": "text_delta", "text": delta["content"]}}
                )
            for appel in delta.get("tool_calls") or []:
                rang = int(appel.get("index") or 0)
                fonction = appel.get("function") or {}
                if rang not in self._appels:
                    evenements += self._ouvrir(
                        "tool",
                        {"type": "tool_use", "id": appel.get("id") or f"call_{rang}", "name": fonction.get("name", ""), "input": {}},
                    )
                    self._appels[rang] = self._index
                if fonction.get("arguments"):
                    evenements.append(
                        {
                            "type": "content_block_delta",
                            "index": self._appels[rang],
                            "delta": {"type": "input_json_delta", "partial_json": fonction["arguments"]},
                        }
                    )
            if choix.get("finish_reason"):
                self._arret = _ARRETS.get(choix["finish_reason"], "end_turn")
        return evenements

    def fin(self) -> list[dict[str, Any]]:
        if self._termine:
            return []
        self._termine = True
        evenements = self._debut() + self._fermer()
        evenements.append(
            {
                "type": "message_delta",
                "delta": {"stop_reason": self._arret, "stop_sequence": None},
                "usage": {"input_tokens": self._entree, "output_tokens": self._sortie},
            }
        )
        evenements.append({"type": "message_stop"})
        return evenements


def en_sse(evenement: dict[str, Any]) -> str:
    """Un événement Anthropic sous sa forme SSE."""
    return f"event: {evenement['type']}\ndata: {json.dumps(evenement, ensure_ascii=False)}\n\n"
