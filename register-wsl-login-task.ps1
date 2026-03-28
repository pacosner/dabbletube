param(
  [string]$TaskName = "Start WSL At Login",
  [string]$DistroName = "",
  [string]$WslUser = "pacos",
  [switch]$RunNow
)

$wslExe = Join-Path $env:SystemRoot "System32\wsl.exe"
$bashCommand = 'systemctl start cron >/dev/null 2>&1 || true'

if (-not (Test-Path $wslExe)) {
  throw "wsl.exe not found at $wslExe"
}

$wslArgs = @()
if ($DistroName) {
  $wslArgs += @("--distribution", $DistroName)
}
if ($WslUser) {
  $wslArgs += @("--user", $WslUser)
}
$wslArgs += @("bash", "-lc", "`"$bashCommand`"")

$action = New-ScheduledTaskAction -Execute $wslExe -Argument ($wslArgs -join " ")
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Force | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "Action: $wslExe $($wslArgs -join ' ')"

if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "Started task immediately."
}
