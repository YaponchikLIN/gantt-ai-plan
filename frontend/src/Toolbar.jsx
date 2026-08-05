import { useState } from "react";
import { exportUrl, importExcel } from "./api";

export default function Toolbar({ plan, onPlan, loading }) {
  const [errors, setErrors] = useState([]);
  const [message, setMessage] = useState("");

  async function upload(event) {
    const file = event.target.files[0];
    if (!file || loading) return;
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
        <label className={loading ? "disabled" : undefined}>
          {loading ? "Модель отвечает…" : "Загрузить Excel"}
          <input
            type="file"
            accept=".xlsx"
            onChange={upload}
            disabled={loading}
            style={{ display: "none" }}
          />
        </label>
        {plan && plan.tasks.length > 0 ? (
          <a className="download" href={exportUrl()}>
            Выгрузить Excel
          </a>
        ) : (
          <button type="button" disabled>
            Выгрузить Excel
          </button>
        )}
        {plan && plan.tasks.length > 0 && (
          <span className="summary">
            Задач: {plan.tasks.length} · конец проекта: {plan.project_finish}
            {plan.deadline && <> · дедлайн: {plan.deadline}</>}
          </span>
        )}
        {plan && plan.fits_deadline === false && (
          <span className="late">опоздание на {plan.days_late} дн.</span>
        )}
        {plan && plan.fits_deadline === true && (
          <span className="summary">в срок</span>
        )}
        {message && <span className="summary">{message}</span>}
      </div>
      {errors.length > 0 && (
        <div className="errors">
          <strong>Файл отклонён целиком, исправьте и загрузите заново:</strong>
          <ul>
            {errors.map((error, index) => (
              <li key={index}>
                {error.row
                  ? `строка ${error.row}, колонка «${error.column}»: ${error.message}`
                  : `${error.column}: ${error.message}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
