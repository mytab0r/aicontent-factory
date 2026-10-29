#!/usr/bin/env python3
"""Guard базы e2e-образа (t_6de08f33). 20-21.10 CI e2e-admin падал 7 раз: `failed to resolve source metadata for
mcr.microsoft.com/playwright:v1.64.1-noble ... TLS handshake timeout` — тег существует, но mcr.microsoft.com
недоступен с ПК-раннеров. FAIL, если: FROM из mcr.microsoft.com; FROM playwright-образа с версией != npm playwright@X
(образ и пакет должны совпадать, источник версии один — строка `playwright@X` в Dockerfile); версия не X.Y.Z.
Usage: check_e2e_base.py [Dockerfile] | --selftest"""
import re
import sys

UNREACHABLE = ("mcr.microsoft.com",)  # недоступны с раннеров ПК/VPS (TLS RST 150.171.69/70)


def check(text):
    errs = []
    froms = re.findall(r"^FROM\s+(\S+)", text, re.M)
    pkg = re.findall(r"\bplaywright@(\S+)", text)
    if not froms:
        errs.append("нет FROM")
    for f in froms:
        if f.split("/")[0] in UNREACHABLE:
            errs.append(f"FROM {f}: registry недоступен с раннеров (t_6de08f33), базу брать с Docker Hub")
        m = re.search(r"playwright:v([^-\s]+)", f)
        if m and pkg and m.group(1) != pkg[0]:
            errs.append(f"FROM {f}: версия образа {m.group(1)} != npm playwright@{pkg[0]}")
    for v in pkg:
        if not re.fullmatch(r"\d+\.\d+\.\d+", v):
            errs.append(f"playwright@{v}: нужна точная версия X.Y.Z (иначе образ и пакет разъедутся)")
    if len(set(pkg)) > 1:
        errs.append(f"разные версии playwright в Dockerfile: {sorted(set(pkg))}")
    return errs


def selftest():
    ok = "FROM node:20-bookworm-slim\nRUN npm i playwright@1.64.1\n"
    assert check(ok) == [], check(ok)
    assert check("FROM mcr.microsoft.com/playwright:v1.64.1-noble\nRUN npm i playwright@1.64.1\n")
    assert check("FROM ghcr.io/x/playwright:v1.63.0-noble\nRUN npm i playwright@1.64.1\n")
    assert check("FROM node:20\nRUN npm i playwright@latest\n")
    assert check("FROM node:20\nRUN npm i playwright@1.64.1 && npm i playwright@1.65.0\n")
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.exit(selftest())
    p = sys.argv[1] if len(sys.argv) > 1 else "test/e2e/Dockerfile"
    e = check(open(p, encoding="utf-8").read())
    print("\n".join(f"{p}: {x}" for x in e) or f"ok: {p}")
    sys.exit(1 if e else 0)
