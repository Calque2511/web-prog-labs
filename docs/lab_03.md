# Лаба 3. Валидация и обработка ошибок (занятие 4)

**Реализовано:** `app/schemas.py` (формат: типы, длины, диапазоны), `app/services/users.py` (бизнес-правила и конфликты),
`app/errors.py` (единый формат, 4xx/5xx), `app/logging_setup.py` (JSON-логи без паролей и токенов). Тесты: `tests/test_users_api.py`.

## Уровни проверок и коды
| Что | Где | Код |
|---|---|---|
| формат: тип, длина, диапазон, email | Pydantic-схема | **400** `validation_error` (все поля сразу) |
| бизнес-правила: имя не из стоп-списка, пароль ≠ логин | сервис | **422** `business_rule_violation` |
| уникальность email | сервис + `UNIQUE` в БД (защита от гонки) | **409** `conflict` |
| не найден | сервис | **404** |
| неожиданная ошибка | глобальный обработчик | **500**, клиенту без стека, со `request_id` |

## Ответы на задания
**Задание 1** (`name="J"`, `email="invalid-email"`, `age=15`, `password="123"`): не пройдут все четыре проверки; ответ **400**:
```json
{"error": {"code": "validation_error", "message": "Invalid request data", "request_id": "…",
  "details": [{"field": "name", "message": "String should have at least 2 characters"},
              {"field": "email", "message": "…must have an @-sign"},
              {"field": "age", "message": "Input should be greater than or equal to 18"},
              {"field": "password", "message": "String should have at least 8 characters"}]}}
```
**Задание 2.** Поле отсутствует — клиент не передал (для PATCH: «не менять»); `null` — явно «нет значения» (у нас запрещено);
`""` — значение есть, но пустое (не пройдёт `min_length`); `0` — валидное число (но `age=0` нарушит диапазон); `false` — валидный булев.
**Задание 3.** Формат: `@` в email, возраст — число, ≥8 символов, имя только буквы. Бизнес-правила: email уникален,
возраст ≥ 18 (зависит от домена), пароль ≠ логин, цензура в имени.
**Задание 5 (форматы ошибок):** конфликт — `{"error":{"code":"conflict","message":"Email already registered","details":[{"field":"email","message":"already exists"}]}}`;
не найден — `code: not_found`; внутренняя — `code: internal_error, message: "Internal server error"` (без деталей).
**Задание 8 (логи):** пароль — **нет**; токен — **нет**; email — осторожно (ПДн; у нас только при неудачном логине для расследования);
стек ошибки, время выполнения, User-Agent, IP, SQL (без значений) — да.
**Задание 9:** `int('abc')` упал внутри `create_user` → валидация должна быть на границе (схема), клиенту — 400 с полем `age`, а не 500.

Дополнительно: PUT (полная замена) и PATCH (частичная) с разными схемами, в PATCH явный `null` отклоняется (400); ошибки валидации пишутся в лог.
