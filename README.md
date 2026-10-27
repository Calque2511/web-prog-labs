# Лабораторные по веб-программированию

Один проект на Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, Redis и nginx, который дополняется от лабы к лабе.
Задания взяты из `materials/pract_01…12/practice/tasks.md` и `lab_plan.md` (лабы 1–10).

Автор: Захар Копейка.

| Лаба | Тема | Где смотреть |
|---|---|---|
| 1 | Окружение, HTTP-сервер, Docker | [docs/lab_01.md](docs/lab_01.md), `Dockerfile`, `docker-compose.yml` |
| 2 | REST CRUD и OpenAPI | [docs/lab_02.md](docs/lab_02.md), `openapi.yaml`, `app/routers/users.py` |
| 3 | Валидация и ошибки | [docs/lab_03.md](docs/lab_03.md) |
| 4–5 | Слои, DI, тесты | [docs/lab_04_05.md](docs/lab_04_05.md) |
| 6 | Аутентификация, БД, миграции | [docs/lab_06.md](docs/lab_06.md) |
| 7 | Транзакции, индексы, N+1 | [docs/lab_07.md](docs/lab_07.md), [docs/demo_output.md](docs/demo_output.md) |
| 8 | Nginx и безопасность | [docs/lab_08.md](docs/lab_08.md) |
| 9–10 | Диагностика, Redis, очереди | [docs/lab_09_10.md](docs/lab_09_10.md) |

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest --cov=app --cov=lab07
uvicorn app.main:app_factory --factory --reload
```

Если PowerShell не разрешает `activate`, вызывайте Python напрямую: `.venv\Scripts\python -m pytest`.

Без настроек приложение работает на SQLite и fakeredis, документация API на http://localhost:8000/docs.
Для интеграционных тестов нужен PostgreSQL: он поднимается сам (пакет `pgserver`) или берётся из `TEST_DATABASE_URL`
(`docker compose -f docker-compose.test.yml up -d`, порты 5433 и 6380).

С Docker: задать `SECRET_KEY` (не короче 32 символов) и выполнить `docker compose up --build`.
nginx слушает порт 80, миграции из `migrations/` применяются при первом старте БД.
Без Docker: `python scripts/local_postgres.py` поднимает PostgreSQL с миграциями, nginx запускается по [docs/lab_08.md](docs/lab_08.md).

Администратор создаётся вручную: `UPDATE users SET role='admin' WHERE email='...';`

## Проверка

- 109 тестов (unit, API, интеграционные на PostgreSQL), покрытие `app` и `lab07` 98 %.
- Тесты проходят и на PostgreSQL 15 с Redis из `docker-compose.test.yml`:
  `TEST_DATABASE_URL=postgresql+psycopg2://test:test@localhost:5433/test_db REDIS_URL=redis://localhost:6380/0 pytest`
- `docker compose up`: сервисы поднимаются, запросы через nginx доходят до приложения и БД, Prometheus собирает `/metrics`.
- Результаты демонстраций (гонки, индексы, N+1, SQL-инъекция, bcrypt, пул соединений): [docs/demo_output.md](docs/demo_output.md).

## Скриншоты и вывод команд

Скриншоты в `docs/screenshots/` сняты автоматически (Edge, Playwright) с запущенного `docker compose`:
запросы выполнялись в Swagger UI на http://localhost/docs. Вывод консольных команд лежит текстом в `docs/outputs/`.

| Лаба | Файлы | Что показано |
|---|---|---|
| 1 | [lab01_health.png](docs/screenshots/lab01_health.png), [curl_health.txt](docs/outputs/curl_health.txt), [docker_compose_ps.txt](docs/outputs/docker_compose_ps.txt) | ответ `/health` через nginx, `curl -v`, состояние контейнеров |
| 2 | [lab02_swagger.png](docs/screenshots/lab02_swagger.png), [lab02_create_user_201.png](docs/screenshots/lab02_create_user_201.png), [lab02_list_users_200.png](docs/screenshots/lab02_list_users_200.png), [lab02_get_user_404.png](docs/screenshots/lab02_get_user_404.png), [lab02_patch_user_200.png](docs/screenshots/lab02_patch_user_200.png), [lab02_delete_user_204.png](docs/screenshots/lab02_delete_user_204.png) | список эндпоинтов и CRUD |
| 3 | [lab03_validation_400.png](docs/screenshots/lab03_validation_400.png), [lab03_conflict_409.png](docs/screenshots/lab03_conflict_409.png), [lab03_business_rule_422.png](docs/screenshots/lab03_business_rule_422.png), [lab03_patch_null_400.png](docs/screenshots/lab03_patch_null_400.png) | ошибки 400, 409, 422 |
| 5 | [pytest_coverage.txt](docs/outputs/pytest_coverage.txt) | 109 тестов, покрытие 98 % |
| 6 | [lab06_login_200.png](docs/screenshots/lab06_login_200.png), [lab06_login_401.png](docs/screenshots/lab06_login_401.png), [lab06_profile_without_token_401.png](docs/screenshots/lab06_profile_without_token_401.png), [lab06_profile_200.png](docs/screenshots/lab06_profile_200.png), [lab06_refresh_200.png](docs/screenshots/lab06_refresh_200.png), [lab06_refresh_reuse_401.png](docs/screenshots/lab06_refresh_reuse_401.png), [lab06_logout_204.png](docs/screenshots/lab06_logout_204.png), [lab06_profile_after_logout_401.png](docs/screenshots/lab06_profile_after_logout_401.png) | вход, защищённый профиль, ротация refresh-токена, logout |
| 8 | [lab08_health_security_headers.png](docs/screenshots/lab08_health_security_headers.png), [burst_rate_limit.txt](docs/outputs/burst_rate_limit.txt) | защитные заголовки, rate limit nginx (429) |
| 9 | [lab09_metrics.png](docs/screenshots/lab09_metrics.png), [lab09_prometheus_targets.png](docs/screenshots/lab09_prometheus_targets.png), [lab09_prometheus_query.png](docs/screenshots/lab09_prometheus_query.png), [lab09_prometheus_alerts.png](docs/screenshots/lab09_prometheus_alerts.png) | метрики, сбор Prometheus, правила алертов |
| 10 | [redis_keys.txt](docs/outputs/redis_keys.txt) | ключи в Redis: refresh-токены и отметки обработанных писем |

Не входит в проект: сертификат Let's Encrypt (нужен свой домен, в `docker-compose.yml` указать e-mail и домен),
дашборды Grafana, скриншоты DevTools из первого занятия.
