param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot,
  [Parameter(Mandatory=$true)][ValidateSet("analyze_media", "desktop_driver", "execute_plan", "review_packet", "rpc_client", "source_inventory", "supervisor", "transcribe", "qc")][string]$Command,
  [string[]]$Arguments = @()
)
$ErrorActionPreference="Stop"
$python=Join-Path $JobRoot "runtime\venv\Scripts\python.exe"
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw "Job runtime is not initialized: $python"}
$relative=if($Command -eq "qc"){"scripts\qc.py"}else{"runtime\$Command.py"}
$script=Join-Path $SkillRoot $relative
if(-not (Test-Path -LiteralPath $script -PathType Leaf)){throw "Runtime command not found: $script"}
& $python $script @Arguments
exit $LASTEXITCODE
