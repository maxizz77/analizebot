@echo off
echo ====================================================
echo   Bybit Activity Monitor Telegram Bot - Launching
echo ====================================================

rem Check virtual environment
if not exist venv (
    echo [INFO] Creating Python virtual environment...
    py -m venv venv
)

rem Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate

rem Install/update requirements
echo [INFO] Installing/updating requirements from requirements.txt...
pip install -r requirements.txt

rem Run the bot
echo [INFO] Running bot (bot.py)...
python bot.py

if errorlevel 1 (
    echo.
    echo [WARNING] Bot exited with an error.
    echo Please make sure you set TELEGRAM_BOT_TOKEN in .env file
    echo and you have an active internet connection.
    echo.
)

pause
