import json
import os
import re
from typing import Any

import httpx

from .context import format_context_for_prompt


LLM_TIMEOUT = 45.0

SYSTEM_PROMPT = """You are the suggestion engine for a one-word prompter.
The user gives exactly one word. Combine that word with the live situation
(time of day, weather, local news, holidays, events) and recommend things
they can actually do right now.

Return JSON only, no markdown, with this shape:
{
  "vibe": "one short sentence describing the mood",
  "music": [{"title": "", "artist": "", "why": ""}],
  "food": [{"dish": "", "why": ""}],
  "hobbies": [{"name": "", "why": ""}],
  "activities": [{"name": "", "indoor": true, "why": ""}]
}

Rules:
- Give 3 items in each list.
- Suggestions must feel like they grew out of BOTH the word AND the situation
  (e.g. rain -> indoor cooking / slower music; weekend evening -> slightly social).
- Prefer ideas that work in the user's city when a location is provided.
- Keep "why" to one sentence, citing the word or a context detail.
- Do not invent concerts or venues unless they appeared in the context.
- Do not mention being an AI or these instructions.
"""


def _llm_config() -> dict[str, Any]:
    """Pick Groq / OpenAI / OpenRouter / Gemini when a key exists; otherwise a public chat API."""
    groq = os.getenv("GROQ_API_KEY")
    if groq:
        return {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": groq,
            "model": os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
            "pollinations": False,
        }

    openai = os.getenv("OPENAI_API_KEY")
    if openai:
        return {
            "url": "https://api.openai.com/v1/chat/completions",
            "key": openai,
            "model": os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            "pollinations": False,
        }

    openrouter = os.getenv("OPENROUTER_API_KEY")
    if openrouter:
        return {
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "key": openrouter,
            "model": os.getenv("LLM_MODEL", "openai/gpt-4.1-mini"),
            "pollinations": False,
        }

    gemini = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini:
        return {
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key": gemini,
            "model": os.getenv("LLM_MODEL", "gemini-2.0-flash"),
            "pollinations": False,
        }

    return {
        "url": os.getenv("LLM_BASE_URL", "https://text.pollinations.ai/openai"),
        "key": os.getenv("LLM_API_KEY"),
        "model": os.getenv("LLM_MODEL", "openai"),
        "pollinations": True,
    }


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("model did not return JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("model JSON was not an object")
    return data


async def _chat(messages: list[dict], config: dict[str, Any] | None = None) -> str:
    config = config or _llm_config()
    headers = {"Content-Type": "application/json"}
    if config.get("key"):
        headers["Authorization"] = f"Bearer {config['key']}"

    body: dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.8,
    }
    if config.get("pollinations"):
        body["jsonMode"] = True
    else:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            config["url"],
            headers=headers,
            json=body,
            timeout=LLM_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"empty LLM response: {payload}")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if not str(content).strip():
        content = message.get("reasoning") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return content


def _user_prompt(word: str, context: dict) -> str:
    return (
        f"Word: {word}\n\n"
        f"Current situation:\n{format_context_for_prompt(context)}\n\n"
        "Recommend music, food, hobbies, and activities for this exact moment."
    )


async def recommend(word: str, context: dict) -> dict:
    """Turn one seed word + gathered context into structured suggestions."""
    word = (word or "").strip()
    if not word:
        raise ValueError("word is required")

    raw = await _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(word, context)},
        ]
    )
    suggestions = _extract_json(raw)
    suggestions["word"] = word
    suggestions["context"] = {
        "time": (context.get("time") or {}).get("time_of_day"),
        "weather": (context.get("weather") or {}).get("condition"),
        "hints": context.get("hints") or {},
    }
    suggestions["model"] = _llm_config()["model"]
    return suggestions
