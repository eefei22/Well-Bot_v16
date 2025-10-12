@echo off
echo ========================================
echo    Well-Bot Backend Server Startup
echo ========================================
echo.

REM Kill any existing processes on port 8000
echo Checking for existing processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    echo Killing existing process %%a on port 8000...
    taskkill /PID %%a /F >nul 2>&1
)
echo Port 8000 cleared.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: py -3.12 -m venv venv
    echo Then install dependencies: pip install -r backend/requirements.txt
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating Python virtual environment...
call venv\Scripts\activate.bat

REM Verify virtual environment is activated
python -c "import sys; print('Python path:', sys.executable)" 2>nul
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment!
    pause
    exit /b 1
)
echo Virtual environment activated successfully.

REM Check if dependencies are installed
echo Checking dependencies...
python -c "import fastapi, socketio, google.cloud.speech, picovoice, pyaudio, numpy, soundfile, librosa, pydub" 2>nul
if errorlevel 1 (
    echo WARNING: Some dependencies are missing!
    echo Updating pip...
    python -m pip install --upgrade pip
    echo Installing/updating dependencies...
    pip install -r backend/requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies!
        echo Please check your internet connection and try again.
        echo You may need to install some dependencies manually.
        pause
        exit /b 1
    )
    echo Dependencies installed successfully!
) else (
    echo All dependencies are already installed.
)

REM Start the backend server
echo.
echo Starting Well-Bot backend server...
echo Server will be available at: http://localhost:8000
echo Press Ctrl+C to stop the server
echo.
echo ========================================
echo.

python backend/main.py

echo.
echo ========================================
echo Backend server stopped.
pause
