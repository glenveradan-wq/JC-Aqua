import re

import mysql.connector

from database import mysql_settings


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(120) NOT NULL,
        email VARCHAR(254) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        email_verified BOOLEAN NOT NULL DEFAULT FALSE,
        verification_code_hash VARCHAR(255) NULL,
        verification_expires_at DATETIME NULL,
        verification_attempts INT UNSIGNED NOT NULL DEFAULT 0,
        verification_last_sent_at DATETIME NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_accounts (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(120) NOT NULL,
        email VARCHAR(254) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        email_verified BOOLEAN NOT NULL DEFAULT FALSE,
        verification_code_hash VARCHAR(255) NULL,
        verification_expires_at DATETIME NULL,
        verification_attempts INT UNSIGNED NOT NULL DEFAULT 0,
        verification_last_sent_at DATETIME NULL,
        firebase_uid VARCHAR(128) NULL UNIQUE,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(160) NOT NULL,
        category VARCHAR(80) NOT NULL DEFAULT '',
        sku VARCHAR(40) NULL,
        description TEXT NULL,
        unit VARCHAR(20) NOT NULL DEFAULT 'pieces',
        available_for_sale BOOLEAN NOT NULL DEFAULT TRUE,
        unit_price DECIMAL(10, 2) NOT NULL,
        stock_quantity INT UNSIGNED NOT NULL DEFAULT 0,
        image_path VARCHAR(255) NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_products_sku (sku)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        sort_order INT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        product_id BIGINT UNSIGNED NOT NULL,
        movement_type ENUM('in', 'out', 'adjustment') NOT NULL,
        quantity INT NOT NULL,
        quantity_before INT UNSIGNED NOT NULL,
        quantity_after INT UNSIGNED NOT NULL,
        note VARCHAR(255) NOT NULL DEFAULT '',
        created_by BIGINT UNSIGNED NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_stock_movements_product
            FOREIGN KEY (product_id) REFERENCES products(id)
            ON DELETE CASCADE ON UPDATE CASCADE,
        CONSTRAINT fk_stock_movements_user
            FOREIGN KEY (created_by) REFERENCES users(id)
            ON DELETE SET NULL ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_orders (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        customer_name VARCHAR(120) NOT NULL,
        customer_contact VARCHAR(40) NOT NULL,
        delivery_address VARCHAR(500) NOT NULL DEFAULT '',
        delivery_option ENUM('pickup', 'delivery') NOT NULL DEFAULT 'pickup',
        delivery_fee DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        delivery_status ENUM(
            'pending', 'confirmed', 'preparing', 'assigned-to-rider',
            'out-for-delivery', 'delivered', 'for-delivery', 'completed', 'cancelled'
        ) NOT NULL DEFAULT 'pending',
        service_area VARCHAR(120) NOT NULL DEFAULT '',
        status ENUM(
            'pending', 'confirmed', 'preparing', 'assigned-to-rider',
            'out-for-delivery', 'delivered', 'for-delivery', 'completed', 'cancelled'
        ) NOT NULL DEFAULT 'pending',
        created_by BIGINT UNSIGNED NULL,
        customer_account_id BIGINT UNSIGNED NULL,
        payment_status ENUM(
            'not-required', 'demo-pending', 'demo-paid',
            'awaiting-payment', 'pending-verification', 'verified', 'cod-pending'
        ) NOT NULL DEFAULT 'not-required',
        payment_method VARCHAR(40) NOT NULL DEFAULT '',
        payment_reference VARCHAR(120) NOT NULL DEFAULT '',
        payment_screenshot_path VARCHAR(255) NULL,
        stock_reserved BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_orders_created_by
            FOREIGN KEY (created_by) REFERENCES users(id)
            ON UPDATE CASCADE,
        CONSTRAINT fk_orders_customer_account
            FOREIGN KEY (customer_account_id) REFERENCES customer_accounts(id)
            ON DELETE SET NULL
            ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS riders (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(120) NOT NULL,
        phone_number VARCHAR(40) NOT NULL,
        service_area VARCHAR(120) NOT NULL DEFAULT '',
        status ENUM('available', 'busy', 'offline') NOT NULL DEFAULT 'available',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        order_id BIGINT UNSIGNED NOT NULL,
        product_id BIGINT UNSIGNED NULL,
        product_name VARCHAR(160) NOT NULL,
        quantity INT UNSIGNED NOT NULL,
        unit_price DECIMAL(10, 2) NOT NULL,
        CONSTRAINT fk_order_items_order
            FOREIGN KEY (order_id) REFERENCES customer_orders(id)
            ON DELETE CASCADE
            ON UPDATE CASCADE,
        CONSTRAINT fk_order_items_product
            FOREIGN KEY (product_id) REFERENCES products(id)
            ON DELETE SET NULL
            ON UPDATE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS shop_settings (
        setting_key VARCHAR(80) NOT NULL PRIMARY KEY,
        setting_value VARCHAR(255) NOT NULL DEFAULT '',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def _ensure_verification_columns(cursor, table_name: str) -> None:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (table_name,),
    )
    columns = {row[0] for row in cursor.fetchall()}
    if "email_verified" not in columns:
        # Existing accounts stay usable; new signups set email_verified explicitly.
        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            ADD email_verified BOOLEAN NOT NULL DEFAULT TRUE
            """
        )
    if "verification_code_hash" not in columns:
        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            ADD verification_code_hash VARCHAR(255) NULL
            """
        )
    if "verification_expires_at" not in columns:
        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            ADD verification_expires_at DATETIME NULL
            """
        )
    if "verification_attempts" not in columns:
        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            ADD verification_attempts INT UNSIGNED NOT NULL DEFAULT 0
            """
        )
    if "verification_last_sent_at" not in columns:
        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            ADD verification_last_sent_at DATETIME NULL
            """
        )


def migrate_existing_schema(cursor) -> None:
    _ensure_verification_columns(cursor, "users")
    _ensure_verification_columns(cursor, "customer_accounts")

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'customer_accounts'
        """
    )
    customer_columns = {row[0] for row in cursor.fetchall()}
    if "firebase_uid" not in customer_columns:
        cursor.execute(
            """
            ALTER TABLE customer_accounts
            ADD firebase_uid VARCHAR(128) NULL UNIQUE
            """
        )

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'products'
        """
    )
    product_columns = {row[0] for row in cursor.fetchall()}
    if "image_path" not in product_columns:
        cursor.execute(
            "ALTER TABLE products ADD image_path VARCHAR(255) NULL"
        )
    if "sku" not in product_columns:
        cursor.execute(
            "ALTER TABLE products ADD sku VARCHAR(40) NULL"
        )
        cursor.execute(
            """
            SELECT INDEX_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'products'
              AND INDEX_NAME = 'uq_products_sku'
            """
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE products ADD UNIQUE KEY uq_products_sku (sku)"
            )
    if "description" not in product_columns:
        cursor.execute("ALTER TABLE products ADD description TEXT NULL")
    if "unit" not in product_columns:
        cursor.execute(
            "ALTER TABLE products ADD unit VARCHAR(20) NOT NULL DEFAULT 'pieces'"
        )
    if "available_for_sale" not in product_columns:
        cursor.execute(
            "ALTER TABLE products ADD available_for_sale BOOLEAN NOT NULL DEFAULT TRUE"
        )

    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'categories'
        """
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            CREATE TABLE categories (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(80) NOT NULL UNIQUE,
                sort_order INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    from catalog_config import INVENTORY_CATEGORIES

    for sort_order, category_name in enumerate(INVENTORY_CATEGORIES, start=1):
        cursor.execute(
            """
            INSERT INTO categories (name, sort_order)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE sort_order = VALUES(sort_order)
            """,
            (category_name, sort_order),
        )
    category_placeholders = ", ".join(["%s"] * len(INVENTORY_CATEGORIES))
    cursor.execute(
        f"DELETE FROM categories WHERE name NOT IN ({category_placeholders})",
        INVENTORY_CATEGORIES,
    )
    # Keep product rows; only clear labels that are not one of the three categories.
    cursor.execute(
        f"""
        UPDATE products
        SET category = ''
        WHERE category IS NOT NULL
          AND TRIM(category) <> ''
          AND category NOT IN ({category_placeholders})
        """,
        INVENTORY_CATEGORIES,
    )

    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'stock_movements'
        """
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            CREATE TABLE stock_movements (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                product_id BIGINT UNSIGNED NOT NULL,
                movement_type ENUM('in', 'out', 'adjustment') NOT NULL,
                quantity INT NOT NULL,
                quantity_before INT UNSIGNED NOT NULL,
                quantity_after INT UNSIGNED NOT NULL,
                note VARCHAR(255) NOT NULL DEFAULT '',
                created_by BIGINT UNSIGNED NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_stock_movements_product
                    FOREIGN KEY (product_id) REFERENCES products(id)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_stock_movements_user
                    FOREIGN KEY (created_by) REFERENCES users(id)
                    ON DELETE SET NULL ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'customer_orders'
        """
    )
    order_columns = {row[0] for row in cursor.fetchall()}
    if "created_by" in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders MODIFY created_by BIGINT UNSIGNED NULL"
        )
    if "customer_account_id" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD customer_account_id BIGINT UNSIGNED NULL"
        )
    if "payment_status" not in order_columns:
        cursor.execute(
            """
            ALTER TABLE customer_orders
            ADD payment_status ENUM(
                'not-required', 'demo-pending', 'demo-paid',
                'awaiting-payment', 'pending-verification', 'verified', 'cod-pending'
            ) NOT NULL DEFAULT 'not-required'
            """
        )
    else:
        cursor.execute(
            """
            ALTER TABLE customer_orders
            MODIFY payment_status ENUM(
                'not-required', 'demo-pending', 'demo-paid',
                'awaiting-payment', 'pending-verification', 'verified', 'cod-pending'
            ) NOT NULL DEFAULT 'not-required'
            """
        )
    if "payment_method" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD payment_method VARCHAR(40) NOT NULL DEFAULT ''"
        )
    if "payment_reference" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD payment_reference VARCHAR(120) NOT NULL DEFAULT ''"
        )
    if "payment_screenshot_path" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD payment_screenshot_path VARCHAR(255) NULL"
        )
    if "stock_reserved" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD stock_reserved BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if "delivery_option" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD delivery_option ENUM('pickup', 'delivery') NOT NULL DEFAULT 'pickup'"
        )
    if "delivery_fee" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD delivery_fee DECIMAL(10, 2) NOT NULL DEFAULT 0.00"
        )
    if "delivery_status" not in order_columns:
        cursor.execute(
            """
            ALTER TABLE customer_orders
            ADD delivery_status ENUM(
                'pending', 'confirmed', 'preparing', 'assigned-to-rider',
                'out-for-delivery', 'delivered', 'for-delivery', 'completed', 'cancelled'
            ) NOT NULL DEFAULT 'pending'
            """
        )
    if "service_area" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD service_area VARCHAR(120) NOT NULL DEFAULT ''"
        )

    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'riders'
        """
    )
    if cursor.fetchone() is None:
        cursor.execute(
            """
            CREATE TABLE riders (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                full_name VARCHAR(120) NOT NULL,
                phone_number VARCHAR(40) NOT NULL,
                service_area VARCHAR(120) NOT NULL DEFAULT '',
                status ENUM('available', 'busy', 'offline') NOT NULL DEFAULT 'available',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    if "rider_id" not in order_columns:
        cursor.execute(
            "ALTER TABLE customer_orders ADD rider_id BIGINT UNSIGNED NULL"
        )
        cursor.execute(
            """
            ALTER TABLE customer_orders
            ADD CONSTRAINT fk_orders_rider
            FOREIGN KEY (rider_id) REFERENCES riders(id)
            ON DELETE SET NULL ON UPDATE CASCADE
            """
        )

    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'order_items'
        """
    )
    item_columns = {row[0] for row in cursor.fetchall()}
    if "product_id" not in item_columns:
        cursor.execute("ALTER TABLE order_items ADD product_id BIGINT UNSIGNED NULL")

    cursor.execute(
        """
        SELECT TABLE_NAME, CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND CONSTRAINT_TYPE = 'FOREIGN KEY'
          AND TABLE_NAME IN ('customer_orders', 'order_items')
        """
    )
    constraints = {row[1] for row in cursor.fetchall()}
    if "fk_orders_customer_account" not in constraints:
        cursor.execute(
            """
            ALTER TABLE customer_orders
            ADD CONSTRAINT fk_orders_customer_account
            FOREIGN KEY (customer_account_id) REFERENCES customer_accounts(id)
            ON DELETE SET NULL ON UPDATE CASCADE
            """
        )
    if "fk_order_items_product" not in constraints:
        cursor.execute(
            """
            ALTER TABLE order_items
            ADD CONSTRAINT fk_order_items_product
            FOREIGN KEY (product_id) REFERENCES products(id)
            ON DELETE SET NULL ON UPDATE CASCADE
            """
        )


def initialize_database() -> None:
    settings = mysql_settings(include_database=False)
    database_name = mysql_settings()["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        raise ValueError("MYSQL_DATABASE may contain only letters, numbers, and underscores.")

    connection = mysql.connector.connect(**settings)
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    finally:
        connection.close()

    settings["database"] = database_name
    connection = mysql.connector.connect(**settings)
    try:
        cursor = connection.cursor()
        for statement in SCHEMA:
            cursor.execute(statement)
        migrate_existing_schema(cursor)
    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
    print("Database and tables are ready.")
