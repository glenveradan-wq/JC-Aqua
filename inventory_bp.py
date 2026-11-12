"""Staff inventory management UI (card grid, categories, stock movements)."""

from __future__ import annotations

from datetime import datetime
from functools import wraps

import mysql.connector
from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from catalog_config import INVENTORY_CATEGORIES
from repositories import (
    CategoryRepository,
    InventoryConflictError,
    ProductRepository,
    StockMovementRepository,
    UserRepository,
)


inventory_bp = Blueprint("inventory", __name__)

LOW_STOCK_THRESHOLD = 5
products = ProductRepository()
categories = CategoryRepository()
stock_movements = StockMovementRepository()
users = UserRepository()


def staff_login_required(view):
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


def stock_status(quantity: int) -> str:
    if quantity <= 0:
        return "out"
    if quantity <= LOW_STOCK_THRESHOLD:
        return "low"
    return "in"


def _inventory_url(**params):
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return url_for("inventory.inventory_home", **clean)


@inventory_bp.app_context_processor
def inject_inventory_helpers():
    return {
        "inventory_stock_status": stock_status,
        "inventory_low_stock_threshold": LOW_STOCK_THRESHOLD,
    }


@inventory_bp.get("/inventory")
@staff_login_required
def inventory_home():
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip().lower()
    sort = request.args.get("sort", "name").strip().lower()
    status = request.args.get("status", "").strip().lower()
    product_id_raw = request.args.get("product", "").strip()
    panel = request.args.get("panel", "").strip().lower()
    stock_action = request.args.get("stock", "").strip().lower()
    if stock_action not in {"in", "out", "adjust"}:
        stock_action = ""

    catalog = products.list_products()
    category_names = list(INVENTORY_CATEGORIES)
    summary = products.inventory_summary(LOW_STOCK_THRESHOLD)

    if category == "__uncategorized__":
        catalog = [
            p
            for p in catalog
            if (p.category or "").strip() not in INVENTORY_CATEGORIES
        ]
    elif category:
        catalog = [
            p
            for p in catalog
            if (p.category or "").strip().lower() == category.lower()
        ]
    if search:
        catalog = [
            p
            for p in catalog
            if search in p.name.lower()
            or search in (p.category or "").lower()
            or search in (p.sku or "").lower()
        ]
    if status == "in":
        catalog = [p for p in catalog if p.stock_quantity > LOW_STOCK_THRESHOLD]
    elif status == "low":
        catalog = [
            p for p in catalog if 0 < p.stock_quantity <= LOW_STOCK_THRESHOLD
        ]
    elif status == "out":
        catalog = [p for p in catalog if p.stock_quantity <= 0]

    if sort == "price":
        catalog.sort(key=lambda p: (p.unit_price, p.name.lower()))
    elif sort == "stock":
        catalog.sort(key=lambda p: (p.stock_quantity, p.name.lower()))
    elif sort == "sku":
        catalog.sort(key=lambda p: ((p.sku or "").lower(), p.name.lower()))
    else:
        catalog.sort(key=lambda p: p.name.lower())
        sort = "name"

    selected = None
    product_movements = []
    if product_id_raw.isdigit():
        selected = products.get(int(product_id_raw))
        if selected is not None:
            product_movements = stock_movements.list_movements(
                product_id=selected.id,
                limit=12,
            )

    return render_template(
        "inventory/browse.html",
        products=catalog,
        categories=category_names,
        summary=summary,
        active_category=category,
        search=request.args.get("q", "").strip(),
        sort=sort,
        status=status,
        selected_product=selected,
        product_movements=product_movements,
        panel=panel,
        stock_action=stock_action,
        stock_form_data={
            "quantity": request.args.get("quantity", ""),
            "note": request.args.get("note", ""),
        },
        now=datetime.now(),
        active_page="inventory",
    )


@inventory_bp.route("/categories", methods=("GET", "POST"))
@staff_login_required
def category_list():
    # Categories are fixed to the three inventory groups; no separate page.
    flash(
        "Inventory uses three fixed categories: Fish Food, Aquarium, and Aquarium Accessories.",
        "info",
    )
    return redirect(url_for("inventory.inventory_home"))


@inventory_bp.route("/categories/<int:category_id>/edit", methods=("GET", "POST"))
@staff_login_required
def category_edit(category_id: int):
    return redirect(url_for("inventory.inventory_home"))


@inventory_bp.post("/categories/<int:category_id>/delete")
@staff_login_required
def category_delete(category_id: int):
    flash("The three inventory categories are fixed and cannot be deleted.", "info")
    return redirect(url_for("inventory.inventory_home"))


@inventory_bp.route("/stock/in", methods=("GET", "POST"))
@staff_login_required
def stock_in():
    return _stock_form("in", "Add stock", "Record newly received inventory.")


@inventory_bp.route("/stock/out", methods=("GET", "POST"))
@staff_login_required
def stock_out():
    return _stock_form("out", "Deduct stock", "Record released or deducted inventory.")


@inventory_bp.route("/stock/adjust", methods=("GET", "POST"))
@staff_login_required
def stock_adjust():
    return _stock_form(
        "adjustment",
        "Adjust stock",
        "Set the correct on-hand quantity for a product.",
    )


def _stock_form(movement_type: str, title: str, description: str):
    catalog = products.list_products()
    form_data = {
        "product_id": request.form.get(
            "product_id", request.args.get("product_id", "")
        ),
        "quantity": request.form.get("quantity", ""),
        "note": request.form.get("note", ""),
    }
    stock_key = {
        "in": "in",
        "out": "out",
        "adjustment": "adjust",
    }[movement_type]

    def _return_to_inventory_modal(product_id: int | str):
        return redirect(
            _inventory_url(
                product=product_id,
                stock=stock_key,
                quantity=form_data["quantity"],
                note=form_data["note"],
            )
        )

    if request.method == "POST":
        try:
            product_id = int(form_data["product_id"])
            quantity = int(form_data["quantity"])
        except ValueError:
            flash("Select a product and enter a valid quantity.", "error")
            if form_data["product_id"].isdigit():
                return _return_to_inventory_modal(form_data["product_id"])
        else:
            note = form_data["note"].strip()
            if not note:
                flash("Enter a reason for this stock adjustment.", "error")
                return _return_to_inventory_modal(product_id)
            try:
                stock_movements.apply_movement(
                    product_id=product_id,
                    movement_type=movement_type,
                    quantity=quantity,
                    note=note,
                    created_by=g.current_user.id,
                )
            except (InventoryConflictError, ValueError) as error:
                flash(str(error), "error")
                return _return_to_inventory_modal(product_id)
            flash("Stock movement saved.", "success")
            return redirect(_inventory_url(product=product_id))

    # Prefer Inventory modal UX; keep standalone form for bookmarks/tests.
    if request.method == "GET" and form_data["product_id"]:
        return redirect(
            _inventory_url(product=form_data["product_id"], stock=stock_key)
        )

    return render_template(
        "inventory/stock_form.html",
        movement_type=movement_type,
        title=title,
        description=description,
        products=catalog,
        form_data=form_data,
        now=datetime.now(),
        active_page="inventory",
    )


@inventory_bp.get("/stock/history")
@staff_login_required
def stock_history():
    movement_type = request.args.get("type", "").strip().lower()
    product_raw = request.args.get("product_id", "").strip()
    product_id = int(product_raw) if product_raw.isdigit() else None
    movements = stock_movements.list_movements(
        product_id=product_id,
        movement_type=movement_type,
        limit=150,
    )
    return render_template(
        "inventory/stock_history.html",
        movements=movements,
        products=products.list_products(),
        selected_product_id=product_id,
        selected_type=movement_type,
        active_page="stock-history",
    )
