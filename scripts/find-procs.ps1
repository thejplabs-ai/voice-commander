$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*voice*' -or $_.Name -like '*python*' }
foreach ($p in $procs) {
    Write-Output "PID=$($p.ProcessId) NAME=$($p.Name) CMD=$($p.CommandLine)"
}
