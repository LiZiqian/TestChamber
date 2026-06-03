$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "============================================"
Write-Host "TestChamber V7 Intranet Server"
Write-Host "Current folder: $PWD"
Write-Host "Port: 9398"
Write-Host "============================================"
Write-Host ""

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

function Write-WhereDiagnostic {
    param([string]$CommandName)

    Write-Host "  where $CommandName`:"
    $items = & where.exe $CommandName 2>$null
    if ($LASTEXITCODE -eq 0 -and $items) {
        foreach ($item in $items) {
            Write-Host "    $item"
        }
    } else {
        Write-Host "    <not found>"
    }
}

function Write-PythonDiagnostics {
    Write-Host "Python diagnostics:"
    if ($env:PYTHON_EXE) {
        Write-Host "  PYTHON_EXE=$env:PYTHON_EXE"
    } else {
        Write-Host "  PYTHON_EXE=<not set>"
    }
    if ($env:CONDA_PREFIX) {
        Write-Host "  CONDA_PREFIX=$env:CONDA_PREFIX"
    } else {
        Write-Host "  CONDA_PREFIX=<not set>"
    }
    Write-WhereDiagnostic "python"
    Write-WhereDiagnostic "py"
    Write-Host ""
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

function Use-PythonCommand {
    param([string[]]$Command)

    if ($script:pythonCommand) {
        return
    }
    if (-not $Command -or $Command.Length -eq 0) {
        return
    }
    if (Test-PythonCommand $Command) {
        $script:pythonCommand = $Command
        $script:pythonDisplay = ($Command -join " ")
    }
}

function Find-Python {
    Use-PythonPath $env:PYTHON_EXE
    if ($env:CONDA_PREFIX) {
        Use-PythonPath (Join-Path $env:CONDA_PREFIX "python.exe")
    }

    $baseDirs = @(
        $env:USERPROFILE,
        $env:LOCALAPPDATA,
        "C:\ProgramData",
        "C:\",
        "D:\"
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    $distros = @(
        "miniforge3",
        "Miniforge3",
        "mambaforge",
        "Mambaforge",
        "anaconda3",
        "Anaconda3"
    )

    foreach ($baseDir in $baseDirs) {
        foreach ($distro in $distros) {
            Use-PythonPath (Join-Path (Join-Path $baseDir $distro) "python.exe")
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        Use-PythonCommand @("py", "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Use-PythonCommand @("python")
    }
}

function Normalize-UserPythonPath {
    param([string]$Path)

    if ($null -eq $Path) {
        return ""
    }
    $clean = $Path.Trim()
    if ($clean.Length -ge 2) {
        $first = $clean[0]
        $last = $clean[$clean.Length - 1]
        if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
            $clean = $clean.Substring(1, $clean.Length - 2).Trim()
        }
    }
    return $clean
}

function Prompt-PythonPath {
    Write-Host "[ERROR] Python 3 was not found automatically."
    Write-Host "If Miniforge, Mambaforge, Anaconda, or Python is installed, enter or drag python.exe here."
    Write-Host "You can also enter the folder that contains python.exe."
    Write-Host "Enter Q to quit."
    Write-Host ""

    while (-not $script:pythonCommand) {
        $inputPath = Normalize-UserPythonPath (Read-Host "python.exe path")
        if ([string]::IsNullOrWhiteSpace($inputPath)) {
            Write-Host "[ERROR] Empty path. Please try again."
            continue
        }
        if ($inputPath -ieq "q") {
            Write-Host "User cancelled."
            return
        }

        $candidate = $inputPath
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            $candidate = Join-Path $candidate "python.exe"
        }

        Use-PythonPath $candidate
        if (-not $script:pythonCommand) {
            Write-Host "[ERROR] This is not a working Python 3 executable:"
            Write-Host "  $inputPath"
            Write-Host "Please enter a valid python.exe path, or Q to quit."
            Write-Host ""
        }
    }
}

Write-PythonDiagnostics
Find-Python

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

if (-not $pythonCommand) {
    Prompt-PythonPath
}

if ($pythonCommand) {
    $pythonArgs = @()
    if ($pythonCommand.Length -gt 1) {
        $pythonArgs = $pythonCommand[1..($pythonCommand.Length - 1)]
    }
    Write-Host ""
    Write-Host "Python:"
    & $pythonCommand[0] @pythonArgs --version
    Write-Host "Using:"
    Write-Host $pythonDisplay
    Write-Host ""
    & $pythonCommand[0] @pythonArgs server.py --host 0.0.0.0 --port 9398
} else {
    Write-Host "[ERROR] Python 3 was not found."
}

Read-Host "Press Enter to exit"
