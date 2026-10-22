"""아이템 고유 효과 (data/items.json 의 "effect" 패시브와 "active" 사용 효과).

sim 이 때마다 여기 함수를 부른다.
  on_basic_hit   기본 공격이 맞았을 때 (마나 칼날 마나 회복, 폭풍 사냥꾼 연쇄 번개, 서리 군주 주문검)
  on_cast        스킬을 썼을 때 (서리 군주 주문검 준비, 영원의 성배 마나 → 체력)
  on_ability_hit 스킬 피해가 적 챔피언에게 들어갔을 때 (대마법사의 왕관 비전 구슬)
  tick           매 틱 (거신의 맥동 불타는 기운)
  use            사용 아이템 (흡혈 대낫, 불멸의 성채, 시간의 모래시계)
같은 효과의 아이템을 여러 개 가져도 효과는 한 번만 (롤의 고유 효과처럼).
"""
from ..shared import data as gamedata
from .entities import Champion, Projectile


def effects(c, kind):
    """c 가 가진 아이템 중 효과 종류가 kind 인 것의 효과 데이터 (없으면 None)."""
    for iid in c.items:
        ef = gamedata.items().get(iid, {}).get("effect")
        if ef and ef["kind"] == kind:
            return ef
    return None


def fx(sim, style, x, z, c, **kw):
    sim.event(e="fx", fx="item", style=style, x=round(x, 2), z=round(z, 2), tm=c.team, d=c.id, **kw)


def homing(sim, c, src, target, style, speed, on_hit):
    """src 위치에서 target 을 따라가는 아이템 투사체."""
    p = Projectile(sim.new_id(), c.team, c, src.x, src.z, style, speed)
    p.target = target.id
    p.on_hit = on_hit
    sim.projectiles[p.id] = p


# ---------------------------------------------------------------- 패시브
def on_basic_hit(sim, c, target):
    if not isinstance(c, Champion):
        return
    t = sim.time
    ef = effects(c, "mana_on_hit")
    if ef:
        c.mana = min(c.max_mana, c.mana + ef["mana"])
    ef = effects(c, "chain")
    if ef:
        c.item_state["chain"] = c.item_state.get("chain", 0) + 1
        if c.item_state["chain"] >= ef["every"]:
            c.item_state["chain"] = 0
            dmg = ef["damage"] + ef["ad_ratio"] * c.stats["ad"]
            near = [u for u in sim.enemies_in_radius(c.team, target.x, target.z, ef["range"]) if u is not target]
            near.sort(key=lambda u: (not isinstance(u, Champion), u.dist_to(target)))
            for u in near[:ef["count"]]:
                homing(sim, c, target, u, "item_bolt", ef["speed"],
                       lambda s_, tg, dmg=dmg: s_.deal_damage(c, tg, dmg, "magic", ability=True, proc=False))
            fx(sim, "spark", target.x, target.z, c)
    ef = effects(c, "spellblade")
    if ef and t < c.item_state.get("blade_until", 0.0) and t >= c.item_state.get("blade_ready", 0.0):
        c.item_state["blade_until"] = 0.0
        c.item_state["blade_ready"] = t + ef["cooldown"]
        sim.deal_damage(c, target, ef["base_ad"] * c.stats["base_ad"], "physical", ability=True, proc=False)
        target.apply_slow(t, ef["slow"], ef["slow_duration"])
        fx(sim, "frost", target.x, target.z, c)


def on_cast(sim, c, cost):
    t = sim.time
    ef = effects(c, "spellblade")
    if ef and t >= c.item_state.get("blade_ready", 0.0):
        c.item_state["blade_until"] = t + ef["window"]
    ef = effects(c, "mana_heal")
    if ef and cost > 0:
        sim.heal(c, cost * ef["ratio"], c)


def on_ability_hit(sim, c, target):
    if not isinstance(c, Champion) or not isinstance(target, Champion):
        return
    ef = effects(c, "missiles")
    if ef is None or sim.time < c.item_state.get("missiles_ready", 0.0):
        return
    c.item_state["missiles_ready"] = sim.time + ef["cooldown"]
    dmg = ef["damage"] + ef["ap_ratio"] * c.stats["ap"]
    for k in range(ef["count"]):
        def launch(s_, k=k):
            if c.dead or not s_.targetable(target, c.team):
                return
            homing(s_, c, c, target, "item_missile", ef["speed"],
                   lambda s2, tg: s2.deal_damage(c, tg, dmg, "magic", ability=True, proc=False))
        sim.schedule(k * 0.12, launch)


def tick(sim, c, dt):
    ef = effects(c, "burn_aura")
    if ef is None or c.dead:
        return
    t = sim.time
    if t < c.item_state.get("burn_next", 0.0):
        return
    c.item_state["burn_next"] = t + 1.0
    dmg = ef["damage"] + ef["hp_ratio"] * c.max_hp
    for u in sim.enemies_in_radius(c.team, c.x, c.z, ef["radius"]):
        sim.deal_damage(c, u, dmg, "magic", ability=True, proc=False)


# ---------------------------------------------------------------- 사용 아이템
def use(sim, c, slot):
    """slot 칸 아이템의 사용 효과. 썼으면 True."""
    if not (0 <= slot < len(c.items)) or c.dead:
        return False
    iid = c.items[slot]
    act = gamedata.items().get(iid, {}).get("active")
    t = sim.time
    if act is None or t < c.item_cd.get(iid, 0.0) or c.stunned(t):
        return False
    kind = act["kind"]
    if kind == "drain":
        dmg = act["damage"] + act["bonus_ad_ratio"] * c.stats["bonus_ad"]
        healed = 0.0
        for u in sim.enemies_in_radius(c.team, c.x, c.z, act["radius"]):
            taken = sim.deal_damage(c, u, dmg, "physical", ability=True, proc=False)
            if isinstance(u, Champion):
                healed += taken * act["heal_ratio"]
        if healed > 0:
            sim.heal(c, healed, c)
        fx(sim, "drain", c.x, c.z, c, r=act["radius"])
    elif kind == "shield":
        sim.add_shield(c, act["amount"] + act["hp_ratio"] * c.max_hp, act["duration"])
        fx(sim, "shield", c.x, c.z, c, dur=act["duration"])
    elif kind == "stasis":
        if c.dash:
            return False
        dur = act["duration"]
        c.clear_orders()
        c.recall_at = None
        c.untarget_until = max(c.untarget_until, t + dur)
        c.stun_until = max(c.stun_until, t + dur)
        fx(sim, "stasis", c.x, c.z, c, dur=dur)
    else:
        return False
    c.item_cd[iid] = t + act["cooldown"]
    return True
