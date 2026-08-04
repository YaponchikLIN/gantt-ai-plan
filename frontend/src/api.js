// Порт бэкенда можно переопределить: VITE_API_BASE=http://localhost:8010/api npm run dev
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";

async function unwrap(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const rows = body.detail;
    if (response.status === 422 && Array.isArray(rows) && rows.every((row) => "row" in row)) {
      const error = new Error("Файл отклонён");
      error.rows = rows;
      throw error;
    }
    const detail = typeof body.detail === "string" ? body.detail : null;
    throw new Error(detail || "Сервер недоступен, попробуйте позже");
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
