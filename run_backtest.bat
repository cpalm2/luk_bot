@echo off
REM 5-year backtest of luk_bot vs QQQ buy-and-hold. Double-click to run.
REM Needs Python 3.10+ for Windows (python.org, tick "Add python.exe to PATH").
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (set PY=python) else (set PY=py)

echo Installing requirements...
%PY% -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Could not run Python. Install it from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)

echo Running the backtest (downloads ~150 stocks, takes a few minutes)...
%PY% -m luk_bot backtest --universe universes\ndx_growth.txt --period 10y --start 2021-10-25 --quiet --benchmark QQQ > backtest_report.txt 2>&1
type backtest_report.txt
echo.
echo Results saved in this folder: backtest_report.txt, backtest_equity.png, backtest_trades.csv, backtest_fills.csv
pause
