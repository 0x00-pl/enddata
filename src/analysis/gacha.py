"""抽卡分析:寻访概率计算(卡池状态机模拟 + 解析分布,两套实现互相对拍)。

架构:每类卡池一个子类,继承 GachaPool 基类;基类 pull() 实现单抽状态机 ——
每抽一次即更新全局状态(GachaGlobalState:6★/5★保底计数 + 已拥有干员,同类型
池之间继承)与当前卡池状态(GachaPool 实例属性:本池累计寻访/当期UP获得/赠送
十连档位,即「当期卡池状态」)。池差异全部以类属性表达(概率字段名与源表
GachaCharPoolTypeTable 一致,单位 = 每百万分率 pm;采集侧暂无 gacha 数据集,
参数内嵌注明出处)。POOLS 按游戏版本给出每期卡池对象(配置单例,模拟前 reset)。

规则口径(限定寻访;源表 type 0 + GachaCharPoolContentTable 名单 + 规则文字):
    单抽基础概率  6★ 0.8% / 5★ 8% / 4★ 91.2%
    6★概率提升    保底周期第66抽起每抽 +5 个百分点(第66抽 5.8% … 第79抽 70.8%)
    6★保底        周期第80抽必出(softGuarantee;shareSoftGuarantee=true → 全局继承)
    6★分配        命中6★后:50% 当期干员(guarantee_id,isHardGuaranteeItem)+
                  25% 往期两期限定干员平分(rateup_ids,即卡池名单里的前两期
                  当期角色)+ 25% 名单内常驻6★平分(standard_ids);
                  份额空缺时并入常驻段(复刻池无往期 → 50% 复刻角色 + 50% 常驻)
    6★硬保底      首个**当期**干员前,本池累计第120抽必得当期干员(hardGuarantee,
                  不跨期继承;获得当期干员后失效 —— up_got 只在命中 guarantee 时
                  计数;往期/常驻6★不触发也不推迟它)。复刻寻访例外:重构寻访
                  重新上线时整体继承上一轮累计进度(含硬保底),见 RerunGacha
    十连保底      每10次有效寻访必出5★及以上(6★同样满足并重置计数)
    赠送十连      本池累计30次赠当期十连(freeTenPullRewardPullCount=[30,0,0]):
                  按基础概率出卡、与保底完全互不影响(不推进也不重置主保底)、
                  不计入累计寻访次数 → 付费抽数 = 有效抽数,必领必用时等价于
                  在付费第30抽后插入一段独立10连
    累计60次      赠下期十连券(testimonialPullCount=60):入全局状态
                  (next_ten_tickets[pool_id],绑定档期上下一期限定池,仅该池
                  可用),下一期限定池开局兑换;为正常寻访口径(计保底与
                  累计,与 30 抽加急招募的赠送口径不同),十连必须整抽
    其他          每240次赠UP潜能信物(intervalAutoRewardPerPullCount,只影响期望
                  份数,不改分布);保障配额按星级累积(4★+2/5★+20/6★+200 厘抽,
                  期望每抽≈5厘,复刻与联合池翻倍),满 250 厘自动兑 1 张限定池
                  寻访券(免费获得、照常计保底,约 2% 回馈);
                  常驻池累计300次自选六星(choicePackPullCount);
                  联合寻访(辉光庆典) 独立保底、无120必得;6★分配 50% 双UP平分 +
    50% 名单内常驻平分;30/60/120抽累计赠礼见 JointGacha 注释

卡池名单(six 池内容)= 常驻6★ + 当期 + 前两期当期角色,来自
GachaCharPoolContentTable 快照;1.0 开服期名单同样按快照(含同期/后续期角色)。

两套实现:
    ① simulate()        驱动 GachaPool.pull() 的规则直演(固定种子可复现)
    ② 解析函数          逐抽概率表 + 「当期干员首达」分布 DP(50%/6★ 段)+
                        赠送十连并入;全图鉴抽数 = 单池当期首达分布卷积
                        (未计顺路获得的上界,模拟为准)
    ③ run()             控制台输出对拍偏差,报告写入 reports/gacha-analysis.md
                        (版本卡池安排 + 全图鉴所需抽数统计)

抽卡策略:策略函数 strategy(pool, g) -> bool 以「当期卡池状态(大保底计数
pulls 等)+ 全局状态(已拥有干员 owned、累计小保底 pity)」决定本抽是否继续,
run_banner() 按策略驱动一个卡池。

用法:
    poetry run enddata analysis gacha    # 或 analysis.gacha.main()
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from itertools import accumulate

from tools.tables import DATA_DIR, REPORTS_DIR

# ---------------------------------------------------------------- 常量
RATE_SCALE = 1_000_000        # 源表概率单位:每百万分率
FREE_TEN_SIZE = 10            # 赠送十连规模
QUOTA_DUP_6STAR = 100         # 重复获取相同6星干员:+50 官方配额(并转化信物×1)
QUOTA_DUP_5STAR = 20          # 重复获取相同5星干员:+10 官方配额(并转化信物×1)
QUOTA_TICKET_COST = 50        # 兑换 1 张限定池寻访券所需配额(= 25 官方配额 = 1 抽)
# 基础每寻访配额(+1)为辉光庆典等特殊寻访的额外规则,普通限定池没有
VERSION_DAYS = 42             # 兜底:最新版本的天数估算(无后续日期可推时)
PASS_DAILY_CRYSTAL = 200      # 小月卡每日嵌晶玉(与天数相关)
# 版本上线日期(社区资料/估算;锚点:2026-01-24 开服、2026-02-24 信使池结束、
# 2026-08-20 前后 1.5 开放——与 1.4 统计 09-01 完结吻合)。版本天数由相邻
# 上线日期差推导,日期偏差会直接传导到小月卡累计。
VERSION_START_DATES: dict[str, str] = {
    "1.0": "2026-01-24", "1.1": "2026-03-05", "1.2": "2026-04-16",
    "1.3": "2026-05-28", "1.4": "2026-07-09", "1.5": "2026-08-20",
    "1.5.2": "2026-09-17",
}
CRYSTAL_PER_PULL = 500        # 每次寻访所需嵌晶玉
STONE_PER_PULL = 75           # 1 衍质源石 = 75 嵌晶玉
PASS_PROTOCOL_REFUND = 36     # 协议定制(大小月卡独有):返还衍质源石×36
    # 注:源石配给(消耗 29/返还 32 衍质源石)零氪玩家同样完成,已含在
    # VERSION_FREE_PULLS 统计中,不在大小月卡增量里重复计算。
BANNER_TICKETS = 5            # 每个限定卡池开启时可购买的当期卡池券张数
SHARE_CURRENT = 0.50          # 6★ 命中后:当期干员份额
SHARE_RATEUP = 0.25           # 往期两期限定干员合计份额(平分)
SHARE_STANDARD = 0.25         # 名单内常驻6★合计份额(平分)
DEFAULT_SEED = 20260918       # 模拟固定种子(可复现,对拍口径稳定)
DEFAULT_TRIALS = 30_000       # 单池保底分布模拟次数
COLLECTION_TRIALS = 8_000     # 全图鉴抽数模拟次数
REPORT_PATH = REPORTS_DIR / "gacha-analysis.md"


# ---------------------------------------------------------------- 状态与结果
@dataclass
class GachaGlobalState:
    """全局(玩家级)状态:shareSoftGuarantee=true 的同类型池之间继承。

    pity = 6★保底计数(已连续未出6★的有效寻访数,下一抽是周期第 pity+1 抽,
    即「累计小保底」);five_pity = 5★及以上十连保底计数;owned = 已拥有干员
    (任何6★命中时由 pull() 写入)。total_pulls/free_pulls/paid_pulls = 累计
    经历的抽数与其中赠送/付费拆分(赠送抽数计入总抽数但不推进保底);
    池重置(reset)不影响本状态。
    """

    pity: int = 0
    five_pity: int = 0
    owned: set[str] = field(default_factory=set)
    total_pulls: int = 0            # 累计经历抽数(含赠送)
    free_pulls: int = 0             # 其中赠送抽数
    paid_pulls: int = 0             # 其中付费抽数
    quota: int = 0                  # 保障配额存量(单位 = 厘抽,即 0.001 抽价值)
    quota_tickets: int = 0          # 配额兑换的限定池寻访券(单抽,任意限定池)
    next_ten_tickets: dict[str, int] = field(default_factory=dict)
    # 下期限定十连券:pool_id → 张数。发券时绑定档期上的下一个限定池,
    # 仅该池开局可兑换(id 校验),不可转移到别的池使用。
    rerun_progress: dict[str, dict] = field(default_factory=dict)
    # 重构寻访(RerunGacha)跨轮继承的进度:pool_id -> {pulls, up_got,
    # free_ten_left, free_ten_granted, next_ticket_granted}。限定寻访每期
    # 全新、不入此表;重构寻访重新上线时由此恢复(官方「已从历史重构寻访
    # 中累计继承 N 次寻访记录」)。


@dataclass(frozen=True)
class Pull:
    """一次寻访的结果。"""

    star: int              # 星级 6/5/4
    up: bool               # 是否UP干员(当期或往期限定;常驻6★为 False)
    free: bool             # 是否赠送抽数(不计保底、不计累计)
    pity: int              # 抽后全局 6★保底计数
    pulls: int             # 抽后本池累计寻访次数(赠送抽数不增;付费轴)
    up_id: str | None = None  # 命中的6★干员(UP干员或常驻;5★/4★为 None)


# ---------------------------------------------------------------- 卡池基类
class GachaPool:
    """寻访池基类:pull() 实现单抽状态机,池差异以类属性表达(默认 = 限定寻访)。

    当期卡池状态 = 实例属性(pulls 累计寻访即「大保底计数」、up_got 已获得当期
    干员、free_ten_* 赠送十连档位);池配置(pool_id/name/干员名单)在构造时注入,
    reset() 重置状态供模拟复用(POOLS 中的对象为配置单例)。

    类属性(概率单位 pm;字段名与 GachaCharPoolTypeTable 一致):
        star6BaseRate / star5BaseRate      6★/5★ 单抽基础概率
        star6RatePromotePullCount / Value  6★概率提升段(自第 N 抽起每抽 +V)
        softGuarantee                      6★保底周期长度(必出)
        hardGuarantee                      首个当期干员前本池累计必得的抽数(0 = 无)
        upRate                             6★中「当期+往期」UP干员合计占比参考
        star5SoftGuarantee                 每 N 次有效寻访必出5★及以上
        freeTenGrantAt                     本池累计 N 次赠当期十连(0 = 无)
        nextTenTicketAt                    本池累计 N 次赠下期十连券(0 = 无)

    实例配置:
        guarantee_id  当期干员(120硬保底对象;联合池为空)
        rateup_ids    名单内往期限定干员(25% 段平分)
        standard_ids  名单内常驻6★(25% 段平分)
    """

    star6BaseRate: int = 8_000
    star5BaseRate: int = 80_000
    star6RatePromotePullCount: tuple[int, ...] = (66,)
    star6RatePromoteValue: tuple[int, ...] = (50_000,)
    softGuarantee: int = 80
    hardGuarantee: int = 120
    upRate: int = 500_000
    star5SoftGuarantee: int = 10
    freeTenGrantAt: int = 30
    nextTenTicketAt: int = 60
    intervalRewardAt: int = 240    # 每累计 N 次赠当期UP潜能信物(0 = 无)
    quota_base: int = 0            # 每寻访基础配额(特殊寻访 +1,普通限定 0)
    pool_name: str = "寻访池"

    # 抽取优先级:赠送十连 → 当期卡池券(每池开启 BANNER_TICKETS 张)→
    # 配额兑换券 → 付费寻访。
    progress_in_global: bool = False  # 进度入全局状态跨轮继承(重构寻访 = True)
    next_pool_id: str = ""            # 下期券绑定的池 id(POOLS 档期推导)

    def __init__(self, global_state: GachaGlobalState | None = None,
                 rng: random.Random | None = None, *,
                 pool_id: str = "", name: str = "",
                 up_ids: tuple[str, ...] = (),
                 guarantee_id: str = "",
                 rateup_ids: tuple[str, ...] = (),
                 standard_ids: tuple[str, ...] = (),
                 sign_in_tickets: int = 5):
        self.g = global_state or GachaGlobalState()
        self.rng = rng or random.Random()
        self.pool_id = pool_id
        self.name = name
        self.up_ids = tuple(up_ids) or \
            ((guarantee_id,) if guarantee_id else ())  # 当期段:50% 平分对象
        self.guarantee_id = guarantee_id               # 120硬保底对象(联合池为空)
        self.rateup_ids = rateup_ids                   # 往期限定段:25% 平分
        self.standard_ids = standard_ids or _STD6      # 名单内常驻6★:25% 平分
        self.sign_in_tickets = sign_in_tickets         # 登录签到送当期凭证张数
        self.pulls = 0                 # 本池累计有效(付费)寻访 = 大保底计数
        self.up_got = 0                # 已获得当期干员次数(硬保底上限1)
        self.free_ten_left = 0         # 待抽的赠送十连余量
        self.free_ten_granted = False  # 累计30次赠十连是否已发
        self.next_ticket_granted = False  # 累计60次赠下期十连券是否已发
        self.interval_got = 0           # 已领取的 240 抽循环潜能信物数
        self.exchange_left = 0          # 开局兑换的配额券余量(正常寻访)
        # 当期免费券 = 可购 5 张 + 登录签到送当期凭证(缺签到的池按实际张数)
        self.banner_ticket_left = BANNER_TICKETS + self.sign_in_tickets

    def reset(self, global_state: GachaGlobalState | None = None) -> None:
        """重置当期卡池状态(配置保留;可注入新的全局状态)。

        普通池清零;重构寻访(progress_in_global)从全局状态恢复上一轮进度
        —— 无存档则视为首轮,同样清零,本轮进度随抽随存(_persist_progress)。
        """
        if global_state is not None:
            self.g = global_state
        saved = self.g.rerun_progress.get(self.pool_id) \
            if self.progress_in_global else None
        if saved:
            self.pulls = saved["pulls"]
            self.up_got = saved["up_got"]
            self.free_ten_left = saved["free_ten_left"]
            self.free_ten_granted = saved["free_ten_granted"]
            self.next_ticket_granted = saved["next_ticket_granted"]
            self.interval_got = saved["interval_got"]
        else:
            self.pulls = 0
            self.up_got = 0
            self.free_ten_left = 0
            self.free_ten_granted = False
            self.next_ticket_granted = False
            self.interval_got = 0
        self.exchange_left = 0
        self.banner_ticket_left = BANNER_TICKETS + self.sign_in_tickets

    def _persist_progress(self) -> None:
        """重构寻访:当前进度写回全局状态,供下次卡池(下一轮)继承。"""
        if self.progress_in_global:
            self.g.rerun_progress[self.pool_id] = {
                "pulls": self.pulls, "up_got": self.up_got,
                "free_ten_left": self.free_ten_left,
                "free_ten_granted": self.free_ten_granted,
                "next_ticket_granted": self.next_ticket_granted,
                "interval_got": self.interval_got,
            }

    # -- 概率 --
    @classmethod
    def star6_rate(cls, cycle: int) -> float:
        """保底周期第 cycle 抽的6★概率(含提升段与保底必出;按调用子类参数)。"""
        r = cls.star6BaseRate
        for start, val in zip(cls.star6RatePromotePullCount,
                              cls.star6RatePromoteValue):
            if cycle >= start:
                r += val * (cycle - start + 1)
        if cycle >= cls.softGuarantee:
            r = RATE_SCALE
        return min(r, RATE_SCALE) / RATE_SCALE

    # -- 单抽状态机 --
    def pull(self) -> Pull:
        """单次寻访:优先消耗赠送抽数(基础概率,不动任何计数);否则为有效
        寻访 —— 推进全局保底计数与本池累计,结算星级/干员与累计赠礼。"""
        g, rng = self.g, self.rng
        if self.free_ten_left:
            self.free_ten_left -= 1
            g.total_pulls += 1
            g.free_pulls += 1
            star, six_id = self._free_star(), None
            dup = False
            if star == 6:
                six_id = self._pick_six()
                dup = six_id in g.owned             # 重复获取(第 2 次及后续)
                g.owned.add(six_id)
            self._grant_quota(star, six_id, dup)
            self._persist_progress()
            return Pull(star, star == 6, True, g.pity, self.pulls, six_id)
        free_kind = None                  # 免费券:当期卡池券 / 配额兑换券
        if self.banner_ticket_left:
            self.banner_ticket_left -= 1
            free_kind = "banner"
        elif self.exchange_left:
            self.exchange_left -= 1
            free_kind = "exchange"
        self.pulls += 1                   # 免费券与付费同权:计入本池累计,
        g.total_pulls += 1                # 推进 120 硬保底与 30/60/240 赠礼档
        if free_kind:
            g.free_pulls += 1
        else:
            g.paid_pulls += 1
        g.pity += 1                                 # 抽后即本抽的周期序数
        g.five_pity += 1
        forced = (bool(self.hardGuarantee) and bool(self.guarantee_id)
                  and self.up_got == 0 and self.pulls >= self.hardGuarantee)
        six_id: str | None
        dup = False
        if forced or g.pity >= self.softGuarantee \
                or rng.random() < self.star6_rate(g.pity):
            g.pity = 0
            g.five_pity = 0
            six_id = self.guarantee_id if forced else self._pick_six()
            dup = six_id in g.owned                 # 第 2 次及后续获取
            g.owned.add(six_id)
            if six_id == self.guarantee_id:
                self.up_got += 1                    # 当期干员到手的唯一途径
            star = 6
        elif (g.five_pity >= self.star5SoftGuarantee
              or rng.random() < self.star5BaseRate / RATE_SCALE):
            g.five_pity = 0
            six_id = self._pick_five()              # 5★ 按已全图鉴:出现即重复转化
            dup = True
            star = 5
        else:
            six_id = None
            star = 4
        self._grant()
        self._grant_quota(star, six_id, dup)
        self._persist_progress()
        return Pull(star, star == 6 and six_id in self.up_ids,
                    False, g.pity, self.pulls, six_id)

    def _pick_five(self) -> str:
        """5★ 命中的具体干员:按已全图鉴计算,从常驻 5★ 名单均匀随机
        (每次出现均转化为对应干员信物×1 + 保障配额×10)。"""
        return _STD5[self.rng.randrange(len(_STD5))]

    @staticmethod
    def _pick_segment(x: float, pool: GachaPool) -> str:
        """6★ 命中后的具体干员:50% 当期段平分(up_ids,联合池即双UP)+
        25% 往期限定平分 + 25% 名单内常驻平分;份额空缺时并入常驻段。"""
        if x < SHARE_CURRENT and pool.up_ids:
            return pool.up_ids[pool.rng.randrange(len(pool.up_ids))]
        if x < SHARE_CURRENT + SHARE_RATEUP and pool.rateup_ids:
            return pool.rateup_ids[pool.rng.randrange(len(pool.rateup_ids))]
        return pool.standard_ids[pool.rng.randrange(len(pool.standard_ids))]

    def _pick_six(self) -> str:
        return self._pick_segment(self.rng.random(), self)

    def _grant_quota(self, star: int, six_id: str | None, dup: bool) -> None:
        """保障配额(官方规则):普通限定池仅来自重复干员转化;特殊寻访
        (辉光庆典等)每寻访额外 +1 基础配额(quota_base)。第 2 次及后续
        获取相同 6★/5★ 干员额外 +50/+10 并转化为对应干员信物×1(信物同时
        计入该干员潜能份数)。满 QUOTA_TICKET_COST 自动兑换限定池寻访券
        (正常寻访口径)。"""
        gain = self.quota_base
        if dup and star == 6:
            gain += QUOTA_DUP_6STAR
        elif dup and star == 5:
            gain += QUOTA_DUP_5STAR
        self.g.quota += gain
        while self.g.quota >= QUOTA_TICKET_COST:
            self.g.quota -= QUOTA_TICKET_COST
            self.g.quota_tickets += 1

    def _free_star(self) -> int:
        """赠送抽数的星级:基础概率独立判定(无十连保底,不动任何计数)。"""
        x = self.rng.random()
        if x < self.star6BaseRate / RATE_SCALE:
            return 6
        if x < (self.star6BaseRate + self.star5BaseRate) / RATE_SCALE:
            return 5
        return 4

    def _grant(self) -> None:
        """累计赠礼结算(只数有效寻访):30次赠当期十连(加急招募,赠送
        口径,由后续 pull() 优先消耗);60次赠下期十连券(入全局状态,
        下一期限定池开局兑换,正常寻访口径、整抽使用)。"""
        if (self.freeTenGrantAt and not self.free_ten_granted
                and self.pulls >= self.freeTenGrantAt):
            self.free_ten_granted = True
            self.free_ten_left += FREE_TEN_SIZE
        if (self.nextTenTicketAt and not self.next_ticket_granted
                and self.pulls >= self.nextTenTicketAt):
            self.next_ticket_granted = True
            if self.next_pool_id:      # 券绑定下期限定池,仅该池可用
                self.g.next_ten_tickets[self.next_pool_id] = \
                    self.g.next_ten_tickets.get(self.next_pool_id, 0) + 1
        while (self.intervalRewardAt
               and self.pulls >= (self.interval_got + 1) * self.intervalRewardAt):
            self.interval_got += 1     # 循环潜能信物:额外当期份,不影响保底
            if self.guarantee_id:
                self.g.owned.add(self.guarantee_id)


# ---------------------------------------------------------------- 五类卡池
class LimitedGacha(GachaPool):      # type 0 限定寻访:参数即基类默认
    pool_name = "限定寻访"


class RerunGacha(LimitedGacha):     # type 4 复刻寻访(官方「重构寻访」):名单仅
    pool_name = "复刻寻访"          # 复刻角色(无往期段,25% 份额并入常驻 → 50% 复刻
    # 角色 + 50% 常驻)。**保底/进度继承规则与限定寻访不同**:重构寻访重新上线时,
    # 上一轮的累计寻访记录整体继承(gachaPoolVersion ≥ 2 时弹「已从历史重构寻访
    # 『%s』中累计继承 N 次寻访记录」确认,ConfirmGachaPoolVersion)—— 120 硬保底
    # 进度、加急招募(30抽)档、循环信物计数全部带过来;限定寻访则每期全新、
    # 硬保底不跨期。进度保存在全局状态 rerun_progress[pool_id],reset 时恢复、
    # 随抽存档(progress_in_global = True)。
    progress_in_global = True
    quota_base = 1                  # 特殊寻访:每寻访额外 +1 基础配额(重构寻访同规)


class JointGacha(GachaPool):        # type 3 特殊寻访(1.2 首个复刻池「辉光庆典」):
    pool_name = "联合寻访"          # 独立保底计数(不与常驻/限定池互通,表内
    hardGuarantee = 0               # shareSoftGuarantee=false);无「120必得当期」,
    nextTenTicketAt = 0             # 6★分配不走通用 50/25/25 —— 重载见 _pick_six。
    quota_base = 1                  # 特殊寻访:每寻访额外 +1 基础配额
    intervalRewardAt = 0            # 累计赠礼(仅限一次,不影响出货分布):30抽赠
    # 加急招募十连(不计保底,同样产出保障配额);60抽赠基础寻访凭证×10(用于
    # 常驻池,故不发下期券);120抽赠调用凭证(当期4名干员任选其一,不占保底);
    # 120抽起循环信物自选。

    def _pick_six(self) -> str:
        """辉光庆典分配:50% 双UP平分(莱万汀/洁尔佩塔各25%)+ 50% 名单内
        常驻平分(艾尔黛拉/骏卫各25%;无往期限定段)。"""
        ids = self.up_ids if self.rng.random() < SHARE_CURRENT \
            else self.standard_ids
        return ids[self.rng.randrange(len(ids))]


class StandardGacha(GachaPool):     # type 2 常驻寻访:无UP(累计300次自选六星)
    pool_name = "常驻寻访"
    intervalRewardAt = 0
    hardGuarantee = 0
    upRate = 0
    freeTenGrantAt = 0
    nextTenTicketAt = 0


class BeginnerGacha(GachaPool):     # type 1 新手寻访:无提升段,40抽封顶必出6★
    pool_name = "新手寻访"
    intervalRewardAt = 0
    star6RatePromotePullCount = ()
    star6RatePromoteValue = ()
    softGuarantee = 40
    hardGuarantee = 0
    upRate = 0
    freeTenGrantAt = 0
    nextTenTicketAt = 0


# 各版本 UP 卡池安排(配置单例;源 = TableCfg/GachaCharPoolTable 快照 +
# GachaCharPoolContentTable 6★ 名单,池名经 I18nTextTable_CN 反查。
# up_ids = 当期段(50% 平分对象;限定/复刻池即当期干员,联合池为双UP);
# rateup_ids = 名单内往期限定干员(前两期当期角色;1.0 开服期名单按快照);
# standard_ids = 名单内常驻6★,缺省为限定池标准 5 人名单)。
_STD6 = ("chr_0009_azrila", "chr_0015_lifeng", "chr_0025_ardelia",
         "chr_0026_lastrite", "chr_0029_pograni")
# 5★ 干员名单(各池一致;源 = GachaCharPoolContentTable starLevel=5)
_STD5 = ("chr_0004_pelica", "chr_0005_chen", "chr_0006_wolfgd", "chr_0007_ikut",
         "chr_0011_seraph", "chr_0012_avywen", "chr_0014_aurora",
         "chr_0018_dapan", "chr_0024_deepfin")
POOLS: dict[str, list[GachaPool]] = {
    # 1.0 开服期按时间口径:往期段 = 已结束的前两期首发池(快照名单另含
    # 后续期角色,属数据怪象,不采用 —— 否则会产生虚假的顺路收益)
    "1.0": [
        LimitedGacha(pool_id="special_1_0_1", name="熔火灼痕",
                     guarantee_id="chr_0016_laevat",                    # 莱万汀
                     rateup_ids=()),
        LimitedGacha(pool_id="special_1_0_2", name="热烈色彩",
                     guarantee_id="chr_0017_yvonne",                    # 伊冯
                     rateup_ids=("chr_0016_laevat",),
                     sign_in_tickets=0),                                # 快照无签到活动
        LimitedGacha(pool_id="special_1_0_3", name="轻飘飘的信使",
                     guarantee_id="chr_0013_aglina",                    # 洁尔佩塔
                     rateup_ids=("chr_0016_laevat", "chr_0017_yvonne")),
    ],
    "1.1": [
        LimitedGacha(pool_id="special_1_1_1", name="河流的女儿",
                     guarantee_id="chr_0027_tangtang",                  # 汤汤
                     rateup_ids=("chr_0017_yvonne", "chr_0013_aglina")),
        LimitedGacha(pool_id="special_1_1_2", name="狼珀",
                     guarantee_id="chr_0028_wulfa",                     # 洛茜
                     rateup_ids=("chr_0027_tangtang", "chr_0017_yvonne")),
    ],
    "1.2": [
        LimitedGacha(pool_id="special_1_2_1", name="春雷动,万物生",
                     guarantee_id="chr_0030_zhuangfy",                  # 庄方宜
                     rateup_ids=("chr_0028_wulfa", "chr_0027_tangtang")),
        JointGacha(pool_id="joint_1_2_2", name="辉光庆典",
                   up_ids=("chr_0016_laevat", "chr_0013_aglina"),       # 莱万汀、洁尔佩塔
                   standard_ids=("chr_0025_ardelia", "chr_0029_pograni")),  # 艾尔黛拉、骏卫
    ],
    "1.3": [
        LimitedGacha(pool_id="special_1_3_1", name="拳出无悔",
                     guarantee_id="chr_0031_mifu",                      # 弭弗
                     rateup_ids=("chr_0030_zhuangfy", "chr_0028_wulfa")),
        LimitedGacha(pool_id="special_1_3_2", name="逐罪者",
                     guarantee_id="chr_0033_camille",                   # 卡缪
                     rateup_ids=("chr_0031_mifu", "chr_0030_zhuangfy")),
    ],
    "1.4": [
        LimitedGacha(pool_id="special_1_4_1", name="临渊望北",
                     guarantee_id="chr_0032_lizhiyan",                  # 诀
                     rateup_ids=("chr_0033_camille", "chr_0031_mifu")),
        LimitedGacha(pool_id="special_1_4_2", name="晨星于此闪耀",
                     guarantee_id="chr_0035_liino",                     # 梨诺
                     rateup_ids=("chr_0032_lizhiyan", "chr_0033_camille")),
    ],
    "1.5": [
        LimitedGacha(pool_id="special_1_5_1", name="冬猎",
                     guarantee_id="chr_0034_typhoea",                   # 提弗洛斯
                     rateup_ids=("chr_0035_liino", "chr_0032_lizhiyan")),
    ],
    "1.5.2": [
        RerunGacha(pool_id="rerun_chr_yvonne", name="绚丽异彩",
                   guarantee_id="chr_0017_yvonne",                      # 伊冯(复刻)
                   standard_ids=("chr_0009_azrila", "chr_0015_lifeng",
                                 "chr_0025_ardelia", "chr_0029_pograni")),
    ],
}


# 下期十连券绑定:按档期顺序,每个限定/复刻池的 60 抽档券对应下一个
# 上线的限定类池(末位无下期,不发);联合寻访不发下期券。
_RERUN_SEQ = [p for pools in POOLS.values() for p in pools
              if isinstance(p, LimitedGacha)]
for _cur, _nxt in zip(_RERUN_SEQ, _RERUN_SEQ[1:]):
    _cur.next_pool_id = _nxt.pool_id


VERSION_FREE_PULLS: dict[str, int] = {
    "1.0": 267, "1.1": 96, "1.2": 114, "1.3": 82, "1.4": 111, "1.5": 85,
}


def total_free_pulls(version: str) -> int:
    """开服至 version(含)全勤可获得的累计免费寻访次数。"""
    return sum(n for v, n in VERSION_FREE_PULLS.items()
               if version_key(v) <= version_key(version))


def total_pass_pulls(version: str) -> int:
    """开服至 version(含),大小月卡玩家可获得的累计寻访次数:
    零氪累计 + 小月卡(每日嵌晶玉 × 版本天数)+ 协议定制(+36 源石,
    按 1:75 折算嵌晶玉后除以单抽消耗)。源石配给(−29/+32)零氪玩家同样
    完成、已含在零氪统计,不重复计入。版本天数由 VERSION_START_DATES
    相邻上线日期差推导(末版兜底 VERSION_DAYS)。"""
    keys = [v for v in sorted(VERSION_FREE_PULLS, key=version_key)
            if version_key(v) <= version_key(version)]
    starts = {v: date.fromisoformat(d) for v, d in VERSION_START_DATES.items()}
    total = 0.0
    for i, v in enumerate(keys):
        nxt = keys[i + 1] if i + 1 < len(keys) else None
        if nxt:
            days = (starts[nxt] - starts[v]).days
        else:
            later = [s for s in sorted(starts, key=version_key)
                     if version_key(s) > version_key(v)]
            days = ((starts[min(later, key=version_key)] - starts[v]).days
                    if later else VERSION_DAYS)
        per_version = (days * PASS_DAILY_CRYSTAL / CRYSTAL_PER_PULL
                       + PASS_PROTOCOL_REFUND * STONE_PER_PULL / CRYSTAL_PER_PULL)
        total += VERSION_FREE_PULLS[v] + per_version
    return round(total)


# ---------------------------------------------------------------- 抽卡策略
Strategy = Callable[[GachaPool, GachaGlobalState], bool]
"""策略函数:(当期卡池状态 GachaPool, 全局状态 GachaGlobalState) -> 本抽是否继续。"""


def collect_missing(pool: GachaPool, g: GachaGlobalState) -> tuple[str, ...]:
    """本池限定UP(up_ids:限定/复刻池的当期干员、联合池的双UP)中尚未拥有的
    干员 —— 常驻6★不在目标内;池内没有限定UP时返回空。"""
    return tuple(u for u in pool.up_ids if u not in g.owned)


def strategy_until_owned(pool: GachaPool, g: GachaGlobalState) -> bool:
    """图鉴策略(无预算上限):只追限定UP,不计常驻6★ —— 本池有限定UP
    且未拿齐就继续;拿齐,或池内本就没有限定UP,即停(不抽)。"""
    return bool(collect_missing(pool, g))


def strategy_until_owned_60(pool: GachaPool, g: GachaGlobalState) -> bool:
    """图鉴策略 + 60 档补抽:目标未拿齐就继续;拿齐后,若本池累计已达
    50 抽(补 ≤10 抽可换 10 张正常口径下期券,总口径不亏),继续抽满 60
    触发下期券档;累计不足 50 则停(补抽净亏)。"""
    if collect_missing(pool, g):
        return True
    threshold = pool.nextTenTicketAt - FREE_TEN_SIZE
    return bool(pool.nextTenTicketAt and pool.up_got
                and pool.pulls >= threshold
                and pool.pulls < pool.nextTenTicketAt)


def run_banner(pool: GachaPool, strategy: Strategy) -> list[Pull]:
    """按策略抽一个卡池:每抽前询问策略(是否继续),返回全部寻访结果。

    60 抽档下期券在开局兑换,为**正常寻访口径**(计保底与累计);所有免费
    券(加急招募/下期券/配额券)必须整抽:免费段内策略不询问、连续抽完,
    不因中途拿到目标而只抽一半;跳过的池不兑换券。
    """
    out: list[Pull] = []
    if not strategy(pool, pool.g):
        return out                        # 本池目标已拿齐:跳过,不兑券
    if (pool.pulls == 0 and pool.free_ten_left == 0
            and pool.g.next_ten_tickets.get(pool.pool_id, 0) > 0):
        pool.g.next_ten_tickets[pool.pool_id] -= 1   # id 对应的券:本池开局兑换
        pool.exchange_left += FREE_TEN_SIZE           # 正常寻访口径:计保底
    if pool.pulls == 0 and pool.exchange_left == 0 and pool.g.quota_tickets > 0:
        pool.exchange_left = pool.g.quota_tickets     # 配额券:本池开局全兑
        pool.g.quota_tickets = 0
    while True:
        if pool.free_ten_left or pool.exchange_left:  # 免费券必须一起抽出
            out.append(pool.pull())
            continue
        if not strategy(pool, pool.g):
            break
        out.append(pool.pull())
    return out


# ---------------------------------------------------------------- ① 模拟
def simulate(pool: GachaPool, trials: int = DEFAULT_TRIALS,
             seed: int = DEFAULT_SEED, pity: int = 0) -> dict[str, list[float]]:
    """驱动 pull() 的规则直演:首个6★/5★+/当期干员的付费抽数经验分布。

    pool 为 POOLS 配置单例(每 trial 前重置);一趟寻访历史同时统计三个首达
    事件;「当期干员」需要 guarantee_id 与硬保底(联合池不统计,分布无界)。
    pity 表达入池时继承的6★保底。
    """
    rng = random.Random(seed)
    six = [0] * pool.softGuarantee
    five = [0] * pool.star5SoftGuarantee
    has_target = bool(pool.hardGuarantee and pool.guarantee_id)
    target = [0] * (pool.hardGuarantee if has_target else 0)
    for _ in range(trials):
        pool.reset(GachaGlobalState(pity=pity))
        pool.rng = rng
        pool.banner_ticket_left = pool.exchange_left = 0   # 对拍口径:纯保底机制
        got6 = got5 = gotu = False
        while not (got6 and got5 and (gotu or not has_target)):
            r = pool.pull()
            t = r.pulls
            if not got6 and r.star == 6:
                six[t - 1] += 1
                got6 = True
            if not got5 and r.star >= 5:
                five[t - 1] += 1
                got5 = True
            if has_target and not gotu and r.up_id == pool.guarantee_id:
                target[t - 1] += 1
                gotu = True
    out = {"six": [n / trials for n in six], "five": [n / trials for n in five]}
    if has_target:
        out["target"] = [n / trials for n in target]
    return out


# ---------------------------------------------------------------- ② 解析解
def six_star_rates(pool_cls: type[GachaPool], pity: int = 0) -> list[float]:
    """从继承的 pity 抽起,逐次有效寻访的6★概率表(末位为保底必出 1.0)。"""
    return ([pool_cls.star6_rate(pity + i + 1)
             for i in range(pool_cls.softGuarantee - pity)] or [1.0])


def first_pmf(rates: list[float]) -> list[float]:
    """给定逐抽概率,首次命中的精确分布(末抽吸收全部剩余质量)。"""
    pmf: list[float] = []
    surv = 1.0
    for r in rates:
        pmf.append(surv * r)
        surv *= 1.0 - r
    if pmf and surv > 0.0:
        pmf[-1] += surv
    return pmf


def six_star_first_pmf(pool_cls: type[GachaPool], pity: int = 0) -> list[float]:
    """首个6★的有效(付费)抽数分布(1..softGuarantee-pity,未并入赠送十连)。"""
    return first_pmf(six_star_rates(pool_cls, pity))


def five_star_first_pmf(pool_cls: type[GachaPool]) -> list[float]:
    """首个5★及以上的分布(每抽 8%+0.8%,第 star5SoftGuarantee 抽补足必出;
    6★同样满足「5★及以上」并重置计数,故逐抽概率恒为两者之和)。赠送十连
    不会介入 —— 首个5★+ 必然在前10次有效寻访内达成。"""
    rate = (pool_cls.star5BaseRate + pool_cls.star6BaseRate) / RATE_SCALE
    return first_pmf([rate] * (pool_cls.star5SoftGuarantee - 1) + [1.0])


def target_first_pmf(pool_cls: type[GachaPool], pity: int = 0) -> list[float]:
    """「当期干员首达」的有效(付费)抽数分布(1..hardGuarantee,末位硬保底
    吸收全部剩余质量;未并入赠送十连)。

    DP:按6★保底计数 c 展开概率质量 —— 命中6★时 50% 当期份额吸收(记入 pmf),
    往期/常驻段与6★未中一样继续(6★命中即保底清零);pity 表达跨池继承,
    hardGuarantee 计数不跨期继承,恒从 0 起
    (复刻寻访例外:跨复刻轮次继承,见 RerunGacha)。
    """
    if not pool_cls.hardGuarantee:
        raise ValueError("该池无当期干员硬保底,分布无界")
    rate = [pool_cls.star6_rate(c) for c in range(1, pool_cls.softGuarantee + 1)]
    share = SHARE_CURRENT
    pmf = [0.0] * pool_cls.hardGuarantee
    mass = [0.0] * pool_cls.softGuarantee
    mass[min(pity, pool_cls.softGuarantee - 1)] = 1.0
    for t in range(1, pool_cls.hardGuarantee + 1):
        nxt = [0.0] * pool_cls.softGuarantee
        hit = 0.0
        for c, m in enumerate(mass):
            if not m:
                continue
            hit += m * rate[c] * share                # 6★且为当期 → 吸收
            nxt[0] += m * rate[c] * (1.0 - share)     # 6★非当期 → 保底清零
            if c + 1 < pool_cls.softGuarantee:
                nxt[c + 1] += m * (1.0 - rate[c])     # 未出6★ → 计数 +1
        if t == pool_cls.hardGuarantee:
            hit += sum(nxt)                           # 末抽硬保底
            nxt = [0.0] * pool_cls.softGuarantee
        pmf[t - 1] = hit
        mass = nxt
    return pmf


def free_ten_hit(pool_cls: type[GachaPool], up_judge: bool) -> float:
    """赠送十连(10连,基础概率,与保底互不影响)至少一抽达成的概率;
    up_judge=True 按「6★且为当期干员」口径(SHARE_CURRENT 段)。"""
    per = pool_cls.star6BaseRate / RATE_SCALE
    if up_judge:
        per *= SHARE_CURRENT
    return 1.0 - (1.0 - per) ** FREE_TEN_SIZE


def apply_free_ten(pool_cls: type[GachaPool], pmf: list[float],
                   hit: float) -> list[float]:
    """把赠送十连并入付费抽数分布:玩家必领必用时,等价于付费第30抽后插入
    一段独立10连 —— 命中(概率 hit)→ 达成提前至付费30抽;未命中 → 30抽后
    的分布按 (1-hit) 缩放。仅适用于达成点可落在30抽之后的口径(6★/当期)。"""
    at = pool_cls.freeTenGrantAt
    out = list(pmf)
    before = 1.0 - sum(out[:at])          # 付费前 at 抽未达成
    out[at - 1] += before * hit
    keep = 1.0 - hit
    for i in range(at, len(out)):
        out[i] *= keep
    return out


def target_paid_pmf(pool_cls: type[GachaPool]) -> list[float]:
    """「当期干员首达」的付费抽数精确分布(含赠送十连并入)。"""
    return apply_free_ten(pool_cls, target_first_pmf(pool_cls),
                          free_ten_hit(pool_cls, up_judge=True))


def conv(a: list[float], b: list[float]) -> list[float]:
    """两个非负分布的卷积(分布 1 起计:pmf[k] = P(T=k+1);合成 T = Ta+Tb,
    out[i+j+1] = Σ a[i]·b[j],输出长度 len(a)+len(b) 完整容纳尾部)。"""
    out = [0.0] * (len(a) + len(b))
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                out[i + j + 1] += x * y
    return out


def cdf(pmf: list[float]) -> list[float]:
    """分布 → 累积分布(第 n 项 = 前 n 抽内达成)。"""
    return list(accumulate(pmf))


def expectation(pmf: list[float]) -> float:
    """分布的期望抽数。"""
    return sum(t * m for t, m in enumerate(pmf, 1))


def pulls_needed(pmf: list[float], q: float) -> int:
    """达到累计概率 q(如 0.9)所需的最小抽数;达不到时返回分布长度(必出点)。"""
    for n, cum in enumerate(cdf(pmf), 1):
        if cum >= q:
            return n
    return len(pmf)


# ---------------------------------------------------------------- ③ 全图鉴
def first_banners() -> list[GachaPool]:
    """全图鉴首发池:各版本限定寻访(排除复刻;联合池为往期UP重复机会,
    不占主路径 —— 两个UP均已在 1.0 首发限定池单独当期过)。"""
    return [p for pools in POOLS.values() for p in pools
            if isinstance(p, LimitedGacha) and not isinstance(p, RerunGacha)]


def collection_pmf() -> list[float]:
    """全图鉴所需总付费抽数的解析分布(上界口径):以首个首发池「当期干员
    首达」付费分布为起点逐池卷积,各池独立、期初 pity=0、未计顺路获得
    (模拟中顺路拿到往期干员可跳过后续池,故模拟优于该上界)。"""
    banners = first_banners()
    pmf = target_paid_pmf(type(banners[0]))
    for _ in banners[1:]:
        pmf = conv(pmf, target_paid_pmf(LimitedGacha))
    return pmf


def simulate_collection(trials: int = COLLECTION_TRIALS,
                        seed: int = DEFAULT_SEED,
                        strategy: Strategy = strategy_until_owned_60
                        ) -> list[tuple[int, int, int]]:
    """全图鉴所需抽数模拟:按给定策略逐池抽取(strategy_until_owned = 每池
    抽到目标拿齐为止,120硬保底兜底),跨期继承 pity 与 owned
    (POOLS 单例,trial 前重置)。
    顺路获得的往期/常驻干员记入 owned,后续池目标已拥有时直接跳过。
    返回每 trial 的 (付费, 赠送, 总抽数) 样本 —— 直接取自 GachaGlobalState
    的 paid_pulls/free_pulls/total_pulls 累计。"""
    plan = first_banners()
    rng = random.Random(seed)
    samples: list[tuple[int, int, int]] = []
    for _ in range(trials):
        g = GachaGlobalState()
        for pool in plan:
            pool.reset(g)
            pool.rng = rng
            run_banner(pool, strategy)
        samples.append((g.paid_pulls, g.free_pulls, g.total_pulls))
    return samples


def sample_pmf(samples: list[int]) -> list[float]:
    """整数样本 → 经验分布(1..max)。"""
    out = [0.0] * max(samples)
    for x in samples:
        out[x - 1] += 1.0 / len(samples)
    return out


# ---------------------------------------------------------------- ④ 版本概率曲线
def cdf_expectation(cdf_arr: list[float]) -> float:
    """由累积分布求期望抽数:E[T] = 1 + Σ_{n≥1} P(T > n)(生存函数求和)。"""
    return 1.0 + sum(1.0 - p for p in cdf_arr)


def version_key(v: str) -> tuple[int, ...]:
    """版本号 → 可比较元组(1.10 > 1.9)。"""
    return tuple(int(x) for x in v.split("."))


def version_banners(version: str) -> list[GachaPool]:
    """截至 version(含)的全部首发限定池(按版本顺序平铺)。"""
    return [p for v, pools in sorted(POOLS.items(), key=lambda kv: version_key(kv[0]))
            if version_key(v) <= version_key(version)
            for p in pools
            if isinstance(p, LimitedGacha) and not isinstance(p, RerunGacha)]


def latest_version() -> str:
    """POOLS 中最新的版本号。"""
    return max(POOLS, key=version_key)


def resolve_plan(target: str | None) -> tuple[str, str, str, list[GachaPool]]:
    """目标 → (标签, 所属版本, 标题, 平铺池列表)。

    语法:
        pool_id | 池名称   单个卡池(special_1_4_1 / 临渊望北;含复刻池)
        <版本>             该版本的卡池列表(1.4 → 临渊望北、晨星于此闪耀)
        <版本>[切片]       版本内切片,Python 语法(1.0[:1] → 只含熔火灼痕)
        [A..]B             跨版本累积平铺(..1.4 = 开服至 1.4;1.2.. = 1.2 起最新)
    缺省 = 最新版本全部首发池。联合寻访仅支持模拟口径。
    """

    def plan_of(ver: str) -> list[GachaPool]:
        return [p for p in POOLS[ver]
                if isinstance(p, LimitedGacha) and not isinstance(p, RerunGacha)]

    def single(p: GachaPool, ver: str):
        return p.pool_id, ver, f"「{p.name}」当期干员集齐概率", [p]

    if not target:                     # 缺省:最新版本及之前的全部首发池
        target = latest_version()
        plan = version_banners(target)
        return target, target, f"截至 {target} 版本全图鉴集齐概率", plan

    # 单个卡池(pool_id 或名称,含复刻)
    for ver, pools in POOLS.items():
        for p in pools:
            if target in (p.pool_id, p.name):
                return single(p, ver)

    # 版本 + 可选切片:1.0[:1](切片语法同 Python)
    m = re.fullmatch(r"(.+?)\[([^\[\]:]*)(?::([^\[\]:]*))?(?::([^\[\]:]*))?\]", target)
    if m:
        base, spec = m.group(1), m.group(2, 3, 4)
        if base not in POOLS:
            raise SystemExit(f"未知版本:{base}(可用:{'、'.join(POOLS)})")
        args = [int(x) if x and x.strip() else None for x in spec]
        plan = plan_of(base)[slice(*args)]
        if not plan:
            raise SystemExit(f"{target} 切片结果为空")
        if len(plan) == 1:
            return single(plan[0], base)
        return target, base, f"{target} 全图鉴集齐概率", plan

    # 跨版本累积:1.0..1.4 / ..1.4 / 1.2..
    if ".." in target:
        a, _, b = target.partition("..")
        lo = version_key(a) if a else None
        hi = version_key(b) if b else None
        plan = [p for v in sorted(POOLS, key=version_key)
                if (lo is None or version_key(v) >= lo)
                and (hi is None or version_key(v) <= hi)
                for p in plan_of(v)]
        if not plan:
            raise SystemExit(f"{target} 没有命中首发限定池")
        return target, b or a or latest_version(), f"{target} 全图鉴集齐概率", plan

    # 纯版本号:该版本的卡池列表
    try:
        version_key(target)
    except ValueError:
        raise SystemExit(f"未知版本或卡池:{target}(版本:{'、'.join(POOLS)};"
                         f"卡池可用 pool_id/名称,切片如 1.0[:1],范围如 ..1.4)")
    plan = plan_of(target)
    if not plan:
        raise SystemExit(f"版本 {target} 没有首发限定池(复刻池用 pool_id 指定)")
    if len(plan) == 1:
        return single(plan[0], target)
    return target, target, f"{target} 全图鉴集齐概率", plan


def collection_cdf(plan: list[GachaPool], trials: int = 5_000,
                   seed: int = DEFAULT_SEED,
                   strategy: Strategy = strategy_until_owned_60
                   ) -> tuple[list[float], float, float]:
    """「平铺全图鉴」策略(strategy_until_owned:逐池抽到当期干员到手、拿齐
    即停、无限定UP的池跳过)下,plan 全部限定UP在 N 次**总寻访**(付费+
    游戏内免费券,与 VERSION_FREE_PULLS 同口径)内集齐的概率
    曲线(模拟,含顺路获得与跳过)。返回 (CDF, 期望总抽数, 免费券抽数均值),
    期望与曲线同口径 —— 由所画 CDF 生存函数求和得出。"""
    rng = random.Random(seed)
    paid: list[int] = []
    free: list[int] = []
    for _ in range(trials):
        g = GachaGlobalState()
        for pool in plan:
            pool.reset(g)
            pool.rng = rng
            run_banner(pool, strategy)
        paid.append(g.paid_pulls)
        free.append(g.free_pulls)
    arr = cdf(sample_pmf([p + f for p, f in zip(paid, free)]))
    return arr, cdf_expectation(arr), sum(free) / len(free)


def collection_cdf_upper(plan: list[GachaPool]) -> tuple[list[float], float]:
    """解析上界(付费口径近似,未计签到券/配额券;模拟曲线为总口径):
    当期干员首达分布逐池卷积后的 CDF。返回 (CDF, 期望付费抽数)。
    需全部池有硬保底(联合寻访无界,只支持模拟)。"""
    if any(not p.hardGuarantee for p in plan):
        raise SystemExit("所选范围含无硬保底的池(联合寻访),解析上界不可用,"
                         "请用 --method simulate")
    pmf = target_paid_pmf(type(plan[0]))
    for _ in plan[1:]:
        pmf = conv(pmf, target_paid_pmf(LimitedGacha))
    arr = cdf(pmf)
    return arr, cdf_expectation(arr)


def render_collection_chart(title: str,
                            curves: list[tuple[str, list[float], str, float]],
                            out_path: Path,
                            marks: list[tuple[str, float, str, str]] = ()
                            ) -> Path:
    """全图鉴集齐概率折线图(手写 SVG,零依赖):横坐标总寻访次数、纵坐标
    集齐概率;curves = [(图例, CDF, 颜色, 期望)];marks = [(标签, 抽数,
    颜色, 与期望的差)] 为参考竖线。全部文字说明集中在左上信息卡,竖排,
    不与曲线/竖线/交点标注重叠;竖线交点处圆点 + 集齐概率。"""

    def prob_at(cdf_arr: list[float], x: float) -> float:
        """竖线位置在主曲线上的概率(线性插值)。"""
        i = int(x)
        if i >= len(cdf_arr) - 1:
            return cdf_arr[-1]
        return cdf_arr[i] + (cdf_arr[i + 1] - cdf_arr[i]) * (x - i)

    w, h = 760, 460
    ml, mr, mt, mb = 64, 24, 46, 52
    pw, ph = w - ml - mr, h - mt - mb
    x_max = max(len(c) for _, c, _, _, _ in curves) + 1  # cdf 第 i 项 = 前 i 抽
    x_step = 100 if x_max <= 600 else (200 if x_max <= 1200 else 400)

    def X(v: float) -> float:
        return ml + v / x_max * pw

    def Y(p: float) -> float:
        return mt + ph * (1.0 - p)

    grid, axes = [], []
    for t in [i / 5 for i in range(6)]:
        grid.append(f'<line x1="{ml}" y1="{Y(t):.1f}" x2="{w - mr}" '
                    f'y2="{Y(t):.1f}" stroke="#e0e0e0"/>')
        grid.append(f'<line x1="{X(t * x_max):.1f}" y1="{mt}" '
                    f'x2="{X(t * x_max):.1f}" y2="{mt + ph}" stroke="#e0e0e0"/>')
        axes.append(f'<text x="{X(t * x_max):.1f}" y="{mt + ph + 18}" '
                    f'text-anchor="middle" font-size="12" fill="#444">'
                    f"{t * x_max:.0f}</text>")
        axes.append(f'<text x="{ml - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" '
                    f'font-size="12" fill="#444">{t:.0%}</text>')

    # 左上信息卡:图例 + 期望 + 参考线说明,竖排(card_row 递增行号)
    card_x = ml + 12
    card_row = 0
    card: list[str] = []

    def card_text(text: str, color: str = "#222") -> None:
        nonlocal card_row
        card.append(f'<text x="{card_x + (20 if color != "#222" else 0)}" '
                    f'y="{mt + 14 + card_row * 18}" font-size="12" '
                    f'fill="{color}">{text}</text>')
        card_row += 1

    def card_swatch(color: str) -> None:
        nonlocal card_row
        ly = mt + 14 + card_row * 18
        card.append(f'<line x1="{card_x}" y1="{ly - 4}" x2="{card_x + 18}" '
                    f'y2="{ly - 4}" stroke="{color}" stroke-width="2"/>')
        card_row += 1

    main_cdf = curves[0][1]                    # 交点标注的主曲线(模拟)

    def prob_at_c(cdf_arr: list[float], x: float) -> float:
        i = int(x)
        if i >= len(cdf_arr) - 1:
            return cdf_arr[-1]
        return cdf_arr[i] + (cdf_arr[i + 1] - cdf_arr[i]) * (x - i)

    lines: list[str] = []
    for li, (label, cdf_arr, color, expect, _fm) in enumerate(curves):
        pts = " ".join(f"{X(i):.1f},{Y(p):.1f}"
                       for i, p in enumerate(cdf_arr[:x_max]))
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="2"/>')
        ex, ey = X(expect), Y(prob_at_c(main_cdf, expect))
        lines.append(f'<line x1="{ex:.1f}" y1="{mt}" x2="{ex:.1f}" y2="{mt + ph}" '
                     f'stroke="{color}" stroke-width="1.5" '
                     f'stroke-dasharray="5,4"/>')
        if li == 0:                            # 主曲线:期望交点圆点 + 概率
            lines.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" '
                         f'fill="{color}"/>')
            lines.append(f'<text x="{ex - 7:.1f}" y="{ey - 8:.1f}" '
                         f'text-anchor="end" font-size="12" font-weight="bold" '
                         f'fill="{color}">{prob_at_c(main_cdf, expect):.0%}</text>')
    for mk_label, x, color, note in marks:
        mx, my = X(min(x, x_max)), Y(prob_at_c(main_cdf, x))
        lines.append(f'<line x1="{mx:.1f}" y1="{mt}" x2="{mx:.1f}" '
                     f'y2="{mt + ph}" stroke="{color}" stroke-width="1.5"/>')
        if x <= x_max:
            lines.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="3.5" '
                         f'fill="{color}"/>')
            lines.append(f'<text x="{mx - 7:.1f}" y="{my - 8:.1f}" '
                         f'text-anchor="end" font-size="12" font-weight="bold" '
                         f'fill="{color}">{prob_at_c(main_cdf, x):.0%}</text>')

    # 信息卡内容:图例行 + 期望行 + 参考线行
    for label, _c, color, _e, _fm in curves:
        card_swatch(color)
        card_text(label)
    for _label, _c, color, expect, _fm in curves:
        card_text(f"E={expect:.0f}(期望)", color)
    for mk_label, x, color, note in marks:
        card_text(f"{mk_label} {x:.0f}({note})", color)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="sans-serif">'
        f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>'
        f'<text x="{w / 2}" y="24" text-anchor="middle" font-size="16" '
        f'fill="#111">{title}(平铺策略,总抽数口径)'
        f'</text>{"".join(grid)}{"".join(lines)}{"".join(card)}{"".join(axes)}'
        f'<text x="{ml + pw / 2}" y="{h - 12}" text-anchor="middle" '
        f'font-size="13" fill="#444">总寻访次数(含游戏内免费券)</text>'
        f'<text x="18" y="{mt + ph / 2}" text-anchor="middle" font-size="13" '
        f'fill="#444" transform="rotate(-90 18 {mt + ph / 2})">集齐概率</text>'
        f'</svg>')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------- 干员名
_CHAR_NAMES: dict[str, str] = {}


def _char_name(cid: str) -> str:
    """干员展示名(读 data/characters 数据集;缺条目回退 id)。"""
    if cid not in _CHAR_NAMES:
        f = DATA_DIR / "characters" / f"{cid}.json"
        try:
            _CHAR_NAMES[cid] = json.loads(f.read_text(encoding="utf-8")).get("name") or cid
        except OSError:
            _CHAR_NAMES[cid] = cid
    return _CHAR_NAMES[cid]


def _up_text(pool: GachaPool) -> str:
    return "、".join(_char_name(u) for u in pool.up_ids)


# ---------------------------------------------------------------- 报告
def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _load_build() -> str:
    f = DATA_DIR / "versions.json"
    try:
        return str(json.loads(f.read_text(encoding="utf-8")).get("game", {}).get("build", "?"))
    except (OSError, ValueError):
        return "?"


def render_report(col_pmf: list[float], col_samples: list[int],
                  now: str) -> str:
    """报告:版本卡池安排 + 规则口径 + 全图鉴所需抽数统计(解析上界 vs 模拟)。"""
    paid = [s[0] for s in col_samples]
    free = [s[1] for s in col_samples]
    total = [s[2] for s in col_samples]
    col_cdf, sim_cdf = cdf(col_pmf), cdf(sample_pmf(total))
    last_ver = [v for v, pools in POOLS.items() if first_banners()[-1] in pools][0]
    free_total = total_free_pulls(last_ver)
    excluded = sum(p.sign_in_tickets + BANNER_TICKETS for p in first_banners())
    lines = [
        "# 抽卡分析报告", "",
        f"- 生成时间:{now}(UTC);数据源:rmxlinux/EndfieldData@main"
        f"(build {_load_build()});卡池安排 = GachaCharPoolTable 快照,"
        "概率参数 = GachaCharPoolTypeTable,6★ 名单 = GachaCharPoolContentTable",
        f"- 全图鉴口径:集齐 {sum(len(p.up_ids) for p in first_banners())} 名"
        "限定首发当期干员(联合/复刻池为重复获取机会,不占主路径);"
        "抽数 = 总寻访次数(付费 + 签到券/配额券/赠送十连等游戏内免费券,"
        "与 VERSION_FREE_PULLS 同口径,免费行为不重复叠加)",
        "",
        "## 一、各版本 UP 卡池安排", "",
        "| 版本 | 卡池 | 类型 | 当期干员 | 同池概率提升(往期) |",
        "|---|---|---|---|---|",
    ]
    for ver, pools in POOLS.items():
        for p in pools:
            note = ""
            if isinstance(p, JointGacha):
                note = "(独立保底;50%双UP+50%常驻平分;120抽赠调用凭证4选1)"
            elif isinstance(p, RerunGacha):
                note = "(重构寻访:累计进度跨轮继承)"
            lines.append(f"| {ver} | {p.name}(`{p.pool_id}`) | "
                         f"{p.pool_name}{note} | {_up_text(p)} | "
                         f"{'、'.join(_char_name(u) for u in p.rateup_ids) or '—'} |")
    lines += [
        "",
        "## 二、规则口径(限定寻访)", "",
        "- 单抽基础概率:6★ 0.8% / 5★ 8%;6★ 概率自第66抽起每抽 +5 个百分点,"
        "第80抽必出6★(该计数在同类型池之间继承)",
        "- 命中6★后:50% 当期干员 + 25% 往期两期限定干员平分 + 25% 名单内常驻6★"
        "平分(复刻池无往期段 → 50% 复刻干员 + 50% 常驻)",
        "- 首个当期干员前,本池累计第120抽必得**当期**干员(不跨期继承,"
        "获得当期干员后失效;往期/常驻6★不影响它)",
        "- 每10次寻访必出5★及以上;累计30次赠当期十连(基础概率、与保底互不影响、"
        "不计累计,按必领必用折入付费口径);累计60次赠下期十连券(入全局状态,"
        "下一期限定池开局兑换,整抽使用)",
        "",
        "## 三、单池参考(限定寻访)", "",
        f"- 当期干员首达:期望 {expectation(target_paid_pmf(LimitedGacha)):.1f} 付费抽,"
        f"120抽必得;首个6★:期望 "
        f"{expectation(apply_free_ten(LimitedGacha, six_star_first_pmf(LimitedGacha), free_ten_hit(LimitedGacha, up_judge=False))):.1f}"
        " 付费抽(综合概率 "
        f"{1 / expectation(apply_free_ten(LimitedGacha, six_star_first_pmf(LimitedGacha), free_ten_hit(LimitedGacha, up_judge=False))):.2%})",
        "- 命中6★后 25% 顺路获得前两期限定干员(各 12.5%)、25% 获得常驻6★",
        "",
        "## 四、全图鉴所需抽数(逐池抽到当期干员到手,120硬保底兜底)", "",
        "| 总抽数 N | 解析上界(付费口径近似) | 模拟(总口径,含顺路/跳过) |",
        "|---|---|---|",
    ]
    for n in (600, 700, 800, 850, 900, 1000, 1100, 1200, 1320):
        a = col_cdf[n - 1] if n <= len(col_cdf) else 1.0
        s = sim_cdf[n - 1] if n <= len(sim_cdf) else 1.0
        lines.append(f"| ≤ {n} | {_pct(a)} | {_pct(s)} |")
    lines += [
        "",
        f"- 解析上界(付费口径近似,各池独立、期初 pity=0、未计顺路):期望 {expectation(col_pmf):.0f} 抽,"
        f"中位数 {pulls_needed(col_pmf, 0.5)} 抽,P90 {pulls_needed(col_pmf, 0.9)} 抽,"
        f"P95 {pulls_needed(col_pmf, 0.95)} 抽,上限 {len(first_banners()) * LimitedGacha.hardGuarantee} 抽"
        "(= 每池都吃满120硬保底)",
        f"- 模拟({len(col_samples)} 次,策略 = 每池抽到当期干员到手,"
        "顺路获得的往期干员可使后续池直接跳过):"
        f"期望总抽数 {sum(total) / len(total):.0f}"
        f"(其中付费 {sum(paid) / len(paid):.0f} + 免费券 {sum(free) / len(free):.0f}),"
        f"P90 {pulls_needed(sample_pmf(total), 0.9)} 抽",
        f"- 全勤对照(总口径):零氪全勤供给 = ③ 福利直送 {free_total} 抽"
        f"(VERSION_FREE_PULLS,已含签到当期凭证与可购当期券 "
        f"{excluded} 张)+ ①加急招募/②配额券与下期券 "
        f"{sum(free) / len(free) - excluded:.0f} 抽 = "
        f"{free_total + sum(free) / len(free) - excluded:.0f} 抽,vs 模拟需求 "
        f"{sum(total) / len(total):.0f} 抽 —— 真付费(④)缺口 "
        f"{max(0.0, sum(total) / len(total) - free_total - sum(free) / len(free) + excluded):.0f} 抽;"
        f"大小月卡供给 {total_pass_pulls(last_ver) + sum(free) / len(free) - excluded:.0f} 抽"
        f"({'覆盖' if total_pass_pulls(last_ver) + sum(free) / len(free) - excluded >= sum(total) / len(total) else '仍有缺口'})",
        "- 两列差异 = 顺路收益与继承效应:25% 的6★落在往期干员(后续池目标"
        "已拥有即跳过)、赠送十连命中时下一池继承保底计数;解析列按各池独立、"
        "期初 pity=0 计算,故恒为保守上界",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 主函数
def run(version: str | None = None, plot: bool = False,
        method: str = "simulate") -> None:
    """控制台输出对拍与全图鉴摘要;报告写入 reports/gacha-analysis.md。

    version 为目标版本或卡池(全勤对照截止版本;配合 --plot 指定统计范围),
    缺省取最新版本。plot=True 绘制集齐概率曲线(横坐标总寻访次数、
    纵坐标集齐概率,SVG 零依赖)。
    method 选择概率计算方式:simulate = 状态机蒙特卡洛(默认,含顺路/
    跳过与下期券);analytic = 解析(卷积上界,快、保守);both = 两者都画。
    """
    # 单池保底分布对拍(模拟 vs 解析):取 1.0 首个限定池(名单不影响当期首达)
    pool = POOLS["1.0"][0]
    ana = {
        "six": apply_free_ten(LimitedGacha, six_star_first_pmf(LimitedGacha),
                              free_ten_hit(LimitedGacha, up_judge=False)),
        "target": target_paid_pmf(LimitedGacha),
        "five": five_star_first_pmf(LimitedGacha),
    }
    sim = simulate(pool)
    print(f"抽卡概率计算 · {pool.pool_name}"
          f"(6★ {pool.star6BaseRate / RATE_SCALE:.1%},"
          f"第{pool.star6RatePromotePullCount[0]}抽起每抽"
          f"+{pool.star6RatePromoteValue[0] / RATE_SCALE:.0%}点,"
          f"{pool.softGuarantee}抽必出6★;6★分配 50% 当期 + 25% 往期平分 + "
          f"25% 常驻;付费{pool.hardGuarantee}抽必得当期干员)")
    print(f"  当期干员首达 期望 {expectation(ana['target']):.1f} 付费抽;"
          f"90%分位 {pulls_needed(ana['target'], 0.9)} 抽")
    for key in ("six", "target", "five"):
        if key in sim:
            diff = max(abs(a - b) for a, b in zip(ana[key], sim[key]))
            print(f"  对拍  {key:<7} 模拟{DEFAULT_TRIALS}次(seed={DEFAULT_SEED}) "
                  f"max|Δpmf| = {diff:.4f}")

    # 全图鉴所需抽数(解析上界 + 模拟)
    col_pmf = collection_pmf()
    col_samples = simulate_collection()
    paid = [s[0] for s in col_samples]
    free = [s[1] for s in col_samples]
    total = [s[2] for s in col_samples]
    print(f"  全图鉴({len(first_banners())} 个首发池)"
          f" 期望(上界){expectation(col_pmf):.0f} 抽、P90 {pulls_needed(col_pmf, 0.9)} 抽、"
          f"上限 {len(first_banners()) * LimitedGacha.hardGuarantee} 抽;"
          f"模拟均值 付费 {sum(paid) / len(paid):.0f} + 赠送 {sum(free) / len(free):.0f}"
          f" = 合计 {sum(total) / len(total):.0f} 抽(含顺路)")
    label, ver, title, plan = resolve_plan(version)
    print(f"  全勤对照:开服至 {ver} 累计约 {total_free_pulls(ver)} 抽"
          "(社区统计,不含外部激励)")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    report = render_report(col_pmf, col_samples, now)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"  {REPORT_PATH}")

    if plot:
        curves = []
        if method in ("both", "simulate"):
            sim_cdf, sim_e, sim_f = collection_cdf(plan)
            curves.append(("模拟", sim_cdf, "#1565c0", sim_e, sim_f))
        if method in ("both", "analytic"):
            ana_cdf, ana_e, ana_f = collection_cdf_upper(plan)
            curves.append(("解析上界(未计顺路)", ana_cdf, "#ef6c00", ana_e, ana_f))
        exp0 = curves[0][3]
        free_mean = curves[0][4]
        # 供给(总口径)= ③ 福利直送(VERSION_FREE_PULLS,已含签到当期凭证与
        # 可购当期券)+ ① 加急招募 + ② 配额券/下期券(模拟免费均值扣除前两者)
        excluded = sum(p.sign_in_tickets + BANNER_TICKETS for p in plan)
        zero = round(total_free_pulls(ver) + free_mean - excluded)
        pass_supply = round(total_pass_pulls(ver) + free_mean - excluded)
        marks = []
        if len(plan) > 1:                  # 全局零氪/月卡线只对版本图有意义
            marks = [
                ("零氪全勤", zero, "#2e7d32",
                 f"{zero - exp0:+.0f}({(zero - exp0) / exp0:+.0%})"),
                ("大小月卡", pass_supply, "#6a1b9a",
                 f"{pass_supply - exp0:+.0f}"
                 f"({(pass_supply - exp0) / exp0:+.0%})"),
            ]
        path = render_collection_chart(
            title, curves,
            REPORTS_DIR / f"gacha-collection-{label}.svg", marks)
        tail_note = (f";零氪 {zero}、大小月卡 {marks[1][1]},括号为与期望的差"
                     if marks else "")
        print(f"  {path}(平铺全图鉴策略,{len(plan)} 个首发池,"
              f"方式 {method}{tail_note})")


def main(version: str | None = None, plot: bool = False,
         method: str = "simulate") -> None:
    run(version, plot, method)


if __name__ == "__main__":
    main()
