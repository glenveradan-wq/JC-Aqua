"""SMTP email helpers for JC Aqua Fish Shop."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from html import escape


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

    def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        if not self.is_configured:
            logger.info("SMTP skipped (not configured): %s -> %s", subject, recipient)
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = recipient
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

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
        safe_name = escape(full_name or "Customer")
        safe_code = escape(code)
        subject = "Your 6-Digit Verification Code"
        body = (
            f"Hello {full_name},\n\n"
            "Thank you for registering with us!\n\n"
            "Your email verification code is:\n\n"
            f"{code}\n\n"
            "This code will expire in 5 minutes.\n\n"
            "For your security, do not share this code with anyone.\n\n"
            "If you did not request this verification, you can ignore this email.\n\n"
            "Thank you,\n"
            "Customer Support Team\n"
        )
        if account_type != "customer":
            body = (
                f"Hello {full_name},\n\n"
                f"Your staff email verification code is: {code}\n\n"
                "Enter this code on the verification page to activate your account.\n"
                "The code expires in 5 minutes.\n\n"
                "If you did not create this account, you can ignore this email.\n\n"
                "JC Aqua Fish Shop\n"
            )
            subject = "Your JC Aqua Fish Shop verification code"
            return self.send_email(recipient, subject, body)

        html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Verification code</title>
</head>
<body style="margin:0;padding:0;background:#f3f8fa;font-family:Segoe UI,Arial,sans-serif;color:#1f3a40;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f8fa;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #d8e4e8;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="padding:24px 28px;background:#0f4a52;color:#ffffff;">
              <p style="margin:0;font-size:14px;letter-spacing:.04em;text-transform:uppercase;opacity:.85;">JC Aqua Fish Shop</p>
              <h1 style="margin:8px 0 0;font-size:22px;line-height:1.3;">Your 6-Digit Verification Code</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:28px;">
              <p style="margin:0 0 12px;font-size:16px;">Hello {safe_name},</p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.55;color:#4f6870;">
                Thank you for registering with us!
              </p>
              <p style="margin:0 0 10px;font-size:15px;color:#4f6870;">Your email verification code is:</p>
              <p style="margin:0 0 20px;font-size:32px;letter-spacing:.35em;font-weight:700;color:#0f4a52;text-align:center;">
                {safe_code}
              </p>
              <p style="margin:0 0 12px;font-size:14px;line-height:1.55;color:#4f6870;">
                This code will expire in <strong>5 minutes</strong>.
              </p>
              <p style="margin:0 0 12px;font-size:14px;line-height:1.55;color:#4f6870;">
                For your security, do not share this code with anyone.
              </p>
              <p style="margin:0;font-size:14px;line-height:1.55;color:#4f6870;">
                If you did not request this verification, you can ignore this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 28px;border-top:1px solid #e8efef;font-size:13px;color:#6a8086;">
              Thank you,<br>Customer Support Team
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        return self.send_email(recipient, subject, body, html_body=html_body)

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
