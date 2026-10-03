# ACE-Step на Windows-ПК (RTX 5070 FE) — генерация без лимитов HF

Цель: твой ПК = бэкенд генерации. Пайплайн в GitHub ходит на `http://<tailnet-ip>:7860`
(тот же Gradio API, что HF Space). Квот нет, трек 45с ~ за 10-20с локально.

## 1. Tailscale (раз)
- Ставим: https://tailscale.com/download/windows
- `tailscale up`, запомнить IP машины (100.x.y.z) — `tailscale ip -4`

## 2. ACE-Step (раз, ~10 мин)
В PowerShell:
```powershell
git clone https://github.com/ace-step/ACE-Step
cd ACE-Step
uv venv .venv
.venv\Scripts\activate
# torch для Blackwell (RTX 50xx) — ТОЛЬКО cu128, стандартный pypi-торч не видит 5070
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
uv pip install -r requirements.txt
# старт сервера, доступный из тейлнет-сети:
python app.py --server_name 0.0.0.0 --port 7860
```
Проверка локально: браузер `http://localhost:7860` — интерфейс Gradio поднялся.
Проверка из тейлнет: с любого устройства сети открыть `http://<tailnet-ip>:7860`.

## 3. Автостарт (чтобы ПК сам поднимал сервер)
Положить `start-ace.bat` в shell:startup (`Win+R` → `shell:startup`):
```bat
cd /d C:\path\to\ACE-Step
call .venv\Scripts\activate.bat
python app.py --server_name 0.0.0.0 --port 7860
```

## 4. Подключение пайплайна
Сказать мне tailnet-IP — я впишу его в GitHub Secret `ACE_ENDPOINT`.
Дальше крон сам: попытка → локальный ACE-Step → фолбэк HF Space, если ПК офлайн.

## Firewall
Windows при первом старте спросит про python в частной сети — разрешить.
Или: `netsh advfirewall firewall add rule name="ACE-Step" dir=in action=allow protocol=TCP localport=7860 remoteip=100.64.0.0/10`
(только тейлнет-подсеть, не весь интернет).

## Лицензия
ACE-Step — Apache-2.0, локальная генерация = коммерчески чисто (см. docs/DECISIONS.md п.1).
