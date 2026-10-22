"""챔피언 봇 AI. 플레이어와 같은 명령 함수(sim.cast, sim.cmd_move 등)를 사용한다.

스킬은 type 별 규칙(plan)으로 쓸 시점과 조준 지점을 정한다.
챔피언 data 에 "bot_priority": ["R","E","W","Q"] 를 넣으면 스킬을 검토하는 순서를 바꿀 수 있다.

- 부쉬: 쫓던 적이 부쉬로 숨으면 마지막으로 본 곳까지 따라 들어가 확인하고, 할 일이 없을 때는 가까운 부쉬에 숨어 기다리며,
  쫓기며 도망칠 때는 뒤쪽 부쉬를 지나 시야를 끊는다.
- 포탑: 체력이 낮은 적이라도 포탑 아래로는 "포탑에 맞으면서 처치하고 빠져나올 수 있을 때"만 들어간다.
"""
import math
import random

from ..shared import data as gamedata
from ..shared import mapdata
from ..shared.constants import EXHAUST_RANGE, IGNITE_RANGE, MARK_RANGE, TURRET_PERIOD, turret_damage
from . import items as item_fx
from .bot_shop import BotShopper

POKE_TYPES = ("volley",)


class BotBrain:
    def __init__(self, champ):
        self.c = champ
        self.rng = random.Random(champ.id * 7919)
        self.think_at = 0.0
        self.reaction = self.rng.uniform(0.18, 0.3)
        self.lane_offset = self.rng.uniform(-3.0, 3.0)
        self.bush_lover = self.rng.random() < 0.7      # 할 일이 없을 때 부쉬에 숨어 기다리는 성격
        self.seen = {}                  # 적 챔피언 id -> (x, z, 본 시각, 체력 비율) — 시야에서 사라진 적을 쫓을 때 쓴다
        self.chase = None               # 쫓던 적 챔피언 id
        self.shopper = BotShopper(champ, random.Random(champ.id * 104729 + random.randrange(1 << 30)))

    # ------------------------------------------------------------------
    def update(self, sim, dt):
        c = self.c
        if sim.time < self.think_at:
            return
        self.think_at = sim.time + self.reaction
        self.level_up(sim)
        if sim.can_shop(c):
            self.shop(sim)
        if not c.dead:
            self.use_spells(sim)            # 소환사 주문은 기절 중에도 쓴다 (정화)
            self.use_items(sim)
        if c.dead or c.dash or c.stunned(sim.time) or sim.locked(c):
            return
        self.decide(sim)

    def use_spells(self, sim):
        """점멸·표식 외의 소환사 주문(회복·유체화·방어막·정화·탈진·점화)을 쓸 때를 정한다."""
        c = self.c
        t = sim.time
        enemies = [e for e in sim.champions.values()
                   if e.team != c.team and not e.dead and c.dist_to(e) <= 9 and sim.can_see(c.team, e)]
        hp = c.hp / max(1.0, c.max_hp)
        hurt = t - c.last_hit_at < 1.5
        for slot, spell in zip(("D", "F"), c.spells):
            if spell in ("flash", "mark") or t < c.ready_at[slot]:
                continue
            aim = None
            if spell == "cleanse":
                fire = bool(enemies) and (c.rooted(t) or c.silenced(t))
            elif spell == "heal":
                fire = hp < 0.4 and (bool(enemies) or hurt)
            elif spell == "barrier":
                fire = hp < 0.5 and (bool(enemies) or hurt)
            elif spell == "ghost":
                weak = [e for e in enemies if e.hp / max(1.0, e.max_hp) < 0.3 and c.dist_to(e) > 4.0]
                fire = bool(enemies) and (hp < 0.3 or bool(weak))
            elif spell == "exhaust":
                near = [e for e in enemies if c.dist_to(e) <= EXHAUST_RANGE - 0.5]
                fire = bool(near) and hp < 0.7
                aim = min(near, key=lambda e: c.dist_to(e)) if near else None
            else:       # ignite
                weak = [e for e in enemies if c.dist_to(e) <= IGNITE_RANGE - 0.5 and e.hp / max(1.0, e.max_hp) < 0.35]
                fire = bool(weak)
                aim = min(weak, key=lambda e: e.hp) if weak else None
            if fire:
                sim.cast_spell(c, slot, aim.x if aim else c.x, aim.z if aim else c.z)

    def use_items(self, sim):
        """사용 아이템: 흡혈 대낫은 적 챔피언이 닿으면, 성채·모래시계는 위험할 때."""
        c = self.c
        t = sim.time
        if c.stunned(t):
            return
        hp = c.hp / max(1.0, c.max_hp)
        hurt = t - c.last_hit_at < 1.5
        for slot, iid in enumerate(c.items):
            act = gamedata.items()[iid].get("active")
            if act is None or t < c.item_cd.get(iid, 0.0):
                continue
            if act["kind"] == "drain":
                fire = any(isinstance(u, type(c)) for u in sim.enemies_in_radius(c.team, c.x, c.z, act["radius"] - 0.3))
            else:
                fire = hurt and hp < (0.45 if act["kind"] == "shield" else 0.25)
            if fire:
                item_fx.use(sim, c, slot)
                return

    def level_up(self, sim):
        c = self.c
        for _ in range(c.skill_points):
            order = [s for s in ("Q", "E", "W") if c.ranks[s] == 0] + c.data.get("skill_order", ["R", "Q", "E", "W"])
            for slot in order:
                if c.ranks[slot] < c.max_rank(slot):
                    sim.level_ability(c, slot)
                    break

    def shop(self, sim):
        self.shopper.shop(sim)              # 가중치 무작위로 고른 목표 아이템을 재료부터 사 모은다 (bot_shop.py)

    # ------------------------------------------------------------------ 판단 보조
    def enemy_turrets(self, sim):
        return [s for s in sim.structures.values() if s.skind == "turret" and s.alive and s.team != self.c.team]

    def turret_threat(self, sim, x, z):
        """(x,z) 가 적 포탑 사거리 안이고 그 포탑이 미니언을 노리고 있지 않으면 위험."""
        for s in self.enemy_turrets(sim):
            if math.hypot(s.x - x, s.z - z) <= mapdata.TURRET_RANGE + 1.0:
                tank = [m for m in sim.minions.values()
                        if m.team == self.c.team and s.dist_to(m) <= mapdata.TURRET_RANGE]
                if len(tank) < 2:
                    return True
                tgt = sim.unit(s.target) if s.target else None
                if tgt is self.c:
                    return True
        return False

    def in_danger(self, sim):
        """귀환하면 안 되는 상황: 최근 피해, 근처에 보이는 적 챔피언/미니언, 적 포탑 사거리."""
        c = self.c
        if sim.time - c.last_hit_at < 3.0:
            return True
        for e in sim.champions.values():
            if e.team != c.team and not e.dead and c.dist_to(e) <= 16 and sim.can_see(c.team, e):
                return True
        for m in sim.minions.values():
            if m.team != c.team and c.dist_to(m) <= 8 and sim.can_see(c.team, m):
                return True
        return any(c.dist_to(s) <= mapdata.TURRET_RANGE + 2 for s in self.enemy_turrets(sim))

    def turret_on_me(self, sim):
        """나를 노리고 있는 적 포탑 (없으면 None)."""
        for s in self.enemy_turrets(sim):
            if s.target == self.c.id and self.c.dist_to(s) <= mapdata.TURRET_RANGE + self.c.radius + 0.5:
                return s
        return None

    def under_turret(self, sim, x, z, margin=1.5):
        """(x, z) 가 적 포탑 사거리(+margin) 안이면 그 포탑, 아니면 None.
        적 챔피언을 때리면 미니언이 포탑 아래에 있어도 포탑이 나를 노리므로 여기서는 미니언을 따지지 않는다."""
        for s in self.enemy_turrets(sim):
            if math.hypot(s.x - x, s.z - z) <= mapdata.TURRET_RANGE + margin:
                return s
        return None

    def quick_kill(self, sim, e):
        """포탑 아래에서도 해 볼 만한가: 쫓아갈 필요 없이 이미 닿아 있고, 지금 쓸 수 있는 스킬과 평타로 1초 안에 끝내고
        포탑에 맞으며 빠져나와도 체력이 넉넉히 남는다."""
        c = self.c
        t = sim.time
        if c.hp / max(1.0, c.max_hp) < 0.6:
            return False
        if c.dist_to(e) > c.stats["attack_range"] + c.radius + e.radius + 0.3:
            return False
        burst = 0.0
        for slot in ("Q", "W", "E", "R"):
            ab = self.ab(slot)
            if ab.get("damage") and self.ready(sim, slot):
                burst += sim.ability_damage(c, ab, c.ranks[slot]) * 0.6          # 방어력·빗나감 감안
        dps = c.stats["ad"] * c.stats["attack_speed"] * 100.0 / (100.0 + max(0.0, e.armor))
        kill_time = max(0.0, (e.hp + e.shield_total(t) - burst) / max(1.0, dps))
        if kill_time > 1.0:
            return False
        shots = int(math.ceil((kill_time + 2.0) / TURRET_PERIOD))        # 처치 + 사거리 밖으로 걸어 나오는 시간
        per = turret_damage(t) * 100.0 / (100.0 + max(0.0, c.armor))
        taken = sum(per * (1 + 0.4 * min(i, 3)) for i in range(shots))
        return c.hp - taken > c.max_hp * 0.35

    def dive_ok(self, sim, e):
        """적 e 를 공격해도 되는가. 포탑 사거리 밖이거나, 내가 포탑 밖에 선 채로 닿거나,
        포탑 아래라도 그 자리에서 바로 끝낼 수 있을 때만 True (체력이 낮다고 포탑 안까지 쫓아 들어가지 않는다)."""
        c = self.c
        if self.under_turret(sim, e.x, e.z, 1.0 + c.radius) is None:
            return True
        reach = c.stats["attack_range"] + c.radius + e.radius
        if self.under_turret(sim, c.x, c.z, c.radius + 0.5) is None and c.dist_to(e) <= reach - 0.2:
            return True
        return self.quick_kill(sim, e)

    def dash_ok(self, sim, e, x, z):
        """(x, z) 로 뛰어드는 스킬을 써도 되는가: 도착 지점이 적 포탑 아래면 그 자리에서 끝낼 수 있을 때만."""
        return self.under_turret(sim, x, z, 1.0) is None or self.quick_kill(sim, e)

    def remember(self, sim, enemies):
        """보이는 적의 위치를 기억해 둔다 (부쉬에 숨으면 마지막으로 본 곳을 쫓아간다)."""
        t = sim.time
        for e in enemies:
            self.seen[e.id] = (e.x, e.z, t, e.hp / max(1.0, e.max_hp))

    def chase_hidden(self, sim, hp_ratio):
        """쫓던 적이 시야에서 사라졌으면(부쉬 등) 마지막으로 본 곳 너머까지 따라가 확인한다. 따라갔으면 True."""
        c = self.c
        t = sim.time
        e = sim.champions.get(self.chase) if self.chase else None
        if e is None or e.dead or sim.can_see(c.team, e):
            self.chase = None
            return False
        mem = self.seen.get(e.id)
        if mem is None or t - mem[2] > 3.5 or hp_ratio < 0.35:
            self.chase = None
            return False
        mx, mz, _, their = mem
        if their > 0.75 and hp_ratio < their:                  # 체력이 넉넉한 적을 불리하게 쫓지는 않는다
            self.chase = None
            return False
        # 마지막으로 본 곳에서 조금 더 들어간 지점 (부쉬 근처면 부쉬 한가운데 쪽)
        bush = self.bush_near(mx, mz, 1.6)
        if bush is not None:
            bx, bz = mapdata.BUSHES[bush][:2]
            tx, tz = mx + (bx - mx) * 0.6, mz + (bz - mz) * 0.6
        else:
            d = math.hypot(mx - c.x, mz - c.z) or 1.0
            tx, tz = mx + (mx - c.x) / d * 1.5, mz + (mz - c.z) / d * 1.5
        if self.under_turret(sim, tx, tz) is not None or c.dist_xy(tx, tz) < 0.8:     # 포탑 아래거나, 가 봤는데 없다
            self.chase = None
            return False
        sim.cmd_move(c, tx, tz)
        return True

    @staticmethod
    def bush_near(x, z, k=1.0):
        """(x, z) 가 부쉬 타원을 k 배로 키운 범위 안이면 그 부쉬 번호 (없으면 None)."""
        for i, (bx, bz, rx, rz) in enumerate(mapdata.BUSHES):
            if ((x - bx) / rx) ** 2 + ((z - bz) / rz) ** 2 <= k * k:
                return i
        return None

    def bush_spot(self, sim, x, z, max_dist):
        """(x, z) 에서 max_dist 안에 있고 적 포탑에 위험하지 않은 부쉬 한가운데 (없으면 None)."""
        best, bd = None, max_dist
        for bx, bz, _rx, _rz in mapdata.BUSHES:
            d = math.hypot(bx - x, bz - z)
            if d < bd and not self.turret_threat(sim, bx, bz):
                best, bd = (bx, bz), d
        return best

    def ab(self, slot):
        return self.c.data["abilities"][slot]

    def ready(self, sim, slot):
        c = self.c
        if c.ranks.get(slot, 0) <= 0 or sim.time < c.ready_at[slot] or c.silenced(sim.time):
            return False
        ab = self.ab(slot)
        return c.mana >= gamedata.rank_value(ab, "mana", c.ranks[slot], 0)

    def aim(self, sim, target, travel_speed=None):
        """대상 위치에 약간의 예측과 오차를 섞어 조준."""
        x, z = target.x, target.z
        if travel_speed and getattr(target, "move_target", None):
            mx, mz = target.move_target
            d = math.hypot(mx - x, mz - z)
            if d > 0.1:
                lead = min(d, self.c.dist_to(target) / travel_speed * 3.0)
                x += (mx - x) / d * lead * 0.7
                z += (mz - z) / d * lead * 0.7
        return x + self.rng.uniform(-0.4, 0.4), z + self.rng.uniform(-0.4, 0.4)

    @staticmethod
    def count_near(enemies, target, radius):
        return sum(1 for e in enemies if e.dist_to(target) <= radius)

    def safe_relic(self, sim, max_dist):
        best, bd = None, max_dist
        for r in sim.relics:
            if not r.active:
                continue
            d = self.c.dist_xy(r.x, r.z)
            if d < bd and not self.turret_threat(sim, r.x, r.z):
                best, bd = r, d
        return best

    # ------------------------------------------------------------------ 스킬 규칙
    def plan(self, sim, slot, target, enemies, allies, hp_ratio):
        """적 챔피언(target)을 상대로 slot 스킬을 쓸 때 조준 지점. 쓰지 않으면 None."""
        c = self.c
        ab = self.ab(slot)
        typ = ab["type"]
        dist = c.dist_to(target)
        their = target.hp / max(1.0, target.max_hp)
        tx, tz = target.x, target.z
        me = (c.x, c.z)
        clustered = self.count_near(enemies, target, 3.4) >= 2

        if typ == "volley":
            return (tx, tz) if dist <= ab["range"] * 0.95 else None
        if typ == "cocoon":                                  # 고치: 적 근처에 깔아 새끼 거미가 달려들게
            return (tx, tz) if 1.5 < dist <= ab["range"] else None
        if typ == "spit_pool":                               # 독 뱉기: 가까운 적의 발밑에 독 웅덩이
            return self.aim(sim, target, None) if dist <= ab["range"] else None
        if typ == "lunge":                                   # 일직선 돌진: 사거리 안에서 적을 겨눠 달려든다
            return self.aim(sim, target, None) if 2.0 < dist <= ab["range"] * 0.85 and self.dash_ok(sim, target, tx, tz) else None
        if typ == "serpent_slam":                            # 내려찍기: 가까이 선 적 한가운데로
            return self.aim(sim, target, None) if dist <= ab["range"] and (their < 0.7 or clustered or dist < 3.5) else None
        if typ == "dive":                                    # 잠행: 떨어져 있는 적에게 솟구친다
            if 5.0 <= dist <= ab["range"] + 1.0 and hp_ratio > 0.4 and self.dash_ok(sim, target, tx, tz):
                return (tx, tz)
            return None
        if typ == "tornado":                                 # 회오리: 사거리 안의 적을 겨눠 굴린다
            return self.aim(sim, target, None) if dist <= ab["range"] * 0.9 else None
        if typ == "wing_sweep":                              # 날개 후려치기: 몸 둘레에 적이 붙어 있을 때
            return me if dist <= ab["radius"] * 0.85 else None
        if typ == "sky_dive":                                # 급강하: 모여 있거나 체력이 낮은 적 위로 (날아오르는 동안 움직임을 예측해 앞에)
            if dist <= ab["range"] and (clustered or their < 0.55) and self.dash_ok(sim, target, tx, tz):
                return self.aim(sim, target, 7.0)
            return None
        if typ == "leap_slam":                               # 도약: 떨어져 있는 적에게 덮친다
            if (2.2 < dist <= ab["range"] + 0.5 and hp_ratio > 0.35 and self.dash_ok(sim, target, tx, tz)):
                return (tx, tz)
            return None
        if typ == "scythe_sweep":                            # 영혼 베기: 날끝(바깥쪽)에 걸리는 거리에서 휘두른다
            return (tx, tz) if ab.get("inner_radius", 0) * 0.7 <= dist <= ab["range"] * 0.95 else None
        if typ == "scythe_throw":                            # 낫 던지기: 사거리 안의 적에게 (돌아오는 길도 벤다)
            return self.aim(sim, target, ab.get("speed")) if dist <= ab["range"] * 0.9 else None
        if typ == "execute":                                 # 사형 선고: 체력이 낮은 적 챔피언에게
            return (tx, tz) if dist <= ab["range"] and their < 0.45 else None
        if typ == "zone":                                    # 독 거미줄
            if dist <= ab["range"] and (clustered or their < 0.5):
                return (tx, tz)
            return None
        return None

    def try_skills(self, sim, target, enemies, allies, hp_ratio):
        c = self.c
        for slot in c.data.get("bot_priority", ["R", "E", "W", "Q"]):
            if not self.ready(sim, slot):
                continue
            pt = self.plan(sim, slot, target, enemies, allies, hp_ratio)
            if pt is not None and sim.cast(c, slot, pt[0], pt[1]):
                return True
        return False

    # ------------------------------------------------------------------
    def decide(self, sim):
        c = self.c
        t = sim.time
        direction = mapdata.team_dir(c.team)
        hp_ratio = c.hp / max(1.0, c.max_hp)
        fx, fz = mapdata.fountain_pos(c.team)
        rng_atk = c.stats["attack_range"]

        # 봇도 시야 안의 적만 안다
        enemies = [e for e in sim.champions.values()
                   if e.team != c.team and not e.dead and c.dist_to(e) <= 13 and sim.can_see(c.team, e)]
        allies = [a for a in sim.champions.values() if a.team == c.team and not a.dead and c.dist_to(a) <= 10]
        self.remember(sim, enemies)
        # 쫓던 챔피언이 포탑 아래로 들어갔으면 하던 공격을 그만둔다 (공격 명령이 남아 있으면 계속 따라 들어간다)
        chasing = sim.champions.get(c.attack_target) if c.attack_target else None
        if chasing is not None and not self.dive_ok(sim, chasing):
            c.clear_orders()

        # ---- 귀환 중: 안전하면 그대로 두고, 위험해지면 귀환을 멈추고 아래 판단(후퇴 등)으로
        if c.recall_at is not None:
            if not self.in_danger(sim):
                return
            c.recall_at = None
        # 우물에서는 거의 다 찰 때까지 회복
        if sim.in_fountain(c) and (hp_ratio < 0.9 or c.mana < c.max_mana * 0.6):
            return

        # ---- 위험: 후퇴
        if hp_ratio < 0.28:
            self.chase = None
            # 안전할 때만 귀환, 아니면 먼저 우물 쪽으로 물러난다
            if not sim.in_fountain(c) and not self.in_danger(sim):
                sim.recall(c)
                return
            relic = self.safe_relic(sim, 16)
            if relic and not enemies:
                sim.cmd_move(c, relic.x, relic.z)
                return
            close = [e for e in enemies if c.dist_to(e) < 5]
            if close and hp_ratio < 0.15 and t >= c.ready_at["D"] and c.spells[0] == "flash":
                sim.flash(c, fx, fz)
                return
            if close:
                self.poke(sim, close[0], c.dist_to(close[0]))
                # 쫓기는 중이면 뒤쪽(우물 쪽)의 가까운 부쉬를 지나 시야를 끊는다
                if mapdata.bush_at(c.x, c.z) < 0:
                    for bx, bz, _rx, _rz in mapdata.BUSHES:
                        if (bx - c.x) * direction < 0.5 and math.hypot(bx - c.x, bz - c.z) < 6.0:
                            sim.cmd_move(c, bx, bz)
                            return
            sim.cmd_move(c, fx + direction * 4, fz)
            return

        if hp_ratio < 0.65:
            relic = self.safe_relic(sim, 9)
            if relic:
                sim.cmd_move(c, relic.x, relic.z)
                return

        # ---- 교전 (포탑 아래의 적은 처치하고 빠져나올 수 있을 때만)
        target = None
        best = 1e9
        for e in enemies:
            if not self.dive_ok(sim, e):
                continue
            score = e.hp / max(1.0, e.max_hp) * 10 + c.dist_to(e)
            if score < best:
                best, target = score, e
        # ---- 포탑이 나를 노리면 (그 자리에서 바로 끝낼 적이 아니면) 사거리 밖으로 빠진다
        tur = self.turret_on_me(sim)
        if tur is not None and not (target is not None and self.quick_kill(sim, target)):
            c.clear_orders()
            away = math.hypot(c.x - tur.x, c.z - tur.z) or 1.0
            out = mapdata.TURRET_RANGE + c.radius + 1.5
            sim.cmd_move(c, tur.x + (c.x - tur.x) / away * out, tur.z + (c.z - tur.z) / away * out)
            return
        if target is not None:
            their = target.hp / max(1.0, target.max_hp)
            dist = c.dist_to(target)
            outnumbered = len(enemies) > len(allies) + 1
            engage = (their < 0.35 or (hp_ratio >= their * 0.85 and not outnumbered) or dist <= rng_atk * 0.7)
            self.poke(sim, target, dist)
            if engage:
                self.chase = target.id
                if self.try_skills(sim, target, enemies, allies, hp_ratio):
                    return
                marked = sim.champions.get(c.mark[0]) if c.mark else None
                if c.mark and their < 0.45 and hp_ratio > 0.5 and (marked is None or self.dash_ok(sim, marked, marked.x, marked.z)):
                    sim.mark(c, target.x, target.z)
                    return
                if (c.spells[1] == "mark" and t >= c.ready_at["F"] and not c.mark and dist <= MARK_RANGE * 0.8
                        and their < 0.6 and hp_ratio > 0.55 and self.rng.random() < 0.3):
                    sim.mark(c, *self.aim(sim, target, 25))
                if c.attack_target != target.id:
                    sim.cmd_attack(c, target.id)
                return
            if dist < rng_atk * 0.9 and rng_atk > 3.0:
                # 불리하면 거리를 벌린다 (원거리 챔피언만)
                sim.cmd_move(c, c.x - direction * 3, c.z)
                return
        elif self.chase_hidden(sim, hp_ratio):
            return

        # ---- 파밍 / 푸시
        allied_minions = [m for m in sim.minions.values() if m.team == c.team]
        if allied_minions:
            front_x = max(m.x * direction for m in allied_minions) * direction
            # 포탑 공격: 미니언이 포탑 어그로를 받는 중이면
            for s in sim.structures.values():
                if s.team != c.team and sim.vulnerable(s) and c.dist_to(s) <= rng_atk + s.radius + 4:
                    if s.skind != "turret" or not self.turret_threat(sim, c.x, c.z):
                        if not enemies:
                            if c.attack_target != s.id:
                                sim.cmd_attack(c, s.id)
                            return
            # 막타 / 미니언 처치
            cand = None
            cand_hp = 1e9
            for m in sim.minions.values():
                if m.team == c.team or c.dist_to(m) > rng_atk + 3.5:
                    continue
                if self.turret_threat(sim, m.x, m.z):
                    continue
                if m.hp < cand_hp:
                    cand, cand_hp = m, m.hp
            if cand is not None:
                if c.attack_target != cand.id:
                    sim.cmd_attack(c, cand.id)
                return
            hold_x = front_x - direction * (rng_atk * 0.6 + 1.0)
        else:
            # 아군 미니언이 없으면 아군 최전방 포탑 근처에서 대기
            own = [s for s in sim.structures.values() if s.team == c.team and s.skind == "turret" and s.alive]
            if own:
                front = max(own, key=lambda s: s.x * direction)
                hold_x = front.x + direction * 3.0
            else:
                hold_x = fx + direction * 10

        hold_z = self.lane_offset
        if self.turret_threat(sim, hold_x, hold_z):
            for s in self.enemy_turrets(sim):
                if abs(s.x - hold_x) < mapdata.TURRET_RANGE + 1.5:
                    hold_x = s.x - direction * (mapdata.TURRET_RANGE + 1.5)
        # 할 일이 없으면 기다릴 자리 근처의 부쉬에 숨는다 (적이 지나가면 덮친다)
        if self.bush_lover and hp_ratio > 0.5:
            spot = self.bush_spot(sim, hold_x, hold_z, 7.0)
            if spot is not None and (spot[0] - hold_x) * direction < 3.0:
                hold_x, hold_z = spot
        if c.dist_xy(hold_x, hold_z) > 1.2:
            if c.move_target is None or math.hypot(c.move_target[0] - hold_x, c.move_target[1] - hold_z) > 1.0:
                sim.cmd_move(c, hold_x, hold_z)

    def poke(self, sim, target, dist):
        """멀리서 견제할 수 있는 직선·부채꼴 스킬 (궁극기 제외)."""
        c = self.c
        if c.mana < c.max_mana * 0.3:
            return
        for slot in ("Q", "W", "E"):
            ab = self.ab(slot)
            if ab["type"] not in POKE_TYPES or not self.ready(sim, slot):
                continue
            rng = ab.get("range", 8)
            if dist <= rng * 0.9:
                sim.cast(c, slot, *self.aim(sim, target, ab.get("speed")))
                return
