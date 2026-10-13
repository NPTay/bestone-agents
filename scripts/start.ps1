# Chạy chương trình Bestone ngay bây giờ (dùng tác vụ đã đăng ký bằng install_autostart.ps1).
# Cách chạy: powershell -ExecutionPolicy Bypass -File scripts\start.ps1

$ErrorActionPreference = "Stop"
$TaskName = "Bestone Fanpage"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Task) {
    Write-Host "Chưa đăng ký '$TaskName'. Hãy chạy scripts\install_autostart.ps1 trước." -ForegroundColor Red
    exit 1
}

Start-ScheduledTask -TaskName $TaskName
Write-Host "Đã bật chương trình. Trang điều khiển: http://127.0.0.1:8765/" -ForegroundColor Green
Write-Host "(Nếu chương trình đang chạy rồi thì bản mới sẽ tự thoát, không chạy trùng.)"
