"""Цикл вызова модели: модель называет инструменты, код их выполняет."""

import json
import os

import httpx

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_STEPS = 10

SYSTEM_PROMPT = """Ты помогаешь редактировать план работ.

Правила:
- План меняется только инструментами. Своих вычислений не делай.
- Даты и длительности не считай сам: бери их из get_plan.
- Если срок под вопросом, вызывай explain_deadline и пересказывай его числа.
- Просят поставить или снять дедлайн проекта — это set_deadline. После него план
  сам отвечает, укладывается он или нет, и это видно пользователю на диаграмме.
- Отвечай коротко, по-русски, называя задачи именами, а не номерами.
"""


async def tools_for_model(session) -> list[dict]:
    """Схемы MCP → формат tools OpenRouter. Служебные инструменты (с «_») скрыты."""
    listed = await session.list_tools()
    return [
        {"type": "function",
         "function": {"name": tool.name,
                      "description": tool.description or "",
                      "parameters": tool.input_schema}}
        for tool in listed.tools
        if not tool.name.startswith("_")
    ]


def parse_arguments(raw: str) -> tuple[dict | None, str | None]:
    """Разобрать аргументы вызова. Кривой JSON — не повод ронять цикл."""
    try:
        return json.loads(raw or "{}"), None
    except json.JSONDecodeError as error:
        return None, f"Аргументы не разобраны как JSON ({error}). Повторите вызов."


async def call_tool(session, name: str, arguments: dict) -> str:
    """Выполнить инструмент. Ошибка возвращается текстом — модель должна её объяснить."""
    try:
        result = await session.call_tool(name, arguments)
    except Exception as error:
        return f"Инструмент {name} не выполнен: {error}"
    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    return text or ("ошибка" if result.is_error else "готово")


async def run_agent(session, messages: list[dict], transport=None) -> tuple[str, list[dict], bool]:
    """Прогнать диалог до текстового ответа.

    Возвращает (текст, дополненная история, упёрлись_в_потолок).
    """
    tools = await tools_for_model(session)
    allowed = {tool["function"]["name"] for tool in tools}
    payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    async with httpx.AsyncClient(timeout=120, transport=transport) as client:
        for _ in range(MAX_STEPS):
            response = await client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json={"model": os.environ.get("MODEL", "anthropic/claude-sonnet-4.5"),
                      "messages": payload_messages, "tools": tools},
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            payload_messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return message.get("content") or "", payload_messages[1:], False

            for call in tool_calls:
                name = call["function"]["name"]
                arguments, error = parse_arguments(call["function"]["arguments"])
                if name not in allowed:
                    result = f"Инструмент {name} недоступен."
                elif error:
                    result = error
                else:
                    result = await call_tool(session, name, arguments)
                payload_messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": result})

    return ("Не смог выполнить это за разумное число шагов. Часть действий могла уже "
            "выполниться — откройте план, чтобы проверить его текущее состояние.",
            payload_messages[1:], True)
