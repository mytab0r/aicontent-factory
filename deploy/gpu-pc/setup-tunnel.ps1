# ============================================================
# One-time setup: Cloudflare Tunnel + OpenSSH Server на GPU-ПК
# Запуск в PowerShell ОТ АДМИНИСТРАТОРА:
#   Set-ExecutionPolicy -Scope Process Bypass; .\setup-tunnel.ps1
# Один раз спросит логин в Cloudflare (браузер) — выбрать зону pxbt.app.
# После выполнения агент на сервере получает SSH-доступ к этому ПК
# через туннель pc.pxbt.app и разворачивает Docker-стек сам.
# В систему ставится ровно 2 вещи: cloudflared.exe + штатная фича
# Windows OpenSSH Server. Удаляется обратимо (см. UNINSTALL внизу).
# ============================================================
$ErrorActionPreference = "Stop"
$TunnelName = "pc-andrey"
$Hostname   = "pc.pxbt.app"   # поменяй, если занят

# --- 1. cloudflared ---
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
}

# --- 2. OpenSSH Server (штатная фича Windows) ---
$cap = Get-WindowsCapability -Online | Where-Object Name -like "OpenSSH.Server*"
if ($cap.State -ne "Installed") {
  Add-WindowsCapability -Online -Name $cap.Name
}
Set-Service sshd -StartupType Automatic
Start-Service sshd

# --- 3. Ключ агента (парольный вход оставляем включённым на случай отката,
#        агент ходит только по ключу) ---
$pub = Read-Host "Вставь публичный ключ агента (ssh-ed25519 ...)"
$adminKeys = "$env:ProgramData\ssh\administrators_authorized_keys"
Add-Content -Path $adminKeys -Value $pub
icacls $adminKeys /inheritance:r /grant "SYSTEM:F" /grant "BUILTIN\Administrators:F" | Out-Null
# владелец не в группе Administrators -> дублируем в user-файл
Add-Content -Path "$env:USERPROFILE\.ssh\authorized_keys" -Value $pub -ErrorAction SilentlyContinue

# --- 4. Cloudflare Tunnel (интерактивный логин в браузере) ---
cloudflared tunnel login
cloudflared tunnel create $TunnelName
cloudflared tunnel route dns $TunnelName $Hostname

$uuid = (cloudflared tunnel list --output json | ConvertFrom-Json |
         Where-Object name -eq $TunnelName).id
$config = @"
tunnel: $uuid
credentials-file: $env:USERPROFILE\.cloudflared\$uuid.json
ingress:
  - hostname: $Hostname
    service: ssh://localhost:22
  - service: http_status:404
"@
Set-Content -Path "$env:USERPROFILE\.cloudflared\config.yml" -Value $config

# --- 5. Служба автостарта туннеля ---
cloudflared service install

Write-Host "`nГОТОВО. Туннель: $Hostname -> ssh://localhost:22"
Write-Host "Сообщи агенту hostname '$Hostname' — дальше он всё сделает сам."
Write-Host "`nUNINSTALL (если захочешь удалить всё):"
Write-Host "  cloudflared service uninstall; cloudflared tunnel delete $TunnelName"
Write-Host "  Remove-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0"
