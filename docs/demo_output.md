# Результаты демонстраций

Сгенерировано `python scripts/demos.py` на встроенном PostgreSQL 16.

## SQL-инъекция: уязвимый и защищённый поиск

Payload: `' OR '1'='1`

- уязвимый вариант вернул **2** строк(и): [('a@x.com',), ('b@x.com',)]
- защищённый вариант вернул **0** строк(и)
- после `'; DROP TABLE` в уязвимом варианте таблица существует: **False**

## Хеширование паролей: время и соль

- sha256 без соли: 0.0006 мс на 1000 хешей — перебирается миллиардами/с, одинаковые пароли дают одинаковый хеш
- bcrypt(cost=12): 196 мс на хеш, проверка 193 мс (верно: True)
- два хеша одного пароля различаются (соль): True; хеш: `$2b$12$y84ilha4ETmt3U9oAZxv9....`

## Connection pooling: без пула vs с пулом (500 коротких запросов)

| режим | время, с | запросов/с |
|---|---|---|
| NullPool (без пула) | 12.16 | 41 |
| QueuePool(5+10) | 0.13 | 3979 |


## Асинхронный доступ (asyncpg)

- INSERT -> id=1; SELECT -> {'id': 1, 'email': 'a@x.com'}
- дубликат обработан: `UniqueViolationError`
- UPDATE -> b@x.com; DELETE -> DELETE 1
- 20 запросов по 0.1 с выполнены конкурентно за **0.27 с** (последовательно было бы 2 с)

## Лаба 7: транзакции и гонки

- перевод 30: A=70, B=80 (атомарно)
- перевод 999 отклонён и откатан: balance 70.00 < 999

| способ | мест | потоков | записано | seats в БД | результат |
|---|---|---|---|---|---|
| наивный check-then-act | 1 | 2 | 2 | 0 | ПЕРЕПРОДАЖА |
| SELECT ... FOR UPDATE | 3 | 10 | 3 | 0 | ок |
| атомарный UPDATE ... WHERE seats > 0 | 3 | 10 | 3 | 0 | ок |


## Лаба 7: индексы и EXPLAIN (50 000 строк)

| запрос | до: узел | до: cost | после: узел | индекс | после: cost |
|---|---|---|---|---|---|
| email = ... | Seq Scan | 1093.0 | Index Scan | idx_users_email | 8.43 |
| name AND age | Seq Scan | 1218.0 | Index Scan | idx_users_name_age | 8.31 |
| age = 30 | Seq Scan | 1093.0 | Bitmap Heap Scan | idx_users_age | 503.61 |
| active AND city | Seq Scan | 1093.0 | Bitmap Heap Scan | idx_users_active_city | 550.84 |
| city (без префикса) | Seq Scan | 1218.0 | Bitmap Heap Scan | idx_users_age | 505.43 |


## Лаба 7: N+1 и eager loading (100 пользователей × 5 заказов)

| strategy | queries | orders | ms |
|---|---|---|---|
| n_plus_1 (lazy) | 101 | 500 | 35.5 |
| joinedload | 1 | 500 | 6.1 |
| subqueryload | 2 | 500 | 6.4 |
| selectinload | 2 | 500 | 4.9 |

