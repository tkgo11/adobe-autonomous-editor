param(
  [ValidateSet("User", "Project")]
  [string]$Scope = "User",
  [string]$ProjectRoot = (Get-Location).Path,
  [switch]$Force,
  [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/tkgo11/adobe-autonomous-editor.git"
$SkillName = "adobe-autonomous-editor"

$git = Get-Command git -ErrorAction SilentlyContinue

function Test-SkillPackage([string]$Target) {
  $skillFile = Join-Path $Target "SKILL.md"
  $metadataFile = Join-Path $Target "agents\openai.yaml"
  if (-not (Test-Path -LiteralPath $skillFile)) { throw "Install verification failed: SKILL.md is missing." }
  if (-not (Test-Path -LiteralPath $metadataFile)) { throw "Install verification failed: agents/openai.yaml is missing." }
  $firstLines = (Get-Content -LiteralPath $skillFile -TotalCount 5) -join "`n"
  if ($firstLines -notmatch "(?m)^name:\s*adobe-autonomous-editor\s*$") {
    throw "Install verification failed: SKILL.md frontmatter name is invalid."
  }
}

function Find-CompatiblePython {
  foreach($name in @("python", "python3")) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if(-not $command -or $command.Source -match "\\WindowsApps\\") { continue }
    try {
      $resolved = & $command.Source -c "import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(1)" 2>$null
      if($LASTEXITCODE -eq 0 -and $resolved) { return ([string]($resolved | Select-Object -Last 1)).Trim() }
    } catch {}
  }
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if($launcher) {
    try {
      $resolved = & $launcher.Source -3 -c "import sys; print(sys.executable) if sys.version_info >= (3,10) else sys.exit(1)" 2>$null
      if($LASTEXITCODE -eq 0 -and $resolved) { return ([string]($resolved | Select-Object -Last 1)).Trim() }
    } catch {}
  }
  return $null
}

function Test-SkillRuntime([string]$Target) {
  if (-not $SkipValidation) {
    $python = Find-CompatiblePython
    if ($python) {
      Write-Host "Running package self-test in staged installation..."
      & $python (Join-Path $Target "tests\selftest.py")
      if ($LASTEXITCODE -ne 0) { throw "Skill self-test failed." }
    } else {
      Write-Warning "Python 3.10+ was not found; runtime validation is deferred to the skill's self-provisioned job environment."
    }
  }
}

function Install-Fresh([string]$Target) {
  if($git) {
    & $git.Source clone --depth 1 $Repo $Target
    if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
    return
  }
  $token = [guid]::NewGuid().ToString("N")
  $archive = Join-Path $env:TEMP ("adobe-autonomous-editor-" + $token + ".zip")
  $expanded = Join-Path $env:TEMP ("adobe-autonomous-editor-install-" + $token)
  try {
    Invoke-WebRequest "https://github.com/tkgo11/adobe-autonomous-editor/archive/refs/heads/main.zip" -OutFile $archive -UseBasicParsing
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded -Force
    $source = Join-Path $expanded "adobe-autonomous-editor-main"
    Test-SkillPackage $source
    Move-Item -LiteralPath $source -Destination $Target
    New-Item -ItemType File -Path (Join-Path $Target ".installed-from-archive") | Out-Null
  } finally {
    if(Test-Path -LiteralPath $expanded) { Remove-Item -LiteralPath $expanded -Recurse -Force }
    if(Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
  }
}

if ($Scope -eq "User") {
  $homeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
  if (-not $homeDir) { throw "Could not determine the user home directory." }
  $skillsRoot = Join-Path $homeDir ".agents\skills"
} else {
  $root = (Resolve-Path -LiteralPath $ProjectRoot).Path
  $skillsRoot = Join-Path $root ".agents\skills"
}

$destination = Join-Path $skillsRoot $SkillName
New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null

function Install-Transactionally {
  $token = [guid]::NewGuid().ToString("N")
  $stage = Join-Path $skillsRoot ("." + $SkillName + ".stage." + $token)
  $backup = Join-Path $skillsRoot ("." + $SkillName + ".backup." + $token)
  try {
    Install-Fresh $stage
    Test-SkillPackage $stage
    Test-SkillRuntime $stage
    if(Test-Path -LiteralPath $destination) { Move-Item -LiteralPath $destination -Destination $backup }
    Move-Item -LiteralPath $stage -Destination $destination
    if(Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
  } catch {
    if((-not (Test-Path -LiteralPath $destination)) -and (Test-Path -LiteralPath $backup)) {
      Move-Item -LiteralPath $backup -Destination $destination
    }
    if(Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    throw
  }
}

if (Test-Path -LiteralPath $destination) {
  $gitDir = Join-Path $destination ".git"
  if ((Test-Path -LiteralPath $gitDir) -and $git) {
    Write-Host "Updating existing skill at $destination"
    & $git.Source -C $destination pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed." }
  } elseif ($Force -or (Test-Path (Join-Path $destination ".installed-from-archive"))) {
    Write-Host "Staging and replacing existing non-git directory at $destination"
    Install-Transactionally
  } else {
    throw "Destination already exists and cannot be safely updated: $destination`nRerun with -Force to replace it."
  }
} else {
  Write-Host "Installing $SkillName to $destination"
  Install-Transactionally
}

Test-SkillPackage $destination
Test-SkillRuntime $destination

Write-Host ""
Write-Host "Installed successfully: $destination" -ForegroundColor Green
Write-Host "Restart Codex (or start a new session) so it refreshes skill discovery."
Write-Host 'Then invoke it explicitly with: $adobe-autonomous-editor'
Write-Host 'Example: $adobe-autonomous-editor Edit D:\Footage\shoot into a polished 60-second vertical video.'
