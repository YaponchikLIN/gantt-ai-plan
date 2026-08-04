import { useEffect, useState } from "react";

// Колонка слева держит и название задачи, и исполнителя, поэтому она шире
// обычного: в поле диаграммы текста нет вовсе, там только полоски и стрелки.
const LABEL_WIDTH = 320;
const DAY_WIDTH = 20;
const ROW_HEIGHT = 34;
const BAR_HEIGHT = 18;
const HEADER_HEIGHT = 40;

const DAY = 24 * 60 * 60 * 1000;

function daysBetween(from, to) {
  return Math.round((new Date(to) - new Date(from)) / DAY);
}

function clip(text, limit) {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

// "YYYY-MM-DD" parses as UTC midnight; reading it back with getDate()/getDay()
// in a timezone behind UTC (e.g. the Americas) lands on the previous local day.
// Building the Date from local y/m/d components keeps the header's weekday and
// day-of-month correct regardless of the browser's timezone.
function parseLocalDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
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

function TaskModal({ task, onClose }) {
  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // onClose is a fresh `() => setSelected(null)` identity each render;
    // omitted since it always does the same thing and re-subscribing on
    // every render buys nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

const MIN_TAIL = 6;
const CLEARANCE = 8;
const MAX_BACK = 40;

/**
 * Маршрут стрелки, не задевающий чужие полоски.
 *
 * Полоски занимают только середину своей строки, между строками остаётся
 * свободный коридор. Поэтому вертикаль можно поставить там, где полосок
 * пересекаемых строк нет: начинаем сразу за финишем предшественника и, пока
 * вертикаль упирается в чью-то полоску, отодвигаем её вправо за эту полоску.
 *
 * Дальше три исхода. Вертикаль осталась левее наследника — входим в его левый
 * край. Попала в его полоску — входим сверху (или снизу, если наследник выше).
 * Уехала правее всей полоски — возвращаемся по коридору перед строкой
 * наследника: там полосок нет, так что обратный отрезок ничего не задевает.
 */
function arrowPath(from, to, rows) {
  const x1 = from.x + from.width;
  const y1 = from.y + 4 + BAR_HEIGHT / 2;
  const x2 = to.x;
  const y2 = to.y + 4 + BAR_HEIGHT / 2;
  const down = to.y > from.y;
  const edge = down ? to.y + 4 : to.y + 4 + BAR_HEIGHT;

  const crossed = rows.filter((row) =>
    down ? row.y > from.y && row.y < to.y : row.y < from.y && row.y > to.y
  );
  const clear = (x) => !crossed.some((row) => x > row.x && x < row.x + row.width);
  const slide = (x, step) => {
    for (let pass = 0; pass <= crossed.length && !clear(x); pass += 1) {
      const blocking = crossed.find((row) => x > row.x && x < row.x + row.width);
      x = step > 0 ? blocking.x + blocking.width + CLEARANCE : blocking.x - CLEARANCE;
    }
    return x;
  };

  // Справа от финиша предшественника — если так удаётся войти в левый край
  // наследника, это лучший вариант: стрелка приходит ровно в начало задачи.
  const right = slide(x1 + CLEARANCE, +1);
  if (x2 - right >= MIN_TAIL) return `M ${x1} ${y1} H ${right} V ${y2} H ${x2}`;

  // Задачи стык в стык: входим сверху у самого начала полоски. Крюк назад тут
  // был бы лишним — обходить нечего.
  if (right <= x2 + MAX_BACK) return `M ${x1} ${y1} H ${right} V ${edge}`;

  // Правый обход увёл далеко в середину полоски. Пробуем слева от старта
  // наследника: короткий крюк назад читается привычно, так рисует MS Project.
  const left = slide(x2 - CLEARANCE, -1);
  if (x1 - left <= MAX_BACK) return `M ${x1} ${y1} H ${left} V ${y2} H ${x2}`;

  // Обе стороны далеко: уходим вправо мимо всех помех, возвращаемся по коридору
  // перед строкой наследника — там полосок нет по построению — и входим сверху.
  const corridor = down ? to.y - 6 : to.y + ROW_HEIGHT - 6;
  const entry = Math.min(x2 + CLEARANCE, x2 + to.width - 2);
  return `M ${x1} ${y1} H ${right} V ${corridor} H ${entry} V ${edge}`;
}

export default function GanttChart({ plan }) {
  const [selected, setSelected] = useState(null);
  // plan is replaced wholesale on chat/import updates; a stale `selected`
  // would otherwise show slack/dates for a task the new plan may not have.
  useEffect(() => setSelected(null), [plan]);
  const { scaleStart, totalDays, rows } = geometry(plan);
  const width = LABEL_WIDTH + totalDays * DAY_WIDTH;
  const height = HEADER_HEIGHT + rows.length * ROW_HEIGHT + 10;

  const days = Array.from({ length: totalDays }, (_, i) => {
    const date = parseLocalDate(scaleStart);
    date.setDate(date.getDate() + i);
    return { i, date, weekend: date.getDay() === 0 || date.getDay() === 6 };
  });

  return (
    <>
    <svg width={width} height={height} role="img" aria-label="Диаграмма Гантта">
      {days.map(({ i, date, weekend }) => (
        <g key={i}>
          {weekend && (
            <rect x={LABEL_WIDTH + i * DAY_WIDTH} y={HEADER_HEIGHT}
                  width={DAY_WIDTH} height={height - HEADER_HEIGHT} fill="var(--weekend)" />
          )}
          <line x1={LABEL_WIDTH + i * DAY_WIDTH} y1={HEADER_HEIGHT}
                x2={LABEL_WIDTH + i * DAY_WIDTH} y2={height} stroke="var(--line)" />
          {i % 2 === 0 && (
            <text x={LABEL_WIDTH + i * DAY_WIDTH + 3} y={HEADER_HEIGHT - 12}
                  fontSize="10" fill="var(--muted)">
              {date.getDate()}.{String(date.getMonth() + 1).padStart(2, "0")}
            </text>
          )}
        </g>
      ))}

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
                  d={arrowPath(from, to, rows)} fill="none"
                  stroke="var(--muted)" strokeWidth="1.2" markerEnd="url(#arrow)" />
          );
        })
      )}

      {rows.map(({ task, y, x, width: barWidth }) => (
        <g key={task.id} onClick={() => setSelected(task)}
           onKeyDown={(event) => {
             if (event.key === "Enter" || event.key === " ") {
               event.preventDefault();
               setSelected(task);
             }
           }}
           role="button" tabIndex={0} aria-label={`${task.name}, ${task.start} — ${task.finish}`}
           style={{ cursor: "pointer" }}>
          <text x={8} y={y + BAR_HEIGHT} fontSize="13" fill="var(--ink)">
            {clip(task.name, 24)}
          </text>
          {/* Исполнитель — в левой колонке, а не у полоски: в поле диаграммы
              ходят стрелки, и любой текст там рано или поздно ими перечёркивается.
              Отступ 12 держит запас: левее LABEL_WIDTH − CLEARANCE стрелка уйти
              не может, так что подписи и линии не встречаются вовсе. */}
          <text x={LABEL_WIDTH - 12} y={y + BAR_HEIGHT} fontSize="11" textAnchor="end"
                fill="var(--muted)">
            {clip(task.assignee, 14)}
          </text>
          <rect x={x} y={y + 4} width={barWidth} height={BAR_HEIGHT} rx="4"
                fill={task.on_critical_path ? "var(--bar-critical)" : "var(--bar)"} />
        </g>
      ))}
    </svg>
      {selected && <TaskModal task={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
