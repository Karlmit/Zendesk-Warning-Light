<#
    Runs a command as NT AUTHORITY\SYSTEM in session 0, the way Intune runs a
    system-context install, and returns its exit code. CI only: needs admin.

    .\run-as-system.ps1 -Command 'C:\path\Intune-Install.cmd' -Log C:\zwl-system.log
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Command,
    [Parameter(Mandatory)] [string]$Log,
    [int]$TimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'

$name = 'zwl-ci-' + [guid]::NewGuid().ToString('N')
# cmd /c so .cmd files run and their output lands in the log.
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
    -Argument "/c `"`"$Command`" > `"$Log`" 2>&1`""
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Force | Out-Null
try {
    Start-ScheduledTask -TaskName $name
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    # 267009 = still running, 267011 = not started yet.
    do {
        Start-Sleep -Seconds 2
        $state = (Get-ScheduledTask -TaskName $name).State
        $code = (Get-ScheduledTaskInfo -TaskName $name).LastTaskResult
        $busy = $state -eq 'Running' -or $code -eq 267009 -or $code -eq 267011
    } while ($busy -and (Get-Date) -lt $deadline)
    if ($busy) { throw "timed out after $TimeoutSeconds s: $Command" }
    if (Test-Path $Log) { Get-Content $Log }
    Write-Output "exit code as SYSTEM: $code"
    exit $code
} finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
