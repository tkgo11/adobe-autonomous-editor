param([Parameter(Mandatory=$true)][string]$JobRoot,[Parameter(Mandatory=$true)][string]$SkillRoot)
$ErrorActionPreference="Stop"
$py=(Get-Command python -ErrorAction Stop).Source
$secret=Join-Path $JobRoot "runtime\bridge-secret.txt"
$state=Join-Path $JobRoot "runtime\broker-state.json"
$log=Join-Path $JobRoot "logs\broker.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$p=Start-Process -FilePath $py -ArgumentList @("$SkillRoot\runtime\orchestrator.py","--secret-file",$secret,"--state",$state) -RedirectStandardOutput $log -RedirectStandardError $log -PassThru -WindowStyle Hidden
$p.Id | Set-Content -Encoding ascii (Join-Path $JobRoot "runtime\broker.pid")
$p.Id
