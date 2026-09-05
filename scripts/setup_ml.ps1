param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot
)
$ErrorActionPreference="Stop"
$py=Join-Path $JobRoot ".venv\Scripts\python.exe"
if(!(Test-Path $py)){& (Join-Path $SkillRoot "scripts\setup_runtime.ps1") -JobRoot $JobRoot -SkillRoot $SkillRoot | Out-Null}
& $py -m pip install -r (Join-Path $SkillRoot "runtime\requirements-ml.txt")
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Write-Output $py
