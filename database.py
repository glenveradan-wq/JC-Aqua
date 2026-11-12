"""MySQL connection helpers for local XAMPP and cloud hosts (Vercel, Render, Railway)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import mysql.connector


def _load_dotenv_if_present() -> None:
    """Load project .env for local runs. On Vercel, dashboard env vars win."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


_load_dotenv_if_present()


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def _parse_database_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql+mysqlconnector", "mariadb"}:
        raise ValueError("DATABASE_URL / MYSQL_URL must start with mysql://")
    database = (parsed.path or "").lstrip("/")
    if "?" in database:
        database = database.split("?", 1)[0]
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": int(parsed.port or 3306),
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "database": database or "jc_aqua_fish_shop",
    }


def _ssl_enabled(host: str) -> bool:
    flag = _first_env("MYSQL_SSL", "DB_SSL", default="").lower()
    if flag in {"1", "true", "yes", "required"}:
        return True
    if flag in {"0", "false", "no", "disable", "disabled"}:
        return False
    # Cloud hosts almost always need TLS; local XAMPP does not.
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    return host not in local_hosts


def mysql_settings(include_database: bool = True) -> dict:
    url = _first_env("DATABASE_URL", "MYSQL_URL", "MYSQL_PUBLIC_URL")
    if url:
        settings = _parse_database_url(url)
    else:
        settings = {
            "host": _first_env("MYSQL_HOST", "DB_HOST", "MYSQLHOST", default="127.0.0.1"),
            "port": int(_first_env("MYSQL_PORT", "DB_PORT", "MYSQLPORT", default="3306")),
            "user": _first_env(
                "MYSQL_USER",
                "DB_USERNAME",
                "DB_USER",
                "MYSQLUSER",
                default="root",
            ),
            "password": _first_env("MYSQL_PASSWORD", "DB_PASSWORD", "MYSQLPASSWORD", default=""),
            "database": _first_env(
                "MYSQL_DATABASE",
                "DB_DATABASE",
                "DB_NAME",
                "MYSQLDATABASE",
                default="jc_aqua_fish_shop",
            ),
        }

    if not include_database:
        settings.pop("database", None)

    # Serverless-friendly timeouts (Vercel / Render).
    settings["connection_timeout"] = int(_first_env("MYSQL_CONNECT_TIMEOUT", default="15"))
    settings["autocommit"] = False

    if _ssl_enabled(settings["host"]):
        # mysql-connector accepts an empty dict to enable TLS defaults.
        settings["ssl_disabled"] = False
        settings["ssl_verify_cert"] = _first_env("MYSQL_SSL_VERIFY", default="0") in {
            "1",
            "true",
            "yes",
        }
    else:
        settings["ssl_disabled"] = True

    return settings


def get_connection():
    settings = mysql_settings()
    # Pure-Python mode is more reliable on Vercel serverless than the C extension.
    settings["use_pure"] = True
    return mysql.connector.connect(**settings)


def database_ping() -> bool:
    try:
        connection = get_connection()
        try:
            connection.ping(reconnect=True, attempts=1, delay=0)
            return True
        finally:
            connection.close()
    except mysql.connector.Error:
        return False
