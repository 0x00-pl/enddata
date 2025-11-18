#!/usr/bin/env python3
"""数据源仓库同步:把 config/sources.json 中所有 git 数据源克隆/更新到本地 sources/。

克隆策略:
    - 全部 --depth 1 --single-branch(只需要当前版本数据)
    - partial=true 的仓库用 --filter=blob:none --no-checkout:
      元数据(目录树)本地全量,blob 按需懒取、取过即本地缓存,
      适合 rmxlinux(1.5GB)等大仓库与不稳定的代理网络
    - sparse=[目录…] 的仓库在 partial 基础上用 sparse-checkout 限定物化范围,
      checkout/reset 只懒取目录内 blob(可选能力,用于压缩超大资源仓库的本地占用)
    - 已存在的仓库执行 fetch + 更新引用到远端最新;
      ⚠️ 非 sparse 的 partial 仓库绝不能 reset --hard(会触发全量 blob 懒取),只移动引用;
      sparse 仓库 reset --hard 只物化 sparse 范围内的 blob,可安全使用

由 `enddata collection clone` 调用;也可程序化使用:
    from collection.fetch import update_repos
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time

from tools import versions
from tools.datasource import PROJECT_ROOT, git_env, git_proxy, info, load_json, repo_dir


def run_git(args: list[str], cwd=None, timeout: int = 600) -> tuple[int, str]:
    cmd = ["git"]
    proxy = git_proxy()
    if proxy:
        cmd += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    cmd += args
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=git_env())
    return r.returncode, (r.stdout + r.stderr)[-500:]


def persist_proxy(dest) -> None:
    """把代理写进仓库配置:partial 仓库后续 cat-file 懒取 blob 时要用。"""
    proxy = git_proxy()
    if proxy:
        run_git(["config", "http.proxy", proxy], cwd=dest)
        run_git(["config", "https.proxy", proxy], cwd=dest)


def clone_one(entry: dict) -> tuple[str, str]:
    repo, branch, partial = entry["repo"], entry.get("branch"), entry.get("partial", False)
    sparse = entry.get("sparse") or []
    dest = repo_dir(repo)
    if dest.is_dir():
        return "exists", ""
    args = ["clone", "--depth", "1", "--single-branch", "--quiet"]
    if partial:
        args += ["--filter=blob:none", "--no-checkout"]
    if branch:
        args += ["--branch", branch]
    args += [f"https://github.com/{repo}.git", str(dest)]
    tag = " (partial+sparse)" if sparse else (" (partial)" if partial else "")
    info(f"[clone] {repo}{tag}")
    code, out = run_git(args, timeout=1800)
    if code != 0:
        return "failed", out
    persist_proxy(dest)
    if sparse:
        # 限定物化范围后再 checkout:blob 懒取仅限 sparse 目录(需先 persist_proxy)
        code, out = run_git(["sparse-checkout", "set", "--no-cone", *sparse], cwd=dest)
        if code != 0:
            return "failed", out
        code, out = run_git(["reset", "--hard", "--quiet"], cwd=dest, timeout=1800)
        if code != 0:
            return "failed", out
    return "cloned", ""


def update_one(entry: dict) -> tuple[str, str]:
    repo, branch = entry["repo"], entry.get("branch")
    sparse = entry.get("sparse") or []
    dest = repo_dir(repo)
    if not branch:
        code, out = run_git(["symbolic-ref", "--short", "HEAD"], cwd=dest)
        if code != 0:
            return "fetch-failed", "无法解析本地分支"
        branch = out.strip()
    code, out = run_git(["fetch", "--depth", "1", "--force", "origin", branch], cwd=dest, timeout=1200)
    if code != 0:
        return "fetch-failed", out
    if sparse:
        # 重应用 sparse 模式(配置里的目录清单可能已变化)+ 物化到 FETCH_HEAD:
        # blob 懒取仅限 sparse 目录(需先 persist_proxy)
        code, out = run_git(["sparse-checkout", "set", "--no-cone", *sparse], cwd=dest)
        if code != 0:
            return "reset-failed", out
        code, out = run_git(["reset", "--hard", "FETCH_HEAD", "--quiet"], cwd=dest, timeout=1800)
        if code != 0:
            return "reset-failed", out
    elif entry.get("partial", False):
        # partial 仓库没有工作区:绝不能用 reset --hard(会触发全量 blob 懒取),
        # 只移动分支引用即可
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


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("tables", nargs="*", help="要抓取的表名(不含 .json),缺省为全部产物依赖表")
    parser.add_argument("--force", action="store_true", help="忽略本地缓存强制重新抓取")
    parser.add_argument("--no-update", action="store_true", help="跳过数据源仓库更新(离线时使用)")


def fetch_tables(names: list[str], force: bool = False) -> None:
    """按需加载原始表:本地仓库直读,缺 blob 自动懒取,force 时走网络刷新。"""
    from tools.tables import load_tables

    load_tables(names, force=force)


def run(args, default_names: list[str] | None = None) -> None:
    if not args.no_update:
        update_repos()
    versions.record_repo_heads()
    versions.refresh_game_build()
    fetch_tables(args.tables or default_names, force=args.force)


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

    versions.record_repo_heads()
    info(f"\n汇总: {summary}")
    info(f"仓库目录: {repos_dir}")
