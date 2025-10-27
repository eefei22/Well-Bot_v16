@echo off
REM Start backend with a specific user UUID
REM Usage: start_backend_with_user.bat <user_uuid>

if "%1"=="" (
    echo Usage: start_backend_with_user.bat ^<user_uuid^>
    echo.
    echo Example:
    echo   start_backend_with_user.bat 8517c97f-66ef-4955-86ed-531013d33d3e
    echo.
    echo Or to use default user:
    echo   start_backend_with_user.bat
    exit /b 1
)

echo Setting DEV_USER_ID=%1
set DEV_USER_ID=%1

echo Starting backend for user: %1
echo.

python main.py

