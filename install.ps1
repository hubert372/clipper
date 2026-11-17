# Clipper - instalator dla Windows. Uruchom w PowerShell:
#   irm https://raw.githubusercontent.com/hubert372/clipper/main/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$dir = Join-Path $HOME 'clipper'

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Have-Python {
  try { return ((& python --version 2>$null | Out-String) -match 'Python 3\.(1[0-9]|[2-9][0-9])') } catch { return $false }
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Install($name, $id) {
  Write-Host "Instaluje: $name..." -ForegroundColor Cyan
  winget install -e --id $id --accept-source-agreements --accept-package-agreements
  Refresh-Path
}

if (-not (Have 'winget')) { throw 'Brak winget. Zaktualizuj "Instalator aplikacji" w Microsoft Store i sprobuj ponownie.' }
if (-not (Have 'git')) { Install 'Git' 'Git.Git' }
if (-not (Have-Python)) { Install 'Python 3.12' 'Python.Python.3.12' }
if (-not (Have 'ffmpeg')) { Install 'FFmpeg' 'Gyan.FFmpeg' }
if (-not (Have 'git')) { throw 'Git nie jest widoczny. Zamknij i otworz PowerShell, potem uruchom komende jeszcze raz.' }
if (-not (Have-Python)) { throw 'Python nie jest widoczny. Zamknij i otworz PowerShell, potem uruchom komende jeszcze raz.' }
if (-not (Have 'ffmpeg')) { throw 'FFmpeg nie jest widoczny. Zamknij i otworz PowerShell, potem uruchom komende jeszcze raz.' }

if (Test-Path (Join-Path $dir '.git')) {
  Write-Host 'Aktualizuje Clipper...' -ForegroundColor Cyan
  git -C $dir pull --ff-only
} elseif (Test-Path $dir) {
  throw "Folder $dir juz istnieje i nie jest instalacja Clippera. Zmien mu nazwe i uruchom komende ponownie."
} else {
  Write-Host "Pobieram Clipper do $dir..." -ForegroundColor Cyan
  git clone https://github.com/hubert372/clipper.git $dir
}
if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie pobrac Clippera z GitHuba.' }

Write-Host 'Instaluje zaleznosci (Streamlink, Whisper) - to moze potrwac kilka minut...' -ForegroundColor Cyan
$py = Join-Path $dir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { python -m venv (Join-Path $dir '.venv') }
& $py -m pip install -q -r (Join-Path $dir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Instalacja zaleznosci nie powiodla sie.' }
Copy-Item (Join-Path $dir 'requirements.txt') (Join-Path $dir '.venv\req.txt') -Force

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Clipper.lnk'))
$lnk.TargetPath = Join-Path $dir 'start.bat'
$lnk.WorkingDirectory = $dir
$lnk.Save()

Write-Host 'Gotowe. Na pulpicie jest skrot "Clipper". Uruchamiam...' -ForegroundColor Green
Start-Process (Join-Path $dir 'start.bat') -WorkingDirectory $dir
