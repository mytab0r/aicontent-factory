$limitGB = 60; $minFreeGB = 40
$log = 'D:\hermes-runner\disk-guard.log'
$vhd = 'D:\Docker\wsl\disk\docker_data.vhdx'
# t_03efb867: 19.10 01:29 UTC this script pruned the stopped ace-step container, then its 20.7 GB image.
# Protected containers are never removed here; aggressive image prune runs only while they exist (in-use images are kept).
$protect = '^(ace-step|ace-step-new)$'
function Log($m) { Add-Content $log ("{0} {1}" -f (Get-Date -Format s), $m) }
if (-not (Test-Path $vhd)) { exit 0 }
$sizeGB = [math]::Round((Get-Item $vhd).Length/1GB,1)
$freeGB = [math]::Round((Get-PSDrive D).Free/1GB,1)
Log "vhdx=${sizeGB}GB freeD=${freeGB}GB"
if ($sizeGB -gt $limitGB -or $freeGB -lt $minFreeGB) {
  Log "over limit: prune (volumes untouched, protected=$protect)"
  docker builder prune -f 2>&1 | Out-Null
  $cut = (Get-Date).ToUniversalTime().AddHours(-24)
  foreach ($c in (docker ps -a --filter status=exited --filter status=created --format '{{.Names}}')) {
    if ($c -match $protect) { Log "keep protected container $c"; continue }
    $created = [datetime]::Parse((docker inspect -f '{{.Created}}' $c)).ToUniversalTime()
    if ($created -lt $cut) { docker rm $c 2>&1 | Out-Null; Log "rm container $c" }
  }
  docker image prune -f 2>&1 | Out-Null
  $sizeGB = [math]::Round((Get-Item $vhd).Length/1GB,1)
  if ($sizeGB -gt $limitGB -or $freeGB -lt $minFreeGB) {
    docker inspect ace-step 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { docker image prune -a -f --filter until=72h 2>&1 | Out-Null; Log "aggressive image prune done" }
    else { Log "SKIP aggressive image prune: ace-step container missing (its image must survive)" }
  }
  if ($freeGB -lt 20) { Log "CRITICAL freeD<20GB: stopping hermes-runner/runner-browser to protect host"; docker stop hermes-runner runner-browser 2>&1 | Out-Null }
}
$ws = 'D:\hermes-runner\ws'; $wsLimitGB = 30
if (Test-Path $ws) {
  $wsGB = [math]::Round(((Get-ChildItem $ws -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum)/1GB,1)
  Log "ws=${wsGB}GB"
  if ($wsGB -gt $wsLimitGB) {
    Log "ws over ${wsLimitGB}GB: stopping hermes-dispatcher"
    docker stop hermes-dispatcher 2>&1 | Out-Null
  }
}
if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Get-Content $log -Tail 200 | Set-Content $log }
