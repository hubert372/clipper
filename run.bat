@echo off
chcp 65001 >nul
cd /d "%~dp0"
python --version >nul 2>nul || (echo Brak Pythona. Zainstaluj: winget install Python.Python.3.12 & pause & exit /b)
where ffmpeg >nul 2>nul || (echo Brak FFmpeg. Zainstaluj: winget install Gyan.FFmpeg i otworz to okno ponownie. & pause & exit /b)
if not exist .venv python -m venv .venv
fc /b requirements.txt .venv\req.txt >nul 2>nul && goto app
echo Instaluje zaleznosci...
.venv\Scripts\python -m pip install -q -r requirements.txt || (echo Instalacja zaleznosci nie powiodla sie. & pause & exit /b)
.venv\Scripts\python -m pip install -q pywebview || echo Okno aplikacji niedostepne - panel otworzy sie w przegladarce.
copy /y requirements.txt .venv\req.txt >nul
:app
start "" .venv\Scripts\pythonw.exe app.py
