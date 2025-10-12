@echo off
echo ========================================
echo    Well-Bot Frontend Server Startup
echo ========================================
echo.

REM Check if frontend directory exists
if not exist "frontend" (
    echo ERROR: Frontend directory not found!
    echo Please ensure the frontend directory exists.
    pause
    exit /b 1
)

REM Navigate to frontend directory
cd frontend

REM Check if node_modules exists
if not exist "node_modules" (
    echo Installing frontend dependencies...
    npm install
    if errorlevel 1 (
        echo ERROR: Failed to install frontend dependencies!
        pause
        exit /b 1
    )
)

REM Check if package.json exists
if not exist "package.json" (
    echo ERROR: package.json not found in frontend directory!
    pause
    exit /b 1
)

REM Start the frontend development server
echo.
echo Starting Well-Bot frontend development server...
echo Frontend will be available at: http://localhost:5173
echo Press Ctrl+C to stop the server
echo.
echo ========================================
echo.

npm run dev

echo.
echo ========================================
echo Frontend server stopped.
pause
