param([Parameter(Mandatory=$true)][string]$JobRoot)
$ErrorActionPreference="Stop"
$ccx=Join-Path $JobRoot "runtime\com.autonomous-editor.bridge.ccx"
if(-not (Test-Path $ccx)){throw "Bridge CCX not found: $ccx"}
$upia=Join-Path ${env:CommonProgramFiles} "Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"
if(-not (Test-Path $upia)){throw "Adobe UPIA not found. Creative Cloud Desktop may need repair/install."}
& $upia /install $ccx
if($LASTEXITCODE -ne 0){throw "UPIA install failed with exit code $LASTEXITCODE"}
