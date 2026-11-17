$ErrorActionPreference = 'Stop'
$taskName = 'SalaryWorkbench-Autostart'
$ruleName = 'SalaryWorkbench-3000'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
  Write-Host 'Please run this script as Administrator.'
  exit 1
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Out-Null
Write-Host "Removed scheduled task '$taskName' and firewall rule '$ruleName'."
