# Installs Hush for the current user: venv, Discord app keys, startup shortcut.
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [-Uninstall]
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Hush.lnk"

function Stop-Hush {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match [regex]::Escape("$dir\hush.py") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

if ($Uninstall) {
    Stop-Hush
    Remove-Item $lnk -ErrorAction SilentlyContinue
    Write-Host "Removed. Your Discord keys stay in your user env vars and the login token in $env:LOCALAPPDATA\Hush."
    return
}

# 1. Python env
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.10+ is required: https://www.python.org/downloads/" }
if (-not (Test-Path "$dir\.venv")) { & python -m venv "$dir\.venv" }
$ErrorActionPreference = 'Continue'
& "$dir\.venv\Scripts\python.exe" -m ensurepip *> $null  # venvs made by uv ship without pip
$ErrorActionPreference = 'Stop'
& "$dir\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "$dir\requirements.txt"
if ($LASTEXITCODE) { throw "Installing dependencies failed." }
& "$dir\.venv\Scripts\python.exe" "$dir\test_hush.py"

# 2. Discord app keys, stored as user env vars, never written to this folder
if (-not [Environment]::GetEnvironmentVariable('DISCORD_CLIENT_ID', 'User')) {
    $id = Read-Host 'Discord Client ID'
    if ($id -notmatch '^\d{17,20}$') { throw "That does not look like a Client ID (17 to 20 digits)." }
    [Environment]::SetEnvironmentVariable('DISCORD_CLIENT_ID', $id, 'User')
}
if (-not [Environment]::GetEnvironmentVariable('DISCORD_CLIENT_SECRET', 'User')) {
    $s = [Net.NetworkCredential]::new('', (Read-Host 'Discord Client Secret' -AsSecureString)).Password
    if (-not $s) { throw "No secret entered." }
    [Environment]::SetEnvironmentVariable('DISCORD_CLIENT_SECRET', $s, 'User')
}

# 3. Start at login, and now
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sh.TargetPath = "$dir\.venv\Scripts\pythonw.exe"
$sh.Arguments = "`"$dir\hush.py`""
$sh.WorkingDirectory = $dir
$sh.Save()
Stop-Hush
Start-Process "$dir\.venv\Scripts\pythonw.exe" "`"$dir\hush.py`"" -WorkingDirectory $dir
Write-Host "Hush is running in the tray. Dictate once and click Authorize in Discord."
