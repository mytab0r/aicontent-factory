[CmdletBinding()]param([switch]$DryRun,[string]$GatePattern)
# --- kanban running-cards gate (t_3720e3a7): no compact/Docker restart while workers run ---
$g = & "C:\dockerlocal\kanban-gate.ps1" $GatePattern; $grc = $LASTEXITCODE
if (-not $DryRun) { Add-Content 'D:\hermes-codex\compact.log' ("{0} {1}" -f (Get-Date -Format s), ($g -join ' ')) }
if ($grc -ne 0) { Write-Output "auto-compact: skip (running kanban cards) :: $($g -join ' ')"; exit 0 }
# --- end gate ---
# DockerVhdxCompact (SYSTEM, every 30 min). H-040 p.3. Sparse NOT used (unsafe since WSL 2.5.6).
# ponytail: thresholds hardcoded; compact only if >=20 GB reclaimable and >=6h since last run (avoid restart loops).
$vhd = 'D:\Docker\wsl\disk\docker_data.vhdx'
$log = 'D:\hermes-codex\compact.log'
$stamp = 'C:\dockerlocal\compact.last'
function L($m){ Add-Content $log "$(Get-Date -Format s) $m" }
$free = (Get-PSDrive D).Free/1GB
$size = (Get-Item $vhd).Length/1GB
if (-not ($free -lt 45 -or $size -ge 90)) { exit 0 }
if ((Test-Path $stamp) -and ((Get-Date) - (Get-Item $stamp).LastWriteTime).TotalHours -lt 6) { exit 0 }
$docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$used = $null
try {
  if ($DryRun) { Write-Output 'dry-run: would fstrim -av' } else {
  & $docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -- fstrim -av 2>&1 | Out-Null
  }
  $kb = (& $docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -- df -k /var/lib 2>$null | Select-Object -Last 1) -split '\s+'
  $used = [double]$kb[2]/1MB
} catch {}
if ($used -ne $null -and ($size - $used) -lt 20) { L "skip: vhdx=$([math]::Round($size,1)) used=$([math]::Round($used,1))"; exit 0 }
if ($DryRun) { Write-Output "dry-run: would compact $vhd (D_free=$([math]::Round($free,1)) vhdx=$([math]::Round($size,1)) used=$used): stop Docker, wsl --shutdown, stop WSLService, Optimize-VHD/diskpart, start WSLService, start Docker"; exit 0 }
Set-Content $stamp (Get-Date -Format s)
L "start: D_free=$([math]::Round($free,1)) vhdx=$([math]::Round($size,1)) used=$used"
cmd /c compact /u $vhd | Out-Null
fsutil sparse setflag $vhd 0 | Out-Null
Get-Process 'Docker Desktop','com.docker.*' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 5
wsl.exe --shutdown 2>$null
Stop-Service WSLService -Force -ErrorAction SilentlyContinue
Start-Sleep 5
$failed = $null
try { Optimize-VHD -Path $vhd -Mode Full -ErrorAction Stop; L 'Optimize-VHD ok' }
catch {
  # t_5dec8455: fallback was silent (rc 0 even if both failed). Now: record failure, restore Docker, exit 1.
  $failed = "Optimize-VHD failed: $($_.Exception.Message)"
  L "$failed ; diskpart"
  $dp = "$env:TEMP\dp.txt"
  "select vdisk file=`"$vhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk" | Set-Content $dp -Encoding ascii
  diskpart /s $dp | Out-Null
  $failed += " ; diskpart rc=$LASTEXITCODE"
}
Start-Service WSLService -ErrorAction SilentlyContinue
Get-Process 'Docker Desktop','com.docker.*' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 5
schtasks /run /tn DockerStart | Out-Null
L "done: vhdx=$([math]::Round((Get-Item $vhd).Length/1GB,1)) D_free=$([math]::Round((Get-PSDrive D).Free/1GB,1))"
# fail loud only after Docker is restarted above: host must never stay without Docker
if ($failed) { L "FAILED: $failed"; Write-Error $failed; exit 1 }
