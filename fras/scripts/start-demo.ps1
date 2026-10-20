# FRAS demo on Windows: creates a virtualenv, installs packages, builds demo data once, starts the server.
# Run from the "fras" folder:  powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv")) {
    Write-Host "Virtual muhit yaratilmoqda..."
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Aniq versiyalar o'rnatilmadi, oxirgi versiyalar bilan urinilmoqda..."
    & .\.venv\Scripts\python.exe -m pip install starlette uvicorn pydantic PyJWT cryptography numpy onnxruntime Pillow XlsxWriter reportlab openpyxl
}

$env:FRAS_DATA_DIR = "data"
$env:FRAS_DEV_RELAX_MFA = "1"
if (-not (Test-Path "data\fras.db")) {
    & .\.venv\Scripts\python.exe -m fras seed-demo
}
Write-Host ""
Write-Host "Brauzerda oching: http://localhost:8000/app/   (to'xtatish: Ctrl+C)"
& .\.venv\Scripts\python.exe -m fras serve --port 8000
