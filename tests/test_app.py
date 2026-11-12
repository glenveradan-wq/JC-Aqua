import os
import unittest
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("FLASK_SECRET_KEY", "test-only-secret-key")

import app as app_module
import inventory_bp as inventory_module
from models import (
    Category,
    CustomerAccount,
    CustomerOrder,
    EmailVerificationCode,
    OrderItem,
    PendingRegistration,
    Product,
    User,
)
from repositories import InventoryConflictError
from werkzeug.security import check_password_hash


class FakeMailService:
    def __init__(self):
        self.enabled = True
        self.sent = []

    @property
    def is_configured(self):
        return True

    def send_verification_code(self, recipient, full_name, code, account_type):
        self.sent.append(("verification", recipient, code, account_type))
        return True

    def send_welcome_email(self, recipient, full_name, account_type):
        self.sent.append(("welcome", recipient, full_name, account_type))
        return True

    def send_order_confirmation(self, recipient, full_name, order_id, total, delivery_option):
        self.sent.append(("order", recipient, order_id))
        return True


class FakeCustomerAccountRepository:
    def __init__(self):
        self.accounts_by_email = {}
        self.accounts_by_id = {}

    def create_account(self, account):
        account.id = len(self.accounts_by_id) + 1
        self.accounts_by_email[account.email] = account
        self.accounts_by_id[account.id] = account
        return account.id

    def create_verified_from_pending(self, full_name, email, password_hash, verified_at):
        account = CustomerAccount(
            id=0,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            email_verified=True,
            email_verified_at=verified_at,
            first_login_verified=False,
        )
        return self.create_account(account)

    def get_by_email(self, email):
        return self.accounts_by_email.get(email)

    def get_by_id(self, account_id):
        return self.accounts_by_id.get(account_id)

    def get_by_firebase_uid(self, firebase_uid):
        for account in self.accounts_by_id.values():
            if account.firebase_uid == firebase_uid:
                return account
        return None

    def link_firebase_uid(self, customer_id, firebase_uid):
        account = self.accounts_by_id[customer_id]
        account.firebase_uid = firebase_uid
        account.email_verified = True
        account.first_login_verified = True

    def set_verification_challenge(
        self,
        customer_id,
        verification_code_hash,
        verification_expires_at,
        verification_last_sent_at=None,
    ):
        account = self.accounts_by_id[customer_id]
        account.verification_code_hash = verification_code_hash
        account.verification_expires_at = verification_expires_at
        account.verification_attempts = 0
        account.verification_last_sent_at = verification_last_sent_at
        account.email_verified = False

    def increment_verification_attempts(self, customer_id):
        account = self.accounts_by_id[customer_id]
        account.verification_attempts = int(account.verification_attempts or 0) + 1
        return account.verification_attempts

    def mark_email_verified(self, customer_id):
        account = self.accounts_by_id[customer_id]
        account.email_verified = True
        account.email_verified_at = datetime.utcnow()
        account.verification_code_hash = None
        account.verification_expires_at = None
        account.verification_attempts = 0
        account.verification_last_sent_at = None

    def mark_first_login_verified(self, customer_id):
        account = self.accounts_by_id[customer_id]
        account.first_login_verified = True
        account.first_login_verified_at = datetime.utcnow()

    def update_profile(self, customer_id, full_name, email, password_hash=None):
        account = self.accounts_by_id[customer_id]
        self.accounts_by_email.pop(account.email, None)
        account.full_name = full_name
        account.email = email
        if password_hash is not None:
            account.password_hash = password_hash
        self.accounts_by_email[email] = account


class FakePendingRegistrationRepository:
    def __init__(self):
        self.by_email = {}

    def get_by_email(self, email):
        return self.by_email.get(email)

    def upsert(self, full_name, email, password_hash, otp_hash, otp_expires_at, last_sent_at):
        existing = self.by_email.get(email)
        pending_id = existing.id if existing else len(self.by_email) + 1
        pending = PendingRegistration(
            id=pending_id,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            otp_hash=otp_hash,
            otp_expires_at=otp_expires_at,
            attempts=0,
            last_sent_at=last_sent_at,
            created_at=datetime.utcnow(),
        )
        self.by_email[email] = pending
        return pending_id

    def set_otp(self, email, otp_hash, otp_expires_at, last_sent_at):
        pending = self.by_email[email]
        pending.otp_hash = otp_hash
        pending.otp_expires_at = otp_expires_at
        pending.attempts = 0
        pending.last_sent_at = last_sent_at

    def increment_attempts(self, email):
        pending = self.by_email[email]
        pending.attempts += 1
        return pending.attempts

    def delete_by_email(self, email):
        self.by_email.pop(email, None)


class FakeEmailVerificationCodeRepository:
    def __init__(self):
        self.codes = []
        self.next_id = 1

    def invalidate_active(self, email, verification_type):
        for code in self.codes:
            if (
                code.email == email
                and code.verification_type == verification_type
                and not code.is_used
            ):
                code.is_used = True

    def create_code(self, email, otp_hash, verification_type, expires_at, customer_id=None):
        self.invalidate_active(email, verification_type)
        code = EmailVerificationCode(
            id=self.next_id,
            email=email,
            otp_hash=otp_hash,
            verification_type=verification_type,
            expires_at=expires_at,
            customer_id=customer_id,
            attempts=0,
            is_used=False,
            created_at=datetime.utcnow(),
        )
        self.next_id += 1
        self.codes.append(code)
        return code.id

    def get_active(self, email, verification_type):
        for code in reversed(self.codes):
            if (
                code.email == email
                and code.verification_type == verification_type
                and not code.is_used
            ):
                return code
        return None

    def increment_attempts(self, code_id):
        for code in self.codes:
            if code.id == code_id:
                code.attempts += 1
                return code.attempts
        return 0

    def mark_used(self, code_id):
        for code in self.codes:
            if code.id == code_id:
                code.is_used = True
                code.verified_at = datetime.utcnow()
                return


class FakeUserRepository:
    def __init__(self):
        self.users_by_email = {}
        self.users_by_id = {}

    def create_account(self, user):
        user.id = len(self.users_by_id) + 1
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user
        return user.id

    def get_by_email(self, email):
        return self.users_by_email.get(email)

    def get_by_id(self, user_id):
        return self.users_by_id.get(user_id)

    def set_verification_challenge(
        self,
        user_id,
        verification_code_hash,
        verification_expires_at,
        verification_last_sent_at=None,
    ):
        user = self.users_by_id[user_id]
        user.verification_code_hash = verification_code_hash
        user.verification_expires_at = verification_expires_at
        user.verification_attempts = 0
        user.verification_last_sent_at = verification_last_sent_at
        user.email_verified = False

    def increment_verification_attempts(self, user_id):
        user = self.users_by_id[user_id]
        user.verification_attempts = int(user.verification_attempts or 0) + 1
        return user.verification_attempts

    def mark_email_verified(self, user_id):
        user = self.users_by_id[user_id]
        user.email_verified = True
        user.verification_code_hash = None
        user.verification_expires_at = None
        user.verification_attempts = 0
        user.verification_last_sent_at = None

    def update_profile(self, user_id, full_name, email, password_hash=None):
        user = self.users_by_id[user_id]
        self.users_by_email.pop(user.email, None)
        user.full_name = full_name
        user.email = email
        if password_hash is not None:
            user.password_hash = password_hash
        self.users_by_email[email] = user


def verified_user(full_name, email, password):
    user = User.create(full_name, email, password)
    user.email_verified = True
    return user


def verified_customer(full_name, email, password):
    account = CustomerAccount.create(full_name, email, password)
    account.email_verified = True
    account.first_login_verified = True
    return account

class FakeOrderRepository:
    def __init__(self):
        self.created = []
        self.customer_created = []
        self.customer_orders = {}
        self.products_repo = None

    def create(self, order, user_id):
        order.id = 5
        self.created.append((order, user_id))
        return order.id

    def summary(self):
        return {"total": 0, "pending": 0, "for_delivery": 0, "completed": 0}

    def list_orders(self, search="", status="", limit=None):
        return []

    def get(self, order_id):
        if order_id in self.customer_orders:
            return self.customer_orders[order_id]
        if order_id == 5:
            return CustomerOrder(
                id=5,
                customer_name="Aqua Customer",
                customer_contact="09171234567",
                delivery_address="Sta. Cruz, Laguna",
                status="pending",
                items=[
                    OrderItem(
                        product_name="Goldfish",
                        quantity=2,
                        unit_price=Decimal("25.00"),
                    )
                ],
                created_at=datetime(2026, 11, 11, 10, 0),
            )
        return None

    def update(self, order):
        return None

    def delete(self, order_id):
        return None

    def create_customer_order(self, order, customer_id, cart):
        from repositories import InventoryConflictError

        items = []
        for product_id, quantity in cart.items():
            product_name = "Betta fish"
            unit_price = Decimal("75.00")
            if self.products_repo is not None:
                product = self.products_repo.get(product_id)
                if product is None or product.stock_quantity < quantity:
                    raise InventoryConflictError(
                        f"Not enough stock available for product #{product_id}."
                    )
                product.stock_quantity -= quantity
                product_name = product.name
                unit_price = product.unit_price
            items.append(
                OrderItem(
                    product_id=product_id,
                    product_name=product_name,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )
        order.id = 6
        order.created_at = datetime(2026, 11, 11, 10, 0)
        order.customer_account_id = customer_id
        if not order.payment_status or order.payment_status == "not-required":
            order.payment_status = "awaiting-payment"
        order.stock_reserved = True
        order.items = items
        self.customer_orders[order.id] = order
        self.customer_created.append((order, customer_id, cart.copy()))
        return order.id

    def submit_payment_reference(self, order_id, customer_id, reference):
        order = self.get_customer_order(order_id, customer_id)
        if order is None:
            return False
        if order.payment_method not in {"gcash", "bank_transfer"}:
            return False
        if order.payment_status not in {
            "awaiting-payment",
            "pending-verification",
            "demo-pending",
        }:
            return False
        order.payment_reference = reference
        order.payment_status = "pending-verification"
        return True

    def verify_payment(self, order_id):
        order = self.customer_orders.get(order_id)
        if order is None:
            return False
        if order.payment_status not in {
            "pending-verification",
            "demo-pending",
            "cod-pending",
        }:
            return False
        order.payment_status = "verified"
        return True

    def list_customer_orders(self, customer_id):
        rows = []
        for order in self.customer_orders.values():
            if order.customer_account_id != customer_id:
                continue
            rows.append(
                {
                    "id": order.id,
                    "status": order.status,
                    "payment_status": order.payment_status,
                    "created_at": order.created_at or datetime(2026, 11, 11, 10, 0),
                    "delivery_option": order.delivery_option,
                    "delivery_fee": order.delivery_fee,
                    "delivery_status": order.delivery_status,
                    "item_count": sum(item.quantity for item in order.items),
                    "total": order.total,
                }
            )
        return rows

    def get_customer_order(self, order_id, customer_id):
        order = self.customer_orders.get(order_id)
        if order and order.customer_account_id == customer_id:
            return order
        return None

    def complete_demo_payment(self, order_id, customer_id):
        order = self.get_customer_order(order_id, customer_id)
        if order is None or order.payment_status != "demo-pending":
            return False
        order.payment_status = "demo-paid"
        return True


class FakeProductRepository:
    def __init__(self):
        self.products = {}
        self.next_id = 1

    def list_products(self, available_for_sale=None):
        items = list(self.products.values())
        if available_for_sale is not None:
            items = [
                item
                for item in items
                if bool(getattr(item, "available_for_sale", True)) is available_for_sale
            ]
        return items

    def list_categories(self):
        from catalog_config import INVENTORY_CATEGORIES

        return list(INVENTORY_CATEGORIES)

    def inventory_summary(self, low_stock_threshold=5):
        items = list(self.products.values())
        return {
            "total_products": len(items),
            "total_categories": len(
                {
                    (product.category or "").strip()
                    for product in items
                    if (product.category or "").strip()
                }
            ),
            "total_stock": sum(product.stock_quantity for product in items),
            "low_stock": sum(
                1
                for product in items
                if 0 < product.stock_quantity <= low_stock_threshold
            ),
            "out_of_stock": sum(
                1 for product in items if product.stock_quantity <= 0
            ),
        }

    def get(self, product_id):
        return self.products.get(product_id)

    def create(self, product):
        product.id = self.next_id
        self.next_id += 1
        self.products[product.id] = product
        return product.id

    def update(self, product):
        self.products[product.id] = product

    def delete(self, product_id):
        del self.products[product_id]


class FakeCategoryRepository:
    def __init__(self):
        self.items = {}
        self.next_id = 1

    def list_categories(self):
        return sorted(self.items.values(), key=lambda item: (item.sort_order, item.name))

    def get(self, category_id):
        return self.items.get(category_id)

    def create(self, name, sort_order=0):
        import mysql.connector

        for item in self.items.values():
            if item.name == name:
                error = mysql.connector.IntegrityError()
                error.errno = 1062
                raise error
        category = Category(id=self.next_id, name=name, sort_order=sort_order)
        self.items[category.id] = category
        self.next_id += 1
        return category.id

    def update(self, category_id, name, sort_order):
        category = self.items[category_id]
        category.name = name
        category.sort_order = sort_order

    def delete(self, category_id):
        del self.items[category_id]


class FakeStockMovementRepository:
    def __init__(self, products_repo=None):
        self.products_repo = products_repo
        self.movements = []
        self.next_id = 1

    def list_movements(self, product_id=None, movement_type="", limit=100):
        rows = self.movements
        if product_id is not None:
            rows = [row for row in rows if row.product_id == product_id]
        if movement_type in {"in", "out", "adjustment"}:
            rows = [row for row in rows if row.movement_type == movement_type]
        return rows[:limit]

    def apply_movement(self, product_id, movement_type, quantity, note, created_by):
        from models import StockMovement

        product = self.products_repo.get(product_id)
        if product is None:
            raise InventoryConflictError("Product not found.")
        before = product.stock_quantity
        if movement_type == "in":
            after = before + quantity
            recorded = quantity
        elif movement_type == "out":
            if quantity > before:
                raise InventoryConflictError("Not enough stock for this stock out.")
            after = before - quantity
            recorded = quantity
        else:
            after = quantity
            recorded = abs(after - before)
        product.stock_quantity = after
        movement = StockMovement(
            id=self.next_id,
            product_id=product_id,
            movement_type=movement_type,
            quantity=recorded,
            quantity_before=before,
            quantity_after=after,
            note=note,
            created_by=created_by,
            created_at=datetime(2026, 11, 12, 8, 0),
            product_name=product.name,
        )
        self.next_id += 1
        self.movements.append(movement)
        return movement.id


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.previous_users = app_module.users
        self.previous_customer_accounts = app_module.customer_accounts
        self.previous_pending_registrations = app_module.pending_registrations
        self.previous_email_verification_codes = app_module.email_verification_codes
        self.previous_orders = app_module.orders
        self.previous_products = app_module.products
        self.previous_categories = app_module.categories
        self.previous_inv_products = inventory_module.products
        self.previous_inv_categories = inventory_module.categories
        self.previous_inv_stock = inventory_module.stock_movements
        self.previous_inv_users = inventory_module.users
        self.previous_registration_code = os.environ.get("STAFF_REGISTRATION_CODE")
        self.previous_cookie_secure = os.environ.get("COOKIE_SECURE")
        os.environ["STAFF_REGISTRATION_CODE"] = "test-staff-invite"
        os.environ.pop("COOKIE_SECURE", None)
        os.environ["SMTP_ENABLED"] = "0"
        app_module.app.config["SESSION_COOKIE_SECURE"] = False
        self.users = FakeUserRepository()
        self.customer_accounts = FakeCustomerAccountRepository()
        self.pending_registrations = FakePendingRegistrationRepository()
        self.email_verification_codes = FakeEmailVerificationCodeRepository()
        self.orders = FakeOrderRepository()
        self.products = FakeProductRepository()
        self.category_repo = FakeCategoryRepository()
        self.stock_repo = FakeStockMovementRepository(self.products)
        self.orders.products_repo = self.products
        app_module.users = self.users
        app_module.customer_accounts = self.customer_accounts
        app_module.pending_registrations = self.pending_registrations
        app_module.email_verification_codes = self.email_verification_codes
        app_module.orders = self.orders
        app_module.products = self.products
        app_module.categories = self.category_repo
        inventory_module.products = self.products
        inventory_module.categories = self.category_repo
        inventory_module.stock_movements = self.stock_repo
        inventory_module.users = self.users
        app_module.mail_service = FakeMailService()
        app_module.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
        )
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.users = self.previous_users
        app_module.customer_accounts = self.previous_customer_accounts
        app_module.pending_registrations = self.previous_pending_registrations
        app_module.email_verification_codes = self.previous_email_verification_codes
        app_module.orders = self.previous_orders
        app_module.products = self.previous_products
        app_module.categories = self.previous_categories
        inventory_module.products = self.previous_inv_products
        inventory_module.categories = self.previous_inv_categories
        inventory_module.stock_movements = self.previous_inv_stock
        inventory_module.users = self.previous_inv_users
        if self.previous_registration_code is None:
            os.environ.pop("STAFF_REGISTRATION_CODE", None)
        else:
            os.environ["STAFF_REGISTRATION_CODE"] = self.previous_registration_code
        if self.previous_cookie_secure is None:
            os.environ.pop("COOKIE_SECURE", None)
        else:
            os.environ["COOKIE_SECURE"] = self.previous_cookie_secure
        app_module.app.config["SESSION_COOKIE_SECURE"] = (
            os.environ.get("COOKIE_SECURE") == "1"
        )
        app_module.app.config.update(
            TESTING=False,
            WTF_CSRF_ENABLED=True,
        )

    def test_workspace_redirects_anonymous_users(self):
        response = self.client.get("/orders")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

    def test_inventory_redirects_anonymous_users(self):
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

    def test_public_pages_render_csrf_protected_forms(self):
        home = self.client.get("/")
        login = self.client.get("/login")
        register = self.client.get("/register")
        customer_login = self.client.get("/customer/login")
        customer_register = self.client.get("/customer/register")
        self.assertEqual(home.status_code, 200)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(register.status_code, 200)
        self.assertEqual(customer_login.status_code, 200)
        self.assertEqual(customer_register.status_code, 200)
        self.assertIn(b'images/jc-aqua-logo.jpg', home.data)
        self.assertIn(b"jc-aqua-logo.jpg", home.data)
        self.assertIn(b'rel="icon"', home.data)
        self.assertIn(b"JC Aqua Fish Shop", home.data)
        self.assertIn(b"Fish Inventory Management System", home.data)
        self.assertIn(b">Login<", home.data)
        self.assertIn(b">Register<", home.data)
        home_content = home.data.split(b"</header>", 1)[-1]
        self.assertIn(b"Browse products", home_content)
        self.assertIn(b"Register", home_content)
        self.assertIn(b"Staff workspace", home_content)
        self.assertIn(b"Login", home_content)
        self.assertEqual(home_content.count(b"home-account-card"), 1)
        self.assertIn(b'images/jc-aqua-logo.jpg', login.data)
        self.assertIn(b'images/jc-aqua-logo.jpg', register.data)
        self.assertIn(b'images/jc-aqua-logo.jpg', customer_login.data)
        self.assertIn(b'images/jc-aqua-logo.jpg', customer_register.data)
        self.assertIn(b'alt="JC Aqua Fish Shop"', login.data)
        self.assertIn(b'data-history-back', login.data)
        self.assertIn(b'data-history-back', register.data)
        self.assertIn(b'name="csrf_token"', login.data)
        self.assertIn(b'name="csrf_token"', register.data)
        self.assertIn(b'name="csrf_token"', customer_login.data)
        self.assertIn(b'name="csrf_token"', customer_register.data)
        self.assertIn(b"staff account for the shop order system", register.data)
        self.assertIn(b'name="registration_code"', register.data)

    def test_catalog_and_customer_footer_use_light_page_branding(self):
        catalog = self.client.get("/catalog")
        self.assertEqual(catalog.status_code, 200)
        self.assertIn(b'class="site-footer"', catalog.data)
        self.assertIn(b"JC Aqua Fish Shop", catalog.data)
        self.assertIn(b'alt="JC Aqua Fish Shop"', catalog.data)

        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        with self.client.session_transaction() as session:
            session.clear()
            session["customer_id"] = account.id
        dashboard = self.client.get("/customer/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'class="site-footer"', dashboard.data)
        self.assertIn(b"JC Aqua Fish Shop", dashboard.data)

    def test_public_catalog_has_back_navigation(self):
        response = self.client.get("/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-history-back', response.data)

    def test_catalog_shows_flash_messages(self):
        with self.client.session_transaction() as session:
            session["_flashes"] = [("success", "Goldfish added to your cart.")]
        response = self.client.get("/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"flash-list", response.data)
        self.assertIn(b"Goldfish added to your cart.", response.data)

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/register",
            data={
                "full_name": "Aqua Staff",
                "email": "staff@example.com",
                "password": "LongPass123",
                "confirm_password": "different-password",
                "registration_code": "test-staff-invite",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"passwords do not match", response.data)
        self.assertEqual(self.users.users_by_email, {})

    def test_register_hashes_password(self):
        response = self.client.post(
            "/register",
            data={
                "full_name": "Aqua Staff",
                "email": "staff@example.com",
                "password": "LongPass123",
                "confirm_password": "LongPass123",
                "registration_code": "test-staff-invite",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/verify")
        user = self.users.get_by_email("staff@example.com")
        self.assertIsNotNone(user)
        self.assertFalse(user.email_verified)
        self.assertNotEqual(user.password_hash, "LongPass123")
        self.assertTrue(user.verify_password("LongPass123"))

    def test_registration_allows_multiple_accounts(self):
        first_response = self.client.post(
            "/register",
            data={
                "full_name": "First Staff",
                "email": "first@example.com",
                "password": "LongPass123",
                "confirm_password": "LongPass123",
                "registration_code": "test-staff-invite",
            },
        )
        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(first_response.headers["Location"], "/verify")

        page = self.client.get("/register")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="full_name"', page.data)
        self.assertIn(b'name="password"', page.data)
        self.assertIn(b'name="registration_code"', page.data)

        second_response = self.client.post(
            "/register",
            data={
                "full_name": "Second Staff",
                "email": "second@example.com",
                "password": "LongPass456",
                "confirm_password": "LongPass456",
                "registration_code": "test-staff-invite",
            },
        )
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(len(self.users.users_by_id), 2)

    def test_staff_registration_blocked_when_code_unset(self):
        os.environ.pop("STAFF_REGISTRATION_CODE", None)

        page = self.client.get("/register")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="registration_code"', page.data)

        rejected = self.client.post(
            "/register",
            data={
                "full_name": "Aqua Staff",
                "email": "staff@example.com",
                "password": "LongPass123",
                "confirm_password": "LongPass123",
                "registration_code": "any-code",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertIn(b"Staff registration is unavailable", rejected.data)
        self.assertEqual(self.users.users_by_email, {})

    def test_staff_registration_requires_valid_code(self):
        os.environ["STAFF_REGISTRATION_CODE"] = "shop-invite-77"

        page = self.client.get("/register")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="registration_code"', page.data)

        rejected = self.client.post(
            "/register",
            data={
                "full_name": "Aqua Staff",
                "email": "staff@example.com",
                "password": "LongPass123",
                "confirm_password": "LongPass123",
                "registration_code": "wrong-code",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertIn(b"valid staff registration code", rejected.data)
        self.assertEqual(self.users.users_by_email, {})

        accepted = self.client.post(
            "/register",
            data={
                "full_name": "Aqua Staff",
                "email": "staff@example.com",
                "password": "LongPass123",
                "confirm_password": "LongPass123",
                "registration_code": "shop-invite-77",
            },
        )
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(accepted.headers["Location"], "/verify")
        self.assertIsNotNone(self.users.get_by_email("staff@example.com"))

    def test_security_headers_are_set(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(
            response.headers["Referrer-Policy"], "strict-origin-when-cross-origin"
        )
        self.assertIn("camera=()", response.headers["Permissions-Policy"])
        csp = response.headers["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("https://www.gstatic.com", csp)
        self.assertNotIn("Strict-Transport-Security", response.headers)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

        login = self.client.get("/customer/login")
        self.assertIn("no-store", login.headers.get("Cache-Control", ""))

    def test_firebase_auth_endpoint_disabled_without_config(self):
        response = self.client.post(
            "/customer/auth/firebase",
            json={"idToken": "fake-token"},
            headers={"X-CSRFToken": "ignored-when-csrf-off"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"not configured", response.data)

    def test_hsts_header_only_when_secure_cookies_enabled(self):
        app_module.app.config["SESSION_COOKIE_SECURE"] = True
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains",
        )

    def test_login_rejects_oversized_password(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        self.users.create_account(user)
        response = self.client.post(
            "/login",
            data={"email": user.email, "password": "x" * 129},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Email or password is incorrect", response.data)

    def test_login_and_logout_manage_session(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        response = self.client.post(
            "/login",
            data={"email": user.email, "password": "LongPass123"},
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], user.id)

        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_login_rejects_invalid_password(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        self.users.create_account(user)
        response = self.client.post(
            "/login",
            data={"email": user.email, "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Email or password is incorrect", response.data)

    def test_create_order_persists_multiple_validated_items(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/orders/new",
            data={
                "customer_name": "Aqua Customer",
                "customer_contact": "09171234567",
                "delivery_address": "Sta. Cruz, Laguna",
                "status": "pending",
                "item_name": ["Goldfish", "Fish food"],
                "quantity": ["2", "1"],
                "unit_price": ["25.00", "80.50"],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/orders/5")
        order, user_id = self.orders.created[0]
        self.assertEqual(user_id, user.id)
        self.assertEqual(len(order.items), 2)
        self.assertEqual(order.total, Decimal("130.50"))

    def test_create_order_rejects_negative_price(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/orders/new",
            data={
                "customer_name": "Aqua Customer",
                "customer_contact": "09171234567",
                "delivery_address": "Sta. Cruz, Laguna",
                "status": "pending",
                "item_name": ["Goldfish"],
                "quantity": ["1"],
                "unit_price": ["-5.00"],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"valid amounts", response.data)
        self.assertEqual(self.orders.created, [])

    def test_create_product_validates_and_saves_inventory(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/products/new",
            data={
                "name": "Fancy Goldfish",
                "category": "Aquarium",
                "unit": "pieces",
                "available_for_sale": "1",
                "unit_price": "125.50",
                "stock_quantity": "8",
            },
        )
        self.assertEqual(response.status_code, 302)
        product = self.products.get(1)
        self.assertEqual(product.name, "Fancy Goldfish")
        self.assertEqual(product.category, "Aquarium")
        self.assertEqual(product.unit, "pieces")
        self.assertTrue(product.available_for_sale)
        self.assertEqual(product.unit_price, Decimal("125.50"))
        self.assertEqual(product.stock_quantity, 8)

    def test_create_product_rejects_invalid_values(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/products/new",
            data={
                "name": "Goldfish",
                "category": "Aquarium",
                "unit": "pieces",
                "unit_price": "-1.00",
                "stock_quantity": "-2",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Price must be a valid amount", response.data)
        self.assertEqual(self.products.products, {})

    def test_product_edit_and_delete(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        self.products.create(
            Product(
                id=0,
                name="Goldfish",
                category="Aquarium",
                unit_price=Decimal("25.00"),
                stock_quantity=4,
            )
        )
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/products/1/edit",
            data={
                "name": "Fancy Goldfish",
                "category": "Aquarium Accessories",
                "unit": "boxes",
                "available_for_sale": "1",
                "unit_price": "30.00",
                "stock_quantity": "3",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.products.get(1).name, "Fancy Goldfish")
        response = self.client.post("/products/1/delete")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.products.get(1))

    def test_inventory_page_shows_product_and_active_navigation(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        self.products.create(
            Product(
                id=0,
                name="Betta fish",
                category="Fish",
                unit_price=Decimal("75.00"),
                stock_quantity=3,
            )
        )
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        redirect = self.client.get("/products")
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect.headers["Location"], "/inventory")

        response = self.client.get("/inventory")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Betta fish", response.data)
        self.assertIn(b"LOW STOCK", response.data)
        self.assertIn(b'aria-current="page">Inventory</a>', response.data)
        self.assertNotIn(b">Categories</a>", response.data)
        self.assertNotIn(b">Stock in</a>", response.data)
        self.assertNotIn(b">Stock out</a>", response.data)
        self.assertIn(b">Stock history</a>", response.data)
        self.assertIn(b">Customer orders</a>", response.data)
        self.assertIn(b"nav-role-tag", response.data)

    def test_stock_in_updates_quantity_and_history(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        product_id = self.products.create(
            Product(
                id=0,
                name="Betta fish",
                category="Fish",
                unit_price=Decimal("75.00"),
                stock_quantity=3,
            )
        )
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/stock/in",
            data={
                "product_id": str(product_id),
                "quantity": "5",
                "note": "Delivery",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.products.get(product_id).stock_quantity, 8)
        self.assertEqual(len(self.stock_repo.movements), 1)
        self.assertEqual(self.stock_repo.movements[0].movement_type, "in")

        history = self.client.get("/stock/history")
        self.assertEqual(history.status_code, 200)
        self.assertIn(b"Betta fish", history.data)
        self.assertIn(b"Delivery", history.data)

    def test_stock_out_rejects_oversell(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        product_id = self.products.create(
            Product(
                id=0,
                name="Betta fish",
                category="Fish",
                unit_price=Decimal("75.00"),
                stock_quantity=2,
            )
        )
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        response = self.client.post(
            "/stock/out",
            data={
                "product_id": str(product_id),
                "quantity": "5",
                "note": "Too many",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.products.get(product_id).stock_quantity, 2)
        self.assertIn(b"Not enough stock", response.data)

    def test_public_catalog_shows_products_without_staff_login(self):
        self.products.create(
            Product(
                id=0,
                name="Betta fish",
                category="Fish",
                unit_price=Decimal("75.00"),
                stock_quantity=3,
            )
        )

        response = self.client.get("/catalog")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Betta fish", response.data)
        self.assertIn(b"Fish", response.data)
        self.assertIn(b"75.00", response.data)
        self.assertIn(b"In stock: 3", response.data)

    def test_public_catalog_shows_empty_state_when_no_products(self):
        response = self.client.get("/catalog")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No products available yet", response.data)

    def test_customer_registration_hashes_password_and_keeps_account_separate(self):
        response = self.client.post(
            "/customer/register",
            data={
                "full_name": "Aqua Customer",
                "email": "customer@example.com",
                "password": "CustomerPass1",
                "confirm_password": "CustomerPass1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/customer/verify")
        # Permanent account is created only after OTP verification.
        self.assertIsNone(self.customer_accounts.get_by_email("customer@example.com"))
        pending = self.pending_registrations.get_by_email("customer@example.com")
        self.assertIsNotNone(pending)
        self.assertNotEqual(pending.password_hash, "CustomerPass1")
        self.assertTrue(check_password_hash(pending.password_hash, "CustomerPass1"))
        self.assertEqual(self.users.users_by_email, {})

    def test_customer_must_verify_email_before_login(self):
        previous_generate = app_module.generate_verification_code
        app_module.generate_verification_code = lambda: "123456"
        try:
            register = self.client.post(
                "/customer/register",
                data={
                    "full_name": "Aqua Customer",
                    "email": "customer@example.com",
                    "password": "CustomerPass1",
                    "confirm_password": "CustomerPass1",
                },
            )
            self.assertEqual(register.headers["Location"], "/customer/verify")
            self.assertIsNone(self.customer_accounts.get_by_email("customer@example.com"))

            blocked = self.client.post(
                "/customer/login",
                data={
                    "email": "customer@example.com",
                    "password": "CustomerPass1",
                },
            )
            self.assertEqual(blocked.status_code, 200)
            self.assertIn(b"Email or password is incorrect", blocked.data)

            verified = self.client.post(
                "/customer/verify",
                data={
                    "email": "customer@example.com",
                    "verification_code": "123456",
                    "action": "verify",
                },
            )
            self.assertEqual(verified.status_code, 302)
            self.assertEqual(verified.headers["Location"], "/customer/login")
            account = self.customer_accounts.get_by_email("customer@example.com")
            self.assertIsNotNone(account)
            self.assertTrue(account.email_verified)
            self.assertFalse(account.first_login_verified)
            self.assertIsNone(self.pending_registrations.get_by_email("customer@example.com"))

            first_login = self.client.post(
                "/customer/login",
                data={
                    "email": "customer@example.com",
                    "password": "CustomerPass1",
                },
            )
            self.assertEqual(first_login.headers["Location"], "/customer/first-login-verify")
            with self.client.session_transaction() as session_data:
                self.assertNotIn("customer_id", session_data)

            completed = self.client.post(
                "/customer/first-login-verify",
                data={
                    "email": "customer@example.com",
                    "verification_code": "123456",
                    "action": "verify",
                },
            )
            self.assertEqual(completed.headers["Location"], "/customer/dashboard")
            account = self.customer_accounts.get_by_email("customer@example.com")
            self.assertTrue(account.first_login_verified)
            with self.client.session_transaction() as session_data:
                self.assertEqual(session_data.get("customer_id"), account.id)

            # Subsequent logins skip first-login OTP.
            self.client.post("/customer/logout")
            again = self.client.post(
                "/customer/login",
                data={
                    "email": "customer@example.com",
                    "password": "CustomerPass1",
                },
            )
            self.assertEqual(again.headers["Location"], "/customer/dashboard")
        finally:
            app_module.generate_verification_code = previous_generate

    def test_customer_verification_limits_wrong_attempts_and_resend_cooldown(self):
        previous_generate = app_module.generate_verification_code
        app_module.generate_verification_code = lambda: "654321"
        try:
            self.client.post(
                "/customer/register",
                data={
                    "full_name": "Aqua Customer",
                    "email": "customer@example.com",
                    "password": "CustomerPass1",
                    "confirm_password": "CustomerPass1",
                },
            )
            pending = self.pending_registrations.get_by_email("customer@example.com")
            self.assertIsNotNone(pending)
            self.assertIsNone(self.customer_accounts.get_by_email("customer@example.com"))

            blocked_resend = self.client.post(
                "/customer/verify",
                data={
                    "email": "customer@example.com",
                    "action": "resend",
                },
                follow_redirects=True,
            )
            self.assertIn(b"Please wait", blocked_resend.data)

            for _ in range(app_module.VERIFICATION_MAX_ATTEMPTS):
                self.client.post(
                    "/customer/verify",
                    data={
                        "email": "customer@example.com",
                        "verification_code": "000000",
                        "action": "verify",
                    },
                )
            locked = self.client.post(
                "/customer/verify",
                data={
                    "email": "customer@example.com",
                    "verification_code": "654321",
                    "action": "verify",
                },
                follow_redirects=True,
            )
            self.assertIn(b"Too many incorrect attempts", locked.data)
            self.assertIsNone(self.customer_accounts.get_by_email("customer@example.com"))

            pending = self.pending_registrations.get_by_email("customer@example.com")
            pending.last_sent_at = None
            resent = self.client.post(
                "/customer/verify",
                data={
                    "email": "customer@example.com",
                    "action": "resend",
                },
                follow_redirects=True,
            )
            self.assertIn(b"verification code", resent.data.lower())
            pending = self.pending_registrations.get_by_email("customer@example.com")
            self.assertEqual(pending.attempts, 0)
        finally:
            app_module.generate_verification_code = previous_generate

    def test_customer_login_uses_customer_session_only(self):
        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        with self.client.session_transaction() as session:
            session["user_id"] = 99

        response = self.client.post(
            "/customer/login",
            data={
                "email": account.email,
                "password": "CustomerPass1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/customer/dashboard")
        with self.client.session_transaction() as session:
            self.assertEqual(session["customer_id"], account.id)
            self.assertNotIn("user_id", session)

    def test_customer_dashboard_and_profile_update(self):
        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        self.products.create(
            Product(
                id=0,
                name="Tilapia",
                category="Fish Food",
                unit_price=Decimal("180.00"),
                stock_quantity=25,
                unit="kilograms",
                available_for_sale=True,
            )
        )
        self.products.create(
            Product(
                id=0,
                name="Salmon",
                category="Aquarium",
                unit_price=Decimal("450.00"),
                stock_quantity=0,
                unit="kilograms",
                available_for_sale=True,
            )
        )
        self.products.create(
            Product(
                id=0,
                name="Hidden Staff Item",
                category="Aquarium Accessories",
                unit_price=Decimal("10.00"),
                stock_quantity=5,
                available_for_sale=False,
            )
        )
        with self.client.session_transaction() as session:
            session["customer_id"] = account.id

        dashboard = self.client.get("/customer/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Welcome, Aqua Customer!", dashboard.data)
        self.assertIn(b"Browse products", dashboard.data)
        self.assertIn(b">Shop<", dashboard.data)
        self.assertIn(b">Cart<", dashboard.data)
        self.assertNotIn(b"Fish stocks", dashboard.data)
        self.assertNotIn(b"Inventory History", dashboard.data)
        self.assertNotIn(b"Riders", dashboard.data)
        self.assertIn(b"Tilapia", dashboard.data)
        self.assertIn(b"180.00/kilograms", dashboard.data)
        self.assertIn(b"25 kilograms", dashboard.data)
        self.assertIn(b"Available", dashboard.data)
        self.assertIn(b"Salmon", dashboard.data)
        self.assertIn(b"Sold out", dashboard.data)
        self.assertIn(b"Fish Food", dashboard.data)
        self.assertIn(b"Aquarium Accessories", dashboard.data)
        self.assertNotIn(b"Hidden Staff Item", dashboard.data)
        self.assertNotIn(b"Add to cart", dashboard.data)
        self.assertNotIn(b"Add product", dashboard.data)

        filtered = self.client.get(
            "/customer/dashboard?category=Fish%20Food&status=available"
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"Tilapia", filtered.data)
        self.assertNotIn(b"Salmon", filtered.data)

        out_only = self.client.get("/customer/dashboard?status=out")
        self.assertEqual(out_only.status_code, 200)
        self.assertIn(b"Salmon", out_only.data)
        self.assertNotIn(b"Tilapia", out_only.data)

        searched = self.client.get("/customer/dashboard?q=tila")
        self.assertEqual(searched.status_code, 200)
        self.assertIn(b"Tilapia", searched.data)
        self.assertNotIn(b"Salmon", searched.data)

        staff_dashboard = self.client.get("/dashboard")
        self.assertEqual(staff_dashboard.status_code, 302)
        self.assertEqual(staff_dashboard.headers["Location"], "/customer/dashboard")

        profile_page = self.client.get("/customer/profile")
        self.assertEqual(profile_page.status_code, 200)
        self.assertIn(b'name="full_name"', profile_page.data)

        updated = self.client.post(
            "/customer/profile",
            data={
                "full_name": "Updated Customer",
                "email": "updated-customer@example.com",
                "current_password": "CustomerPass1",
                "new_password": "CustomerPass2",
                "confirm_password": "CustomerPass2",
            },
        )
        self.assertEqual(updated.status_code, 302)
        refreshed = self.customer_accounts.get_by_id(account.id)
        self.assertEqual(refreshed.full_name, "Updated Customer")
        self.assertEqual(refreshed.email, "updated-customer@example.com")
        self.assertTrue(refreshed.verify_password("CustomerPass2"))

    def test_staff_profile_update(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        page = self.client.get("/profile")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Your profile", page.data)

        response = self.client.post(
            "/profile",
            data={
                "full_name": "Updated Staff",
                "email": "updated-staff@example.com",
                "current_password": "LongPass123",
                "new_password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        refreshed = self.users.get_by_id(user.id)
        self.assertEqual(refreshed.full_name, "Updated Staff")
        self.assertEqual(refreshed.email, "updated-staff@example.com")
        self.assertTrue(refreshed.verify_password("LongPass123"))

    def test_customer_catalog_adds_product_and_renders_cart_page(self):
        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        product = Product(
            id=0,
            name="Betta fish",
            category="Fish",
            unit_price=Decimal("75.00"),
            stock_quantity=3,
        )
        self.products.create(product)
        with self.client.session_transaction() as session:
            session["customer_id"] = account.id

        catalog = self.client.get("/catalog")
        self.assertIn(b"Add to cart", catalog.data)
        response = self.client.post(
            f"/customer/cart/add/{product.id}", data={"quantity": "2"}
        )
        self.assertEqual(response.status_code, 302)
        cart_page = self.client.get("/customer/cart")
        self.assertEqual(cart_page.status_code, 200)
        self.assertIn(b"Betta fish", cart_page.data)
        self.assertIn(b"150.00", cart_page.data)

    def test_customer_product_detail_and_add_to_order(self):
        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        product_id = self.products.create(
            Product(
                id=0,
                name="Tilapia",
                category="Fish Food",
                unit_price=Decimal("180.00"),
                stock_quantity=25,
                unit="kilograms",
                available_for_sale=True,
                description="Fresh tilapia sold per kilogram.",
            )
        )
        with self.client.session_transaction() as session:
            session["customer_id"] = account.id

        dashboard = self.client.get("/customer/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(f"/customer/products/{product_id}".encode(), dashboard.data)

        detail = self.client.get(f"/customer/products/{product_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Tilapia", detail.data)
        self.assertIn(b"Fresh tilapia sold per kilogram.", detail.data)
        self.assertIn(b"Add to Order", detail.data)
        self.assertIn(b'name="quantity"', detail.data)

        added = self.client.post(
            f"/customer/cart/add/{product_id}",
            data={"quantity": "3"},
        )
        self.assertEqual(added.status_code, 302)
        self.assertEqual(added.headers["Location"], "/customer/cart")
        cart = self.client.get("/customer/cart")
        self.assertIn(b"Tilapia", cart.data)
        self.assertIn(b"540.00", cart.data)

    def test_customer_checkout_creates_order_and_demo_payment_is_explicit(self):
        account = verified_customer(
            "Aqua Customer", "customer@example.com", "CustomerPass1"
        )
        account.id = self.customer_accounts.create_account(account)
        product = Product(
            id=0,
            name="Betta fish",
            category="Fish",
            unit_price=Decimal("75.00"),
            stock_quantity=3,
        )
        self.products.create(product)
        with self.client.session_transaction() as session:
            session["customer_id"] = account.id
            session["customer_cart"] = {str(product.id): 2}

        checkout = self.client.get("/customer/checkout")
        self.assertEqual(checkout.status_code, 200)
        self.assertIn(b"Payment verification workflow", checkout.data)
        self.assertIn(b"GCash", checkout.data)
        self.assertIn(b">Address<", checkout.data)
        self.assertIn(b">Name<", checkout.data)
        self.assertIn(b">Number<", checkout.data)
        response = self.client.post(
            "/customer/checkout",
            data={
                "customer_name": account.full_name,
                "customer_contact": "09171234567",
                "delivery_address": "Sta. Cruz, Laguna",
                "delivery_option": "delivery",
                "payment_method": "gcash",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "/customer/orders/6/payment"
        )
        self.assertEqual(len(self.orders.customer_created), 1)
        order, customer_id, cart = self.orders.customer_created[0]
        self.assertEqual(customer_id, account.id)
        self.assertEqual(cart, {product.id: 2})
        self.assertTrue(order.stock_reserved)
        self.assertEqual(order.payment_method, "gcash")
        self.assertEqual(order.payment_status, "awaiting-payment")
        detail = self.client.get("/customer/orders/6")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"staff verification", detail.data)
        payment = self.client.get("/customer/orders/6/payment")
        self.assertEqual(payment.status_code, 200)
        self.assertIn(b"Transaction reference", payment.data)
        submitted = self.client.post(
            "/customer/orders/6/payment",
            data={"payment_reference": "GCASH12345"},
        )
        self.assertEqual(submitted.status_code, 302)
        self.assertEqual(order.payment_status, "pending-verification")
        self.assertEqual(order.payment_reference, "GCASH12345")

    def test_customer_cannot_view_another_customer_order(self):
        first = verified_customer(
            "First Customer", "first@example.com", "CustomerPass1"
        )
        first.id = self.customer_accounts.create_account(first)
        second = verified_customer(
            "Second Customer", "second@example.com", "CustomerPass2"
        )
        second.id = self.customer_accounts.create_account(second)
        order = CustomerOrder(
            id=6,
            customer_name=first.full_name,
            customer_contact="09171234567",
            delivery_address="Sta. Cruz, Laguna",
            status="pending",
            customer_account_id=first.id,
            payment_status="demo-pending",
            stock_reserved=True,
        )
        self.orders.customer_orders[order.id] = order
        with self.client.session_transaction() as session:
            session["customer_id"] = second.id

        response = self.client.get("/customer/orders/6")

        self.assertEqual(response.status_code, 404)

    def test_staff_workspace_pages_render(self):
        user = verified_user("Aqua Staff", "staff@example.com", "LongPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

        for path in (
            "/dashboard",
            "/profile",
            "/orders",
            "/orders/new",
            "/orders/5",
            "/orders/5/edit",
            "/inventory",
            "/products/new",
            "/stock/in",
            "/stock/history",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                if path == "/dashboard":
                    self.assertIn(b'class="site-page dashboard-page"', response.data)
                    self.assertIn(b"Order dashboard", response.data)
                    self.assertNotIn(b"dashboard-brand-banner", response.data)
                    self.assertIn(b'data-history-back', response.data)
                    self.assertIn(b'images/jc-aqua-logo.jpg', response.data)
                    self.assertIn(b'class="site-nav-brand"', response.data)
                if path == "/profile":
                    self.assertIn(b"Your profile", response.data)

        categories_redirect = self.client.get("/categories")
        self.assertEqual(categories_redirect.status_code, 302)
        self.assertEqual(categories_redirect.headers["Location"], "/inventory")
        inventory_page = self.client.get("/inventory")
        self.assertEqual(inventory_page.status_code, 200)
        self.assertIn(b"Fish Food", inventory_page.data)
        self.assertIn(b"Aquarium Accessories", inventory_page.data)
        self.assertNotIn(b"Manage categories", inventory_page.data)

    def test_post_without_csrf_token_is_rejected(self):
        app_module.app.config["WTF_CSRF_ENABLED"] = True
        response = self.client.post("/login", data={"email": "a@b.com", "password": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"could not be verified", response.data)

    def test_dashboard_includes_inventory_shortcuts(self):
        user = verified_user("Staff", "staff-dash@example.com", "StaffPass123")
        user.id = self.users.create_account(user)
        with self.client.session_transaction() as session:
            session["user_id"] = user.id
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inventory", response.data)
        self.assertIn(b"Stock history", response.data)
        self.assertIn(b'rel="icon"', response.data)


class ModelBehaviorTests(unittest.TestCase):
    def test_product_stock_helpers(self):
        product = Product(
            id=1,
            name="Fish Food",
            category="Fish Food",
            unit_price=Decimal("50.00"),
            stock_quantity=4,
            available_for_sale=True,
        )
        self.assertTrue(product.is_in_stock())
        self.assertTrue(product.is_low_stock())
        self.assertEqual(product.stock_status(), "low-stock")
        self.assertTrue(product.can_sell(2))
        self.assertFalse(product.can_sell(10))
        product.apply_stock_change(-1)
        self.assertEqual(product.stock_quantity, 3)

    def test_customer_order_totals_and_flags(self):
        order = CustomerOrder(
            id=1,
            customer_name="Buyer",
            customer_contact="buyer@example.com",
            delivery_address="Sta. Cruz, Laguna",
            status="pending",
            items=[
                OrderItem("Pellets", 2, Decimal("25.00"), product_id=1),
            ],
            delivery_option="delivery",
            delivery_fee=Decimal("40.00"),
            payment_status="submitted",
        )
        self.assertEqual(order.items_subtotal, Decimal("50.00"))
        self.assertEqual(order.total, Decimal("90.00"))
        self.assertEqual(order.item_count(), 2)
        self.assertTrue(order.is_delivery())
        self.assertTrue(order.awaits_payment_verification())


if __name__ == "__main__":
    unittest.main()
