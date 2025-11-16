"""采集+初步处理(多数据源综合):敌人数据集 → data/enemies/ 目录。

目录按敌人类型 EN slug 分层(DisplayEnemyTypeTable:common/elite/boss/
advanced/alpha,缺展示信息的入 unknown;typeSlug 字段与目录同名),条目
typeName/name 跟随默认语言(--lang);index.json 为按类型分组的 id 清单
(纯清单,无内容)。

数据来源与贡献:
    - rmxlinux@TableCfg(本地 git):
        EnemyTable × EnemyDisplayInfoTable × EnemyAttributeTemplateTable →
          精英标记、初始霸体、韧性、五系抗性(统一为减伤比例)、满级生命/攻击/防御
        EnemyTemplateDisplayInfoTable(按 templateId 关联,374/381 命中)→
          显示名/昵称/档案描述(哈希可 I18n 反查;EnemyDisplayInfoTable 的哈希全为 0)、
          displayType 分类、出没区域 distributionIds、特殊能力 abilityDescIds
        DisplayEnemyTypeTable → 分类枚举(0 普通/1 精英/2 领袖/3 进阶/4 头目;
          EN 名称经 I18nTextTable_EN 反查作目录 slug)
        DistributionInfoTable → distributionIds 反查出没区域名
        EnemyAbilityDescTable / EnemyRelatedDeathTips → 能力与击杀提示文本
    - AndreaFrederica/jei-web(本地 git,森空岛 Wiki「威胁」分区):条目图标与
      Wiki itemId。join 键为当前语言的显示名(CN 构建 56/56 命中;其他语言 Wiki 包
      无对应译名,图标/Wiki 字段留空)
注:EnemyTagTable(5 个枚举)与敌人无可用关联键 —— EnemyTemplateDisplayInfoTable.tags
    全部为空数组,其余表无 tag 引用,故不产出标签字段。
"""

from __future__ import annotations

import json
import re
import subprocess
import time

from tools.datasource import PROJECT_ROOT, git_env, info, repo_dir
from tools.tables import I18n, attr_map, dump_dir, i18n_table, load_tables, slugify

PRODUCT = "enemies"

REQUIRED_TABLES = [
    "EnemyTable", "EnemyDisplayInfoTable", "EnemyAttributeTemplateTable", "I18nTextTable_CN",
    "EnemyTemplateDisplayInfoTable", "DisplayEnemyTypeTable",
    "EnemyAbilityDescTable", "EnemyRelatedDeathTips", "DistributionInfoTable",
    "I18nTextTable_EN",
]

WIKI_REPO = "AndreaFrederica/jei-web"
WIKI_PACK_DIR = "public/packs/aef-skland/items/终末地百科/威胁"


def _pack_file(repo: str, pack_dir: str, name: str) -> bytes | None:
    """优先直读工作区已检出的文件;partial 克隆缺失时回退 git cat-file。"""
    f = repo_dir(repo) / pack_dir / name
    if f.is_file():
        return f.read_bytes()
    return _git_bytes(repo, "cat-file", "blob", f"HEAD:{pack_dir}/{name}")


def _git_bytes(repo: str, *args, timeout: int = 300) -> bytes | None:
    d = repo_dir(repo)
    r = subprocess.run(["git", "-C", str(d), *args],
                       capture_output=True, timeout=timeout, env=git_env())
    return r.stdout if r.returncode == 0 else None


def load_wiki_threats() -> dict[str, dict]:
    """从 jei-web 森空岛 Wiki「威胁」分区提取 name → {itemId, icon}。

    文件路径含中文,git 命令用 -z 避免路径转义;懒取 blob 失败时重试 3 次
    (退避 2s/4s/6s)。任何失败只影响补充字段,返回空表不影响主流程。
    """
    out: dict[str, dict] = {}
    listing = _git_bytes(WIKI_REPO, "ls-tree", "-z", "--name-only", f"HEAD:{WIKI_PACK_DIR}")
    if not listing:
        info("  ! jei-web 威胁分区不可读,跳过敌人图标/Wiki 补充")
        return out
    files = [f for f in listing.decode("utf-8").split("\0") if f.endswith(".json")]
    for f in files:
        raw = None
        for attempt in range(3):
            raw = _pack_file(WIKI_REPO, WIKI_PACK_DIR, f)
            if raw:
                break
            time.sleep(2 * (attempt + 1))
        if not raw:
            continue
        try:
            d = json.loads(raw)
            item = ((d.get("wiki") or {}).get("data") or {}).get("item") or {}
            out[d.get("name", "?")] = {"itemId": item.get("itemId"), "icon": d.get("icon")}
        except Exception:  # noqa: BLE001 - 损坏条目跳过
            continue
    return out


def build(raw: dict, t: I18n, wiki_threats: dict[str, dict] | None = None) -> list[dict]:
    display = raw["EnemyDisplayInfoTable"]
    tpl_display = raw["EnemyTemplateDisplayInfoTable"]
    ability_tbl = raw["EnemyAbilityDescTable"]
    dist_tbl = raw["DistributionInfoTable"]
    tips_tbl = raw["EnemyRelatedDeathTips"]
    type_names = {int(k): t(v.get("name")) for k, v in raw["DisplayEnemyTypeTable"].items()}
    # EN 名称仅用于目录 slug,条目内 typeName/name 跟随默认语言;缺展示信息的入 unknown
    t_en = I18n(raw["I18nTextTable_EN"])
    type_slugs = {int(k): slugify(t_en(v.get("name")), f"type_{k}")
                  for k, v in raw["DisplayEnemyTypeTable"].items()}
    threats = load_wiki_threats() if wiki_threats is None else wiki_threats

    enemies = []
    for eid, e in raw["EnemyTable"].items():
        d = display.get(eid, {})
        template_id = e.get("templateId") or d.get("templateId")
        template = raw["EnemyAttributeTemplateTable"].get(e.get("attrTemplateId"), {})
        curve = template.get("levelDependentAttributes") or []
        lv_max = attr_map(curve[-1:]) if curve else {}
        # 抗性:新版是具名百分数字段(0-100),旧版是 *ResistScalar(受伤倍率);
        # 统一归一化为「减伤比例」0-1 输出
        resists = {}
        for k, v in template.items():
            if k.endswith("Resistance") and isinstance(v, (int, float)) and v:
                resists[k.replace("Resistance", "")] = v / 100
            elif k.endswith("ResistScalar") and isinstance(v, (int, float)) and v != 1:
                resists[k.replace("DmgResistScalar", "")] = 1 - v

        # 模板级展示信息:显示名(默认语言)/昵称/档案描述/分类/出没区域/特殊能力
        td = tpl_display.get(template_id, {})
        join_name = t(td.get("name"))
        abilities: list[str] = []
        for aid in (td.get("abilityDescIds") or []) + (d.get("abilityDescIds") or []):
            desc = t((ability_tbl.get(aid) or {}).get("description"))
            if desc and desc not in abilities:
                abilities.append(desc)
        distributions: list[str] = []
        for did_ in td.get("distributionIds") or []:
            area = t((dist_tbl.get(did_) or {}).get("areaName"))
            if area and area not in distributions:
                distributions.append(area)
        death_tips = [tip for tip in
                      (t(x) for x in (tips_tbl.get(eid, {}).get("tipContents") or []))
                      if tip]

        # Wiki「威胁」分区:显示名精确 join(CN 构建 56/56 命中)补图标与条目 ID
        th = threats.get(join_name) if join_name else None

        enemies.append({
            "id": eid,
            "templateId": template_id,
            # 显示名:模板展示名(默认语言)优先;解包 EnemyDisplayInfoTable 的哈希均为 0
            "name": t(td.get("name")) or t(d.get("name")) or t(d.get("nickname")) or template_id,
            "nickname": t(td.get("nickname")),
            "typeName": type_names.get(td.get("displayType")),
            "typeSlug": type_slugs.get(td.get("displayType")) or "unknown",
            "icon": (th or {}).get("icon"),
            "wikiItemId": (th or {}).get("itemId"),
            "desc": re.sub(r"<[^>]+>", "", t(td.get("description")) or "") or None,
            "abilities": abilities,
            "deathTips": death_tips,
            "distributions": distributions,
            "dangerous": e.get("isDangerous", False),
            "superArmor": template.get("initialSuperArmor"),
            "maxResilience": template.get("maxResilience"),
            "resists": resists,
            "lvMax": {k: lv_max.get(k) for k in ("MaxHp", "Atk", "Def") if lv_max.get(k) is not None},
        })
    enemies.sort(key=lambda x: x["id"])
    return enemies


def write(payload: list[dict]) -> None:
    """每个敌人一个独立文件,按类型 EN slug 子目录存放(typeSlug 字段 = 子目录名)。

    index.json 只是清单:按 typeSlug 分组的敌人 id 列表;描述/能力/出没区域等
    一切内容都在子文件里,不在索引中重复。
    """
    def finalize(_rows: list, entries: list[dict]) -> dict:
        grouped: dict[str, list] = {}
        for e in entries:
            grouped.setdefault(e["typeSlug"], []).append(e["id"])
        return dict(sorted(grouped.items()))

    dump_dir(PRODUCT, payload, subdir=lambda e: e["typeSlug"],
             index_map=lambda e: e["id"], index_finalize=finalize)


def main(force: bool = False) -> None:
    raw = load_tables(REQUIRED_TABLES, force=force)
    threats = load_wiki_threats()
    payload = build(raw, I18n(raw[i18n_table()]), threats)
    write(payload)
    n_name = sum(1 for x in payload if x["name"] and x["name"] != x["id"])
    n_icon = sum(1 for x in payload if x["icon"])
    info(f"  显示名 {n_name}/{len(payload)} 条,Wiki 威胁 join {n_icon}/{len(payload)} 条"
         f"(威胁分区 {len(threats)} 条)")


if __name__ == "__main__":
    main()
