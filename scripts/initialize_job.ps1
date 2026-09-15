param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot,
  [Parameter(Mandatory=$true)][string[]]$Source,
  [string]$Brief = "",
  [switch]$InstallBridge,
  [switch]$ForceInstallBridge,
  [switch]$StartBroker,
  [switch]$LaunchPremiere,
  [switch]$NoAuto,
  [switch]$SkipRuntimeSetup
)
$ErrorActionPreference="Stop"
New-Item -ItemType Directory -Force -Path (Join-Path $JobRoot "runtime") | Out-Null
if($SkipRuntimeSetup){$py=(Get-Command python -ErrorAction Stop).Source}
else{$py=& (Join-Path $SkillRoot "scripts\setup_runtime.ps1") -JobRoot $JobRoot -SkillRoot $SkillRoot | Select-Object -Last 1}
$initArgs=@((Join-Path $SkillRoot "runtime\initialize.py"),"--job-root",$JobRoot,"--skill-root",$SkillRoot,"--brief",$Brief)
foreach($s in $Source){$initArgs += @("--source",$s)}
$explicit = $InstallBridge -or $StartBroker -or $LaunchPremiere -or $ForceInstallBridge
if((-not $NoAuto) -and (-not $explicit)){$initArgs += "--auto"}
if($InstallBridge -or $ForceInstallBridge){$initArgs += "--install-bridge"}
if($ForceInstallBridge){$initArgs += "--force-install-bridge"}
if($StartBroker){$initArgs += "--start-broker"}
if($LaunchPremiere){$initArgs += "--launch-premiere"}
& $py @initArgs
exit $LASTEXITCODE
