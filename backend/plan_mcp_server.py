"""MCP-сервер плана работ: хранилище, пересчёт дат, инструменты агента."""

import copy
from contextlib import contextmanager
from datetime import date, timedelta

from mcp.server import MCPServer

srv = MCPServer("plan")

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

    late_finish = {}
    for tid in reversed(order):
        late_starts = [late_finish[s] - timedelta(days=tasks[s]["duration"])
                       for s in successors[tid]]
        late_finish[tid] = min(late_starts, default=project_finish)

    slack = {tid: (late_finish[tid] - finish[tid]).days for tid in order}

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
            "slack": slack[tid],
            "on_critical_path": slack[tid] == 0,
        })

    return {
        "project_start": STATE["project_start"].isoformat(),
        "project_finish": project_finish.isoformat(),
        "tasks": rows,
    }


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
    """Найти задачу или объяснить, что её нет.

    Возвращает живой словарь из STATE: менять его можно только внутри
    `with _transaction():`, иначе правка останется без снимка и отката.
    """
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
        ids = [t["id"] for t in tasks]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"Повторяющиеся id задач: {duplicates}")
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


@srv.tool()
def shift_tasks(task_ids: list[int], days: int) -> dict:
    """Сдвинуть задачи на указанное число дней. Положительное — вправо, отрицательное — влево.

    Сдвиг считается от текущего старта: он уже учитывает и предшественников,
    и прежнее ограничение. Наследники сдвигаются сами при пересчёте.
    """
    with _transaction():
        starts = {row["id"]: date.fromisoformat(row["start"])
                  for row in recalculate()["tasks"]}
        for task_id in task_ids:
            task = _require(task_id)  # проверка ДО чтения starts[task_id]: иначе KeyError обгоняет ValueError
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


@srv.tool()
def add_task(name: str, duration: int, assignee: str = "",
             predecessors: list[int] | None = None, description: str = "") -> dict:
    """Добавить задачу. Даты не задаются — они вычисляются из предшественников."""
    with _transaction():
        name = name.strip()
        if "," in name:
            raise ValueError("Имя задачи не может содержать запятую: она разделяет предшественников")
        if any(t["name"] == name for t in STATE["tasks"].values()):
            raise ValueError(f"Задача с именем «{name}» уже есть")
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
        task = _require(task_id)
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


@srv.tool()
def explain_deadline(task_id: int, required_finish: str, inclusive: bool = True) -> dict:
    """Справка: укладывается ли задача в срок и что этому мешает. Ничего не меняет.

    `required_finish` — дата так, как её назвал пользователь, в формате ГГГГ-ММ-ДД.
    Пересчитывать её не нужно: `inclusive=True` (по умолчанию) значит «успеть до конца
    этого дня включительно», `inclusive=False` — «закончить строго раньше этой даты».

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
    if inclusive:
        deadline += timedelta(days=1)  # хранимый finish — день после последнего рабочего
    finish = date.fromisoformat(target["finish"])
    return {
        "task": target["name"],
        "current_finish": target["finish"],
        "required_finish": required_finish,
        "inclusive": inclusive,
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


if __name__ == "__main__":
    srv.run("stdio")
