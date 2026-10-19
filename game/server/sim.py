"""칼바람 모드 게임 시뮬레이션 (서버 권한).

- 단일 라인, 양 팀 외곽/내부 포탑 → 억제기 → 쌍둥이 포탑 → 넥서스
- 레벨 3, 1400 골드로 시작 / B 귀환(8초) / 상점은 사망 중이거나 우물에서만
- 우물에서 체력·마나 회복, 라인에는 체력 회복 유물(구슬)도 생성
- 시야: 팀마다 챔피언·미니언·구조물 주변만 보이고, 부쉬 안은 같은 부쉬 안에서만 보인다
- 포탑 방패: 포탑 체력이 한 칸(1/5) 깎일 때마다 근처 적 챔피언에게 골드
- 30초마다 미니언 웨이브, 억제기 파괴 시 슈퍼 미니언
- 소환사 주문: 선택 화면에서 고른 두 개를 D / F 칸에 넣는다 (점멸·표식·회복·유체화·방어막·정화·탈진·점화)
- 챔피언 스킬은 abilities.py 의 type 별 핸들러가 처리한다 (이 파일은 피해·상태이상·장판 같은 공통 규칙)
"""
import math
import types
import random

from ..shared import data as gamedata
from ..shared import mapdata
from ..shared.constants import (
    ASSIST_GOLD_RATIO, ASSIST_WINDOW, BARRIER_BASE, BOUNTY_ASSIST_POINT, DEATH_STREAK_GOLD, BARRIER_PER_LEVEL, BARRIER_TIME, BLUE, CLEANSE_IMMUNE,
    EXHAUST_DMG_REDUCE, EXHAUST_RANGE, EXHAUST_SLOW, EXHAUST_TIME, FIRST_BLOOD_BONUS, FIRST_WAVE_TIME,
    FLASH_COOLDOWN, FLASH_RANGE, GHOST_SPEED_PCT, GHOST_TIME, HEAL_ALLY_RATIO, HEAL_BASE, HEAL_PER_LEVEL, HEAL_RANGE,
    HEAL_SPEED_PCT, HEAL_SPEED_TIME, IGNITE_BASE, IGNITE_HEAL_CUT, IGNITE_PER_LEVEL, IGNITE_RANGE, IGNITE_TICK,
    IGNITE_TIME, FOUNTAIN_HEAL_PCT, FOUNTAIN_LASER_DPS, FOUNTAIN_LASER_RADIUS, FOUNTAIN_RADIUS, INHIBITOR_RESPAWN,
    INVENTORY_SLOTS, MARK_COOLDOWN, MINION_GOLD_RANGE, MARK_DASH_SPEED, MARK_RANGE, MARK_RECAST_TIME,
    MARK_SPEED, MAX_LEVEL, PASSIVE_GOLD_PER_SEC, PASSIVE_XP_PER_SEC, PLATE_SHARE_RANGE, RECALL_TIME, RECALL_TIME_HOME, RED,
    RELIC_FIRST_SPAWN, RELIC_HEAL_PCT, RELIC_RADIUS, RELIC_RESPAWN, SELL_RATIO, SIGHT, WAVE_INTERVAL, XP_SHARE_RANGE,
    death_timer, kill_bounty, xp_to_next,
)
from ..shared.spells import SPELLS
from . import abilities
from .bot import BotBrain
from .entities import (
    MINION_CODES, TURRET_MINION_DMG, Anchor, Champion, Minion, Projectile, Relic, Structure,
)

MINION_AGGRO = 7.0
MULTIKILL_WINDOW = 10.0          # 이 시간 안에 이어서 처치하면 더블킬·트리플킬 …
INHIBITOR_SOON = 15.0           # 억제기 재생성 이만큼 전에 '곧 재생성' 안내
TURRET_PERIOD = 0.85
TURRET_CHAMP_DMG = 128.0        # 포탑 → 챔피언 기본 피해 (+분당 2.5, 연속 공격 시 증가)
SLOTS = ("Q", "W", "E", "R")


def point_segment_dist(px, pz, ax, az, bx, bz):
    vx, vz = bx - ax, bz - az
    wx, wz = px - ax, pz - az
    vv = vx * vx + vz * vz
    t = 0.0 if vv <= 1e-9 else max(0.0, min(1.0, (wx * vx + wz * vz) / vv))
    cx, cz = ax + vx * t, az + vz * t
    return math.hypot(px - cx, pz - cz)


def other(team):
    return RED if team == BLUE else BLUE


class Simulation:
    def __init__(self, members):
        """members: [{"key", "name", "team", "bot", "champ", "spells"(생략하면 점멸·표식)}]"""
        self.time = 0.0
        self._next_id = 1
        self.champions = {}         # id -> Champion
        self.by_key = {}            # member_key -> Champion
        self.minions = {}
        self.structures = {}
        # 우물 제단 기둥: 포탑처럼 길을 막는 고정 장애물 (x, z, radius 만 있으면 된다)
        self.pillars = [types.SimpleNamespace(x=px, z=pz, radius=mapdata.PILLAR_RADIUS)
                        for team in (0, 1) for px, pz in mapdata.fountain_pillars(team)]
        self.projectiles = {}
        self.effects = {}
        self.zones = {}             # 성역·정원·덫·감옥 같은 장판 (Zone)
        self.anchors = {}           # 거미 고치 (Cocoon)
        self.scheduled = []         # [(실행 시각, 함수)] 시간차로 일어나는 일 (칼 던지기 등)
        self.relics = []
        self.events = []
        self.help_calls = []        # (만료, 가해 챔피언 id, 피해 팀, x, z)
        self.brains = {}
        self.wave_index = 0
        self.next_wave_at = FIRST_WAVE_TIME
        self.first_blood = False
        self.minion_warned = False
        self.winner = None
        self.score = {BLUE: 0, RED: 0}
        self.rng = random.Random()
        self.visible = {BLUE: set(), RED: set()}    # 팀별로 보이는 적 유닛 id
        self._observers = {BLUE: [], RED: []}
        self.gone_minions = []      # 지난 스냅샷 이후 죽은 미니언 (클라이언트 사라짐 효과용)

        for info in mapdata.structure_layout():
            s = Structure(self.new_id(), info)
            self.structures[s.id] = s

        for i, (x, z) in enumerate(mapdata.RELIC_POSITIONS):
            r = Relic(self.new_id(), x, z)
            r.respawn_at = RELIC_FIRST_SPAWN
            self.relics.append(r)

        for team in (BLUE, RED):
            ms = [m for m in members if m["team"] == team]
            pts = mapdata.spawn_points(team, len(ms))
            for m, (x, z) in zip(ms, pts):
                c = Champion(self.new_id(), team, x, z, m["key"], m["name"], m["champ"], m["bot"], m.get("spells"))
                c.facing = 0.0 if team == BLUE else math.pi
                self.champions[c.id] = c
                self.by_key[m["key"]] = c
                if m["bot"]:
                    self.brains[c.id] = BotBrain(c)

    # ------------------------------------------------------------------ 유틸
    def new_id(self):
        self._next_id += 1
        return self._next_id

    def event(self, **kw):
        self.events.append(kw)

    def unit(self, uid):
        return (self.champions.get(uid) or self.minions.get(uid) or self.structures.get(uid)
                or self.anchors.get(uid))

    def schedule(self, delay, fn):
        """delay 초 뒤에 fn(sim) 을 실행한다."""
        self.scheduled.append((self.time + delay, fn))

    def structure_by_key(self, team, key):
        for s in self.structures.values():
            if s.team == team and s.key == key:
                return s
        return None

    def vulnerable(self, s):
        if not s.alive:
            return False
        for key in s.requires:
            req = self.structure_by_key(s.team, key)
            if req is not None and req.alive:
                return False
        return True

    def targetable(self, u, by_team):
        """by_team 팀이 u 를 공격 대상으로 삼을 수 있는가."""
        if u is None or u.team == by_team or not u.alive:
            return False
        if u.untargetable(self.time):
            return False
        if isinstance(u, Champion):
            return not u.dead
        if isinstance(u, Structure):
            return self.vulnerable(u)
        return True

    def enemies_in_radius(self, team, x, z, radius, champions=True, minions=True):
        t = self.time
        out = []
        if champions:
            for c in self.champions.values():
                if (c.team != team and not c.dead and not c.untargetable(t)
                        and math.hypot(c.x - x, c.z - z) <= radius + c.radius):
                    out.append(c)
        if minions:
            for m in self.minions.values():
                if m.team != team and math.hypot(m.x - x, m.z - z) <= radius + m.radius:
                    out.append(m)
            for a in self.anchors.values():                 # 적 고치도 스킬 범위에 맞는다
                if getattr(a, "cocoon", False) and a.team != team and a.alive and math.hypot(a.x - x, a.z - z) <= radius + a.radius:
                    out.append(a)
        return out

    def allies_in_radius(self, team, x, z, radius):
        """같은 팀 챔피언 (자신 포함)."""
        return [c for c in self.champions.values()
                if c.team == team and not c.dead and math.hypot(c.x - x, c.z - z) <= radius + c.radius]

    # ------------------------------------------------------------------ 시야
    def observers(self, team):
        """team 의 시야 제공자 목록: (x, z, 시야 반경, 서 있는 부쉬 번호)."""
        fx, fz = mapdata.fountain_pos(team)
        out = [(fx, fz, SIGHT["fountain"], -1)]
        for c in self.champions.values():
            if c.team == team and not c.dead:
                out.append((c.x, c.z, SIGHT["champion"], mapdata.bush_at(c.x, c.z)))
        for m in self.minions.values():
            if m.team == team:
                out.append((m.x, m.z, SIGHT["minion"], mapdata.bush_at(m.x, m.z)))
        for st in self.structures.values():
            if st.team == team and st.alive:
                out.append((st.x, st.z, SIGHT[st.skind], -1))
        for a in self.anchors.values():                     # 거미 고치: 놓인 곳 주변만 좁게 보인다 (부쉬 안이면 그 부쉬도)
            if a.team == team and getattr(a, "cocoon", False):
                out.append((a.x, a.z, SIGHT["cocoon"], mapdata.bush_at(a.x, a.z)))
        return out

    @staticmethod
    def seen_by(obs, x, z):
        """(x, z) 가 시야 제공자들 중 하나에게 보이는가. 부쉬 안은 같은 부쉬에 있어야 보인다."""
        bush = mapdata.bush_at(x, z)
        for ox, oz, r, ob in obs:
            if (x - ox) ** 2 + (z - oz) ** 2 <= r * r and (bush < 0 or bush == ob):
                return True
        return False

    def update_vision(self):
        for team in (BLUE, RED):
            obs = self.observers(team)
            vis = set()
            for c in self.champions.values():
                if c.team != team and not c.dead and self.seen_by(obs, c.x, c.z):
                    vis.add(c.id)
            for m in self.minions.values():
                if m.team != team and self.seen_by(obs, m.x, m.z):
                    vis.add(m.id)
            for a in self.anchors.values():                 # 적 고치는 부쉬 밖이면 늘 보이고, 부쉬 안이면 그 부쉬를 볼 때만 보인다
                if (a.team != team and getattr(a, "cocoon", False)
                        and (mapdata.bush_at(a.x, a.z) < 0 or self.seen_by(obs, a.x, a.z))):
                    vis.add(a.id)
            self.visible[team] = vis
            self._observers[team] = obs

    def can_see(self, team, u):
        """team 이 유닛 u 를 볼 수 있는가 (아군과 구조물은 항상 보임)."""
        if isinstance(u, Anchor) and getattr(u, "cocoon", False):
            return u.team == team or u.id in self.visible[team]
        return u.team == team or isinstance(u, (Structure, Anchor)) or u.id in self.visible[team]

    def in_fountain(self, c):
        fx, fz = mapdata.fountain_pos(c.team)
        return math.hypot(c.x - fx, c.z - fz) <= FOUNTAIN_RADIUS

    def can_shop(self, c):
        return c.dead or self.in_fountain(c)

    # ------------------------------------------------------------------ 이동
    def obstacles(self):
        # 부서진 구조물(잔해)도 살아 있을 때와 같은 크기로 길을 막는다
        return list(self.structures.values()) + self.pillars

    def move_unit(self, u, tx, tz, speed, dt, stop_dist=0.0):
        """u 를 (tx, tz) 쪽으로 이동. 도착하면 True."""
        dx, dz = tx - u.x, tz - u.z
        d = math.hypot(dx, dz)
        if d <= stop_dist + 1e-3:
            return True
        step = min(speed * dt, d - stop_dist)
        ux, uz = dx / d, dz / d
        ghost = u.ghost(self.time)
        # 앞에 구조물이 있으면 옆으로 비켜간다 (망령 상태는 그냥 통과)
        for s in ([] if ghost else self.obstacles()):
            ox, oz = s.x - u.x, s.z - u.z
            along = ox * ux + oz * uz
            if 0.0 < along < s.radius + 3.0 and along < d:
                perp = -ox * uz + oz * ux
                clear = s.radius + u.radius + 0.25
                if abs(perp) < clear:
                    side = -1.0 if perp > 0 else 1.0
                    if abs(perp) < 1e-3:
                        side = 1.0 if (u.z >= 0) else -1.0
                    k = (clear - abs(perp)) / clear * 2.0
                    nx_, nz_ = -uz * side, ux * side
                    ux, uz = ux + nx_ * k, uz + nz_ * k
                    n = math.hypot(ux, uz) or 1.0
                    ux, uz = ux / n, uz / n
        nx, nz = u.x + ux * step, u.z + uz * step
        u.x, u.z = self.resolve_position(nx, nz, u.radius, ghost)
        u.facing = math.atan2(uz, ux)
        return False

    def resolve_position(self, x, z, radius, ghost=False):
        x, z = mapdata.clamp_to_map(x, z, radius)
        for s in ([] if ghost else self.obstacles()):
            dx, dz = x - s.x, z - s.z
            d = math.hypot(dx, dz)
            min_d = s.radius + radius
            if d < min_d:
                if d < 1e-4:
                    dx, dz, d = 0.0, 1.0, 1.0
                x, z = s.x + dx / d * min_d, s.z + dz / d * min_d
        return mapdata.clamp_to_map(x, z, radius)

    def face(self, u, x, z):
        if abs(x - u.x) + abs(z - u.z) > 1e-4:
            u.facing = math.atan2(z - u.z, x - u.x)

    # ------------------------------------------------------------------ 피해
    def deal_damage(self, src, target, amount, dtype, ability=False, basic=False):
        if target is None or not target.alive or amount <= 0:
            return 0.0
        if isinstance(target, Champion) and target.dead:
            return 0.0
        if isinstance(target, Anchor):
            if getattr(target, "cocoon", False):
                # 고치: 평타든 스킬이든 받은 피해만큼 체력이 깎인다 (방어력 없음)
                target.hp -= amount
                if target.hp <= 0:
                    target.hp = 0
                    self.on_death(target, src)
                return amount
            # 줄 말뚝은 기본 공격으로만 부서지고, 한 번에 1씩 깎인다 (3번이면 파괴)
            if basic and not ability:
                target.hp -= 1.0
                if target.hp <= 0:
                    target.hp = 0
                    self.on_death(target, src)
            return 0.0
        if isinstance(target, Structure):
            if ability or not self.vulnerable(target):
                return 0.0
        if target.untargetable(self.time):
            return 0.0
        if isinstance(src, Champion) and self.time < src.exhaust_until:
            amount *= 1.0 - EXHAUST_DMG_REDUCE              # 탈진: 주는 피해 감소
        if dtype == "physical":
            res = target.armor
        elif dtype == "magic":
            res = target.mr
        else:
            res = None
        if res is None:
            dmg = amount
        elif res >= 0:
            dmg = amount * 100.0 / (100.0 + res)
        else:
            dmg = amount * (2.0 - 100.0 / (100.0 - res))
        taken = dmg                                   # 방어력 적용 후, 보호막 이전

        self.apply_hp_loss(target, dmg)
        if isinstance(target, Champion) and dmg > 0:
            target.recall_at = None         # 피해를 받으면 귀환 취소
            target.last_hit_at = self.time
        if isinstance(target, Structure):
            while target.plates_left > 0 and target.hp <= target.max_hp * (target.plates_left - 1) / target.plates:
                self.break_plate(target)

        src_id = src.id if src is not None else 0
        if basic:
            self.event(e="dmg", s=src_id, d=target.id, v=int(round(taken)), ty=dtype[0], b=1)    # b: 기본 공격 (효과음용)
        else:
            self.event(e="dmg", s=src_id, d=target.id, v=int(round(taken)), ty=dtype[0])

        if isinstance(src, Champion):
            if isinstance(target, Champion):
                target.damage_log[src.id] = self.time
                self.help_calls.append((self.time + 2.0, src.id, target.team, target.x, target.z))
            # 생명력 흡수: 챔피언·미니언을 때릴 때만 (포탑·억제기·넥서스·고치·말뚝은 제외)
            if (basic and src.stats.get("life_steal", 0) > 0 and not src.dead
                    and isinstance(target, (Champion, Minion))):
                self.heal(src, taken * src.stats["life_steal"])

        if target.hp <= 0:
            target.hp = 0
            self.on_death(target, src)
        return taken

    def apply_hp_loss(self, target, dmg):
        """보호막을 먼저 깎고 남은 만큼 체력을 줄인다. 죽음 처리는 부르는 쪽이 한다."""
        t = self.time
        rem = dmg
        if target.shields:
            for sh in list(target.shields):
                if sh["until"] <= t:
                    target.shields.remove(sh)
                    continue
                take = min(rem, sh["amount"])
                sh["amount"] -= take
                rem -= take
                if sh["amount"] <= 0.01:
                    target.shields.remove(sh)
                if rem <= 0:
                    break
        if rem > 0:
            target.hp -= rem
        return rem

    def add_shield(self, target, amount, duration, src=None):
        """보호막을 건다."""
        if amount <= 0 or target is None or not target.alive:
            return False
        target.shields.append({"amount": amount, "until": self.time + duration})
        return True

    def break_plate(self, s):
        """포탑 방패 한 칸 파괴: 근처 적 챔피언들이 골드를 나눠 갖는다."""
        s.plates_left -= 1
        near = [c for c in self.champions.values()
                if c.team != s.team and not c.dead and c.dist_to(s) <= PLATE_SHARE_RANGE]
        if near and s.plate_gold:
            share = s.plate_gold / len(near)
            for c in near:
                c.gold += share
                self.event(e="gold", d=c.id, v=int(round(share)), x=round(s.x, 2), z=round(s.z, 2))
        self.event(e="fx", fx="plate", x=round(s.x, 2), z=round(s.z, 2))

    def heal(self, c, amount, src=None, quiet=False):
        """체력 회복."""
        if amount <= 0 or not c.alive or getattr(c, "dead", False):
            return 0.0
        if getattr(c, "ignite", None):
            amount *= 1.0 - IGNITE_HEAL_CUT                   # 점화: 받는 회복량 감소
        before = c.hp
        c.hp = min(c.max_hp, c.hp + amount)
        gained = c.hp - before
        if src is not None and not quiet and gained >= 1.0:
            self.event(e="heal", d=c.id, v=int(round(gained)))
        return gained

    # ------------------------------------------------------------------ 처치
    def on_death(self, target, killer):
        if isinstance(target, Champion):
            self.champion_died(target, killer)
        elif isinstance(target, Minion):
            target.alive = False
            self.minions.pop(target.id, None)
            self.gone_minions.append(target.id)
            near = [c for c in self.champions.values()
                    if c.team != target.team and not c.dead and c.dist_to(target) <= XP_SHARE_RANGE]
            if target.mtype != "spiderling":
                if isinstance(killer, Champion) and killer.team != target.team:
                    killer.cs += 1
                    self.give_gold(killer, target.gold, target.x, target.z)
                else:
                    # 미니언·포탑이 처치하면 근처에 있던 적 챔피언들이 골드를 나눠 받는다
                    share = [c for c in near if c.dist_to(target) <= MINION_GOLD_RANGE]
                    for c in share:
                        self.give_gold(c, target.gold / len(share), target.x, target.z)
            for c in near:
                self.give_xp(c, target.xp / len(near))
        elif isinstance(target, Structure):
            self.structure_destroyed(target, killer)
        elif isinstance(target, Anchor):
            abilities.anchor_destroyed(self, target)

    def champion_died(self, victim, killer):
        victim.dead = True
        victim.recall_at = None
        victim.deaths += 1
        victim.respawn_at = self.time + death_timer(victim.level)
        victim.clear_orders()
        victim.dash = None
        victim.buffs = []
        victim.slows = []
        victim.stun_until = victim.root_until = 0.0
        victim.cleanse(self.time)
        victim.shields = []
        victim.silence_until = victim.airborne_until = 0.0
        victim.ghost_until = victim.untarget_until = victim.cc_immune_until = 0.0
        victim.exhaust_until = 0.0
        victim.lock_until = 0.0
        victim.ignite = None

        recent = {cid: t for cid, t in victim.damage_log.items() if self.time - t <= ASSIST_WINDOW}
        victim.damage_log = {}
        killer_champ = killer if isinstance(killer, Champion) else None
        credited = killer_champ is not None                      # 챔피언 손에 죽었는가 (아니면 포탑·미니언에게 처형)
        shutdown = victim.kill_streak >= 3                       # 연속 처치 중이던 상대를 끊었는가
        # 처치 골드: 연달아 죽던 챔피언이면 줄고, 처치·어시스트를 쌓은 챔피언이면 현상금(제압 골드)이 붙는다
        base_gold = DEATH_STREAK_GOLD[min(victim.death_streak, len(DEATH_STREAK_GOLD) - 1)]
        bounty = kill_bounty(victim.bounty_pts)
        victim.kill_streak = 0
        victim.multi_n = 0
        victim.bounty_pts = 0.0
        victim.death_streak += 1
        if killer_champ is None and recent:
            # 포탑·미니언에게 처치되면 마지막으로 피해를 준 챔피언이 처치 관여
            killer_champ = self.champions.get(max(recent, key=recent.get))
        if killer_champ is not None and killer_champ.team == victim.team:
            killer_champ = None

        assists = [self.champions[cid] for cid in recent
                   if killer_champ is None or cid != killer_champ.id]
        assists = [a for a in assists if a.team != victim.team]

        multi = streak = 0
        fb = False
        if killer_champ is not None:
            killer_champ.kills += 1
            killer_champ.kill_streak += 1
            streak = killer_champ.kill_streak
            killer_champ.multi_n = killer_champ.multi_n + 1 if self.time - killer_champ.multi_t <= MULTIKILL_WINDOW else 1
            killer_champ.multi_t = self.time
            multi = killer_champ.multi_n
            killer_champ.bounty_pts += 1.0
            killer_champ.death_streak = 0
            gold = base_gold + bounty
            if not self.first_blood:
                self.first_blood = True
                fb = True
                gold += FIRST_BLOOD_BONUS
                self.event(e="announce", text=f"{killer_champ.name} 님이 선취점을 올렸습니다!")
            self.give_gold(killer_champ, gold, victim.x, victim.z)
            self.score[killer_champ.team] += 1
        else:
            self.score[other(victim.team)] += 1
        for a in assists:
            a.assists += 1
            a.bounty_pts += BOUNTY_ASSIST_POINT
            a.death_streak = 0
            self.give_gold(a, base_gold * ASSIST_GOLD_RATIO / len(assists), victim.x, victim.z)

        xp_total = 100 + 35 * victim.level
        gainers = ([killer_champ] if killer_champ else []) + assists
        for g in gainers:
            self.give_xp(g, xp_total / len(gainers))

        self.event(e="kill", k=killer_champ.id if killer_champ else (killer.id if killer else 0),
                   kn=killer_champ.name if killer_champ else ("포탑" if isinstance(killer, Structure) else "미니언"),
                   kt=other(victim.team), v=victim.id, vn=victim.name, vt=victim.team,
                   mk=multi, ks=streak, sd=shutdown, fb=fb, ke=credited,          # 아나운서가 고르는 데 쓰는 값
                   bt=bounty if killer_champ is not None else 0)                   # 제압 골드

    def structure_destroyed(self, s, killer):
        s.alive = False
        s.hp = 0
        names = {"turret": "포탑이", "inhibitor": "억제기가", "nexus": "넥서스가"}
        enemy = other(s.team)
        if s.skind == "turret":
            for c in self.champions.values():
                if c.team == enemy:
                    c.gold += 150
        elif s.skind == "inhibitor":
            s.respawn_at = self.time + INHIBITOR_RESPAWN
            for c in self.champions.values():
                if c.team == enemy:
                    c.gold += 50
        self.event(e="announce", text=f"{'블루' if s.team == BLUE else '레드'}팀 {names[s.skind]} 파괴되었습니다!")
        if s.skind in ("turret", "inhibitor"):
            self.event(e="vo", key="turret_down" if s.skind == "turret" else "inhib_down", tm=s.team)
        s.soon_sent = False
        if s.skind == "nexus":
            self.winner = enemy
            self.event(e="victory", team=enemy)

    def give_gold(self, c, amount, x, z):
        """골드를 주고 받는 사람에게 +골드 글자를 띄운다."""
        if amount <= 0:
            return
        c.gold += amount
        self.event(e="gold", d=c.id, v=int(round(amount)), x=round(x, 2), z=round(z, 2))

    def give_xp(self, c, amount):
        if c.level >= MAX_LEVEL:
            return
        c.xp += amount
        while c.level < MAX_LEVEL and c.xp >= xp_to_next(c.level):
            c.xp -= xp_to_next(c.level)
            c.level += 1
            c.skill_points += 1
            c.recompute_stats(self.time)
            self.event(e="levelup", d=c.id, lv=c.level)
        if c.level >= MAX_LEVEL:
            c.xp = 0

    # ------------------------------------------------------------------ 테스트용 치트 (F6 체력 · F7 마나 · F8 쿨타임 · F9 레벨)
    def cheat_levelup(self, c):
        """F9: 레벨을 1 올린다 (스킬 포인트도 1). 최대 레벨이면 아무 일도 없다."""
        if c.dead or c.level >= MAX_LEVEL:
            return
        self.give_xp(c, xp_to_next(c.level) - c.xp)

    # ------------------------------------------------------------------ 명령
    def handle_command(self, key, msg):
        c = self.by_key.get(key)
        if c is None or self.winner is not None:
            return
        cmd = msg.get("c")
        try:
            if cmd == "level":
                self.level_ability(c, msg["slot"])
            elif cmd == "cheat_lv":
                self.cheat_levelup(c)
            elif cmd == "cheat_hp" and not c.dead:
                c.hp = c.max_hp
            elif cmd == "cheat_mana" and not c.dead:
                c.mana = c.max_mana
            elif cmd == "cheat_cd":
                c.ready_at = {k: 0.0 for k in c.ready_at}
            elif cmd == "buy":
                self.buy(c, msg["item"])
            elif cmd == "sell":
                self.sell(c, int(msg["slot"]))
            elif cmd == "undo":
                self.undo(c)
            elif cmd == "swap":
                self.swap_items(c, int(msg["a"]), int(msg["b"]))
            elif cmd == "ping":
                self.ping(c, float(msg["x"]), float(msg["z"]), str(msg.get("k", "alert")))
            elif c.dead:
                return
            elif cmd == "recall":
                self.recall(c)
            elif cmd == "move":
                c.recall_at = None
                self.cmd_move(c, float(msg["x"]), float(msg["z"]))
            elif cmd == "amove":
                c.recall_at = None
                self.cmd_move(c, float(msg["x"]), float(msg["z"]))
                c.attack_move = True
            elif cmd == "attack":
                c.recall_at = None
                self.cmd_attack(c, int(msg["id"]))
            elif cmd == "stop":
                c.recall_at = None
                if not self.locked(c):
                    c.clear_orders()
            elif cmd == "cast":
                self.cast(c, msg["slot"], float(msg["x"]), float(msg["z"]))
            elif cmd == "spell":
                self.cast_spell(c, msg["slot"], float(msg["x"]), float(msg["z"]))
        except (KeyError, TypeError, ValueError):
            pass

    def locked(self, c):
        """몸을 쓰는 스킬 동작 중이라 이동·공격·스킬·주문을 할 수 없는가 (이무기 E 등)."""
        return self.time < c.lock_until

    def cmd_move(self, c, x, z):
        if c.dash or self.locked(c):
            return
        c.windup = None
        c.attack_target = None
        c.attack_move = False
        c.move_target = mapdata.clamp_to_map(x, z, c.radius)

    def cmd_attack(self, c, uid):
        if c.dash or self.locked(c):
            return
        target = self.unit(uid)
        if not self.targetable(target, c.team) or not self.can_see(c.team, target):
            return
        if c.attack_target != uid:
            c.windup = None
        c.attack_target = uid
        c.move_target = None
        c.attack_move = False

    def recall(self, c):
        """귀환 시작: 정신집중 동안 가만히 있으면 우물로 이동 (이동·공격·스킬·피해·기절 시 취소).
        맵 절반을 기준으로 우리 진영(우리 우물 쪽)에서는 RECALL_TIME_HOME, 적 진영에서는 RECALL_TIME."""
        if c.dead or c.dash or c.recall_at is not None or c.stunned(self.time) or self.locked(c):
            return
        c.clear_orders()
        home = c.x * mapdata.team_dir(c.team) <= 0.0          # 블루는 x < 0, 레드는 x > 0 이 우리 진영
        c.recall_total = RECALL_TIME_HOME if home else RECALL_TIME
        c.recall_at = self.time + c.recall_total

    def level_ability(self, c, slot):
        if slot not in SLOTS or c.skill_points <= 0:
            return
        if c.ranks[slot] >= c.max_rank(slot):
            return
        c.ranks[slot] += 1
        c.skill_points -= 1

    def buy(self, c, iid):
        """구매. 돈이 모자라면 롤처럼 아직 없는 재료를 살 수 있는 만큼 산다 (gamedata.purchase_plan). 한 번 누른 구매가 되돌리기 한 번."""
        if iid not in gamedata.items() or not self.can_shop(c):
            return
        plan = gamedata.purchase_plan(c.items, iid, c.gold, INVENTORY_SLOTS)
        if not plan:
            return
        before, spent = list(c.items), 0.0
        for one in plan:
            ok, used, price, _why = gamedata.can_buy(c.items, one, INVENTORY_SLOTS)    # 가진 하위 아이템은 재료로 쓰여 값이 깎인다 / 신발은 하나만
            if not ok or c.gold < price:
                break
            for comp in used:
                c.items.remove(comp)
            c.gold -= price
            spent += price
            c.items.append(one)
        if spent > 0:
            c.undo.append({"items": before, "gold": spent})
        c.recompute_stats(self.time)

    def sell(self, c, slot):
        if not self.can_shop(c) or not (0 <= slot < len(c.items)):
            return
        before = list(c.items)
        iid = c.items.pop(slot)
        refund = gamedata.items()[iid]["cost"] * SELL_RATIO
        c.gold += refund
        c.undo.append({"items": before, "gold": -refund})
        c.recompute_stats(self.time)

    PING_KINDS = ("alert", "danger", "omw", "assist", "missing")

    def ping(self, c, x, z, kind):
        """핑: 같은 팀에게만 (x, z) 에 신호를 보낸다. 너무 자주 찍지 못하게 5초에 5번까지."""
        if kind not in self.PING_KINDS:
            return
        t = self.time
        c.ping_times = [p for p in c.ping_times if t - p < 5.0]
        if len(c.ping_times) >= 5:
            return
        c.ping_times.append(t)
        x, z = mapdata.clamp_to_map(x, z)
        self.event(e="ping", d=c.id, k=kind, x=round(x, 2), z=round(z, 2), tm=c.team)

    def swap_items(self, c, a, b):
        """인벤토리 자리 바꾸기 (언제든 가능). b 가 빈 칸이면 a 의 아이템을 맨 뒤 칸으로 옮긴다."""
        n = len(c.items)
        if not (0 <= a < n) or not (0 <= b < INVENTORY_SLOTS) or a == b:
            return
        if b < n:
            c.items[a], c.items[b] = c.items[b], c.items[a]
        else:
            c.items.append(c.items.pop(a))

    def undo(self, c):
        """상점 되돌리기: 마지막 구매·판매를 없던 일로 (아이템과 골드를 그 전으로)."""
        if not c.undo or not self.can_shop(c):
            return
        last = c.undo.pop()
        c.items = list(last["items"])
        c.gold = max(0.0, c.gold + last["gold"])
        c.recompute_stats(self.time)

    # ------------------------------------------------------------------ 스킬
    def ability_damage(self, c, ab, rank):
        base = gamedata.rank_value(ab, "damage", rank, 0.0)
        return (base + ab.get("ad_ratio", 0) * c.stats["ad"] + ab.get("bonus_ad_ratio", 0) * c.stats["bonus_ad"]
                + ab.get("ap_ratio", 0) * c.stats["ap"])

    def ability_amount(self, c, ab, rank, key):
        """damage 외의 수치(회복량·보호막 등). key 값 + key_ap × 주문력 + key_ad × 공격력."""
        return (gamedata.rank_value(ab, key, rank, 0.0) + ab.get(key + "_ap", 0) * c.stats["ap"]
                + ab.get(key + "_ad", 0) * c.stats["ad"])

    def cast(self, c, slot, x, z):
        t = self.time
        if slot not in SLOTS or c.dead or c.stunned(t) or c.dash or c.silenced(t) or self.locked(c):
            return False
        rank = c.ranks[slot]
        if rank <= 0 or t < c.ready_at[slot]:
            return False
        ab = c.data["abilities"][slot]
        handler = abilities.HANDLERS.get(ab["type"])
        if handler is None:
            return False
        cost = gamedata.rank_value(ab, "mana", rank, 0)
        if c.mana < cost:
            return False
        dx, dz = x - c.x, z - c.z
        d = math.hypot(dx, dz)
        if d < 1e-3:
            dx, dz, d = math.cos(c.facing), math.sin(c.facing), 1.0
        cx = abilities.Cast(self, c, slot, ab, rank, x, z, dx / d, dz / d, d)
        if not handler(cx):
            return False

        c.mana -= cost
        c.recall_at = None
        c.ready_at[slot] = t + c.cooldown_of(slot)
        c.windup = None
        c.cast_anim_until = t + 0.3
        self.face(c, x, z)
        self.event(e="cast", d=c.id, slot=slot)
        return True

    def cast_spell(self, c, slot, x, z):
        """D / F 칸에 들어 있는 소환사 주문을 쓴다. (x, z) 는 마우스가 가리키는 바닥 지점."""
        if slot not in ("D", "F") or self.locked(c):
            return
        spell = c.spells[0 if slot == "D" else 1]
        if spell == "flash":
            self.flash(c, x, z, slot)
        elif spell == "mark":
            self.mark(c, x, z, slot)
        else:
            fn = getattr(self, "spell_" + spell, None)
            if fn is not None and self.time >= c.ready_at[slot] and fn(c, x, z):
                c.ready_at[slot] = self.time + SPELLS[spell]["cooldown"]
                c.recall_at = None
                self.event(e="fx", fx="spell", style=spell, x=round(c.x, 2), z=round(c.z, 2), tm=c.team)

    def pick_enemy_champion(self, c, x, z, rng):
        """사거리 안, 볼 수 있는 적 챔피언 중 (x, z) 에 가장 가까운 한 명 (없으면 None)."""
        best, best_d = None, 1e9
        for e in self.champions.values():
            if e.team == c.team:
                continue
            if not self.targetable(e, c.team) or not self.can_see(c.team, e):
                continue
            if c.dist_to(e) > rng + e.radius:
                continue
            d = math.hypot(e.x - x, e.z - z)
            if d < best_d:
                best, best_d = e, d
        return best

    def add_speed_buff(self, u, pct, duration):
        u.buffs.append({"until": self.time + duration, "move_speed_pct": pct})
        u.recompute_stats(self.time)

    def spell_heal(self, c, x, z):
        amount = HEAL_BASE + HEAL_PER_LEVEL * c.level
        self.heal(c, amount, c)
        self.add_speed_buff(c, HEAL_SPEED_PCT, HEAL_SPEED_TIME)
        ally, ratio = None, 2.0
        for a in self.champions.values():
            if a is c or a.team != c.team or a.dead or c.dist_to(a) > HEAL_RANGE:
                continue
            r = a.hp / max(1.0, a.max_hp)
            if r < ratio:
                ally, ratio = a, r
        if ally is not None:
            self.heal(ally, amount * HEAL_ALLY_RATIO, c)
            self.add_speed_buff(ally, HEAL_SPEED_PCT, HEAL_SPEED_TIME)
            self.event(e="fx", fx="spell", style="heal", x=round(ally.x, 2), z=round(ally.z, 2), tm=c.team)
        return True

    def spell_ghost(self, c, x, z):
        self.add_speed_buff(c, GHOST_SPEED_PCT, GHOST_TIME)
        return True

    def spell_barrier(self, c, x, z):
        self.add_shield(c, BARRIER_BASE + BARRIER_PER_LEVEL * c.level, BARRIER_TIME, c)
        return True

    def spell_cleanse(self, c, x, z):
        c.cleanse(self.time)
        c.cc_immune_until = max(c.cc_immune_until, self.time + CLEANSE_IMMUNE)
        return True

    def spell_exhaust(self, c, x, z):
        tg = self.pick_enemy_champion(c, x, z, EXHAUST_RANGE)
        if tg is None:
            return False
        tg.exhaust_until = self.time + EXHAUST_TIME
        tg.apply_slow(self.time, EXHAUST_SLOW, EXHAUST_TIME)
        self.event(e="fx", fx="spell", style="exhaust", x=round(tg.x, 2), z=round(tg.z, 2), tm=c.team)
        return True

    def spell_ignite(self, c, x, z):
        tg = self.pick_enemy_champion(c, x, z, IGNITE_RANGE)
        if tg is None:
            return False
        total = IGNITE_BASE + IGNITE_PER_LEVEL * c.level
        tg.ignite = {"until": self.time + IGNITE_TIME, "next": self.time + IGNITE_TICK,
                     "tick": total * IGNITE_TICK / IGNITE_TIME, "src": c.id}
        self.event(e="fx", fx="spell", style="ignite", x=round(tg.x, 2), z=round(tg.z, 2), tm=c.team)
        return True

    def tick_ignite(self, c):
        ig = c.ignite
        if ig is None:
            return
        t = self.time
        while ig["next"] <= t and ig["next"] <= ig["until"] + 1e-6:
            ig["next"] += IGNITE_TICK
            src = self.champions.get(ig["src"])
            self.deal_damage(src, c, ig["tick"], "true", ability=True)
            if c.dead:
                break
        if c.dead or t >= ig["until"]:
            c.ignite = None

    def flash(self, c, x, z, slot="D"):
        if self.time < c.ready_at[slot] or c.stunned(self.time) or self.locked(c):
            return
        dx, dz = x - c.x, z - c.z
        d = math.hypot(dx, dz)
        if d < 1e-3:
            dx, dz, d = math.cos(c.facing), math.sin(c.facing), 1.0
        dist = min(d, FLASH_RANGE)
        ox, oz = c.x, c.z
        c.x, c.z = self.resolve_position(c.x + dx / d * dist, c.z + dz / d * dist, c.radius)
        c.dash = None
        c.windup = None
        c.recall_at = None
        c.ready_at[slot] = self.time + FLASH_COOLDOWN
        self.face(c, x, z)
        self.event(e="fx", fx="flash", x=round(ox, 2), z=round(oz, 2), x2=round(c.x, 2), z2=round(c.z, 2), tm=c.team)

    def mark(self, c, x, z, slot="F"):
        if self.locked(c):
            return
        # 표식 재사용: 맞힌 대상에게 돌진
        if c.mark and self.time <= c.mark[1]:
            target = self.unit(c.mark[0])
            c.mark = None
            if self.targetable(target, c.team) and not c.rooted(self.time):
                c.clear_orders()
                c.recall_at = None
                c.dash = {"x": target.x, "z": target.z, "speed": MARK_DASH_SPEED, "follow": target.id}
            return
        if self.time < c.ready_at[slot] or c.stunned(self.time):
            return
        dx, dz = x - c.x, z - c.z
        d = math.hypot(dx, dz)
        if d < 1e-3:
            dx, dz, d = math.cos(c.facing), math.sin(c.facing), 1.0
        p = Projectile(self.new_id(), c.team, c, c.x, c.z, "snowball", MARK_SPEED)
        p.dx, p.dz = dx / d, dz / d
        p.remaining = MARK_RANGE
        p.width = 0.7

        def on_hit(sim, target, c=c):
            sim.deal_damage(c, target, 10 + 5 * c.level, "true", ability=True)
            c.mark = (target.id, sim.time + MARK_RECAST_TIME)
        p.on_hit = on_hit
        self.projectiles[p.id] = p
        c.recall_at = None
        c.ready_at[slot] = self.time + MARK_COOLDOWN
        self.face(c, x, z)

    # ------------------------------------------------------------------ 기본 공격
    def basic_attack_payload(self, c, target):
        dmg = c.stats["ad"]
        crit = self.rng.random() < c.stats["crit"]
        if crit:
            dmg *= 1.75
        self.deal_damage(c, target, dmg, "physical", basic=True)

    def release_attack(self, attacker, target, damage_fn, style, speed, ranged):
        if ranged:
            ox, oz = attacker.x, attacker.z
            data = getattr(attacker, "data", None)
            muzzle = data["stats"].get("projectile_muzzle", 0.0) if data else 0.0
            if muzzle:                                       # 입처럼 몸 앞쪽에서 나가는 투사체
                d = math.hypot(target.x - ox, target.z - oz)
                if d > 1e-6:
                    ox, oz = ox + (target.x - ox) / d * muzzle, oz + (target.z - oz) / d * muzzle
            p = Projectile(self.new_id(), attacker.team, attacker, ox, oz, style, speed)
            p.target = target.id
            p.on_hit = damage_fn
            self.projectiles[p.id] = p
        else:
            damage_fn(self, target)

    # ------------------------------------------------------------------ 갱신
    def update(self, dt):
        if self.winner is not None:
            return
        self.time += dt
        t = self.time
        self.help_calls = [h for h in self.help_calls if h[0] > t]
        self.run_scheduled()

        if not self.minion_warned and t >= FIRST_WAVE_TIME - 30.0:
            self.minion_warned = True
            self.event(e="vo", key="minions_30")
        if t >= self.next_wave_at:
            if self.wave_index == 0:
                self.event(e="vo", key="minions_spawned")
            self.spawn_wave()
            self.wave_index += 1
            self.next_wave_at += WAVE_INTERVAL

        for brain in self.brains.values():
            brain.update(self, dt)

        self.update_displacements(dt)
        for c in self.champions.values():
            self.update_champion(c, dt)
        for m in list(self.minions.values()):
            if m.alive:
                self.update_minion(m, dt)
        self.separate_minions()
        for s in self.structures.values():
            self.update_structure(s, dt)
        self.update_projectiles(dt)
        for e in list(self.effects.values()):
            if e.follow is not None:                        # 대상 지정 스킬의 예고 원은 대상을 따라간다 (사라지면 그 자리)
                u = self.unit(e.follow)
                if self.targetable(u, e.team):
                    e.x, e.z = u.x, u.z
                else:
                    e.follow = None
            if t >= e.trigger_at:
                del self.effects[e.id]
                e.on_trigger(self, e)
        self.update_zones(dt)
        self.update_anchors()
        self.update_relics()
        self.update_vision()

    def run_scheduled(self):
        t = self.time
        if not self.scheduled:
            return
        due = [s for s in self.scheduled if s[0] <= t]
        if due:
            self.scheduled = [s for s in self.scheduled if s[0] > t]
            for _, fn in sorted(due, key=lambda s: s[0]):
                fn(self)

    def update_displacements(self, dt):
        """넉백: 밀려나다가 벽·구조물에 막히면 멈추고 스턴."""
        t = self.time
        for u in list(self.champions.values()) + list(self.minions.values()):
            kb = u.kb
            if not kb:
                continue
            if isinstance(u, Champion) and u.dead:
                u.kb = None
                continue
            step = min(kb["speed"] * dt, kb["left"])
            tx, tz = u.x + kb["dx"] * step, u.z + kb["dz"] * step
            rx, rz = self.resolve_position(tx, tz, u.radius)
            blocked = math.hypot(rx - tx, rz - tz) > 0.02
            u.x, u.z = rx, rz
            kb["left"] -= step
            if blocked:
                u.kb = None
                if kb.get("stun", 0) > 0:
                    u.apply_stun(t, kb["stun"])
                self.event(e="fx", fx="wallhit", x=round(u.x, 2), z=round(u.z, 2), tm=1 - u.team)
            elif kb["left"] <= 1e-3:
                u.kb = None

    def update_zones(self, dt):
        t = self.time
        for z in list(self.zones.values()):
            if z.id not in self.zones:
                continue
            if t >= z.until:
                self.end_zone(z)
            else:
                abilities.ZONE_TICK[z.kind](self, z, dt)

    def end_zone(self, z):
        if self.zones.pop(z.id, None) is not None:
            abilities.ZONE_END.get(z.kind, lambda sim, zone: None)(self, z)

    def update_anchors(self):
        t = self.time
        for a in list(self.anchors.values()):
            if t >= a.until:
                abilities.remove_anchor(self, a, hatch=True)

    def update_champion(self, c, dt):
        t = self.time
        if c.undo and not self.can_shop(c):
            c.undo = []                     # 상점(우물)을 벗어나면 되돌리기 기록은 사라진다
        if c.dead:
            if t >= c.respawn_at:
                c.dead = False
                c.recompute_stats(t)
                c.hp, c.mana = c.max_hp, c.max_mana
                pts = mapdata.spawn_points(c.team, 5)
                c.x, c.z = pts[c.id % 5]
                c.clear_orders()
                self.event(e="respawn", d=c.id)
            return

        self.update_statuses(c, dt)
        if c.dead:
            return
        c.gold += PASSIVE_GOLD_PER_SEC * dt
        self.give_xp(c, PASSIVE_XP_PER_SEC * dt)
        c.recompute_stats(t)
        c.hp = min(c.max_hp, c.hp + c.stats["hp_regen"] / 5.0 * dt)
        c.mana = min(c.max_mana, c.mana + c.stats["mana_regen"] / 5.0 * dt)
        if c.mark and t > c.mark[1]:
            c.mark = None
        if self.in_fountain(c):
            self.heal(c, c.max_hp * FOUNTAIN_HEAL_PCT * dt)
            c.mana = min(c.max_mana, c.mana + c.max_mana * FOUNTAIN_HEAL_PCT * dt)

        # 귀환
        if c.recall_at is not None:
            if c.stunned(t):
                c.recall_at = None
            elif t >= c.recall_at:
                c.recall_at = None
                ox, oz = c.x, c.z
                c.x, c.z = mapdata.spawn_points(c.team, 5)[c.id % 5]
                c.clear_orders()
                self.event(e="fx", fx="recall", x=round(ox, 2), z=round(oz, 2), x2=round(c.x, 2), z2=round(c.z, 2), tm=c.team)

        # 적 우물 레이저
        efx, efz = mapdata.fountain_pos(other(c.team))
        if math.hypot(c.x - efx, c.z - efz) < FOUNTAIN_LASER_RADIUS:
            self.deal_damage(None, c, FOUNTAIN_LASER_DPS * dt, "true")
            if c.dead:
                return

        c.anim = 0
        if c.dash:
            self.update_dash(c, dt)
            c.anim = 1
            return
        if c.stunned(t):
            c.windup = None
            return
        if self.locked(c):
            c.anim = 3
            return
        if t < c.cast_anim_until:
            c.anim = 3

        # 공격 준비 동작
        if c.windup:
            fire_at, tid = c.windup
            target = self.unit(tid)
            if not self.targetable(target, c.team):
                c.windup = None
            elif t >= fire_at:
                c.windup = None
                self.release_attack(c, target, lambda sim, tg, c=c: sim.basic_attack_payload(c, tg),
                                    c.data["stats"].get("projectile_style", "arrow"),
                                    c.data["stats"].get("projectile_speed", 20), c.data["stats"].get("ranged", True))
            else:
                c.anim = 2
                return

        target = self.unit(c.attack_target) if c.attack_target else None
        if c.attack_target and (not self.targetable(target, c.team) or not self.can_see(c.team, target)):
            c.attack_target = None
            target = None

        if target is None and c.attack_move:
            target = self.nearest_enemy_for_champion(c, c.stats["attack_range"] + 2.0)
            if target:
                c.attack_target = target.id
            elif c.move_target:
                if self.move_unit(c, c.move_target[0], c.move_target[1], c.stats["move_speed"], dt) or c.rooted(t):
                    pass
                c.anim = 1
                if c.dist_xy(*c.move_target) < 0.1:
                    c.clear_orders()
                return

        if target is not None:
            reach = c.stats["attack_range"] + c.radius + target.radius
            if c.dist_to(target) <= reach:
                self.face(c, target.x, target.z)
                if t >= c.attack_ready_at:
                    period = 1.0 / c.stats["attack_speed"]
                    c.attack_ready_at = t + period
                    c.windup = (t + max(0.08, period * 0.22), target.id)
                    c.anim = 2
                    if isinstance(target, Champion):
                        self.help_calls.append((t + 2.0, c.id, target.team, target.x, target.z))
            elif not c.rooted(t):
                self.move_unit(c, target.x, target.z, c.stats["move_speed"], dt, stop_dist=reach * 0.95)
                c.anim = 1
            return

        if c.move_target and not c.rooted(t):
            if self.move_unit(c, c.move_target[0], c.move_target[1], c.stats["move_speed"], dt):
                c.move_target = None
            else:
                c.anim = 1

    def update_statuses(self, c, dt):
        """매 틱: 점화 피해."""
        self.tick_ignite(c)

    def update_dash(self, c, dt):
        d = c.dash
        if d["follow"]:
            tg = self.unit(d["follow"])
            if not self.targetable(tg, c.team):
                c.dash = None
                return
            d["x"], d["z"] = tg.x, tg.z
            stop = c.radius + tg.radius
        else:
            stop = 0.0
        dx, dz = d["x"] - c.x, d["z"] - c.z
        dist = math.hypot(dx, dz)
        sw, ox, oz = d.get("sweep"), c.x, c.z
        if d.get("delay", 0.0) > 0:                         # 도약 전 웅크리는 시간: 제자리에서 대상을 바라본다
            d["delay"] -= dt
            if dist > 1e-4:
                c.facing = math.atan2(dz, dx)
            return
        if d.get("flight"):                                 # 정해진 시간 동안 날아 정확히 그때 착지한다 (대상이 움직여도)
            left = d["flight"]
            d["flight"] = left - dt
            step = (dist - stop) * dt / left if left > dt else 1e9
        else:
            step = d["speed"] * dt
        if dist - stop <= step:
            if dist > 1e-4:
                k = max(0.0, dist - stop) / dist
                c.x, c.z = self.resolve_position(c.x + dx * k, c.z + dz * k, c.radius)
            if sw:
                abilities.sweep_hit(self, c, sw, ox, oz)
            if d["follow"]:
                c.attack_target = d["follow"]
            c.dash = None
            if d.get("land"):
                abilities.land_slam(self, c, d["land"])        # 점프 덮치기 착지
            return
        c.facing = math.atan2(dz, dx)
        c.x, c.z = self.resolve_position(c.x + dx / dist * step, c.z + dz / dist * step, c.radius, c.ghost(self.time))
        if sw:
            abilities.sweep_hit(self, c, sw, ox, oz)

    def nearest_enemy_for_champion(self, c, radius):
        best, best_d = None, radius
        for u in list(self.champions.values()) + list(self.minions.values()) + list(self.structures.values()):
            if not self.targetable(u, c.team) or not self.can_see(c.team, u):
                continue
            d = c.dist_to(u) - u.radius
            if d < best_d:
                best, best_d = u, d
        return best

    # ------------------------------------------------------------------ 미니언
    def spawn_wave(self):
        minutes = self.time / 60.0
        for team in (BLUE, RED):
            types = ["melee"] * 3
            if self.wave_index % 3 == 2 or (minutes >= 20 and self.wave_index % 2 == 1):
                types.append("cannon")
            enemy_inhib = self.structure_by_key(other(team), "inhib")
            if enemy_inhib is not None and not enemy_inhib.alive:
                types.append("super")
            types += ["caster"] * 3
            sx, sz = mapdata.minion_spawn(team)
            direction = mapdata.team_dir(team)
            for i, mt in enumerate(types):
                row = i // 3
                col = (i % 3) - 1
                x = sx - direction * row * 1.3
                z = sz + col * 1.4
                m = Minion(self.new_id(), team, x, z, mt, minutes)
                m.facing = 0.0 if team == BLUE else math.pi
                self.minions[m.id] = m

    def minion_pick_target(self, m):
        t = self.time
        # 아군 챔피언을 공격한 적 챔피언 (도움 요청)
        for exp, aid, hteam, hx, hz in self.help_calls:
            if hteam == m.team and math.hypot(hx - m.x, hz - m.z) <= MINION_AGGRO:
                a = self.champions.get(aid)
                if self.targetable(a, m.team) and m.dist_to(a) <= MINION_AGGRO and self.can_see(m.team, a):
                    return a
        best, best_d = None, MINION_AGGRO
        for e in self.minions.values():
            if e.team != m.team and self.can_see(m.team, e):
                d = m.dist_to(e)
                if d < best_d:
                    best, best_d = e, d
        if best:
            return best
        for s in self.structures.values():
            if self.targetable(s, m.team):
                d = m.dist_to(s) - s.radius
                if d < best_d:
                    best, best_d = s, d
        if best:
            return best
        for c in self.champions.values():
            if self.targetable(c, m.team) and self.can_see(m.team, c):
                d = m.dist_to(c)
                if d < best_d:
                    best, best_d = c, d
        _ = t
        return best

    def update_spiderling(self, m, dt):
        """새끼 거미 (거미 여왕 E): 가까운 적 챔피언(없으면 적 미니언)을 거미 여왕과 같은 평타(거미줄 탄)로 공격한다.
        적에게 죽지 않는 한 사라지지 않는다."""
        t = self.time
        b = m.baby
        m.anim = 0
        if m.stunned(t):
            m.windup = None
            return
        if m.windup:                                        # 평타 준비 동작: 끝나면 거미줄 탄을 쏜다
            fire_at, tid = m.windup
            tg = self.unit(tid)
            if not self.targetable(tg, m.team) or not self.can_see(m.team, tg):
                m.windup = None
            elif t >= fire_at:
                m.windup = None
                dmg = b["dmg"]
                owner = m.owner
                self.release_attack(m, tg, lambda sim, u, dmg=dmg, owner=owner: sim.deal_damage(owner, u, dmg, "physical", ability=True),
                                    "baby_shot", b.get("proj_speed", 20.0), True)
            else:
                m.anim = 2
                return
        best, best_d = None, 11.0
        for c in self.champions.values():
            if self.targetable(c, m.team) and self.can_see(m.team, c):
                d = m.dist_to(c)
                if d < best_d:
                    best, best_d = c, d
        if best is None:
            best_d = 5.0
            for e in self.minions.values():
                if e.team != m.team and e.mtype != "spiderling" and self.can_see(m.team, e):
                    d = m.dist_to(e)
                    if d < best_d:
                        best, best_d = e, d
        if best is None:                                    # 적이 없으면 주인 곁에 머문다
            o = m.owner
            if m.dist_to(o) > 2.5 and not m.rooted(t):
                self.move_unit(m, o.x, o.z, m.move_speed * (1 - m.slow_amount(t)), dt)
                m.anim = 1
            return
        reach = m.attack_range + m.radius + best.radius
        if m.dist_to(best) <= reach:
            self.face(m, best.x, best.z)
            if t >= m.attack_ready_at:
                period = 1.0 / m.attack_speed
                m.attack_ready_at = t + period
                m.windup = (t + period * 0.3, best.id)
                m.anim = 2
            return
        self.face(m, best.x, best.z)
        if not m.rooted(t):
            self.move_unit(m, best.x, best.z, m.move_speed * (1 - m.slow_amount(t)), dt, stop_dist=reach * 0.9)
            m.anim = 1

    def update_minion(self, m, dt):
        t = self.time
        if m.mtype == "spiderling":
            return self.update_spiderling(m, dt)
        m.anim = 0
        if m.stunned(t):
            m.windup = None
            return
        if m.windup:
            fire_at, tid = m.windup
            target = self.unit(tid)
            if not self.targetable(target, m.team) or not self.can_see(m.team, target):
                m.windup = None
            elif t >= fire_at:
                m.windup = None
                dmg = m.ad
                style = "cannon_ball" if m.mtype == "cannon" else "minion_bolt"
                self.release_attack(m, target, lambda sim, tg, m=m, dmg=dmg: sim.deal_damage(m, tg, dmg, "physical"),
                                    style, 14.0, m.ranged)
            else:
                m.anim = 2
                return

        target = self.unit(m.target) if m.target else None
        if target is not None and not self.can_see(m.team, target):
            target = None                   # 시야에서 사라지면(부쉬 등) 놓친다
        if target is None or not self.targetable(target, m.team) or t >= m.retarget_at:
            # 이미 교전 중인 대상이 사거리 안에 있으면 유지
            keep = (self.targetable(target, m.team)
                    and m.dist_to(target) <= m.attack_range + m.radius + target.radius + 0.3
                    and not isinstance(target, Champion))
            if not keep:
                target = self.minion_pick_target(m)
                m.target = target.id if target else None
            m.retarget_at = t + 0.4

        if target is not None:
            reach = m.attack_range + m.radius + target.radius
            if m.dist_to(target) <= reach:
                self.face(m, target.x, target.z)
                if t >= m.attack_ready_at:
                    period = 1.0 / m.attack_speed
                    m.attack_ready_at = t + period
                    m.windup = (t + period * 0.3, target.id)
                    m.anim = 2
            elif not m.rooted(t):
                self.move_unit(m, target.x, target.z, m.move_speed * (1 - m.slow_amount(t)), dt, stop_dist=reach * 0.9)
                m.anim = 1
            return

        if not m.rooted(t):
            ex = -mapdata.fountain_pos(m.team)[0] * 0.85
            self.move_unit(m, ex, m.lane_z * 0.5, m.move_speed * (1 - m.slow_amount(t)), dt)
            m.anim = 1

    def separate_minions(self):
        ms = list(self.minions.values())
        n = len(ms)
        for i in range(n):
            a = ms[i]
            for j in range(i + 1, n):
                b = ms[j]
                dx, dz = b.x - a.x, b.z - a.z
                min_d = (a.radius + b.radius) * 0.9
                if abs(dx) > min_d or abs(dz) > min_d:
                    continue
                d = math.hypot(dx, dz)
                if d < min_d:
                    if d < 1e-4:
                        dx, dz, d = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1), 1.0
                        d = math.hypot(dx, dz) or 1.0
                    push = (min_d - d) * 0.5
                    ux, uz = dx / d, dz / d
                    a.x, a.z = self.resolve_position(a.x - ux * push, a.z - uz * push, a.radius)
                    b.x, b.z = self.resolve_position(b.x + ux * push, b.z + uz * push, b.radius)

    # ------------------------------------------------------------------ 구조물
    def update_structure(self, s, dt):
        t = self.time
        if not s.alive:
            if (s.skind == "inhibitor" and s.respawn_at is not None and not getattr(s, "soon_sent", False)
                    and s.respawn_at - t <= INHIBITOR_SOON):
                s.soon_sent = True
                self.event(e="vo", key="inhib_soon", tm=s.team)
            if s.skind == "inhibitor" and s.respawn_at is not None and t >= s.respawn_at:
                s.alive = True
                s.hp = s.max_hp
                s.respawn_at = None
                self.event(e="announce", text=f"{'블루' if s.team == BLUE else '레드'}팀 억제기가 재생성되었습니다.")
            return
        if s.skind != "turret":
            return
        rng = mapdata.TURRET_RANGE

        def in_range(u):
            return u is not None and s.dist_to(u) <= rng + u.radius

        target = self.unit(s.target) if s.target else None
        if not self.targetable(target, s.team) or not in_range(target):
            target = None

        # 아군 챔피언을 공격한 적 챔피언 우선
        if not isinstance(target, Champion):
            for exp, aid, hteam, hx, hz in self.help_calls:
                if hteam == s.team and math.hypot(hx - s.x, hz - s.z) <= rng:
                    a = self.champions.get(aid)
                    if self.targetable(a, s.team) and in_range(a):
                        target = a
                        break
        if target is None:
            best, best_d = None, 1e9
            for m in self.minions.values():
                if m.team != s.team and in_range(m):
                    d = s.dist_to(m)
                    if d < best_d:
                        best, best_d = m, d
            if best is None:
                for c in self.champions.values():
                    if self.targetable(c, s.team) and in_range(c):
                        d = s.dist_to(c)
                        if d < best_d:
                            best, best_d = c, d
            target = best

        new_id = target.id if target else None
        if new_id != s.target:
            s.ramp = 0
            if isinstance(target, Champion):
                # 포탑이 이 챔피언을 처음 노린다 -> 본인에게 경고음
                self.event(e="fx", fx="turret_lock", x=s.x, z=s.z, d=target.id)
        s.target = new_id
        if target is None or t < s.attack_ready_at:
            return
        s.attack_ready_at = t + TURRET_PERIOD
        if isinstance(target, Champion):
            dmg = (TURRET_CHAMP_DMG + 2.5 * min(30.0, t / 60.0)) * (1 + 0.4 * min(s.ramp, 3))
            shot_style = "turret_shot" if s.ramp == 0 else ("turret_shot_2" if s.ramp < 3 else "turret_shot_3")
            s.ramp += 1

            def hit(sim, tg, s=s, dmg=dmg):
                sim.deal_damage(s, tg, dmg, "physical")
        else:
            pct = TURRET_MINION_DMG.get(target.mtype, 0.3)

            def hit(sim, tg, s=s, pct=pct):
                sim.deal_damage(s, tg, tg.max_hp * pct, "true")
        self.release_attack(s, target, hit, shot_style if isinstance(target, Champion) else "turret_shot", 16.0, True)

    # ------------------------------------------------------------------ 투사체
    def update_projectiles(self, dt):
        for p in list(self.projectiles.values()):
            if p.target is not None:
                tg = self.unit(p.target)
                if tg is None or not tg.alive or (isinstance(tg, Champion) and tg.dead):
                    p.dead = True
                else:
                    dx, dz = tg.x - p.x, tg.z - p.z
                    d = math.hypot(dx, dz)
                    step = p.speed * dt
                    if d <= step + tg.radius * 0.5:
                        p.dead = True
                        if p.on_hit:
                            p.on_hit(self, tg)
                    else:
                        p.dx, p.dz = dx / d, dz / d
                        p.x += p.dx * step
                        p.z += p.dz * step
            else:
                step = min(p.speed * dt, p.remaining)
                ox, oz = p.x, p.z
                p.x += p.dx * step
                p.z += p.dz * step
                p.remaining -= step
                p.traveled += step
                hits = []
                for u in (list(self.champions.values()) + list(self.minions.values())
                          + [a for a in self.anchors.values() if getattr(a, "cocoon", False)]):
                    if u.id in p.hit_ids or not self.targetable(u, p.team) or isinstance(u, Structure):
                        continue
                    if point_segment_dist(u.x, u.z, ox, oz, p.x, p.z) <= p.width * 0.5 + u.radius:
                        hits.append(((u.x - ox) * p.dx + (u.z - oz) * p.dz, u))
                hits.sort(key=lambda h: h[0])
                if hits and not p.pierce:
                    hits = hits[:1]
                for _, hit in hits:
                    p.hit_ids.add(hit.id)
                    if p.on_hit:
                        p.on_hit(self, hit)
                    self.event(e="fx", fx=p.style + "_hit", x=round(hit.x, 2), z=round(hit.z, 2), tm=p.team)
                if hits and not p.pierce:
                    p.dead = True
                elif p.remaining <= 1e-4:
                    p.dead = True
                    if not p.hit_ids and p.on_miss:
                        p.on_miss(self, p)
            if p.dead:
                self.projectiles.pop(p.id, None)

    # ------------------------------------------------------------------ 유물
    def update_relics(self):
        t = self.time
        for r in self.relics:
            if not r.active:
                if t >= r.respawn_at:
                    r.active = True
                continue
            for c in self.champions.values():
                if not c.dead and math.hypot(c.x - r.x, c.z - r.z) <= RELIC_RADIUS + c.radius:
                    self.heal(c, c.max_hp * RELIC_HEAL_PCT)
                    c.mana = min(c.max_mana, c.mana + c.max_mana * RELIC_HEAL_PCT)
                    r.active = False
                    r.respawn_at = t + RELIC_RESPAWN
                    self.event(e="fx", fx="relic", x=r.x, z=r.z, d=c.id)
                    break

    # ------------------------------------------------------------------ 직렬화
    def static_info(self):
        return {
            "structures": [{"i": s.id, "k": s.skind, "key": s.key, "tm": s.team, "x": s.x, "z": s.z,
                            "r": s.radius, "mhp": s.max_hp, "pl": s.plates} for s in self.structures.values()],
            "champions": [{"i": c.id, "pk": c.member_key, "n": c.name, "c": c.champ_id, "tm": c.team, "bot": c.is_bot}
                          for c in self.champions.values()],
        }

    def event_visible(self, team, ev):
        """이 이벤트를 team 에게 보내도 되는가 (안 보이는 곳의 정보는 숨긴다)."""
        e = ev.get("e")
        if e in ("dmg", "gold", "heal"):
            keys = ("s", "d") if e == "dmg" else ("d",)
            return any((ch := self.champions.get(ev.get(k))) is not None and ch.team == team for k in keys)
        if e == "ping":
            return ev.get("tm") == team                     # 핑은 같은 팀에게만
        if e in ("cast", "levelup"):
            u = self.champions.get(ev.get("d"))
            return u is not None and self.can_see(team, u)
        if e == "fx" and "x" in ev:
            obs = self._observers[team]
            pts = [(ev["x"], ev["z"])] + ([(ev["x2"], ev["z2"])] if "x2" in ev else [])
            return any(self.seen_by(obs, x, z) for x, z in pts)
        return True

    def champion_row(self, c, t):
        st = []
        if c.stunned(t):
            st.append("stun")
        if c.slow_amount(t) > 0:
            st.append("slow")
        if c.buffs:
            st.append("buff")
        if c.silenced(t):
            st.append("silence")
        if t < c.root_until:
            st.append("root")
        if c.airborne(t):
            st.append("air")
        if c.shield_total(t) > 0:
            st.append("shield")
        if c.ghost(t):
            st.append("ghost")
        if c.cc_immune(t):
            st.append("immune")
        if t < c.exhaust_until:
            st.append("exhaust")
        if c.ignite:
            st.append("ignite")
        row = {
            "i": c.id, "x": round(c.x, 2), "z": round(c.z, 2), "f": round(c.facing, 2),
            "hp": round(c.hp), "mhp": round(c.max_hp), "mp": round(c.mana), "mmp": round(c.max_mana),
            "lv": c.level, "xp": round(c.xp), "xpn": xp_to_next(c.level), "g": int(c.gold), "it": c.items,
            "ab": c.ranks, "sp": c.skill_points,
            "cd": {k: round(max(0.0, v - t), 1) for k, v in c.ready_at.items()},
            "mk": bool(c.mark), "spl": c.spells, "dead": c.dead, "rt": round(max(0.0, c.respawn_at - t), 1) if c.dead else 0,
            "rc": round(max(0.0, c.recall_at - t), 1) if c.recall_at is not None else 0, "rct": c.recall_total,
            "st": st, "a": c.anim, "k": c.kills, "d": c.deaths, "as": c.assists, "cs": c.cs,
            "shop": self.can_shop(c), "ud": len(c.undo),
            "s": {"ad": round(c.stats["ad"]), "ap": round(c.stats["ap"]), "ar": round(c.stats["armor"]),
                  "mr": round(c.stats["mr"]), "aspd": round(c.stats["attack_speed"], 2),
                  "ms": round(c.stats["move_speed"] * 100), "ah": round(c.stats["ability_haste"]),
                  "cr": round(c.stats["crit"] * 100)},
            "sb": {k: round(v, 2) for k, v in c.base_stats.items()},
            "sh": round(c.shield_total(t)),
        }
        return row

    def snapshots(self):
        """팀별 스냅샷 {팀: 스냅샷}. 각 팀은 자기 시야에 있는 적만 받는다."""
        t = self.time
        champs = {c.id: self.champion_row(c, t) for c in self.champions.values()}
        # 점수판(Tab)은 시야와 상관없이 모두에게
        board = [[c.id, c.level, c.kills, c.deaths, c.assists, c.cs, int(c.gold), c.items, c.dead,
                  round(max(0.0, c.respawn_at - t)) if c.dead else 0, kill_bounty(c.bounty_pts), c.spells]
                 for c in self.champions.values()]
        structs = [[s.id, round(s.hp), int(s.alive), int(self.vulnerable(s)), s.target or 0]
                   for s in self.structures.values()]
        out = {}
        for team in (BLUE, RED):
            obs = self._observers[team]
            vis = self.visible[team]
            minions = [[m.id, MINION_CODES[m.mtype], m.team, round(m.x, 2), round(m.z, 2), round(m.facing, 2),
                        round(m.hp), round(m.max_hp), m.anim]
                       for m in self.minions.values() if m.team == team or m.id in vis]
            projs = [[p.id, p.style, p.team, round(p.x, 2), round(p.z, 2), round(p.dx, 2), round(p.dz, 2)]
                     for p in self.projectiles.values() if p.team == team or self.seen_by(obs, p.x, p.z)]
            effs = [[e.id, e.style, e.team, round(e.x, 2), round(e.z, 2), e.radius, round(e.trigger_at - t, 2)]
                    for e in self.effects.values() if e.team == team or self.seen_by(obs, e.x, e.z)]
            zones = [[z.id, z.style, z.team, round(z.x, 2), round(z.z, 2), z.radius, round(z.until - t, 2),
                      round(z.until - z.born, 2)]
                     for z in self.zones.values()
                     if z.team == team or self.seen_by(obs, z.x, z.z)]
            anchors = [[a.id, a.team, round(a.x, 2), round(a.z, 2), math.ceil(a.hp), round(a.until - t, 1),
                        1 if getattr(a, "cocoon", False) else 0, round(getattr(a, "until", 0) - getattr(a, "born", 0), 1),
                        int(a.max_hp)]
                       for a in self.anchors.values() if self.can_see(team, a)]
            # 회복 구슬은 시야 안에 있을 때만 있다고 알려준다
            relics = [[r.id, r.x, r.z, int(r.active and self.seen_by(obs, r.x, r.z))] for r in self.relics]
            out[team] = {
                "t": "snap", "time": round(t, 2), "score": [self.score[BLUE], self.score[RED]],
                "ch": [row for cid, row in champs.items() if self.champions[cid].team == team or cid in vis],
                "mn": minions, "st": structs, "pj": projs, "ef": effs, "zn": zones, "an": anchors, "rl": relics, "sb": board,
                "gone": self.gone_minions,
                "ev": [ev for ev in self.events if self.event_visible(team, ev)],
                "wave": round(max(0.0, self.next_wave_at - t), 1),
            }
        self.events = []
        self.gone_minions = []
        return out
