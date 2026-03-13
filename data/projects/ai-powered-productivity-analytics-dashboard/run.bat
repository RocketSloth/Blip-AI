@echo off
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies. Make sure Python and pip are installed.
    pause
    exit /b 1
)
echo.
echo Starting the app...
python -m uvicorn app.main:app --reload
pause