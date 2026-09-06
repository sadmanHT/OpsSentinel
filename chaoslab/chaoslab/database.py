from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection


class SimulatorDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @contextmanager
    def connection(self) -> Iterator[Connection[tuple[object, ...]]]:
        with psycopg.connect(self.database_url) as connection:
            yield connection

    def ensure_schema(self) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sim_products (
                    id INTEGER PRIMARY KEY,
                    sku TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    price_cents INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sim_orders (
                    id INTEGER PRIMARY KEY,
                    customer TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sim_order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES sim_orders(id),
                    product_id INTEGER NOT NULL REFERENCES sim_products(id),
                    quantity INTEGER NOT NULL
                )
                """
            )
            cur.execute("SELECT COUNT(*) FROM sim_products")
            product_count = cur.fetchone()
            if product_count and product_count[0] == 0:
                cur.executemany(
                    "INSERT INTO sim_products (id, sku, name, price_cents) VALUES (%s, %s, %s, %s)",
                    [
                        (1, "SKU-RED", "Red Widget", 1200),
                        (2, "SKU-BLUE", "Blue Widget", 1500),
                        (3, "SKU-GREEN", "Green Widget", 900),
                        (4, "SKU-BLACK", "Black Widget", 1800),
                    ],
                )
            cur.execute("SELECT COUNT(*) FROM sim_orders")
            order_count = cur.fetchone()
            if order_count and order_count[0] == 0:
                cur.executemany(
                    "INSERT INTO sim_orders (id, customer) VALUES (%s, %s)",
                    [(index, f"customer-{index}") for index in range(1, 7)],
                )
                items: list[tuple[int, int, int]] = []
                for order_id in range(1, 7):
                    for product_id in range(1, 5):
                        items.append((order_id, product_id, 1 + ((order_id + product_id) % 2)))
                cur.executemany(
                    (
                        "INSERT INTO sim_order_items (order_id, product_id, quantity) "
                        "VALUES (%s, %s, %s)"
                    ),
                    items,
                )
            conn.commit()

    def fetch_orders_batch(self) -> tuple[list[dict[str, object]], int]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.id, o.customer, p.id, p.sku, p.name, p.price_cents, i.quantity
                FROM sim_orders o
                JOIN sim_order_items i ON i.order_id = o.id
                JOIN sim_products p ON p.id = i.product_id
                ORDER BY o.id, p.id
                """
            )
            rows = cur.fetchall()
        orders: dict[int, dict[str, object]] = {}
        for order_id, customer, product_id, sku, name, price, quantity in rows:
            order = orders.setdefault(order_id, {"id": order_id, "customer": customer, "items": []})
            items = order["items"]
            assert isinstance(items, list)
            items.append(
                {
                    "product_id": product_id,
                    "sku": sku,
                    "name": name,
                    "price_cents": price,
                    "quantity": quantity,
                }
            )
        return list(orders.values()), 1

    def fetch_orders_n_plus_one(self) -> tuple[list[dict[str, object]], int]:
        query_count = 0
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, customer FROM sim_orders ORDER BY id")
            query_count += 1
            orders = []
            for order_id, customer in cur.fetchall():
                cur.execute(
                    (
                        "SELECT product_id, quantity FROM sim_order_items "
                        "WHERE order_id = %s ORDER BY id"
                    ),
                    (order_id,),
                )
                query_count += 1
                items = []
                for product_id, quantity in cur.fetchall():
                    cur.execute(
                        "SELECT id, sku, name, price_cents FROM sim_products WHERE id = %s",
                        (product_id,),
                    )
                    query_count += 1
                    product = cur.fetchone()
                    if product is None:
                        continue
                    items.append(
                        {
                            "product_id": product[0],
                            "sku": product[1],
                            "name": product[2],
                            "price_cents": product[3],
                            "quantity": quantity,
                        }
                    )
                orders.append({"id": order_id, "customer": customer, "items": items})
        return orders, query_count
