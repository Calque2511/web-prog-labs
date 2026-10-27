# Лаба 1. Окружение и первый HTTP-сервер (занятия 1–2)

**Что сделано:** FastAPI-сервер (`app/main.py`, `GET /`, `GET /health`), `Dockerfile`, `docker-compose.yml`
(app + postgres + redis + nginx), конфигурация через переменные окружения (`.env.example`).
Проверено: сервер запущен через `uvicorn`, отвечает на `curl` напрямую и через nginx.

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements-dev.txt
uvicorn app.main:app_factory --factory --port 8000
curl -v http://localhost:8000/health        # {"status":"ok"}
```

## Занятие 1 — ответы

**Задание 1 (запрос `POST /api/users`).**
1. `POST` — создать ресурс (небезопасный, не идемпотентный). 2. Ресурс — коллекция `/api/users` на хосте `api.example.com`.
3. `Host` — виртуальный хост; `Content-Type: application/json` — формат тела; `Content-Length` — длина тела в байтах;
`Authorization: Bearer …` — JWT-токен. 4. JSON с name/email/age. 5. JSON.
(Замечание: в примере `Content-Length: 45`, а тело длиннее — 60 байт; сервер обрежет/отвергнет такой запрос.)

**Задание 2 (статус-коды).** список — 200; создание — 201; не найден — 404; плохой email — 400; уже существует — 409;
внутренняя ошибка — 500; удаление — 204; нужна аутентификация — 401.
Именно так отвечает наше API (см. `tests/test_users_api.py`).

**Задание 3 (DNS и порты).** `https://example.com:8080` — DNS резолвит имя в IP, браузер соединяется с портом 8080 по TLS
(стандартный для HTTPS 443 переопределён). 80 — HTTP без шифрования, 443 — HTTPS (TLS). `localhost` = `127.0.0.1` / `::1` (петля).
DNS переводит имена в IP. Кэш DNS (в ОС, браузере, резолвере) хранит ответы на время TTL — быстрее и меньше нагрузки.

**Задание 4 (путь запроса).** Браузер → DNS → (интернет) → балансировщик/reverse proxy (nginx, TLS, статика) →
backend-приложение (FastAPI) → [кэш Redis] → база данных (PostgreSQL). Именно эта цепочка собрана в `docker-compose.yml`.

**Задание 5 (Content-Type).** HTML — `text/html; charset=utf-8`; JSON — `application/json`; XML — `application/xml`;
PNG — `image/png`; загрузка формой — `multipart/form-data`; CSS — `text/css`; JS — `text/javascript`.

**Задания 6–8.** `curl -v https://httpbin.org/get` показывает: строки `>` (запрос), `<` (статус и заголовки ответа), затем тело.
`/status/404`, `/status/500` — тело пустое, смысл несёт только код. Порт 80 требует прав администратора/занят IIS (на Linux — root).
Для DevTools (F12 → Network) — метод, URL, заголовки, `Content-Type`, размер, время; повторить запрос — «Copy as cURL».

## Занятие 2 — ответы

**YAML-конфиг:** порт 8080; SSL включён; пул 5–20; features: authentication, logging, caching; TTL кэша 3600 с.
**docker-compose из задания:** сервисы web, app, db, redis; с хоста доступен только web на 8080 (остальные — во внутренней сети);
у app заданы `DATABASE_URL` и `REDIS_URL`; данные PostgreSQL — в named volume `pgdata`; в web монтируются `./html` и `./nginx.conf` (ro);
порядок запуска по `depends_on`: db, redis → app → web (но `depends_on` без `healthcheck` ждёт старта, а не готовности —
в нашем compose использованы `condition: service_healthy`).

**Задания 3–5, 10:** см. `docker-compose.yml`, `Dockerfile`, `nginx/nginx.conf` (reverse proxy на сервис `app` по DNS-имени внутри сети compose).

**Задание 8 (диагностика):** `docker ps -a` (упал ли контейнер, exit code) → `docker logs` (трейс) → `docker exec -it … sh` →
`env` (переменные заданы?) → `ss -tlnp` (слушает ли `0.0.0.0`, а не `127.0.0.1`) → `getent hosts db`/`ping db` (DNS сети compose).

**Задание 9 (volumes):** bind mount — путь с хоста (удобно для разработки), named volume — управляется Docker (для данных БД).
`docker compose down` удаляет контейнеры, но не named volumes; `down -v` — удаляет и данные. Список: `docker volume ls`.

> `docker compose up` проверен на запущенном стеке: сервисы стартуют, `app` и `postgres` — `healthy`, миграции применяются автоматически,
> запросы через nginx:80 доходят до приложения и БД.
