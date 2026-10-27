# Лаба 8. Nginx и безопасность (занятия 10–11)

## Nginx
`nginx/nginx.conf` — для Docker (upstream `app:8000`); `nginx/nginx.local.conf` — **проверенная** локальная версия
(portable nginx 1.26.2 в `tools/`, без Docker). Что реально проверено командами `curl`:
- HTTP :8080 → **301** на HTTPS :8443; HTTPS с самоподписанным сертификатом (в проде — Let's Encrypt: `certbot --nginx -d домен`), заголовок HSTS.
- reverse proxy на FastAPI; регистрация → логин → профиль через nginx; запись реально попала в PostgreSQL (в БД хеш `$2b$12$…`).
- статика `/static/` с `expires 30d`, gzip (`Content-Encoding: gzip`).
- **rate limit** `10r/s burst=20`: 200 параллельных запросов → `{429: 161, 200: 39}`, ответ 429 — JSON.
- upstream остановлен → **503** JSON вместо голого 502 (`error_page`); тайм-ауты `proxy_connect/send/read_timeout`.
- `server_tokens off`, `client_max_body_size 10M`, `X-Request-ID` пробрасывается в приложение; в лог пишутся `$request_time` и `$request_id`.
- балансировка: `upstream` с `least_conn`; для round-robin уберите директиву (по умолчанию).

```bash
python scripts/local_postgres.py                  # PostgreSQL + миграции, печатает DATABASE_URL
set DATABASE_URL=...   &&  uvicorn app.main:app_factory --factory --port 8000
tools\nginx-1.26.2\nginx.exe -p tools/nginx-1.26.2/ -c ../../nginx/nginx.local.conf
python scripts/burst.py https://localhost:8443/health 200
```
**Let's Encrypt и мониторинг в `docker-compose.yml`:** сервисы `certbot`, `prometheus` (`prometheus.yml` + правила `prometheus/alerts.yml`) и `grafana` (:3000, вход admin/admin, источник данных — `http://prometheus:9090`).
В `nginx.conf` добавлен `location /.well-known/acme-challenge/` для проверки домена; HTTPS-блок на :443 закомментирован — включайте его после
получения сертификата (порядок описан в комментарии), иначе nginx не стартует. Домен и e-mail в команде `certbot` нужно заменить на свои.
Запущено и проверено: nginx, prometheus, grafana стартуют в compose; `nginx.conf` проходит `nginx -t`; `promtool check rules` — 3 правила корректны.
Не проверено: получение сертификата (нужны публичный домен и реальный e-mail).

Приложение тоже ставит защитные заголовки, поэтому в `location /` стоят `proxy_hide_header`: в ответе остаётся по одной копии от nginx.

## Безопасность (занятие 11)
| Тема | Реализация / доказательство |
|---|---|
| Пароли | bcrypt, соль внутри хеша; cost 12 ≈ 190 мс на хеш против ≈ 0 у sha256 (`demo_output.md`); одинаковый ответ для «нет пользователя»/«неверный пароль», фиктивная проверка для выравнивания времени |
| SQL-инъекция | демо: `' OR '1'='1` возвращает все строки в f-строке, 0 — в параметризованном; `; DROP TABLE` реально удаляет таблицу в уязвимом варианте. В приложении — только ORM/параметры |
| XSS | вывод экранируется (`html.escape`), CSP `default-src 'self'`, auth-cookie `HttpOnly`, валидация ввода (`tests/test_web.py`) |
| CSRF | подписанный токен, double-submit cookie, `SameSite=Strict`, проверка `Origin` |
| RBAC и владение | роли `admin`/`user`; `require_role`, `ensure_owner_or_admin` (подмена ID в URL → 403 + запись в лог); админ может всё |
| Секреты | `.env` вне git, `.env.example`, `SECRET_KEY` ≥ 32 символов проверяется при старте |
| CORS | только `CORS_ORIGINS`, методы и заголовки перечислены; чужой Origin не получает `Access-Control-Allow-Origin` |
| Заголовки | `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `X-XSS-Protection` (устаревший, оставлен по заданию), CSP (кроме `/docs`) |

**Перебор паролей:** после 5 неудачных входов подряд логин блокируется на 15 минут (счётчик в Redis, ответ 429; сбрасывается успешным входом;
тесты `test_login_is_locked_…`). **Не реализовано:** rate limit на уровне приложения (есть на nginx).
