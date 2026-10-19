#!/usr/bin/env python3
"""YouTube Data API v3 OAuth2 setup — non-interactive, agent-driven.

По образцу /opt/data/skills/productivity/google-workspace/scripts/setup.py,
но с узким набором scope под публикацию видео и чтение аналитики (не весь
Google Workspace).

Запускать интерпретатором, где уже стоит google-api-python-client
(/opt/hermes/.venv/bin/python) — в .venv самого проекта этих пакетов нет,
и плодить их туда не нужно (YAGNI, см. AGENTS.md п.2):

  /opt/hermes/.venv/bin/python pipeline/youtube_oauth.py --check

Команды:
  --check                          # валиден ли токен? exit 0 = да, 1 = нет
  --client-secret /path/to.json    # сохранить OAuth client credentials
  --auth-url                       # напечатать OAuth URL для пользователя
  --auth-code CODE                 # обменять код на токен
  --revoke                         # отозвать и удалить токен

Agent workflow:
  1. --check. exit 0 -> уже есть валидный токен, дальше не идти.
  2. Спросить у пользователя путь к client_secret.json, --client-secret PATH.
  3. --auth-url, отправить ссылку пользователю.
  4. Пользователь открывает ссылку, авторизуется, получает code (в URL
     редиректа на localhost — страница не откроется, код берётся из
     адресной строки браузера).
  5. --auth-code CODE (можно вставить всю redirect-URL целиком).
  6. --check для проверки.

Токен и client secret хранятся в <repo>/.state/ — эта директория в
.gitignore, в git не попадает.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".state"
TOKEN_PATH = STATE_DIR / "youtube_token.json"
CLIENT_SECRET_PATH = STATE_DIR / "youtube_client_secret.json"
PENDING_AUTH_PATH = STATE_DIR / "youtube_oauth_pending.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",  # нужен для videos().delete()
    "https://www.googleapis.com/auth/youtube.force-ssl",  # captions.insert/list (localize.py, t_b9eb61b2)
]

# OOB-флоу google deprecated — используем localhost-редирект, код
# пользователь копирует из адресной строки браузера после редиректа.
REDIRECT_URI = "http://localhost:1"


def _normalize_authorized_user_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if not normalized.get("type"):
        normalized["type"] = "authorized_user"
    return normalized


def _load_token_payload(path: Path = TOKEN_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _missing_scopes_from_payload(payload: dict) -> list[str]:
    raw = payload.get("scopes") or payload.get("scope")
    if not raw:
        return []
    granted = {s.strip() for s in (raw.split() if isinstance(raw, str) else raw) if s.strip()}
    return sorted(scope for scope in SCOPES if scope not in granted)


def check_auth(quiet: bool = False) -> bool:
    """Проверить валидность сохранённого токена. Возвращает True/False."""
    if not TOKEN_PATH.exists():
        print(f"NOT_AUTHENTICATED: нет токена в {TOKEN_PATH}")
        return False

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    except Exception as e:
        print(f"TOKEN_CORRUPT: {e}")
        return False

    payload = _load_token_payload(TOKEN_PATH)
    if creds.valid:
        missing = _missing_scopes_from_payload(payload)
        if missing:
            print(f"AUTHENTICATED (partial): токен валиден, но не хватает {len(missing)} scope:")
            for s in missing:
                print(f"  - {s}")
        if not quiet:
            print(f"AUTHENTICATED: токен валиден, {TOKEN_PATH}")
        return True

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(
                json.dumps(_normalize_authorized_user_payload(json.loads(creds.to_json())), indent=2),
                encoding="utf-8",
            )
            if not quiet:
                print(f"AUTHENTICATED: токен обновлён, {TOKEN_PATH}")
            return True
        except Exception as e:
            err = str(e).lower()
            if "invalid_grant" in err or "token_revoked" in err:
                print(f"TOKEN_REVOKED: {e}\n  Перезапустить --auth-url для нового consent.")
            else:
                print(f"REFRESH_FAILED: {e}")
            return False

    print("TOKEN_INVALID: перезапустить setup.")
    return False


def store_client_secret(path: str) -> None:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        print(f"ERROR: файл не найден: {src}")
        sys.exit(1)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("ERROR: файл не валидный JSON.")
        sys.exit(1)
    if "installed" not in data and "web" not in data:
        print("ERROR: это не client_secret.json от Google OAuth (нет ключа 'installed'/'web').")
        print("Скачать правильный файл: https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_SECRET_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"OK: client secret сохранён в {CLIENT_SECRET_PATH}")


def _save_pending_auth(*, state: str, code_verifier: str) -> None:
    PENDING_AUTH_PATH.write_text(
        json.dumps({"state": state, "code_verifier": code_verifier, "redirect_uri": REDIRECT_URI}, indent=2),
        encoding="utf-8",
    )


def _load_pending_auth() -> dict:
    if not PENDING_AUTH_PATH.exists():
        print("ERROR: нет незавершённой OAuth-сессии. Сначала --auth-url.")
        sys.exit(1)
    try:
        data = json.loads(PENDING_AUTH_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: не удалось прочитать pending OAuth-сессию: {e}")
        sys.exit(1)
    if not data.get("state") or not data.get("code_verifier"):
        print("ERROR: pending OAuth-сессия без PKCE-данных. Заново --auth-url.")
        sys.exit(1)
    return data


def _extract_code_and_state(code_or_url: str) -> tuple[str, str | None]:
    if not code_or_url.startswith("http"):
        return code_or_url, None
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(code_or_url)
    params = parse_qs(parsed.query)
    if "code" not in params:
        print("ERROR: в URL нет параметра 'code'.")
        sys.exit(1)
    return params["code"][0], params.get("state", [None])[0]


def get_auth_url() -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: нет сохранённого client secret. Сначала --client-secret.")
        sys.exit(1)

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), scopes=SCOPES, redirect_uri=REDIRECT_URI,
        autogenerate_code_verifier=True,
    )
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _save_pending_auth(state=state, code_verifier=flow.code_verifier)
    print(auth_url)


def exchange_auth_code(code: str) -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: нет сохранённого client secret. Сначала --client-secret.")
        sys.exit(1)

    pending = _load_pending_auth()
    raw_callback = code
    code, returned_state = _extract_code_and_state(code)
    if returned_state and returned_state != pending["state"]:
        print("ERROR: OAuth state mismatch. Заново --auth-url.")
        sys.exit(1)

    from google_auth_oauthlib.flow import Flow
    from urllib.parse import parse_qs, urlparse

    granted_scopes = list(SCOPES)
    if isinstance(raw_callback, str) and raw_callback.startswith("http"):
        scope_val = (parse_qs(urlparse(raw_callback).query).get("scope") or [""])[0].strip()
        if scope_val:
            granted_scopes = scope_val.split()

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), scopes=granted_scopes,
        redirect_uri=pending.get("redirect_uri", REDIRECT_URI),
        state=pending["state"], code_verifier=pending["code_verifier"],
    )
    try:
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        flow.fetch_token(code=code)
    except Exception as e:
        print(f"ERROR: обмен кода на токен не удался: {e}")
        print("Код мог истечь — заново --auth-url.")
        sys.exit(1)

    creds = flow.credentials
    token_payload = _normalize_authorized_user_payload(json.loads(creds.to_json()))
    actually_granted = list(creds.granted_scopes or []) if getattr(creds, "granted_scopes", None) else []
    if actually_granted:
        token_payload["scopes"] = actually_granted
    elif granted_scopes != SCOPES:
        token_payload["scopes"] = granted_scopes

    missing = _missing_scopes_from_payload(token_payload)
    if missing:
        print(f"WARNING: токену не хватает scope: {', '.join(missing)}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print(f"OK: авторизовано. Токен сохранён в {TOKEN_PATH}")


def revoke() -> None:
    if not TOKEN_PATH.exists():
        print("Нечего отзывать — токена нет.")
        return

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        import urllib.request
        urllib.request.urlopen(
            urllib.request.Request(
                f"https://oauth2.googleapis.com/revoke?token={creds.token}",
                method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"},
            ),
            timeout=15,
        )
        print("Токен отозван в Google.")
    except Exception as e:
        print(f"Удалённый отзыв не удался (токен мог уже быть недействителен): {e}")

    TOKEN_PATH.unlink(missing_ok=True)
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print(f"Удалено: {TOKEN_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Data API v3 OAuth setup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--client-secret", metavar="PATH")
    group.add_argument("--auth-url", action="store_true")
    group.add_argument("--auth-code", metavar="CODE")
    group.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check_auth() else 1)
    elif args.client_secret:
        store_client_secret(args.client_secret)
    elif args.auth_url:
        get_auth_url()
    elif args.auth_code:
        exchange_auth_code(args.auth_code)
    elif args.revoke:
        revoke()


if __name__ == "__main__":
    main()
