param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot
)
$ErrorActionPreference="Stop"
$base=(Get-Command python -ErrorAction Stop).Source
$venv=Join-Path $JobRoot "runtime\venv"
if(-not (Test-Path (Join-Path $venv "Scripts\python.exe"))){ & $base -m venv $venv }
$py=Join-Path $venv "Scripts\python.exe"
& $py -m pip install --disable-pip-version-check -r (Join-Path $SkillRoot "runtime\requirements.txt")
if($LASTEXITCODE -ne 0){ throw "Runtime dependency installation failed" }
$py
