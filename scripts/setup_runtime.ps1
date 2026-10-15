param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot
)
$ErrorActionPreference="Stop"
$base=& (Join-Path $SkillRoot "scripts\provision_python.ps1") -JobRoot $JobRoot | Select-Object -Last 1
if(-not $base -or -not (Test-Path $base)){throw "Could not provision a compatible Python runtime"}
$venv=Join-Path $JobRoot "runtime\venv"
if(-not (Test-Path (Join-Path $venv "Scripts\python.exe"))){ & $base -m venv $venv }
$py=Join-Path $venv "Scripts\python.exe"
& $py -m pip install --disable-pip-version-check --requirement (Join-Path $SkillRoot "runtime\requirements.txt")
if($LASTEXITCODE -ne 0){ throw "Runtime dependency installation failed" }
$py
