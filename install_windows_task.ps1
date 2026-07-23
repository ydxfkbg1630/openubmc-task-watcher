param(
  [string]$ProjectDir = "F:\openubmc-task-watcher",
  [int]$IntervalMinutes = 5,
  [string]$TaskName = "OpenUBMCInternTaskWatcher",
  [string]$Notify = "toast,wechat,email",
  [string]$EnvFile = ".env",
  [switch]$ShowConsole
)

$ErrorActionPreference = "Stop"
$PythonName = if ($ShowConsole) { "python.exe" } else { "pythonw.exe" }
$Python = Join-Path $ProjectDir ".venv\Scripts\$PythonName"
$Script = Join-Path $ProjectDir "openubmc_task_watcher.py"
$State = Join-Path $ProjectDir "state.json"

if (-not (Test-Path $Python)) {
  throw "Python venv not found: $Python"
}
if (-not (Test-Path $Script)) {
  throw "Watcher script not found: $Script"
}

$Argument = "`"$Script`" --once --state `"$State`" --notify $Notify --env-file `"$EnvFile`""
$Action = New-ScheduledTaskAction -Execute $Python -Argument $Argument -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
  -Description "Watch openUBMC internship task issues and notify on new tasks." -Force | Out-Null

if ($ShowConsole) {
  Write-Host "Installed scheduled task '$TaskName' to run every $IntervalMinutes minute(s) with a console window."
} else {
  Write-Host "Installed scheduled task '$TaskName' to run every $IntervalMinutes minute(s) in the background."
}
