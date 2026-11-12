from decimal import Decimal

import mysql.connector

from database import get_connection
from models import (
    Category,
    CustomerAccount,
    CustomerOrder,
    OrderItem,
    Product,
    Rider,
    StockMovement,
    User,
)


_ACCOUNT_SELECT_COLUMNS = (
    "id, full_name, email, password_hash, email_verified, "
    "verification_code_hash, verification_expires_at, "
    "verification_attempts, verification_last_sent_at"
)
_CUSTOMER_SELECT_COLUMNS = (
    f"{_ACCOUNT_SELECT_COLUMNS}, firebase_uid"
)


class UserRepository:
    def create_account(self, user: User) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO users (
                    full_name, email, password_hash, email_verified,
                    verification_code_hash, verification_expires_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user.full_name,
                    user.email,
                    user.password_hash,
                    bool(user.email_verified),
                    user.verification_code_hash,
                    user.verification_expires_at,
                ),
            )
            user_id = cursor.lastrowid
            connection.commit()
            return user_id
        finally:
            connection.close()

    def get_by_email(self, email: str) -> User | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"SELECT {_ACCOUNT_SELECT_COLUMNS} FROM users WHERE email = %s",
                (email,),
            )
            row = cursor.fetchone()
            return User.from_row(row) if row else None
        finally:
            connection.close()

    def get_by_id(self, user_id: int) -> User | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"SELECT {_ACCOUNT_SELECT_COLUMNS} FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            return User.from_row(row) if row else None
        finally:
            connection.close()

    def set_verification_challenge(
        self,
        user_id: int,
        verification_code_hash: str,
        verification_expires_at,
        verification_last_sent_at=None,
    ) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET verification_code_hash = %s,
                    verification_expires_at = %s,
                    verification_attempts = 0,
                    verification_last_sent_at = %s,
                    email_verified = FALSE
                WHERE id = %s
                """,
                (
                    verification_code_hash,
                    verification_expires_at,
                    verification_last_sent_at,
                    user_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def increment_verification_attempts(self, user_id: int) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET verification_attempts = verification_attempts + 1
                WHERE id = %s
                """,
                (user_id,),
            )
            cursor.execute(
                "SELECT verification_attempts FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            connection.commit()
            return int(row[0]) if row else 0
        finally:
            connection.close()

    def mark_email_verified(self, user_id: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET email_verified = TRUE,
                    verification_code_hash = NULL,
                    verification_expires_at = NULL,
                    verification_attempts = 0,
                    verification_last_sent_at = NULL
                WHERE id = %s
                """,
                (user_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def update_profile(
        self,
        user_id: int,
        full_name: str,
        email: str,
        password_hash: str | None = None,
    ) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            if password_hash is None:
                cursor.execute(
                    """
                    UPDATE users
                    SET full_name = %s, email = %s
                    WHERE id = %s
                    """,
                    (full_name, email, user_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE users
                    SET full_name = %s, email = %s, password_hash = %s
                    WHERE id = %s
                    """,
                    (full_name, email, password_hash, user_id),
                )
            connection.commit()
        finally:
            connection.close()


class ShopSettingsRepository:
    def get(self, key: str, default: str = "") -> str:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT setting_value
                FROM shop_settings
                WHERE setting_key = %s
                """,
                (key,),
            )
            row = cursor.fetchone()
            if row is None:
                return default
            return str(row[0] or default)
        finally:
            connection.close()

    def set(self, key: str, value: str) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO shop_settings (setting_key, setting_value)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
                """,
                (key, value),
            )
            connection.commit()
        finally:
            connection.close()

    def get_gcash_number(self) -> str:
        return self.get("gcash_number", "").strip()

    def set_gcash_number(self, number: str) -> None:
        self.set("gcash_number", number.strip())


class CustomerAccountRepository:
    def create_account(self, customer: CustomerAccount) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO customer_accounts (
                    full_name, email, password_hash, email_verified,
                    verification_code_hash, verification_expires_at, firebase_uid
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    customer.full_name,
                    customer.email,
                    customer.password_hash,
                    bool(customer.email_verified),
                    customer.verification_code_hash,
                    customer.verification_expires_at,
                    customer.firebase_uid,
                ),
            )
            customer_id = cursor.lastrowid
            connection.commit()
            return customer_id
        finally:
            connection.close()

    def get_by_email(self, email: str) -> CustomerAccount | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT {_CUSTOMER_SELECT_COLUMNS}
                FROM customer_accounts
                WHERE email = %s
                """,
                (email,),
            )
            row = cursor.fetchone()
            return CustomerAccount.from_row(row) if row else None
        finally:
            connection.close()

    def get_by_firebase_uid(self, firebase_uid: str) -> CustomerAccount | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT {_CUSTOMER_SELECT_COLUMNS}
                FROM customer_accounts
                WHERE firebase_uid = %s
                """,
                (firebase_uid,),
            )
            row = cursor.fetchone()
            return CustomerAccount.from_row(row) if row else None
        finally:
            connection.close()

    def link_firebase_uid(self, customer_id: int, firebase_uid: str) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_accounts
                SET firebase_uid = %s,
                    email_verified = TRUE
                WHERE id = %s
                """,
                (firebase_uid, customer_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_by_id(self, customer_id: int) -> CustomerAccount | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                f"""
                SELECT {_CUSTOMER_SELECT_COLUMNS}
                FROM customer_accounts
                WHERE id = %s
                """,
                (customer_id,),
            )
            row = cursor.fetchone()
            return CustomerAccount.from_row(row) if row else None
        finally:
            connection.close()

    def set_verification_challenge(
        self,
        customer_id: int,
        verification_code_hash: str,
        verification_expires_at,
        verification_last_sent_at=None,
    ) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_accounts
                SET verification_code_hash = %s,
                    verification_expires_at = %s,
                    verification_attempts = 0,
                    verification_last_sent_at = %s,
                    email_verified = FALSE
                WHERE id = %s
                """,
                (
                    verification_code_hash,
                    verification_expires_at,
                    verification_last_sent_at,
                    customer_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def increment_verification_attempts(self, customer_id: int) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_accounts
                SET verification_attempts = verification_attempts + 1
                WHERE id = %s
                """,
                (customer_id,),
            )
            cursor.execute(
                "SELECT verification_attempts FROM customer_accounts WHERE id = %s",
                (customer_id,),
            )
            row = cursor.fetchone()
            connection.commit()
            return int(row[0]) if row else 0
        finally:
            connection.close()

    def mark_email_verified(self, customer_id: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_accounts
                SET email_verified = TRUE,
                    verification_code_hash = NULL,
                    verification_expires_at = NULL,
                    verification_attempts = 0,
                    verification_last_sent_at = NULL
                WHERE id = %s
                """,
                (customer_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def update_profile(
        self,
        customer_id: int,
        full_name: str,
        email: str,
        password_hash: str | None = None,
    ) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            if password_hash is None:
                cursor.execute(
                    """
                    UPDATE customer_accounts
                    SET full_name = %s, email = %s
                    WHERE id = %s
                    """,
                    (full_name, email, customer_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE customer_accounts
                    SET full_name = %s, email = %s, password_hash = %s
                    WHERE id = %s
                    """,
                    (full_name, email, password_hash, customer_id),
                )
            connection.commit()
        finally:
            connection.close()


class InventoryConflictError(Exception):
    pass


class RiderRepository:
    def list_riders(self) -> list[Rider]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, phone_number, service_area, status
                FROM riders
                ORDER BY full_name, id
                """
            )
            return [
                Rider(
                    id=row["id"],
                    full_name=row["full_name"],
                    phone_number=row["phone_number"],
                    service_area=row["service_area"],
                    status=row["status"],
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()

    def create(self, rider: Rider) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO riders (full_name, phone_number, service_area, status)
                VALUES (%s, %s, %s, %s)
                """,
                (rider.full_name, rider.phone_number, rider.service_area, rider.status),
            )
            rider_id = cursor.lastrowid
            connection.commit()
            return rider_id
        finally:
            connection.close()

    def get(self, rider_id: int) -> Rider | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, phone_number, service_area, status
                FROM riders
                WHERE id = %s
                """,
                (rider_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Rider(
                id=row["id"],
                full_name=row["full_name"],
                phone_number=row["phone_number"],
                service_area=row["service_area"],
                status=row["status"],
            )
        finally:
            connection.close()

    def update(self, rider: Rider) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE riders
                SET full_name = %s, phone_number = %s, service_area = %s, status = %s
                WHERE id = %s
                """,
                (
                    rider.full_name,
                    rider.phone_number,
                    rider.service_area,
                    rider.status,
                    rider.id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def delete(self, rider_id: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM riders WHERE id = %s", (rider_id,))
            connection.commit()
        finally:
            connection.close()

    def assign_to_order(self, order_id: int, rider_id: int | None, status: str = "pending") -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            valid_statuses = {
                "pending",
                "confirmed",
                "preparing",
                "assigned-to-rider",
                "out-for-delivery",
                "delivered",
                "for-delivery",
                "completed",
                "cancelled",
            }
            final_status = status if status in valid_statuses else "pending"
            cursor.execute(
                """
                UPDATE customer_orders
                SET rider_id = %s,
                    delivery_status = %s,
                    status = %s
                WHERE id = %s
                """,
                (rider_id, final_status, final_status, order_id),
            )
            connection.commit()
        finally:
            connection.close()


class ProductRepository:
    @staticmethod
    def _from_row(row: dict) -> Product:
        return Product.from_row(row)

    def list_products(self, available_for_sale: bool | None = None) -> list[Product]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            query = """
                SELECT id, name, category, sku, description, unit,
                       available_for_sale, unit_price, stock_quantity, image_path
                FROM products
            """
            params: tuple = ()
            if available_for_sale is not None:
                query += " WHERE available_for_sale = %s"
                params = (1 if available_for_sale else 0,)
            query += " ORDER BY name, id"
            cursor.execute(query, params)
            return [self._from_row(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def list_categories(self) -> list[str]:
        from catalog_config import INVENTORY_CATEGORIES

        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT name
                FROM categories
                ORDER BY sort_order, name
                """
            )
            names = [row[0] for row in cursor.fetchall()]
            if names:
                return names
            return list(INVENTORY_CATEGORIES)
        finally:
            connection.close()

    def inventory_summary(self, low_stock_threshold: int = 5) -> dict:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_products,
                    COALESCE(SUM(stock_quantity), 0) AS total_stock,
                    SUM(CASE WHEN stock_quantity = 0 THEN 1 ELSE 0 END) AS out_of_stock,
                    SUM(
                        CASE
                            WHEN stock_quantity > 0 AND stock_quantity <= %s THEN 1
                            ELSE 0
                        END
                    ) AS low_stock
                FROM products
                """,
                (low_stock_threshold,),
            )
            product_row = cursor.fetchone() or {}
            cursor.execute("SELECT COUNT(*) AS total_categories FROM categories")
            category_row = cursor.fetchone() or {}
            return {
                "total_products": int(product_row.get("total_products") or 0),
                "total_categories": int(category_row.get("total_categories") or 0),
                "total_stock": int(product_row.get("total_stock") or 0),
                "low_stock": int(product_row.get("low_stock") or 0),
                "out_of_stock": int(product_row.get("out_of_stock") or 0),
            }
        finally:
            connection.close()

    def get(self, product_id: int) -> Product | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, name, category, sku, description, unit,
                       available_for_sale, unit_price, stock_quantity, image_path
                FROM products
                WHERE id = %s
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._from_row(row)
        finally:
            connection.close()

    def create(self, product: Product) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO products
                    (name, category, sku, description, unit, available_for_sale,
                     unit_price, stock_quantity, image_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    product.name,
                    product.category,
                    product.sku or None,
                    product.description or None,
                    product.unit or "pieces",
                    1 if product.available_for_sale else 0,
                    product.unit_price,
                    product.stock_quantity,
                    product.image_path,
                ),
            )
            product_id = cursor.lastrowid
            connection.commit()
            return product_id
        finally:
            connection.close()

    def update(self, product: Product) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE products
                SET name = %s,
                    category = %s,
                    sku = %s,
                    description = %s,
                    unit = %s,
                    available_for_sale = %s,
                    unit_price = %s,
                    stock_quantity = %s,
                    image_path = %s
                WHERE id = %s
                """,
                (
                    product.name,
                    product.category,
                    product.sku or None,
                    product.description or None,
                    product.unit or "pieces",
                    1 if product.available_for_sale else 0,
                    product.unit_price,
                    product.stock_quantity,
                    product.image_path,
                    product.id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def delete(self, product_id: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
            connection.commit()
        finally:
            connection.close()


class CategoryRepository:
    def list_categories(self) -> list[Category]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, name, sort_order
                FROM categories
                ORDER BY sort_order, name
                """
            )
            return [
                Category(
                    id=row["id"],
                    name=row["name"],
                    sort_order=row["sort_order"],
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()

    def get(self, category_id: int) -> Category | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, name, sort_order FROM categories WHERE id = %s",
                (category_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Category(
                id=row["id"],
                name=row["name"],
                sort_order=row["sort_order"],
            )
        finally:
            connection.close()

    def create(self, name: str, sort_order: int = 0) -> int:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO categories (name, sort_order) VALUES (%s, %s)",
                (name, sort_order),
            )
            category_id = cursor.lastrowid
            connection.commit()
            return category_id
        finally:
            connection.close()

    def update(self, category_id: int, name: str, sort_order: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM categories WHERE id = %s",
                (category_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return
            old_name = row[0]
            cursor.execute(
                """
                UPDATE categories
                SET name = %s, sort_order = %s
                WHERE id = %s
                """,
                (name, sort_order, category_id),
            )
            if old_name != name:
                cursor.execute(
                    "UPDATE products SET category = %s WHERE category = %s",
                    (name, old_name),
                )
            connection.commit()
        finally:
            connection.close()

    def delete(self, category_id: int) -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM categories WHERE id = %s",
                (category_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return
            name = row[0]
            cursor.execute(
                "UPDATE products SET category = '' WHERE category = %s",
                (name,),
            )
            cursor.execute("DELETE FROM categories WHERE id = %s", (category_id,))
            connection.commit()
        finally:
            connection.close()


class StockMovementRepository:
    def list_movements(
        self,
        product_id: int | None = None,
        movement_type: str = "",
        limit: int = 100,
    ) -> list[StockMovement]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            clauses = []
            params: list = []
            if product_id is not None:
                clauses.append("m.product_id = %s")
                params.append(product_id)
            if movement_type in {"in", "out", "adjustment"}:
                clauses.append("m.movement_type = %s")
                params.append(movement_type)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            cursor.execute(
                f"""
                SELECT m.id, m.product_id, m.movement_type, m.quantity,
                       m.quantity_before, m.quantity_after, m.note,
                       m.created_by, m.created_at, p.name AS product_name,
                       COALESCE(u.full_name, '') AS created_by_name
                FROM stock_movements m
                JOIN products p ON p.id = m.product_id
                LEFT JOIN users u ON u.id = m.created_by
                {where}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [
                StockMovement(
                    id=row["id"],
                    product_id=row["product_id"],
                    movement_type=row["movement_type"],
                    quantity=row["quantity"],
                    quantity_before=row["quantity_before"],
                    quantity_after=row["quantity_after"],
                    note=row["note"] or "",
                    created_by=row["created_by"],
                    created_at=row["created_at"],
                    product_name=row["product_name"],
                    created_by_name=row["created_by_name"] or "",
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()

    def apply_movement(
        self,
        product_id: int,
        movement_type: str,
        quantity: int,
        note: str,
        created_by: int | None,
    ) -> int:
        if movement_type not in {"in", "out", "adjustment"}:
            raise ValueError("Invalid movement type.")
        if movement_type == "adjustment":
            if quantity < 0:
                raise ValueError("Adjusted stock cannot be negative.")
        elif quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        connection = get_connection()
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, stock_quantity
                FROM products
                WHERE id = %s
                FOR UPDATE
                """,
                (product_id,),
            )
            product = cursor.fetchone()
            if product is None:
                raise InventoryConflictError("Product not found.")
            before = int(product["stock_quantity"])
            if movement_type == "in":
                after = before + quantity
                recorded_quantity = quantity
            elif movement_type == "out":
                if quantity > before:
                    raise InventoryConflictError("Not enough stock for this stock out.")
                after = before - quantity
                recorded_quantity = quantity
            else:
                # adjustment: quantity is the target on-hand amount
                after = quantity
                recorded_quantity = abs(after - before)
            if after < 0 or after > 4294967295:
                raise InventoryConflictError("Resulting stock quantity is invalid.")
            cursor.execute(
                "UPDATE products SET stock_quantity = %s WHERE id = %s",
                (after, product_id),
            )
            cursor.execute(
                """
                INSERT INTO stock_movements
                    (product_id, movement_type, quantity, quantity_before,
                     quantity_after, note, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    product_id,
                    movement_type,
                    recorded_quantity,
                    before,
                    after,
                    note[:255],
                    created_by,
                ),
            )
            movement_id = cursor.lastrowid
            connection.commit()
            return movement_id
        except (mysql.connector.Error, InventoryConflictError, ValueError):
            connection.rollback()
            raise
        finally:
            connection.close()


class OrderRepository:
    def list_orders(
        self,
        search: str = "",
        status: str = "",
        limit: int | None = None,
    ) -> list[CustomerOrder]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            query = """
                SELECT o.id, o.customer_name, o.customer_contact,
                       o.delivery_address, o.status, o.created_at,
                       COALESCE(SUM(i.quantity), 0) AS item_count,
                       COALESCE(SUM(i.quantity * i.unit_price), 0.00) AS total
                FROM customer_orders o
                LEFT JOIN order_items i ON i.order_id = o.id
                WHERE (%s = '' OR o.status = %s)
                  AND (%s = '' OR o.customer_name LIKE %s
                       OR o.customer_contact LIKE %s
                       OR CAST(o.id AS CHAR) LIKE %s)
                GROUP BY o.id
                ORDER BY o.created_at DESC
            """
            parameters: list = [
                status,
                status,
                search,
                f"%{search}%",
                f"%{search}%",
                f"%{search}%",
            ]
            if limit is not None:
                query += " LIMIT %s"
                parameters.append(limit)
            cursor.execute(query, tuple(parameters))
            return cursor.fetchall()
        finally:
            connection.close()

    def get(self, order_id: int) -> CustomerOrder | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, customer_name, customer_contact, delivery_address,
                       status, created_at, customer_account_id, payment_status,
                       payment_method, payment_reference, payment_screenshot_path,
                       stock_reserved, delivery_option, delivery_fee, delivery_status,
                       service_area, rider_id
                FROM customer_orders
                WHERE id = %s
                """,
                (order_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            cursor.execute(
                """
                SELECT product_id, product_name, quantity, unit_price
                FROM order_items
                WHERE order_id = %s
                ORDER BY id
                """,
                (order_id,),
            )
            items = [
                OrderItem(
                    product_name=item["product_name"],
                    quantity=item["quantity"],
                    unit_price=Decimal(item["unit_price"]),
                    product_id=item["product_id"],
                )
                for item in cursor.fetchall()
            ]
            return CustomerOrder(
                id=row["id"],
                customer_name=row["customer_name"],
                customer_contact=row["customer_contact"],
                delivery_address=row["delivery_address"],
                status=row["status"],
                items=items,
                created_at=row["created_at"],
                customer_account_id=row["customer_account_id"],
                payment_status=row["payment_status"],
                payment_method=row.get("payment_method") or "",
                payment_reference=row.get("payment_reference") or "",
                payment_screenshot_path=row.get("payment_screenshot_path"),
                stock_reserved=bool(row["stock_reserved"]),
                delivery_option=row.get("delivery_option", "pickup"),
                delivery_fee=Decimal(row.get("delivery_fee", "0.00") or "0.00"),
                delivery_status=row.get("delivery_status", "pending"),
                service_area=row.get("service_area", ""),
                rider_id=row.get("rider_id"),
            )
        finally:
            connection.close()

    def create_customer_order(
        self,
        order: CustomerOrder,
        customer_id: int | None,
        cart: dict[int, int],
    ) -> int:
        connection = get_connection()
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            products_by_id = {}
            for product_id in sorted(cart):
                cursor.execute(
                    """
                    SELECT id, name, unit_price, stock_quantity
                    FROM products
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (product_id,),
                )
                product = cursor.fetchone()
                if product is None or product["stock_quantity"] < cart[product_id]:
                    raise InventoryConflictError(
                        f"Not enough stock available for product #{product_id}."
                    )
                products_by_id[product_id] = product

            items = [
                OrderItem(
                    product_id=product_id,
                    product_name=product["name"],
                    quantity=cart[product_id],
                    unit_price=Decimal(product["unit_price"]),
                )
                for product_id, product in products_by_id.items()
            ]
            payment_status = order.payment_status or "awaiting-payment"
            payment_method = order.payment_method or ""
            cursor.execute(
                """
                INSERT INTO customer_orders
                    (customer_name, customer_contact, delivery_address,
                     delivery_option, delivery_fee, delivery_status,
                     status, customer_account_id, payment_status,
                     payment_method, payment_reference, stock_reserved)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, TRUE)
                """,
                (
                    order.customer_name,
                    order.customer_contact,
                    order.delivery_address,
                    order.delivery_option,
                    order.delivery_fee,
                    order.delivery_status,
                    customer_id,
                    payment_status,
                    payment_method,
                    order.payment_reference or "",
                ),
            )
            order_id = cursor.lastrowid
            for item in items:
                cursor.execute(
                    """
                    UPDATE products
                    SET stock_quantity = stock_quantity - %s
                    WHERE id = %s AND stock_quantity >= %s
                    """,
                    (item.quantity, item.product_id, item.quantity),
                )
                if cursor.rowcount != 1:
                    raise InventoryConflictError(
                        f"Not enough stock available for {item.product_name}."
                    )
                cursor.execute(
                    """
                    INSERT INTO order_items
                        (order_id, product_id, product_name, quantity, unit_price)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        item.product_id,
                        item.product_name,
                        item.quantity,
                        item.unit_price,
                    ),
                )
            connection.commit()
            return order_id
        except (mysql.connector.Error, InventoryConflictError):
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_customer_orders(self, customer_id: int) -> list[dict]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT o.id, o.status, o.payment_status, o.created_at,
                       o.delivery_option, o.delivery_fee, o.delivery_status,
                       COALESCE(SUM(i.quantity), 0) AS item_count,
                       COALESCE(SUM(i.quantity * i.unit_price), 0.00) AS total
                FROM customer_orders o
                LEFT JOIN order_items i ON i.order_id = o.id
                WHERE o.customer_account_id = %s
                GROUP BY o.id
                ORDER BY o.created_at DESC
                """,
                (customer_id,),
            )
            return cursor.fetchall()
        finally:
            connection.close()

    def get_customer_order(self, order_id: int, customer_id: int) -> CustomerOrder | None:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, customer_name, customer_contact, delivery_address,
                       status, created_at, customer_account_id,
                       payment_status, payment_method, payment_reference,
                       payment_screenshot_path, stock_reserved, delivery_option,
                       delivery_fee, delivery_status, service_area, rider_id
                FROM customer_orders
                WHERE id = %s AND customer_account_id = %s
                """,
                (order_id, customer_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                SELECT product_id, product_name, quantity, unit_price
                FROM order_items WHERE order_id = %s ORDER BY id
                """,
                (order_id,),
            )
            items = [
                OrderItem(
                    product_id=item["product_id"],
                    product_name=item["product_name"],
                    quantity=item["quantity"],
                    unit_price=Decimal(item["unit_price"]),
                )
                for item in cursor.fetchall()
            ]
            return CustomerOrder(
                id=row["id"],
                customer_name=row["customer_name"],
                customer_contact=row["customer_contact"],
                delivery_address=row["delivery_address"],
                status=row["status"],
                items=items,
                created_at=row["created_at"],
                customer_account_id=row["customer_account_id"],
                payment_status=row["payment_status"],
                payment_method=row.get("payment_method") or "",
                payment_reference=row.get("payment_reference") or "",
                payment_screenshot_path=row.get("payment_screenshot_path"),
                stock_reserved=bool(row["stock_reserved"]),
                delivery_option=row.get("delivery_option", "pickup"),
                delivery_fee=Decimal(row.get("delivery_fee", "0.00") or "0.00"),
                delivery_status=row.get("delivery_status", "pending"),
                service_area=row.get("service_area", ""),
                rider_id=row.get("rider_id"),
            )
        finally:
            connection.close()

    def submit_payment_reference(
        self,
        order_id: int,
        customer_id: int,
        reference: str,
        screenshot_path: str | None = None,
    ) -> bool:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            if screenshot_path:
                cursor.execute(
                    """
                    UPDATE customer_orders
                    SET payment_reference = %s,
                        payment_screenshot_path = %s,
                        payment_status = 'pending-verification'
                    WHERE id = %s AND customer_account_id = %s
                      AND payment_status IN ('awaiting-payment', 'pending-verification', 'demo-pending')
                      AND payment_method IN ('gcash', 'bank_transfer')
                      AND status != 'cancelled' AND stock_reserved = TRUE
                    """,
                    (reference, screenshot_path, order_id, customer_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE customer_orders
                    SET payment_reference = %s,
                        payment_status = 'pending-verification'
                    WHERE id = %s AND customer_account_id = %s
                      AND payment_status IN ('awaiting-payment', 'pending-verification', 'demo-pending')
                      AND payment_method IN ('gcash', 'bank_transfer')
                      AND status != 'cancelled' AND stock_reserved = TRUE
                    """,
                    (reference, order_id, customer_id),
                )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def verify_payment(self, order_id: int) -> bool:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_orders
                SET payment_status = 'verified'
                WHERE id = %s
                  AND payment_status IN ('pending-verification', 'demo-pending', 'cod-pending')
                  AND status != 'cancelled' AND stock_reserved = TRUE
                """,
                (order_id,),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def complete_demo_payment(self, order_id: int, customer_id: int) -> bool:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE customer_orders
                SET payment_status = 'demo-paid'
                WHERE id = %s AND customer_account_id = %s
                  AND payment_status = 'demo-pending'
                  AND status != 'cancelled' AND stock_reserved = TRUE
                """,
                (order_id, customer_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def assign_rider(self, order_id: int, rider_id: int | None, status: str = "pending") -> None:
        connection = get_connection()
        try:
            cursor = connection.cursor()
            valid_statuses = {
                "pending",
                "confirmed",
                "preparing",
                "assigned-to-rider",
                "out-for-delivery",
                "delivered",
                "for-delivery",
                "completed",
                "cancelled",
            }
            final_status = status if status in valid_statuses else "pending"
            cursor.execute(
                """
                UPDATE customer_orders
                SET rider_id = %s,
                    delivery_status = %s,
                    status = %s
                WHERE id = %s
                """,
                (rider_id, final_status, final_status, order_id),
            )
            connection.commit()
        finally:
            connection.close()

    def create(self, order: CustomerOrder, user_id: int) -> int:
        connection = get_connection()
        try:
            connection.start_transaction()
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO customer_orders
                    (customer_name, customer_contact, delivery_address, status, created_by)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order.customer_name,
                    order.customer_contact,
                    order.delivery_address,
                    order.status,
                    user_id,
                ),
            )
            order_id = cursor.lastrowid
            cursor.executemany(
                """
                INSERT INTO order_items (order_id, product_name, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (
                        order_id,
                        item.product_name,
                        item.quantity,
                        item.unit_price,
                    )
                    for item in order.items
                ],
            )
            connection.commit()
            return order_id
        except mysql.connector.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

    def update(self, order: CustomerOrder) -> None:
        connection = get_connection()
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT customer_account_id, stock_reserved
                FROM customer_orders
                WHERE id = %s
                FOR UPDATE
                """,
                (order.id,),
            )
            current = cursor.fetchone()
            if current is None:
                raise ValueError(f"Order {order.id} does not exist.")

            if current["customer_account_id"] is not None:
                if current["stock_reserved"] and order.status == "cancelled":
                    cursor.execute(
                        """
                        SELECT product_id, quantity
                        FROM order_items
                        WHERE order_id = %s AND product_id IS NOT NULL
                        """,
                        (order.id,),
                    )
                    for item in cursor.fetchall():
                        cursor.execute(
                            """
                            UPDATE products
                            SET stock_quantity = stock_quantity + %s
                            WHERE id = %s
                            """,
                            (item["quantity"], item["product_id"]),
                        )
                    cursor.execute(
                        "UPDATE customer_orders SET stock_reserved = FALSE WHERE id = %s",
                        (order.id,),
                    )
                elif not current["stock_reserved"] and order.status != "cancelled":
                    cursor.execute(
                        """
                        SELECT product_id, product_name, quantity
                        FROM order_items
                        WHERE order_id = %s
                        """,
                        (order.id,),
                    )
                    items = cursor.fetchall()
                    if not items or any(item["product_id"] is None for item in items):
                        raise InventoryConflictError(
                            "This cancelled order contains products that are no longer available."
                        )
                    for item in sorted(items, key=lambda value: value["product_id"]):
                        cursor.execute(
                            """
                            UPDATE products
                            SET stock_quantity = stock_quantity - %s
                            WHERE id = %s AND stock_quantity >= %s
                            """,
                            (
                                item["quantity"],
                                item["product_id"],
                                item["quantity"],
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise InventoryConflictError(
                                f"Not enough stock available for {item['product_name']}."
                            )
                    cursor.execute(
                        "UPDATE customer_orders SET stock_reserved = TRUE WHERE id = %s",
                        (order.id,),
                    )

            cursor.execute(
                """
                UPDATE customer_orders
                SET customer_name = %s, customer_contact = %s,
                    delivery_address = %s, status = %s
                WHERE id = %s
                """,
                (
                    order.customer_name,
                    order.customer_contact,
                    order.delivery_address,
                    order.status,
                    order.id,
                ),
            )
            if current["customer_account_id"] is None:
                cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order.id,))
                cursor.executemany(
                    """
                    INSERT INTO order_items
                        (order_id, product_id, product_name, quantity, unit_price)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            order.id,
                            item.product_id,
                            item.product_name,
                            item.quantity,
                            item.unit_price,
                        )
                        for item in order.items
                    ],
                )
            connection.commit()
        except (mysql.connector.Error, InventoryConflictError, ValueError):
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete(self, order_id: int) -> None:
        connection = get_connection()
        try:
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT customer_account_id, stock_reserved
                FROM customer_orders WHERE id = %s FOR UPDATE
                """,
                (order_id,),
            )
            order = cursor.fetchone()
            if order is None:
                connection.commit()
                return
            if order["customer_account_id"] is not None and order["stock_reserved"]:
                cursor.execute(
                    """
                    SELECT product_id, quantity
                    FROM order_items
                    WHERE order_id = %s AND product_id IS NOT NULL
                    """,
                    (order_id,),
                )
                for item in cursor.fetchall():
                    cursor.execute(
                        """
                        UPDATE products SET stock_quantity = stock_quantity + %s
                        WHERE id = %s
                        """,
                        (item["quantity"], item["product_id"]),
                    )
            cursor.execute("DELETE FROM customer_orders WHERE id = %s", (order_id,))
            connection.commit()
        except mysql.connector.Error:
            connection.rollback()
            raise
        finally:
            connection.close()

    def summary(self) -> dict[str, int]:
        connection = get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(status = 'pending') AS pending,
                       SUM(status = 'for-delivery') AS for_delivery,
                       SUM(status = 'completed') AS completed
                FROM customer_orders
                """
            )
            row = cursor.fetchone()
            return {key: int(value or 0) for key, value in row.items()}
        finally:
            connection.close()
