-- Safe migration: customer email OTP verification + first-login gate
-- Does not drop tables or delete existing customer rows.
-- Run via: python init_db.py  (preferred)  OR apply manually in MySQL Workbench.

ALTER TABLE customer_accounts
    ADD COLUMN IF NOT EXISTS email_verified_at DATETIME NULL,
    ADD COLUMN IF NOT EXISTS first_login_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS first_login_verified_at DATETIME NULL;

-- Existing verified customers keep access (no forced first-login OTP).
UPDATE customer_accounts
SET first_login_verified = TRUE,
    first_login_verified_at = COALESCE(first_login_verified_at, CURRENT_TIMESTAMP),
    email_verified_at = COALESCE(email_verified_at, CURRENT_TIMESTAMP)
WHERE email_verified = TRUE
  AND first_login_verified = FALSE;

CREATE TABLE IF NOT EXISTS pending_registrations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    otp_expires_at DATETIME NOT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    last_sent_at DATETIME NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pending_registrations_email (email),
    KEY idx_pending_registrations_expires (otp_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS email_verification_codes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT UNSIGNED NULL,
    email VARCHAR(254) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    verification_type ENUM('registration', 'first_login') NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT UNSIGNED NOT NULL DEFAULT 0,
    is_used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_at DATETIME NULL,
    KEY idx_evc_email_type (email, verification_type),
    KEY idx_evc_customer (customer_id),
    KEY idx_evc_expires (expires_at),
    CONSTRAINT fk_evc_customer
        FOREIGN KEY (customer_id) REFERENCES customer_accounts(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
