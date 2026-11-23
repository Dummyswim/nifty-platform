FROM python:3.14-slim
WORKDIR /app
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/src ./src
COPY backend/alembic ./alembic
RUN pip install --no-cache-dir .
