"""PyMySQL-backed stand-in for mysql.connector (pure Python, Vercel-safe).

Importing the real mysql-connector-python C extension often crashes serverless
workers with FUNCTION_INVOCATION_FAILED before Flask can return a response.
This module keeps the existing `import mysql.connector` call sites working.
"""

from __future__ import annotations

import ssl as ssl_module
from typing import Any

import pymysql
from pymysql.err import (
    DatabaseError,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
    Warning,
)

__all__ = [
    "connect",
    "Error",
    "Warning",
    "InterfaceError",
    "DatabaseError",
    "DataError",
    "OperationalError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "NotSupportedError",
]


class _CompatConnection:
    """Expose mysql.connector-style cursor(dictionary=True) on a PyMySQL connection."""

    def __init__(self, raw: pymysql.connections.Connection) -> None:
        self._raw = raw

    def cursor(self, dictionary: bool = False, **_kwargs: Any):
        if dictionary:
            return self._raw.cursor(pymysql.cursors.DictCursor)
        return self._raw.cursor()

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()

    def ping(self, reconnect: bool = True, attempts: int = 1, delay: int = 0, **_kwargs: Any):
        # mysql.connector accepts attempts/delay; PyMySQL only has reconnect.
        _ = attempts, delay
        return self._raw.ping(reconnect=reconnect)

    def is_connected(self) -> bool:
        try:
            self._raw.ping(reconnect=False)
            return True
        except Exception:  # noqa: BLE001
            return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def connect(**kwargs: Any) -> _CompatConnection:
    host = kwargs.get("host", "127.0.0.1")
    port = int(kwargs.get("port") or 3306)
    user = kwargs.get("user", "root")
    password = kwargs.get("password", "")
    database = kwargs.get("database")
    connect_timeout = int(
        kwargs.get("connection_timeout")
        or kwargs.get("connect_timeout")
        or 15
    )
    autocommit = bool(kwargs.get("autocommit", False))

    connect_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "connect_timeout": connect_timeout,
        "autocommit": autocommit,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.Cursor,
    }
    if database:
        connect_kwargs["database"] = database

    ssl_disabled = kwargs.get("ssl_disabled")
    if ssl_disabled is False or (
        ssl_disabled is None and kwargs.get("ssl") is not None
    ):
        ctx = ssl_module.create_default_context()
        verify = bool(kwargs.get("ssl_verify_cert"))
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl_module.CERT_NONE
        connect_kwargs["ssl"] = ctx
    elif isinstance(kwargs.get("ssl"), (dict, ssl_module.SSLContext)):
        connect_kwargs["ssl"] = kwargs["ssl"]

    return _CompatConnection(pymysql.connect(**connect_kwargs))
