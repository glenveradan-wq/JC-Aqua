"""Firebase Authentication helpers for customer sign-in."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any


logger = logging.getLogger(__name__)


def firebase_web_config() -> dict[str, str] | None:
    """Public web config used by the browser SDK. Returns None when incomplete."""
    api_key = os.environ.get("FIREBASE_API_KEY", "").strip()
    auth_domain = os.environ.get("FIREBASE_AUTH_DOMAIN", "").strip()
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
    app_id = os.environ.get("FIREBASE_APP_ID", "").strip()
    messaging_sender_id = os.environ.get("FIREBASE_MESSAGING_SENDER_ID", "").strip()
    storage_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()

    if not (api_key and auth_domain and project_id and app_id):
        return None

    config = {
        "apiKey": api_key,
        "authDomain": auth_domain,
        "projectId": project_id,
        "appId": app_id,
    }
    if messaging_sender_id:
        config["messagingSenderId"] = messaging_sender_id
    if storage_bucket:
        config["storageBucket"] = storage_bucket
    return config


def firebase_client_configured() -> bool:
    return firebase_web_config() is not None


def firebase_enabled() -> bool:
    """True when the browser SDK and Admin verification are both ready."""
    return firebase_client_configured() and _admin_ready()


def _credentials_path() -> str:
    return (
        os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip()
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    )


def _credentials_json() -> str:
    return os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()


def _admin_ready() -> bool:
    return bool(_credentials_path() or _credentials_json())


@lru_cache(maxsize=1)
def _get_firebase_app():
    if not _admin_ready():
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.warning("firebase-admin is not installed.")
        return None

    if firebase_admin._apps:
        return firebase_admin.get_app()

    try:
        raw_json = _credentials_json()
        if raw_json:
            info = json.loads(raw_json)
            cred = credentials.Certificate(info)
        else:
            cred = credentials.Certificate(_credentials_path())
        return firebase_admin.initialize_app(cred)
    except Exception:
        logger.exception("Failed to initialize Firebase Admin SDK.")
        return None


def verify_firebase_id_token(id_token: str) -> dict[str, Any] | None:
    """Verify a Firebase ID token and return decoded claims, or None on failure."""
    token = (id_token or "").strip()
    if not token:
        return None

    app = _get_firebase_app()
    if app is None:
        return None

    try:
        from firebase_admin import auth

        return auth.verify_id_token(token)
    except Exception:
        logger.exception("Firebase ID token verification failed.")
        return None
