"""采集与初步处理的共享工具:i18n 反查、属性枚举、vfs 资源链接、原始表加载与输出。"""

from __future__ import annotations

import json
from pathlib import Path

from tools.enddata_http import PROJECT_ROOT, RAW_DIR, info, load_json

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

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


def vfs_url(kind: str, **params) -> str | None:
    """按 config/sources.json 的 fffdan_vfs 注册项拼资源 URL(宏山档案局资源镜像,WebP)。"""
    path = vfs_url.patterns.get(kind)
    if vfs_url.base is None or not path:
        return None
    for k, v in params.items():
        if v is None or v == "":
            return None
        path = path.replace("{" + k + "}", str(v))
    return f"{vfs_url.base}{vfs_url.prefix}/{path}"


vfs_url.base = None
vfs_url.prefix = None
vfs_url.patterns = {}


def load_vfs_config() -> None:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"].get("fffdan_vfs")
    if not cfg:
        return
    vfs_url.base = cfg["hosts"][0]
    vfs_url.prefix = cfg["vfs_prefix"]
    vfs_url.patterns = cfg["paths"]


def raw_tables_dir() -> Path:
    cfg = load_json(PROJECT_ROOT / "config" / "sources.json")["sources"]["tablecfg"]
    return RAW_DIR / "tablecfg" / cfg["repo"].replace("/", "__") / cfg["branch"]


def load_raw_tables() -> dict:
    """加载主源全部已抓取的原始表,按表名索引。"""
    return {p.stem: load_json(p) for p in raw_tables_dir().glob("*.json")}


def dump(name: str, payload):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROCESSED_DIR / f"{name}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"  -> {dest.relative_to(PROJECT_ROOT)} ({dest.stat().st_size/1024:.0f} KB, {len(payload) if isinstance(payload, list) else '...'} 条)")
