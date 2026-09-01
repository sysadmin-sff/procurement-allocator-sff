# Деплой

Требования к продовому окружению, без которых части системы не работают
как задумано. Не общая инструкция по установке — только то, что нельзя
вывести из кода.

## Обязательно: reverse proxy и `TRUSTED_PROXY_IP`

ADR-0024 §9 требует HTTPS, а значит перед приложением стоит reverse proxy,
терминирующий TLS. Из-за этого `request.client.host` для backend — это
адрес прокси, один и тот же для всех сотрудников. Rate limiting на
`/auth/login` и `/auth/callback` (ADR-0024 §10) считает лимит по клиенту,
поэтому ему нужен реальный адрес клиента из `X-Forwarded-For`.

Заголовок можно подделать, поэтому приложение доверяет ему только когда
TCP-пир запроса в точности равен `TRUSTED_PROXY_IP`
(`backend/app/core/rate_limit.py`, `client_ip`). Отсюда два обязательных
условия — оба, по отдельности ни одно не достаточно.

### 1. Прокси должен ЗАМЕНЯТЬ `X-Forwarded-For`, а не дополнять

```nginx
proxy_set_header X-Forwarded-For $remote_addr;
```

**Не** `proxy_add_x_forwarded_for`. Это распространённый дефолт из
примеров конфигов, и он *дополняет* список: если клиент прислал свой
`X-Forwarded-For`, прокси допишет реальный адрес справа, а приложение
читает **левый** элемент — то есть значение, полностью подконтрольное
вызывающей стороне. Результат: любой может назначить себе чужой адрес
(потратить лимит коллеги) или менять его на каждый запрос и не
лимитироваться вовсе.

### 2. `TRUSTED_PROXY_IP` должен быть выставлен в адрес прокси

```
TRUSTED_PROXY_IP=10.0.0.9
```

Значение сравнивается с `request.client.host` дословно, поэтому это
должен быть **IP**, каким его видит сокет backend, а не hostname и не
URL. Если backend и прокси в Docker/Compose — это адрес прокси во
внутренней сети, а не публичный адрес.

### Что происходит, если условия не выполнены

| Ситуация | Последствие |
|---|---|
| `TRUSTED_PROXY_IP` не задан | Заголовок игнорируется всегда. Лимит **не обходится**, но считает весь офис за одного клиента: 10 запросов в минуту на всех, одиннадцатый вход получает 429. Fail-safe, но входы ломаются. |
| `TRUSTED_PROXY_IP` задан неверно (не совпал с пиром) | То же самое — заголовок игнорируется, весь офис в одном ведре. |
| `TRUSTED_PROXY_IP` верный, но nginx с `proxy_add_x_forwarded_for` | Левый элемент подконтролен клиенту: лимит обходится подстановкой произвольного адреса. Единственный из четырёх вариантов, который **снимает** защиту. |
| Порт backend доступен в обход прокси | Прямое подключение имеет собственный пир, не равный `TRUSTED_PROXY_IP`, поэтому его заголовок игнорируется — лимит считается по реальному адресу подключившегося. Обхода нет. |

Проверка после деплоя: сделать 11 запросов подряд к `/auth/login` с
одного клиента — одиннадцатый должен вернуть `429` с телом
`{"detail": "Too many requests, please try again later."}`. Затем то же
с другой машины — она не должна быть заблокирована. Если блокируется,
`TRUSTED_PROXY_IP` или заголовок настроены неверно.

## Остальные обязательные переменные окружения

Полный список и значения по умолчанию — `Settings` в
`backend/app/core/config.py`, там же назначение каждой в docstring.
Критичные для прода:

| Переменная | Замечание |
|---|---|
| `DATABASE_URL` | — |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_WORKSPACE_DOMAIN` | Без них `/auth/*` отвечает 500 (ADR-0024 §8). |
| `SESSION_SIGNING_SECRET` | Подпись короткоживущей cookie oauth-флоу. |
| `BOOTSTRAP_ADMIN_EMAIL` | Первый админ создаётся на старте (ADR-0024 §2). |
| `FRONTEND_URL` | Абсолютный URL, иначе редирект после логина резолвится относительно backend. |
| `BACKEND_PUBLIC_URL` | Внешний адрес backend'а (схема+хост+path-префикс), ровно как зарегистрирован в Google Cloud Console. За host nginx с `/api/`-prefix-stripping — `https://<домен>/api`. См. ниже, отдельный раздел. |
| `COOKIE_SECURE` | Оставить `true`; `false` только для локального HTTP. |
| `TRUSTED_PROXY_IP` | См. выше. |

## `BACKEND_PUBLIC_URL` — OAuth `redirect_uri` не выводится из запроса

`GET /auth/login` и `GET /auth/callback` (`backend/app/api/auth.py`,
`_callback_redirect_uri`) отправляют Google одно и то же значение
`redirect_uri` — оно обязано побайтово совпадать с тем, что зарегистрировано
в Google Cloud Console. Раньше оно строилось через `request.url_for(...)`
(Starlette) — работало в локальной разработке (прямой доступ к
`localhost:8000`, без прокси и без `/api`-префикса), но за host nginx с
`/api/`-prefix-stripping (см. раздел "Docker Compose + host nginx" выше)
ломалось систематически: backend получает запрос уже без `/api`-префикса и
всегда по обычному HTTP внутри docker-сети — `request.url_for(...)`
неизбежно возвращает `http://<host>/auth/callback` вместо реального
`https://<домен>/api/auth/callback`.

Это не проблема доверия заголовку (не тот же случай, что
`X-Forwarded-For`/`TRUSTED_PROXY_IP` выше) — backend физически не может
восстановить внешний префикс из одного конкретного запроса, потому что
nginx уже обрезал его до того, как запрос дошёл до backend. Поэтому
`BACKEND_PUBLIC_URL` — фиксированное значение в конфиге, не выводимое ни из
`request`, ни из `X-Forwarded-*`:

```
BACKEND_PUBLIC_URL=https://<домен>/api
```

Должно точно соответствовать authorized redirect URI в Google Cloud
Console (`<BACKEND_PUBLIC_URL>/auth/callback`).

## Docker Compose + host nginx

Файлы: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`
(корень репозитория — рядом с обоими build-контекстами, чтобы относительные
пути `./backend`/`./frontend` не требовали переопределения), `deploy/nginx/
<домен>.conf`, `backend/.env.example`.

**nginx — на хосте, не в Docker.** `certbot --nginx` (обязательный первый
TLS-шаг, см. ниже) редактирует конфиг живого nginx-процесса и умеет
перегружать его — это рассчитано на хостовую установку, а не на
nginx-контейнер (там потребовался бы отдельный certbot-контейнер с shared
volume и ручной reload, заметно сложнее ради того же результата на
масштабе одного сервера/одного проекта). Поэтому:
- `backend` публикует порт **только на loopback** хоста
  (`127.0.0.1:8000:8000` в `docker-compose.yml`) — недоступен снаружи
  хоста, но виден хостовому nginx как `proxy_pass http://127.0.0.1:8000/`.
- `frontend`-сервис в compose — не долгоживущий контейнер: собирает `npm
  run build` и копирует `dist/` на **bind-mount** хостовой директории
  `deploy/frontend_dist/` (не именованный Docker-volume — тот не был бы
  напрямую читаем хостовым nginx без bind-mount, а именно bind-mount и
  делает эту разницу неважной), которую nginx отдаёт через `root`.
  Перезапуск после каждого фронтенд-деплоя: `docker compose run --rm
  frontend`.
- `postgres` не публикует порт на хост вообще — виден только `backend` по
  имени сервиса внутри docker-сети.

**Same-origin `/api/`-роутинг, не поддомен.** SPA (React Router) и backend
(FastAPI) используют одинаковые верхнеуровневые пути (`/projects`,
`/suppliers`, `/orders`, `/users` — ни один роутер в `main.py` не имеет
общего префикса). Разнести их на `api.<домен>` было бы чище, но
`session_id`/`csrf_token` cookies (ADR-0024 §3) выставляются без явного
`Domain=`-атрибута — на отдельном поддомене такие cookies не долетали бы
до фронтенда без правки кода аутентификации (вне объёма текущей задачи).
Вместо этого nginx проксирует `/api/` → backend с обрезкой префикса
(`/api/projects` → `/projects` на backend), фронтенд собран с
`VITE_API_BASE_URL=/api` (`frontend/Dockerfile`) — один origin, cookies
работают как есть, без изменений в auth-коде.

**pgvector/Postgres — версия образа.** `docker-compose.yml` использует
`pgvector/pgvector:pg17`. Это версия, подтверждённая для локальной
Windows-разработки (`docs/known-issues.md`, EDB-инсталлятор + сборка
pgvector из исходников под PG17) — **на проде эта версия не проверялась
отдельно**, известных причин ожидать несовместимость нет (миграция
`f1a6780bb7da_add_material_embedding_column.py` использует только
`CREATE EXTENSION vector` + колонку `Vector(1536)`, ничего
version-specific), но перед первым продовым запуском стоит явно
подтвердить, что PG17 — осознанный выбор, а не унаследованное
dev-предположение.

**Тайминги nginx.** `proxy_read_timeout`/`proxy_send_timeout` в
`deploy/nginx/<домен>.conf` — 1200s (20 минут): импорт прайс-листа
занимает 13+ минут на реальных данных (см. ADR-0021/известные проблемы),
дефолтный таймаут nginx (60s) обрывал бы запрос на середине.

### Раннбук первого запуска

1. Скопировать `deploy/nginx/example.com.conf` в
   `/etc/nginx/sites-available/<домен>.conf` на сервере, заменить
   `example.com` и `/path/to/procurement-allocator` на реальные значения,
   включить (`sites-enabled`), `nginx -t`, `systemctl reload nginx`.
2. Скопировать `backend/.env.example` → `backend/.env`, заполнить реальными
   значениями (никогда не коммитить), **кроме** `TRUSTED_PROXY_IP` — его
   значение неизвестно до запуска Docker-сети, заполняется отдельно на шаге 3.5.
3. Поднять БД и дождаться healthy:
   ```
   docker compose up -d postgres
   docker compose ps  # ждать postgres: healthy
   ```
3.5. Определить `TRUSTED_PROXY_IP`. Backend публикует порт на
   `127.0.0.1:8000` хоста (не `0.0.0.0` внутри контейнера — см. раздел выше),
   host-nginx проксирует туда же — но **пир, которого видит backend внутри
   контейнера, это не `127.0.0.1` и не `host.docker.internal`** (последнее —
   специфика Docker Desktop, на голом Docker Engine на Linux по умолчанию не
   определено), а адрес шлюза Docker-сети (`docker-compose`-бридж). Взять
   его отсюда:
   ```
   docker compose up -d backend
   docker network inspect procurement-allocator_default \
     --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
   ```
   (имя сети — `<имя-проекта>_default`, `docker compose config` покажет
   точное имя, если оно отличается от имени директории репозитория).
   Вписать полученный IP в `TRUSTED_PROXY_IP` в `backend/.env`, затем
   перезапустить backend, чтобы подхватить переменную:
   ```
   docker compose up -d backend
   ```
   Подтвердить после первого реального запроса через nginx (шаг 9) — если
   значение неверное, `TRUSTED_PROXY_IP` не совпадёт с реальным пиром и
   rate limiting деградирует до одного бакета на весь офис (fail-safe, но
   не то, что нужно) — см. таблицу в начале файла.
4. Применить миграции:
   ```
   docker compose run --rm backend alembic upgrade head
   ```
5. Импортировать реальные данные (перезаписывает содержимое таблиц —
   см. предупреждение в самом скрипте, сначала dry-run без `--confirm`):
   ```
   docker compose run --rm backend python -m app.scripts.import_real_data
   docker compose run --rm backend python -m app.scripts.import_real_data --confirm
   ```
6. Бэкафилл эмбеддингов материалов (нужен для матчинга при импорте прайсов,
   ADR-0019 §1):
   ```
   docker compose run --rm backend python -m app.scripts.backfill_material_embeddings
   ```
7. Собрать фронтенд и поднять backend:
   ```
   docker compose run --rm frontend
   docker compose up -d
   ```
8. TLS — **ручной шаг, не автоматизируется этой задачей**:
   ```
   sudo certbot --nginx -d <домен>
   ```
   certbot сам допишет `listen 443 ssl`/сертификаты в конфиг из шага 1 и
   настроит редирект с 80 на 443.
9. Проверка: `docker compose config` (без реального `.env` — только на
   синтаксис), затем открыть `https://<домен>` в браузере, пройти вход
   через Google, и повторить проверку rate limiting из раздела выше (11
   запросов к `/auth/login` с одной машины → 429 на 11-м, с другой машины
   не блокируется).
