"""챔피언 스킬 동작.

sim.cast() 가 스킬 data 의 "type" 으로 HANDLERS 에서 핸들러를 골라 부른다.
핸들러는 Cast 를 받아 성공하면 True (마나·재사용 대기시간이 소모됨), 실패하면 False 를 돌려준다.

수치는 data/champions/*.json 의 스킬 항목에서 읽는다. 리스트면 스킬 레벨별 값이다.
  피해량:   damage + ad_ratio / bonus_ad_ratio / ap_ratio
  그 밖의 수치(장판 초당 피해 등):  <키> + <키>_ap × 주문력 + <키>_ad × 공격력
"""
import math

from ..shared import data as gamedata
from ..shared import mapdata
from .entities import Champion, Cocoon, GroundEffect, Minion, Projectile, Zone

HANDLERS = {}
ZONE_TICK = {}
ZONE_END = {}


class Cast:
    def __init__(self, sim, c, slot, ab, rank, x, z, ux, uz, d):
        self.sim, self.c, self.slot, self.ab, self.rank = sim, c, slot, ab, rank
        self.x, self.z = x, z           # 마우스가 가리킨 바닥 좌표
        self.ux, self.uz = ux, uz       # 시전자 -> 마우스 방향 (단위 벡터)
        self.d = d                      # 시전자와 마우스 사이 거리

    def val(self, key, default=0.0):
        return gamedata.rank_value(self.ab, key, self.rank, default)

    def ground_point(self, rng):
        """사거리 안으로 제한한 지정 지점."""
        dist = min(self.d, rng)
        gx, gz = self.c.x + self.ux * dist, self.c.z + self.uz * dist
        return mapdata.clamp_to_map(gx, gz)


def handler(*types):
    def deco(fn):
        for t in types:
            HANDLERS[t] = fn
        return fn
    return deco


def fx(sim, kind, x, z, tm=None, **kw):
    """화면 효과 이벤트. tm = 이 스킬을 쓴 쪽의 팀 (클라이언트가 아군 파랑 / 적 빨강으로 칠하는 데 쓴다)."""
    ev = {"e": "fx", "fx": kind, "x": round(x, 2), "z": round(z, 2)}
    if tm is not None:
        ev["tm"] = tm
    for k, v in kw.items():
        ev[k] = round(v, 2) if isinstance(v, float) else v
    sim.event(**ev)


def interrupt(u):
    """공중에 뜨거나 밀려날 때 하던 동작을 끊는다."""
    if isinstance(u, Champion):
        u.dash = None
        u.clear_orders()
        u.recall_at = None
    elif hasattr(u, "windup"):
        u.windup = None


def apply_cc(sim, ab, rank, target):
    """스킬 data 의 slow / stun / airborne / root / silence 를 대상에게 건다."""
    t = sim.time
    rv = gamedata.rank_value
    if ab.get("slow"):
        target.apply_slow(t, rv(ab, "slow", rank), rv(ab, "slow_duration", rank, 1.0))
    if ab.get("stun"):
        target.apply_stun(t, rv(ab, "stun", rank))
    if ab.get("airborne"):
        if target.apply_stun(t, rv(ab, "airborne", rank), airborne=True):
            interrupt(target)
    if ab.get("root"):
        target.apply_root(t, rv(ab, "root", rank))
    if ab.get("silence"):
        target.apply_silence(t, rv(ab, "silence", rank))


def rotate(ux, uz, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    return ux * ca - uz * sa, ux * sa + uz * ca

def remove_anchor(sim, a, hatch=False):
    """새끼 거미 고치: 시간이 다 되면 부화, 부서지면 그냥 터진다."""
    if sim.anchors.pop(a.id, None) is None:
        return
    a.alive = False
    if hatch:
        hatch_cocoon(sim, a)
    else:
        fx(sim, "cocoon_break", a.x, a.z, tm=a.owner.team)


def anchor_destroyed(sim, a):
    remove_anchor(sim, a)


@handler("zone")
def zone(cx):
    """바닥에 장판을 깐다: 안의 적은 둔화 + 지속 피해."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    gx, gz = cx.ground_point(ab["range"])
    spawn_zone(sim, c, ab, cx.rank, gx, gz)
    return True


def spawn_zone(sim, c, ab, rank, gx, gz):
    """(gx, gz) 에 장판을 만든다 (ab 의 radius / duration / slow / damage_per_sec ...). 점프 내려찍기도 이걸 쓴다."""
    radius = ab["radius"]
    rv = gamedata.rank_value
    dur = rv(ab, "duration", rank)
    data = {"slow": rv(ab, "slow", rank),
            "dps": sim.ability_amount(c, ab, rank, "damage_per_sec"), "dtype": ab.get("damage_type", "magic"),
            "dps_next": 0.0}
    style = ab.get("style", "zone")

    def spawn(sim_, eff=None):
        t = sim_.time
        z = Zone(sim_.new_id(), "aura", c.team, c, gx, gz, radius, t + dur, style, data=data)
        z.born = t
        sim_.zones[z.id] = z
        fx(sim_, "zone_start", gx, gz, r=radius, style=style, tm=c.team)
    delay = ab.get("delay", 0.0)
    if delay > 0:
        eff = GroundEffect(sim.new_id(), c.team, c, gx, gz, radius, sim.time + delay, style, lambda s_, e: spawn(s_))
        sim.effects[eff.id] = eff
    else:
        spawn(sim)


def tick_aura(sim, z, dt):
    t = sim.time
    d = z.data
    owner = z.owner
    if d["slow"]:
        for u in sim.enemies_in_radius(z.team, z.x, z.z, z.radius):
            u.apply_slow(t, d["slow"], 0.4)
    if d.get("dps") and t >= d["dps_next"]:                 # 장판 위의 적에게 0.5초마다 피해 (독 거미줄)
        d["dps_next"] = t + 0.5
        for u in sim.enemies_in_radius(z.team, z.x, z.z, z.radius):
            sim.deal_damage(owner, u, d["dps"] * 0.5, d["dtype"], ability=True)


# ====================================================================== 8번: 동굴 여왕 거미 (보스러시 이식)
@handler("volley")
def volley(cx):
    """부채꼴로 여러 발을 동시에 쏜다 (독침 탄막). 한 발씩 따로 명중한다."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    n = max(1, int(ab.get("count", 5)))
    spread = math.radians(ab.get("spread", 55))
    dmg = sim.ability_damage(c, ab, cx.rank)
    dtype = ab.get("damage_type", "magic")
    for j in range(n):
        ang = (j / (n - 1) - 0.5) * spread if n > 1 else 0.0
        ux, uz = rotate(cx.ux, cx.uz, ang)
        p = Projectile(sim.new_id(), c.team, c, c.x + ux * 0.7, c.z + uz * 0.7, ab.get("style", "spine"), ab["speed"])
        p.dx, p.dz = ux, uz
        p.remaining = ab["range"] - 0.7                      # 시전자 중심에서 range 까지 (표시 범위와 같다)
        p.width = ab["width"]
        p.pierce = False

        def on_hit(sim_, target, dmg=dmg):
            sim_.deal_damage(c, target, dmg, dtype, ability=True)
            apply_cc(sim_, ab, cx.rank, target)
        p.on_hit = on_hit
        sim.projectiles[p.id] = p
    fx(sim, "volley", c.x, c.z, a=math.atan2(cx.uz, cx.ux), w=ab.get("spread", 55), style=ab.get("style", "spine"), tm=c.team)
    return True


@handler("leap_slam")
def leap_slam(cx):
    """도약해 내리꽂는다. 대상 지정형("aim": "enemy")이면 마우스에 가장 가까운 적 챔피언에게 뛰어들어 스턴을 걸고
    그 자리에 장판("zone")을 깐다 (거미 여왕 R). 아니면 지정한 지점으로 도약 (피해 + 둔화)."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    if c.rooted(sim.time):
        return False
    ox, oz = c.x, c.z
    land = {"ab": ab, "rank": cx.rank, "dmg": sim.ability_damage(c, ab, cx.rank), "target": None}
    follow = None
    if ab.get("aim") == "enemy":
        tg = sim.pick_enemy_champion(c, cx.x, cx.z, ab["range"])
        if tg is None:
            return False
        follow = tg.id
        land["target"] = tg.id
        tx, tz = tg.x, tg.z
    else:
        dist = min(cx.d, ab["range"])
        tx, tz = sim.resolve_position(c.x + cx.ux * dist, c.z + cx.uz * dist, c.radius)
    flight = ab.get("flight") or max(0.15, math.hypot(tx - c.x, tz - c.z) / ab["speed"])    # 공중에 떠 있는 시간
    windup = ab.get("windup", 0.0)                                                          # 웅크렸다가 뛰기까지
    c.clear_orders()
    c.dash = {"x": tx, "z": tz, "speed": ab.get("speed", 22.0), "follow": follow, "empower": None, "land": land,
              "flight": flight if ab.get("flight") else None, "delay": windup}
    fx(sim, "leap", ox, oz, x2=tx, z2=tz, dur=flight, delay=windup, d=c.id, tm=c.team, tg=follow,
       r=ab.get("radius", 0.0), zr=(ab.get("zone") or {}).get("radius", 0.0))
    return True


def land_slam(sim, c, land):
    """leap_slam 의 착지: 반경 안의 적에게 피해와 둔화, 지정한 대상은 스턴, 그 자리에 장판."""
    ab = land["ab"]
    rank = land["rank"]
    for u in sim.enemies_in_radius(c.team, c.x, c.z, ab["radius"]):
        sim.deal_damage(c, u, land["dmg"], ab.get("damage_type", "physical"), ability=True)
        apply_cc(sim, ab, rank, u)
    tg = sim.unit(land["target"]) if land.get("target") else None
    if tg is not None and tg.alive and not getattr(tg, "dead", False):
        if tg.apply_stun(sim.time, gamedata.rank_value(ab, "stun", rank, 1.2)):
            interrupt(tg)
    if land.get("dive") or land.get("sky"):
        c.untarget_until = 0.0
    if land.get("dive"):
        fx(sim, "dive_out", c.x, c.z, r=ab["radius"], d=c.id, tm=c.team)
    fx(sim, "slam", c.x, c.z, r=ab["radius"], style=ab.get("style", "pounce"), tm=c.team)
    if ab.get("zone"):
        spawn_zone(sim, c, ab["zone"], rank, c.x, c.z)


# ====================================================================== 거미 여왕 E: 새끼 거미 고치
@handler("cocoon")
def cocoon(cx):
    """지정한 곳에 시전자→마우스 선과 수직(T자)으로 고치 여러 개를 놓는다. 시간이 지나면 고치마다 새끼 거미가 부화한다."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    gx, gz = cx.ground_point(ab["range"])
    n = max(1, int(ab.get("count", 3)))
    gap = ab.get("spacing", 1.7)
    hatch = cx.val("hatch", 6.5)
    mine = sorted((a for a in sim.anchors.values() if getattr(a, "cocoon", False) and a.owner is c), key=lambda a: a.until)
    while len(mine) + n > int(ab.get("max_cocoons", 6)) and mine:
        remove_anchor(sim, mine.pop(0))                        # 너무 많으면 가장 오래된 것부터 터뜨린다
    # 새끼 거미 체력은 거미 최대 체력에 비례
    baby = {"hp": cx.val("baby_hp_ratio", 0.33) * c.max_hp, "speed": ab.get("baby_speed", 5.4),
            "dmg": cx.val("baby_ad", 10.0) + cx.val("baby_ad_ratio", 0.1) * c.stats["ad"],      # 평타 한 대의 피해 (물리)
            "proj_speed": c.data["stats"].get("projectile_speed", 20), "max_babies": ab.get("max_babies", 12), "ab": ab, "rank": cx.rank}
    px, pz = -cx.uz, cx.ux                                     # 시전 방향에 수직인 방향
    for k in range(n):
        off = (k - (n - 1) / 2) * gap
        x, z = mapdata.clamp_to_map(gx + px * off, gz + pz * off)
        a = Cocoon(sim.new_id(), c.team, c, x, z, sim.time + hatch, hp=cx.val("cocoon_hp", 100.0))
        a.born = sim.time
        a.baby = baby
        sim.anchors[a.id] = a
        fx(sim, "cocoon_set", x, z, tm=c.team, hatch=hatch)
    return True


def hatch_cocoon(sim, a):
    """고치가 부화: 새끼 거미 한 마리가 튀어나온다."""
    c, b = a.owner, a.baby
    m = Minion(sim.new_id(), c.team, a.x, a.z, "spiderling", 0.0)
    m.max_hp = m.hp = b["hp"]
    m.owner = c
    m.baby = b
    m.move_speed = b["speed"]
    m.attack_speed = b.get("attack_speed", m.attack_speed)
    m.facing = c.facing
    sim.minions[m.id] = m
    kids = sorted((e for e in sim.minions.values() if e.mtype == "spiderling" and e.owner is c), key=lambda e: e.id)
    while len(kids) > int(b.get("max_babies", 12)):          # 새끼 거미가 너무 많이 쌓이면 가장 오래된 것부터 정리
        o = kids.pop(0)
        sim.minions.pop(o.id, None)
        sim.gone_minions.append(o.id)
        o.alive = False
    fx(sim, "cocoon_hatch", a.x, a.z, tm=c.team)


ZONE_TICK.update({"aura": tick_aura})


# ====================================================================== 이무기 (보스러시 2층 보스에서 옮김)
@handler("spit_pool")
def spit_pool(cx):
    """Q 독 뱉기 / 화염 뱉기: 덩어리를 포물선으로 뱉어 착지한 자리에 웅덩이(장판)를 남긴다. style 이 모양을 정한다 (venom 독 / fire 불)."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    gx, gz = cx.ground_point(ab["range"])
    flight = ab.get("flight", 0.7)
    windup = ab.get("windup", 0.0)                      # 머리를 쳐들었다가 뱉기까지 (그동안 입에서 아직 안 나간다)
    style = ab.get("style", "venom")

    def launch(sim_):
        fx(sim_, "spit", c.x, c.z, x2=gx, z2=gz, dur=flight, d=c.id, style=style, tm=c.team)
    if windup > 0:
        sim.schedule(windup, launch)
    else:
        launch(sim)
    spawn_zone(sim, c, dict(ab, delay=windup + flight), cx.rank, gx, gz)
    land_dmg = sim.ability_damage(c, ab, cx.rank)
    r = ab["radius"]

    def land(sim_, rank=cx.rank):
        for u in sim_.enemies_in_radius(c.team, gx, gz, r):
            sim_.deal_damage(c, u, land_dmg, ab.get("damage_type", "magic"), ability=True)
        fx(sim_, "spit_land", gx, gz, r=r, style=style, tm=c.team)
    sim.schedule(windup + flight, land)
    return True


@handler("lunge")
def lunge(cx):
    """W 일직선 돌진: 잠깐 몸을 쳐들고 노려본 뒤(예고선) 쏜살같이 일직선으로 달려들며 지나는 길의 적을 물어뜯는다."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    if c.rooted(sim.time):
        return False
    dist = ab["range"]
    tx, tz = sim.resolve_position(c.x + cx.ux * dist, c.z + cx.uz * dist, c.radius)
    windup = ab.get("windup", 0.4)
    c.clear_orders()
    sweep = {"ab": ab, "rank": cx.rank, "dmg": sim.ability_damage(c, ab, cx.rank), "half": ab.get("width", 1.6) / 2, "hit": set(),
             "fx": ab.get("hit_fx", "bite")}
    c.dash = {"x": tx, "z": tz, "speed": ab["speed"], "follow": None, "empower": None, "delay": windup, "sweep": sweep}
    dur = math.hypot(tx - c.x, tz - c.z) / ab["speed"]
    if ab.get("untargetable"):                          # 망령 걸음: 지나가는 동안 대상으로 지정되지 않는다
        c.untarget_until = sim.time + windup + dur + 0.05
    fx(sim, "lunge", c.x, c.z, x2=tx, z2=tz, delay=windup, dur=dur, w=ab.get("width", 1.6),
       d=c.id, tm=c.team, style=ab.get("style", "lunge"))
    return True


def sweep_hit(sim, c, sw, ox, oz):
    """돌진하는 머리가 (ox,oz)->현재 위치로 지나간 길에 닿은 적을 한 번씩 물어뜯는다."""
    ab = sw["ab"]
    mx, mz = (ox + c.x) / 2, (oz + c.z) / 2
    reach = math.hypot(c.x - ox, c.z - oz) / 2 + sw["half"] + 1.0
    inner_hit = sw.setdefault("inner_hit", set())
    for u in sim.enemies_in_radius(c.team, mx, mz, reach):
        inner_done = not sw.get("inner") or u.id in inner_hit
        if u.id in sw["hit"] and inner_done:
            continue
        # 선분 (o -> c) 과 u 사이 거리
        vx, vz = c.x - ox, c.z - oz
        ll = vx * vx + vz * vz
        k = 0.0 if ll < 1e-9 else max(0.0, min(1.0, ((u.x - ox) * vx + (u.z - oz) * vz) / ll))
        dd = math.hypot(u.x - (ox + vx * k), u.z - (oz + vz * k))
        if dd > sw["half"] + u.radius:
            continue
        if u.id not in sw["hit"]:                                      # 바깥 바에 처음 닿으면 기본 피해
            sw["hit"].add(u.id)
            sim.deal_damage(c, u, sw["dmg"], ab.get("damage_type", "physical"), ability=True)
            apply_cc(sim, ab, sw["rank"], u)
            fx(sim, sw.get("fx", "bite"), u.x, u.z, tm=c.team)
        if sw.get("inner") and u.id not in inner_hit and dd <= sw["inner"] + u.radius:     # 안쪽 바에 들어오면 나머지 피해 (합쳐서 mult 배)
            inner_hit.add(u.id)
            sim.deal_damage(c, u, sw["dmg"] * (sw.get("mult", 2.0) - 1.0), ab.get("damage_type", "physical"), ability=True)


@handler("serpent_slam")
def serpent_slam(cx):
    """E 내려찍기: 머리를 높이 쳐들었다가(예고 원) 한가운데로 내리꽂는다. 충격파 고리가 바깥으로 퍼지며 맞은 적을 늦춘다.
    대상 지정형("aim": "enemy")이면 마우스에 가장 가까운 적 챔피언을 노리고, 쳐든 동안 대상이 움직이면 예고 원도 따라간다."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    follow = None
    if ab.get("aim") == "enemy":
        tg = sim.pick_enemy_champion(c, cx.x, cx.z, ab["range"])
        if tg is None:
            return False
        follow = tg.id
        gx, gz = tg.x, tg.z
    else:
        gx, gz = cx.ground_point(ab["range"])
    r = ab["radius"]
    wr = ab.get("wave_radius", r * 2.0)
    delay = ab.get("delay", 0.75)
    dmg = sim.ability_damage(c, ab, cx.rank)
    wdmg = dmg * ab.get("wave_ratio", 0.5)
    dtype = ab.get("damage_type", "physical")
    hit = set()

    def strike(sim_, eff):
        gx, gz = eff.x, eff.z
        for u in sim_.enemies_in_radius(c.team, eff.x, eff.z, r):
            hit.add(u.id)
            sim_.deal_damage(c, u, dmg, dtype, ability=True)
            apply_cc(sim_, ab, cx.rank, u)
        fx(sim_, "slam", eff.x, eff.z, r=r, style="serpent", tm=c.team)

        steps = 4
        for i in range(1, steps + 1):
            def wave(s2, i=i):
                inner, outer = r + (wr - r) * (i - 1) / steps, r + (wr - r) * i / steps
                for u in s2.enemies_in_radius(c.team, gx, gz, outer + 0.4):
                    d = math.hypot(u.x - gx, u.z - gz)
                    if u.id in hit or d < inner - u.radius or d > outer + u.radius:
                        continue
                    hit.add(u.id)
                    s2.deal_damage(c, u, wdmg, dtype, ability=True)
                    u.apply_slow(s2.time, ab.get("wave_slow", 0.4), ab.get("wave_slow_duration", 1.2))
            sim.schedule(ab.get("wave_delay", 0.14) * i, wave)
        fx(sim_, "shockwave", eff.x, eff.z, r=r, r2=wr, dur=ab.get("wave_delay", 0.14) * steps, tm=c.team)
    eff = GroundEffect(sim.new_id(), c.team, c, gx, gz, r, sim.time + delay, "serpent", strike)
    eff.follow = follow
    sim.effects[eff.id] = eff
    c.clear_orders()
    c.lock_until = sim.time + delay                    # 머리를 쳐들었다 내리꽂는 동안은 움직이거나 다른 행동을 할 수 없다
    fx(sim, "serpent_rear", c.x, c.z, d=c.id, dur=delay, x2=gx, z2=gz, tm=c.team, tg=follow)
    return True


@handler("dive")
def dive(cx):
    """R 잠행: 머리부터 땅속으로 가라앉아(그동안 맞힐 수 없다) 땅속을 헤엄쳐 지정한 곳에서 솟구쳐 주변 적을 띄운다."""
    sim, c, ab = cx.sim, cx.c, cx.ab
    if c.rooted(sim.time):
        return False
    gx, gz = cx.ground_point(ab["range"])
    gx, gz = sim.resolve_position(gx, gz, c.radius)
    sink = ab.get("sink", 0.6)
    travel = max(0.25, min(ab.get("travel_max", 0.9), math.hypot(gx - c.x, gz - c.z) / ab.get("speed", 20.0)))
    c.clear_orders()
    interrupt(c)
    c.untarget_until = sim.time + sink + travel + 0.05
    land = {"ab": ab, "rank": cx.rank, "dmg": sim.ability_damage(c, ab, cx.rank), "target": None, "dive": True}
    c.dash = {"x": gx, "z": gz, "speed": ab.get("speed", 20.0), "follow": None, "empower": None, "land": land,
              "flight": travel, "delay": sink}
    fx(sim, "dive", c.x, c.z, x2=gx, z2=gz, sink=sink, dur=travel, d=c.id, r=ab["radius"], tm=c.team)
    return True


# ====================================================================== 용 (보스러시 3층 보스에서 옮김)
def knock_away(sim, c, ab, rank, u, dx, dz, default_dist=2.0):
    """u 를 (dx, dz) 방향(단위 벡터)으로 밀어낸다. 밀리는 동안 행동 불가, 벽에 부딪히면 wall_stun 만큼 기절."""
    dist = gamedata.rank_value(ab, "knock_distance", rank, default_dist)
    speed = gamedata.rank_value(ab, "knock_speed", rank, 14.0)
    if dist <= 0:
        return
    if u.apply_stun(sim.time, dist / speed + 0.05):
        interrupt(u)
        u.kb = {"dx": dx, "dz": dz, "left": dist, "speed": speed, "stun": gamedata.rank_value(ab, "wall_stun", rank, 0.8)}


@handler("tornado")
def tornado(cx):
    """W 날개 바람 + 회오리: 날개를 치켜들었다가 휘두르는 순간(delay),
    ① 전방 부채꼴(cone_range, angle)의 적은 피해 + 둔화 + 밀려나고, ② 한가운데로는 회오리 투사체가 굴러가며 닿는 적을 공중에 띄운다(에어본)."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    delay = ab.get("delay", 0.35)
    ux, uz = cx.ux, cx.uz
    dmg = sim.ability_damage(c, ab, rank)
    dtype = ab.get("damage_type", "magic")
    cone_r = ab.get("cone_range", 6.5)
    half = math.radians(ab.get("angle", 100)) / 2
    cone_dmg = sim.ability_amount(c, ab, rank, "cone_damage")
    fx(sim, "gust_wind", c.x, c.z, a=math.atan2(uz, ux), r=cone_r, w=ab.get("angle", 100), delay=delay, d=c.id, tm=c.team)

    def launch(sim_):
        if c.dead or c.stunned(sim_.time):                      # 준비하는 동안 쓰러지거나 기절하면 불발
            return
        for u in sim_.enemies_in_radius(c.team, c.x, c.z, cone_r):      # ① 부채꼴 바람
            rx, rz = u.x - c.x, u.z - c.z
            d = math.hypot(rx, rz)
            if d > 1e-6:
                ang = math.acos(max(-1.0, min(1.0, (rx * ux + rz * uz) / d)))
                if ang > half + math.asin(min(1.0, u.radius / d)):
                    continue
            sim_.deal_damage(c, u, cone_dmg, dtype, ability=True)
            u.apply_slow(sim_.time, gamedata.rank_value(ab, "slow", rank), gamedata.rank_value(ab, "slow_duration", rank, 1.0))
            nx, nz = (rx / d, rz / d) if d > 1e-6 else (ux, uz)
            knock_away(sim_, c, ab, rank, u, nx, nz, 2.0)
        fx(sim_, "gust", c.x, c.z, a=math.atan2(uz, ux), r=cone_r, w=ab.get("angle", 100), tm=c.team)
        p = Projectile(sim_.new_id(), c.team, c, c.x + ux * 1.2, c.z + uz * 1.2, ab.get("style", "tornado"), ab["speed"])    # ② 회오리
        p.dx, p.dz = ux, uz
        p.remaining = ab["range"]
        p.width = ab["width"]
        p.pierce = True

        def on_hit(s_, target):
            s_.deal_damage(c, target, dmg, dtype, ability=True)
            if target.apply_stun(s_.time, gamedata.rank_value(ab, "airborne", rank, 0.9), airborne=True):
                interrupt(target)
            target.apply_slow(s_.time, gamedata.rank_value(ab, "slow", rank), gamedata.rank_value(ab, "slow_duration", rank, 1.0))
        p.on_hit = on_hit
        sim_.projectiles[p.id] = p
    sim.schedule(delay, launch)
    return True


@handler("wing_sweep")
def wing_sweep(cx):
    """E 날개 후려치기: 날개를 뒤로 젖혔다가(delay) 몸 둘레를 크게 후려친다. 맞은 적은 피해 + 둔화 + 바깥으로 밀려난다."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    R = ab["radius"]
    delay = ab.get("delay", 0.45)
    dmg = sim.ability_damage(c, ab, rank)
    dtype = ab.get("damage_type", "physical")
    fx(sim, "wing_wind", c.x, c.z, r=R, delay=delay, d=c.id, tm=c.team)

    def strike(sim_):
        if c.dead or c.stunned(sim_.time):
            return
        for u in sim_.enemies_in_radius(c.team, c.x, c.z, R):
            sim_.deal_damage(c, u, dmg, dtype, ability=True)
            apply_cc(sim_, ab, rank, u)
            rx, rz = u.x - c.x, u.z - c.z
            d = math.hypot(rx, rz)
            knock_away(sim_, c, ab, rank, u, *((rx / d, rz / d) if d > 1e-6 else (cx.ux, cx.uz)), 1.8)
        fx(sim_, "slam", c.x, c.z, r=R, style="wing", tm=c.team)
    sim.schedule(delay, strike)
    return True


@handler("sky_dive")
def sky_dive(cx):
    """R 불꽃 비행: 하늘 높이 떠오른 뒤(rise 동안 대상 지정 불가) 지정한 곳으로 수평으로 날아가며 입에서 아래로 불을 쏟고,
    도착하면 내려앉는다. 지나는 길은 바깥 바(path_width)에 닿으면 불길 피해, 안쪽 바(inner_width)에 있으면 inner_mult 배 피해, 착지 지점은 큰 피해 + 둔화 + 불길 웅덩이."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    if c.rooted(sim.time):
        return False
    gx, gz = cx.ground_point(ab["range"])
    gx, gz = sim.resolve_position(gx, gz, c.radius)
    dist = math.hypot(gx - c.x, gz - c.z)
    rise = ab.get("rise", 1.0)
    flight = max(ab.get("min_flight", 0.7), dist / ab.get("speed", 10.0))
    c.clear_orders()
    interrupt(c)
    c.untarget_until = sim.time + rise + flight + 0.05
    sweep = {"ab": ab, "rank": rank, "dmg": sim.ability_amount(c, ab, rank, "path_damage"), "half": ab.get("path_width", 5.0) / 2,
             "inner": ab.get("inner_width", 3.0) / 2, "mult": ab.get("inner_mult", 2.0), "hit": set(), "fx": "burn"}
    land = {"ab": ab, "rank": rank, "dmg": sim.ability_damage(c, ab, rank), "target": None, "sky": True}
    c.dash = {"x": gx, "z": gz, "speed": 20.0, "follow": None, "empower": None, "land": land, "sweep": sweep,
              "delay": rise, "flight": flight}
    fx(sim, "sky_dive", c.x, c.z, x2=gx, z2=gz, rise=rise, dur=round(flight, 3), h=ab.get("height", 6.5), r=ab["radius"],
       w=ab.get("path_width", 5.0), w2=ab.get("inner_width", 3.0), zr=ab.get("zone", {}).get("radius", 0.0), d=c.id, tm=c.team)
    return True


# ====================================================================== 망령 사신
def in_cone(c, u, ux, uz, half):
    """u 가 c 에서 (ux, uz) 방향 반각 half 의 부채꼴 안에 (몸 크기까지 쳐서) 들어오는가."""
    rx, rz = u.x - c.x, u.z - c.z
    d = math.hypot(rx, rz)
    if d < 1e-6:
        return True
    ang = math.acos(max(-1.0, min(1.0, (rx * ux + rz * uz) / d)))
    return ang <= half + math.asin(min(1.0, u.radius / d))


@handler("scythe_sweep")
def scythe_sweep(cx):
    """Q 영혼 베기: 낫을 젖혔다가(delay) 앞쪽 부채꼴을 휩쓴다. 날끝(inner_radius 바깥)에 걸린 적은 edge_mult 배 피해 + 둔화,
    날끝으로 벤 적 챔피언마다 체력을 회복한다."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    delay = ab.get("delay", 0.3)
    R = ab["range"]
    inner = ab.get("inner_radius", R * 0.6)
    half = math.radians(ab.get("angle", 160)) / 2
    ux, uz = cx.ux, cx.uz
    dmg = sim.ability_damage(c, ab, rank)
    dtype = ab.get("damage_type", "physical")
    heal_each = sim.ability_amount(c, ab, rank, "heal")
    a = math.atan2(uz, ux)
    fx(sim, "reap_wind", c.x, c.z, a=a, r=R, w=ab.get("angle", 160), delay=delay, d=c.id, tm=c.team)

    def strike(sim_):
        if c.dead or c.stunned(sim_.time):
            return
        healed = 0.0
        for u in sim_.enemies_in_radius(c.team, c.x, c.z, R):
            if not in_cone(c, u, ux, uz, half):
                continue
            edge = math.hypot(u.x - c.x, u.z - c.z) + u.radius >= inner
            sim_.deal_damage(c, u, dmg * (ab.get("edge_mult", 1.5) if edge else 1.0), dtype, ability=True)
            if edge:
                u.apply_slow(sim_.time, gamedata.rank_value(ab, "slow", rank), gamedata.rank_value(ab, "slow_duration", rank, 1.0))
                fx(sim_, "reap_edge", u.x, u.z, tm=c.team)
                if isinstance(u, Champion):
                    healed += heal_each
        if healed > 0:
            sim_.heal(c, healed, c)
        fx(sim_, "reap_sweep", c.x, c.z, a=a, r=R, r0=inner, w=ab.get("angle", 160), tm=c.team)
    sim.schedule(delay, strike)
    c.clear_orders()
    c.lock_until = sim.time + delay                    # 젖히는 동안은 제자리
    return True


@handler("scythe_throw")
def scythe_throw(cx):
    """W 낫 던지기: 젖혔다가(windup) 낫을 일직선으로 던진다. 끝까지 날아간 낫은 시전자에게 되돌아오며,
    가는 길과 오는 길에 닿은 적을 한 번씩 벤다 (오는 길은 return_ratio 배 피해)."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    windup = ab.get("windup", 0.22)
    ux, uz = cx.ux, cx.uz
    dmg = sim.ability_damage(c, ab, rank)
    dtype = ab.get("damage_type", "physical")

    def caught(sim_, p):
        fx(sim_, "scythe_catch", p.x, p.z, d=c.id, tm=c.team)

    def launch(sim_):
        if c.dead or c.stunned(sim_.time):                 # 던지기 전에 쓰러지거나 기절하면 손에 그대로 남는다
            fx(sim_, "scythe_catch", c.x, c.z, d=c.id, tm=c.team)
            return
        p = Projectile(sim_.new_id(), c.team, c, c.x + ux * 0.6, c.z + uz * 0.6, ab.get("style", "scythe"), ab["speed"])
        p.dx, p.dz = ux, uz
        p.remaining = ab["range"] - 0.6
        p.width = ab["width"]
        p.pierce = True
        p.ret = {"owner": c.id, "back": False, "speed": ab.get("return_speed", ab["speed"]), "until": sim_.time + 4.0}
        p.on_return = caught

        def on_hit(s_, target):
            k = ab.get("return_ratio", 0.6) if p.ret["back"] else 1.0
            s_.deal_damage(c, target, dmg * k, dtype, ability=True)
            target.apply_slow(s_.time, gamedata.rank_value(ab, "slow", rank), gamedata.rank_value(ab, "slow_duration", rank, 1.0))
        p.on_hit = on_hit
        sim_.projectiles[p.id] = p
        fx(sim_, "scythe_throw", c.x, c.z, d=c.id, tm=c.team)
    sim.schedule(windup, launch)
    c.clear_orders()
    c.lock_until = sim.time + windup
    return True


@handler("execute")
def execute(cx):
    """R 사형 선고: 대상 적 챔피언 머리 위로 영혼의 낫을 불러내 delay 뒤 내려친다 (예고 원은 대상을 따라간다).
    둘레의 적은 피해 + 잃은 체력 × missing_hp 만큼 더 입고, 대상이 이걸로 쓰러지면 재사용 대기시간의 kill_refund 가 돌아온다."""
    sim, c, ab, rank = cx.sim, cx.c, cx.ab, cx.rank
    tg = sim.pick_enemy_champion(c, cx.x, cx.z, ab["range"])
    if tg is None:
        return False
    delay = ab.get("delay", 0.8)
    r = ab.get("radius", 1.8)
    dmg = sim.ability_damage(c, ab, rank)
    miss = gamedata.rank_value(ab, "missing_hp", rank, 0.0)
    dtype = ab.get("damage_type", "physical")

    def strike(sim_, eff):
        for u in sim_.enemies_in_radius(c.team, eff.x, eff.z, r):
            extra = miss * max(0.0, u.max_hp - u.hp) if isinstance(u, Champion) else 0.0
            sim_.deal_damage(c, u, dmg + extra, dtype, ability=True)
            apply_cc(sim_, ab, rank, u)
        if tg.dead and ab.get("kill_refund"):
            cd = c.cooldown_of("R")
            c.ready_at["R"] = min(c.ready_at["R"], sim_.time + cd * (1.0 - ab["kill_refund"]))
            fx(sim_, "reap_soul", tg.x, tg.z, d=c.id, tm=c.team)
        fx(sim_, "reap_strike", eff.x, eff.z, r=r, tm=c.team)
    eff = GroundEffect(sim.new_id(), c.team, c, tg.x, tg.z, r, sim.time + delay, "reap", strike)
    eff.follow = tg.id
    sim.effects[eff.id] = eff
    c.clear_orders()
    c.lock_until = sim.time + delay
    fx(sim, "reap", c.x, c.z, d=c.id, dur=delay, x2=tg.x, z2=tg.z, r=r, tg=tg.id, tm=c.team)
    return True
