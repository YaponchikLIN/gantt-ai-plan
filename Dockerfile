# --- stage 1: build the frontend -------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_BASE=/api npm run build

# --- stage 2: backend + built frontend, same-origin -------------------------------
FROM python:3.12-slim
WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY --from=frontend /app/frontend/dist frontend/dist

USER appuser
EXPOSE 8080
# Порт берётся из окружения: Render и подобные площадки задают его сами, локально — 8080.
CMD ["sh", "-c", "python -m uvicorn api:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8080}"]
