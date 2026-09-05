# Compatibility wrapper. New jobs should use initialize_job.ps1 or runtime/initialize.py.
param(
    [string]$JobRoot = (Get-Location).Path,
    [string]$SkillRoot = (Split-Path -Parent $PSScriptRoot),
    [string[]]$Source = @(),
    [string]$Brief = ""
)
$ErrorActionPreference="Stop"
if($Source.Count -eq 0){
  Write-Warning "No sources supplied. Running environment-only discovery through legacy scaffold is no longer supported; pass -Source."
}
& (Get-Command python -ErrorAction Stop).Source "$SkillRoot\runtime\initialize.py" --job-root $JobRoot --skill-root $SkillRoot --brief $Brief @($Source | ForEach-Object { @('--source', $_) } | ForEach-Object { $_ })
exit $LASTEXITCODE
