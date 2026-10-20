param(
  [Parameter(Mandatory=$true)][string]$JobRoot,
  [Parameter(Mandatory=$true)][string]$SkillRoot,
  [Parameter(Mandatory=$true)][string[]]$Source,
  [string]$Brief = "",
  [ValidateSet("crafting-first", "adobe-only")][string]$EditorPriority = "crafting-first",
  [switch]$InstallCraftingApps,
  [switch]$ForceInstallCraftingApps,
  [switch]$InstallBridge,
  [switch]$ForceInstallBridge,
  [switch]$StartBroker,
  [switch]$LaunchPremiere,
  [switch]$NoAuto,
  [switch]$SkipRuntimeSetup
)
$ErrorActionPreference="Stop"
New-Item -ItemType Directory -Force -Path (Join-Path $JobRoot "runtime") | Out-Null
if($SkipRuntimeSetup){$py=(Get-Command python -ErrorAction Stop).Source;$entry=Join-Path $SkillRoot "runtime\initialize.py"}
else{$py=& (Join-Path $SkillRoot "scripts\provision_python.ps1") -JobRoot $JobRoot | Select-Object -Last 1;$entry=Join-Path $SkillRoot "runtime\bootstrap.py"}
$initArgs=@($entry,"--job-root",$JobRoot,"--skill-root",$SkillRoot,"--brief",$Brief,"--editor-priority",$EditorPriority)
foreach($s in $Source){$initArgs += @("--source",$s)}
if(-not $NoAuto){$initArgs += "--auto"}
if($InstallCraftingApps -or $ForceInstallCraftingApps){$initArgs += "--install-crafting-apps"}
if($ForceInstallCraftingApps){$initArgs += "--force-install-crafting-apps"}
if($InstallBridge -or $ForceInstallBridge){$initArgs += "--install-bridge"}
if($ForceInstallBridge){$initArgs += "--force-install-bridge"}
if($StartBroker){$initArgs += "--start-broker"}
if($LaunchPremiere){$initArgs += "--launch-premiere"}
& $py @initArgs
exit $LASTEXITCODE
