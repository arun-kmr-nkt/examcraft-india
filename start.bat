@echo off
title ExamCraft India - AI Exam Platform

echo.
echo  =====================================================
echo         ExamCraft India - AI-Powered Exam Platform
echo  =====================================================
echo.

:: Check if API key is set
if "%GOOGLE_API_KEY%"=="" (
    echo  [INFO] GOOGLE_API_KEY is not set.
    echo  Get a FREE key at: https://aistudio.google.com/apikey
    echo.
    set /p APIKEY="  Enter your Google AI API key: "
    set GOOGLE_API_KEY=%APIKEY%
    echo.
)

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

:: Install dependencies if needed
if not exist "venv\" (
    echo  Creating virtual environment...
    python -m venv venv
    echo  Installing dependencies...
    venv\Scripts\pip install -r requirements.txt --quiet
    echo  Dependencies installed!
    echo.
)

echo  Starting ExamCraft India...
echo  Open your browser at: http://localhost:5000
echo  Press Ctrl+C to stop the server
echo.

:: Activate venv and run app
call venv\Scripts\activate
python app.py

pause
