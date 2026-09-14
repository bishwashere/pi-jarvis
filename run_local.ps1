param()

$ErrorActionPreference = "Stop"

function Set-JarvisDefault {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $CurrentValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($CurrentValue)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

$ProjectDir = [Environment]::GetEnvironmentVariable("JARVIS_PROJECT_DIR", "Process")
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = $PSScriptRoot
}
$ProjectDir = [IO.Path]::GetFullPath($ProjectDir)

$VenvDir = [Environment]::GetEnvironmentVariable("JARVIS_VENV_DIR", "Process")
if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ProjectDir "runtime\venv"
} elseif (-not [IO.Path]::IsPathRooted($VenvDir)) {
    $VenvDir = Join-Path $ProjectDir $VenvDir
}

$PythonPath = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path -PathType Leaf $PythonPath)) {
    throw @"
Jarvis virtual environment not found at $VenvDir
Run this first:
  `$env:UV_PROJECT_ENVIRONMENT = "runtime/venv"
  uv sync --python 3.12 --locked
"@
}

# Vosk and sounddevice avoid the optional whisper.cpp and Linux ALSA tools.
# Callers can set any of these variables before launching to override a default.
$env:JARVIS_PROJECT_DIR = $ProjectDir
Set-JarvisDefault "JARVIS_COMMAND_STT_ENGINE" "vosk"
Set-JarvisDefault "JARVIS_PLAYBACK_BACKEND" "sounddevice"
Set-JarvisDefault "JARVIS_PLAYBACK_DEVICE" "default"
Set-JarvisDefault "JARVIS_CONFIGURE_VOLUME" "false"

$ScriptsDir = Join-Path $VenvDir "Scripts"
$env:Path = "$ScriptsDir$([IO.Path]::PathSeparator)$env:Path"

Push-Location $ProjectDir
try {
    & $PythonPath (Join-Path $ProjectDir "jarvis_voice.py")
    $ExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

exit $ExitCode
