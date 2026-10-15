# Compatibility wrapper. New jobs should use initialize_job.ps1 or runtime/bootstrap.py.
param(
    [string]$JobRoot = (Get-Location).Path,
    [string]$SkillRoot = (Split-Path -Parent $PSScriptRoot),
    [string[]]$Source = @(),
    [string]$Brief = "",
    [ValidateSet("crafting-first", "adobe-only")][string]$EditorPriority = "crafting-first"
)
$ErrorActionPreference="Stop"
if($Source.Count -eq 0){
  Write-Warning "No sources supplied. Running environment-only discovery through legacy scaffold is no longer supported; pass -Source."
}
$py=& (Join-Path $SkillRoot "scripts\provision_python.ps1") -JobRoot $JobRoot | Select-Object -Last 1
& $py "$SkillRoot\runtime\bootstrap.py" --job-root $JobRoot --skill-root $SkillRoot --brief $Brief --editor-priority $EditorPriority --auto @($Source | ForEach-Object { @('--source', $_) } | ForEach-Object { $_ })
exit $LASTEXITCODE
