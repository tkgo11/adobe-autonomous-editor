param(
  [Parameter(Mandatory=$true)][string]$JobRoot
)
$ErrorActionPreference = "Stop"

function Test-PipVenv {
  param([Parameter(Mandatory=$true)][string]$Python)
  $probe = Join-Path ([System.IO.Path]::GetTempPath()) ("aae-python-probe-" + [guid]::NewGuid().ToString("N"))
  try {
    & $Python -c "import sys; assert sys.version_info >= (3,10)" *> $null
    if($LASTEXITCODE -ne 0) { return $false }
    & $Python -m venv $probe *> $null
    $venvCreated = $LASTEXITCODE -eq 0
    $venvPython = Join-Path $probe "Scripts\python.exe"
    if(-not $venvCreated -or -not (Test-Path -LiteralPath $venvPython)) { return $false }
    & $venvPython -m pip --version *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  } finally {
    if(Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Recurse -Force }
  }
}

function Resolve-CompatiblePython {
  $commands = @("python", "python3")
  foreach($name in $commands) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if($command) {
      if($command.Source -match "\\WindowsApps\\") { continue }
      try {
        $resolved = & $command.Source -c "import sys; assert sys.version_info >= (3,10); print(sys.executable)" 2>$null
        if($LASTEXITCODE -eq 0 -and $resolved) {
          $candidate = [string]($resolved | Select-Object -Last 1)
          if(Test-PipVenv -Python $candidate.Trim()) { return $candidate.Trim() }
        }
      } catch {}
    }
  }
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if($launcher) {
    try {
      $resolved = & $launcher.Source -3 -c "import sys; assert sys.version_info >= (3,10); print(sys.executable)" 2>$null
      if($LASTEXITCODE -eq 0 -and $resolved) {
        $candidate = [string]($resolved | Select-Object -Last 1)
        if(Test-PipVenv -Python $candidate.Trim()) { return $candidate.Trim() }
      }
    } catch {}
  }
  return $null
}

$existing = Resolve-CompatiblePython
if($existing) { Write-Output $existing; exit 0 }

# Python 3.12.10 is the last 3.12 release with official Windows installers and
# remains supported by the runtime. Install it per job, without admin rights or
# a system PATH mutation.
$version = "3.12.10"
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
switch($arch) {
  "X64"   { $artifact = "python-$version-amd64.exe" }
  "Arm64" { $artifact = "python-$version-arm64.exe" }
  "X86"   { $artifact = "python-$version.exe" }
  default { throw "No bundled Python bootstrap route for Windows architecture $arch" }
}
$runtime = Join-Path $JobRoot "runtime"
$target = Join-Path $runtime "python-base"
$python = Join-Path $target "python.exe"
if(Test-Path -LiteralPath $target) {
  if((Test-Path -LiteralPath $python) -and (Test-PipVenv -Python $python)) {
    Write-Output $python
    exit 0
  }
  # The job-local installation is incomplete or no longer supports venvs.
  # Remove only this installer-owned target before repairing it.
  Remove-Item -LiteralPath $target -Recurse -Force
}

$downloads = Join-Path $runtime "bootstrap-downloads"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
$installer = Join-Path $downloads $artifact
$url = "https://www.python.org/ftp/python/$version/$artifact"
Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing

$signature = Get-AuthenticodeSignature -FilePath $installer
if($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
  throw "Refusing unverified Python installer: signature=$($signature.Status), signer=$($signature.SignerCertificate.Subject)"
}

$arguments = @(
  "/quiet", "InstallAllUsers=0", "Include_launcher=0", "Include_test=0",
  "Include_doc=0", "Include_tcltk=0", "Include_pip=1", "PrependPath=0",
  "TargetDir=`"$target`""
)
$process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
if($process.ExitCode -ne 0 -or -not (Test-Path $python)) {
  throw "Per-job Python installation failed with exit code $($process.ExitCode)"
}
Write-Output $python
