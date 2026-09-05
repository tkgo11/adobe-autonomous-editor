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

function Require-Command([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command '$Name' was not found. Install it and rerun this installer."
  }
}

Require-Command "git"

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

if (Test-Path -LiteralPath $destination) {
  $gitDir = Join-Path $destination ".git"
  if (Test-Path -LiteralPath $gitDir) {
    Write-Host "Updating existing skill at $destination"
    & git -C $destination pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed." }
  } elseif ($Force) {
    Write-Host "Replacing existing non-git directory at $destination"
    Remove-Item -LiteralPath $destination -Recurse -Force
    & git clone --depth 1 $Repo $destination
    if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
  } else {
    throw "Destination already exists and is not a git checkout: $destination`nRerun with -Force to replace it."
  }
} else {
  Write-Host "Installing $SkillName to $destination"
  & git clone --depth 1 $Repo $destination
  if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
}

$skillFile = Join-Path $destination "SKILL.md"
$metadataFile = Join-Path $destination "agents\openai.yaml"
if (-not (Test-Path -LiteralPath $skillFile)) { throw "Install verification failed: SKILL.md is missing." }
if (-not (Test-Path -LiteralPath $metadataFile)) { throw "Install verification failed: agents/openai.yaml is missing." }

$firstLines = (Get-Content -LiteralPath $skillFile -TotalCount 5) -join "`n"
if ($firstLines -notmatch "(?m)^name:\s*adobe-autonomous-editor\s*$") {
  throw "Install verification failed: SKILL.md frontmatter name is invalid."
}

if (-not $SkipValidation) {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    Write-Host "Running package self-test..."
    & $python.Source (Join-Path $destination "tests\selftest.py")
    if ($LASTEXITCODE -ne 0) { throw "Skill self-test failed." }
  } else {
    Write-Warning "Python was not found, so the optional package self-test was skipped."
  }
}

Write-Host ""
Write-Host "Installed successfully: $destination" -ForegroundColor Green
Write-Host "Restart Codex (or start a new session) so it refreshes skill discovery."
Write-Host 'Then invoke it explicitly with: $adobe-autonomous-editor'
Write-Host 'Example: $adobe-autonomous-editor Edit D:\Footage\shoot into a polished 60-second vertical video.'
