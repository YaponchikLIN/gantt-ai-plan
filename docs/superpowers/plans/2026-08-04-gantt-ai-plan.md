# Диаграмма Гантта с AI-редактированием — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Веб-приложение, где план работ рисуется диаграммой Гантта, редактируется фразами на естественном языке через MCP-инструменты и обменивается с Excel в обе стороны.

**Architecture:** Три процесса. MCP-сервер (stdio) держит план в памяти и выставляет десять инструментов; каждый инструмент атомарен и заканчивается пересчётом дат. FastAPI держит одну MCP-сессию на всё приложение, гоняет агентский цикл через OpenRouter и отдаёт фронту план целиком. React переводит готовые даты в координаты SVG и ничего не вычисляет.

**Tech Stack:** Python 3.11+, `mcp` 2.0.0, FastAPI, uvicorn, openpyxl, httpx, pytest; React 19 + Vite; модель `anthropic/claude-sonnet-4.5` через OpenRouter.

**Спека:** `docs/superpowers/specs/2026-08-04-gantt-ai-plan-design.md`

---

## Проверенные факты об окружении

Проверено запуском перед написанием плана — не по памяти:

- В `mcp` 2.0.0 **нет** `mcp.server.fastmcp`. Сервер: `from mcp.server import MCPServer`, регистрация `@srv.tool()`, запуск `srv.run("stdio")`.
- Поля протокола в 2.0.0 — **snake_case**: `tool.input_schema`, `result.is_error`, `result.structured_content` (в конспекте фигурировал старый camelCase).
- Функция, обёрнутая `@srv.tool()`, остаётся вызываемой напрямую — тесты зовут инструменты как обычные функции, без asyncio и без клиента.
- Инструмент, вернувший `dict`, приезжает клиенту как `result.content[0].text` с JSON-строкой; `structured_content` при этом `None`.
- Исключение внутри инструмента приезжает как `is_error=True` и текст `Error executing tool <name>: <сообщение>`. Отдельного канала ошибок не нужно.
- Клиент: `stdio_client(StdioServerParameters(...))` → `ClientSession(read, write)` → `await session.initialize()`.
- OpenRouter отвечает на формат tools OpenAI и возвращает `choices[0].message.tool_calls[].function.{name,arguments}`, `finish_reason: "tool_calls"`. Ключ и модель рабочие.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `backend/plan_mcp_server.py` | `STATE`, `recalculate()`, транзакция, десять инструментов + служебный `_load_plan` |
| `backend/excel_io.py` | `parse_excel` (два прохода), `_check_cycles`, `export_excel` |
| `backend/agent_loop.py` | Конвертация схем MCP → OpenRouter, цикл вызовов, потолок итераций |
| `backend/api.py` | Четыре эндпоинта, CORS, `lifespan` с MCP-сессией |
| `backend/demo_scenarios.py` | Прогон инструментов без модели + генерация `sample_plan.xlsx` |
| `backend/test_plan.py` | Тесты расчёта, инструментов, Excel |
| `frontend/src/App.jsx` | Состояние, вызовы API, раскладка |
| `frontend/src/GanttChart.jsx` | SVG: шкала, полоски, стрелки, модалка |
| `frontend/src/Chat.jsx` | Лента сообщений, ввод, блокировка |
| `frontend/src/Toolbar.jsx` | Импорт, экспорт, ошибки 422 |
| `frontend/src/api.js` | Четыре функции обращения к бэкенду |
| `docs/ROADMAP.md` | Техдолг: что упрощено, чем грозит, порядок закрытия |

Логика расчёта живёт в одном файле с инструментами намеренно: инструменты — тонкие обёртки над `STATE` и `recalculate()`, разносить их по файлам значит плодить импорты ради красоты.

---

### Task 1: Скелет проекта и зависимости

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`
- Create: `backend/.env`
- Modify: `.gitignore` (уже содержит `.env`, `__pycache__/`, `.venv/`, `node_modules/`, `dist/` — проверить)

- [ ] **Step 1: Записать зависимости**

`backend/requirements.txt`:

```
mcp==2.0.0
fastapi==0.141.1
uvicorn==0.52.1
openpyxl==3.1.5
httpx==0.28.1
python-dotenv==1.2.2
python-multipart==0.0.20
pytest==9.1.1
```

`python-multipart` нужен FastAPI для приёма файла в `/api/import`; без него загрузка падает на старте приложения.

- [ ] **Step 2: Записать пример конфигурации**

`backend/.env.example`:

```
OPENROUTER_API_KEY=sk-or-v1-...
MODEL=anthropic/claude-sonnet-4.5
```

- [ ] **Step 3: Создать рабочий .env с боевым ключом**

`backend/.env` (в `.gitignore`, в репозиторий не попадает):

```
OPENROUTER_API_KEY=<боевой ключ, взять у владельца проекта — в репозиторий не коммитить>
MODEL=anthropic/claude-sonnet-4.5
```

- [ ] **Step 4: Поставить зависимости**

Виртуальное окружение `.venv` в корне уже создано. Команда:

```bash
uv pip install --python .venv/bin/python -r backend/requirements.txt
```

Ожидается: установка проходит, ошибок разрешения версий нет.

- [ ] **Step 5: Проверить, что .env не отслеживается**

```bash
git status --short backend/
```

Ожидается: в выводе есть `backend/.env.example` и `backend/requirements.txt`, строки `backend/.env` **нет**.

- [ ] **Step 6: Коммит**

```bash
git add backend/requirements.txt backend/.env.example
git commit -m "chore: pin backend dependencies"
```

---

### Task 2: Пересчёт дат — порядок и прямой проход

**Files:**
- Create: `backend/plan_mcp_server.py`
- Create: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

`backend/test_plan.py`:

```python
from datetime import date

import plan_mcp_server as srv


def set_tasks(tasks, project_start=date(2026, 9, 1)):
    """Положить план в хранилище напрямую, минуя инструменты."""
    srv.STATE["tasks"] = {t["id"]: t for t in tasks}
    srv.STATE["project_start"] = project_start
    srv.STATE["next_id"] = max((t["id"] for t in tasks), default=0) + 1


def task(id, name, duration, predecessors=(), assignee="", not_earlier_than=None):
    return {"id": id, "name": name, "description": "", "assignee": assignee,
            "duration": duration, "predecessors": list(predecessors),
            "not_earlier_than": not_earlier_than}


def by_name(plan):
    return {t["name"]: t for t in plan["tasks"]}


def test_chain_of_three_gets_six_computed_dates():
    set_tasks([
        task(1, "Проектирование", 5),
        task(2, "Разработка", 10, [1]),
        task(3, "Тестирование", 4, [2]),
    ])
    t = by_name(srv.recalculate())
    assert (t["Проектирование"]["start"], t["Проектирование"]["finish"]) == ("2026-09-01", "2026-09-06")
    assert (t["Разработка"]["start"], t["Разработка"]["finish"]) == ("2026-09-06", "2026-09-16")
    assert (t["Тестирование"]["start"], t["Тестирование"]["finish"]) == ("2026-09-16", "2026-09-20")


def test_constraint_pushes_task_right():
    set_tasks([
        task(1, "Проектирование", 5),
        task(2, "Разработка", 10, [1], not_earlier_than=date(2026, 9, 10)),
    ])
    t = by_name(srv.recalculate())
    assert t["Разработка"]["start"] == "2026-09-10"


def test_cycle_raises_with_ids():
    set_tasks([
        task(1, "А", 1, [3]),
        task(2, "Б", 1, [1]),
        task(3, "В", 1, [2]),
    ])
    try:
        srv.recalculate()
    except ValueError as e:
        assert "1" in str(e) and "2" in str(e) and "3" in str(e)
    else:
        raise AssertionError("цикл должен был вызвать ValueError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'plan_mcp_server'`.

- [ ] **Step 3: Написать минимальную реализацию**

`backend/plan_mcp_server.py`:

```python
"""MCP-сервер плана работ: хранилище, пересчёт дат, инструменты агента."""

from datetime import date, timedelta

STATE = {"tasks": {}, "project_start": date.today(), "next_id": 1}


def _topological_order():
    """Порядок обхода: задача идёт после всех своих предшественников.

    Возвращает (порядок, наследники). Цикл → ValueError со списком id.
    """
    tasks = STATE["tasks"]
    successors = {tid: [] for tid in tasks}
    indegree = {}
    for tid, t in tasks.items():
        indegree[tid] = len(t["predecessors"])
        for p in t["predecessors"]:
            if p not in tasks:
                raise ValueError(f"Задача {tid} ссылается на несуществующую задачу {p}")
            successors[p].append(tid)

    ready = sorted(tid for tid, deg in indegree.items() if deg == 0)
    order = []
    while ready:
        tid = ready.pop(0)
        order.append(tid)
        for s in successors[tid]:
            indegree[s] -= 1
            if indegree[s] == 0:
                ready.append(s)
        ready.sort()

    if len(order) != len(tasks):
        stuck = sorted(set(tasks) - set(order))
        raise ValueError(f"Цикл в зависимостях: {stuck}")
    return order, successors


def recalculate():
    """Вычислить даты. Единственный источник дат в системе."""
    tasks = STATE["tasks"]
    order, successors = _topological_order()

    start, finish = {}, {}
    for tid in order:
        t = tasks[tid]
        candidates = [finish[p] for p in t["predecessors"]]
        candidates.append(STATE["project_start"])
        if t["not_earlier_than"]:
            candidates.append(t["not_earlier_than"])
        start[tid] = max(candidates)
        finish[tid] = start[tid] + timedelta(days=t["duration"])

    project_finish = max(finish.values(), default=STATE["project_start"])

    rows = []
    for tid in sorted(order, key=lambda i: (start[i], i)):
        t = tasks[tid]
        rows.append({
            "id": tid,
            "name": t["name"],
            "description": t["description"],
            "assignee": t["assignee"],
            "duration": t["duration"],
            "predecessors": list(t["predecessors"]),
            "not_earlier_than": t["not_earlier_than"].isoformat() if t["not_earlier_than"] else None,
            "start": start[tid].isoformat(),
            "finish": finish[tid].isoformat(),
        })

    return {
        "project_start": STATE["project_start"].isoformat(),
        "project_finish": project_finish.isoformat(),
        "tasks": rows,
    }
```

- [ ] **Step 4: Запустить тест и убедиться, что он проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `3 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: topological order and forward pass for task dates"
```

---

### Task 3: Обратный проход — запас и критический путь

**Files:**
- Modify: `backend/plan_mcp_server.py` (функция `recalculate`)
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py` перед блоком `if __name__`:

```python
def branching_plan():
    """Проектирование → (Разработка | Документация) → Тестирование."""
    return [
        task(1, "Проектирование", 5),
        task(2, "Разработка", 4, [1]),
        task(3, "Документация", 7, [1]),
        task(4, "Тестирование", 4, [2, 3]),
    ]


def test_slack_and_critical_path():
    set_tasks(branching_plan())
    plan = srv.recalculate()
    t = by_name(plan)
    assert t["Тестирование"]["start"] == "2026-09-13"
    assert t["Разработка"]["slack"] == 3
    assert t["Разработка"]["on_critical_path"] is False
    assert t["Документация"]["slack"] == 0
    assert t["Документация"]["on_critical_path"] is True
    assert plan["project_finish"] == "2026-09-17"


def test_delay_of_five_days_with_slack_three_moves_end_by_two():
    tasks = branching_plan()
    tasks[1]["duration"] = 4 + 5  # Разработка опаздывает на 5 дней
    set_tasks(tasks)
    plan = srv.recalculate()
    t = by_name(plan)
    assert plan["project_finish"] == "2026-09-19"  # было 17-е, уехало на 2
    assert t["Разработка"]["on_critical_path"] is True
    assert t["Документация"]["on_critical_path"] is False
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `KeyError: 'slack'`.

- [ ] **Step 3: Дописать обратный проход**

В `backend/plan_mcp_server.py`, внутри `recalculate()`, между строкой `project_finish = ...` и сборкой `rows`:

```python
    late_finish = {}
    for tid in reversed(order):
        late_starts = [late_finish[s] - timedelta(days=tasks[s]["duration"])
                       for s in successors[tid]]
        late_finish[tid] = min(late_starts, default=project_finish)
```

И в словарь задачи в `rows` дописать два поля:

```python
            "slack": (late_finish[tid] - finish[tid]).days,
            "on_critical_path": late_finish[tid] == finish[tid],
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `5 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: backward pass computing slack and critical path"
```

---

### Task 4: MCP-сервер, транзакция, чтение плана

**Files:**
- Modify: `backend/plan_mcp_server.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_get_plan_returns_computed_dates():
    set_tasks(branching_plan())
    plan = srv.get_plan()
    assert len(plan["tasks"]) == 4
    assert by_name(plan)["Проектирование"]["start"] == "2026-09-01"


def test_load_plan_replaces_everything():
    set_tasks(branching_plan())
    plan = srv._load_plan(
        tasks=[{"id": 1, "name": "Одна", "description": "", "assignee": "",
                "duration": 3, "predecessors": [], "not_earlier_than": None}],
        project_start="2026-10-01",
    )
    assert [t["name"] for t in plan["tasks"]] == ["Одна"]
    assert plan["project_start"] == "2026-10-01"
    assert srv.STATE["next_id"] == 2


def test_transaction_rolls_back_on_failure():
    set_tasks(branching_plan())
    before = srv.recalculate()
    try:
        with srv._transaction():
            srv.STATE["tasks"][2]["predecessors"].append(4)  # замыкает цикл
    except ValueError:
        pass
    else:
        raise AssertionError("цикл должен был вызвать ValueError")
    assert srv.recalculate() == before
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'plan_mcp_server' has no attribute 'get_plan'`.

- [ ] **Step 3: Реализовать сервер, транзакцию и два инструмента чтения**

В `backend/plan_mcp_server.py` заменить строку импортов на:

```python
"""MCP-сервер плана работ: хранилище, пересчёт дат, инструменты агента."""

import copy
from contextlib import contextmanager
from datetime import date, timedelta

from mcp.server import MCPServer

srv = MCPServer("plan")

STATE = {"tasks": {}, "project_start": date.today(), "next_id": 1}
```

В конец файла дописать:

```python
@contextmanager
def _transaction():
    """Операция применяется целиком или не применяется вовсе.

    Пересчёт внутри блока — проверка, что план остался вычислимым.
    Упало — хранилище возвращается к снимку, ошибка уходит наружу.
    """
    snapshot = copy.deepcopy(STATE)
    try:
        yield
        recalculate()
    except Exception:
        STATE.clear()
        STATE.update(snapshot)
        raise


def _require(task_id: int) -> dict:
    task = STATE["tasks"].get(task_id)
    if task is None:
        raise ValueError(f"Задача {task_id} не найдена")
    return task


@srv.tool()
def get_plan() -> dict:
    """Прочитать план целиком с вычисленными датами, запасом и критическим путём."""
    return recalculate()


@srv.tool(name="_load_plan")
def _load_plan(tasks: list[dict], project_start: str) -> dict:
    """Служебный инструмент импорта: заменить план целиком. Модели не показывается."""
    with _transaction():
        STATE["tasks"] = {
            t["id"]: {
                "id": t["id"],
                "name": t["name"],
                "description": t.get("description", ""),
                "assignee": t.get("assignee", ""),
                "duration": t["duration"],
                "predecessors": list(t.get("predecessors", [])),
                "not_earlier_than": (date.fromisoformat(t["not_earlier_than"])
                                     if t.get("not_earlier_than") else None),
            }
            for t in tasks
        }
        STATE["project_start"] = date.fromisoformat(project_start)
        STATE["next_id"] = max(STATE["tasks"], default=0) + 1
    return recalculate()


if __name__ == "__main__":
    srv.run("stdio")
```

Пересчёт зовётся дважды — внутри транзакции ради проверки и на выходе ради результата. Двести задач считаются за микросекунды, экономить тут нечего.

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `8 passed`.

- [ ] **Step 5: Проверить, что сервер поднимается по stdio**

```bash
cd backend && timeout 3 ../.venv/bin/python plan_mcp_server.py < /dev/null; echo "exit=$?"
```

Ожидается: процесс живёт до таймаута и завершается по нему (`exit=124`) либо тихо выходит на закрытом stdin. Трейсбека быть не должно.

- [ ] **Step 6: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: MCP server with atomic transaction and plan reading tools"
```

---

### Task 5: Инструменты сдвига, смены исполнителя и ограничения

**Files:**
- Modify: `backend/plan_mcp_server.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_shift_tasks_moves_task_and_its_dependents():
    set_tasks(branching_plan())
    plan = srv.shift_tasks(task_ids=[1], days=2)
    t = by_name(plan)
    assert t["Проектирование"]["start"] == "2026-09-03"
    assert t["Разработка"]["start"] == "2026-09-08"  # наследник уехал сам


def test_reassign_does_not_touch_dates():
    set_tasks(branching_plan())
    before = by_name(srv.recalculate())["Разработка"]["start"]
    plan = srv.reassign_tasks(task_ids=[2], assignee="Петров")
    t = by_name(plan)["Разработка"]
    assert t["assignee"] == "Петров"
    assert t["start"] == before


def test_shift_unknown_task_raises_and_changes_nothing():
    set_tasks(branching_plan())
    before = srv.recalculate()
    try:
        srv.shift_tasks(task_ids=[1, 99], days=5)
    except ValueError as e:
        assert "99" in str(e)
    else:
        raise AssertionError("несуществующая задача должна была вызвать ValueError")
    assert srv.recalculate() == before


def test_set_constraint_applies_not_earlier_than():
    set_tasks(branching_plan())
    plan = srv.set_constraint(task_id=2, not_earlier_than="2026-09-20")
    assert by_name(plan)["Разработка"]["start"] == "2026-09-20"
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'plan_mcp_server' has no attribute 'shift_tasks'`.

- [ ] **Step 3: Реализовать три инструмента**

В `backend/plan_mcp_server.py` перед блоком `if __name__` дописать:

```python
@srv.tool()
def shift_tasks(task_ids: list[int], days: int) -> dict:
    """Сдвинуть задачи на указанное число дней. Положительное — вправо, отрицательное — влево.

    Наследники сдвигаются сами при пересчёте, перечислять их не нужно.
    """
    with _transaction():
        starts = {row["id"]: date.fromisoformat(row["start"])
                  for row in recalculate()["tasks"]}
        for task_id in task_ids:
            task = _require(task_id)  # отдельным шагом: правая часть вычисляется первой
            task["not_earlier_than"] = starts[task_id] + timedelta(days=days)
    return recalculate()


@srv.tool()
def reassign_tasks(task_ids: list[int], assignee: str) -> dict:
    """Сменить исполнителя у задач. Даты не меняются."""
    with _transaction():
        for task_id in task_ids:
            _require(task_id)["assignee"] = assignee
    return recalculate()


@srv.tool()
def set_constraint(task_id: int, not_earlier_than: str | None) -> dict:
    """Запретить задаче начинаться раньше указанной даты (ГГГГ-ММ-ДД). None снимает ограничение."""
    with _transaction():
        task = _require(task_id)
        task["not_earlier_than"] = date.fromisoformat(not_earlier_than) if not_earlier_than else None
    return recalculate()
```

Сдвиг выражается через ограничение «не раньше» — отдельного поля «сдвиг» в хранилище нет, а закреплять задачу на новой дате всё равно нужно, иначе пересчёт вернёт её обратно к предшественникам.

Базой сдвига служит текущий старт, а не хранимое ограничение: старт уже учитывает
и предшественников, и прежнее ограничение. Если брать за базу ограничение, то сдвиг
задачи, которую держат предшественники, запишет новое ограничение, ничего не сдвинет
и отчитается об успехе. Старты собираются одним пересчётом на всю пачку.

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `12 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: shift, reassign and constraint tools"
```

---

### Task 6: Инструменты структуры плана

**Files:**
- Modify: `backend/plan_mcp_server.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_add_task_gets_next_id_and_dates():
    set_tasks(branching_plan())
    plan = srv.add_task(name="Приёмка", duration=2, assignee="Сидоров", predecessors=[4])
    t = by_name(plan)["Приёмка"]
    assert t["id"] == 5
    assert t["start"] == "2026-09-17"
    assert t["finish"] == "2026-09-19"


def test_set_duration_moves_dependents():
    set_tasks(branching_plan())
    plan = srv.set_duration(task_id=3, duration=2)  # Документация короче Разработки
    t = by_name(plan)
    assert t["Тестирование"]["start"] == "2026-09-10"
    assert t["Разработка"]["on_critical_path"] is True


def test_add_predecessor_that_closes_cycle_is_rolled_back():
    set_tasks(branching_plan())
    before = srv.recalculate()
    try:
        srv.add_predecessor(task_id=1, predecessor_id=4)  # Тестирование → Проектирование
    except ValueError as e:
        assert "Цикл" in str(e)
    else:
        raise AssertionError("замыкание цикла должно было вызвать ValueError")
    assert srv.recalculate() == before


def test_remove_predecessor_frees_the_task():
    set_tasks(branching_plan())
    plan = srv.remove_predecessor(task_id=3, predecessor_id=1)
    t = by_name(plan)["Документация"]
    assert t["predecessors"] == []
    assert t["start"] == "2026-09-01"


def test_add_predecessor_is_idempotent():
    set_tasks(branching_plan())
    srv.add_predecessor(task_id=4, predecessor_id=2)
    plan = srv.add_predecessor(task_id=4, predecessor_id=2)
    assert by_name(plan)["Тестирование"]["predecessors"] == [2, 3]
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'plan_mcp_server' has no attribute 'add_task'`.

- [ ] **Step 3: Реализовать четыре инструмента**

В `backend/plan_mcp_server.py` перед блоком `if __name__` дописать:

```python
@srv.tool()
def add_task(name: str, duration: int, assignee: str = "",
             predecessors: list[int] | None = None, description: str = "") -> dict:
    """Добавить задачу. Даты не задаются — они вычисляются из предшественников."""
    with _transaction():
        if duration < 0:
            raise ValueError("Длительность не может быть отрицательной")
        for p in predecessors or []:
            _require(p)
        task_id = STATE["next_id"]
        STATE["tasks"][task_id] = {
            "id": task_id, "name": name, "description": description,
            "assignee": assignee, "duration": duration,
            "predecessors": sorted(set(predecessors or [])), "not_earlier_than": None,
        }
        STATE["next_id"] += 1
    return recalculate()


@srv.tool()
def set_duration(task_id: int, duration: int) -> dict:
    """Изменить длительность задачи в днях."""
    with _transaction():
        task = _require(task_id)  # сначала существование, потом значение
        if duration < 0:
            raise ValueError("Длительность не может быть отрицательной")
        task["duration"] = duration
    return recalculate()


@srv.tool()
def add_predecessor(task_id: int, predecessor_id: int) -> dict:
    """Добавить зависимость: задача начнётся не раньше финиша предшественника.

    Остальные зависимости остаются на месте. Замыкание цикла откатывается.
    """
    with _transaction():
        task = _require(task_id)
        _require(predecessor_id)
        if predecessor_id == task_id:
            raise ValueError("Задача не может быть предшественником самой себе")
        task["predecessors"] = sorted(set(task["predecessors"]) | {predecessor_id})
    return recalculate()


@srv.tool()
def remove_predecessor(task_id: int, predecessor_id: int) -> dict:
    """Убрать одну зависимость. Остальные остаются на месте."""
    with _transaction():
        task = _require(task_id)
        if predecessor_id not in task["predecessors"]:
            raise ValueError(f"Задача {predecessor_id} не является предшественником задачи {task_id}")
        task["predecessors"] = [p for p in task["predecessors"] if p != predecessor_id]
    return recalculate()
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `17 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: structural tools for tasks and dependencies"
```

---

### Task 7: Удаление задачи с перевязкой наследников

**Files:**
- Modify: `backend/plan_mcp_server.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_delete_task_bridges_successors_to_predecessors():
    set_tasks([
        task(1, "Проектирование", 5),
        task(2, "Разработка", 10, [1]),
        task(3, "Тестирование", 4, [2]),
    ])
    result = srv.delete_task(task_id=2)
    t = by_name(result["plan"])
    assert "Разработка" not in t
    assert t["Тестирование"]["predecessors"] == [1]
    assert t["Тестирование"]["start"] == "2026-09-06"  # не уехало на старт проекта
    assert result["rebonded"] == [{"task": "Тестирование",
                                   "inherited": ["Проектирование"],
                                   "predecessors_now": ["Проектирование"]}]


def test_delete_task_without_successors_just_removes_it():
    set_tasks(branching_plan())
    result = srv.delete_task(task_id=4)
    assert "Тестирование" not in by_name(result["plan"])
    assert result["rebonded"] == []
    assert result["plan"]["project_finish"] == "2026-09-13"


def test_delete_task_does_not_duplicate_links():
    set_tasks([
        task(1, "А", 2),
        task(2, "Б", 2, [1]),
        task(3, "В", 2, [1, 2]),  # уже зависит и от А, и от Б
    ])
    result = srv.delete_task(task_id=2)
    assert by_name(result["plan"])["В"]["predecessors"] == [1]


def test_delete_unknown_task_raises():
    set_tasks(branching_plan())
    before = srv.recalculate()
    try:
        srv.delete_task(task_id=99)
    except ValueError as e:
        assert "99" in str(e)
    else:
        raise AssertionError("несуществующая задача должна была вызвать ValueError")
    assert srv.recalculate() == before
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'plan_mcp_server' has no attribute 'delete_task'`.

- [ ] **Step 3: Реализовать удаление**

В `backend/plan_mcp_server.py` перед блоком `if __name__` дописать:

```python
@srv.tool()
def delete_task(task_id: int) -> dict:
    """Удалить задачу. Её наследники получают её предшественников, порядок работ сохраняется.

    Возвращает план и список перевязанных связей, чтобы можно было
    сказать пользователю, что именно изменилось.
    """
    rebonded = []
    with _transaction():
        victim = _require(task_id)
        inherited = list(victim["predecessors"])
        del STATE["tasks"][task_id]
        for other in STATE["tasks"].values():
            if task_id not in other["predecessors"]:
                continue
            kept = set(other["predecessors"]) - {task_id}
            other["predecessors"] = sorted(kept | set(inherited))
            rebonded.append({
                "task": other["name"],
                "inherited": [STATE["tasks"][p]["name"] for p in sorted(set(inherited) - kept)],
                "predecessors_now": [STATE["tasks"][p]["name"] for p in other["predecessors"]],
            })
    return {"plan": recalculate(), "deleted": victim["name"], "rebonded": rebonded}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `21 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: delete task by bridging successors to its predecessors"
```

---

### Task 8: Справка по недостижимому сроку

**Files:**
- Modify: `backend/plan_mcp_server.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_explain_deadline_when_it_does_not_fit():
    set_tasks(branching_plan())
    info = srv.explain_deadline(task_id=4, required_finish="2026-09-12")
    assert info["fits"] is False
    assert info["days_short"] == 5  # финиш 17-го против требуемого 12-го
    assert info["own_duration"] == 4
    chain = {c["name"]: c for c in info["predecessors_chain"]}
    assert set(chain) == {"Проектирование", "Разработка", "Документация"}
    assert chain["Документация"]["on_critical_path"] is True
    assert chain["Разработка"]["on_critical_path"] is False


def test_explain_deadline_when_it_fits():
    set_tasks(branching_plan())
    info = srv.explain_deadline(task_id=4, required_finish="2026-09-30")
    assert info["fits"] is True
    assert info["days_short"] == 0


def test_explain_deadline_changes_nothing():
    set_tasks(branching_plan())
    before = srv.recalculate()
    srv.explain_deadline(task_id=4, required_finish="2026-09-12")
    assert srv.recalculate() == before
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'plan_mcp_server' has no attribute 'explain_deadline'`.

- [ ] **Step 3: Реализовать справку**

В `backend/plan_mcp_server.py` перед блоком `if __name__` дописать:

```python
@srv.tool()
def explain_deadline(task_id: int, required_finish: str) -> dict:
    """Справка: укладывается ли задача в срок и что этому мешает. Ничего не меняет.

    `required_finish` — дата в формате ГГГГ-ММ-ДД в той же системе отсчёта, что и
    поле `finish`: это день, следующий за последним рабочим днём. Если пользователь
    сказал «закончить к 12 сентября включительно», передавайте 2026-09-13.

    Возвращает готовые числа — считать разницу дат самостоятельно не нужно.
    Что именно сокращать, справка не решает: запас — свойство всего плана, а не
    отдельной задачи. Сократите что-нибудь и вызовите справку заново.
    """
    _require(task_id)
    plan = recalculate()
    rows = {row["id"]: row for row in plan["tasks"]}
    target = rows[task_id]

    ancestors, queue = set(), list(target["predecessors"])
    while queue:
        current = queue.pop()
        if current in ancestors:
            continue
        ancestors.add(current)
        queue.extend(rows[current]["predecessors"])

    deadline = date.fromisoformat(required_finish)
    finish = date.fromisoformat(target["finish"])
    return {
        "task": target["name"],
        "current_finish": target["finish"],
        "required_finish": required_finish,
        "fits": finish <= deadline,
        "days_short": max(0, (finish - deadline).days),
        "own_duration": target["duration"],
        "on_critical_path": target["on_critical_path"],
        "slack": target["slack"],
        "predecessors_chain": [
            {"id": a, "name": rows[a]["name"], "duration": rows[a]["duration"],
             "on_critical_path": rows[a]["on_critical_path"]}
            for a in sorted(ancestors, key=lambda a: -rows[a]["duration"])
        ],
    }
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `24 passed`.

- [ ] **Step 5: Проверить, что модели видно ровно десять инструментов**

```bash
cd backend && ../.venv/bin/python -c "
import asyncio, plan_mcp_server as s
names = sorted(t.name for t in asyncio.run(s.srv.list_tools()))
print(len(names), names)
"
```

Ожидается: `11` имён, из них одно `_load_plan` — то есть модели после фильтрации достанется десять.

- [ ] **Step 6: Коммит**

```bash
git add backend/plan_mcp_server.py backend/test_plan.py
git commit -m "feat: explain_deadline reference tool"
```

---

### Task 9: Импорт Excel в два прохода

**Files:**
- Create: `backend/excel_io.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py` (импорты в начале файла дополнить строкой `import io` и `import excel_io`):

```python
def make_xlsx(rows):
    """Собрать файл в память: шапка плюс переданные строки."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Задача", "Описание", "Исполнитель", "Длительность", "Предшественники"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_import_resolves_forward_reference():
    """Строка ссылается на задачу, которая идёт ниже по файлу."""
    data = make_xlsx([
        ["Тестирование", "", "Петров", 4, "Разработка"],
        ["Разработка", "", "Иванов", 10, "Проектирование"],
        ["Проектирование", "", "Иванов", 5, ""],
    ])
    tasks, errors = excel_io.parse_excel(data)
    assert errors == []
    by_id = {t["id"]: t for t in tasks}
    testing = next(t for t in tasks if t["name"] == "Тестирование")
    assert [by_id[p]["name"] for p in testing["predecessors"]] == ["Разработка"]


def test_import_reports_row_and_column_for_unknown_predecessor():
    data = make_xlsx([
        ["Проектирование", "", "Иванов", 5, ""],
        ["Разработка", "", "Иванов", 10, "Проктирование"],  # опечатка
    ])
    tasks, errors = excel_io.parse_excel(data)
    assert tasks == []
    assert len(errors) == 1
    assert errors[0]["row"] == 3  # шапка занимает первую строку
    assert errors[0]["column"] == "Предшественники"
    assert "Проктирование" in errors[0]["message"]


def test_import_collects_all_errors_at_once():
    data = make_xlsx([
        ["", "", "Иванов", 5, ""],
        ["Разработка", "", "Иванов", "десять", ""],
        ["Тестирование", "", "Петров", 4, "Нет такой"],
    ])
    tasks, errors = excel_io.parse_excel(data)
    assert tasks == []
    assert len(errors) == 3
    assert [e["row"] for e in errors] == [2, 3, 4]


def test_import_catches_cycle_by_names():
    data = make_xlsx([
        ["А", "", "", 1, "В"],
        ["Б", "", "", 1, "А"],
        ["В", "", "", 1, "Б"],
    ])
    tasks, errors = excel_io.parse_excel(data)
    assert tasks == []
    assert len(errors) == 1
    message = errors[0]["message"]
    assert "А" in message and "Б" in message and "В" in message
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'excel_io'`.

- [ ] **Step 3: Реализовать разбор**

`backend/excel_io.py`:

```python
"""Импорт и экспорт плана в Excel.

В файле предшественники записаны именами, в базе — id. Разбор идёт в два
прохода: порядок строк произволен, и ссылка вперёд по файлу иначе теряется.
"""

import io

from openpyxl import Workbook, load_workbook

COLUMNS = ["Задача", "Описание", "Исполнитель", "Длительность", "Предшественники"]
FIRST_DATA_ROW = 2


def _split_names(cell) -> list[str]:
    if cell in (None, ""):
        return []
    return [part.strip() for part in str(cell).split(",") if part.strip()]


def parse_excel(data: bytes):
    """Разобрать файл. Возвращает (задачи, ошибки).

    Ошибки собираются все сразу и указывают на строку и колонку. Если ошибка
    хотя бы одна, задачи не возвращаются: частичная загрузка не ломает расчёты,
    а даёт молча неверный ответ.
    """
    workbook = load_workbook(io.BytesIO(data))
    sheet = workbook.active
    rows = list(sheet.iter_rows(min_row=FIRST_DATA_ROW, values_only=True))

    errors = []
    names = {}
    tasks = []

    # Первый проход: раздать id, заполнить словарь имён. Связи не трогаем.
    for offset, row in enumerate(rows):
        row_number = FIRST_DATA_ROW + offset
        name = (row[0] or "").strip() if row and row[0] else ""
        if not name and not any(row or []):
            continue
        if not name:
            errors.append({"row": row_number, "column": "Задача",
                           "message": "пустое имя задачи"})
            continue
        if name in names:
            errors.append({"row": row_number, "column": "Задача",
                           "message": f"задача «{name}» встречается второй раз"})
            continue

        try:
            duration = int(row[3])
        except (TypeError, ValueError):
            errors.append({"row": row_number, "column": "Длительность",
                           "message": f"«{row[3]}» не число"})
            continue

        task_id = len(tasks) + 1
        names[name] = task_id
        tasks.append({"id": task_id, "name": name, "description": row[1] or "",
                      "assignee": row[2] or "", "duration": duration,
                      "predecessors": [], "not_earlier_than": None,
                      "_row": row_number, "_predecessor_names": _split_names(row[4])})

    # Второй проход: те же строки, теперь любое имя находится.
    for task in tasks:
        for predecessor_name in task["_predecessor_names"]:
            if predecessor_name not in names:
                errors.append({"row": task["_row"], "column": "Предшественники",
                               "message": f"задача «{predecessor_name}» не найдена"})
                continue
            task["predecessors"].append(names[predecessor_name])

    if not errors:
        errors.extend(_check_cycles(tasks))

    for task in tasks:
        del task["_row"]
        del task["_predecessor_names"]

    return ([], errors) if errors else (tasks, [])


def _check_cycles(tasks) -> list[dict]:
    """Тот же обход, что в recalculate, но без арифметики дат.

    Цикл ловится здесь, а не при пересчёте: тут известны имена и номера строк,
    а в recalculate только id — пользователь получил бы «Цикл: [1, 2, 3]».
    """
    indegree = {t["id"]: len(t["predecessors"]) for t in tasks}
    successors = {t["id"]: [] for t in tasks}
    for task in tasks:
        for p in task["predecessors"]:
            successors[p].append(task["id"])

    ready = [tid for tid, deg in indegree.items() if deg == 0]
    seen = 0
    while ready:
        tid = ready.pop()
        seen += 1
        for s in successors[tid]:
            indegree[s] -= 1
            if indegree[s] == 0:
                ready.append(s)

    if seen == len(tasks):
        return []

    stuck = [t for t in tasks if indegree[t["id"]] > 0]
    listed = ", ".join(f"«{t['name']}»" for t in stuck)
    return [{"row": min(t["_row"] for t in stuck), "column": "Предшественники",
             "message": f"циклическая зависимость между задачами: {listed}"}]
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `28 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/excel_io.py backend/test_plan.py
git commit -m "feat: two-pass Excel import with row-level errors and cycle check"
```

---

### Task 10: Экспорт Excel и круговой сценарий

**Files:**
- Modify: `backend/excel_io.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py`:

```python
def test_export_writes_predecessor_names_not_ids():
    set_tasks(branching_plan())
    data = excel_io.export_excel(srv.recalculate())
    from openpyxl import load_workbook
    sheet = load_workbook(io.BytesIO(data)).active
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    testing = next(r for r in rows if r[0] == "Тестирование")
    assert testing[4] == "Разработка, Документация"


def test_export_then_import_gives_the_same_plan():
    set_tasks(branching_plan())
    original = srv.recalculate()
    data = excel_io.export_excel(original)
    tasks, errors = excel_io.parse_excel(data)
    assert errors == []
    srv._load_plan(tasks=tasks, project_start=original["project_start"])
    restored = srv.recalculate()
    strip = lambda plan: [(t["name"], t["duration"], t["start"], t["finish"]) for t in plan["tasks"]]
    assert strip(restored) == strip(original)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `AttributeError: module 'excel_io' has no attribute 'export_excel'`.

- [ ] **Step 3: Реализовать экспорт**

В конец `backend/excel_io.py` дописать:

```python
def export_excel(plan) -> bytes:
    """Выгрузить план. Предшественники пишутся именами: файл должен грузиться обратно."""
    names = {task["id"]: task["name"] for task in plan["tasks"]}
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "План"
    sheet.append(COLUMNS)
    for task in plan["tasks"]:
        sheet.append([
            task["name"], task["description"], task["assignee"], task["duration"],
            ", ".join(names[p] for p in task["predecessors"]),
        ])
    for column, width in zip("ABCDE", (30, 40, 18, 14, 40)):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `30 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/excel_io.py backend/test_plan.py
git commit -m "feat: Excel export with predecessor names, round-trip covered"
```

**Изменения по итогам ревью (в коде они есть, в тексте выше — нет):**

- Добавлена **необязательная шестая колонка «Не раньше»**: без неё каждый сдвиг,
  записанный `shift_tasks` в виде ограничения, молча пропадал при обратной загрузке.
  Проверка шапки по-прежнему сверяет только первые пять колонок, поэтому файлы
  из пяти колонок читаются как раньше, а чужая шестая колонка игнорируется —
  читаем её, только если она названа «Не раньше».
- **Запятая в имени задачи запрещена** в `parse_excel` и в `add_task`. Запятая
  разделяет предшественников; схема экранирования — механика ради случая, которого
  никто не просил.
- **Повторяющиеся имена отклоняются** при создании задачи, а `export_excel`
  оставляет проверку как страховку: файл с двумя одинаковыми именами не загрузится
  обратно.
- Имя задачи обрезается по краям один раз — при создании.

---

### Task 11: Агентский цикл

**Files:**
- Create: `backend/agent_loop.py`
- Modify: `backend/test_plan.py`

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/test_plan.py` (в начало файла добавить `import agent_loop`):

```python
class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = "описание"
        self.input_schema = {"type": "object", "properties": {}}


class FakeToolsResult:
    def __init__(self, names):
        self.tools = [FakeTool(n) for n in names]


class FakeSession:
    """Подменяет MCP-сессию: список инструментов и вызовы без реального сервера."""

    def __init__(self, names):
        self._names = names
        self.calls = []

    async def list_tools(self):
        return FakeToolsResult(self._names)


def test_service_tools_are_hidden_from_the_model():
    import asyncio
    session = FakeSession(["get_plan", "shift_tasks", "_load_plan"])
    tools = asyncio.run(agent_loop.tools_for_model(session))
    names = [t["function"]["name"] for t in tools]
    assert names == ["get_plan", "shift_tasks"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}
```

- [ ] **Step 2: Запустить и убедиться, что падает**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `ModuleNotFoundError: No module named 'agent_loop'`.

- [ ] **Step 3: Реализовать цикл**

`backend/agent_loop.py`:

```python
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


async def call_tool(session, name: str, arguments: dict) -> str:
    """Выполнить инструмент. Ошибка возвращается текстом — модель должна её объяснить."""
    result = await session.call_tool(name, arguments)
    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    return text or ("ошибка" if result.is_error else "готово")


async def run_agent(session, messages: list[dict]) -> tuple[str, list[dict], bool]:
    """Прогнать диалог до текстового ответа.

    Возвращает (текст, дополненная история, упёрлись_в_потолок).
    """
    tools = await tools_for_model(session)
    payload_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    async with httpx.AsyncClient(timeout=120) as client:
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
                arguments = json.loads(call["function"]["arguments"] or "{}")
                result = await call_tool(session, call["function"]["name"], arguments)
                payload_messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": result})

    return ("Не смог выполнить это за разумное число шагов. План возвращён в исходное состояние.",
            payload_messages[1:], True)
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q
```

Ожидается: `31 passed`.

- [ ] **Step 5: Коммит**

```bash
git add backend/agent_loop.py backend/test_plan.py
git commit -m "feat: agent loop with MCP schema conversion and step ceiling"
```

---

### Task 12: HTTP-слой

**Files:**
- Create: `backend/api.py`

- [ ] **Step 1: Написать api.py**

`backend/api.py`:

```python
"""HTTP-слой: четыре сценария ТЗ — четыре эндпоинта. Все возвращают план целиком."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

import agent_loop
import excel_io

load_dotenv(Path(__file__).with_name(".env"))

SERVER = Path(__file__).with_name("plan_mcp_server.py")
history: list[dict] = []  # одна на приложение: см. ROADMAP, пункт 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    """MCP-сессия поднимается один раз на старте: это отдельный процесс."""
    parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            app.state.mcp = session
            yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # порт vite; в продакшене — закрытый список
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
    plan = await call("_load_plan", {"tasks": tasks, "project_start": _today()})
    history.clear()
    return plan


@app.post("/api/chat")
async def chat(request: ChatRequest):
    snapshot = await call("get_plan")
    history.append({"role": "user", "content": request.message})
    text, updated, gave_up = await agent_loop.run_agent(app.state.mcp, list(history))
    if gave_up:
        # Полусделанная последовательность операций хуже отказа.
        await call("_load_plan", {"tasks": snapshot["tasks"],
                                  "project_start": snapshot["project_start"]})
    else:
        history[:] = updated
    return {"reply": text, "plan": await call("get_plan")}


@app.get("/api/export")
async def export():
    plan = await call("get_plan")
    return Response(
        content=excel_io.export_excel(plan),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plan.xlsx"'},
    )


def _today() -> str:
    from datetime import date
    return date.today().isoformat()
```

- [ ] **Step 2: Поднять сервер**

```bash
cd backend && ../.venv/bin/python -m uvicorn api:app --port 8000 &
sleep 3
```

Ожидается: в логе `Application startup complete`, трейсбека нет.

- [ ] **Step 3: Проверить пустой план**

```bash
curl -s localhost:8000/api/plan
```

Ожидается: `{"project_start":"<сегодня>","project_finish":"<сегодня>","tasks":[]}`.

- [ ] **Step 4: Проверить импорт битого файла**

```bash
cd backend && ../.venv/bin/python -c "
from test_plan import make_xlsx
open('/tmp/broken.xlsx','wb').write(make_xlsx([['А','', '',5,'Нет такой']]))
"
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/broken.xlsx" localhost:8000/api/import
```

Ожидается: `422`.

- [ ] **Step 5: Остановить сервер и закоммитить**

```bash
kill %1
git add backend/api.py
git commit -m "feat: FastAPI endpoints over MCP session"
```

---

### Task 13: Демо-прогон и образец файла

**Files:**
- Create: `backend/demo_scenarios.py`
- Create: `sample_plan.xlsx` (генерируется)

- [ ] **Step 1: Написать demo_scenarios.py**

`backend/demo_scenarios.py`:

```python
"""Прогон инструментов без модели: детерминированно и не тратит запросы к API.

Запуск: python demo_scenarios.py [--sample]
  --sample — записать образец плана в ../sample_plan.xlsx
"""

import sys
from pathlib import Path

import excel_io
import plan_mcp_server as srv

SAMPLE = [
    ("Сбор требований", "Интервью с заказчиком", "Иванов", 4, []),
    ("Проектирование", "Схема данных и API", "Иванов", 5, ["Сбор требований"]),
    ("Дизайн интерфейса", "Макеты экранов", "Кузнецова", 6, ["Сбор требований"]),
    ("Разработка бэкенда", "", "Петров", 10, ["Проектирование"]),
    ("Разработка фронтенда", "", "Смирнов", 12, ["Проектирование", "Дизайн интерфейса"]),
    ("Интеграция", "", "Петров", 3, ["Разработка бэкенда", "Разработка фронтенда"]),
    ("Тестирование", "", "Николаева", 5, ["Интеграция"]),
    ("Исправление дефектов", "", "Петров", 4, ["Тестирование"]),
    ("Документация", "", "Кузнецова", 6, ["Интеграция"]),
    ("Приёмка", "", "Иванов", 2, ["Исправление дефектов", "Документация"]),
]


def load_sample():
    ids = {}
    tasks = []
    for number, (name, description, assignee, duration, predecessors) in enumerate(SAMPLE, 1):
        ids[name] = number
        tasks.append({"id": number, "name": name, "description": description,
                      "assignee": assignee, "duration": duration,
                      "predecessors": [ids[p] for p in predecessors],
                      "not_earlier_than": None})
    return srv._load_plan(tasks=tasks, project_start="2026-09-01")


def show(title, plan):
    print(f"\n=== {title} ===")
    print(f"конец проекта: {plan['project_finish']}")
    for task in plan["tasks"]:
        mark = "*" if task["on_critical_path"] else " "
        print(f" {mark} {task['name']:<24} {task['start']} → {task['finish']}"
              f"  запас {task['slack']:>2}  {task['assignee']}")


def main():
    show("исходный план", load_sample())
    show("сдвиг «Тестирования» на 3 дня", srv.shift_tasks(task_ids=[7], days=3))
    show("«Документация» сокращена до 2 дней", srv.set_duration(task_id=9, duration=2))
    show("исполнитель «Интеграции» — Николаева",
         srv.reassign_tasks(task_ids=[6], assignee="Николаева"))

    result = srv.delete_task(task_id=6)
    show("«Интеграция» удалена, наследники перевязаны", result["plan"])
    print("перевязано:", result["rebonded"])

    load_sample()
    print("\n=== справка по сроку «Приёмки» на 2026-09-25 ===")
    info = srv.explain_deadline(task_id=10, required_finish="2026-09-25")
    print(f"укладывается: {info['fits']}, не хватает дней: {info['days_short']}")
    for link in info["predecessors_chain"]:
        mark = "*" if link["on_critical_path"] else " "
        print(f" {mark} {link['name']:<24} {link['duration']} дн.")

    print("\n=== откат: попытка замкнуть цикл ===")
    before = srv.recalculate()
    try:
        srv.add_predecessor(task_id=1, predecessor_id=10)
    except ValueError as error:
        print("ошибка:", error)
    print("план не изменился:", srv.recalculate() == before)


def write_sample():
    plan = load_sample()
    path = Path(__file__).resolve().parent.parent / "sample_plan.xlsx"
    path.write_bytes(excel_io.export_excel(plan))
    print("записано:", path)


if __name__ == "__main__":
    write_sample() if "--sample" in sys.argv else main()
```

- [ ] **Step 2: Запустить прогон**

```bash
cd backend && ../.venv/bin/python demo_scenarios.py
```

Ожидается: пять блоков плана; звёздочками отмечен критический путь; удаление печатает перевязанные связи; последний блок печатает текст ошибки про цикл и `план не изменился: True`.

- [ ] **Step 3: Сгенерировать образец**

```bash
cd backend && ../.venv/bin/python demo_scenarios.py --sample
```

Ожидается: `записано: /home/yaponchiklin/Projects/Tests/sample_plan.xlsx`.

- [ ] **Step 4: Проверить, что образец грузится обратно без ошибок**

```bash
cd backend && ../.venv/bin/python -c "
import excel_io
tasks, errors = excel_io.parse_excel(open('../sample_plan.xlsx','rb').read())
print(len(tasks), 'задач, ошибок:', errors)
"
```

Ожидается: `10 задач, ошибок: []`.

- [ ] **Step 5: Коммит**

```bash
git add backend/demo_scenarios.py sample_plan.xlsx
git commit -m "feat: model-free demo run and sample plan file"
```

---

### Task 14: Каркас фронта и обращения к API

**Files:**
- Create: `frontend/` (шаблон Vite)
- Create: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/main.jsx`
- Create: `frontend/src/styles.css`

- [ ] **Step 1: Развернуть шаблон**

```bash
cd /home/yaponchiklin/Projects/Tests && npm create vite@latest frontend -- --template react && cd frontend && npm install
```

Ожидается: каталог `frontend/` с `package.json`, `index.html`, `src/main.jsx`, `src/App.jsx`.

- [ ] **Step 2: Удалить лишнее из шаблона**

```bash
cd frontend && rm -f src/App.css src/assets/react.svg public/vite.svg && rm -rf src/assets
```

- [ ] **Step 3: Написать модуль обращений**

`frontend/src/api.js`:

```javascript
const BASE = "http://localhost:8000/api";

async function unwrap(response) {
  if (response.status === 422) {
    const body = await response.json();
    const error = new Error("Файл отклонён");
    error.rows = body.detail;
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Сервер недоступен, попробуйте позже");
  }
  return response.json();
}

export function fetchPlan() {
  return fetch(`${BASE}/plan`).then(unwrap);
}

export function sendMessage(message) {
  return fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  }).then(unwrap);
}

export function importExcel(file) {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${BASE}/import`, { method: "POST", body: form }).then(unwrap);
}

export function exportUrl() {
  return `${BASE}/export`;
}
```

- [ ] **Step 4: Написать корневой компонент**

`frontend/src/App.jsx`:

```jsx
import { useEffect, useState } from "react";
import Chat from "./Chat";
import GanttChart from "./GanttChart";
import Toolbar from "./Toolbar";
import { fetchPlan } from "./api";
import "./styles.css";

export default function App() {
  const [plan, setPlan] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchPlan().then(setPlan).catch(() => setPlan(null));
  }, []);

  return (
    <div className="app">
      <Toolbar plan={plan} onPlan={setPlan} />
      <div className="workspace">
        <main className="chart-pane">
          {plan && plan.tasks.length > 0 ? (
            <GanttChart plan={plan} />
          ) : (
            <p className="empty">План пуст. Загрузите файл Excel или попросите чат добавить задачи.</p>
          )}
        </main>
        <Chat
          messages={messages}
          setMessages={setMessages}
          loading={loading}
          setLoading={setLoading}
          onPlan={setPlan}
        />
      </div>
    </div>
  );
}
```

`frontend/src/main.jsx`:

```jsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 5: Написать стили**

`frontend/src/styles.css`:

```css
:root {
  --bg: #ffffff;
  --ink: #1b1f24;
  --muted: #6a737d;
  --line: #d8dee4;
  --bar: #4c78a8;
  --bar-critical: #d1495b;
  --weekend: #f4f6f8;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }
body { margin: 0; color: var(--ink); background: var(--bg); }

.app { display: flex; flex-direction: column; height: 100vh; }
.workspace { display: flex; flex: 1; min-height: 0; }
.chart-pane { flex: 1; overflow: auto; padding: 12px; }
.empty { color: var(--muted); padding: 24px; }

.toolbar {
  display: flex; gap: 12px; align-items: center;
  padding: 10px 12px; border-bottom: 1px solid var(--line);
}
.toolbar button, .toolbar label {
  padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px;
  background: #fff; cursor: pointer; font: inherit;
}
.errors { border-top: 1px solid var(--line); background: #fff5f5; padding: 8px 12px; }
.errors li { color: var(--bar-critical); }

.chat { width: 380px; display: flex; flex-direction: column; border-left: 1px solid var(--line); }
.chat-log { flex: 1; overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.chat-message { padding: 8px 10px; border-radius: 8px; background: #f2f4f7; white-space: pre-wrap; }
.chat-message.user { background: #e7f0f8; align-self: flex-end; }
.chat-message.error { background: #fff0f0; color: var(--bar-critical); }
.chat-form { display: flex; gap: 8px; padding: 10px; border-top: 1px solid var(--line); }
.chat-form input { flex: 1; padding: 8px; border: 1px solid var(--line); border-radius: 6px; font: inherit; }

.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35);
  display: flex; align-items: center; justify-content: center;
}
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; min-width: 320px; }
.modal dt { color: var(--muted); font-size: 13px; margin-top: 8px; }
```

- [ ] **Step 6: Проверить сборку**

Файлы `GanttChart.jsx`, `Chat.jsx`, `Toolbar.jsx` появятся в следующих задачах, поэтому пока создать заглушки:

```bash
cd frontend/src && for f in GanttChart Chat Toolbar; do echo "export default function $f() { return null; }" > $f.jsx; done
npm run build --prefix ..
```

Ожидается: `built in ...`, ошибок нет.

- [ ] **Step 7: Коммит**

```bash
git add frontend
git commit -m "feat: frontend scaffold with API module and layout"
```

---

### Task 15: Диаграмма — шкала и полоски

**Files:**
- Modify: `frontend/src/GanttChart.jsx`

- [ ] **Step 1: Написать компонент**

`frontend/src/GanttChart.jsx`:

```jsx
import { useState } from "react";

const LABEL_WIDTH = 220;
const DAY_WIDTH = 24;
const ROW_HEIGHT = 34;
const BAR_HEIGHT = 18;
const HEADER_HEIGHT = 40;

const DAY = 24 * 60 * 60 * 1000;

export function daysBetween(from, to) {
  return Math.round((new Date(to) - new Date(from)) / DAY);
}

function geometry(plan) {
  const scaleStart = plan.tasks.reduce(
    (earliest, task) => (task.start < earliest ? task.start : earliest),
    plan.project_start
  );
  const totalDays = Math.max(daysBetween(scaleStart, plan.project_finish) + 2, 14);
  const rows = plan.tasks.map((task, index) => ({
    task,
    y: HEADER_HEIGHT + index * ROW_HEIGHT,
    x: LABEL_WIDTH + daysBetween(scaleStart, task.start) * DAY_WIDTH,
    width: Math.max(daysBetween(task.start, task.finish) * DAY_WIDTH, 4),
  }));
  return { scaleStart, totalDays, rows };
}

export default function GanttChart({ plan }) {
  const [selected, setSelected] = useState(null);
  const { scaleStart, totalDays, rows } = geometry(plan);
  const width = LABEL_WIDTH + totalDays * DAY_WIDTH;
  const height = HEADER_HEIGHT + rows.length * ROW_HEIGHT + 10;

  const days = Array.from({ length: totalDays }, (_, i) => {
    const date = new Date(new Date(scaleStart).getTime() + i * DAY);
    return { i, date, weekend: date.getDay() === 0 || date.getDay() === 6 };
  });

  return (
    <svg width={width} height={height} role="img" aria-label="Диаграмма Гантта">
      {days.map(({ i, date, weekend }) => (
        <g key={i}>
          {weekend && (
            <rect x={LABEL_WIDTH + i * DAY_WIDTH} y={HEADER_HEIGHT}
                  width={DAY_WIDTH} height={height - HEADER_HEIGHT} fill="var(--weekend)" />
          )}
          <line x1={LABEL_WIDTH + i * DAY_WIDTH} y1={HEADER_HEIGHT}
                x2={LABEL_WIDTH + i * DAY_WIDTH} y2={height} stroke="var(--line)" />
          {date.getDate() % 2 === 1 && (
            <text x={LABEL_WIDTH + i * DAY_WIDTH + 3} y={HEADER_HEIGHT - 12}
                  fontSize="10" fill="var(--muted)">
              {date.getDate()}.{String(date.getMonth() + 1).padStart(2, "0")}
            </text>
          )}
        </g>
      ))}

      {rows.map(({ task, y, x, width: barWidth }) => (
        <g key={task.id} onClick={() => setSelected(task)} style={{ cursor: "pointer" }}>
          <text x={8} y={y + BAR_HEIGHT} fontSize="13" fill="var(--ink)">
            {task.name.length > 26 ? `${task.name.slice(0, 25)}…` : task.name}
          </text>
          <rect x={x} y={y + 4} width={barWidth} height={BAR_HEIGHT} rx="4"
                fill={task.on_critical_path ? "var(--bar-critical)" : "var(--bar)"} />
          <text x={x + barWidth + 6} y={y + BAR_HEIGHT} fontSize="11" fill="var(--muted)">
            {task.assignee}
          </text>
        </g>
      ))}
    </svg>
  );
}

export { LABEL_WIDTH, DAY_WIDTH, ROW_HEIGHT, BAR_HEIGHT, HEADER_HEIGHT, geometry };
```

Цвета берутся из переменных в `styles.css`: критический путь красный, остальное синее — две категории, различимые и в чёрно-белой печати за счёт разной светлоты. Если палитру придётся пересматривать (тёмная тема, больше категорий), правила лежат в скиле `dataviz` — спека ссылается на него именно для этого.

- [ ] **Step 2: Проверить сборку**

```bash
npm run build --prefix frontend
```

Ожидается: сборка проходит.

- [ ] **Step 3: Коммит**

```bash
git add frontend/src/GanttChart.jsx
git commit -m "feat: Gantt bars, day scale and weekend shading"
```

---

### Task 16: Стрелки зависимостей

**Files:**
- Modify: `frontend/src/GanttChart.jsx`

- [ ] **Step 1: Дописать построение маршрута**

В `frontend/src/GanttChart.jsx` перед `export default function GanttChart` дописать:

```jsx
const GAP = 12;

/**
 * Маршрут стрелки от финиша предшественника к старту наследника.
 *
 * Есть горизонтальный зазор — идём вправо, по вертикали, снова вправо.
 * Зазора нет (предшественник кончается ровно в день старта) — обходим ряд
 * снизу и подходим слева. Иначе линия ушла бы вправо и вернулась назад,
 * а наконечник смотрел бы не в ту сторону.
 */
export function arrowPath(from, to) {
  const x1 = from.x + from.width;
  const y1 = from.y + 4 + BAR_HEIGHT / 2;
  const x2 = to.x;
  const y2 = to.y + 4 + BAR_HEIGHT / 2;

  if (x2 - x1 >= GAP) {
    const mid = x1 + (x2 - x1) / 2;
    return `M ${x1} ${y1} H ${mid} V ${y2} H ${x2}`;
  }

  const detour = Math.max(y1, y2) + ROW_HEIGHT / 2;
  return `M ${x1} ${y1} H ${x1 + GAP / 2} V ${detour} H ${x2 - GAP} V ${y2} H ${x2}`;
}
```

- [ ] **Step 2: Отрисовать стрелки**

В том же файле, внутри `<svg>`, между блоком сетки и блоком полосок вставить:

```jsx
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3"
                orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L7,3 z" fill="var(--muted)" />
        </marker>
      </defs>

      {rows.flatMap(({ task, ...to }) =>
        task.predecessors.map((predecessorId) => {
          const from = rows.find((row) => row.task.id === predecessorId);
          if (!from) return null;
          return (
            <path key={`${predecessorId}-${task.id}`}
                  d={arrowPath(from, to)} fill="none"
                  stroke="var(--muted)" strokeWidth="1.2" markerEnd="url(#arrow)" />
          );
        })
      )}
```

Стрелки рисуются до полосок, чтобы полоска перекрывала линию, а не наоборот.

- [ ] **Step 3: Проверить оба маршрута глазами**

```bash
npm run build --prefix frontend
```

Ожидается: сборка проходит. Визуальная проверка — в задаче 20: в образце плана есть и случай с зазором («Тестирование» после «Интеграции» — зазора нет, задачи стык в стык), и случай с зазором («Документация» → «Приёмка»).

- [ ] **Step 4: Коммит**

```bash
git add frontend/src/GanttChart.jsx
git commit -m "feat: dependency arrows with separate route for zero-gap links"
```

---

### Task 17: Модалка задачи

**Files:**
- Modify: `frontend/src/GanttChart.jsx`

- [ ] **Step 1: Дописать модалку**

В `frontend/src/GanttChart.jsx` перед `export default function GanttChart` дописать компонент:

```jsx
function TaskModal({ task, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <h3>{task.name}</h3>
        <dl>
          <dt>Исполнитель</dt><dd>{task.assignee || "не назначен"}</dd>
          <dt>Длительность</dt><dd>{task.duration} дн.</dd>
          <dt>Сроки</dt><dd>{task.start} → {task.finish}</dd>
          <dt>Запас</dt>
          <dd>{task.on_critical_path ? "нет, задача на критическом пути" : `${task.slack} дн.`}</dd>
          {task.not_earlier_than && (<><dt>Не раньше</dt><dd>{task.not_earlier_than}</dd></>)}
          {task.description && (<><dt>Описание</dt><dd>{task.description}</dd></>)}
        </dl>
        <button onClick={onClose}>Закрыть</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Показать её из компонента**

Обернуть возвращаемое значение `GanttChart` во фрагмент: `<svg>…</svg>` остаётся как есть, после него добавить:

```jsx
      {selected && <TaskModal task={selected} onClose={() => setSelected(null)} />}
```

Так как `<svg>` и модалка теперь два узла, `return (` должен открываться `<>` и закрываться `</>`.

- [ ] **Step 3: Проверить сборку**

```bash
npm run build --prefix frontend
```

Ожидается: сборка проходит.

- [ ] **Step 4: Коммит**

```bash
git add frontend/src/GanttChart.jsx
git commit -m "feat: task detail modal with slack and constraint"
```

---

### Task 18: Чат

**Files:**
- Modify: `frontend/src/Chat.jsx`

- [ ] **Step 1: Написать компонент**

`frontend/src/Chat.jsx`:

```jsx
import { useState } from "react";
import { sendMessage } from "./api";

export default function Chat({ messages, setMessages, loading, setLoading, onPlan }) {
  const [text, setText] = useState("");

  async function submit(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message || loading) return;

    setMessages((log) => [...log, { role: "user", text: message }]);
    setText("");
    setLoading(true);
    try {
      const answer = await sendMessage(message);
      setMessages((log) => [...log, { role: "assistant", text: answer.reply }]);
      onPlan(answer.plan);
    } catch (error) {
      setMessages((log) => [...log, { role: "error", text: error.message }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <aside className="chat">
      <div className="chat-log">
        {messages.map((message, index) => (
          <div key={index} className={`chat-message ${message.role}`}>{message.text}</div>
        ))}
        {loading && <div className="chat-message">Думаю…</div>}
      </div>
      <form className="chat-form" onSubmit={submit}>
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Перенеси задачи Иванова на неделю вправо"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !text.trim()}>Отправить</button>
      </form>
    </aside>
  );
}
```

Оптимистичных обновлений нет: пока модель не ответила, ввод заблокирован. Результат фразы предсказать нельзя — это тот же дифф, от которого ушли в дизайне.

- [ ] **Step 2: Проверить сборку**

```bash
npm run build --prefix frontend
```

Ожидается: сборка проходит.

- [ ] **Step 3: Коммит**

```bash
git add frontend/src/Chat.jsx
git commit -m "feat: chat pane wired to /api/chat"
```

---

### Task 19: Панель импорта и экспорта

**Files:**
- Modify: `frontend/src/Toolbar.jsx`

- [ ] **Step 1: Написать компонент**

`frontend/src/Toolbar.jsx`:

```jsx
import { useState } from "react";
import { exportUrl, importExcel } from "./api";

export default function Toolbar({ plan, onPlan }) {
  const [errors, setErrors] = useState([]);
  const [message, setMessage] = useState("");

  async function upload(event) {
    const file = event.target.files[0];
    if (!file) return;
    setErrors([]);
    setMessage("");
    try {
      onPlan(await importExcel(file));
    } catch (error) {
      // 422 — файл прочитан, данные не годятся; в error.rows лежат строки и колонки.
      if (error.rows) setErrors(error.rows);
      else setMessage(error.message);
    } finally {
      event.target.value = "";
    }
  }

  return (
    <>
      <div className="toolbar">
        <label>
          Загрузить Excel
          <input type="file" accept=".xlsx" onChange={upload} style={{ display: "none" }} />
        </label>
        <a className="download" href={exportUrl()}>
          <button type="button" disabled={!plan || plan.tasks.length === 0}>Выгрузить Excel</button>
        </a>
        {plan && plan.tasks.length > 0 && (
          <span className="summary">
            Задач: {plan.tasks.length} · конец проекта: {plan.project_finish}
          </span>
        )}
        {message && <span className="summary">{message}</span>}
      </div>
      {errors.length > 0 && (
        <div className="errors">
          <strong>Файл отклонён целиком, исправьте и загрузите заново:</strong>
          <ul>
            {errors.map((error, index) => (
              <li key={index}>
                строка {error.row}, колонка «{error.column}»: {error.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 2: Проверить сборку**

```bash
npm run build --prefix frontend
```

Ожидается: сборка проходит.

- [ ] **Step 3: Коммит**

```bash
git add frontend/src/Toolbar.jsx
git commit -m "feat: import and export toolbar with row-level error list"
```

---

### Task 20: Живой прогон, README и ROADMAP

**Files:**
- Create: `docs/ROADMAP.md`
- Create: `README.md`

- [ ] **Step 1: Поднять оба процесса**

```bash
cd backend && ../.venv/bin/python -m uvicorn api:app --port 8000 &
npm run dev --prefix frontend &
sleep 4
curl -s localhost:8000/api/plan | head -c 120
```

Ожидается: JSON плана; vite сообщает `Local: http://localhost:5173/`.

- [ ] **Step 2: Загрузить образец и проверить диаграмму глазами**

Открыть `http://localhost:5173`, нажать «Загрузить Excel», выбрать `sample_plan.xlsx`.

Проверить по списку:
- полоски выстроены лесенкой, критический путь красный;
- у «Тестирования» после «Интеграции» зазора нет — стрелка обходит снизу и входит слева, наконечник смотрит вправо;
- у «Документация» → «Приёмка» зазор есть — стрелка идёт вправо, вниз, вправо;
- клик по полоске открывает модалку с запасом и сроками.

- [ ] **Step 3: Проверить чат вживую**

Отправить в чат: `Перенеси задачи Петрова на неделю вправо`.

Ожидается: модель вызывает `get_plan`, находит задачи Петрова, вызывает `shift_tasks`, диаграмма перерисовывается, в ленте появляется короткий ответ.

Затем отправить: `Приёмка должна закончиться до 25 сентября` — ожидается вызов `explain_deadline` и объяснение с числами, план при этом не меняется.

Затем: `Удали Интеграцию` — ожидается, что «Тестирование» и «Документация» получат предшественников удалённой задачи, а не уедут на старт проекта.

- [ ] **Step 4: Записать ROADMAP**

`docs/ROADMAP.md`:

```markdown
# Roadmap to production

Что сделано упрощённо, чем это грозит, что потребуется для боевого состояния.
Порядок — от того, что ломается первым при реальной нагрузке.

## 1. План живёт в памяти процесса

**Сейчас.** Словарь внутри MCP-сервера, один на всё приложение.
**Чем грозит.** План теряется при перезапуске и общий для всех, кто открыл страницу.
**Что нужно.** Хранилище (PostgreSQL), таблицы задач и связей, план привязан
к проекту, проект — к владельцу.

## 2. История диалога одна на приложение

**Сейчас.** Список сообщений на уровне модуля `api.py`.
**Чем грозит.** При двух пользователях фразы попадают в одну ленту. Первый
пишет «перенеси задачи Иванова на неделю», второй — «а теперь на Петрова»,
и модель считает это одним разговором. Ошибки не возникнет, план поменяется
не так, как хотел никто.
**Что нужно.** История на сессию пользователя, обрезка по длине контекста.

## 3. Нет блокировки на план

**Сейчас.** Два одновременных запроса правят один словарь.
**Чем грозит.** Параллельные правки накладываются, побеждает последняя.
**Что нужно.** Версия плана и проверка при записи: пришла правка на устаревшую
версию — 409 и предложение перечитать план.

## 4. Нет авторизации

**Сейчас.** Любой, кто открыл страницу, правит план.
**Что нужно.** Вход, права на проект, отдельно роль наблюдателя.

## 5. Календарные дни вместо рабочих

**Сейчас.** Сдвиг на 7 дней — семь суток, выходные внутри.
**Чем грозит.** Планы расходятся с реальными сроками команды.
**Что нужно.** Производственный календарь: выходные, праздники, регион проекта.
Формула пересчёта меняется в одном месте — `recalculate`.

## 6. CORS открыт на localhost

**Сейчас.** Разрешён `http://localhost:5173`.
**Что нужно.** Закрытый список доменов из конфигурации.

## 7. Нет истории операций и отката в интерфейсе

**Сейчас.** Откат есть только внутри одной операции и одной фразы.
**Чем грозит.** Неудачную правку нельзя отменить, кроме как повторной фразой.
**Что нужно.** Журнал операций. Он возможен по построению: единица изменения —
операция, откат — обратная операция.
```

- [ ] **Step 5: Записать README**

`README.md`:

```markdown
# Диаграмма Гантта с редактированием через чат

План работ рисуется диаграммой Гантта, правится фразами на естественном языке
и обменивается с Excel в обе стороны.

## Главное правило

Модель задаёт намерение, код вычисляет следствия. Агент не возвращает новый
план — он вызывает инструменты («сдвинуть задачи 12, 15, 40 на +7»), а даты
пересчитывает код. Переписывая двести задач ради изменения трёх, мы дали бы
модели сто девяносто семь возможностей ошибиться там, где ошибка не требовалась.

## Запуск

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp backend/.env.example backend/.env   # вписать ключ OpenRouter

cd backend && ../.venv/bin/python -m uvicorn api:app --port 8000
npm install --prefix frontend && npm run dev --prefix frontend
```

Открыть `http://localhost:5173`, загрузить `sample_plan.xlsx`.

## Проверка

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q   # расчёты, инструменты, Excel
cd backend && ../.venv/bin/python demo_scenarios.py           # прогон инструментов без модели
```

## Как это устроено

Три процесса: MCP-сервер (stdio) с планом и инструментами, FastAPI с агентским
циклом и одной MCP-сессией на всё приложение, React с диаграммой.

| Файл | Содержимое |
|---|---|
| `backend/plan_mcp_server.py` | Хранилище, `recalculate`, десять инструментов + служебный `_load_plan` |
| `backend/agent_loop.py` | Конвертация схем MCP → OpenRouter, цикл вызовов |
| `backend/excel_io.py` | Импорт в два прохода, проверка циклов, экспорт |
| `backend/api.py` | Четыре эндпоинта, CORS, `lifespan` |
| `frontend/src/GanttChart.jsx` | Полоски, стрелки, модалка |

Дат в базе нет. Хранятся длительности, связи и ограничения «не раньше»;
старт задачи — максимум финишей предшественников, ограничения и старта проекта.
Обратный проход даёт запас и критический путь.

Инструменты подобраны прогоном реальных фраз до конца: где сценарий упирался
в отсутствие операции, там появлялся инструмент. Форма аргументов выбиралась
по вопросу «что произойдёт, если модель ошибётся»: `add_predecessor` вместо
полного списка зависимостей, `days` вместо готовой даты.

Известные упрощения и порядок их закрытия — в `docs/ROADMAP.md`.

## Использование AI-ассистентов

Проект сделан в паре с Claude (Claude Code). Разбор архитектуры вёлся диалогом:
контракт между чатом и планом, состав инструментов, обработка конфликтов и
разбор Excel — результат этого разбора, он сохранён в `session_notes.md` и
`docs/superpowers/specs/`. Ассистент писал код по утверждённому плану
(`docs/superpowers/plans/`), тесты писались до реализации.
```

- [ ] **Step 6: Прогнать всё разом**

```bash
cd backend && ../.venv/bin/python -m pytest test_plan.py -q && ../.venv/bin/python demo_scenarios.py > /dev/null && echo DEMO_OK
npm run build --prefix frontend
```

Ожидается: `31 passed`, `DEMO_OK`, сборка фронта без ошибок.

- [ ] **Step 7: Остановить процессы и закоммитить**

```bash
kill %1 %2 2>/dev/null
git add README.md docs/ROADMAP.md
git commit -m "docs: readme and production roadmap"
```

---

## Что осталось за рамками плана

Названо в спеке, сознательно не делается: деплой, демо-видео, кнопки undo/redo
в интерфейсе, тесты фронта (вычислений там нет — только перевод чисел в координаты).
