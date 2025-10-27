"""数据源版本记录与版本报告:结构化存储于 data/versions.json。

文件结构:
{
  "updatedAt": "2026-09-15T08:40:00+00:00",
  "game":   { "build": "initial_..._main_...", "checkedAt": "..." },
  "repos":  { "rmxlinux/EndfieldData": { "branch": "main", "sha": "ef902ef",
                                         "date": "2026-09-08", "subject": "Update 9/8" }, ... }
}

由 collection 域命令(clone/fetch/all)在运行时刷新;enddata version 读取并报告。
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone

from tools.datasource import PROJECT_ROOT, http_get, load_json, repo_dir

VERSIONS_PATH = PROJECT_ROOT / "data" / "versions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    if VERSIONS_PATH.exists():
        return json.loads(VERSIONS_PATH.read_text(encoding="utf-8"))
    return {}


def save(data: dict) -> None:
    data["updatedAt"] = _now()
    VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERSIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def repo_head(entry: dict) -> dict:
    """读取单个数据源仓库的 HEAD 信息(分支/短哈希/日期/提交说明)。"""
    d = repo_dir(entry["repo"])
    info = {"repo": entry["repo"], "branch": entry.get("branch") or "?",
            "sha": "-", "date": "-", "subject": "-", "status": "缺失"}
    if not d.is_dir():
        return info
    if info["branch"] == "?":
        r = subprocess.run(["git", "-C", str(d), "symbolic-ref", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, env=_git_env())
        if r.returncode == 0:
            info["branch"] = r.stdout.strip()
    r = subprocess.run(["git", "-C", str(d), "log", "-1", "--format=%h|%cs|%s"],
                       capture_output=True, text=True, timeout=30, env=_git_env())
    if r.returncode == 0:
        sha, date, subject = r.stdout.strip().split("|", 2)
        info.update({"sha": sha, "date": date, "subject": subject, "status": "ok"})
    return info


def _git_env() -> dict:
    import os
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    return env


def record_repo_heads() -> dict:
    """记录 config 中全部 git 数据源仓库的当前 HEAD。"""
    git_cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["git"]
    data = load()
    heads = {}
    for entry in git_cfg["clone"]:
        head = repo_head(entry)
        heads[entry["repo"]] = head
        data.setdefault("repos", {})[entry["repo"]] = {
            "branch": head["branch"], "sha": head["sha"],
            "date": head["date"], "subject": head["subject"],
        }
    save(data)
    return heads


def fetch_game_build() -> str | None:
    """从宏山档案局镜像逐主机探测官方构建号,失败返回 None。"""
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["fffdan_vfs"]
    for host in cfg["hosts"]:
        try:
            return http_get(host + cfg["version_endpoint"], timeout=10).decode().strip()
        except Exception:  # noqa: BLE001 - 逐主机故障转移
            continue
    return None


def game_build() -> str | None:
    """已记录的游戏构建号基线(无记录返回 None)。"""
    return load().get("game", {}).get("build")


def record_game_build(build: str) -> None:
    data = load()
    data["game"] = {"build": build, "checkedAt": _now()}
    save(data)


def refresh_game_build() -> str | None:
    """探测并记录当前游戏构建号;不可达时保留原值。"""
    build = fetch_game_build()
    if build:
        record_game_build(build)
    return load().get("game", {}).get("build")


# ---- enddata version 报告 ----


def project_version() -> str:
    try:
        from importlib.metadata import version
        return version("enddata")
    except Exception:  # noqa: BLE001 - 未安装时回退读 pyproject.toml
        text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "(.*?)"', text, re.M)
        return m.group(1) if m else "?"


def _dataset_build_line() -> str:
    meta_path = PROJECT_ROOT / "data" / "meta.json"
    if not meta_path.exists():
        return "数据集构建: 无(尚未运行 enddata collection all)"
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    c = m.get("counts", {})
    return ("数据集构建: {}(干员 {} / 物品 {} / 配方 {} / 武器 {} / 装备 {} / 敌人 {})"
            .format(m.get("generatedAt", "?"), c.get("characters"), c.get("items"),
                    c.get("recipes"), c.get("weapons"), c.get("equips"), c.get("enemies")))


def run(args=None) -> None:
    v = load()
    print(f"EndData v{project_version()}\n")

    print("[数据源仓库] data/versions.json")
    repos = v.get("repos", {})
    if repos:
        for repo, r in repos.items():
            print(f"  {repo:<45} {r.get('branch', '?'):<8} {r.get('sha', '-'):<9} "
                  f"{r.get('date', '-')}  {r.get('subject', '')[:40]}")
    else:
        print("  尚无记录(运行 enddata collection clone/fetch 后生成)")

    game = v.get("game", {})
    print("\n[游戏构建号]")
    if game.get("build"):
        print(f"  {game['build']}  (检查于 {game.get('checkedAt', '?')})")
    else:
        print("  尚无记录(运行 enddata collection fetch/all 后生成)")

    print("\n[本地数据]")
    print(f"  {_dataset_build_line()}")
