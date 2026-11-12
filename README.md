# JC Aqua Fish Shop

Flask shop-management application with separate customer and staff accounts.
Customers can browse products, manage a cart, place orders, and view order
status and history. Staff can manage products, inventory, and customer orders.
Payments are simulated only; no real payment provider or third-party delivery
API is connected.

## Requirements

- Python 3.10 or later
- MySQL 8 or compatible MySQL server
- A MySQL account that can create a database and tables

## Run locally on Windows PowerShell

From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set the connection settings for your local MySQL installation. Do not commit
real passwords or API secrets:

```powershell
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = ""
$env:MYSQL_DATABASE = "jc_aqua_fish_shop"
$env:FLASK_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
# Required for staff signup at /register (blocked when unset or incorrect)
$env:STAFF_REGISTRATION_CODE = "your-private-invite-code"
# Local HTTP: leave COOKIE_SECURE unset or 0. HTTPS production: set to 1.
# $env:COOKIE_SECURE = "1"
# Optional SMTP (welcome + order emails). Leave SMTP_ENABLED=0 until configured.
# $env:SMTP_ENABLED = "1"
# $env:SMTP_HOST = "smtp.gmail.com"
# $env:SMTP_PORT = "587"
# $env:SMTP_USERNAME = "you@example.com"
# $env:SMTP_PASSWORD = "app-password"
# $env:SMTP_SENDER = "you@example.com"
# Optional Firebase customer auth (Google + email). See .env.example.
# $env:FIREBASE_API_KEY = "..."
# $env:FIREBASE_AUTH_DOMAIN = "your-project.firebaseapp.com"
# $env:FIREBASE_PROJECT_ID = "your-project"
# $env:FIREBASE_APP_ID = "1:...:web:..."
# $env:FIREBASE_CREDENTIALS_FILE = "C:\path\to\serviceAccount.json"
```

See `.env.example` for the full settings list. Do not commit real secrets.
Customer Firebase buttons appear on `/customer/login` and `/customer/register`
only when both the web config and Admin credentials are set.

For local XAMPP only, `MYSQL_PASSWORD` may be empty if the local MySQL `root`
account has no password. Prefer a dedicated MySQL user for other setups.

Create the database tables and start Flask:

```powershell
python init_db.py
python app.py
```

Open `http://127.0.0.1:5000/`. Customer accounts can be created at
`/customer/register`. After registration, a 6-digit verification code is emailed
and must be entered at `/customer/verify` before `/customer/login` works.
Staff accounts use the same flow at `/register` then `/verify`. Customers can
browse `/catalog`, add in-stock products to their cart, check out, and view
their orders at `/customer/orders`. Checkout reserves inventory; cancelling
or deleting a customer order releases its reserved stock.

Staff accounts are separate. Create a staff account at `/register` (requires
`STAFF_REGISTRATION_CODE`) and sign in at `/login` to use `/dashboard`,
`/orders`, and `/products`. Staff registration is rejected when the invite
code is missing or incorrect. Staff can update product prices and stock and
manage customer order status. Customer order items remain tied to their
purchased products and cannot be changed in the staff order editor.

Session cookies use `HttpOnly` and `SameSite=Lax`. For HTTPS deployments set
`COOKIE_SECURE=1` so cookies are marked `Secure` and the app sends
`Strict-Transport-Security`. Keep `COOKIE_SECURE=0` for local HTTP.

## Deploy on Vercel (MySQL required)

Vercel does **not** run your XAMPP MySQL. `.env` is gitignored, so you must
paste env vars in **Vercel → Project Settings → Environment Variables**.

1. Create a **cloud MySQL** database (Railway, Aiven, FreeSQLDatabase, etc.).
2. Run `python init_db.py` locally against that cloud DB (set `MYSQL_*` first)
   so tables exist.
3. In Vercel, set at least:
   - `FLASK_SECRET_KEY`
   - `MYSQL_HOST` (cloud hostname, **not** `127.0.0.1`)
   - `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE`
   - or one `DATABASE_URL=mysql://user:pass@host:3306/jc_aqua_fish_shop`
   - `SMTP_*` for email OTP
   - `STAFF_REGISTRATION_CODE`
   - `COOKIE_SECURE=1`
4. Redeploy, then open `/health/db` — `"ok": true` means MySQL is reachable.

The staff workspace pages share a common navigation and layout template.

The order total is calculated from item quantities and unit prices on the
server. Orders support `pending`, `confirmed`, `preparing`, `for-delivery`,
`completed`, and `cancelled` statuses. Checkout and stock reservation run in
one database transaction. All state-changing forms use CSRF protection;
passwords are stored as Werkzeug password hashes.

The customer payment screen is a demo simulator only. It records a demo
payment status in the application and does not charge a payment method, call a
gateway, or confirm a real transaction.

## Local delivery

The shop uses a nearby-area delivery model for customers within approved
service zones. Orders outside the nearby service area are offered as pickup
only. Delivery is managed locally by the shop or assigned local riders and
requires no third-party API connection for the initial implementation.
