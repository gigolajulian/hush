# Builds Hush.exe and installs it for the current user, no admin: %LOCALAPPDATA%\Programs\Hush, Start menu,
# start at login, and an entry in Settings > Installed apps. Asks for the Discord app keys once.
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [-Uninstall]
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$app = "$env:LOCALAPPDATA\Programs\Hush"
$programs = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

if ($Uninstall) { & "$dir\uninstall.ps1"; return }

# 1. Build the exe
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.10+ is required to build Hush: https://www.python.org/downloads/" }
if (-not (Test-Path "$dir\.venv")) { & python -m venv "$dir\.venv" }
$py = "$dir\.venv\Scripts\python.exe"
$ErrorActionPreference = 'Continue'
& $py -m ensurepip *> $null  # venvs made by uv ship without pip
$ErrorActionPreference = 'Stop'
& $py -m pip install -q --disable-pip-version-check -r "$dir\requirements.txt" pyinstaller
if ($LASTEXITCODE) { throw "Installing dependencies failed." }
& $py "$dir\test_hush.py"
if ($LASTEXITCODE) { throw "Self-check failed." }
New-Item -ItemType Directory -Force "$dir\build" | Out-Null
$ErrorActionPreference = 'Continue'  # PyInstaller logs to stderr, which PowerShell 5.1 would treat as an error
& $py "$dir\scripts\build.py" *> "$dir\build\build.log"
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -or -not (Test-Path "$dir\dist\Hush.exe")) { throw "Build failed, see build\build.log." }
$version = (Get-Item "$dir\dist\Hush.exe").VersionInfo.ProductVersion

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

# 3. Stop any running Hush: the installed exe, or an older copy that ran hush.py with pythonw
Get-CimInstance Win32_Process -Filter "Name='Hush.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.ExecutablePath -like "$app\*" -or $_.CommandLine -match [regex]::Escape("$dir\hush.py") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Wait-Process -Id $_.ProcessId -Timeout 5 -ErrorAction SilentlyContinue }

# 4. Copy the app
New-Item -ItemType Directory -Force $app | Out-Null
Copy-Item "$dir\dist\Hush.exe", "$dir\uninstall.ps1" $app -Force
Remove-Item "$app\Hush.exe.old" -ErrorAction SilentlyContinue

# 5. Start menu, and start at login through the HKCU Run key (the tray's Start with Windows item toggles it)
Remove-Item "$programs\Startup\Hush.lnk" -ErrorAction SilentlyContinue  # older installs started from a Startup shortcut
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' Hush "`"$app\Hush.exe`""
$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in @("$programs\Hush.lnk")) {
    $sh = $shell.CreateShortcut($lnk)
    $sh.TargetPath = "$app\Hush.exe"
    $sh.Arguments = ''
    $sh.WorkingDirectory = $app
    $sh.IconLocation = "$app\Hush.exe,0"
    $sh.Description = 'Mutes Discord while you dictate to Claude'
    $sh.Save()
}

# 6. Settings > Installed apps
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Hush'
New-Item $key -Force | Out-Null
$values = @{
    DisplayName     = 'Hush'
    DisplayVersion  = $version
    Publisher       = 'Julian Gigola'
    DisplayIcon     = "$app\Hush.exe"
    InstallLocation = $app
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$app\uninstall.ps1`""
    URLInfoAbout    = 'https://github.com/loupedesk/hush'
}
foreach ($k in $values.Keys) { Set-ItemProperty $key $k $values[$k] }
foreach ($k in 'NoModify', 'NoRepair') { Set-ItemProperty $key $k 1 -Type DWord }
Set-ItemProperty $key EstimatedSize ([int]((Get-Item "$app\Hush.exe").Length / 1KB)) -Type DWord

# 7. Start now
Start-Process "$app\Hush.exe" -WorkingDirectory $app
Write-Host "Hush $version is installed and running in the tray. Dictate once in a voice call and click Authorize in Discord if asked."
