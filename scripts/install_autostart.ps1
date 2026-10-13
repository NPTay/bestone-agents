# Đăng ký chương trình Bestone tự chạy (không hiện cửa sổ) mỗi khi đăng nhập Windows.
# Cách chạy: powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1

$ErrorActionPreference = "Stop"
$TaskName = "Bestone Fanpage"
$Repo = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Repo ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Pythonw)) {
    Write-Host "Chưa có $Pythonw. Hãy chạy scripts\setup.ps1 trước." -ForegroundColor Red
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m app" -WorkingDirectory $Repo
# Tên đầy đủ dạng MÁY\người_dùng (thiếu phần MÁY thì Windows báo "The parameter is incorrect").
$UserId = "$env:USERDOMAIN\$env:USERNAME"
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
# Chạy bằng tài khoản đang đăng nhập, quyền thường (không cần quyền quản trị).
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
# Tự khởi động lại tối đa 3 lần, mỗi lần cách 5 phút; không giới hạn thời gian chạy.
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Chương trình quản lý Fanpage Bestone" -Force | Out-Null

Write-Host "Đã đăng ký '$TaskName': chương trình sẽ tự chạy mỗi khi đăng nhập Windows." -ForegroundColor Green
Write-Host "Muốn chạy ngay bây giờ: powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
