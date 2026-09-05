param(
    [Parameter(Mandatory=$true)][string]$ScriptPath,
    [string]$AfterFX
)

$ErrorActionPreference = "Stop"

if (-not $AfterFX) {
    $roots = @("$env:ProgramFiles\Adobe", "${env:ProgramFiles(x86)}\Adobe")
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $hit = Get-ChildItem -Path $root -Filter "AfterFX.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { $AfterFX = $hit.FullName; break }
    }
}

if (-not $AfterFX -or -not (Test-Path $AfterFX)) { throw "AfterFX.exe not found" }
$resolved = (Resolve-Path $ScriptPath).Path

& $AfterFX -r $resolved
if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
    throw "After Effects dispatcher returned exit code $LASTEXITCODE"
}
