CREATE TABLE IF NOT EXISTS orders (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product    VARCHAR(100)   NOT NULL,
    total      NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMP      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders(user_id);
