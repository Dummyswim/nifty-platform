FROM python:3.14-slim
# mirror the repo layout: code resolves alembic/, data/ and .env relative to its own location
WORKDIR /app/backend
COPY backend/pyproject.toml backend/alembic.ini backend/requirements.lock ./
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY data /app/data
RUN pip install --no-cache-dir -c requirements.lock -e .
