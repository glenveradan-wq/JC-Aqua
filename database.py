import os

import mysql.connector


def mysql_settings(include_database: bool = True) -> dict:
    settings = {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
    }
    if include_database:
        settings["database"] = os.environ.get(
            "MYSQL_DATABASE",
            "jc_aqua_fish_shop",
        )
    return settings


def get_connection():
    return mysql.connector.connect(**mysql_settings())
