@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

if defined HTML_TO_PDF_PYTHON (
    "%HTML_TO_PDF_PYTHON%" "%~dp0html_to_pdf_converter.py"
    set "STATUS=!ERRORLEVEL!"
    goto finished
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%~dp0html_to_pdf_converter.py"
    set "STATUS=!ERRORLEVEL!"
    goto finished
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3 "%~dp0html_to_pdf_converter.py"
    set "STATUS=!ERRORLEVEL!"
    goto finished
)

echo Python 3.10 or later was not found.
echo Set HTML_TO_PDF_PYTHON to the required Python executable.
set "STATUS=1"

:finished
echo.
pause
exit /b !STATUS!
