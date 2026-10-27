# Лаба 7. Транзакции и оптимизация запросов (занятие 9)

Код: `lab07/transactions.py`, `lab07/indexes.py`; тесты на настоящей PostgreSQL 16: `tests/test_lab07_postgres.py`;
сырые результаты прогона: [`demo_output.md`](demo_output.md) (`python scripts/demos.py`).

## Транзакции и гонки
- `transfer(from, to, amount)` — одна транзакция: `SELECT … FOR UPDATE` (в порядке `id`, чтобы встречные переводы не давали deadlock),
  проверка баланса, два `UPDATE`, `COMMIT`; при `InsufficientFunds`/`AccountNotFound` — `ROLLBACK`. Тест: 20 встречных переводов параллельно — без deadlock, сумма сохраняется.
- **Гонка (check-then-act):** два потока читают `seats = 1`, оба записываются → 2 регистрации на 1 место. Воспроизведено (тест `test_naive_registration_oversells_seat`).
  *Замечание:* при `CHECK (seats >= 0)` и `UPDATE seats = seats - 1` БД бы сама отвергла второй поток; гонка проявляется, когда новое значение считается в приложении.

| Способ | Результат при 10 потоках на 3 места |
|---|---|
| наивный | переполнение (см. demo_output.md) |
| `SELECT … FOR UPDATE` | ровно 3 регистрации |
| `UPDATE … SET seats = seats - 1 WHERE seats > 0` + проверка `rowcount` | ровно 3, без явной блокировки — предпочтительно |
| `UNIQUE(user_id, course_id)` | повторная регистрация → `IntegrityError` → `AlreadyRegistered` |

## Индексы и EXPLAIN (50 000 строк)
| Запрос | до | после (индекс) |
|---|---|---|
| `email = …` | Seq Scan, cost 1093 | Index Scan `idx_users_email`, **8.4** |
| `name = … AND age = …` | Seq Scan, 1218 | Index Scan `idx_users_name_age`, **8.3** |
| `age = 30` (низкая селективность) | Seq Scan, 1093 | Bitmap Scan, 502 — выигрыш мал |
| `active AND city` | Seq Scan | Bitmap Scan `idx_users_active_city`, 552 |
Правило левого префикса: индекс `(name, age, city)` работает для `name`, `name+age`, `name+age+city`, но **не** для `city` или `age` отдельно
(`test_composite_index_left_prefix_rule`). Индекс по булевому `active` почти бесполезен (2 значения) — полезен только в составе.

## N+1 (100 пользователей × 5 заказов)
| Стратегия | Запросов | Время |
|---|---|---|
| lazy (N+1) | 101 | ~36 мс |
| `joinedload` | 1 | ~6 мс |
| `subqueryload` | 2 | ~7 мс |
| `selectinload` | 2 | ~5 мс |
Время зависит от машины; число запросов — детерминированно (проверено тестом). На локальной БД разница небольшая, по сети — кратная.
