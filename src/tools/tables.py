"""原始表加载与初步处理共享工具:i18n 反查、属性枚举翻译、vfs 资源链接、数据集输出。"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone

from tools.datasource import (
    PROJECT_ROOT,
    FetchError,
    fetch_gh_file,
    info,
    load_json,
    local_head,
    read_from_git,
    remote_head,
    repo_dir,
    update_repo_to_remote,
)

DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str | None, fallback: str) -> str:
    """名称 → 目录 slug(小写,非字母数字归并为下划线);空名回退 fallback。"""
    s = _SLUG_RE.sub("_", (text or "").lower()).strip("_")
    return s or fallback

# 默认翻译语言(表名 I18nTextTable_<LANG>),由入口脚本 --lang 修改;CN 为项目基准
DEFAULT_LANG = "CN"

# 数据源提供的语言表(rmxlinux@TableCfg/I18nTextTable_<LANG>.json)
LANGUAGES = ("CN", "TC", "EN", "JP", "KR", "FR", "DE", "IT", "MX", "BR", "RU", "ID", "TH", "VN")


def set_default_lang(lang: str) -> None:
    global DEFAULT_LANG  # noqa: PLW0603 - 模块级配置开关,入口 --lang 设置一次
    DEFAULT_LANG = lang.upper()


def i18n_table() -> str:
    """当前默认语言的 i18n 表名(load_tables 会把占位表名 I18nTextTable_CN 解析到它)。"""
    return f"I18nTextTable_{DEFAULT_LANG}"


# 离线模式开关:默认 True,原始表仅读本地 sources/ 克隆、零网络(采集慢/失败的根源是
# 联网回退,见 load_table)。CLI 用 --online 允许联网补缺、--force 强制联网重抓(隐含
# online);程序化调用方同样默认离线,需联网时先调 set_online(True)。
_ONLINE = False


def set_online(online: bool) -> None:
    global _ONLINE  # noqa: PLW0603 - 模块级模式开关(CLI --online/--force 设置)
    _ONLINE = bool(online)


def online() -> bool:
    return _ONLINE


def warn(msg: str) -> None:
    print(f"警告: {msg}", file=sys.stderr, flush=True)


# 主数据源本地快照超过该天数视为可能过期(离线构建前警告一次)
STALE_DAYS = 7


def warn_stale() -> None:
    """离线构建前的数据过期警告:按 tablecfg 主源仓库的本地 HEAD 日期判断,只读本地 git。

    克隆缺失同样警告(离线模式下无表可用);日期新鲜则保持安静。
    """
    from tools import versions  # 惰性导入,与 fetch.py 引 tables 同款,避免加重顶层依赖

    cfg = _tablecfg()
    head = versions.repo_head({"repo": cfg["repo"], "branch": cfg["branch"]})
    if head["status"] != "ok":
        warn(f"本地缺少 {cfg['repo']} 克隆,离线模式无原始表可用;先运行 enddata collection clone")
        return
    age = (datetime.now(timezone.utc).date() - date.fromisoformat(head["date"])).days
    if age > STALE_DAYS:
        warn(f"数据源快照已 {age} 天未更新({head['sha']} {head['date']}「{head['subject']}」),"
             "可能落后当前游戏版本;联网刷新请运行 enddata collection fetch,或加 --force 重抓全部表")

ATTRACTIONS_OF_INTEREST = ["MaxHp", "Atk", "Def", "Str", "Agi", "Wisd", "Will"]

# rmxlinux 新版把 attrType 从字符串改成了整数枚举(AttributeMetaTable.iconName 反查 + 数值交叉验证)
INT_ATTR_MAP = {
    0: "Level", 1: "MaxHp", 2: "Atk", 3: "Def",
    9: "CriticalRate", 10: "CriticalDamageIncrease",
    39: "Str", 40: "Agi", 41: "Wisd", 42: "Will",
    4: "PhysicalDamageTakenScalar", 5: "FireDamageTakenScalar",
    6: "PulseDamageTakenScalar", 7: "CrystDamageTakenScalar",
    55: "EtherDamageTakenScalar", 48: "NaturalDamageTakenScalar",
    # 以下取自 AttributeMetaTable 的 iconName(装备词条常见效率类)
    17: "NormalAtkEfficiency", 28: "UltimateSkillEfficiency", 32: "NormalSkillEfficiency",
    33: "ComboSkillEfficiency", 44: "UltimateSpGainScalar", 47: "ComboSkillCooldown",
    29: "HealOutputIncrease", 30: "HealTakenIncrease", 26: "PoiseEfficiency",
    50: "PhysicalDamageIncrease", 51: "FireDamageIncrease", 52: "PulseDamageIncrease",
    53: "CrystDamageIncrease", 54: "NaturalDamageIncrease", 61: "DamageToBrokenUnitIncrease",
    87: "OriginiumArts",
}


def attr_name(t) -> str | None:
    if isinstance(t, int):
        return INT_ATTR_MAP.get(t)
    return t


def attr_map(attr_list: list[dict]) -> dict:
    """[{attrs: [{attrType, attrValue}]}] 形式(敌人等级曲线)拍平成 {attrType: value}。"""
    out = {}
    for entry in attr_list or []:
        for a in entry.get("attrs", []):
            t, v = attr_name(a.get("attrType")), a.get("attrValue")
            if t:
                out[t] = v
    return out


def flat_attrs(attrs: list[dict] | None) -> dict:
    """[{attrType, attrValue}] 形式(角色分段面板)拍平成 {attrType: value}。"""
    return {attr_name(a["attrType"]): a["attrValue"] for a in attrs or [] if a.get("attrType") is not None}


class I18n:
    def __init__(self, table: dict):
        self.table = table
        self.misses = 0

    def __call__(self, ref: dict | None) -> str | None:
        """把 {id: 哈希, text: null} 的文本引用解析为中文,失败返回 None。"""
        if not isinstance(ref, dict):
            return None
        if ref.get("text"):
            return ref["text"]
        hid = ref.get("id")
        if not hid:
            return None
        text = self.table.get(str(hid))
        if text is None:
            self.misses += 1
        return text


# fffdan vfs 配置(load_vfs_config 注入;模块级可变状态,仅本模块读写)
_vfs: dict = {"base": None, "prefix": None, "patterns": {}}


def vfs_url(kind: str, **params) -> str | None:
    """按 config/sources.json 的 fffdan_vfs 注册项拼资源 URL(宏山档案局资源镜像,WebP)。

    采集管线已不再生成 vfs 直链(数据集只存裸 id,站点构建期经 icon_git 本地化),
    本函数保留作 vfs 路径模式的程序化参考。
    """
    path = _vfs["patterns"].get(kind)
    if _vfs["base"] is None or not path:
        return None
    for k, v in params.items():
        if v is None or v == "":
            return None
        path = path.replace("{" + k + "}", str(v))
    return f"{_vfs['base']}{_vfs['prefix']}/{path}"


def load_vfs_config() -> None:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"].get("fffdan_vfs")
    if not cfg:
        return
    _vfs["base"] = cfg["hosts"][0]
    _vfs["prefix"] = cfg["vfs_prefix"]
    _vfs["patterns"] = cfg["paths"]


def _tablecfg() -> dict:
    return load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]


# force 刷新时已核对过远端的仓库(每仓库每次运行至多一次,避免逐表重复网络往返)
_fresh_repos: set[str] = set()


def sync_repo_fresh(repo: str, branch: str) -> None:
    """force 语义的刷新:ls-remote 核对远端 HEAD,一致则零下载;有新提交才增量 fetch+reset。

    网络失败或无本地克隆时不阻塞构建——前者沿用本地快照(提示),后者由 load_table
    回落 HTTP 逐表抓取。成功与否都只做一次,同仓库后续表直接读本地。
    """
    key = f"{repo}@{branch}"
    if key in _fresh_repos or not repo_dir(repo).is_dir():
        return
    _fresh_repos.add(key)
    remote_sha = remote_head(repo, branch)
    if remote_sha is None:
        warn("远端 HEAD 核对失败,沿用本地快照继续(数据可能不是最新)")
        return
    local_sha = local_head(repo)
    if local_sha == remote_sha:
        return  # 本地已是远端最新,零下载
    info(f"同步 {key}:{(local_sha or '?')[:7]} → {remote_sha[:7]}(增量)")
    if not update_repo_to_remote(repo, branch):
        warn("增量同步失败,沿用本地快照继续(数据可能不是最新)")


def load_table(name: str, force: bool = False) -> dict:
    """读取单张原始表(已解析 JSON)。

    本地克隆是第一数据源,两种模式都优先直读 sources/ 工作区(git cat-file 兜底):
        - 默认离线:只读本地,缺表抛 FetchError(零网络);
        - force:先经 sync_repo_fresh 核对/增量同步仓库(每仓库一次),仍读本地,
          不逐表重新下载;本地无克隆或缺表时才回退 jsdelivr → raw → API;
        - online()(--online):缺表时允许联网补抓。
    """
    cfg = _tablecfg()
    repo, branch = cfg["repo"], cfg["branch"]
    remote = f"{cfg.get('table_dir', 'TableCfg')}/{name}.json"
    if force:
        sync_repo_fresh(repo, branch)
    data = read_from_git(repo, remote)
    if data is None:
        if not (force or online()):
            raise FetchError(
                f"缺原始表 {name}(本地 {repo_dir(repo).relative_to(PROJECT_ROOT)} 无该文件),"
                "当前为离线模式(默认)不联网补抓。请先 enddata collection fetch 更新本地数据源,"
                "或加 --online 允许联网补抓")
        data, _channel = fetch_gh_file(repo, branch, remote)
    return json.loads(data)


def load_tables(names: list[str], force: bool = False) -> dict:
    """批量加载原始表,按表名索引。

    表名 I18nTextTable_CN 是默认语言表的占位,按 --lang 解析到实际表名;
    其余语言表(如 items/enemies 目录 slug 用的 EN)按显式表名加载。
    """
    resolved = list(dict.fromkeys(
        i18n_table() if n == "I18nTextTable_CN" else n for n in names))
    return {name: load_table(name, force=force) for name in resolved}


def dump(name: str, payload):
    dest = DATA_DIR / f"{name}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"  -> {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size/1024:.0f} KB, {len(payload) if isinstance(payload, list) else '...'} 条)")


# 目录化产物中非条目文件(清理旧文件时保留,每次构建整体覆盖)
_DIR_RESERVED = ("index.json", "_global.json")


def dump_dir(name: str, entries: list[dict], exclude_index: tuple[str, ...] = (),
             subdir=None, index_map=None, index_finalize=None) -> None:
    """数据集目录化输出(characters 格式):每条一个 <id>.json + index.json。

    exclude_index 列出的重字段(长文本/嵌套详情)只进单条文件,索引里剔除;
    subdir 为可选 entry → 子目录相对路径(如 'manual'),按分类分层存放;
    index_map 为可选 entry → 索引条目的自定义映射(默认取整条剔除重字段);
    index_finalize 为可选(索引列表, entries) → 最终序列化对象,如按站点分组的 id 清单;
    重建时清理目录内全部旧条目文件与空子目录。
    """
    out_dir = DATA_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.rglob("*.json"):
        if old.parent == out_dir and old.name in _DIR_RESERVED:
            continue
        old.unlink()
    for d in sorted((p for p in out_dir.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts), reverse=True):
        d.rmdir()  # 条目文件已清空,自底向上删空目录
    for e in entries:
        dest = out_dir / (subdir(e) if subdir else "") / f"{e['id']}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")
    if index_map is not None:
        index = [index_map(e) for e in entries]
    else:
        index = [{k: v for k, v in e.items() if k not in exclude_index} for e in entries]
    if index_finalize is not None:
        index = index_finalize(index, entries)
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    cats = len({subdir(e) for e in entries}) if subdir else 0
    info(f"  -> {out_dir.relative_to(PROJECT_ROOT)}/ ({len(entries)} 条 + index.json"
         + (f",{cats} 个分类子目录" if cats else "") + ")")
