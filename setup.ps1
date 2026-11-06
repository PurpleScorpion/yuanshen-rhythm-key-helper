param(
    [string]$Python = '',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$venvPath = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$versionProbe = "import sys,struct; ok=(3,12)<=sys.version_info[:2]<(3,15) and struct.calcsize('P')==8 and sys.implementation.name=='cpython'; sys.exit(0 if ok else 1)"

function Test-Interpreter {
    param([string]$Executable, [string[]]$Prefix = @(), [switch]$VirtualEnvironment)
    try {
        $probe = $versionProbe
        if ($VirtualEnvironment) {
            $probe = $probe.Replace('if ok else', 'if ok and sys.prefix != sys.base_prefix else')
        }
        & $Executable @Prefix -c $probe *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-BasePython {
    if ($Python) {
        if (-not (Test-Interpreter -Executable $Python)) {
            throw 'The specified Python must be 64-bit CPython 3.12, 3.13, or 3.14.'
        }
        return $Python
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.14', '-3.13', '-3.12')) {
            if (Test-Interpreter -Executable $launcher.Source -Prefix @($version)) {
                return (& $launcher.Source $version -c 'import sys; print(sys.executable)')
            }
        }
    }
    $candidates = @()
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch '\\WindowsApps\\') {
            $candidates += $command.Source
        }
    }
    foreach ($version in @('314', '313', '312')) {
        if ($env:LOCALAPPDATA) {
            $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"
        }
        if ($env:ProgramFiles) {
            $candidates += Join-Path $env:ProgramFiles "Python$version\python.exe"
        }
    }
    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate) -and (Test-Interpreter -Executable $candidate)) {
            return $candidate
        }
    }
    throw 'No supported Python found. Install 64-bit Python 3.14 from https://www.python.org/downloads/windows/ (include the Python launcher), then run setup.cmd again.'
}

try {
    $usable = (Test-Path -LiteralPath $venvPython) -and
        (Test-Interpreter -Executable $venvPython -VirtualEnvironment)
    if ($CheckOnly) {
        if (-not $usable) { exit 1 }
        & $venvPython -c 'import cv2, mss, numpy' *> $null
        exit $LASTEXITCODE
    }
    if (-not $usable) {
        # Find a working base before moving anything. Never delete an old environment.
        $basePython = Find-BasePython
        Write-Host "Using Python: $basePython"
        if (Test-Path -LiteralPath $venvPath) {
            $item = Get-Item -LiteralPath $venvPath -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'The .venv path is a link. Rename it manually before running setup.'
            }
            $resolvedSource = [IO.Path]::GetFullPath($item.FullName)
            $suffix = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
            $backup = [IO.Path]::GetFullPath((Join-Path $projectRoot ".venv.backup-$suffix"))
            if ($resolvedSource -ne $venvPath -or
                -not $backup.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Environment path validation failed.'
            }
            Move-Item -LiteralPath $resolvedSource -Destination $backup
            Write-Host "Saved the old environment: $backup"
        }
        & $basePython -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
        if (-not (Test-Interpreter -Executable $venvPython -VirtualEnvironment)) {
            throw 'The new virtual environment did not pass its startup check.'
        }
    }
    & $venvPython -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and rerun setup.cmd.' }
    & $venvPython -c 'import cv2, mss, numpy'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency import check failed.' }
    Write-Host 'Setup complete. Run start.cmd.'
    exit 0
} catch {
    if (-not $CheckOnly) { Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red }
    exit 1
}
