"""共享的 GitHub 文件抓取工具:本地 git 仓库 → jsdelivr CDN → raw → GitHub API blob 多级回退。

GitHub API 匿名配额为 60 次/小时,因此优先级为:
    1. sources/ 下的本地克隆(collection/clone_sources.py 维护)——零网络
    2. data/raw/ 的历史缓存——零网络
    3. jsdelivr / raw(无配额限制的渠道)
    4. GitHub API blob(有配额,仅兜底)
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/collection/ → 仓库根
RAW_DIR = PROJECT_ROOT / "data" / "raw"
REPOS_DIR = PROJECT_ROOT / "sources"

USER_AGENT = "enddata-collector (fan-made game data aggregator)"
TIMEOUT = 90


def git_env() -> dict:
    """绕过全局 git 配置(insteadOf 会把 https 改写成 SSH 导致克隆失败)。"""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    return env


def git_proxy() -> str | None:
    try:
        return load_json(PROJECT_ROOT / "config" / "sources.json")["git"].get("proxy")
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def repo_dir(repo: str) -> Path:
    return REPOS_DIR / repo.replace("/", "__")


def read_from_git(repo: str, path: str, timeout: int = 180) -> bytes | None:
    """从本地克隆读取文件。全量克隆直接读工作区;partial 克隆经 cat-file
    读取(blob 未在本地时会按需懒取,成功后即本地缓存)。失败返回 None。"""
    d = repo_dir(repo)
    if not d.is_dir():
        return None
    worktree_file = d / path
    if worktree_file.is_file():
        return worktree_file.read_bytes()
    cmd = ["git", "-C", str(d), "cat-file", "blob", f"HEAD:{path}"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=git_env())
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


class FetchError(Exception):
    pass


def http_get(url: str, rng: str | None = None, timeout: int = TIMEOUT) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def gh_api(path: str) -> dict:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise FetchError(f"GitHub API {e.code}: {url}") from e


def resolve_branch(repo: str, branch: str | None) -> str:
    if branch:
        return branch
    return gh_api(f"/repos/{repo}")["default_branch"]


def _try(url: str) -> bytes | None:
    try:
        return http_get(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def _via_blob(repo: str, branch: str, path: str) -> bytes:
    """GitHub API 兜底:消耗配额,能取到超大文件(CDN 对 >20MB 文件会失败)。"""
    meta = gh_api(f"/repos/{repo}/contents/{path}?ref={branch}")
    if meta.get("encoding") == "base64" and "content" in meta:
        return base64.b64decode(meta["content"])
    if "git_url" in meta:
        blob = gh_api("/repos/" + repo + "/git/blobs/" + meta["git_url"].rsplit("/", 1)[-1])
        return base64.b64decode(blob["content"])
    raise FetchError(f"无法通过 blob API 获取 {repo}@{branch}/{path}")


def fetch_gh_file(repo: str, branch: str, path: str, use_api_fallback: bool = True) -> tuple[bytes, str]:
    """抓取仓库单文件,返回 (内容, 实际使用的渠道)。"""
    attempts = [
        (f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}", "jsdelivr"),
        (f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", "raw"),
    ]
    for url, channel in attempts:
        data = _try(url)
        if data is not None:
            return data, channel
        time.sleep(0.5)
    if use_api_fallback:
        return _via_blob(repo, branch, path), "api-blob"
    raise FetchError(f"所有渠道均失败: {repo}@{branch}/{path}")


def cache_path(source: str, repo: str, branch: str, *parts: str) -> Path:
    safe_repo = repo.replace("/", "__")
    return RAW_DIR / source / safe_repo / branch / Path(*parts)


def fetch_to_cache(source: str, repo: str, branch: str, remote_path: str, local_name: str | None = None,
                   force: bool = False) -> tuple[Path, str]:
    """抓取文件并缓存到 data/raw/<source>/<repo>/<branch>/,已存在则直接返回。
    渠道优先级:cache → 本地 git 仓库 → jsdelivr → raw → GitHub API blob。"""
    name = local_name or Path(remote_path).name
    dest = cache_path(source, repo, branch, name)
    if dest.exists() and not force:
        return dest, "cache"
    data = read_from_git(repo, remote_path)
    if data is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        channel = "git"
    else:
        data, channel = fetch_gh_file(repo, branch, remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    print(f"  [{channel}] {remote_path} -> {dest.relative_to(PROJECT_ROOT)} ({len(data)/1024:.0f} KB)")
    return dest, channel


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def info(msg: str):
    print(msg, flush=True)


def die(msg: str, code: int = 1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)
