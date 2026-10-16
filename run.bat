@echo off
cd /d "%~dp0"

call ".venv\Scripts\activate.bat"

python manage.py collectstatic --noinput
if errorlevel 1 (
    echo Failed to collect static files.
    pause
    exit /b 1
)

python manage.py runserver

pause