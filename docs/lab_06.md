# Лаба 6. Аутентификация и БД (занятия 7–8)

**Реализовано:** `app/security.py`, `app/services/auth.py`, `app/routers/auth.py`, `app/routers/web.py`, `migrations/`.

| Endpoint | Назначение |
|---|---|
| `POST /auth/register` (= `POST /users`) | регистрация, пароль хранится как bcrypt-хеш |
| `POST /auth/login` | `access_token` (15 мин) + `refresh_token` (7 дней) |
| `POST /auth/refresh` | **ротация**: старый refresh одноразовый, повторное использование → 401 |
| `GET /auth/profile` | профиль (Bearer) |
| `POST /auth/logout` | access-токен в blacklist (Redis, TTL = остаток жизни), refresh отзывается |
| `GET/POST /settings` | защищённая страница + CSRF-токен (`X-CSRF-Token`) |
| `GET /form`, `POST /submit` | форма с CSRF (double-submit cookie, `SameSite=Strict`, проверка `Origin`, экранирование вывода) |
| `POST /set-cookie`, `GET /get-cookie`, `POST /delete-cookie` | cookie с `HttpOnly`, `SameSite`, `Secure` (через `COOKIE_SECURE`), сессионные и с `Max-Age` |

Payload JWT: `user_id, sub, username, role, jti, type, iss, iat, exp`. Проверяются подпись, `exp`, `iss`, тип токена; алгоритм `none` отвергается.
Redis: `REDIS_URL` или in-memory `fakeredis` (для dev/тестов). Состояние токенов в Redis → несколько экземпляров приложения видят одни данные.

**БД:** параметризованные запросы везде (ORM / `%s`); миграции `001_create_users.sql`, `002_create_orders.sql` применяются
автоматически (`docker-entrypoint-initdb.d`) или `scripts/local_postgres.py`; `ON DELETE CASCADE` на заказах.

## Сравнение Session и JWT (занятие 7, задание 4)
| | Session (cookie + хранилище) | JWT |
|---|---|---|
| Сложность | проще | сложнее (refresh, ротация) |
| Производительность | запрос в хранилище на каждый вызов | проверка подписи без обращения к хранилищу |
| Масштабирование | нужно общее хранилище (Redis) | stateless |
| Отзыв | мгновенно | только через blacklist/короткий TTL |
| Безопасность | cookie: HttpOnly/SameSite, нужен CSRF | Bearer не подвержен CSRF, но нужна защита от XSS при хранении |
Вывод: JWT + blacklist для API; сессии удобны для серверных веб-страниц.

## Cookie (задание 7)
`HttpOnly` — недоступна JS; `Secure` — только HTTPS; `SameSite=Strict` — не отправляется с чужих сайтов, `Lax` — только при переходе по ссылке (GET);
`Path=/settings` — отправляется только на этот путь; `Expires` — постоянная, без него — сессионная. JS видит только cookie без `HttpOnly` (`theme`, `user_id`).
Чеклист безопасности (задание 9): у всех auth-cookie есть `HttpOnly`, `Secure` включается в проде (`COOKIE_SECURE=true`), `SameSite` задан, чувствительных данных в cookie нет.
