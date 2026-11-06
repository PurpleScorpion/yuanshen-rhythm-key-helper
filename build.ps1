param(
    [string]$Python = '',
    [string]$OutputDir = 'dist'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$appName = 'yuanshen-rhythm-key-helper'

function Resolve-BuildPython {
    param([string]$WorkDir)
    if ($Python) {
        $specified = (Resolve-Path -LiteralPath $Python).Path
        $probe = & $specified -c "import sys; print(int(sys.prefix != sys.base_prefix))"
        if ($LASTEXITCODE -ne 0) { throw 'The selected Python cannot start.' }
        if ($probe -eq '1') { return $specified }
        $isolated = Join-Path $WorkDir 'venv'
        & $specified -m venv $isolated | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Could not create a build virtual environment.' }
        return (Join-Path $isolated 'Scripts\python.exe')
    }
    # Let the source setup reuse, create, or repair the project's local venv.
    $setup = Join-Path $projectRoot 'setup.ps1'
    & $setup -CheckOnly | Out-Host
    if ($LASTEXITCODE -ne 0) {
        & $setup | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed.' }
    }
    return (Join-Path $projectRoot '.venv\Scripts\python.exe')
}

$savedEnvironment = @{}
foreach ($name in @('PYTHONUTF8', 'PYTHONDONTWRITEBYTECODE', 'TCL_LIBRARY', 'TK_LIBRARY', 'PYINSTALLER_CONFIG_DIR')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    if (-not [IO.Path]::IsPathRooted($OutputDir)) {
        $OutputDir = Join-Path $projectRoot $OutputDir
    }
    $outputRoot = ([IO.DirectoryInfo]::new($OutputDir)).FullName.TrimEnd([IO.Path]::DirectorySeparatorChar)
    $outputParent = [IO.Directory]::GetParent($outputRoot)
    if (-not $outputParent -or (Test-Path -LiteralPath $outputRoot)) {
        throw 'The output directory must be new. Choose another -OutputDir or move the previous output.'
    }
    $outputBundle = Join-Path $outputRoot $appName
    $outputArchive = Join-Path $outputRoot "$appName-windows-x64.zip"
    # Keep staging names short for Windows systems with the legacy path limit.
    $runName = [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $workRoot = Join-Path (Join-Path $projectRoot 'build') $runName
    New-Item -ItemType Directory -Path $workRoot | Out-Null
    $buildPython = Resolve-BuildPython -WorkDir $workRoot
    $probe = @'
import sys, sysconfig
if sys.implementation.name != "cpython" or not (3, 12) <= sys.version_info[:2] < (3, 15) or sysconfig.get_platform() != "win-amd64":
    raise SystemExit("Use 64-bit Windows CPython 3.12, 3.13, or 3.14.")
if sys.prefix == sys.base_prefix:
    raise SystemExit("Install build dependencies in a virtual environment.")
import tkinter
print(sys.base_prefix)
print(tkinter.TclVersion)
print(tkinter.TkVersion)
'@
    $pythonInfo = @($probe | & $buildPython -)
    if ($LASTEXITCODE -ne 0 -or $pythonInfo.Count -ne 3) {
        throw 'The selected Python must include the Tcl/Tk component.'
    }
    $tclBase = Join-Path $pythonInfo[0] 'tcl'
    $env:TCL_LIBRARY = Join-Path $tclBase ('tcl' + $pythonInfo[1])
    $env:TK_LIBRARY = Join-Path $tclBase ('tk' + $pythonInfo[2])
    if (-not (Test-Path -LiteralPath (Join-Path $env:TCL_LIBRARY 'init.tcl') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $env:TK_LIBRARY 'tk.tcl') -PathType Leaf)) {
        throw 'Tcl/Tk scripts are missing from the base Python installation. Install the Tcl/Tk component and retry.'
    }
    & $buildPython -c "import tkinter; root = tkinter.Tk(); root.withdraw(); root.destroy()"
    if ($LASTEXITCODE -ne 0) { throw 'The selected Python could not initialize Tk.' }

    $requirements = Join-Path $projectRoot 'requirements-build.txt'
    & $buildPython -m pip install --disable-pip-version-check --only-binary=:all: -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies.' }

    $icon = Join-Path $projectRoot 'assets\rhythm.ico'
    $logo = Join-Path $projectRoot 'assets\logo.png'
    $sample = Join-Path $projectRoot 'config.example.json'
    if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) { throw 'assets/rhythm.ico is missing.' }
    if (-not (Test-Path -LiteralPath $logo -PathType Leaf)) { throw 'assets/logo.png is missing.' }
    if (-not (Test-Path -LiteralPath $sample -PathType Leaf)) { throw 'config.example.json is missing.' }
    $checkSample = @'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from rhythm_helper.settings import DEFAULTS, load_config
sample = root / "config.example.json"
if json.loads(sample.read_text(encoding="utf-8-sig")) != DEFAULTS or load_config(sample) != DEFAULTS:
    raise SystemExit("config.example.json must match the factory defaults in rhythm_helper.settings.")
'@
    $checkSample | & $buildPython - $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Invalid factory configuration example.' }

    # Use the ignored build folder when possible. A different destination
    # volume needs a staging folder there for the final atomic rename.
    $stageParent = [IO.Directory]::GetParent($workRoot).FullName
    if ([IO.Path]::GetPathRoot($workRoot) -ne [IO.Path]::GetPathRoot($outputRoot)) {
        $stageParent = $outputParent.FullName
    }
    $stageDist = Join-Path $stageParent "p$runName"
    New-Item -ItemType Directory -Path $stageDist | Out-Null
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $workRoot 'pyinstaller-cache'
    $options = @(
        '--onedir', '--windowed', '--uac-admin', '--noconfirm',
        '--name', $appName, '--icon', $icon, '--add-data', "$icon;assets", '--add-data', "$logo;assets",
        '--specpath', $workRoot, '--workpath', (Join-Path $workRoot 'work'),
        '--distpath', $stageDist, '--paths', $projectRoot, (Join-Path $projectRoot 'main.py')
    )
    & $buildPython -m PyInstaller @options
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed. For WinError 206 or an excessively long DLL/data path, retry from shorter source and output directories.'
    }

    $bundle = Join-Path $stageDist $appName
    Copy-Item -LiteralPath $sample -Destination (Join-Path $bundle 'config.json')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'PORTABLE-README.txt') -Destination (Join-Path $bundle 'README.txt')
    Copy-Item -LiteralPath (Join-Path $projectRoot '校准练习.cmd') -Destination $bundle

    $verify = @'
import sys, xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import pefile

bundle, icon, logo = map(Path, sys.argv[1:])
program = bundle / (bundle.name + ".exe")
for item in ("_internal/_tcl_data/init.tcl", "_internal/_tk_data/tk.tcl", "_internal/_tkinter.pyd", "_internal/assets/rhythm.ico", "_internal/assets/logo.png"):
    if not (bundle / item).is_file():
        raise SystemExit(f"Missing bundled resource: {item}")
if (bundle / "_internal/assets/rhythm.ico").read_bytes() != icon.read_bytes():
    raise SystemExit("Packaged window icon differs from the source icon.")
if (bundle / "_internal/assets/logo.png").read_bytes() != logo.read_bytes():
    raise SystemExit("Packaged logo differs from the source image.")
with pefile.PE(str(program), fast_load=True) as pe:
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Subsystem != 2:
        raise SystemExit("Expected an AMD64 Windows GUI executable.")
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    types = {entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
    if not {3, 14, 24} <= types:
        raise SystemExit("Missing icon or application manifest.")
    levels = []
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == 24:
            for resource in entry.directory.entries:
                for language in resource.directory.entries:
                    data = language.data.struct
                    xml = ET.fromstring(pe.get_data(data.OffsetToData, data.Size).rstrip(b"\0"))
                    levels.extend(xml.iterfind(".//{*}requestedExecutionLevel"))
    if len(levels) != 1 or levels[0].get("level") != "requireAdministrator" or levels[0].get("uiAccess", "false").lower() != "false":
        raise SystemExit("Expected a requireAdministrator manifest with uiAccess=false.")
archive = bundle.parent / (bundle.name + "-windows-x64.zip")
with ZipFile(archive, "x", ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            output.write(path, path.relative_to(bundle.parent).as_posix())
with ZipFile(archive) as output:
    if output.testzip() is not None:
        raise SystemExit("ZIP integrity check failed.")
'@
    $verify | & $buildPython - $bundle $icon $logo
    if ($LASTEXITCODE -ne 0) { throw 'Bundle validation or ZIP creation failed.' }

    $actualStage = (Resolve-Path -LiteralPath $stageDist).Path
    if ($actualStage -ne [IO.Path]::GetFullPath($stageDist) -or
        [IO.Directory]::GetParent($actualStage).FullName -ne $stageParent -or
        [IO.Directory]::GetParent($outputRoot).FullName -ne $outputParent.FullName) {
        throw 'Output path validation failed.'
    }
    [IO.Directory]::Move($actualStage, $outputRoot)
    Write-Host "Executable: $(Join-Path $outputBundle "$appName.exe")"
    Write-Host "ZIP: $outputArchive"
    exit 0
} catch {
    Write-Host "Build failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
