"""봇의 아이템 고르기: 가중치를 준 무작위.

한 번에 목표 아이템(신발 또는 2·3단계 아이템) 하나를 정하고, 다 살 때까지 그 재료부터 사 모은다.
목표를 고를 때 아이템마다 점수를 매겨 점수에 비례한 확률로 뽑는다.

  점수 = (아이템 능력치·효과의 값어치 ÷ 가격)^4 × 무작위(0.6~1.4) × 상황 배율
  - 값어치: 능력치 하나하나를 골드로 환산(STAT_GOLD)하고, 챔피언 성향(AD / AP)에 맞는 능력치일수록 크게 쳐 준다
  - 마나를 많이 쓰는 챔피언은 마나 아이템을, 적이 AD 위주면 방어력을, AP 위주면 마법 저항력을 더 쳐 준다
  - 봇마다 성격(공격적 ~ 단단함)이 달라 같은 챔피언이라도 고르는 아이템이 달라진다
  - 지고 있으면(데스가 킬보다 많으면) 방어 능력치를, 이기고 있으면 공격 능력치를 더 쳐 준다
  - 처음 두 핵심 아이템은 공격 능력치 비중이 큰 것을 더 쳐 준다
  - 챔피언 data 의 bot_build 에 있는 아이템은 조금 더, 가진 2단계를 재료로 쓰는 3단계는 더 쳐 준다
"""
import math

from ..shared import data as gamedata
from ..shared.constants import INVENTORY_SLOTS

# 능력치 1 당 골드 (상점 가성비 점검과 같은 기준: 공격력·공속을 주문력·스킬 가속보다 비싸게)
STAT_GOLD = {"ad": 38, "attack_speed": 2800, "crit": 3000, "life_steal": 3500, "ap": 17, "ability_haste": 20,
             "hp": 2.67, "armor": 20, "mr": 18, "move_speed": 1200, "hp_regen": 3, "mana": 1.4, "mana_regen": 10}
OFFENSE = {"ad", "attack_speed", "crit", "life_steal", "ap", "ability_haste"}
DEFENSE = {"hp", "armor", "mr", "hp_regen"}
# 성향별로 능력치를 얼마나 쳐 주는가
FIT = {
    "ad": {"ad": 1.0, "attack_speed": 0.9, "crit": 0.8, "life_steal": 0.85, "ap": 0.05, "ability_haste": 0.7,
           "hp": 0.6, "armor": 0.5, "mr": 0.5, "move_speed": 0.6, "hp_regen": 0.3, "mana": 0.15, "mana_regen": 0.15},
    "ap": {"ad": 0.05, "attack_speed": 0.1, "crit": 0.05, "life_steal": 0.05, "ap": 1.0, "ability_haste": 0.95,
           "hp": 0.6, "armor": 0.5, "mr": 0.5, "move_speed": 0.6, "hp_regen": 0.3, "mana": 0.6, "mana_regen": 0.6},
}
# 고유 효과·사용 효과의 값어치 (성향별 골드)
EFFECT_GOLD = {
    "mana_on_hit": {"ad": 250, "ap": 0}, "chain": {"ad": 500, "ap": 0}, "spellblade": {"ad": 600, "ap": 50},
    "missiles": {"ad": 0, "ap": 550}, "mana_heal": {"ad": 100, "ap": 400}, "burn_aura": {"ad": 400, "ap": 400},
    "drain": {"ad": 550, "ap": 0}, "shield": {"ad": 400, "ap": 400}, "stasis": {"ad": 100, "ap": 600},
}


def profile(cdata):
    """챔피언 성향: 스킬 계수 합으로 "ad" / "ap"."""
    ad = ap = 0.0

    def walk(d):
        nonlocal ad, ap
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v)
            elif isinstance(v, (int, float)):
                if k.endswith("_ad") or k in ("ad_ratio", "bonus_ad_ratio") or k.startswith("baby_ad_ratio"):
                    ad += v
                elif k.endswith("_ap") or k == "ap_ratio":
                    ap += v
            elif isinstance(v, list) and k == "baby_ad_ratio":
                ad += sum(v) / len(v)
    for ab in cdata["abilities"].values():
        walk(ab)
    return "ap" if ap > ad else "ad"


def mana_hungry(cdata):
    """스킬 한 바퀴 마나 ÷ 기본 마나: 클수록 마나 아이템이 반갑다."""
    total = sum(ab.get("mana", [0])[-1] for slot, ab in cdata["abilities"].items() if slot != "R")
    return total / max(1.0, cdata["stats"]["mana"])


def enemy_ap_share(sim, team):
    enemies = [c for c in sim.champions.values() if c.team != team]
    if not enemies:
        return 0.5
    return sum(1 for c in enemies if profile(c.data) == "ap") / len(enemies)


def item_value(it, prof, mult):
    v = 0.0
    for k, amount in it["stats"].items():
        v += STAT_GOLD.get(k, 0) * amount * FIT[prof].get(k, 0.3) * mult.get(k, 1.0)
    for part in (it.get("effect"), it.get("active")):
        if part:
            v += EFFECT_GOLD.get(part["kind"], {}).get(prof, 200)
    return v


def offense_share(it, prof):
    """아이템 능력치 값어치 중 공격 능력치 비율 (0~1)."""
    tot = off = 0.0
    for k, amount in it["stats"].items():
        v = STAT_GOLD.get(k, 0) * amount * FIT[prof].get(k, 0.3)
        tot += v
        if k in OFFENSE:
            off += v
    return off / tot if tot > 0 else 0.0


class BotShopper:
    def __init__(self, champ, rng):
        self.c = champ
        self.rng = rng
        self.goal = None
        self.prof = profile(champ.data)
        self.hungry = mana_hungry(champ.data)
        self.tank = rng.random()                # 성격: 0 공격적 ~ 1 단단함

    def owned(self, iid):
        return any(gamedata.contains(have, iid) for have in self.c.items)

    def multipliers(self, sim):
        c = self.c
        ap_share = enemy_ap_share(sim, c.team)
        m = {"armor": 0.7 + 0.6 * (1.0 - ap_share), "mr": 0.7 + 0.6 * ap_share}
        if self.hungry > 0.45:
            m["mana"] = m["mana_regen"] = 1.0 + min(2.0, (self.hungry - 0.45) * 4)
        behind = c.deaths - c.kills
        off = 1.25 - 0.5 * self.tank + (0.15 if behind <= -3 else 0.0) - (0.2 if behind >= 3 else 0.0)
        dfn = 0.75 + 0.5 * self.tank + (0.35 if behind >= 3 else 0.0)
        for k in OFFENSE:
            m[k] = m.get(k, 1.0) * off
        for k in DEFENSE:
            m[k] = m.get(k, 1.0) * dfn
        return m

    def pick(self, sim):
        """다음 목표 아이템을 무작위로 고른다 (없으면 None)."""
        c = self.c
        its = gamedata.items()
        has_boots = any(gamedata.is_boots(i) for i in c.items)
        cores = [i for i in c.items if its[i].get("tier", 1) >= 2 and not gamedata.is_boots(i)]
        want_boots = not has_boots and len(cores) >= 1
        effects = {its[i][k]["kind"] for i in c.items for k in ("effect", "active") if its[i].get(k)}
        mult = self.multipliers(sim)
        build = set(c.data.get("bot_build", []))
        cands = []
        for iid, it in its.items():
            if it.get("tier", 1) < 2 or self.owned(iid) or bool(it.get("boots")) != want_boots:
                continue
            if any(it.get(k) and it[k]["kind"] in effects for k in ("effect", "active")):
                continue                            # 같은 고유 효과는 하나만
            ok, _used, _price, _why = gamedata.can_buy(c.items, iid, INVENTORY_SLOTS)
            if not ok:
                continue
            fit = item_value(it, self.prof, mult) / it["cost"]
            w = fit ** 4 * self.rng.uniform(0.6, 1.4)
            if iid in build:
                w *= 1.4
            if len(cores) < 2 and not want_boots:
                w *= 1.0 + 2.0 * offense_share(it, self.prof)   # 처음 두 개는 주로 공격 아이템
            if any(gamedata.contains(iid, have) for have in cores):
                w *= 1.8                            # 가진 2단계를 키우는 3단계
            if w > 0:
                cands.append((iid, w))
        if not cands:
            return None
        r = self.rng.random() * sum(w for _i, w in cands)
        for iid, w in cands:
            r -= w
            if r <= 0:
                return iid
        return cands[-1][0]

    def shop(self, sim):
        c = self.c
        if self.goal and (self.owned(self.goal) or not gamedata.can_buy(c.items, self.goal, INVENTORY_SLOTS)[0]):
            self.goal = None
        if self.goal is None:
            self.goal = self.pick(sim)
        if self.goal:
            sim.buy(c, self.goal)                   # 모자라면 롤처럼 빠진 재료부터 산다
