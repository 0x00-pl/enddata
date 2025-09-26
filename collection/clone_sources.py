#!/usr/bin/env python3
"""把 config/sources.json 中所有 git 形态数据源克隆/更新到本地 sources/。

克隆策略:
    - 全部 --depth 1 --single-branch(只需要当前版本数据)
    - partial=true 的仓库用 --filter=blob:none --no-checkout:
      元数据(目录树)本地全量,blob 按需懒取、取过即本地缓存,
      适合 rmxlinux(1.5GB)等大仓库与不稳定的代理网络
    - 已存在的仓库执行 fetch + reset 更新到远端最新

用法:
    python3 collection/clone_sources.py            # 克隆缺失的 + 更新已有的
    python3 collection/clone_sources.py --no-update  # 只克隆缺失的,不更新已有
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enddata_http import PROJECT_ROOT, git_env, git_proxy, info, load_json, repo_dir  # noqa: E402


def run_git(args: list[str], cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    cmd = ["git"]
    proxy = git_proxy()
    if proxy:
        cmd += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    cmd += args
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=git_env())
    return r.returncode, (r.stdout + r.stderr)[-500:]


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


def persist_proxy(dest: Path) -> None:
    """把代理写进仓库配置:partial 仓库后续 cat-file 懒取 blob 时要用。"""
    proxy = git_proxy()
    if proxy:
        run_git(["config", "http.proxy", proxy], cwd=dest)
        run_git(["config", "https.proxy", proxy], cwd=dest)


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-update", action="store_true", help="只克隆缺失的,不更新已有仓库")
    parser.add_argument("--only", nargs="*", help="只处理指定仓库(如 rmxlinux/EndfieldData)")
    args = parser.parse_args()

    git_cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["git"]
    entries = git_cfg["clone"]
    if args.only:
        entries = [e for e in entries if e["repo"] in args.only]

    REPOS_DIR = PROJECT_ROOT / git_cfg.get("repos_dir", "sources")
    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int] = {}
    for entry in entries:
        repo = entry["repo"]
        status, out = clone_one(entry)
        if status == "exists" and not args.no_update:
            status, out = update_one(entry)
        summary[status] = summary.get(status, 0) + 1
        if status in ("failed", "fetch-failed", "reset-failed"):
            info(f"[FAIL] {repo}: {out.strip()[-300:]}")
        else:
            info(f"[{status}] {repo}")
        time.sleep(1)

    info(f"\n汇总: {summary}")
    info(f"仓库目录: {REPOS_DIR}")


if __name__ == "__main__":
    main()
