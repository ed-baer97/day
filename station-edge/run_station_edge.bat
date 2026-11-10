@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

:loop
echo [%date% %time%] Запуск станционного узла АГЗС (АСКА-02 -> SQLite -> VPS)...
"%PY_EXE%" -m agzs_edge serve
echo [%date% %time%] Процесс завершился (код %errorlevel%). Перезапуск через 5 секунд...
timeout /t 5 /nobreak >nul
goto loop
