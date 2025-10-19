#!/usr/bin/env python3
"""采集:更新本地数据源仓库(sources/)并抓取 TableCfg 原始数值表。

一条命令完成两步:
    1. 仓库同步:全部 --depth 1 --single-branch;partial=true 的仓库用
       --filter=blob:none --no-checkout(blob 按需懒取、取过即本地缓存),
       已存在的仓库 fetch 后更新到远端最新;
       ⚠️ partial 仓库绝不能 reset --hard(会触发全量 blob 懒取),只移动引用
    2. 数值表抓取:本地 git 仓库 → 缓存 → jsdelivr → raw → 一图流 COS → GitHub API
       多级回退,产物写入 data/raw/tablecfg/ 并更新 manifest.json

由 `enddata collection <产物>/all` 的隐式依赖机制调用:
    python3 -m collection.fetch --no-update   # 跳过仓库更新(离线)
    python3 -m collection.fetch ItemTable --force
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone

from tools.enddata_http import (
    PROJECT_ROOT,
    RAW_DIR,
    fetch_to_cache,
    gh_api,
    git_env,
    git_proxy,
    http_get,
    info,
    load_json,
    repo_dir,
    resolve_branch,
)

MANIFEST = RAW_DIR / "tablecfg" / "manifest.json"

# ================= 第一步:数据源仓库同步 =================


def run_git(args: list[str], cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    cmd = ["git"]
    proxy = git_proxy()
    if proxy:
        cmd += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    cmd += args
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=git_env())
    return r.returncode, (r.stdout + r.stderr)[-500:]


def persist_proxy(dest: Path) -> None:
    """把代理写进仓库配置:partial 仓库后续 cat-file 懒取 blob 时要用。"""
    proxy = git_proxy()
    if proxy:
        run_git(["config", "http.proxy", proxy], cwd=dest)
        run_git(["config", "https.proxy", proxy], cwd=dest)


def clone_one(entry: dict) -> tuple[str, str]:
    repo, branch, partial = entry["repo"], entry.get("branch"), entry.get("partial", False)
    dest = repo_dir(repo)
    if dest.is_dir():
        return "exists", ""
    args = ["clone", "--depth", "1", "--single-branch", "--quiet"]
    if partial:
        args += ["--filter=blob:none", "--no-checkout"]
    if branch:
        args += ["--branch", branch]
    args += [f"https://github.com/{repo}.git", str(dest)]
    info(f"[clone] {repo}{' (partial)' if partial else ''}")
    code, out = run_git(args, timeout=1800)
    if code != 0:
        return "failed", out
    persist_proxy(dest)
    return "cloned", ""


def update_one(entry: dict) -> tuple[str, str]:
    repo, branch = entry["repo"], entry.get("branch")
    dest = repo_dir(repo)
    if not branch:
        code, out = run_git(["symbolic-ref", "--short", "HEAD"], cwd=dest)
        if code != 0:
            return "fetch-failed", "无法解析本地分支"
        branch = out.strip()
    code, out = run_git(["fetch", "--depth", "1", "--force", "origin", branch], cwd=dest, timeout=1200)
    if code != 0:
        return "fetch-failed", out
    if entry.get("partial", False):
        # partial 仓库没有工作区:绝不能用 reset --hard(会触发全量 blob 懒取),
        # 只移动分支引用即可,read_from_git 走 HEAD:path 的 cat-file
        code, out = run_git(["update-ref", f"refs/heads/{branch}", "FETCH_HEAD"], cwd=dest)
        if code != 0:
            return "reset-failed", out
    else:
        code, out = run_git(["reset", "--hard", f"origin/{branch}", "--quiet"], cwd=dest)
        if code != 0:
            return "reset-failed", out
    return "updated", ""


def configure_clone_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-update", action="store_true", help="只克隆缺失的,不更新已有仓库")
    parser.add_argument("--only", nargs="*", help="只处理指定仓库(如 rmxlinux/EndfieldData)")


def update_repos(no_update: bool = False, only: list[str] | None = None) -> None:
    git_cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["git"]
    entries = git_cfg["clone"]
    if only:
        entries = [e for e in entries if e["repo"] in only]

    repos_dir = PROJECT_ROOT / git_cfg.get("repos_dir", "sources")
    repos_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int] = {}
    for entry in entries:
        repo = entry["repo"]
        status, out = clone_one(entry)
        if status == "exists" and not no_update:
            status, out = update_one(entry)
        summary[status] = summary.get(status, 0) + 1
        if status in ("failed", "fetch-failed", "reset-failed"):
            info(f"[FAIL] {repo}: {out.strip()[-300:]}")
        else:
            info(f"[{status}] {repo}")
        time.sleep(1)

    info(f"\n汇总: {summary}")
    info(f"仓库目录: {repos_dir}")


# ================= 第二步:数值表抓取 =================


def fetch_tables(names: list[str], force: bool = False) -> None:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    repo = cfg["repo"]
    branch = resolve_branch(repo, cfg.get("branch"))
    wanted = names
    table_dir = cfg.get("table_dir", "TableCfg")
    i18n_dir = cfg.get("i18n_dir", table_dir)
    # 不同镜像的 i18n 位置不同(rmxlinux 在 TableCfg/ 内,XiaBei-cy 在 i18n/ 目录),
    # 依次尝试候选目录,取第一个命中
    candidates = []
    for d in (table_dir, i18n_dir):
        if d and d not in candidates:
            candidates.append(d)
    info(f"数据源: {repo}@{branch}  待抓取 {len(wanted)} 个文件")

    results = {"repo": repo, "branch": branch, "fetched_at": None, "files": {}}
    ok = 0
    cos_base = None
    try:
        cos_base = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["yituliu_cos"]["table_base"]
    except (KeyError, FileNotFoundError, json.JSONDecodeError):
        pass
    for name in wanted:
        try:
            last_err = None
            dest = channel = None
            for d in candidates:
                try:
                    dest, channel = fetch_to_cache("tablecfg", repo, branch, f"{d}/{name}.json", force=force)
                    last_err = None
                    break
                except Exception as e:  # noqa: BLE001 - 目录候选失败则继续
                    last_err = e
            if dest is None and cos_base:
                # 兜底:一图流 COS 直取(无需 git,见 docs/sources.md)
                data = http_get(f"{cos_base}/{name}.json")
                dest = RAW_DIR / "tablecfg" / repo.replace("/", "__") / branch / f"{name}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                channel = "yituliu-cos"
            if dest is None:
                raise last_err
            results["files"][name] = {
                "path": str(dest.relative_to(PROJECT_ROOT)),
                "channel": channel,
                "size_kb": round(dest.stat().st_size / 1024),
            }
            ok += 1
        except Exception as e:  # noqa: BLE001 - 单表失败不中断整批
            info(f"  [FAIL] {name}: {e}")
            results["files"][name] = {"error": str(e)}
        time.sleep(0.3)  # 温和一些,避免触发限流

    results["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"完成 {ok}/{len(wanted)},清单已写入 {MANIFEST.relative_to(PROJECT_ROOT)}")


def ensure_tables(names: list[str], force: bool = False) -> None:
    """产物命令的隐式依赖:确保原始表在本地缓存,缺失的自动补抓。"""
    from tools.common import raw_tables_dir

    d = raw_tables_dir()
    wanted = names
    if force:
        info(f"强制重抓依赖的原始表 {len(wanted)} 张")
        fetch_tables(wanted, force=True)
        return
    missing = [n for n in wanted if not (d / f"{n}.json").exists()]
    if missing:
        info(f"缺少原始表,自动补抓 {len(missing)} 张: {', '.join(missing)}")
        fetch_tables(missing, force=False)
