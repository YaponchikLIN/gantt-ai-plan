"""Прогон инструментов без модели: детерминированно и не тратит запросы к API.

Запуск: python demo_scenarios.py [--sample]
  --sample — записать ../sample_plan.xlsx и ../demo_plan.xlsx
"""

import sys
from pathlib import Path

import excel_io
import plan_mcp_server as srv
from sample_data import demo_tasks, sample_tasks


def load_sample():
    """Дата старта здесь фиксированная: демо должно печатать одно и то же."""
    return srv._load_plan(tasks=sample_tasks(), project_start="2026-09-01")


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
    """Оба файла: образец из ТЗ и другой план для демонстрации загрузки.

    Второй нужен именно другим: если загрузить план, совпадающий с тем, что
    подставляется при старте, диаграмма не изменится и показывать будет нечего.
    """
    root = Path(__file__).resolve().parent.parent
    for name, tasks in (("sample_plan.xlsx", sample_tasks()), ("demo_plan.xlsx", demo_tasks())):
        plan = srv._load_plan(tasks=tasks, project_start="2026-09-01")
        path = root / name
        path.write_bytes(excel_io.export_excel(plan))
        print("записано:", path, f"({len(plan['tasks'])} задач)")


if __name__ == "__main__":
    write_sample() if "--sample" in sys.argv else main()
