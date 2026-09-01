# syntax=docker/dockerfile:1

# Build-only image — produces dist/, nothing else. No nginx here: this repo
# runs a single host-level nginx in front of both the static frontend and the
# backend (see docker-compose.yml/deploy/nginx for why), so this image is
# never run as a long-lived container, only `docker compose build`/`run` to
# populate the frontend_dist volume.

FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked in at build time — the SPA calls the backend through nginx's /api/
# proxy on the same origin (see deploy/nginx), not a separate host, so a
# same-origin relative path works for every environment this image is built
# for and needs no other build args.
ENV VITE_API_BASE_URL=/api

RUN npm run build

# docker-compose copies /app/dist out of this stage onto the frontend_dist
# volume (see the frontend service's command) — no CMD/ENTRYPOINT needed for
# a container that only ever runs once to produce that output.
