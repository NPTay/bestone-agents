# Cài đặt lần đầu: tạo môi trường Python, cài chương trình, tạo file .env.
# Cách chạy (PowerShell, ở thư mục gốc dự án):
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Đang tạo môi trường Python (.venv)..."
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Không tạo được .venv. Hãy cài Python 3.12 từ python.org rồi chạy lại." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Đang cài chương trình (có thể mất vài phút)..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Cài đặt bị lỗi. Kiểm tra kết nối mạng rồi chạy lại." -ForegroundColor Red
    exit 1
}

$EnvFile = Join-Path $Repo ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Repo ".env.example") $EnvFile
    Write-Host "Đã tạo file .env từ .env.example."
} else {
    Write-Host "File .env đã có, giữ nguyên."
}

Write-Host ""
Write-Host "Cài đặt xong. Các bước tiếp theo:" -ForegroundColor Green
Write-Host "  1. Mở file .env bằng Notepad, điền ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, META_APP_ID, META_APP_SECRET, META_PAGE_ID."
Write-Host "  2. Gửi /start cho bot Telegram, rồi chạy:"
Write-Host "       .venv\Scripts\python -m app.cli.setup_tools telegram-chat-id"
Write-Host "     và điền số chat id vào TELEGRAM_ADMIN_CHAT_ID trong .env."
Write-Host "  3. Lấy token Trang Facebook:"
Write-Host "       .venv\Scripts\python -m app.cli.setup_tools meta-token --user-token <token ngắn hạn>"
Write-Host "  4. Kiểm tra mọi thứ:"
Write-Host "       .venv\Scripts\python -m app.cli.setup_tools check"
Write-Host "  5. Cho chương trình tự chạy khi đăng nhập Windows:"
Write-Host "       powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1"
