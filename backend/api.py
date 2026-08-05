"""HTTP-слой: четыре сценария ТЗ — четыре эндпоинта. Все возвращают план целиком."""

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

import agent_loop
import excel_io
from sample_data import sample_tasks

load_dotenv(Path(__file__).with_name(".env"))

SERVER = Path(__file__).with_name("plan_mcp_server.py")
history: list[dict] = []  # одна на приложение: см. ROADMAP, пункт 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    """MCP-сессия поднимается один раз на старте: это отдельный процесс.

    Сразу после подъёма план заполняется тестовыми данными, чтобы открытая
    страница показывала диаграмму, а не пустой экран с просьбой загрузить файл.
    Старт проекта — сегодняшний день, поэтому демо всегда выглядит актуальным.
    """
    parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            app.state.mcp = session
            await call("_load_plan", {"tasks": sample_tasks(),
                                      "project_start": date.today().isoformat()})
            yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # порт vite; в продакшене — закрытый список из ALLOWED_ORIGINS
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def call(name: str, arguments: dict | None = None) -> dict:
    """Вызвать инструмент MCP и разобрать JSON из текстового блока."""
    result = await app.state.mcp.call_tool(name, arguments or {})
    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    if result.is_error:
        raise HTTPException(status_code=400, detail=text)
    return json.loads(text)


class ChatRequest(BaseModel):
    message: str


@app.get("/api/plan")
async def get_plan():
    return await call("get_plan")


@app.post("/api/import")
async def import_excel(file: UploadFile):
    tasks, errors = excel_io.parse_excel(await file.read())
    if errors:
        # 422, а не 500: файл прочитан, данные не годятся, и вот что именно.
        raise HTTPException(status_code=422, detail=errors)
    plan = await call("_load_plan", {"tasks": tasks, "project_start": date.today().isoformat()})
    history.clear()
    return plan


@app.post("/api/chat")
async def chat(request: ChatRequest):
    snapshot = await call("get_plan")
    history.append({"role": "user", "content": request.message})
    try:
        text, updated, gave_up = await agent_loop.run_agent(app.state.mcp, list(history))
    except Exception as error:
        # Модель отвалилась посреди цепочки: откатываем план и забываем фразу,
        # иначе она навсегда останется в истории без ответа.
        history.pop()
        await _restore(snapshot)
        raise HTTPException(
            status_code=502,
            detail=f"Модель не ответила ({error}). План возвращён в исходное состояние.",
        ) from error

    if gave_up:
        plan = await _restore(snapshot)
        text = "Не смог выполнить это за разумное число шагов. План возвращён в исходное состояние."
    else:
        history[:] = updated
        plan = await call("get_plan")
    return {"reply": text, "plan": plan}


async def _restore(snapshot: dict) -> dict:
    """Вернуть план к снимку, сделанному до фразы, вместе с дедлайном."""
    return await call("_load_plan", {"tasks": snapshot["tasks"],
                                     "project_start": snapshot["project_start"],
                                     "deadline": snapshot["deadline"]})


@app.get("/api/export")
async def export():
    plan = await call("get_plan")
    return Response(
        content=excel_io.export_excel(plan),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plan.xlsx"'},
    )


DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.is_dir():
    # Монтируется последним: маршруты /api уже объявлены выше и имеют приоритет.
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
