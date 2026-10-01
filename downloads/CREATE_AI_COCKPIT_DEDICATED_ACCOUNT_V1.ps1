param(
    [string]$UserName = "AI-Cockpit"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    throw "Run this script from an elevated Windows PowerShell."
}

if ($null -eq (Get-Command Get-LocalUser -ErrorAction SilentlyContinue) -or
    $null -eq (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) {
    throw "Microsoft.PowerShell.LocalAccounts cmdlets are required. Use 64-bit Windows PowerShell."
}

$current = [Environment]::UserName
if ($current -ieq $UserName) {
    throw "The dedicated AI Cockpit account must be different from the current work account."
}

$existing = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    Write-Host ("Creating local standard user: " + $UserName) -ForegroundColor Cyan
    $password = Read-Host "Enter a password for the dedicated AI Cockpit Windows account" -AsSecureString

    if ($null -eq $password) {
        throw "A password is required."
    }

    New-LocalUser `
        -Name $UserName `
        -Password $password `
        -Description "Dedicated Windows session for AI Cockpit / MarketSpeed II RSS isolation" `
        -AccountNeverExpires | Out-Null

    $existing = Get-LocalUser -Name $UserName -ErrorAction Stop
} else {
    Write-Host ("Dedicated account already exists: " + $UserName) -ForegroundColor Yellow
}

$usersGroup = Get-LocalGroup -SID "S-1-5-32-545" -ErrorAction Stop
$adminsGroup = Get-LocalGroup -SID "S-1-5-32-544" -ErrorAction Stop

$memberName = $env:COMPUTERNAME + "\" + $UserName

$usersMembers = @(Get-LocalGroupMember -Group $usersGroup.Name -ErrorAction SilentlyContinue)
if (-not ($usersMembers | Where-Object { $_.Name -ieq $memberName })) {
    Add-LocalGroupMember -Group $usersGroup.Name -Member $memberName
}

$adminMembers = @(Get-LocalGroupMember -Group $adminsGroup.Name -ErrorAction SilentlyContinue)
if ($adminMembers | Where-Object { $_.Name -ieq $memberName }) {
    throw "Safety violation: $memberName is a member of Administrators. Remove administrator membership before using this account for AI Cockpit."
}

Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host " DEDICATED AI COCKPIT ACCOUNT READY" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host ("Account: " + $memberName) -ForegroundColor Cyan
Write-Host "Privilege: standard Users group only" -ForegroundColor Green
Write-Host ""
Write-Host "Next: run PREPARE_AI_COCKPIT_DEDICATED_RUNTIME_V1.ps1 from the work account, then use Windows 'Switch user' to sign into this account once." -ForegroundColor Yellow
