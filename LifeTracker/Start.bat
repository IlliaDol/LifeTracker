@echo off
REM ---- LifeTracker robust bootstrap ----
setlocal
TITLE LifeTracker - bootstrap

REM 1) Python check
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python not found. Install Python 3.10–3.12 from https://www.python.org/ and tick "Add to PATH".
  pause
  exit /b 1
)

REM 2) Create venv if missing
if not exist "venv\Scripts\python.exe" (
  echo [+] Creating virtual environment...
  python -m venv venv
  if errorlevel 1 (
    echo [!] Failed to create venv.
    pause
    exit /b 1
  )
)

REM 3) Ensure pip is up-to-date
echo [+] Upgrading pip...
call venv\Scripts\python -m pip install --upgrade pip

REM 4) Always install/refresh dependencies (pulls matplotlib if missing)
echo [+] Installing/Updating dependencies from requirements.txt...
call venv\Scripts\pip install -r requirements.txt

REM 5) Extra sanity check for matplotlib (handles old venvs)
echo [+] Verifying matplotlib...
call venv\Scripts\python -c "import matplotlib" 2>nul
if errorlevel 1 (
  echo [!] matplotlib not detected, installing directly...
  call venv\Scripts\pip install matplotlib
)

REM 6) Launch app
echo [+] Launching LifeTracker...
call venv\Scripts\python main.py

echo.
echo [*] Program finished. Press any key to exit.
pause >nul
