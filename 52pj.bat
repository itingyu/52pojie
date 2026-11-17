@echo off
rem 52pj - thin launcher; all logic lives in pojie.py
rem Usage: 52pj forums   (this bat is just a shortcut)
setlocal
set "SELF=%~dp0pojie.py"
py -3 "%SELF%" %* & endlocal & exit /b
python "%SELF%" %* & endlocal & exit /b
echo.
echo [x] Python not found. Install Python 3.8+ from https://www.python.org/downloads/windows/
echo     or run directly:  python "%SELF%" %*
echo.
endlocal
exit /b 1
