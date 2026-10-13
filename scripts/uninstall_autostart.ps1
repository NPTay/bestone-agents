# Gỡ chế độ tự chạy của chương trình Bestone.
# Cách chạy: powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1

$ErrorActionPreference = "Stop"
$TaskName = "Bestone Fanpage"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Task) {
    Write-Host "Không có tác vụ '$TaskName', không cần gỡ."
    exit 0
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Đã gỡ '$TaskName'. Chương trình sẽ không tự chạy khi đăng nhập nữa." -ForegroundColor Green
