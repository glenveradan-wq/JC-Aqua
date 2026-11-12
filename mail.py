"""SMTP email helpers for JC Aqua Fish Shop."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage


logger = logging.getLogger(__name__)


class MailService:
    """Send transactional emails over SMTP when configured."""

    def __init__(self) -> None:
        self.host = os.environ.get("SMTP_HOST", "").strip()
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.username = os.environ.get("SMTP_USERNAME", "").strip()
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.use_tls = os.environ.get("SMTP_USE_TLS", "1") == "1"
        self.sender = os.environ.get(
            "SMTP_SENDER",
            self.username or "noreply@jcaqua.local",
        ).strip()
        self.enabled = os.environ.get("SMTP_ENABLED", "0") == "1"

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.host and self.sender)

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        if not self.is_configured:
            logger.info("SMTP skipped (not configured): %s -> %s", subject, recipient)
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = recipient
        message.set_content(body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=20) as server:
                if self.use_tls:
                    server.starttls()
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException):
            logger.exception("Failed to send email to %s", recipient)
            return False
        return True

    def send_welcome_email(self, recipient: str, full_name: str, account_type: str) -> bool:
        subject = "Welcome to JC Aqua Fish Shop"
        role = "customer" if account_type == "customer" else "staff"
        body = (
            f"Hello {full_name},\n\n"
            f"Your {role} account for JC Aqua Fish Shop is verified and ready.\n"
            "You can sign in anytime to continue shopping or managing orders.\n\n"
            "JC Aqua Fish Shop\n"
        )
        return self.send_email(recipient, subject, body)

    def send_verification_code(
        self,
        recipient: str,
        full_name: str,
        code: str,
        account_type: str,
    ) -> bool:
        role = "customer" if account_type == "customer" else "staff"
        subject = "Your JC Aqua Fish Shop verification code"
        body = (
            f"Hello {full_name},\n\n"
            f"Your {role} email verification code is: {code}\n\n"
            "Enter this code on the verification page to activate your account.\n"
            "The code expires in 5 minutes.\n\n"
            "If you did not create this account, you can ignore this email.\n\n"
            "JC Aqua Fish Shop\n"
        )
        return self.send_email(recipient, subject, body)

    def send_order_confirmation(
        self,
        recipient: str,
        full_name: str,
        order_id: int,
        total: str,
        delivery_option: str,
    ) -> bool:
        subject = f"Order #{order_id} received — JC Aqua Fish Shop"
        body = (
            f"Hello {full_name},\n\n"
            f"We received your order #{order_id}.\n"
            f"Fulfillment: {delivery_option}\n"
            f"Total: PHP {total}\n\n"
            "You can track status from your customer dashboard.\n"
            "Demo payments in this project do not charge a real card.\n\n"
            "Thank you for shopping with JC Aqua Fish Shop.\n"
        )
        return self.send_email(recipient, subject, body)
