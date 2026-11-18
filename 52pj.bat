@echo off
rem 52pj - thin launcher; all logic lives in pojie.py
rem Usage: 52pj forums   (this bat is just a shortcut)
setlocal
set "SELF=%~dp0pojie.py"
where py >nul 2>&1 && (py -3 "%SELF%" %* & endlocal & exit /b)
where python >nul 2>&1 && (python "%SELF%" %* & endlocal & exit /b)
if exist "H:\software\ide\anaconda\python.exe" (
  "H:\software\ide\anaconda\python.exe" "%SELF%" %* & endlocal & exit /b
)
echo.
echo [x] Python not found. Install Python 3.8+ from https://www.python.org/downloads/windows/
echo     or run directly:  python "%SELF%" %*
echo.
endlocal
exit /b 1
