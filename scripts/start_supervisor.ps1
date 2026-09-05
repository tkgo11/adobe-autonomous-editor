param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot,
  [int]$IntervalSeconds = 5
)
$ErrorActionPreference="Stop"
$py=Join-Path $JobRoot ".venv\Scripts\python.exe"
if(!(Test-Path $py)){$py=(Get-Command python -ErrorAction Stop).Source}
$log=Join-Path $JobRoot "logs\supervisor.log"
$proc=Start-Process -FilePath $py -ArgumentList @((Join-Path $SkillRoot "runtime\supervisor.py"),"--job-root",$JobRoot,"--skill-root",$SkillRoot,"--interval",$IntervalSeconds) -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log+".err")
$proc.Id | Set-Content -Encoding ASCII (Join-Path $JobRoot "runtime\supervisor.pid")
Write-Output $proc.Id
