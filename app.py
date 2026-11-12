import itertools
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path

import mysql.connector
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from firebase_auth import (
    firebase_enabled,
    firebase_web_config,
    verify_firebase_id_token,
)
from mail import MailService
from models import (
    DELIVERY_OPTIONS,
    LOCAL_DELIVERY_AREA_KEYWORDS,
    ORDER_STATUSES,
    CustomerAccount,
    CustomerOrder,
    OrderItem,
    Product,
    Rider,
    User,
)
from catalog_config import (
    CATEGORY_EXAMPLES,
    DEFAULT_PRODUCT_UNIT,
    INVENTORY_CATEGORIES,
    PRODUCT_UNITS,
)
from repositories import (
    CategoryRepository,
    CustomerAccountRepository,
    InventoryConflictError,
    OrderRepository,
    ProductRepository,
    RiderRepository,
    ShopSettingsRepository,
    StockMovementRepository,
    UserRepository,
)


app = Flask(__name__)
PRODUCT_UPLOAD_DIR = Path(app.root_path) / "static" / "uploads" / "products"
PAYMENT_UPLOAD_DIR = Path(app.root_path) / "static" / "uploads" / "payments"
PRODUCT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LOW_STOCK_THRESHOLD = 5
GCASH_NUMBER_PATTERN = re.compile(r"^[0-9+() .-]{7,40}$")
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY"),
    # Local HTTP: leave COOKIE_SECURE unset/0. HTTPS production: set COOKIE_SECURE=1.
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    WTF_CSRF_TIME_LIMIT=3600,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "Set FLASK_SECRET_KEY before starting the app. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

csrf = CSRFProtect(app)
users = UserRepository()
customer_accounts = CustomerAccountRepository()
orders = OrderRepository()
products = ProductRepository()
categories = CategoryRepository()
stock_movements = StockMovementRepository()
riders = RiderRepository()
shop_settings = ShopSettingsRepository()
mail_service = MailService()
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^[0-9+() .-]{7,40}$")
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
VERIFICATION_CODE_TTL_MINUTES = 5
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5
PAYMENT_METHODS = {"gcash", "bank_transfer", "cod"}
PAYMENT_METHOD_LABELS = {
    "gcash": "GCash",
    "bank_transfer": "Bank Transfer",
    "cod": "Cash on Delivery",
}


def staff_registration_code() -> str:
    return os.environ.get("STAFF_REGISTRATION_CODE", "").strip()


def staff_registration_is_configured() -> bool:
    return bool(staff_registration_code())


def staff_registration_code_is_valid(submitted_code: str) -> bool:
    expected = staff_registration_code()
    if not expected:
        return False
    return secrets.compare_digest(submitted_code.strip(), expected)


def password_length_is_valid(password: str) -> bool:
    return PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https://*.googleusercontent.com; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self' https://www.gstatic.com; "
        "connect-src 'self' https://identitytoolkit.googleapis.com "
        "https://securetoken.googleapis.com https://www.googleapis.com "
        "https://firebaseinstallations.googleapis.com; "
        "frame-src https://accounts.google.com https://*.firebaseapp.com; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'"
    )
    # HSTS only when Secure cookies are enabled (HTTPS deployments).
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.context_processor
def workspace_navigation():
    endpoint = request.endpoint or ""
    if endpoint in {"dashboard", "profile"}:
        active_page = "dashboard"
    elif endpoint in {"product_list", "new_product", "edit_product", "delete_product"}:
        active_page = "products"
    elif endpoint in {"rider_list", "new_rider", "edit_rider", "delete_rider"}:
        active_page = "riders"
    else:
        active_page = "orders"
    return {
        "active_page": active_page,
        "firebase_enabled": firebase_enabled(),
        "firebase_config": firebase_web_config() if firebase_enabled() else None,
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        user_id = session.get("user_id")
        if not isinstance(user_id, int):
            if isinstance(session.get("customer_id"), int):
                flash("Staff workspace is for shop staff only.", "info")
                return redirect(url_for("customer_dashboard"))
            session.clear()
            flash("Please sign in to access the order workspace.", "info")
            return redirect(url_for("login"))

        g.current_user = users.get_by_id(user_id)
        if g.current_user is None:
            session.clear()
            flash("Your session has expired. Please sign in again.", "info")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def customer_login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        customer_id = session.get("customer_id")
        if not isinstance(customer_id, int):
            if isinstance(session.get("user_id"), int):
                flash("Customer pages require a customer account.", "info")
                return redirect(url_for("dashboard"))
            flash("Please sign in with your customer account to continue.", "info")
            return redirect(url_for("customer_login"))

        g.current_customer = customer_accounts.get_by_id(customer_id)
        if g.current_customer is None:
            session.pop("customer_id", None)
            flash("Your customer session has expired. Please sign in again.", "info")
            return redirect(url_for("customer_login"))
        return view(**kwargs)

    return wrapped_view


def customer_cart() -> dict[int, int]:
    raw_cart = session.get("customer_cart", {})
    if not isinstance(raw_cart, dict):
        return {}
    cart = {}
    for product_id, quantity in raw_cart.items():
        try:
            parsed_id = int(product_id)
            parsed_quantity = int(quantity)
        except (TypeError, ValueError):
            continue
        if parsed_id > 0 and 1 <= parsed_quantity <= 100:
            cart[parsed_id] = parsed_quantity
    return cart


def list_available_riders() -> list:
    try:
        return riders.list_riders()
    except mysql.connector.Error:
        return []


def parse_order_form() -> tuple[CustomerOrder | None, str | None]:
    customer_name = request.form.get("customer_name", "").strip()
    customer_contact = request.form.get("customer_contact", "").strip()
    delivery_address = request.form.get("delivery_address", "").strip()
    status = request.form.get("status", "pending").strip()

    if not 2 <= len(customer_name) <= 120:
        return None, "Enter a customer name between 2 and 120 characters."
    if not PHONE_PATTERN.fullmatch(customer_contact):
        return None, "Enter a valid contact number between 7 and 40 characters."
    if not 5 <= len(delivery_address) <= 500:
        return None, "Enter a delivery address between 5 and 500 characters."
    if status not in ORDER_STATUSES:
        return None, "Choose a valid order status."

    names = request.form.getlist("item_name")
    quantities = request.form.getlist("quantity")
    unit_prices = request.form.getlist("unit_price")
    if not names or len(names) != len(quantities) or len(names) != len(unit_prices):
        return None, "Add at least one complete order item."
    if len(names) > 50:
        return None, "An order can contain no more than 50 items."

    items = []
    for name, quantity_value, price_value in zip(names, quantities, unit_prices):
        name = name.strip()
        if not 1 <= len(name) <= 160:
            return None, "Each item name must be between 1 and 160 characters."
        try:
            quantity = int(quantity_value)
            unit_price = Decimal(price_value)
            if not unit_price.is_finite():
                return None, "Enter a valid item price."
            rounded_price = unit_price.quantize(Decimal("0.01"))
        except (ValueError, InvalidOperation):
            return None, "Enter a whole-number quantity and a valid item price."
        if quantity < 1 or quantity > 100000:
            return None, "Item quantities must be between 1 and 100,000."
        if (
            not unit_price.is_finite()
            or unit_price < 0
            or unit_price > Decimal("99999999.99")
            or unit_price != rounded_price
        ):
            return None, "Item prices must be valid amounts with up to two decimal places."
        items.append(
            OrderItem(
                product_name=name,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    return (
        CustomerOrder(
            id=0,
            customer_name=customer_name,
            customer_contact=customer_contact,
            delivery_address=delivery_address,
            status=status,
            items=items,
        ),
        None,
    )


def order_form_values(order=None, form=None) -> dict:
    if form is not None:
        names = form.getlist("item_name")
        quantities = form.getlist("quantity")
        prices = form.getlist("unit_price")
        rows = [
            {
                "product_name": name,
                "quantity": quantity,
                "unit_price": price,
            }
            for name, quantity, price in itertools.zip_longest(
                names,
                quantities,
                prices,
                fillvalue="",
            )
        ]
        return {
            "customer_name": form.get("customer_name", ""),
            "customer_contact": form.get("customer_contact", ""),
            "delivery_address": form.get("delivery_address", ""),
            "status": form.get("status", "pending"),
            "items": rows or [{"product_name": "", "quantity": "1", "unit_price": ""}],
        }
    if order is not None:
        return {
            "customer_name": order.customer_name,
            "customer_contact": order.customer_contact,
            "delivery_address": order.delivery_address,
            "status": order.status,
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                }
                for item in order.items
            ],
        }
    return {
        "customer_name": "",
        "customer_contact": "",
        "delivery_address": "",
        "status": "pending",
        "items": [{"product_name": "", "quantity": "1", "unit_price": ""}],
    }


def calculate_local_delivery_fee(delivery_address: str) -> tuple[Decimal, str | None]:
    normalized = delivery_address.lower().strip()
    if not normalized:
        return Decimal("0.00"), "Enter a delivery address for nearby delivery orders."
    if not any(keyword in normalized for keyword in LOCAL_DELIVERY_AREA_KEYWORDS):
        return Decimal("0.00"), (
            "Delivery is available only in nearby service areas around the shop. "
            "Please choose meet-up at the shop or update the nearby delivery address."
        )
    return Decimal("35.00"), None


def save_product_image(file_storage) -> tuple[str | None, str | None]:
    """Save an uploaded product image. Returns (relative_path, error)."""
    if file_storage is None or not getattr(file_storage, "filename", None):
        return None, None
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None, "Choose a valid image file."
    extension = Path(filename).suffix.lower()
    if extension not in PRODUCT_IMAGE_EXTENSIONS:
        return None, "Image must be JPG, PNG, WEBP, or GIF."
    PRODUCT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = PRODUCT_UPLOAD_DIR / stored_name
    file_storage.save(destination)
    return f"uploads/products/{stored_name}", None


def ensure_category_exists(category_name: str) -> None:
    name = category_name.strip()
    if name not in INVENTORY_CATEGORIES:
        return
    try:
        categories.create(name, sort_order=INVENTORY_CATEGORIES.index(name) + 1)
    except mysql.connector.IntegrityError:
        return


def parse_product_form(
    existing_image_path: str | None = None,
) -> tuple[Product | None, str | None]:
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    sku = request.form.get("sku", "").strip() or None
    description = request.form.get("description", "").strip()
    unit = request.form.get("unit", DEFAULT_PRODUCT_UNIT).strip().lower()
    available_for_sale = request.form.get("available_for_sale") == "1"
    price_value = request.form.get("unit_price", "").strip()
    stock_value = request.form.get("stock_quantity", "").strip()

    if not 1 <= len(name) <= 160:
        return None, "Enter a product name between 1 and 160 characters."
    if category not in INVENTORY_CATEGORIES:
        return None, "Choose one of the three inventory categories."
    if unit not in PRODUCT_UNITS:
        return None, "Choose a valid unit of measurement."
    if sku is not None and not 1 <= len(sku) <= 40:
        return None, "SKU must be between 1 and 40 characters."
    if len(description) > 2000:
        return None, "Description must be no more than 2000 characters."
    try:
        unit_price = Decimal(price_value)
        stock_quantity = int(stock_value)
        rounded_price = unit_price.quantize(Decimal("0.01"))
    except (ValueError, InvalidOperation):
        return None, "Enter a valid price and whole-number stock quantity."
    if (
        not unit_price.is_finite()
        or unit_price < 0
        or unit_price > Decimal("99999999.99")
        or unit_price != rounded_price
    ):
        return None, "Price must be a valid amount with up to two decimal places."
    if not 0 <= stock_quantity <= 4294967295:
        return None, "Stock quantity must be between 0 and 4,294,967,295."

    image_path = existing_image_path
    uploaded = request.files.get("image")
    saved_path, image_error = save_product_image(uploaded)
    if image_error:
        return None, image_error
    if saved_path:
        image_path = saved_path

    return (
        Product(
            id=0,
            name=name,
            category=category,
            unit_price=unit_price,
            stock_quantity=stock_quantity,
            image_path=image_path,
            sku=sku,
            description=description,
            unit=unit,
            available_for_sale=available_for_sale,
        ),
        None,
    )


def product_form_values(product=None, form=None) -> dict:
    if form is not None:
        return {
            "name": form.get("name", ""),
            "category": form.get("category", ""),
            "sku": form.get("sku", ""),
            "description": form.get("description", ""),
            "unit": form.get("unit", DEFAULT_PRODUCT_UNIT),
            "available_for_sale": form.get("available_for_sale") == "1",
            "unit_price": form.get("unit_price", ""),
            "stock_quantity": form.get("stock_quantity", ""),
            "image_path": form.get("image_path", ""),
        }
    if product is not None:
        return {
            "name": product.name,
            "category": product.category,
            "sku": product.sku or "",
            "description": product.description or "",
            "unit": product.unit or DEFAULT_PRODUCT_UNIT,
            "available_for_sale": bool(product.available_for_sale),
            "unit_price": product.unit_price,
            "stock_quantity": product.stock_quantity,
            "image_path": product.image_path or "",
        }
    return {
        "name": "",
        "category": "",
        "sku": "",
        "description": "",
        "unit": DEFAULT_PRODUCT_UNIT,
        "available_for_sale": True,
        "unit_price": "",
        "stock_quantity": "0",
        "image_path": "",
    }


def payment_status_for_method(payment_method: str) -> str:
    if payment_method == "cod":
        return "cod-pending"
    return "awaiting-payment"


def parse_profile_form(account) -> tuple[dict | None, str | None, str | None]:
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    profile_data = {"full_name": full_name, "email": email}

    if not account.verify_password(current_password):
        return profile_data, None, "Current password is incorrect."
    if not 2 <= len(full_name) <= 120:
        return profile_data, None, "Enter a name between 2 and 120 characters."
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
        return profile_data, None, "Enter a valid email address."
    if new_password or confirm_password:
        if not password_length_is_valid(new_password):
            return (
                profile_data,
                None,
                (
                    f"Your new password must be between {PASSWORD_MIN_LENGTH} and "
                    f"{PASSWORD_MAX_LENGTH} characters."
                ),
            )
        if new_password != confirm_password:
            return profile_data, None, "The new passwords do not match."
        return profile_data, generate_password_hash(new_password), None
    return profile_data, None, None


def notify_welcome(email: str, full_name: str, account_type: str) -> None:
    if mail_service.send_welcome_email(email, full_name, account_type):
        flash("A welcome email was sent to your address.", "info")


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def account_repository(account_type: str):
    return customer_accounts if account_type == "customer" else users


def resend_cooldown_remaining(account) -> int:
    last_sent = getattr(account, "verification_last_sent_at", None)
    if not last_sent:
        return 0
    if getattr(last_sent, "tzinfo", None) is not None:
        last_sent = last_sent.astimezone(timezone.utc).replace(tzinfo=None)
    elapsed = (utc_now_naive() - last_sent).total_seconds()
    remaining = VERIFICATION_RESEND_COOLDOWN_SECONDS - int(elapsed)
    return max(0, remaining)


def issue_verification_code(account, account_type: str) -> str:
    code = generate_verification_code()
    now = utc_now_naive()
    expires_at = now + timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)
    code_hash = generate_password_hash(code)
    repo = account_repository(account_type)
    repo.set_verification_challenge(account.id, code_hash, expires_at, now)
    account.verification_code_hash = code_hash
    account.verification_expires_at = expires_at
    account.verification_attempts = 0
    account.verification_last_sent_at = now
    account.email_verified = False
    return code


def notify_verification_code(
    email: str,
    full_name: str,
    code: str,
    account_type: str,
) -> bool:
    sent = mail_service.send_verification_code(email, full_name, code, account_type)
    if sent:
        flash("We sent a 6-digit verification code to your email.", "info")
    else:
        flash(
            "Your account was created, but the verification email could not be sent. "
            "Check SMTP settings, then use Resend code.",
            "error",
        )
    return sent


def begin_email_verification(email: str, account_type: str) -> None:
    session["pending_verification_email"] = email
    session["pending_verification_account"] = account_type


def handle_verification_post(account, account_type: str, email: str, action: str):
    """Process verify/resend for customer or staff. Returns redirect response or None."""
    login_endpoint = "customer_login" if account_type == "customer" else "login"
    repo = account_repository(account_type)

    if action == "resend":
        wait_seconds = resend_cooldown_remaining(account)
        if wait_seconds > 0:
            flash(
                f"Please wait {wait_seconds} seconds before requesting another code.",
                "error",
            )
            return None
        code = issue_verification_code(account, account_type)
        notify_verification_code(email, account.full_name, code, account_type)
        begin_email_verification(email, account_type)
        return None

    if account.verification_attempts >= VERIFICATION_MAX_ATTEMPTS:
        flash(
            "Too many incorrect attempts. Use Resend code to get a new verification code.",
            "error",
        )
        return None

    code = request.form.get("verification_code", "").strip()
    if not re.fullmatch(r"\d{6}", code):
        flash("Enter the 6-digit verification code from your email.", "error")
        return None

    if not account.verify_email_code(code):
        attempts = repo.increment_verification_attempts(account.id)
        account.verification_attempts = attempts
        remaining = VERIFICATION_MAX_ATTEMPTS - attempts
        if remaining <= 0:
            flash(
                "Too many incorrect attempts. Use Resend code to get a new verification code.",
                "error",
            )
        else:
            flash(
                f"That verification code is invalid or has expired. "
                f"{remaining} attempt(s) remaining.",
                "error",
            )
        return None

    repo.mark_email_verified(account.id)
    session.pop("pending_verification_email", None)
    session.pop("pending_verification_account", None)
    notify_welcome(email, account.full_name, account_type)
    flash("Your email is verified. Please sign in.", "success")
    return redirect(url_for(login_endpoint))


def notify_order_placed(order_id: int, order: CustomerOrder, customer) -> None:
    mail_service.send_order_confirmation(
        customer.email,
        customer.full_name,
        order_id,
        f"{order.total:.2f}",
        order.delivery_option,
    )


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if session.get("customer_id"):
        return redirect(url_for("customer_dashboard"))
    return render_template("index.html")


@app.route("/catalog")
def public_catalog():
    return render_template(
        "catalog.html",
        products=products.list_products(available_for_sale=True),
        customer_signed_in=isinstance(session.get("customer_id"), int),
        cart_count=sum(customer_cart().values()),
    )


@app.route("/customer/register", methods=("GET", "POST"))
def customer_register():
    if isinstance(session.get("customer_id"), int):
        return redirect(url_for("customer_dashboard"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not 2 <= len(full_name) <= 120:
            flash("Enter a name between 2 and 120 characters.", "error")
        elif not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif not password_length_is_valid(password):
            flash(
                f"Your password must be between {PASSWORD_MIN_LENGTH} and "
                f"{PASSWORD_MAX_LENGTH} characters.",
                "error",
            )
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        else:
            try:
                customer = CustomerAccount.create(full_name, email, password)
                customer.id = customer_accounts.create_account(customer)
            except mysql.connector.IntegrityError as error:
                if error.errno == 1062:
                    flash("A customer account with that email already exists.", "error")
                else:
                    raise
            else:
                code = issue_verification_code(customer, "customer")
                notify_verification_code(email, full_name, code, "customer")
                begin_email_verification(email, "customer")
                flash("Enter the verification code from your email to activate your account.", "success")
                return redirect(url_for("customer_verify_email"))
    return render_template("customer_register.html")


@app.route("/customer/verify", methods=("GET", "POST"))
def customer_verify_email():
    if isinstance(session.get("customer_id"), int):
        return redirect(url_for("customer_dashboard"))
    email = (
        request.form.get("email", "").strip().lower()
        or session.get("pending_verification_email", "")
    )
    customer = None
    if email and EMAIL_PATTERN.fullmatch(email) and len(email) <= 254:
        customer = customer_accounts.get_by_email(email)
    if request.method == "POST":
        action = request.form.get("action", "verify")
        if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            flash("Enter the email address used during registration.", "error")
        elif customer is None:
            flash("No customer account was found for that email.", "error")
        elif customer.email_verified:
            flash("That email is already verified. Please sign in.", "info")
            return redirect(url_for("customer_login"))
        else:
            response = handle_verification_post(customer, "customer", email, action)
            if response is not None:
                return response
            customer = customer_accounts.get_by_email(email)
    return render_template(
        "verify_email.html",
        account_type="customer",
        email=email,
        verify_endpoint="customer_verify_email",
        login_endpoint="customer_login",
        register_endpoint="customer_register",
        resend_wait_seconds=resend_cooldown_remaining(customer) if customer else 0,
    )


@app.route("/customer/login", methods=("GET", "POST"))
def customer_login():
    if isinstance(session.get("customer_id"), int):
        return redirect(url_for("customer_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        customer = (
            customer_accounts.get_by_email(email)
            if EMAIL_PATTERN.fullmatch(email) and len(email) <= 254
            else None
        )
        if (
            customer is None
            or not password
            or len(password) > PASSWORD_MAX_LENGTH
            or not customer.verify_password(password)
        ):
            flash("Email or password is incorrect.", "error")
        elif not customer.email_verified:
            begin_email_verification(email, "customer")
            flash("Please verify your email before signing in.", "info")
            return redirect(url_for("customer_verify_email"))
        else:
            session.clear()
            session["customer_id"] = customer.id
            flash(f"Welcome, {customer.full_name}.", "success")
            return redirect(url_for("customer_dashboard"))
    return render_template("customer_login.html")


@app.post("/customer/auth/firebase")
def customer_firebase_auth():
    if not firebase_enabled():
        return jsonify({"ok": False, "error": "Firebase authentication is not configured."}), 503

    payload = request.get_json(silent=True) or {}
    id_token = str(payload.get("idToken") or "").strip()
    claims = verify_firebase_id_token(id_token)
    if claims is None:
        return jsonify({"ok": False, "error": "Firebase sign-in could not be verified."}), 401

    firebase_uid = str(claims.get("uid") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    full_name = str(
        claims.get("name")
        or payload.get("fullName")
        or (email.split("@")[0] if email else "Customer")
    ).strip()[:120]
    email_verified = bool(claims.get("email_verified", False))

    if not firebase_uid or not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
        return jsonify({"ok": False, "error": "Firebase account is missing a valid email."}), 400
    if not email_verified:
        return jsonify(
            {
                "ok": False,
                "error": "Verify your Firebase email first, then sign in again.",
            }
        ), 403
    if not 2 <= len(full_name) <= 120:
        full_name = email.split("@")[0][:120]

    account = customer_accounts.get_by_firebase_uid(firebase_uid)
    if account is None:
        account = customer_accounts.get_by_email(email)
        if account is None:
            account = CustomerAccount.create_from_firebase(full_name, email, firebase_uid)
            try:
                account.id = customer_accounts.create_account(account)
            except mysql.connector.IntegrityError:
                account = customer_accounts.get_by_email(email)
                if account is None:
                    return jsonify({"ok": False, "error": "Could not create customer account."}), 409
        if account.firebase_uid != firebase_uid:
            customer_accounts.link_firebase_uid(account.id, firebase_uid)
            account.firebase_uid = firebase_uid
        if not account.email_verified:
            customer_accounts.mark_email_verified(account.id)
            account.email_verified = True

    session.clear()
    session["customer_id"] = account.id
    session["auth_provider"] = "firebase"
    return jsonify(
        {
            "ok": True,
            "redirect": url_for("customer_dashboard"),
            "full_name": account.full_name,
        }
    )


@app.post("/customer/logout")
@customer_login_required
def customer_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@app.post("/customer/cart/add/<int:product_id>")
@customer_login_required
def customer_cart_add(product_id: int):
    product = products.get(product_id)
    if product is None or not product.available_for_sale:
        abort(404)
    next_url = request.form.get("next", "").strip()
    allowed_next = {
        url_for("customer_dashboard"),
        url_for("customer_cart_view"),
        url_for("customer_product_detail", product_id=product_id),
    }
    redirect_target = next_url if next_url in allowed_next else url_for(
        "customer_product_detail", product_id=product_id
    )
    if product.stock_quantity < 1:
        flash("This product is currently out of stock.", "error")
        return redirect(redirect_target)
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    cart = customer_cart()
    new_quantity = cart.get(product_id, 0) + quantity
    if quantity < 1 or new_quantity > min(product.stock_quantity, 100):
        flash("Choose a quantity available in stock (maximum 100 kg per item).", "error")
        return redirect(redirect_target)
    cart[product_id] = new_quantity
    session["customer_cart"] = {str(key): value for key, value in cart.items()}
    flash(f"{product.name} added to your order ({quantity} kg).", "success")
    if request.form.get("checkout") == "1":
        return redirect(url_for("customer_cart_view"))
    return redirect(url_for("customer_cart_view"))


@app.route("/customer/cart", methods=("GET", "POST"))
@customer_login_required
def customer_cart_view():
    cart = customer_cart()
    if request.method == "POST":
        product_id_value = request.form.get("product_id", "")
        try:
            product_id = int(product_id_value)
            quantity = int(request.form.get("quantity", "0"))
        except ValueError:
            flash("Enter a valid cart quantity.", "error")
            return redirect(url_for("customer_cart_view"))
        product = products.get(product_id)
        if product is None:
            cart.pop(product_id, None)
            flash("That product is no longer available.", "error")
        elif quantity == 0:
            cart.pop(product_id, None)
            flash("Item removed from your cart.", "success")
        elif quantity < 1 or quantity > 100 or quantity > product.stock_quantity:
            flash("Choose a quantity currently available in stock.", "error")
        else:
            cart[product_id] = quantity
            flash("Cart updated.", "success")
        session["customer_cart"] = {str(key): value for key, value in cart.items()}
        return redirect(url_for("customer_cart_view"))

    rows = []
    for product_id, quantity in cart.items():
        product = products.get(product_id)
        if product is None:
            continue
        rows.append(
            {
                "product": product,
                "quantity": quantity,
                "line_total": product.unit_price * quantity,
            }
        )
    return render_template(
        "customer_cart.html",
        cart_items=rows,
        total=sum(
            (row["line_total"] for row in rows),
            start=Decimal("0.00"),
        ),
        active_page="cart",
    )


@app.route("/customer/checkout", methods=("GET", "POST"))
@customer_login_required
def customer_checkout():
    cart = customer_cart()
    if not cart:
        flash("Your cart is empty.", "info")
        return redirect(url_for("customer_cart_view"))
    rows = []
    for product_id, quantity in cart.items():
        product = products.get(product_id)
        if product is None:
            flash("A product in your cart is no longer available. Review your cart.", "error")
            return redirect(url_for("customer_cart_view"))
        rows.append(
            {
                "product": product,
                "quantity": quantity,
                "line_total": product.unit_price * quantity,
            }
        )

    form_data = {
        "customer_name": g.current_customer.full_name,
        "customer_contact": "",
        "delivery_address": "",
        "delivery_option": "delivery",
        "payment_method": "gcash",
    }
    order_total = sum((row["line_total"] for row in rows), start=Decimal("0.00"))
    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        customer_contact = request.form.get("customer_contact", "").strip()
        delivery_option = request.form.get("delivery_option", "delivery").strip().lower()
        delivery_address = request.form.get("delivery_address", "").strip()
        payment_method = request.form.get("payment_method", "").strip().lower()
        form_data.update(
            customer_name=customer_name,
            customer_contact=customer_contact,
            delivery_address=delivery_address,
            delivery_option=delivery_option,
            payment_method=payment_method,
        )
        can_place = True
        delivery_fee = Decimal("0.00")
        final_address = "Pickup at shop"
        if payment_method not in PAYMENT_METHODS:
            flash(
                "Choose a payment method: GCash, Bank Transfer, or Cash on Delivery.",
                "error",
            )
            can_place = False
        elif delivery_option not in DELIVERY_OPTIONS:
            flash("Choose either pickup or nearby delivery.", "error")
            can_place = False
        elif not 2 <= len(customer_name) <= 120:
            flash("Enter a customer name between 2 and 120 characters.", "error")
            can_place = False
        elif not PHONE_PATTERN.fullmatch(customer_contact):
            flash("Enter a valid number between 7 and 40 characters.", "error")
            can_place = False
        elif not 5 <= len(delivery_address) <= 500:
            flash("Enter an address between 5 and 500 characters.", "error")
            can_place = False
        elif delivery_option == "delivery":
            delivery_fee, delivery_error = calculate_local_delivery_fee(
                delivery_address
            )
            final_address = delivery_address
            if delivery_error is not None:
                flash(delivery_error, "error")
                can_place = False
        else:
            final_address = delivery_address

        if can_place:
            order = CustomerOrder(
                id=0,
                customer_name=customer_name,
                customer_contact=customer_contact,
                delivery_address=final_address,
                status="pending",
                delivery_option=delivery_option,
                delivery_fee=delivery_fee
                if delivery_option == "delivery"
                else Decimal("0.00"),
                delivery_status="pending",
                payment_method=payment_method,
                payment_status=payment_status_for_method(payment_method),
            )
            try:
                order_id = orders.create_customer_order(
                    order,
                    g.current_customer.id,
                    cart,
                )
            except InventoryConflictError as error:
                flash(
                    f"{error} Your cart was not charged; review available stock.",
                    "error",
                )
                return redirect(url_for("customer_cart_view"))
            session.pop("customer_cart", None)
            created = orders.get_customer_order(order_id, g.current_customer.id)
            if created is not None:
                notify_order_placed(order_id, created, g.current_customer)
            return redirect(url_for("customer_payment", order_id=order_id))

    delivery_fee = Decimal("0.00")
    if form_data["delivery_option"] == "delivery":
        delivery_fee, _ = calculate_local_delivery_fee(form_data["delivery_address"])
    return render_template(
        "customer_checkout.html",
        cart_items=rows,
        total=order_total + delivery_fee,
        form_data=form_data,
        delivery_fee=delivery_fee,
        payment_methods=PAYMENT_METHOD_LABELS,
        active_page="cart",
    )


def customer_stock_status(quantity: int) -> str:
    if quantity <= 0:
        return "out"
    if quantity <= LOW_STOCK_THRESHOLD:
        return "low"
    return "in"


@app.route("/customer/dashboard")
@customer_login_required
def customer_dashboard():
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "").strip().lower()

    catalog = products.list_products(available_for_sale=True)
    category_names = list(INVENTORY_CATEGORIES)

    if category:
        catalog = [
            item
            for item in catalog
            if (item.category or "").strip().lower() == category.lower()
        ]
    if search:
        catalog = [
            item
            for item in catalog
            if search in item.name.lower()
            or search in (item.category or "").lower()
        ]
    if status == "available":
        catalog = [item for item in catalog if item.stock_quantity > 0]
    elif status == "low":
        catalog = [
            item
            for item in catalog
            if 0 < item.stock_quantity <= LOW_STOCK_THRESHOLD
        ]
    elif status == "out":
        catalog = [item for item in catalog if item.stock_quantity <= 0]

    catalog.sort(key=lambda item: item.name.lower())
    return render_template(
        "customer_dashboard.html",
        customer=g.current_customer,
        products=catalog,
        categories=category_names,
        active_category=category,
        search=request.args.get("q", "").strip(),
        status=status,
        customer_stock_status=customer_stock_status,
        active_page="dashboard",
    )


@app.route("/customer/profile", methods=("GET", "POST"))
@customer_login_required
def customer_profile():
    profile_data = {
        "full_name": g.current_customer.full_name,
        "email": g.current_customer.email,
    }
    if request.method == "POST":
        profile_data, password_hash, error = parse_profile_form(g.current_customer)
        if error:
            flash(error, "error")
        else:
            try:
                customer_accounts.update_profile(
                    g.current_customer.id,
                    profile_data["full_name"],
                    profile_data["email"],
                    password_hash,
                )
            except mysql.connector.IntegrityError as integrity_error:
                if integrity_error.errno == 1062:
                    flash("That email is already used by another account.", "error")
                else:
                    raise
            else:
                g.current_customer = customer_accounts.get_by_id(g.current_customer.id)
                flash("Your profile was updated.", "success")
                return redirect(url_for("customer_profile"))
    return render_template(
        "customer_profile.html",
        profile_data=profile_data,
        active_page="profile",
    )


@app.route("/customer/orders")
@customer_login_required
def customer_orders():
    return render_template(
        "customer_orders.html",
        orders=orders.list_customer_orders(g.current_customer.id),
        active_page="orders",
    )


@app.route("/customer/orders/<int:order_id>")
@customer_login_required
def customer_order_detail(order_id: int):
    order = orders.get_customer_order(order_id, g.current_customer.id)
    if order is None:
        abort(404)
    return render_template(
        "customer_order_detail.html",
        order=order,
        active_page="orders",
    )


@app.route("/customer/products/<int:product_id>")
@customer_login_required
def customer_product_detail(product_id: int):
    product = products.get(product_id)
    if product is None or not product.available_for_sale:
        abort(404)
    return render_template(
        "customer_product_detail.html",
        product=product,
        customer_stock_status=customer_stock_status,
        active_page="dashboard",
    )


@app.route("/customer/orders/<int:order_id>/payment", methods=("GET", "POST"))
@customer_login_required
def customer_payment(order_id: int):
    order = orders.get_customer_order(order_id, g.current_customer.id)
    if order is None:
        abort(404)
    if request.method == "POST":
        if order.payment_method == "cod":
            flash(
                "Cash on Delivery selected. Pay the rider or shop staff when you receive your order.",
                "info",
            )
            return redirect(url_for("customer_order_detail", order_id=order_id))
        reference = request.form.get("payment_reference", "").strip()
        if not 4 <= len(reference) <= 120:
            flash("Enter a payment reference between 4 and 120 characters.", "error")
        elif orders.submit_payment_reference(
            order_id, g.current_customer.id, reference
        ):
            flash(
                "Payment reference submitted. Staff will verify it before confirming payment.",
                "success",
            )
            return redirect(url_for("customer_order_detail", order_id=order_id))
        else:
            flash("This order cannot accept a payment reference right now.", "error")
        order = orders.get_customer_order(order_id, g.current_customer.id)
    return render_template(
        "customer_payment.html",
        order=order,
        payment_label=PAYMENT_METHOD_LABELS.get(
            order.payment_method, order.payment_method or "Payment"
        ),
        active_page="orders",
    )


@app.route("/customer/orders/<int:order_id>/demo-payment", methods=("GET", "POST"))
@customer_login_required
def customer_demo_payment(order_id: int):
    return redirect(url_for("customer_payment", order_id=order_id))


@app.route("/login", methods=("GET", "POST"))
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = (
            users.get_by_email(email)
            if EMAIL_PATTERN.fullmatch(email) and len(email) <= 254
            else None
        )
        if (
            user is None
            or not password
            or len(password) > PASSWORD_MAX_LENGTH
            or not user.verify_password(password)
        ):
            flash("Email or password is incorrect.", "error")
        elif not user.email_verified:
            begin_email_verification(email, "staff")
            flash("Please verify your email before signing in.", "info")
            return redirect(url_for("staff_verify_email"))
        else:
            session.clear()
            session["user_id"] = user.id
            flash(f"Welcome back, {user.full_name}.", "success")
            return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/verify", methods=("GET", "POST"))
def staff_verify_email():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    email = (
        request.form.get("email", "").strip().lower()
        or session.get("pending_verification_email", "")
    )
    user = None
    if email and EMAIL_PATTERN.fullmatch(email) and len(email) <= 254:
        user = users.get_by_email(email)
    if request.method == "POST":
        action = request.form.get("action", "verify")
        if not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            flash("Enter the email address used during registration.", "error")
        elif user is None:
            flash("No staff account was found for that email.", "error")
        elif user.email_verified:
            flash("That email is already verified. Please sign in.", "info")
            return redirect(url_for("login"))
        else:
            response = handle_verification_post(user, "staff", email, action)
            if response is not None:
                return response
            user = users.get_by_email(email)
    return render_template(
        "verify_email.html",
        account_type="staff",
        email=email,
        verify_endpoint="staff_verify_email",
        login_endpoint="login",
        register_endpoint="register",
        resend_wait_seconds=resend_cooldown_remaining(user) if user else 0,
    )


@app.route("/register", methods=("GET", "POST"))
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    registration_configured = staff_registration_is_configured()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        registration_code = request.form.get("registration_code", "")

        if not registration_configured:
            flash(
                "Staff registration is unavailable until a registration code is configured.",
                "error",
            )
        elif not staff_registration_code_is_valid(registration_code):
            flash("Enter a valid staff registration code.", "error")
        elif not 2 <= len(full_name) <= 120:
            flash("Enter a name between 2 and 120 characters.", "error")
        elif not EMAIL_PATTERN.fullmatch(email) or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif not password_length_is_valid(password):
            flash(
                f"Your password must be between {PASSWORD_MIN_LENGTH} and "
                f"{PASSWORD_MAX_LENGTH} characters.",
                "error",
            )
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        else:
            try:
                user = User.create(full_name, email, password)
                user.id = users.create_account(user)
            except mysql.connector.IntegrityError as error:
                if error.errno == 1062:
                    flash("An account with that email already exists.", "error")
                else:
                    raise
            else:
                code = issue_verification_code(user, "staff")
                notify_verification_code(email, full_name, code, "staff")
                begin_email_verification(email, "staff")
                flash(
                    "Enter the verification code from your email to activate your account.",
                    "success",
                )
                return redirect(url_for("staff_verify_email"))
    return render_template(
        "register.html",
        requires_registration_code=True,
    )


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    summary = orders.summary()
    recent_orders = orders.list_orders(limit=5)
    inventory_summary = products.inventory_summary(LOW_STOCK_THRESHOLD)
    return render_template(
        "dashboard.html",
        summary=summary,
        recent_orders=recent_orders,
        inventory_summary=inventory_summary,
    )


@app.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    profile_data = {
        "full_name": g.current_user.full_name,
        "email": g.current_user.email,
    }
    if request.method == "POST":
        profile_data, password_hash, error = parse_profile_form(g.current_user)
        if error:
            flash(error, "error")
        else:
            try:
                users.update_profile(
                    g.current_user.id,
                    profile_data["full_name"],
                    profile_data["email"],
                    password_hash,
                )
            except mysql.connector.IntegrityError as integrity_error:
                if integrity_error.errno == 1062:
                    flash("That email is already used by another account.", "error")
                else:
                    raise
            else:
                g.current_user = users.get_by_id(g.current_user.id)
                flash("Your profile was updated.", "success")
                return redirect(url_for("profile"))
    return render_template("profile.html", profile_data=profile_data)


@app.route("/orders")
@login_required
def order_list():
    search = request.args.get("q", "").strip()[:100]
    status = request.args.get("status", "").strip()
    if status not in ORDER_STATUSES:
        status = ""
    order_rows = orders.list_orders(search=search, status=status)
    return render_template(
        "orders.html",
        orders=order_rows,
        search=search,
        selected_status=status,
        statuses=ORDER_STATUSES,
    )


@app.route("/riders")
@login_required
def rider_list():
    return render_template("riders.html", riders=list_available_riders())


@app.route("/riders/new", methods=("GET", "POST"))
@login_required
def new_rider():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        service_area = request.form.get("service_area", "").strip()
        if not 2 <= len(full_name) <= 120:
            flash("Enter a rider name between 2 and 120 characters.", "error")
        elif not PHONE_PATTERN.fullmatch(phone_number):
            flash("Enter a valid contact number between 7 and 40 characters.", "error")
        elif not 2 <= len(service_area) <= 120:
            flash("Enter the rider's service area.", "error")
        else:
            try:
                riders.create(
                    Rider(
                        id=0,
                        full_name=full_name,
                        phone_number=phone_number,
                        service_area=service_area,
                        status="available",
                    )
                )
            except mysql.connector.Error:
                flash("Rider management is unavailable until the database is ready.", "error")
                return render_template("rider_form.html", rider=None, editing=False)
            flash("The rider was added to the delivery team.", "success")
            return redirect(url_for("rider_list"))
    return render_template("rider_form.html", rider=None, editing=False)


@app.route("/riders/<int:rider_id>/edit", methods=("GET", "POST"))
@login_required
def edit_rider(rider_id: int):
    rider = riders.get(rider_id)
    if rider is None:
        abort(404)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        service_area = request.form.get("service_area", "").strip()
        status = request.form.get("status", rider.status).strip()
        if not 2 <= len(full_name) <= 120:
            flash("Enter a rider name between 2 and 120 characters.", "error")
        elif not PHONE_PATTERN.fullmatch(phone_number):
            flash("Enter a valid contact number between 7 and 40 characters.", "error")
        elif not 2 <= len(service_area) <= 120:
            flash("Enter the rider's service area.", "error")
        elif status not in {"available", "busy", "offline"}:
            flash("Choose a valid rider status.", "error")
        else:
            riders.update(
                Rider(
                    id=rider_id,
                    full_name=full_name,
                    phone_number=phone_number,
                    service_area=service_area,
                    status=status,
                )
            )
            flash("The rider details were updated.", "success")
            return redirect(url_for("rider_list"))
    return render_template("rider_form.html", rider=rider, editing=True)


@app.post("/riders/<int:rider_id>/delete")
@login_required
def delete_rider(rider_id: int):
    if riders.get(rider_id) is None:
        abort(404)
    riders.delete(rider_id)
    flash("The rider was removed from the delivery list.", "success")
    return redirect(url_for("rider_list"))


@app.route("/products")
@login_required
def product_list():
    return redirect(url_for("inventory.inventory_home"))


def _product_form_context(**extra):
    context = {
        "category_options": list(INVENTORY_CATEGORIES),
        "category_examples": CATEGORY_EXAMPLES,
        "product_units": PRODUCT_UNITS,
    }
    context.update(extra)
    return context


@app.route("/products/new", methods=("GET", "POST"))
@login_required
def new_product():
    if request.method == "POST":
        product, error = parse_product_form()
        if error:
            flash(error, "error")
            return render_template(
                "product_form.html",
                **_product_form_context(
                    form_data=product_form_values(form=request.form),
                    editing=False,
                ),
            ), 400
        try:
            products.create(product)
        except mysql.connector.IntegrityError:
            flash("That SKU is already in use.", "error")
            return render_template(
                "product_form.html",
                **_product_form_context(
                    form_data=product_form_values(form=request.form),
                    editing=False,
                ),
            ), 400
        ensure_category_exists(product.category)
        flash("The product was added to inventory.", "success")
        return redirect(url_for("inventory.inventory_home"))
    return render_template(
        "product_form.html",
        **_product_form_context(
            form_data=product_form_values(),
            editing=False,
        ),
    )


@app.route("/products/<int:product_id>/edit", methods=("GET", "POST"))
@login_required
def edit_product(product_id: int):
    product = products.get(product_id)
    if product is None:
        abort(404)
    if request.method == "POST":
        updated_product, error = parse_product_form(
            existing_image_path=product.image_path
        )
        if error:
            flash(error, "error")
            form_data = product_form_values(form=request.form)
            form_data["image_path"] = product.image_path or ""
            return render_template(
                "product_form.html",
                **_product_form_context(
                    form_data=form_data,
                    editing=True,
                    product_id=product_id,
                ),
            ), 400
        updated_product.id = product_id
        try:
            products.update(updated_product)
        except mysql.connector.IntegrityError:
            flash("That SKU is already in use.", "error")
            form_data = product_form_values(form=request.form)
            form_data["image_path"] = product.image_path or ""
            return render_template(
                "product_form.html",
                **_product_form_context(
                    form_data=form_data,
                    editing=True,
                    product_id=product_id,
                ),
            ), 400
        ensure_category_exists(updated_product.category)
        flash("The product was updated.", "success")
        return redirect(url_for("inventory.inventory_home"))
    return render_template(
        "product_form.html",
        **_product_form_context(
            form_data=product_form_values(product=product),
            editing=True,
            product_id=product_id,
        ),
    )


@app.post("/products/<int:product_id>/delete")
@login_required
def delete_product(product_id: int):
    if products.get(product_id) is None:
        abort(404)
    products.delete(product_id)
    flash("The product was removed from inventory.", "success")
    return redirect(url_for("inventory.inventory_home"))


@app.route("/orders/new", methods=("GET", "POST"))
@login_required
def new_order():
    if request.method == "POST":
        order, error = parse_order_form()
        if error:
            flash(error, "error")
            return render_template(
                "order_form.html",
                form_data=order_form_values(form=request.form),
                editing=False,
                statuses=ORDER_STATUSES,
            ), 400
        order_id = orders.create(order, g.current_user.id)
        flash("The order was created.", "success")
        return redirect(url_for("order_detail", order_id=order_id))
    return render_template(
        "order_form.html",
        form_data=order_form_values(),
        editing=False,
        statuses=ORDER_STATUSES,
    )


@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id: int):
    order = orders.get(order_id)
    if order is None:
        abort(404)
    try:
        assigned_rider = riders.get(order.rider_id) if order.rider_id else None
    except mysql.connector.Error:
        assigned_rider = None
    rider_list = list_available_riders()
    return render_template("order_detail.html", order=order, assigned_rider=assigned_rider, riders=rider_list)


@app.post("/orders/<int:order_id>/assign-rider")
@login_required
def assign_rider(order_id: int):
    order = orders.get(order_id)
    if order is None:
        abort(404)
    rider_id = request.form.get("rider_id")
    if rider_id in (None, ""):
        flash("Choose a rider before assigning the order.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    try:
        rider = riders.get(int(rider_id))
    except mysql.connector.Error:
        flash("Rider assignment is unavailable while the database is not ready.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    if rider is None:
        flash("That rider could not be found.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    new_status = "assigned-to-rider" if order.delivery_option == "delivery" else "confirmed"
    orders.assign_rider(order_id, rider.id, new_status)
    flash(f"Order assigned to {rider.full_name}.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.post("/orders/<int:order_id>/delivery-status")
@login_required
def update_delivery_status(order_id: int):
    order = orders.get(order_id)
    if order is None:
        abort(404)
    status = request.form.get("delivery_status", "").strip()
    if order.delivery_option != "delivery":
        flash("This order is for pickup only.", "info")
        return redirect(url_for("order_detail", order_id=order_id))
    if status not in {"pending", "confirmed", "preparing", "assigned-to-rider", "out-for-delivery", "delivered", "for-delivery", "completed", "cancelled"}:
        flash("Choose a valid delivery status.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    orders.assign_rider(order_id, order.rider_id, status)
    flash("The delivery status was updated.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.post("/orders/<int:order_id>/verify-payment")
@login_required
def verify_order_payment(order_id: int):
    order = orders.get(order_id)
    if order is None:
        abort(404)
    if orders.verify_payment(order_id):
        flash("Payment marked as verified.", "success")
    else:
        flash("This order is not ready for payment verification.", "error")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/orders/<int:order_id>/edit", methods=("GET", "POST"))
@login_required
def edit_order(order_id: int):
    order = orders.get(order_id)
    if order is None:
        abort(404)
    if request.method == "POST":
        if order.customer_account_id is not None:
            customer_name = request.form.get("customer_name", "").strip()
            customer_contact = request.form.get("customer_contact", "").strip()
            delivery_address = request.form.get("delivery_address", "").strip()
            status = request.form.get("status", "").strip()
            if not 2 <= len(customer_name) <= 120:
                error = "Enter a customer name between 2 and 120 characters."
            elif not PHONE_PATTERN.fullmatch(customer_contact):
                error = "Enter a valid contact number between 7 and 40 characters."
            elif not 5 <= len(delivery_address) <= 500:
                error = "Enter a delivery address between 5 and 500 characters."
            elif status not in ORDER_STATUSES:
                error = "Choose a valid order status."
            else:
                error = None

            if error:
                flash(error, "error")
                return render_template(
                    "order_form.html",
                    form_data={
                        "customer_name": customer_name,
                        "customer_contact": customer_contact,
                        "delivery_address": delivery_address,
                        "status": status or order.status,
                        "items": [],
                    },
                    editing=True,
                    order_id=order_id,
                    statuses=ORDER_STATUSES,
                    customer_order=True,
                ), 400
            updated_order = CustomerOrder(
                id=order_id,
                customer_name=customer_name,
                customer_contact=customer_contact,
                delivery_address=delivery_address,
                status=status,
                customer_account_id=order.customer_account_id,
            )
            try:
                orders.update(updated_order)
            except InventoryConflictError as error:
                flash(str(error), "error")
                return render_template(
                    "order_form.html",
                    form_data=order_form_values(order=order),
                    editing=True,
                    order_id=order_id,
                    statuses=ORDER_STATUSES,
                    customer_order=True,
                ), 400
            flash("The customer order was updated.", "success")
            return redirect(url_for("order_detail", order_id=order_id))

        updated_order, error = parse_order_form()
        if error:
            flash(error, "error")
            return render_template(
                "order_form.html",
                form_data=order_form_values(form=request.form),
                editing=True,
                order_id=order_id,
                statuses=ORDER_STATUSES,
            ), 400
        updated_order.id = order_id
        orders.update(updated_order)
        flash("The order was updated.", "success")
        return redirect(url_for("order_detail", order_id=order_id))
    return render_template(
        "order_form.html",
        form_data=order_form_values(order=order),
        editing=True,
        order_id=order_id,
        statuses=ORDER_STATUSES,
        customer_order=order.customer_account_id is not None,
    )


@app.post("/orders/<int:order_id>/delete")
@login_required
def delete_order(order_id: int):
    if orders.get(order_id) is None:
        abort(404)
    orders.delete(order_id)
    flash("The order was deleted.", "success")
    return redirect(url_for("order_list"))


@app.errorhandler(mysql.connector.Error)
def handle_database_error(error):
    app.logger.exception("Database operation failed: %s", error)
    return (
        render_template(
            "error.html",
            title="Database unavailable",
            message="We could not complete that request. Check the MySQL connection and try again.",
        ),
        503,
    )


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return (
        render_template(
            "error.html",
            title="Form expired",
            message="This form could not be verified. Reload the page and try again.",
        ),
        400,
    )


from inventory_bp import inventory_bp

app.register_blueprint(inventory_bp)


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
