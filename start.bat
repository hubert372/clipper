@echo off
rem Ten plik tylko pobiera aktualizacje i uruchamia run.bat (wlasciwa logika jest w run.bat).
cd /d "%~dp0"
if not exist .git goto run
where git >nul 2>nul || goto run
echo Sprawdzam aktualizacje...
git pull --ff-only -q || echo Nie udalo sie pobrac aktualizacji - uruchamiam obecna wersje.
:run
call run.bat
