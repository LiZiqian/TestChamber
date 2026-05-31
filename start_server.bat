@echo off
setlocal EnableExtensions

REM TestChamber V6.1 Intranet Server Starter
REM Fixed port: 9398
REM Prefer Miniforge/Conda Python, then Windows Python Launcher, then PATH.

cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHON_LABEL="

if defined PYTHON_EXE call :try_python_path "%PYTHON_EXE%"
if defined CONDA_PREFIX call :try_python_path "%CONDA_PREFIX%\python.exe"
call :try_python_path "%USERPROFILE%\miniforge3\python.exe"
call :try_python_path "%USERPROFILE%\AppData\Local\miniforge3\python.exe"
call :try_python_path "%LOCALAPPDATA%\miniforge3\python.exe"
call :try_python_path "C:\ProgramData\miniforge3\python.exe"
call :try_python_path "C:\Miniforge3\python.exe"

if not defined PYTHON_CMD (
    py -3 -c "import sys" >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON_CMD=py -3"
        set "PYTHON_LABEL=py -3"
    )
)

if not defined PYTHON_CMD (
    python -c "import sys" >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON_CMD=python"
        set "PYTHON_LABEL=python"
    )
)

echo ============================================
echo TestChamber V6.1 Intranet Server
echo Current folder:
echo %CD%
echo Python:
if defined PYTHON_CMD (
    %PYTHON_CMD% --version
    echo Using:
    echo %PYTHON_LABEL%
) else (
    echo Not found
)
echo Port:
echo 9398
echo ============================================
echo.

if not exist "server.py" (
    echo [ERROR] server.py was not found in this folder.
    pause
    exit /b 1
)

if not exist "index.html" (
    echo [ERROR] index.html was not found in this folder.
    pause
    exit /b 1
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found.
    echo If Miniforge is installed, start this file from "Miniforge Prompt",
    echo or set PYTHON_EXE to your Miniforge python.exe path before running.
    echo Example:
    echo set PYTHON_EXE=C:\Users\your_name\miniforge3\python.exe
    echo If Windows Store python aliases are enabled, disable them in:
    echo Settings ^> Apps ^> Advanced app settings ^> App execution aliases
    pause
    exit /b 1
)

%PYTHON_CMD% server.py --host 0.0.0.0 --port 9398

echo.
echo Server stopped or failed to start.
pause
exit /b %ERRORLEVEL%

:try_python_path
if defined PYTHON_CMD exit /b 0
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "import sys" >nul 2>nul
if %ERRORLEVEL% NEQ 0 exit /b 1
set "PYTHON_CMD="%~1""
set "PYTHON_LABEL=%~1"
exit /b 0
