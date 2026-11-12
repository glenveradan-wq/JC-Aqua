# Loads local .env (gitignored) into this PowerShell session, then starts Flask.
# Usage:
#   .\start-dev.ps1
# Optional:
#   .\start-dev.ps1 -InitDb

param(
    [switch]$InitDb
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "Virtual environment not found. Create it with: py -m venv .venv"
}

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "Created .env from .env.example. Edit .env before relying on SMTP." -ForegroundColor Yellow
}

Get-Content ".\.env" | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        return
    }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    Set-Item -Path "Env:$name" -Value $value
}

if (-not $env:FLASK_SECRET_KEY -or $env:FLASK_SECRET_KEY -like "replace-with-*") {
    $env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
    Write-Host "Generated a temporary FLASK_SECRET_KEY for this session." -ForegroundColor Yellow
}

.\.venv\Scripts\Activate.ps1

if ($InitDb) {
    python init_db.py
}

Write-Host "SMTP_ENABLED=$($env:SMTP_ENABLED)  HOST=$($env:SMTP_HOST)  USER=$($env:SMTP_USERNAME)" -ForegroundColor Cyan
Write-Host "Starting app at http://127.0.0.1:5000/" -ForegroundColor Cyan
python app.py
