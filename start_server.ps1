$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "============================================"
Write-Host "TestChamber V6.1 Intranet Server"
Write-Host "Current folder: $PWD"
Write-Host "Port: 9398"
Write-Host "============================================"

$pythonCommand = $null
$pythonDisplay = $null

function Test-PythonCommand {
    param([string[]]$Command)

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $exe = $Command[0]
        $args = @()
        if ($Command.Length -gt 1) {
            $args = $Command[1..($Command.Length - 1)]
        }
        & $exe @args -c "import sys" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldPreference
    }
}

function Use-PythonPath {
    param([string]$Path)

    if ($script:pythonCommand) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }
    if (Test-PythonCommand @($Path)) {
        $script:pythonCommand = @($Path)
        $script:pythonDisplay = $Path
    }
}

Use-PythonPath $env:PYTHON_EXE
if ($env:CONDA_PREFIX) {
    Use-PythonPath (Join-Path $env:CONDA_PREFIX "python.exe")
}

$commonPythonPaths = @(
    (Join-Path $env:USERPROFILE "miniforge3\python.exe"),
    (Join-Path $env:USERPROFILE "AppData\Local\miniforge3\python.exe"),
    (Join-Path $env:LOCALAPPDATA "miniforge3\python.exe"),
    "C:\ProgramData\miniforge3\python.exe",
    "C:\Miniforge3\python.exe"
)
foreach ($path in $commonPythonPaths) {
    Use-PythonPath $path
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand -and $pyLauncher) {
    if (Test-PythonCommand @("py", "-3")) {
        $pythonCommand = @("py", "-3")
        $pythonDisplay = "py -3"
    }
}

if (-not $pythonCommand) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        if (Test-PythonCommand @("python")) {
            $pythonCommand = @("python")
            $pythonDisplay = "python"
        }
    }
}

if (-not (Test-Path ".\server.py")) {
    Write-Host "[ERROR] server.py was not found in this folder."
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path ".\index.html")) {
    Write-Host "[ERROR] index.html was not found in this folder."
    Read-Host "Press Enter to exit"
    exit 1
}

if ($pythonCommand) {
    $pythonArgs = @()
    if ($pythonCommand.Length -gt 1) {
        $pythonArgs = $pythonCommand[1..($pythonCommand.Length - 1)]
    }
    Write-Host "Python:"
    & $pythonCommand[0] @pythonArgs --version
    Write-Host "Using: $pythonDisplay"
    & $pythonCommand[0] @pythonArgs server.py --host 0.0.0.0 --port 9398
} else {
    Write-Host "[ERROR] Python 3 was not found."
    Write-Host "If Miniforge is installed, start this file from 'Miniforge Prompt',"
    Write-Host "or set PYTHON_EXE to your Miniforge python.exe path before running."
    Write-Host "Example:"
    Write-Host "set PYTHON_EXE=C:\Users\your_name\miniforge3\python.exe"
    Write-Host "If Windows Store python aliases are enabled, disable them in:"
    Write-Host "Settings > Apps > Advanced app settings > App execution aliases"
}

Read-Host "Press Enter to exit"
