import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from werkzeug.security import check_password_hash, generate_password_hash


ORDER_STATUSES = (
    "pending",
    "confirmed",
    "preparing",
    "assigned-to-rider",
    "out-for-delivery",
    "delivered",
    "for-delivery",
    "completed",
    "cancelled",
)

DELIVERY_OPTIONS = ("pickup", "delivery")
LOCAL_DELIVERY_AREA_KEYWORDS = (
    "laguna",
    "sta. cruz",
    "sta cruz",
    "calamba",
    "cabuyao",
    "los baños",
    "los banos",
    "pila",
    "siniloan",
    "liliw",
    "nagcarlan",
    "magdalena",
    "pagsanjan",
    "san pedro",
    "biñan",
    "binan",
)


@dataclass
class User:
    id: int
    full_name: str
    email: str
    password_hash: str
    email_verified: bool = False
    verification_code_hash: str | None = None
    verification_expires_at: datetime | None = None
    verification_attempts: int = 0
    verification_last_sent_at: datetime | None = None

    @classmethod
    def create(cls, full_name: str, email: str, password: str) -> "User":
        return cls(
            id=0,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            email_verified=False,
        )

    @classmethod
    def from_row(cls, row: dict) -> "User":
        return cls(
            id=row["id"],
            full_name=row["full_name"],
            email=row["email"],
            password_hash=row["password_hash"],
            email_verified=bool(row.get("email_verified", False)),
            verification_code_hash=row.get("verification_code_hash"),
            verification_expires_at=row.get("verification_expires_at"),
            verification_attempts=int(row.get("verification_attempts") or 0),
            verification_last_sent_at=row.get("verification_last_sent_at"),
        )

    def verify_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def verify_email_code(self, code: str) -> bool:
        if not self.verification_code_hash:
            return False
        if self.verification_expires_at and self.verification_expires_at < datetime.now(
            timezone.utc
        ).replace(tzinfo=None):
            return False
        return check_password_hash(self.verification_code_hash, code)


@dataclass
class CustomerAccount:
    id: int
    full_name: str
    email: str
    password_hash: str
    email_verified: bool = False
    email_verified_at: datetime | None = None
    first_login_verified: bool = False
    first_login_verified_at: datetime | None = None
    verification_code_hash: str | None = None
    verification_expires_at: datetime | None = None
    verification_attempts: int = 0
    verification_last_sent_at: datetime | None = None
    firebase_uid: str | None = None

    @classmethod
    def create(cls, full_name: str, email: str, password: str) -> "CustomerAccount":
        return cls(
            id=0,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            email_verified=False,
            first_login_verified=False,
        )

    @classmethod
    def create_from_firebase(
        cls,
        full_name: str,
        email: str,
        firebase_uid: str,
    ) -> "CustomerAccount":
        # Local password login is disabled for Firebase-only accounts.
        random_secret = f"firebase:{firebase_uid}:{secrets.token_urlsafe(24)}"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return cls(
            id=0,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(random_secret),
            email_verified=True,
            email_verified_at=now,
            first_login_verified=True,
            first_login_verified_at=now,
            firebase_uid=firebase_uid,
        )

    @classmethod
    def from_row(cls, row: dict) -> "CustomerAccount":
        return cls(
            id=row["id"],
            full_name=row["full_name"],
            email=row["email"],
            password_hash=row["password_hash"],
            email_verified=bool(row.get("email_verified", False)),
            email_verified_at=row.get("email_verified_at"),
            first_login_verified=bool(row.get("first_login_verified", False)),
            first_login_verified_at=row.get("first_login_verified_at"),
            verification_code_hash=row.get("verification_code_hash"),
            verification_expires_at=row.get("verification_expires_at"),
            verification_attempts=int(row.get("verification_attempts") or 0),
            verification_last_sent_at=row.get("verification_last_sent_at"),
            firebase_uid=row.get("firebase_uid"),
        )

    def verify_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def verify_email_code(self, code: str) -> bool:
        if not self.verification_code_hash:
            return False
        if self.verification_expires_at and self.verification_expires_at < datetime.now(
            timezone.utc
        ).replace(tzinfo=None):
            return False
        return check_password_hash(self.verification_code_hash, code)


@dataclass
class PendingRegistration:
    id: int
    full_name: str
    email: str
    password_hash: str
    otp_hash: str
    otp_expires_at: datetime
    attempts: int = 0
    last_sent_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "PendingRegistration":
        return cls(
            id=int(row["id"]),
            full_name=row["full_name"],
            email=row["email"],
            password_hash=row["password_hash"],
            otp_hash=row["otp_hash"],
            otp_expires_at=row["otp_expires_at"],
            attempts=int(row.get("attempts") or 0),
            last_sent_at=row.get("last_sent_at"),
            created_at=row.get("created_at"),
        )

    def otp_is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc).replace(tzinfo=None)
        expires = self.otp_expires_at
        if getattr(expires, "tzinfo", None) is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return expires < current

    def verify_otp(self, code: str, now: datetime | None = None) -> bool:
        if not self.otp_hash or self.otp_is_expired(now):
            return False
        return check_password_hash(self.otp_hash, code)


@dataclass
class EmailVerificationCode:
    id: int
    email: str
    otp_hash: str
    verification_type: str
    expires_at: datetime
    customer_id: int | None = None
    attempts: int = 0
    is_used: bool = False
    created_at: datetime | None = None
    verified_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "EmailVerificationCode":
        return cls(
            id=int(row["id"]),
            email=row["email"],
            otp_hash=row["otp_hash"],
            verification_type=row["verification_type"],
            expires_at=row["expires_at"],
            customer_id=row.get("customer_id"),
            attempts=int(row.get("attempts") or 0),
            is_used=bool(row.get("is_used", False)),
            created_at=row.get("created_at"),
            verified_at=row.get("verified_at"),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc).replace(tzinfo=None)
        expires = self.expires_at
        if getattr(expires, "tzinfo", None) is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return expires < current

    def verify_otp(self, code: str, now: datetime | None = None) -> bool:
        if self.is_used or not self.otp_hash or self.is_expired(now):
            return False
        return check_password_hash(self.otp_hash, code)


@dataclass
class OrderItem:
    product_name: str
    quantity: int
    unit_price: Decimal
    product_id: int | None = None

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def with_quantity(self, quantity: int) -> "OrderItem":
        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")
        return OrderItem(
            product_name=self.product_name,
            quantity=quantity,
            unit_price=self.unit_price,
            product_id=self.product_id,
        )


@dataclass
class Product:
    id: int
    name: str
    category: str
    unit_price: Decimal
    stock_quantity: int
    image_path: str | None = None
    sku: str | None = None
    description: str = ""
    unit: str = "pieces"
    available_for_sale: bool = True
    low_stock_threshold: int = 5

    @classmethod
    def from_row(cls, row: dict) -> "Product":
        return cls(
            id=int(row["id"]),
            name=row["name"],
            category=row.get("category") or "",
            unit_price=Decimal(str(row["unit_price"])),
            stock_quantity=int(row.get("stock_quantity") or 0),
            image_path=row.get("image_path"),
            sku=row.get("sku"),
            description=row.get("description") or "",
            unit=row.get("unit") or "pieces",
            available_for_sale=bool(row.get("available_for_sale", True)),
        )

    def is_in_stock(self) -> bool:
        return self.stock_quantity > 0

    def is_low_stock(self) -> bool:
        return 0 < self.stock_quantity <= self.low_stock_threshold

    def is_out_of_stock(self) -> bool:
        return self.stock_quantity <= 0

    def can_sell(self, quantity: int = 1) -> bool:
        return (
            self.available_for_sale
            and quantity > 0
            and self.stock_quantity >= quantity
        )

    def stock_status(self) -> str:
        if self.is_out_of_stock():
            return "out-of-stock"
        if self.is_low_stock():
            return "low-stock"
        return "in-stock"

    def apply_stock_change(self, delta: int) -> int:
        """Return the new stock quantity after applying a signed delta."""
        new_quantity = self.stock_quantity + delta
        if new_quantity < 0:
            raise ValueError("Stock quantity cannot go below zero.")
        self.stock_quantity = new_quantity
        return self.stock_quantity


@dataclass
class Category:
    id: int
    name: str
    sort_order: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "Category":
        return cls(
            id=int(row["id"]),
            name=row["name"],
            sort_order=int(row.get("sort_order") or 0),
        )

    def display_name(self) -> str:
        return self.name.strip()


@dataclass
class StockMovement:
    id: int
    product_id: int
    movement_type: str
    quantity: int
    quantity_before: int
    quantity_after: int
    note: str = ""
    created_by: int | None = None
    created_at: datetime | None = None
    product_name: str = ""
    created_by_name: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "StockMovement":
        return cls(
            id=int(row["id"]),
            product_id=int(row["product_id"]),
            movement_type=row["movement_type"],
            quantity=int(row["quantity"]),
            quantity_before=int(row["quantity_before"]),
            quantity_after=int(row["quantity_after"]),
            note=row.get("note") or "",
            created_by=row.get("created_by"),
            created_at=row.get("created_at"),
            product_name=row.get("product_name") or "",
            created_by_name=row.get("created_by_name") or "",
        )

    def is_increase(self) -> bool:
        return self.quantity_after > self.quantity_before


@dataclass
class Rider:
    id: int
    full_name: str
    phone_number: str
    service_area: str
    status: str = "available"

    def is_available(self) -> bool:
        return self.status == "available"

    def can_serve_area(self, area: str) -> bool:
        if not area:
            return False
        return area.strip().lower() in self.service_area.strip().lower()


@dataclass
class CustomerOrder:
    id: int
    customer_name: str
    customer_contact: str
    delivery_address: str
    status: str
    items: list[OrderItem] = field(default_factory=list)
    created_at: datetime | None = None
    customer_account_id: int | None = None
    payment_status: str = "not-required"
    payment_method: str = ""
    payment_reference: str = ""
    payment_screenshot_path: str | None = None
    stock_reserved: bool = False
    delivery_option: str = "pickup"
    delivery_fee: Decimal = field(default_factory=lambda: Decimal("0.00"))
    delivery_status: str = "pending"
    service_area: str = ""
    rider_id: int | None = None

    @property
    def items_subtotal(self) -> Decimal:
        return sum(
            (item.line_total for item in self.items),
            start=Decimal("0.00"),
        )

    @property
    def total(self) -> Decimal:
        return self.items_subtotal + self.delivery_fee

    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    def is_pickup(self) -> bool:
        return self.delivery_option == "pickup"

    def is_delivery(self) -> bool:
        return self.delivery_option == "delivery"

    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    def awaits_payment_verification(self) -> bool:
        return self.payment_status in {"pending", "submitted", "awaiting-verification"}
