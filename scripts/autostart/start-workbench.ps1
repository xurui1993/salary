param(
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$logDir = Join-Path $root 'logs'
$logFile = Join-Path $logDir 'autostart.log'
$outFile = Join-Path $logDir 'server.out.log'
$errFile = Join-Path $logDir 'server.err.log'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-AutostartLog([string]$Message) {
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Add-Content -Path $logFile -Value $line -Encoding UTF8
  Write-Host $line
}

foreach ($file in @($outFile, $errFile)) {
  if (Test-Path $file) {
    $size = (Get-Item $file).Length
    if ($size -ge 10MB) {
      Move-Item -Force $file ($file + '.1')
    }
  }
}

$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
$tsxCli = Join-Path $root 'node_modules\tsx\dist\cli.mjs'
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
  $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
  if (Test-Path $candidate) { $pythonExe = $candidate }
}

if (-not $nodeExe) {
  Write-AutostartLog 'node not found in PATH; cannot start.'
  exit 1
}
if (-not (Test-Path $tsxCli)) {
  Write-AutostartLog "tsx not found: $tsxCli; run npm install first."
  exit 1
}

$listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if ($DryRun) {
  Write-AutostartLog "Dry run. root=$root node=$nodeExe python=$pythonExe port3000=$([bool]$listener)"
  exit 0
}
if ($listener) {
  Write-AutostartLog 'Port 3000 is already listening; skip startup.'
  exit 0
}

$deadline = (Get-Date).AddSeconds(90)
$networkReady = $false
while ((Get-Date) -lt $deadline) {
  $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object { $_.NextHop -ne '0.0.0.0' } |
    Select-Object -First 1
  if ($route -and (Test-Connection -ComputerName $route.NextHop -Count 1 -Quiet -ErrorAction SilentlyContinue)) {
    $networkReady = $true
    break
  }
  Start-Sleep -Seconds 3
}
if ($networkReady) {
  Write-AutostartLog 'Network is ready.'
} else {
  Write-AutostartLog 'Network not ready after 90s; starting anyway.'
}

$nodeDir = Split-Path -Parent $nodeExe
$env:PATH = $nodeDir + ';' + $env:PATH
if ($pythonExe) {
  $env:PATH = (Split-Path -Parent $pythonExe) + ';' + $env:PATH
  $env:PYTHON_PATH = $pythonExe
}

while ($true) {
  $existing = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
  if ($existing) {
    Write-AutostartLog 'Port 3000 is already listening; skip startup.'
    exit 0
  }
  foreach ($file in @($outFile, $errFile)) {
    if (Test-Path $file) {
      $size = (Get-Item $file).Length
      if ($size -ge 10MB) {
        Move-Item -Force $file ($file + '.1')
      }
    }
  }
  Write-AutostartLog "Starting dev server. root=$root node=$nodeExe python=$pythonExe"
  $process = Start-Process -FilePath $nodeExe -ArgumentList @($tsxCli, 'server.ts') `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
  Write-AutostartLog "Started process $($process.Id)."
  $process.WaitForExit()
  $code = $process.ExitCode
  Write-AutostartLog "Server exited with code $code; restarting in 3s..."
  Start-Sleep -Seconds 3
}
