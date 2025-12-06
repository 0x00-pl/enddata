"""描述占位符回填共享工具:{key:fmt} → blackboard/values 实际数值(采集/分析共用)。

值来源约定(CLAUDE.md「描述占位符数值来源」):技能 → levels[].blackboard,
潜能 → potentials[].values,被动节点 → passiveSkillNodeInfo.values,
武器/套装 → SkillPatchTable blackboard。

解析规则:
    - fmt 为最后一个冒号后的模板(key 本身允许含冒号,如 floor:deck_wisd):
      '0' 整数 / '0%'·'0.0%' 百分比(值×100)/ '0.0'·'0.00' 定长小数 /
      '0.##' 与缺省(裸 {键})去尾零
    - key 可为算式:项 = 数字或 values 键(* 连乘),项间 +/- 求和,
      如 duration-1、1+corrupt_rate、-ignore_fire_resist、atk_scale*max_stack
    - 键名缺位的无名参数:values 恰有一个 paramN 条目时以其顶替未知键名
      参与算式(如 coolDown→param2、1-costvalue→1-param1);零个或多个
      paramN 无法对应,保留占位符原样
    - 查不到的键(含表内带尾随空格的脏数据,先 strip 再查)与解析到 0 的
      条目一律视为缺数:占位符维持原样,键名可经 missing 列表收集,
      未传 missing 时直接抛 ValueError(见 fill_placeholders)
"""

from __future__ import annotations

import re

# 两种形态:{key:fmt} 与裸 {key}(fmt 缺省)。fmt 段不允许再含冒号,回溯即可让
# key 吃掉中间的冒号(如 floor:deck_wisd:0 → key='floor:deck_wisd'、fmt='0')
PLACEHOLDER_RE = re.compile(r"\{\s*([^{}]+?)\s*(?::\s*([^{}:]+?)\s*)?\}")
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_PARAM_RE = re.compile(r"param\d+\Z")


def strip_rich_tags(text: str | None) -> str | None:
    """剥离富文本标签(<@ba.vup> 着色、<#ba.*> 状态图标引用、</>)。"""
    return _TAG_RE.sub("", text) if text else text


def _fmt_value(value: float, spec: str | None) -> str:
    """按 fmt 模板渲染数值:百分比先 ×100;缺省与 0.## 去尾零,其余定长。"""
    if spec in (None, "", "0.##"):
        out = f"{value:.2f}".rstrip("0").rstrip(".")
        return out or "0"
    if spec.endswith("%"):
        num = spec[:-1]
        decimals = len(num.split(".")[-1]) if "." in num else 0
        return f"{value * 100:.{decimals}f}%"
    if "." in spec:
        return f"{value:.{len(spec.split('.')[-1])}f}"
    return f"{value:.0f}"


def _eval_expr(expr: str, values: dict, fallback: float | None = None) -> float | None:
    """算式求值:项为数字或 values 键(* 连乘),项间 +/- 求和;查不到返回 None。

    fallback 供无名参数回退:未知键名以该值顶替;出现多个不同未知键名时
    无法唯一对应,返回 None。
    """
    total, sign, unknown = 0.0, 1.0, set()
    for term in re.split(r"([+-])", expr):
        term = term.strip()
        if not term:
            continue
        if term == "+":
            continue
        if term == "-":
            sign = -1.0
            continue
        v = 1.0
        for k in term.split("*"):
            k = k.strip()
            if _NUM_RE.fullmatch(k):
                v *= float(k)
                continue
            x = values.get(k, values.get(k.strip()))
            if not isinstance(x, (int, float)):
                if fallback is None:
                    return None
                unknown.add(k)
                x = fallback
            v *= x
        total += sign * v
        sign = 1.0
    return total if len(unknown) <= 1 else None


def resolve_value(key: str, values: dict) -> float | None:
    """占位符键(同名或算式)→ 数值;查不到返回 None。"""
    v = values.get(key, values.get(key.strip()))
    if isinstance(v, (int, float)):
        return float(v)
    value = _eval_expr(key, values)
    if value is not None:
        return value
    params = [x for k, x in values.items() if _PARAM_RE.match(k)]
    if len(params) == 1:
        return _eval_expr(key, values, fallback=params[0])
    return None


def fill_placeholders(text: str | None, values: dict, *,
                      missing: list[str] | None = None) -> str | None:
    """回填 {key:fmt} 占位符为实际值;查不到或解析到 0 一律视为缺数。

    缺数的占位符维持原样不替换(不产出「+0%」一类误导文案):传 missing
    清单时收集键名交由调用方汇总,未传则直接抛 ValueError。
    """
    if not text or "{" not in text:
        return text

    def repl(m: re.Match) -> str:
        value = resolve_value(m.group(1), values)
        if value is None or value == 0:
            if missing is None:
                raise ValueError(f"占位符无法解析: {m.group(0)}")
            missing.append(m.group(1).strip())
            return m.group(0)
        return _fmt_value(value, m.group(2))

    return PLACEHOLDER_RE.sub(repl, text)


def fill_desc(text: str | None, values: dict, **kw) -> str | None:
    """采集侧一步到位:剥富文本标签 + 回填占位符 + 去首尾空白。"""
    if not text:
        return None
    out = fill_placeholders(strip_rich_tags(text), values, **kw)
    return out.strip() if out else out
