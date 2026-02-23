@echo off
echo ============================================
echo   Cam's Grocery Deals - Finding This Week's Deals
echo ============================================
echo.
python "%~dp0run.py" %*
echo.
if %ERRORLEVEL% NEQ 0 (
    echo Something went wrong. Check the error above.
    echo If Python is not installed, download it from python.org
)
echo   View online: https://camerongeisler.github.io/cams-grocery-deals/
echo.
pause
