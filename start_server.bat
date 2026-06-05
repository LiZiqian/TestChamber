@echo off
setlocal EnableExtensions

REM TestChamber V7 Intranet Server Starter
REM Default port: 9398
REM Prefer explicit Python paths, Conda/Miniforge installs, then Windows Python Launcher, then PATH.

cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHON_LABEL="
set "DEFAULT_PORT=9398"
set "SERVER_PORT=%DEFAULT_PORT%"

echo ============================================
echo TestChamber V7 Intranet Server
echo Current folder:
echo %CD%
echo Default port:
echo %DEFAULT_PORT%
echo ============================================
echo.

call :prompt_server_port
if errorlevel 1 exit /b 1
echo.
echo Selected port:
echo %SERVER_PORT%
echo.

call :print_diagnostics
call :discover_python

if not exist "backend\server.py" (
    echo [ERROR] backend\server.py was not found in this folder.
    pause
    exit /b 1
)

if not exist "frontend\index.html" (
    echo [ERROR] frontend\index.html was not found in this folder.
    pause
    exit /b 1
)

if not defined PYTHON_CMD call :prompt_python_path

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found.
    pause
    exit /b 1
)

echo.
echo Python:
%PYTHON_CMD% --version
echo Using:
echo %PYTHON_LABEL%
echo.

%PYTHON_CMD% -m backend.server --host 0.0.0.0 --port %SERVER_PORT%

echo.
echo Server stopped or failed to start.
pause
exit /b %ERRORLEVEL%

:prompt_server_port
:prompt_server_port_choice
set "USE_DEFAULT_PORT="
set /p "USE_DEFAULT_PORT=Use default port %DEFAULT_PORT%? [Y/n]: "
call :normalize_input_path USE_DEFAULT_PORT

if not defined USE_DEFAULT_PORT (
    set "SERVER_PORT=%DEFAULT_PORT%"
    call :warn_if_port_in_use
    exit /b 0
)

if /I "%USE_DEFAULT_PORT%"=="Y" (
    set "SERVER_PORT=%DEFAULT_PORT%"
    call :warn_if_port_in_use
    exit /b 0
)
if /I "%USE_DEFAULT_PORT%"=="YES" (
    set "SERVER_PORT=%DEFAULT_PORT%"
    call :warn_if_port_in_use
    exit /b 0
)
if /I "%USE_DEFAULT_PORT%"=="N" goto prompt_custom_port
if /I "%USE_DEFAULT_PORT%"=="NO" goto prompt_custom_port
if /I "%USE_DEFAULT_PORT%"=="Q" (
    echo User cancelled.
    exit /b 1
)

echo Please enter Y to use %DEFAULT_PORT%, N to set another port, or Q to quit.
goto prompt_server_port_choice

:prompt_custom_port
echo.
echo Enter a server port.
echo Valid TCP ports are 1-65535. This launcher accepts 1024-49151 to avoid system and ephemeral ports.
echo Avoid common ports when possible: 3000, 3306, 5000, 5432, 6379, 8000, 8080, 8888, 9000.
echo Enter Q to quit.
echo.

:prompt_custom_port_loop
set "SERVER_PORT_INPUT="
set /p "SERVER_PORT_INPUT=Port: "
call :normalize_input_path SERVER_PORT_INPUT

if not defined SERVER_PORT_INPUT (
    echo [ERROR] Empty port. Please try again.
    goto prompt_custom_port_loop
)

if /I "%SERVER_PORT_INPUT%"=="Q" (
    echo User cancelled.
    exit /b 1
)

call :validate_port "%SERVER_PORT_INPUT%"
if errorlevel 1 goto prompt_custom_port_loop

set "SERVER_PORT=%SERVER_PORT_INPUT%"
call :is_discouraged_port "%SERVER_PORT%"
if not errorlevel 1 (
    echo [WARNING] Port %SERVER_PORT% is commonly used by other tools.
    set "KEEP_COMMON_PORT="
    set /p "KEEP_COMMON_PORT=Use it anyway? [y/N]: "
    call :normalize_input_path KEEP_COMMON_PORT
    if /I not "%KEEP_COMMON_PORT%"=="Y" goto prompt_custom_port_loop
)

call :warn_if_port_in_use
exit /b 0

:validate_port
set "PORT_TO_CHECK=%~1"
echo(%PORT_TO_CHECK%| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
    echo [ERROR] Port must be a number.
    exit /b 1
)
set "PORT_NUMBER="
set /a PORT_NUMBER=%PORT_TO_CHECK% >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Port must be a valid number.
    exit /b 1
)
if %PORT_NUMBER% LSS 1024 (
    echo [ERROR] Port must be 1024 or higher for normal user startup.
    exit /b 1
)
if %PORT_NUMBER% GTR 49151 (
    echo [ERROR] Port must be 49151 or lower to avoid dynamic ephemeral ports.
    exit /b 1
)
exit /b 0

:is_discouraged_port
for %%P in (3000 3306 5000 5432 6379 8000 8080 8888 9000) do (
    if "%~1"=="%%P" exit /b 0
)
exit /b 1

:warn_if_port_in_use
call :is_port_in_use "%SERVER_PORT%"
if not errorlevel 1 (
    echo [WARNING] Port %SERVER_PORT% already appears to be in use. Startup may fail unless the existing service is stopped.
)
exit /b 0

:is_port_in_use
netstat -ano | findstr /r /c:":%~1 .*LISTENING" >nul 2>nul
exit /b %ERRORLEVEL%

:print_diagnostics
echo Python diagnostics:
if defined PYTHON_EXE (
    echo   PYTHON_EXE=%PYTHON_EXE%
) else (
    echo   PYTHON_EXE=^<not set^>
)
if defined CONDA_PREFIX (
    echo   CONDA_PREFIX=%CONDA_PREFIX%
) else (
    echo   CONDA_PREFIX=^<not set^>
)
call :print_where python
call :print_where py
echo.
exit /b 0

:print_where
echo   where %~1:
where %~1 2>nul
if errorlevel 1 echo     ^<not found^>
exit /b 0

:discover_python
if defined PYTHON_EXE call :try_python_path "%PYTHON_EXE%"
if defined CONDA_PREFIX call :try_python_path "%CONDA_PREFIX%\python.exe"

for %%D in (miniforge3 Miniforge3 mambaforge Mambaforge anaconda3 Anaconda3) do (
    call :try_python_path "%USERPROFILE%\%%D\python.exe"
    call :try_python_path "%USERPROFILE%\AppData\Local\%%D\python.exe"
    if defined LOCALAPPDATA call :try_python_path "%LOCALAPPDATA%\%%D\python.exe"
    call :try_python_path "C:\ProgramData\%%D\python.exe"
    call :try_python_path "C:\%%D\python.exe"
    call :try_python_path "D:\%%D\python.exe"
)

call :try_python_command py -3
call :try_python_command python
exit /b 0

:try_python_command
if defined PYTHON_CMD exit /b 0
if "%~1"=="" exit /b 1
if "%~2"=="" (
    %~1 -c "import sys" >nul 2>nul
) else (
    %~1 %~2 -c "import sys" >nul 2>nul
)
if errorlevel 1 exit /b 1
if "%~2"=="" (
    set "PYTHON_CMD=%~1"
    set "PYTHON_LABEL=%~1"
) else (
    set "PYTHON_CMD=%~1 %~2"
    set "PYTHON_LABEL=%~1 %~2"
)
exit /b 0

:try_python_path
if defined PYTHON_CMD exit /b 0
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
if not exist "%~1\*" (
    "%~1" -c "import sys" >nul 2>nul
    if errorlevel 1 exit /b 1
    set "PYTHON_CMD="%~1""
    set "PYTHON_LABEL=%~1"
    exit /b 0
)
exit /b 1

:prompt_python_path
echo [ERROR] Python 3 was not found automatically.
echo If Miniforge, Mambaforge, Anaconda, or Python is installed, enter or drag python.exe here.
echo You can also enter the folder that contains python.exe.
echo Enter Q to quit.
echo.

:prompt_python_path_loop
set "USER_PYTHON_PATH="
set /p "USER_PYTHON_PATH=python.exe path: "
call :normalize_input_path USER_PYTHON_PATH

if not defined USER_PYTHON_PATH (
    echo [ERROR] Empty path. Please try again.
    goto prompt_python_path_loop
)

if /I "%USER_PYTHON_PATH%"=="Q" (
    echo User cancelled.
    exit /b 1
)

if exist "%USER_PYTHON_PATH%\python.exe" (
    call :try_python_path "%USER_PYTHON_PATH%\python.exe"
) else (
    call :try_python_path "%USER_PYTHON_PATH%"
)

if defined PYTHON_CMD exit /b 0

echo [ERROR] This is not a working Python 3 executable:
echo   %USER_PYTHON_PATH%
echo Please enter a valid python.exe path, or Q to quit.
echo.
goto prompt_python_path_loop

:normalize_input_path
setlocal EnableDelayedExpansion
set "VALUE=!%~1!"
for /f "tokens=* delims= " %%A in ("!VALUE!") do set "VALUE=%%A"
:normalize_trim_right
if "!VALUE:~-1!"==" " (
    set "VALUE=!VALUE:~0,-1!"
    goto normalize_trim_right
)
if "!VALUE:~0,1!"=="""" set "VALUE=!VALUE:~1!"
if "!VALUE:~-1!"=="""" set "VALUE=!VALUE:~0,-1!"
endlocal & set "%~1=%VALUE%"
exit /b 0
