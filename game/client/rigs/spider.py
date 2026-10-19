"""동굴 여왕 거미 — 보스러시(DEEP NEST) 1층 보스의 절차적 리그를 이 게임으로 옮긴 것.

원본: bosses/spider/rig.py (구·원통·원뿔로 만든 몸 + 다리 8개의 2본 IK + 발걸음 + 포즈 블렌딩).
이 게임의 렌더러는 씬 그래프가 없어서, 부품마다 메시 하나(몸통/눈/배/주머니/다리 3종)를 만들어 두고
매 프레임 부품의 행렬을 계산해 그린다. 모든 계산은 원본과 같은 "보스 단위"로 하고 마지막에 SC 배로 줄인다.

챔피언 동작 연결:
  update(dt, d, ent)  서버 상태(d)와 화면 위치(ent.x, ent.z, ent.f)로 몸·다리를 갱신
  cast(slot)          스킬 시전 시작 (Q 앞다리 들기 / W 배 치켜들기 + 뒤돌기 / R 앞다리 들기)
  leap(dur)           점프 덮치기(E): 공중 자세 → 착지하며 다리가 퍼진다
  draw(r, tint, emis) 그리기
죽으면 마디마다 흩어지는(원본의 explode) 파편이 된다.
"""
import math
import random

import numpy as np

from ..geometry import MeshBuilder
from ..gl import Mesh, facing_to_rot
from . import CHAMP_SCALE, DEATH_FADE, DEATH_SHOW

PI = math.pi
SC = 0.28 * CHAMP_SCALE         # 보스 단위 -> 이 게임 단위
THORAX_R = 1.7
LEAP_PEAK = 26.0 / CHAMP_SCALE  # 점프 최고 높이 (보스 단위, 몸 크기와 상관없이 월드 약 7.3)

IDLE = {'height': 2.3, 'pitch': 0, 'abdomen': 0.14, 'stance': 1, 'frontRaise': 0, 'squash': 1,
        'tremble': 0, 'legFollow': 0, 'abdPulse': 0}
POSES = {
    'idle': {},
    'webWind': {'height': 2.85, 'pitch': -0.45, 'frontRaise': 1, 'tremble': 0.03},
    'crouch': {'height': 1.2, 'stance': 0.82, 'squash': 0.86, 'abdomen': 0.32, 'tremble': 0.05},
    'air': {'height': 2.0, 'legFollow': 1, 'squash': 1.08, 'pitch': -0.25, 'abdomen': 0.2},
    'splay': {'height': 1.05, 'stance': 1.38, 'abdomen': -0.06, 'squash': 0.92},
    'barrage': {'height': 2.6, 'pitch': 0.14, 'abdomen': 1.05, 'tremble': 0.07},
    'eggs': {'height': 1.85, 'abdomen': -0.14, 'abdPulse': 1, 'tremble': 0.035, 'stance': 1.1},
    'rear': {'height': 3.05, 'pitch': -0.75, 'frontRaise': 1, 'abdomen': 0.35, 'stance': 1.05},
    'stagger': {'height': 0.95, 'stance': 1.42, 'abdomen': -0.12, 'squash': 0.96},
}
L1, L2 = 2.6, 4.7
HIP_Z = [0.82, 0.28, -0.28, -0.82]
HOME_ANGLE = [0.95, 0.4, -0.2, -0.72]
HOME_R = [5.0, 5.5, 5.5, 5.1]
LEG_COUNT = 8
GROUPS = [0, 1, 0, 1, 1, 0, 1, 0]
ATTACK_TIME = 0.34


# ------------------------------------------------------------------ 행렬 도구
def _T(x, y, z):
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def _S(x, y=None, z=None):
    y = x if y is None else y
    z = x if z is None else z
    return np.diag([x, y, z, 1.0])


def _Rx(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def _Ry(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def _Rz(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def _euler(x, y, z):
    return _Rx(x) @ _Ry(y) @ _Rz(z)                # three.js 의 XYZ 순서


def _from_to(a, b):
    """단위 벡터 a 를 b 로 돌리는 회전 (4x4)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    m = np.eye(4)
    if c < -0.999999:
        m[:3, :3] = np.diag([1.0, -1.0, -1.0])      # 반대 방향: X 축 둘레 180도
        return m
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    m[:3, :3] = np.eye(3) + vx + vx @ vx / (1 + c)
    return m


_SCALE = _S(SC)


def _hex(h, k=1.0):
    return (min(1.0, ((h >> 16) & 255) / 255 * k), min(1.0, ((h >> 8) & 255) / 255 * k), min(1.0, (h & 255) / 255 * k))


def _xf(dst, src, M):
    """src 의 정점을 M 으로 옮겨 dst 에 붙인다."""
    if not src.verts:
        return
    arr = np.array(src.verts, dtype=float)
    R, t = M[:3, :3], M[:3, 3]
    pos = arr[:, :3] @ R.T + t
    nrm = arr[:, 3:6] @ R.T
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.where(ln < 1e-9, 1.0, ln)
    out = np.concatenate([pos, nrm, arr[:, 6:]], axis=1)
    dst.verts.extend(map(tuple, out))


def _sphere(r, color, scale=(1, 1, 1), seg=14, rings=10):
    b = MeshBuilder()
    b.sphere((0, 0, 0), r, color, seg, rings, scale)
    return b


def _cyl(r_bottom, r_top, h, color, seg=7, centered=True):
    b = MeshBuilder()
    b.cylinder((0, -h / 2 if centered else 0.0, 0), r_bottom, h, color, seg, radius_top=r_top)
    return b


# ------------------------------------------------------------------ 메시 (렌더러당 한 번)
class SpiderAssets:
    def __init__(self, renderer):
        k = 1.35                                    # 위에서 내려다보는 시점에서도 잘 보이도록 원본보다 살짝 밝게
        thorax, eyes, abd, sacs = MeshBuilder(), MeshBuilder(), MeshBuilder(), MeshBuilder()
        _xf(thorax, _sphere(1.3, _hex(0x4A1C16, k), (1, 0.85, 1.15)), _T(0, 0, 0))
        _xf(thorax, _sphere(0.85, _hex(0x5C2418, k), (1, 0.9, 1), 12, 9), _T(0, 0.12, 1.35))
        white = (1.0, 1.0, 1.0)
        for sx in (-1, 1):
            _xf(eyes, _sphere(0.2, white, seg=10, rings=8), _T(sx * 0.34, 0.42, 2.06))
            _xf(eyes, _sphere(0.11, white, seg=8, rings=6), _T(sx * 0.62, 0.38, 1.86))
            _xf(eyes, _sphere(0.11, white, seg=8, rings=6), _T(sx * 0.24, 0.72, 1.92))
            _xf(eyes, _sphere(0.11, white, seg=8, rings=6), _T(sx * 0.7, 0.14, 1.74))
            cone = MeshBuilder()
            cone.cylinder((0, -0.475, 0), 0.15, 0.95, _hex(0xCFC4A8, 1.1), 7, radius_top=0.0)
            _xf(thorax, cone, _T(sx * 0.3, -0.55, 2.1) @ _Rx(PI - 0.35))
            _xf(thorax, _cyl(0.14, 0.1, 0.9, _hex(0x3A1812, k), 6), _T(sx * 0.72, -0.25, 2.1) @ _Rx(1.1))
        # 배 (abdomen 좌표계: 배 중심이 원점)
        _xf(abd, _sphere(1.9, _hex(0x7C2218, k), (1, 0.9, 1.25), 16, 12), _T(0, 0, 0))
        spike_col = _hex(0x1C0C08, 1.6)
        A, B, C = 1.9, 1.71, 2.375
        for px, py, pz in ((0.9, 1.23, -1.2), (1.0, 1.44, 0.3), (0.5, 0.8, -2.0), (1.25, 0.9, -0.55)):
            for sx in (-1, 1):
                n = np.array([sx * px / (A * A), py / (B * B), pz / (C * C)])
                n /= np.linalg.norm(n)
                sp = MeshBuilder()
                sp.cylinder((0, -0.375, 0), 0.17, 0.75, spike_col, 6, radius_top=0.0)
                pos = np.array([sx * px, py, pz]) + n * 0.25
                _xf(abd, sp, _T(*pos) @ _from_to((0, 1, 0), n))
        for sx in (-1, 1):
            sp = MeshBuilder()
            sp.cylinder((0, -0.35, 0), 0.2, 0.7, spike_col, 6, radius_top=0.0)
            _xf(abd, sp, _T(sx * 0.25, -0.1, -2.5) @ _Rx(-PI / 2))
        for r_, pos in ((0.55, (0, 1.52, -0.6)), (0.46, (0, 1.08, -1.85)), (0.4, (0, 1.58, 0.55))):
            _xf(sacs, _sphere(r_, white, seg=12, rings=9), _T(*pos))
        mk = lambda b: Mesh.from_builder(renderer, b)
        self.thorax, self.eyes, self.abdomen, self.sacs = mk(thorax), mk(eyes), mk(abd), mk(sacs)
        # 다리: 아래(엉덩이/무릎) 쪽에서 위(무릎/발끝) 쪽으로 높이 1, +Y 가 끝
        self.upper = mk(_cyl(1.0, 0.8, 1.0, _hex(0x35160E, 1.7), 7, centered=False))
        self.lower = mk(_cyl(0.9, 0.34, 1.0, _hex(0x35160E, 1.7), 7, centered=False))
        self.knee = mk(_sphere(0.4, _hex(0xC08A34, 1.1), seg=9, rings=7))


def _wrap(a):
    while a > PI:
        a -= 2 * PI
    while a < -PI:
        a += 2 * PI
    return a


def heavy_chain(state, tx, tz, start, dt, rate_head, rate_tail, max_bend=None):
    """긴 몸(이무기 몸통·용 꼬리)을 묵직하게 끌고 다닌다.
    start 앞의 마디는 목표 자리(머리가 지나온 길)에 그대로 두고, 그 뒤는 마디마다 방향(앞 마디 -> 이 마디)을 들고 있다가
    목표 모양의 방향 쪽으로 rate_head(start 마디) ~ rate_tail(꼬리 끝) 의 빠르기(1/초)로만 돌린다. 위치는 앞 마디에서
    그 방향으로 목표 모양의 간격만큼 이어 붙인다. max_bend(rad, 숫자 하나 또는 마디 사이마다의 배열)가 있으면
    앞 마디와 꺾이는 각도도 그 이하로 묶어 몸이 빳빳해진다. 그래서 빙빙 돌아도 꼬리가 길을 그대로 따라 작게 꼬이지 않고, 늦게 묵직하게 돈다.
    state: 지난 프레임의 마디 방향 배열 (없으면 None). 반환: (x, z, 새 방향 배열)."""
    n = len(tx)
    start = max(1, min(n, start))
    dx, dz = np.diff(tx), np.diff(tz)
    seg = np.hypot(dx, dz)
    want = np.arctan2(dz, dx)                          # want[k-1] = 마디 k-1 -> k 의 목표 방향
    if state is None or len(state) != n - 1:
        return tx.copy(), tz.copy(), want
    ang = state.copy()
    ang[:start - 1] = want[:start - 1]
    u = np.clip((np.arange(1, n) - start) / max(1, n - 1 - start), 0.0, 1.0)
    k = 1 - np.exp(-(rate_head + (rate_tail - rate_head) * u) * dt)
    d = (want - ang + np.pi) % (2 * np.pi) - np.pi
    ang = ang + d * k
    # 이웃 마디와 방향을 조금 고르게 (꼬리 끝이 꺾여 접히지 않게)
    s0 = start - 1
    if n - 1 - s0 > 2:
        a = ang[s0:]
        dl = (np.roll(a, 1) - a + np.pi) % (2 * np.pi) - np.pi
        dr = (np.roll(a, -1) - a + np.pi) % (2 * np.pi) - np.pi
        dl[0] = dr[-1] = 0.0
        ang[s0:] = a + 0.25 * (dl + dr)
    if max_bend is not None and s0 > 0:
        al = ang.tolist()
        mbl = np.broadcast_to(np.asarray(max_bend, dtype=float), (n - 1,)).tolist()
        for j in range(s0, n - 1):
            rel = (al[j] - al[j - 1] + math.pi) % (2 * math.pi) - math.pi
            mb = mbl[j]
            if rel > mb:
                al[j] = al[j - 1] + mb
            elif rel < -mb:
                al[j] = al[j - 1] - mb
        ang = np.array(al)
    x, z = tx.copy(), tz.copy()
    cx, cz = np.cos(ang[s0:]) * seg[s0:], np.sin(ang[s0:]) * seg[s0:]
    x[start:] = x[start - 1] + np.cumsum(cx)
    z[start:] = z[start - 1] + np.cumsum(cz)
    return x, z, ang


class _Debris:
    __slots__ = ("mesh", "base", "pos", "ang", "vel", "spin", "tint", "unlit", "rest", "r")


class SpiderAnim:
    def __init__(self, assets):
        self.a = assets
        self.t = 0.0
        self.cur = dict(IDLE)
        self.tgt = dict(IDLE)
        self.rate = {k: 8.0 for k in IDLE}
        self.pose_name = 'idle'
        self.px = self.pz = 0.0
        self.yaw = 0.0
        self.vel = [0.0, 0.0]
        self.lift = 0.0
        self.have_pos = False
        self.hip_local = []
        self.home_local = []
        self.side = []
        for n in range(LEG_COUNT):
            s = -1 if n < 4 else 1
            i = n % 4
            self.side.append(s)
            self.hip_local.append((s * 0.95, 0.05, HIP_Z[i]))
            self.home_local.append((s * HOME_R[i] * math.cos(HOME_ANGLE[i]), 0.0, HOME_R[i] * math.sin(HOME_ANGLE[i])))
        self.homes = [[0.0, 0.0, 0.0] for _ in range(LEG_COUNT)]
        self.feet = [[0.0, 0.0, 0.0] for _ in range(LEG_COUNT)]
        self.f_from = [[0.0] * 3 for _ in range(LEG_COUNT)]
        self.f_to = [[0.0] * 3 for _ in range(LEG_COUNT)]
        self.f_t = [0.0] * LEG_COUNT
        self.f_dur = [0.2] * LEG_COUNT
        self.f_step = [False] * LEG_COUNT
        self.f_lift = [0.0] * LEG_COUNT
        self.gait_phase = 0.0
        self.legs = [None] * LEG_COUNT                  # (hip, knee, end)
        self.M_body = np.eye(4)
        self.M_abd = np.eye(4)
        self.cast_pose = None
        self.cast_until = 0.0
        self.turn_back_until = 0.0
        self.leap_t0 = -9.0
        self.leap_dur = 0.0
        self.landed_until = 0.0
        self.atk_t = 0.0
        self.atk_leg = 0
        self.atk_i = 0
        self.prev_a = 0
        self.last_attack = -9.0
        self.rage = False
        self.was_dead = False
        self.dead_clock = 0.0
        self.debris = []
        self.won = False
        self.hit_flash = 0.0
        self._compute_homes(1.0)
        self.snap_feet()
        self._sync_body(0.0)
        self._solve_legs()

    # ------------------------------------------------------------ 외부 API (게임·선택 장면이 부른다)
    def set_pose(self, name, rate=8.0):
        if name == self.pose_name and abs(self.rate.get('height', 0) - rate) < 1e-6:
            return
        self.pose_name = name
        p = {**IDLE, **POSES[name]}
        for k, v in p.items():
            self.tgt[k] = v
            self.rate[k] = rate

    def cast(self, slot):
        if slot == "W":                                   # 앞다리를 들고 몸을 젖힘 (거미줄 장판)
            self.cast_pose, self.cast_until = 'webWind', self.t + 0.6
        elif slot == "Q":                                 # 뒤돌아 배를 치켜들고 독침을 뿌림
            self.cast_pose, self.cast_until = 'barrage', self.t + 0.95
            self.turn_back_until = self.t + 0.95
        elif slot == "E":                                 # 배를 부풀려 고치를 낳는다
            self.cast_pose, self.cast_until = 'eggs', self.t + 0.9
        self.atk_t = 0.0

    def leap(self, dur, delay=0.0):
        """점프 덮치기: delay 초 웅크렸다가 dur 초 동안 날아가 착지한다."""
        self.leap_t0 = self.t + delay
        self.leap_dur = max(0.15, dur)
        self.landed_until = 0.0
        self.cast_pose = None
        self.atk_t = 0.0

    def play_key(self, key):
        if key == "attack":
            self.attack()
        elif key == "R":
            self.leap(0.5)
        else:
            self.cast(key)

    def attack(self, windup=0.0):
        self.atk_t = ATTACK_TIME
        self.atk_leg = 0 if self.atk_i % 2 == 0 else 4
        self.atk_i += 1
        self.last_attack = self.t

    def win(self):
        if not self.won:
            self.won = True

    @property
    def corpse_visible(self):
        return self.dead_clock < DEATH_SHOW

    @property
    def alpha(self):
        if self.was_dead:
            return max(0.0, min(1.0, (DEATH_SHOW - self.dead_clock) / DEATH_FADE))
        return 1.0

    # ------------------------------------------------------------ 발 / 홈
    def _compute_homes(self, stance):
        sy, cy = math.sin(self.yaw), math.cos(self.yaw)
        for i in range(LEG_COUNT):
            lx = self.home_local[i][0] * stance
            lz = self.home_local[i][2] * stance
            self.homes[i][0] = self.px + lx * cy + lz * sy
            self.homes[i][1] = 0.0
            self.homes[i][2] = self.pz - lx * sy + lz * cy

    def snap_feet(self):
        for i in range(LEG_COUNT):
            self.feet[i][:] = self.homes[i]
            self.f_step[i] = False
            self.f_lift[i] = 0.0

    def slide_feet(self, stance, time):
        self._compute_homes(stance)
        for i in range(LEG_COUNT):
            self.f_from[i][:] = self.feet[i]
            self.f_to[i][:] = self.homes[i]
            self.f_t[i] = 0.0
            self.f_dur[i] = time
            self.f_step[i] = True
            self.f_lift[i] = 0.5

    def _gait_update(self, dt, o):
        for i in range(LEG_COUNT):
            if not self.f_step[i]:
                continue
            self.f_t[i] += dt / self.f_dur[i]
            k = min(1.0, self.f_t[i])
            e = k * k * (3 - 2 * k)
            for j in range(3):
                self.feet[i][j] = self.f_from[i][j] + (self.f_to[i][j] - self.f_from[i][j]) * e
            if k >= 1:
                self.f_step[i] = False
                self.feet[i][:] = self.f_to[i]
        for i in range(LEG_COUNT):
            if self.f_step[i]:
                continue
            d = math.hypot(self.feet[i][0] - self.homes[i][0], self.feet[i][2] - self.homes[i][2])
            if d <= o['threshold']:
                continue
            blocked = any(self.f_step[j] and GROUPS[j] != GROUPS[i] for j in range(LEG_COUNT))
            if blocked and d < o['threshold'] * 2.4:
                continue
            self.f_from[i][:] = self.feet[i]
            self.f_to[i][:] = (self.homes[i][0] + self.vel[0] * o['lead'], self.homes[i][1],
                               self.homes[i][2] + self.vel[1] * o['lead'])
            self.f_t[i] = 0.0
            self.f_dur[i] = o['stepTime']
            self.f_step[i] = True
            self.f_lift[i] = o['lift']

    def _foot(self, i):
        f = list(self.feet[i])
        if self.f_step[i]:
            f[1] += math.sin(PI * min(1.0, self.f_t[i])) * self.f_lift[i]
        return f

    # ------------------------------------------------------------ 몸
    def _sync_body(self, dt):
        p = self.cur
        spd = math.hypot(self.vel[0], self.vel[1])
        self.gait_phase += dt * (2 + spd * 1.3)
        walk = min(1.0, spd / 3) * (1 - p['legFollow'])
        bob = math.sin(self.gait_phase * 2) * 0.08 * walk
        tr = p['tremble']
        r = random.random
        bx = (r() - 0.5) * tr * 2 if tr else 0.0
        by = p['height'] + bob + ((r() - 0.5) * tr if tr else 0.0) + self.lift
        bz = (r() - 0.5) * tr * 2 if tr else 0.0
        roll = math.sin(self.gait_phase) * 0.03 * walk
        sq = max(0.5, p['squash'])
        k = 1 / math.sqrt(sq)
        M_root = _T(self.px, 0.0, self.pz) @ _Ry(self.yaw)
        self.M_body = M_root @ _T(bx, by, bz) @ _euler(p['pitch'], 0, roll) @ _S(k, sq, k)
        pulse = 1 + 0.14 * p['abdPulse'] * (0.5 + 0.5 * math.sin(self.t * 13))
        self.M_abd = (self.M_body @ _T(0, 0.25, -1.0) @ _Rx(p['abdomen']) @ _T(0, 0.35, -2.3) @ _S(pulse))

    def _solve_two_bone(self, hip, target, pole_hint):
        d = np.array(target) - np.array(hip)
        dl = float(np.linalg.norm(d))
        if dl < 1e-5:
            d, dl = np.array([0.0, -1.0, 0.0]), 1e-5
        else:
            d = d / dl
        d_min, d_max = abs(L1 - L2) + 0.02, L1 + L2 - 0.02
        dc = min(d_max, max(d_min, dl))
        cos_a = (L1 * L1 + dc * dc - L2 * L2) / (2 * L1 * dc)
        sin_a = math.sqrt(max(0.0, 1 - cos_a * cos_a))
        pole = np.array(pole_hint, float) - d * float(np.dot(pole_hint, d))
        if float(np.dot(pole, pole)) < 1e-6:
            pole = np.array([1.0, 0.0, 0.0]) - d * d[0]
        pole /= max(1e-9, float(np.linalg.norm(pole)))
        hip = np.array(hip)
        return hip + d * (L1 * cos_a) + pole * (L1 * sin_a), hip + d * dc

    def _solve_legs(self):
        p = self.cur
        sy, cy = math.sin(self.yaw), math.cos(self.yaw)
        t = self.t
        for i in range(LEG_COUNT):
            s = self.side[i]
            hl = self.hip_local[i]
            hip = (self.M_body @ np.array([hl[0], hl[1], hl[2], 1.0]))[:3]
            foot = self._foot(i)
            if (i == 0 or i == 4) and p['frontRaise'] > 0.01:
                wig = math.sin(t * 9 + i) * 0.35
                lx, lz = s * 1.5 + wig * s, 3.6
                tmp = (self.px + lx * cy + lz * sy, p['height'] + self.lift + 1.9 + math.sin(t * 7 + i * 2) * 0.3,
                       self.pz - lx * sy + lz * cy)
                k = min(1.0, p['frontRaise'])
                foot = [foot[j] + (tmp[j] - foot[j]) * k for j in range(3)]
            if self.atk_t > 0 and i == self.atk_leg:                       # 기본 공격: 앞다리를 들었다가 내리찍는다
                k = 1 - self.atk_t / ATTACK_TIME
                if k < 0.4:
                    w, fwd, hgt = k / 0.4, 2.6, 2.2 * (k / 0.4)
                elif k < 0.6:
                    w, fwd, hgt = 1.0, 2.6 + 3.0 * ((k - 0.4) / 0.2), 2.2 * (1 - (k - 0.4) / 0.2) + 0.3
                else:
                    w, fwd, hgt = 1 - (k - 0.6) / 0.4, 5.6, 0.3
                lx, lz = s * 1.4, fwd
                tmp = (self.px + lx * cy + lz * sy, hgt + self.lift, self.pz - lx * sy + lz * cy)
                foot = [foot[j] + (tmp[j] - foot[j]) * w for j in range(3)]
            if p['legFollow'] > 0.001:
                lx, lz = self.home_local[i][0] * 0.4, self.home_local[i][2] * 0.4
                tmp = (self.px + lx * cy + lz * sy, max(0.4, p['height'] - 1.5) + self.lift,
                       self.pz - lx * sy + lz * cy)
                k = min(1.0, p['legFollow'])
                foot = [foot[j] + (tmp[j] - foot[j]) * k for j in range(3)]
            hlx, hlz = self.home_local[i][0], self.home_local[i][2]
            pole = np.array([hlx * cy + hlz * sy, 0.0, -hlx * sy + hlz * cy])
            pole = pole / max(1e-9, float(np.linalg.norm(pole))) * 0.45
            pole[1] = 1.0
            knee, end = self._solve_two_bone(hip, foot, pole)
            self.legs[i] = (hip, knee, end)

    # ------------------------------------------------------------ 매 프레임
    def update(self, dt, d, ent=None):
        dt = min(dt, 0.1)
        self.t += dt
        d = d or {}
        st = d.get("st", ())
        a = d.get("a", 0)
        dead = bool(d.get("dead"))
        if ent is not None:
            self._track(dt, ent, d)
        if dead:
            if not self.was_dead:
                self.was_dead = True
                self.dead_clock = 0.0
                self._explode()
            self.dead_clock += dt
            self._update_debris(dt)
            return
        if self.was_dead:                                   # 부활
            self.was_dead = False
            self.debris = []
            self.cast_pose = None
            self.leap_dur = 0.0
            self._compute_homes(1.0)
            self.snap_feet()
        mh = d.get("mhp") or 0
        self.rage = bool(mh) and d.get("hp", mh) / mh < 0.4
        # 새로 시작된 기본 공격 (이벤트가 따로 없으니 서버 상태로 판단)
        if a == 2 and self.t - self.last_attack > 0.6 and self.cast_pose is None and not self.leap_dur:
            self.attack()
        self.prev_a = a
        self.atk_t = max(0.0, self.atk_t - dt)
        # 자세 고르기
        fly = self._leaping()
        if fly:
            p = (self.t - self.leap_t0) / self.leap_dur
            self.lift = LEAP_PEAK * 4 * p * (1 - p)
            self.set_pose('air', 14)
        else:
            self.lift += (0.0 - self.lift) * min(1.0, dt * 14)
            if self.leap_dur and self.landed_until == 0.0 and self.t >= self.leap_t0 + self.leap_dur:
                self.landed_until = self.t + 0.4                    # 착지: 다리가 사방으로 퍼진다
                self.set_pose('splay', 26)
                self.slide_feet(1.38, 0.13)
                self.leap_dur = 0.0
            if self.leap_dur and self.t < self.leap_t0:                # 도약 직전: 몸을 낮게 웅크린다
                self.set_pose('crouch', 12)
            elif self.t < self.landed_until:
                pass
            elif "air" in st:
                self.set_pose('air', 8)
            elif "stun" in st:
                self.set_pose('stagger', 6)
            elif self.cast_pose and self.t < self.cast_until:
                self.set_pose(self.cast_pose, 7 if self.cast_pose == 'webWind' else 6)
            elif self.won:
                self.set_pose('rear', 5)
            elif d.get("rc", 0) > 0:
                self.set_pose('crouch', 4)
            else:
                self.cast_pose = None
                self.landed_until = 0.0
                self.set_pose('idle', 6 if self.pose_name in ('webWind', 'barrage') else 4)
        if fly:
            self.landed_until = 0.0
        # 포즈 블렌딩
        for k in self.cur:
            self.cur[k] += (self.tgt[k] - self.cur[k]) * (1 - math.exp(-self.rate[k] * dt))
        self._sync_body(dt)
        self._compute_homes(self.cur['stance'])
        if self.cur['legFollow'] < 0.5:
            spd = math.hypot(self.vel[0], self.vel[1])
            self._gait_update(dt, {'threshold': 1.25 * self.cur['stance'], 'stepTime': max(0.12, 0.2 - spd * 0.006),
                                   'lift': 1.05, 'lead': 0.12})
        self._solve_legs()

    def _leaping(self):
        return self.leap_dur > 0 and 0.0 <= self.t - self.leap_t0 < self.leap_dur

    def _track(self, dt, ent, d):
        x, z = ent.x / SC, ent.z / SC
        face = facing_to_rot(ent.f)
        if self.turn_back_until > self.t:
            face += PI                                  # 배(꼬리쪽)가 목표를 향하도록
        if not self.have_pos:
            self.have_pos = True
            self.px, self.pz, self.yaw = x, z, face
            self._compute_homes(1.0)
            self.snap_feet()
            return
        mx, mz = x - self.px, z - self.pz
        moved = math.hypot(mx, mz)
        if moved > 14.0 and not self._leaping():        # 순간이동 (귀환·플래시·부활): 발도 새 자리에
            self.px, self.pz, self.vel = x, z, [0.0, 0.0]
            self._compute_homes(self.cur['stance'])
            self.snap_feet()
        else:
            k = 1 - math.exp(-10 * dt)
            vx, vz = (mx / dt, mz / dt) if dt > 1e-6 else (0.0, 0.0)
            self.vel[0] += (vx - self.vel[0]) * k
            self.vel[1] += (vz - self.vel[1]) * k
            self.px, self.pz = x, z
        self.yaw += _wrap(face - self.yaw) * (1 - math.exp(-14 * dt))

    # ------------------------------------------------------------ 그리기
    def _parts(self):
        """(메시, 보스 단위 월드 행렬, 색 조정, 밝기 고정 여부) 목록."""
        a = self.a
        out = [(a.thorax, self.M_body, None, False), (a.eyes, self.M_body, 'eye', True),
               (a.abdomen, self.M_abd, None, False), (a.sacs, self.M_abd, 'sac', True)]
        for i in range(LEG_COUNT):
            hip, knee, end = self.legs[i]
            out.append((a.upper, self._seg(hip, knee, 0.3), None, False))
            out.append((a.lower, self._seg(knee, end, 0.27), None, False))
            out.append((a.knee, _T(*knee), None, False))
        return out

    @staticmethod
    def _seg(a, b, th):
        d = np.array(b) - np.array(a)
        ln = float(np.linalg.norm(d))
        if ln < 1e-5:
            return _T(*a) @ _S(th, 1e-4, th)
        return _T(*a) @ _from_to((0, 1, 0), d / ln) @ _S(th, ln, th)

    def _glow(self, kind):
        t = self.t
        if kind == 'eye':
            k = 1.3 + 0.4 * math.sin(t * (17 if self.rage else 4))
            return (1.0 * k, 0.12 * k, 0.08 * k) if self.rage else (1.0 * k, 0.78 * k, 0.12 * k)
        q = 0.95 + 0.3 * math.sin(t * (13 if self.rage else 3.2))
        return (1.0 * q, 0.5 * q, 0.06 * q)

    def draw(self, r, tint=(1, 1, 1, 1), emis=(0, 0, 0)):
        alpha = tint[3] if len(tint) > 3 else 1.0
        base_e = (emis[0] + 0.05, emis[1] + 0.015, emis[2] + 0.01)
        if self.was_dead:
            for db in self.debris:
                M = _T(*db.pos) @ _euler(*db.ang) @ db.base
                self._draw_part(r, db.mesh, M, db.tint, db.unlit, tint, alpha, base_e)
            return
        for mesh, M, kind, unlit in self._parts():
            col = self._glow(kind) if kind else None
            self._draw_part(r, mesh, M, col, unlit, tint, alpha, base_e)

    def _draw_part(self, r, mesh, M, col, unlit, tint, alpha, base_e):
        model = _SCALE @ M
        if col is not None:
            r.draw(mesh, model, tint=(col[0], col[1], col[2], alpha), unlit=1.0)
        else:
            r.draw(mesh, model, tint=(tint[0], tint[1], tint[2], alpha), emissive=base_e)

    # ------------------------------------------------------------ 사망: 마디별 분해 (원본의 explode)
    def _explode(self):
        r = random.random
        center = np.array([self.px, 1.8, self.pz])
        self.debris = []
        for mesh, M, kind, unlit in self._parts():
            db = _Debris()
            db.mesh = mesh
            pos = M[:3, 3].copy()
            base = M.copy()
            base[:3, 3] = 0.0
            db.base = base
            d = pos - center
            d[1] = abs(d[1]) * 0.5 + 0.6
            d /= max(1e-6, float(np.linalg.norm(d)))
            sp = 4 + r() * 9
            db.vel = d * sp + np.array([(r() - 0.5) * 3, 5 + r() * 8, (r() - 0.5) * 3])
            db.pos = pos
            db.ang = np.zeros(3)
            db.spin = np.array([(r() - 0.5) * 12, (r() - 0.5) * 12, (r() - 0.5) * 12])
            db.tint = (1.0, 1.0, 1.0)
            db.unlit = unlit
            db.rest = False
            db.r = 0.5
            if kind:
                db.tint = self._glow(kind)
            else:
                db.tint = None
            self.debris.append(db)

    def _update_debris(self, dt):
        for db in self.debris:
            if db.rest:
                continue
            db.vel[1] -= 28 * dt
            db.pos += db.vel * dt
            db.ang += db.spin * dt
            if db.pos[1] < db.r:
                db.pos[1] = db.r
                db.vel[1] *= -0.35
                db.vel[0] *= 0.78
                db.vel[2] *= 0.78
                db.spin *= 0.6
                if abs(db.vel[1]) < 1.2 and math.hypot(db.vel[0], db.vel[2]) < 0.6:
                    db.rest = True


# ------------------------------------------------------------------ 새끼 거미 (거미 여왕을 줄인 모양, 같은 걸음걸이)
BABY_S = 0.105                  # 보스 단위 -> 새끼 거미 크기
BABY_FRAMES = 16                # 한 걸음 주기를 이만큼의 모양으로 나눠 둔다
BABY_SPEED = 26.0               # 걸음 모양을 만들 때의 이동 속도 (보스 단위/초)

_baby_cache = {}


def _baby_cycle():
    """메인 거미와 같은 걸음 알고리즘(발 고정 → 멀어지면 짝지어 번갈아 내딛기 + 2본 IK 무릎)을 곧게 걷는 몸에 돌려서
    한 주기의 몸·다리 자세를 몸 기준 좌표로 뽑아 둔다. -> (주기(초), [{body, abd, legs}] * BABY_FRAMES)"""
    if "cycle" in _baby_cache:
        return _baby_cache["cycle"]

    class _Ent:
        pass

    ent = _Ent()
    ent.x = ent.z = 0.0
    ent.f = 0.0
    ent.f = math.atan2(1.0, 0.0)                     # 서버 facing: (cos, sin) = (dx, dz) -> +Z 방향
    anim = SpiderAnim(None)
    dt = 1 / 120
    vz = BABY_SPEED * SC                             # 월드 단위/초

    def tick():
        ent.z += vz * dt
        anim.update(dt, {"a": 1, "st": ()}, ent)

    starts = []
    prev = False
    t = 0.0
    for _ in range(int(3.5 / dt)):
        tick()
        t += dt
        cur = anim.f_step[0]
        if cur and not prev and t > 1.0:
            starts.append(t)
        prev = cur
    period = (starts[-1] - starts[-2]) if len(starts) >= 2 else 0.35
    # 한 주기를 다시 돌리며 자세를 저장
    frames = []
    nxt = 0.0
    el = 0.0
    while len(frames) < BABY_FRAMES:
        if el >= nxt:
            root = _T(anim.px, 0.0, anim.pz) @ _Ry(anim.yaw)
            inv = np.linalg.inv(root)
            legs = []
            for hip, knee, end in anim.legs:
                legs.append(tuple((inv @ np.array([*p, 1.0]))[:3] for p in (hip, knee, end)))
            frames.append({"body": inv @ anim.M_body, "abd": inv @ anim.M_abd, "legs": legs})
            nxt += period / BABY_FRAMES
        tick()
        el += dt
    _baby_cache["cycle"] = (period, frames)
    return _baby_cache["cycle"]


def baby_period():
    return _baby_cycle()[0]


def build_baby(frame, team_color=None):
    """새끼 거미 한 프레임의 모양 (MeshBuilder). 몸·눈은 거미 여왕과 같은 비율과 색이고, 가시와 눈 여러 개는 뺐으며
    등의 주황 구는 하나다."""
    period, frames = _baby_cycle()
    fr = frames[frame % BABY_FRAMES]
    k = 1.35
    b = MeshBuilder()
    S = _S(BABY_S)
    _xf(b, _sphere(1.3, _hex(0x4A1C16, k), (1, 0.85, 1.15), 10, 8), S @ fr["body"])
    _xf(b, _sphere(0.85, _hex(0x5C2418, k), (1, 0.9, 1), 9, 7), S @ fr["body"] @ _T(0, 0.12, 1.35))
    for sx in (-1, 1):
        _xf(b, _sphere(0.26, (1.0, 0.95, 0.8), seg=8, rings=6), S @ fr["body"] @ _T(sx * 0.34, 0.45, 2.06))
    _xf(b, _sphere(1.9, _hex(0x7C2218, k), (1, 0.9, 1.25), 11, 8), S @ fr["abd"])
    _xf(b, _sphere(0.62, (1.0, 0.62, 0.18), seg=9, rings=6), S @ fr["abd"] @ _T(0, 1.62, -0.6))   # 등의 주황 구 하나
    leg_col = _hex(0x35160E, 1.9)
    up = _cyl(1.0, 0.8, 1.0, leg_col, 5, centered=False)
    lo = _cyl(0.9, 0.34, 1.0, leg_col, 5, centered=False)
    kn = _sphere(0.5, _hex(0xC08A34, 1.2), seg=6, rings=4)
    for hip, knee, end in fr["legs"]:
        _xf(b, up, S @ SpiderAnim._seg(hip, knee, 0.34))
        _xf(b, lo, S @ SpiderAnim._seg(knee, end, 0.3))
        _xf(b, kn, S @ _T(*knee))
    return b
