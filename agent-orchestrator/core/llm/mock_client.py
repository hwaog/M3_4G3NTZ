"""Proveedor simulado: ejecuta el sistema completo sin llamar a la API.

Sirve para tres cosas:
  1. Desarrollar y testear la lógica de orquestación con costo cero.
  2. Correr la suite de tests en CI sin secretos.
  3. Ensayar demos sin depender de la red.

Es determinista a propósito: la misma entrada produce la misma traza, que es
lo que permite comparar patrones de orquestación entre sí.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from core.llm.provider import LLMProvider, LLMResponse, ToolCall, estimate_cost
from core.orchestrator.state import Usage

_WORD_RE = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
_STOPWORDS = {
    "para", "como", "cual", "cuales", "sobre", "desde", "hasta", "este",
    "esta", "estos", "esas", "pero", "porque", "donde", "cuando", "quiero",
    "puedo", "favor", "tengo", "hacer", "sera", "seria", "todo", "toda",
}


def _strip_accents(word: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn"
    )


def _stem(word: str) -> str:
    """Stemming rudimentario en español: quita plurales y recorta a 5 letras."""
    word = _strip_accents(word.lower())
    if word.endswith("es") and len(word) > 4:
        word = word[:-2]
    elif word.endswith("s") and len(word) > 3:
        word = word[:-1]
    return word[:5]


def _tokens(text: str) -> set[str]:
    """Conjunto de raíces comparables, sin palabras vacías."""
    return {
        _stem(w)
        for w in _WORD_RE.findall(text)
        if len(w) > 3 and _strip_accents(w.lower()) not in _STOPWORDS
    }


def _approx_token_count(text: str) -> int:
    return max(1, len(text) // 4)


class MockProvider(LLMProvider):
    """Simula respuestas coherentes según las herramientas disponibles."""

    name = "mock"

    def __init__(self, seed_note: str = "respuesta simulada") -> None:
        self._seed_note = seed_note
        self.call_count = 0

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        self.call_count += 1
        tools = tools or []
        tool_names = [t["name"] for t in tools]
        used = self._tools_already_used(messages)
        user_text = self._last_user_text(messages)

        if "classify_intent" in tool_names:
            return self._classify(model, system, messages, tools)

        delegates = [n for n in tool_names if n.startswith("delegate_to_")]
        if delegates and not used:
            return self._delegate(model, system, user_text, delegates)

        pending = [n for n in tool_names if n not in used and not n.startswith("delegate_to_")]
        if pending and not delegates:
            return self._single_tool_call(model, system, pending[0], user_text)

        return self._final_text(model, system, user_text, messages)

    # --- estrategias de simulación ---------------------------------------

    def _classify(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Clasifica por solapamiento de palabras con la descripción de cada agente."""
        schema = tools[0].get("input_schema", {})
        candidates: list[str] = (
            schema.get("properties", {}).get("agent_id", {}).get("enum", [])
        )
        descriptions: dict[str, str] = json.loads(
            schema.get("properties", {})
            .get("agent_id", {})
            .get("description", "{}")
            .split("::", 1)[-1]
            or "{}"
        )

        user_text = self._last_user_text(messages)
        user_tokens = _tokens(user_text)

        best_id, best_score = None, 0
        for agent_id in candidates:
            if agent_id == "escalate":
                continue
            overlap = len(user_tokens & _tokens(descriptions.get(agent_id, agent_id)))
            if overlap > best_score:
                best_id, best_score = agent_id, overlap

        if best_id is None:
            best_id = "escalate"
            confidence = 0.1
            reason = "Sin coincidencia con ningún asistente disponible."
        else:
            # Se puntúa por COBERTURA, no por conteo bruto: qué proporción de
            # la consulta apunta a este asistente. Así una pregunta corta y
            # clara ("¿cuál es el horario?") no queda penalizada por ser
            # concisa, mientras que un término suelto dentro de una frase
            # larga y ajena sigue quedando bajo el umbral.
            coverage = best_score / max(len(user_tokens), 1)
            confidence = min(0.95, 0.35 + 0.65 * coverage)
            reason = (
                f"{best_score} de {len(user_tokens)} término(s) relevantes "
                f"apuntan a '{best_id}'."
            )

        args = {"agent_id": best_id, "confidence": round(confidence, 2), "reason": reason}
        return self._build(
            model, system, text="", tool_calls=[ToolCall(id="mock_cls", name="classify_intent", arguments=args)]
        )

    def _delegate(
        self, model: str, system: str, user_text: str, delegates: list[str]
    ) -> LLMResponse:
        """El supervisor reparte la tarea entre sus workers."""
        calls = [
            ToolCall(
                id=f"mock_del_{i}",
                name=name,
                arguments={
                    "task": f"[{self._seed_note}] Atiende tu parte de: {user_text[:160]}"
                },
            )
            for i, name in enumerate(delegates[:3])
        ]
        return self._build(
            model, system, text="Reparto la tarea entre los agentes.", tool_calls=calls
        )

    def _single_tool_call(
        self, model: str, system: str, tool_name: str, user_text: str
    ) -> LLMResponse:
        return self._build(
            model,
            system,
            text="",
            tool_calls=[
                ToolCall(
                    id="mock_tool",
                    name=tool_name,
                    arguments={"query": user_text[:120] or "consulta simulada"},
                )
            ],
        )

    def _final_text(
        self, model: str, system: str, user_text: str, messages: list[dict[str, Any]]
    ) -> LLMResponse:
        role = self._role_from_system(system)
        text = (
            f"[{self._seed_note} · {role}] Respuesta a: \"{user_text[:120]}\". "
            "En modo simulado no se consulta el modelo real; la traza de pasos, "
            "el uso de herramientas y el conteo de costo sí son reales."
        )
        return self._build(model, system, text=text, tool_calls=[])

    # --- utilidades ------------------------------------------------------

    def _build(
        self,
        model: str,
        system: str,
        *,
        text: str,
        tool_calls: list[ToolCall],
    ) -> LLMResponse:
        in_tokens = _approx_token_count(system) + 40
        out_tokens = _approx_token_count(text) + 20 * len(tool_calls)
        usage = Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=estimate_cost(model, in_tokens, out_tokens),
        )
        raw: list[dict[str, Any]] = []
        if text:
            raw.append({"type": "text", "text": text})
        for tc in tool_calls:
            raw.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
            )
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason="tool_use" if tool_calls else "end_turn",
            raw_content=raw,
        )

    @staticmethod
    def _tools_already_used(messages: list[dict[str, Any]]) -> set[str]:
        used: set[str] = set()
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    used.add(block.get("name", ""))
        return used

    @staticmethod
    def _last_user_text(messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
        return ""

    @staticmethod
    def _role_from_system(system: str) -> str:
        first = system.strip().splitlines()[0] if system.strip() else "agente"
        return first.lstrip("# ").strip()[:60] or "agente"
