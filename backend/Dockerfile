# syntax=docker/dockerfile:1

# --- build stage: compile deps (psycopg[binary]/pgvector wheels, ortools) ---
# separately from the runtime image, so the final image doesn't carry
# compilers/headers it never needs at run time.
FROM python:3.10-slim AS build

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

# Installs into the system site-packages of THIS stage only; copied wholesale
# into the runtime stage below rather than re-resolved there.
RUN pip install --no-cache-dir --prefix=/install .

# --- runtime stage ---
FROM python:3.10-slim AS runtime

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=build /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY data ./data

USER app

# Binds 0.0.0.0 *inside the container* so other containers on the compose
# network (nginx) can reach it by service name — this is not "exposed to the
# internet": docker-compose.yml never publishes this port to the host (no
# `ports:` mapping), so it is unreachable from outside the docker network.
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
