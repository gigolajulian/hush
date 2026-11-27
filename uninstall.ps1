# Removes the installed Hush app: exe, shortcuts, Installed apps entry. Settings > Installed apps runs this copy.
# Keeps the Discord keys (user env vars) and the login token and settings in %LOCALAPPDATA%\Hush.
$ErrorActionPreference = 'Stop'
$app = "$env:LOCALAPPDATA\Programs\Hush"
$programs = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

Get-CimInstance Win32_Process -Filter "Name='Hush.exe'" |
    Where-Object { $_.ExecutablePath -like "$app\*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Wait-Process -Id $_.ProcessId -Timeout 5 -ErrorAction SilentlyContinue }
Remove-Item "$programs\Startup\Hush.lnk", "$programs\Hush.lnk" -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Hush' -Recurse -ErrorAction SilentlyContinue
Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' Hush -ErrorAction SilentlyContinue
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
Write-Host "Hush removed. Your Discord keys stay in your user env vars, the login token in $env:LOCALAPPDATA\Hush."
