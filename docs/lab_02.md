# Лаба 2. REST API для CRUD (занятие 3)

**Реализовано:** `app/routers/users.py` — CRUD пользователей + вложенный ресурс заказов. Спецификация — [`openapi.yaml`](../openapi.yaml)
(генерируется из кода: `python scripts/export_openapi.py`), интерактивная — `http://localhost:8000/docs`.

| Операция | Метод и URL | Успех | Ошибки |
|---|---|---|---|
| список (пагинация, поиск, фильтр, сортировка) | `GET /users?page=&size=&q=&min_age=&max_age=&sort=` | 200 | 400, 401 |
| один | `GET /users/{id}` | 200 | 401, 404 |
| создать | `POST /users` | 201 + `Location` | 400, 409, 422 |
| заменить целиком | `PUT /users/{id}` | 200 | 400, 401, 403, 404, 409 |
| частично | `PATCH /users/{id}` | 200 | то же |
| удалить | `DELETE /users/{id}` | 204 | 401, 403, 404 |
| заказы пользователя | `GET/POST /users/{id}/orders` | 200 / 201 | 401, 403, 404 |

Формат списка: `{"items": [...], "total": 42, "page": 1, "size": 20}`. Формат ошибки: `{"error": {"code", "message", "details", "request_id"}}`.

## Ответы на задания занятия 3
**Методы:** создать пост — POST; список — GET; один — GET; обновить целиком — PUT; изменить заголовок — PATCH; удалить — DELETE;
комментарий — `POST /posts/{id}/comments`; комментарии — `GET /posts/{id}/comments`; лайк — `PUT /posts/{id}/like` (идемпотентно) или POST;
популярные — `GET /posts?sort=-likes`.
**Коды:** создание 201; получение 200; не найден 404; неверные данные 400; не авторизован 401; нет прав 403; уже существует 409;
удаление 204; ошибка сервера 500; сервис недоступен 503.
**Идемпотентность:** GET — да; POST /users — нет; PUT — да; PATCH `/users/123/email` — да (установка значения; «+1» было бы нет);
DELETE — да (состояние то же; код ответа может смениться на 404); `GET ?page=1` — да.
**Эндпоинт товаров:** `GET /products?category=books&min_price=10&max_price=100&sort=price|-name&page=2&size=20&q=python` →
`{"items":[…],"total":134,"page":2,"size":20}`; 400 при плохих параметрах. Тот же шаблон реализован для `/users`.
**Блог/магазин (задания 1, 10):** ресурсы `/posts`, `/posts/{id}/comments`, `/tags`, `/categories`; `/products`, `/categories`, `/orders`,
`/orders/{id}/items`, `/users`. Изменяющие операции требуют авторизации; создание заказа — только владелец (проверка в `ensure_owner_or_admin`).

httpbin и JSONPlaceholder (задания 7, 9): `curl -X PUT https://httpbin.org/put -d …` возвращает 200 и эхо запроса; JSONPlaceholder
отвечает 201 на POST и 200 на PUT/DELETE, но данные не сохраняет (песочница).
