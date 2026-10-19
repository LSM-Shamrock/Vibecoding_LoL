"""망령 사신 — 절차적 리그.

다리 없이 떠 있는 해골 사신: 두건 속 해골, 몸통, 소매 달린 두 팔(2본 IK), 두 손으로 쥔 거대한 낫.
옷자락(긴 로브·등 망토·소매 끝)은 천 시뮬레이션으로 움직인다. 입자(Verlet) 사이를 거리 제약으로 묶고,
위쪽은 몸에 붙들어 두고 아래로 갈수록 원래 모양으로 약하게만 끌어당겨서, 몸이 움직이면 끝자락이 늦게 따라오며
바람(흔들림)에 펄럭인다. 끝자락은 기둥마다 길이가 들쭉날쭉해 너덜너덜하다.

챔피언 동작 연결:
  update(dt, d, ent)   서버 상태(d)와 화면 위치(ent.x, ent.z, ent.f)로 몸·낫·천을 갱신
  cast(slot)           Q 크게 휘두르기 / W 낫 던지기 / E 망령 걸음 / R 내려치기
  on_fx(kind, ev)      lunge(E 돌진 자세) · scythe_throw / scythe_catch(낫이 손을 떠남 / 돌아옴) · reap(R 준비 시간)
  draw(r, tint, emis)  그리기
죽으면 몸이 로브 속으로 꺼지고, 붙들려 있던 천이 풀려 바닥에 무너져 내린다.
"""
import math
import random

import numpy as np

from ..geometry import MeshBuilder
from ..gl import Mesh, facing_to_rot
from . import CHAMP_SCALE, DEATH_FADE, DEATH_SHOW
from .spider import _S, _T, _Rx, _Ry, _Rz, _from_to, _sphere, _wrap, _xf

PI = math.pi
SC = 1.15 * CHAMP_SCALE         # 리그 단위 -> 월드 단위
_SCALE = _S(SC)

WAIST_Y = 1.15                  # 떠 있는 허리 높이
CHEST_UP = 0.42                 # 허리 -> 가슴
SHOULDER = (0.39, 0.07)         # 가슴 기준 어깨 (좌우, 높이)
HEAD_AT = (0.0, 0.46, 0.04)     # 가슴 기준 머리
UPPER, FORE = 0.44, 0.46        # 위팔 / 아래팔 길이

# 낫 (낫 좌표: 아래쪽 손잡이가 원점, +Y 가 자루 끝, +Z 가 날이 뻗는 쪽)
BUTT, TOP = -0.75, 1.65
BLADE_LEN = 1.3
GRIP2 = 0.5                     # 왼손이 쥐는 자리 (오른손은 원점). 팔이 닿지 않으면 왼손은 놓는다

CLOTH_TOP = (0.21, 0.18, 0.28)
CLOTH_HEM = (0.36, 0.28, 0.5)
BONE = (0.9, 0.87, 0.78)
SHAFT = (0.24, 0.17, 0.15)
METAL = (0.55, 0.5, 0.62)
BLADE = (0.8, 0.84, 0.92)
SOUL = (0.55, 0.95, 1.0)        # 날끝의 영혼 빛

H = 1 / 50                      # 천 시뮬레이션 한 걸음 (초)
MAX_STEPS = 5
ITERS = 3
ATTACK_TIME = 0.5


def _n(v):
    v = np.asarray(v, float)
    ln = float(np.linalg.norm(v))
    return v / ln if ln > 1e-9 else v


def _smooth(k):
    k = min(1.0, max(0.0, k))
    return k * k * (3 - 2 * k)


def _lerp(a, b, k):
    return a + (b - a) * k


# ------------------------------------------------------------------ 낫 자세: (g 아래 손잡이, u 자루 방향, b 날 방향)
def _pose(g, u, b):
    u = _n(u)
    b = np.asarray(b, float)
    b = _n(b - u * float(np.dot(b, u)))
    return (np.asarray(g, float), u, b)


def _mix(p, q, k):
    return _pose(_lerp(p[0], q[0], k), _lerp(p[1], q[1], k), _lerp(p[2], q[2], k))


def sweep_pose(theta, phi, rad=0.46, y=1.38):
    """몸 둘레로 수평에 가깝게 휘두르는 자세. theta: 자루가 뻗는 방향(0 = 앞, + = 오른쪽), phi: 들린 각도.
    날은 theta 가 줄어드는 쪽(오른쪽 -> 왼쪽으로 휘두를 때 나아가는 쪽)을 향한다."""
    st, ct = math.sin(theta), math.cos(theta)
    u = (st * math.cos(phi), math.sin(phi), ct * math.cos(phi))
    return _pose((rad * st, y, rad * ct), u, (-ct, 0.0, st))


def chop_pose(alpha, y=1.55):
    """몸 앞 세로로 내려치는 자세. alpha: 자루가 앞 수평에서 아래로 기운 각도 (음수면 위로, -pi/2 면 수직)."""
    sa, ca = math.sin(alpha), math.cos(alpha)
    return _pose((0.24, y, 0.36), (0.22, -sa, ca), (0.0, -ca, -sa))


IDLE_POSE = _pose((0.2, 1.02, 0.5), (0.25, 1.0, 0.05), (-0.35, 0.0, 1.0))
MOVE_POSE = _pose((0.42, 1.12, 0.2), (0.15, 0.55, -0.82), (-0.2, 0.9, 0.4))
RECALL_POSE = _pose((0.32, 0.95, 0.32), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
WIN_POSE = _pose((0.28, 1.72, 0.25), (0.15, 1.0, 0.2), (-0.3, 0.0, 1.0))
STUN_POSE = _pose((0.2, 0.85, 0.4), (0.3, 0.55, 0.75), (-1.0, 0.0, 0.2))
DEAD_POSE = _pose((0.5, 0.06, -0.9), (-0.2, 0.0, 1.0), (1.0, 0.0, 0.0))


# ------------------------------------------------------------------ 메시
def _sleeve(r0, r1, color, seg=14):
    """반지름 1 기준 원통 (아래 r0 -> 위 r1, 높이 1, +Y). 그릴 때 두께·길이로 늘린다."""
    b = MeshBuilder()
    b.cylinder((0, 0, 0), r0, 1.0, color, seg, radius_top=r1)
    return b


def _loft(rings, color, seg=22, cut=None):
    """아래에서 위로 쌓은 타원 단면들을 매끈하게 이은 면. rings: (높이, 좌우 반지름, 앞뒤 반지름, 앞뒤 치우침[, 앞쪽만 더 내밈]).
    단면 각도 0 이 앞(+Z). cut(높이, 각도) 가 참인 칸은 비운다 (두건의 얼굴 구멍)."""
    P = np.zeros((len(rings), seg + 1, 3))
    for j, rg in enumerate(rings):
        y, rx, rz, cz = rg[:4]
        fr = rg[4] if len(rg) > 4 else 0.0
        for i in range(seg + 1):
            a = 2 * PI * i / seg
            c = math.cos(a)
            P[j, i] = (math.sin(a) * rx, y, c * rz + cz + fr * max(0.0, c) ** 2)
    du = np.roll(P, -1, axis=1) - np.roll(P, 1, axis=1)
    du[:, 0] = du[:, -1] = P[:, 1] - P[:, -2]
    dv = np.zeros_like(P)
    dv[1:-1] = P[2:] - P[:-2]
    dv[0], dv[-1] = P[1] - P[0], P[-1] - P[-2]
    N = np.cross(du, dv)
    N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-9)
    b = MeshBuilder()
    for j in range(len(rings) - 1):
        for i in range(seg):
            if cut and cut((rings[j][0] + rings[j + 1][0]) / 2, 2 * PI * (i + 0.5) / seg):
                continue
            q = [(j, i), (j, i + 1), (j + 1, i + 1), (j + 1, i)]
            pts = [tuple(P[a, c]) for a, c in q]
            ns = [tuple(N[a, c]) for a, c in q]
            b.tri(pts[0], pts[1], pts[2], color, ns[0], ns[1], ns[2])
            b.tri(pts[0], pts[2], pts[3], color, ns[0], ns[2], ns[3])
    return b


def _face_hole(y, a):
    a = (a + PI) % (2 * PI) - PI
    return abs(a) < math.radians(52) and -0.17 < y < 0.19


def _blade_curve(n=16):
    """날의 등(spine)과 날끝(edge) 점들 (낫 좌표)."""
    out = []
    for k in range(n + 1):
        s = k / n
        spine = np.array([0.0, TOP - 0.06 - 0.5 * s ** 1.8, BLADE_LEN * s])
        tan = np.array([0.0, -0.9 * s ** 0.8, BLADE_LEN])
        inner = _n((0.0, -tan[2], tan[1]))                  # 등에서 자루 쪽 아래로
        w = 0.27 * (1 - s) ** 0.7 + 0.012
        out.append((spine, spine + inner * w, 0.028 * (1 - s) + 0.006))
    return out


def scythe_builders():
    """낫 메시 (자루, 날, 날끝 빛) — 낫 좌표, 리그 단위."""
    shaft, blade, edge = MeshBuilder(), MeshBuilder(), MeshBuilder()
    shaft.cylinder((0, BUTT, 0), 0.038, TOP - BUTT, SHAFT, 8, radius_top=0.034)
    shaft.cylinder((0, BUTT - 0.08, 0), 0.03, 0.1, METAL, 8, radius_top=0.045)          # 물미
    for y in (-0.08, 0.5, 0.62):                                                        # 손잡이 감은 띠
        shaft.cylinder((0, y, 0), 0.046, 0.06, METAL, 8)
    shaft.sphere((0, TOP - 0.02, 0), 0.075, METAL, 10, 7)                               # 날 이음매
    shaft.cylinder((0, TOP + 0.03, 0), 0.05, 0.16, METAL, 8, radius_top=0.0)            # 끝 뿔
    pts = _blade_curve()
    for (s0, e0, t0), (s1, e1, t1) in zip(pts, pts[1:]):
        for sx in (1, -1):
            a, b_ = s0 + (sx * t0, 0, 0), s1 + (sx * t1, 0, 0)
            c, d = e1 + (sx * 0.004, 0, 0), e0 + (sx * 0.004, 0, 0)
            if sx > 0:
                blade.quad(tuple(a), tuple(b_), tuple(c), tuple(d), BLADE)
            else:
                blade.quad(tuple(a), tuple(d), tuple(c), tuple(b_), BLADE)
        blade.quad(tuple(s0 + (-t0, 0, 0)), tuple(s1 + (-t1, 0, 0)), tuple(s1 + (t1, 0, 0)), tuple(s0 + (t0, 0, 0)), METAL)
        e0b, e1b = e0 + (s0 - e0) * 0.1, e1 + (s1 - e1) * 0.1                         # 날끝을 따라 흐르는 빛 띠
        for sx in (1, -1):
            edge.quad(tuple(e0 + (sx * 0.006, 0, 0)), tuple(e1 + (sx * 0.006, 0, 0)),
                      tuple(e1b + (sx * 0.012, 0, 0)), tuple(e0b + (sx * 0.012, 0, 0)), (1, 1, 1))
    return shaft, blade, edge


def build_scythe_projectile():
    """날아가는 낫 (던지기): 월드 크기, 자루가 X 축으로 누워 무게중심이 원점, Y 축으로 돌리면 수평으로 돈다."""
    shaft, blade, edge = scythe_builders()
    out = MeshBuilder()
    M = _S(SC) @ _Rz(-PI / 2) @ _T(0, -0.85, -0.3)
    for b, col in ((shaft, None), (blade, None), (edge, (0.75, 0.95, 1.0))):
        if col:
            b.verts = [(*v[:6], *col, *v[9:]) for v in b.verts]
        _xf(out, b, M)
    return out


class ReaperAssets:
    def __init__(self, renderer):
        mk = lambda b: Mesh.from_builder(renderer, b)
        # 아랫몸 (허리 좌표): 로브 윗단 속으로 이어지는 허리
        torso = _loft([(-0.15, 0.25, 0.21, 0.0), (0.1, 0.27, 0.215, 0.0), (0.32, 0.3, 0.225, 0.0)], CLOTH_TOP)
        # 윗몸 (가슴 좌표): 가슴 -> 둥글게 처진 어깨 -> 목 (어깨 끝에서 팔이 나온다)
        chest = _loft([(-0.34, 0.29, 0.22, 0.0), (-0.14, 0.32, 0.235, 0.0), (0.0, 0.35, 0.24, -0.01),
                       (0.07, 0.38, 0.23, -0.02), (0.13, 0.33, 0.21, -0.02), (0.18, 0.23, 0.17, -0.01),
                       (0.23, 0.13, 0.12, 0.0)], CLOTH_TOP)
        for sx in (-1, 1):
            _xf(chest, _sphere(0.1, CLOTH_TOP, (1.0, 0.95, 1.0), 12, 8), _T(sx * SHOULDER[0], SHOULDER[1], 0))
        # 두건 (머리 좌표): 어깨에 걸친 자락에서 뒤로 뾰족하게 접힌 꼭대기까지, 앞은 얼굴 자리가 뚫렸고 안은 새까맣다
        hood = _loft([(-0.31, 0.31, 0.27, -0.03), (-0.2, 0.25, 0.25, 0.0, 0.03), (-0.06, 0.215, 0.235, 0.0, 0.05),
                      (0.08, 0.205, 0.23, -0.01, 0.06), (0.19, 0.175, 0.2, -0.04, 0.04), (0.27, 0.12, 0.15, -0.09),
                      (0.33, 0.06, 0.08, -0.15), (0.36, 0.0, 0.0, -0.21)], CLOTH_TOP, cut=_face_hole)
        inner = MeshBuilder()
        inner.sphere((0, 0.0, 0.0), 0.2, (0, 0, 0), 14, 10, (0.95, 1.0, 1.0))
        self.torso, self.chest, self.hood, self.inner = mk(torso), mk(chest), mk(hood), mk(inner)
        self.upper = mk(_sleeve(1.0, 0.85, CLOTH_TOP))
        self.fore = mk(_sleeve(0.8, 1.55, CLOTH_TOP))
        self.elbow = mk(_sphere(1.0, CLOTH_TOP, seg=10, rings=7))
        hand = MeshBuilder()
        hand.sphere((0, 0, 0), 0.065, BONE, 10, 7, (1.0, 0.8, 1.2))
        for k in range(3):                                   # 손가락 마디
            hand.cylinder(((k - 1) * 0.03, 0.0, 0.05), 0.013, 0.07, BONE, 5, radius_top=0.009)
        self.hand = mk(hand)
        shaft, blade, edge = scythe_builders()
        self.shaft, self.blade, self.edge = mk(shaft), mk(blade), mk(edge)
        self.cloth_spec = _cloth_spec()
        n = len(self.cloth_spec["tris"]) * 3
        self.cloth = Mesh(renderer, [(np.zeros((n, 11), dtype="f4"), None)])     # 천: 매 프레임 정점을 새로 써 넣는다


# ------------------------------------------------------------------ 천
def _cloth_spec():
    """천 조각들(로브 / 등 망토 / 두 소매 끝)의 쉬는 모양과 제약 (모든 사신이 같은 모양을 쓴다)."""
    rng = random.Random(7)
    rest, anchor, stiff, tf, phase, col, outward = [], [], [], [], [], [], []
    pairs, lens, tris = [], [], []

    def patch(grid, aid, stiff_rows, wrap, push_out):
        R, C = len(grid), len(grid[0])
        base = len(rest)
        idx = lambda r, c: base + r * C + (c % C)
        for r in range(R):
            t = r / (R - 1)
            for c in range(C):
                rest.append(grid[r][c])
                anchor.append(aid)
                stiff.append(stiff_rows[r])
                tf.append(t)
                phase.append(c * 2.399 + aid * 1.3)
                col.append(tuple(_lerp(np.array(CLOTH_TOP), np.array(CLOTH_HEM), t ** 1.2)))
                outward.append(push_out)
        cols = C if wrap else C - 1
        for r in range(R):
            for c in range(C):
                if r + 1 < R:
                    pairs.append((idx(r, c), idx(r + 1, c)))
                if r + 2 < R:
                    pairs.append((idx(r, c), idx(r + 2, c)))
                if r > 0 and c < cols:
                    pairs.append((idx(r, c), idx(r, c + 1)))
        for r in range(R - 1):
            for c in range(cols):
                a, b, cc, d = idx(r, c), idx(r, c + 1), idx(r + 1, c + 1), idx(r + 1, c)
                tris.append((a, d, cc))
                tris.append((a, cc, b))

    # 로브 (허리 좌표): 허리에 붙어 아래로 넓게 퍼진다. 앞은 조금 짧고, 기둥마다 길고 짧아 끝이 톱니처럼 해졌다
    R, C = 8, 20
    lengths = [0.84 * (1 - 0.08 * math.cos(2 * PI * c / C)) + (0.17 if c % 2 else 0.0) + rng.uniform(-0.05, 0.05) for c in range(C)]
    grid = []
    for r in range(R):
        t = r / (R - 1)
        row = []
        for c in range(C):
            a = 2 * PI * c / C
            rad = 0.27 + (0.56 - 0.27) * t ** 1.25
            row.append((math.sin(a) * rad, 0.02 - lengths[c] * t, math.cos(a) * rad * 0.93))
        grid.append(row)
    patch(grid, 0, [1.0, 0.2, 0.08, 0.035, 0.018, 0.011, 0.008, 0.006], True, 1.0)
    # 등 망토 (가슴 좌표): 두 어깨 사이 등에서 늘어져 로브 바깥으로 흩날린다
    R, C = 9, 9
    grid = []
    lengths = []
    for c in range(C):
        x = (c / (C - 1) - 0.5) * 2
        lengths.append(1.38 + 0.08 * (1 - x * x) + (0.15 if c % 2 else 0.0) + rng.uniform(-0.06, 0.06))
    for r in range(R):
        t = r / (R - 1)
        row = []
        for c in range(C):
            x = (c / (C - 1) - 0.5) * 2
            row.append((x * 0.32 * (1 + 0.45 * t), 0.14 - lengths[c] * t, -0.19 - 0.06 * (1 - x * x) - 0.44 * t ** 1.1))
        grid.append(row)
    patch(grid, 1, [1.0, 0.12, 0.05, 0.022, 0.012, 0.008, 0.006, 0.005, 0.004], False, 0.0)
    # 소매 끝 (손목 좌표 둘: +Y 가 손 쪽): 넓은 소매 끝이 해져 늘어진다
    for aid in (2, 3):
        R, C = 4, 7
        lengths = [0.26 + (0.09 if c % 2 else 0.0) + rng.uniform(-0.03, 0.03) for c in range(C)]
        grid = []
        for r in range(R):
            t = r / (R - 1)
            row = []
            for c in range(C):
                a = 2 * PI * c / C
                rad = 0.16 + 0.07 * t
                row.append((math.cos(a) * rad, lengths[c] * t, math.sin(a) * rad))
            grid.append(row)
        patch(grid, aid, [1.0, 0.05, 0.02, 0.012], True, 0.0)

    rest = np.array(rest, float)
    pairs = np.array(pairs, int)
    anchor = np.array(anchor, int)
    # 제약 길이는 쉬는 모양에서 그대로 잰다 (소매는 손목 좌표라 그대로, 나머지도 각자 좌표 안에서)
    lens = np.linalg.norm(rest[pairs[:, 1]] - rest[pairs[:, 0]], axis=1)
    pinned = np.array(tf) == 0.0
    w = (~pinned).astype(float)
    ws = w[pairs[:, 0]] + w[pairs[:, 1]]
    ws[ws == 0] = 1.0
    cnt = np.bincount(pairs.ravel(), minlength=len(rest)).astype(float)
    cnt[cnt == 0] = 1.0
    n, m = len(rest), len(pairs)
    tris = np.array(tris, int)

    def gather(wa, wb):
        """제약 보정량(m) -> 입자 이동량(n) 을 한 번의 행렬곱으로 모으는 행렬 (np.add.at 보다 훨씬 빠르다)."""
        G = np.zeros((n, m))
        G[pairs[:, 0], np.arange(m)] += wa
        G[pairs[:, 1], np.arange(m)] -= wb
        return G * (1.5 / cnt)[:, None]
    tri_g = np.zeros((n, len(tris)))
    for k in range(3):
        tri_g[tris[:, k], np.arange(len(tris))] += 1.0
    return {"rest": rest, "anchor": anchor, "groups": [np.where(anchor == k)[0] for k in range(4)],
            "stiff": np.array(stiff), "tf": np.array(tf), "phase": np.array(phase), "col": np.array(col),
            "outward": np.array(outward), "pairs": pairs, "lens": lens, "pinned": pinned,
            "G": gather(w[pairs[:, 0]] / ws, w[pairs[:, 1]] / ws), "G_loose": gather(0.5, 0.5), "tris": tris, "tri_g": tri_g}


class Cloth:
    def __init__(self, spec):
        self.s = spec
        n = len(spec["rest"])
        self.P = np.zeros((n, 3))
        self.Pp = np.zeros((n, 3))
        self.target_prev = None
        self.loose = False                                    # 죽어서 몸에서 풀려났는가
        self.acc = 0.0

    def targets(self, mats):
        s = self.s
        out = np.empty_like(s["rest"])
        for k, idx in enumerate(s["groups"]):
            M = mats[k]
            out[idx] = s["rest"][idx] @ M[:3, :3].T + M[:3, 3]
        return out

    def reset(self, mats):
        tg = self.targets(mats)
        self.P[:] = tg
        self.Pp[:] = tg
        self.target_prev = tg
        self.loose = False
        self.acc = 0.0

    def shift(self, dx, dz):
        for A in (self.P, self.Pp, self.target_prev):
            if A is not None:
                A[:, 0] += dx
                A[:, 2] += dz

    def step(self, dt, mats, t, gust, center, axis_top):
        s = self.s
        tg = self.targets(mats)
        if self.target_prev is None:
            self.reset(mats)
        self.acc = min(self.acc + dt, H * MAX_STEPS)
        n = int(self.acc / H + 1e-6)
        if n <= 0:
            return
        self.acc -= n * H
        tp = self.target_prev
        tf, ph = s["tf"], s["phase"]
        pin = s["pinned"] & (not self.loose)
        stiff = s["stiff"] * (0.0 if self.loose else 1.0)
        pairs, lens = s["pairs"], s["lens"]
        pi_, pj_ = pairs[:, 0], pairs[:, 1]
        G = s["G_loose"] if self.loose else s["G"]
        for k in range(n):
            tt = t - (n - 1 - k) * H
            T = tp + (tg - tp) * ((k + 1) / n)
            # 흔들림: 아래로 갈수록 세지고, 기둥마다 엇갈린 위상이 아래로 흘러내린다 + 잔 떨림
            a = gust * tf ** 1.3
            wave = tt - tf * 0.9
            acc = np.empty_like(self.P)
            acc[:, 0] = a * (np.sin(2.9 * wave + ph) + 0.35 * np.sin(9.0 * wave + 1.7 * ph))
            acc[:, 1] = a * 0.45 * np.sin(2.3 * wave + 1.3 * ph) + (-14.0 if self.loose else 1.5 * tf - 2.0)
            acc[:, 2] = a * (np.cos(3.4 * wave + 0.7 * ph) + 0.35 * np.cos(8.2 * wave + ph))
            out = self.P[:, [0, 2]] - center                  # 로브는 가끔 바깥으로 부풀었다 가라앉는다
            ln = np.maximum(np.linalg.norm(out, axis=1), 1e-6)
            puff = s["outward"] * gust * 0.5 * tf * (0.55 + 0.45 * np.sin(1.9 * tt + ph))
            acc[:, 0] += out[:, 0] / ln * puff
            acc[:, 2] += out[:, 1] / ln * puff
            vel = self.P - self.Pp
            Pn = self.P + vel * (1.0 - (2.6 if self.loose else 1.4) * H) + acc * (H * H)
            Pn += (T - Pn) * stiff[:, None]
            self.Pp = self.P
            self.P = Pn
            P = self.P
            if pin.any():
                P[pin] = T[pin]
            for _ in range(ITERS):
                d = P[pj_] - P[pi_]
                ln = np.maximum(np.linalg.norm(d, axis=1), 1e-9)
                P += G @ (d * ((ln - lens) / ln)[:, None])
                if pin.any():
                    P[pin] = T[pin]
            # 몸통(허리~가슴)을 뚫고 들어가지 않게, 바닥 밑으로 내려가지 않게
            if not self.loose:
                a0 = np.array([center[0], axis_top[1] - CHEST_UP - 0.1, center[1]])
                ab = np.asarray(axis_top) - a0
                L2 = float(ab @ ab)
                q = np.clip(((P - a0) @ ab) / L2, 0.0, 1.0)
                c = a0 + q[:, None] * ab
                dv = P - c
                dl = np.maximum(np.linalg.norm(dv, axis=1), 1e-9)
                hit = (dl < 0.31) & ~pin
                if hit.any():
                    P[hit] = c[hit] + dv[hit] / dl[hit, None] * 0.31
            low = P[:, 1] < 0.03
            if low.any():
                P[low, 1] = 0.03
                fr = 0.6 if self.loose else 0.2
                self.Pp[low, 0] += (P[low, 0] - self.Pp[low, 0]) * fr
                self.Pp[low, 2] += (P[low, 2] - self.Pp[low, 2]) * fr
        self.target_prev = tg

    def vertices(self):
        s = self.s
        P, tris = self.P, s["tris"]
        fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
        nrm = s["tri_g"] @ fn
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-9)[:, None]
        idx = tris.ravel()
        out = np.zeros((len(idx), 11), dtype="f4")
        out[:, 0:3] = P[idx]
        out[:, 3:6] = nrm[idx]
        out[:, 6:9] = s["col"][idx]
        return out


# ------------------------------------------------------------------ 동작 제어
class ReaperAnim:
    bar_h = 2.65                    # 체력바 높이 (두건 위)
    pick_h = 2.2

    def __init__(self, assets):
        self.a = assets
        self.t = 0.0
        self.px = self.pz = 0.0
        self.yaw = 0.0
        self.vel = [0.0, 0.0]
        self.have_pos = False
        self.lift = 0.0
        self.pose = IDLE_POSE
        self.body = {"lean": 0.0, "twist": 0.0, "hover": 0.0, "pitch": 0.0, "head": 0.0, "roll": 0.0}
        self.act = None                                   # (이름, 시작 시각, 길이, 정보)
        self.last_attack = -9.0
        self.away_until = -1.0                            # 낫을 던져 손에 없는 동안
        self.ghost_until = 0.0                            # E 망령 걸음 중 (반투명)
        self.was_dead = False
        self.dead_clock = 0.0
        self.won = False
        self.cloth = Cloth(assets.cloth_spec) if assets is not None else None
        self.mats = {}
        self.arms = []
        self._frames()

    # ------------------------------------------------------------ 외부 API
    def cast(self, slot):
        if slot == "Q":
            self._start("Q", 0.85)
        elif slot == "W":
            self._start("W", 0.75)
            self.away_until = self.t + 3.0                # 서버가 던졌다고 알려 주면(scythe_throw) 다시 맞춘다
        elif slot == "E":
            self._start("E", 0.45)
        elif slot == "R":
            self._start("R", 1.2, {"delay": 0.8})

    def on_fx(self, kind, ev):
        if kind == "lunge":
            dur = float(ev.get("delay", 0.05)) + float(ev.get("dur", 0.25))
            self._start("E", dur + 0.15)
            self.ghost_until = self.t + dur + 0.05
            if "x2" in ev:
                dx, dz = ev["x2"] - ev["x"], ev["z2"] - ev["z"]
                if math.hypot(dx, dz) > 0.1:
                    self.yaw = math.atan2(dx, dz)
        elif kind == "scythe_throw":
            self.away_until = self.t + 3.0
        elif kind == "scythe_catch":
            self.away_until = self.t
            if not self.act:
                self._start("catch", 0.35)
        elif kind == "reap":
            delay = float(ev.get("dur", 0.8))
            self._start("R", delay + 0.75, {"delay": delay})

    def play_key(self, key):
        if key == "attack":
            self.attack()
        else:
            self.cast(key)
            if key == "W":
                self.away_until = self.t + 1.3            # 미리보기: 던진 낫이 잠시 뒤 돌아온다

    def attack(self, windup=0.0):
        self._start("attack", ATTACK_TIME)
        self.last_attack = self.t

    def win(self):
        self.won = True

    @property
    def corpse_visible(self):
        return self.dead_clock < DEATH_SHOW

    @property
    def alpha(self):
        if self.was_dead:
            return max(0.0, min(1.0, (DEATH_SHOW - self.dead_clock) / DEATH_FADE))
        return 1.0

    def _start(self, name, dur, info=None):
        self.act = (name, self.t, dur, info or {})

    # ------------------------------------------------------------ 동작 곡선
    def _action(self):
        """지금 하는 동작의 (낫 자세, 몸 자세) — 하는 동작이 없으면 None."""
        if not self.act:
            return None
        name, t0, dur, info = self.act
        e = self.t - t0
        if e >= dur:
            self.act = None
            return None
        k = e / dur
        idle = IDLE_POSE
        if name == "attack":                               # 기본 공격: 오른쪽 뒤로 젖혔다가 앞을 가로질러 왼쪽으로 벤다
            wind, cut = 0.38, 0.62
            if k < wind:
                q = _smooth(k / wind)
                return _mix(idle, sweep_pose(1.9, 0.35), q), {"twist": 0.6 * q, "lean": -0.05 * q}
            if k < cut:
                q = _smooth((k - wind) / (cut - wind))
                return sweep_pose(_lerp(1.9, -1.4, q), _lerp(0.35, 0.05, q)), {"twist": _lerp(0.6, -0.55, q), "lean": _lerp(-0.05, 0.18, q)}
            q = _smooth((k - cut) / (1 - cut))
            return _mix(sweep_pose(-1.4, 0.05), idle, q), {"twist": -0.55 * (1 - q), "lean": 0.18 * (1 - q)}
        if name == "Q":                                    # 영혼 베기: 낮게 크게 젖혔다가 몸을 비틀며 반 바퀴 넘게 휩쓴다
            w_end, c_end = 0.2, 0.36
            if e < w_end:
                q = _smooth(e / w_end)
                return _mix(idle, sweep_pose(2.45, 0.12, 0.3, 1.25), q), {"twist": 0.9 * q, "lean": 0.1 * q, "hover": -0.08 * q}
            if e < c_end:
                q = _smooth((e - w_end) / (c_end - w_end))
                return (sweep_pose(_lerp(2.45, -2.5, q), 0.08, 0.32, 1.25),
                        {"twist": _lerp(0.9, -0.9, q), "lean": _lerp(0.1, 0.22, q), "hover": -0.08})
            q = _smooth((e - c_end) / max(0.05, dur - c_end))
            return _mix(sweep_pose(-2.5, 0.08, 0.32, 1.25), idle, q), {"twist": -0.9 * (1 - q), "lean": 0.22 * (1 - q), "hover": -0.08 * (1 - q)}
        if name == "W":                                    # 낫 던지기: 젖혔다가 앞으로 내던진다 (손에서 떠난 뒤엔 빈손)
            rel = 0.22
            if e < rel:
                q = _smooth(e / rel)
                return _mix(idle, sweep_pose(1.75, 0.45, 0.25, 1.45), q), {"twist": 0.7 * q}
            q = _smooth((e - rel) / max(0.05, dur - rel))
            return sweep_pose(_lerp(1.75, -0.6, min(1.0, q * 2.5)), 0.3), {"twist": _lerp(0.7, -0.35, min(1.0, q * 2.5)) * (1 - q), "lean": 0.2 * (1 - q)}
        if name == "E":                                    # 망령 걸음: 몸을 낮게 앞으로 숙이고 낫은 뒤로 끈다
            q = _smooth(min(1.0, e / 0.08)) * (1 - _smooth((k - 0.75) / 0.25))
            return _mix(idle, sweep_pose(2.7, -0.3, 0.25, 1.1), q), {"lean": 0.6 * q, "hover": -0.15 * q, "twist": 0.3 * q, "head": -0.3 * q}
        if name == "catch":
            q = math.sin(PI * k)
            return _mix(idle, sweep_pose(0.4, 0.6, 0.32, 1.5), q), {"lean": -0.08 * q}
        if name == "R":                                    # 사형 선고: 낫을 머리 위로 치켜들었다가 앞으로 내려친다
            delay = info.get("delay", 0.8)
            up = chop_pose(-2.25, 1.62)
            if e < 0.35:
                q = _smooth(e / 0.35)
                return _mix(idle, up, q), {"lean": -0.18 * q, "pitch": -0.2 * q, "head": 0.15 * q, "hover": 0.12 * q}
            chop0 = max(0.36, delay - 0.12)
            if e < chop0:
                shake = 0.03 * math.sin(self.t * 40)
                return chop_pose(-2.25 + shake, 1.62), {"lean": -0.18, "pitch": -0.2, "head": 0.15, "hover": 0.12}
            chop1 = delay + 0.08
            if e < chop1:
                q = _smooth((e - chop0) / (chop1 - chop0))
                return chop_pose(_lerp(-2.25, 0.62, q), _lerp(1.62, 1.35, q)), {"lean": _lerp(-0.18, 0.38, q), "pitch": _lerp(-0.2, 0.25, q),
                                                                               "head": _lerp(0.15, -0.2, q), "hover": _lerp(0.12, -0.12, q)}
            if e < chop1 + 0.25:
                return chop_pose(0.62, 1.35), {"lean": 0.38, "pitch": 0.25, "head": -0.2, "hover": -0.12}
            q = _smooth((e - chop1 - 0.25) / max(0.05, dur - chop1 - 0.25))
            b = {"lean": 0.38, "pitch": 0.25, "head": -0.2, "hover": -0.12}
            return _mix(chop_pose(0.62, 1.35), idle, q), {k_: v * (1 - q) for k_, v in b.items()}
        return None

    # ------------------------------------------------------------ 매 프레임
    def update(self, dt, d, ent=None):
        dt = min(dt, 0.12)
        self.t += dt
        d = d or {}
        st = d.get("st", ())
        dead = bool(d.get("dead"))
        if ent is not None:
            self._track(dt, ent)
        spd = math.hypot(self.vel[0], self.vel[1])
        mv = min(1.0, spd / 4.5)
        if dead:
            if not self.was_dead:
                self.was_dead = True
                self.dead_clock = 0.0
                self.act = None
            self.dead_clock += dt
            if self.dead_clock > 0.3 and self.cloth and not self.cloth.loose:
                self.cloth.loose = True                   # 붙들던 몸이 사라져 천이 무너진다
            self.pose = _mix(self.pose, DEAD_POSE, 1 - math.exp(-6 * dt))
            self._frames()
            self._step_cloth(dt, 2.0)
            return
        if self.was_dead:                                   # 부활: 천을 새 자리에 다시 입힌다
            self.was_dead = False
            self.dead_clock = 0.0
            self.won = False
            self.away_until = -1.0
            self.pose = IDLE_POSE
            self._frames()
            if self.cloth:
                self.cloth.reset(self._cloth_mats())
        if d.get("a", 0) == 2 and self.t - self.last_attack > 0.55 and not self.act:
            self.attack()
        act = self._action()
        body = {"lean": 0.0, "twist": 0.0, "hover": 0.0, "pitch": 0.0, "head": 0.0, "roll": 0.0}
        if act:
            tgt_pose, b = act
            body.update(b)
            rate = 40.0
        else:
            rate = 9.0
            if "stun" in st or "air" in st:
                tgt_pose = STUN_POSE
                body.update(lean=0.25, head=-0.45, hover=-0.2)
            elif self.won:
                tgt_pose = WIN_POSE
                body.update(lean=-0.15, head=0.25, hover=0.15)
            elif d.get("rc", 0) > 0:
                tgt_pose = RECALL_POSE
                body.update(hover=-0.3, head=-0.25, lean=0.05)
            else:
                tgt_pose = _mix(IDLE_POSE, MOVE_POSE, mv)
                sway = math.sin(self.t * 2.2)
                body.update(lean=0.25 * mv, roll=0.03 * sway * mv, head=-0.05 * mv)
        k = 1 - math.exp(-rate * dt)
        self.pose = _mix(self.pose, tgt_pose, k)
        kb = 1 - math.exp(-(22.0 if act else 7.0) * dt)
        for key in self.body:
            self.body[key] += (body[key] - self.body[key]) * kb
        self._frames()
        self._step_cloth(dt, 5.5 + 9.0 * mv + (6.0 if self.t < self.ghost_until else 0.0))

    def _track(self, dt, ent):
        x, z = ent.x / SC, ent.z / SC
        face = facing_to_rot(ent.f)
        if not self.have_pos:
            self.have_pos = True
            self.px, self.pz, self.yaw = x, z, face
            self._frames()
            if self.cloth:
                self.cloth.reset(self._cloth_mats())
            return
        mx, mz = x - self.px, z - self.pz
        if math.hypot(mx, mz) > 6.0 / SC:                   # 순간이동 (귀환·점멸·부활): 천도 그대로 옮긴다
            self.px, self.pz, self.vel = x, z, [0.0, 0.0]
            if self.cloth:
                self.cloth.shift(mx, mz)
        else:
            k = 1 - math.exp(-10 * dt)
            vx, vz = (mx / dt, mz / dt) if dt > 1e-6 else (0.0, 0.0)
            self.vel[0] += (vx - self.vel[0]) * k
            self.vel[1] += (vz - self.vel[1]) * k
            self.px, self.pz = x, z
        if not (self.act and self.act[0] == "E"):
            self.yaw += _wrap(face - self.yaw) * (1 - math.exp(-12 * dt))

    # ------------------------------------------------------------ 뼈대 계산
    def _frames(self):
        b = self.body
        bob = 0.06 * math.sin(self.t * 2.1)
        hover = WAIST_Y + b["hover"] + bob
        sink = 1.0
        if self.was_dead:                                   # 죽음: 허리가 바닥까지 꺼지며 몸이 로브 속으로 사라진다
            q = _smooth(self.dead_clock / 0.55)
            hover = _lerp(WAIST_Y, 0.25, q)
            sink = 1.0 - _smooth((self.dead_clock - 0.1) / 0.5)
        root = _T(self.px, 0.0, self.pz) @ _Ry(self.yaw)
        M_body = root @ _T(0, hover, 0) @ _Ry(b["twist"] * 0.35) @ _Rx(b["lean"]) @ _Rz(b["roll"])
        M_chest = M_body @ _T(0, CHEST_UP, 0) @ _Ry(b["twist"] * 0.55) @ _Rx(b["pitch"])
        M_head = M_chest @ _T(*HEAD_AT) @ _Ry(-b["twist"] * 0.4) @ _Rx(-b["head"])
        M_hold = root @ _T(0, hover - WAIST_Y, 0) @ _Rx(b["lean"] * 0.4)
        g, u, bl = self.pose
        x_ = _n(np.cross(u, bl))
        S = np.eye(4)
        S[:3, 0], S[:3, 1], S[:3, 2], S[:3, 3] = x_, u, bl, g
        M_scy = M_hold @ S
        self.mats = {"root": root, "body": M_body, "chest": M_chest, "head": M_head, "scythe": M_scy, "sink": sink}
        # 팔: 어깨에서 낫의 손잡이(또는 빈손 자리)로 2본 IK
        holding = self.t >= self.away_until
        shoulders = [(M_chest @ np.array([side * SHOULDER[0], SHOULDER[1], 0.0, 1.0]))[:3] for side in (1, -1)]
        sway = 0.04 * math.sin(self.t * 2.2)
        free_l = (M_hold @ np.array([-0.5, 1.12 + sway, 0.3, 1.0]))[:3]          # 빈 왼손: 몸 옆으로 살짝 띄워 늘어뜨린다
        if holding:
            hands = [(M_scy @ np.array([0.0, 0.0, 0.0, 1.0]))[:3], (M_scy @ np.array([0.0, GRIP2, 0.0, 1.0]))[:3]]
            # 크게 휘두르느라 왼팔이 자루에 닿지 않으면 왼손은 놓고 몸 옆으로 (늘어나거나 몸을 뚫지 않게)
            far = float(np.linalg.norm(hands[1] - shoulders[1])) - (UPPER + FORE) * 0.97
            w = _smooth(1.0 - far / 0.12)
            self.two = w if not hasattr(self, "two") else self.two + (w - self.two) * 0.35
            hands[1] = free_l + (hands[1] - free_l) * self.two
        else:
            reach = 0.4 if (self.act and self.act[0] == "W") else 0.0
            hands = [(M_hold @ np.array([0.45, 1.25 + reach * 0.4, 0.45 + reach, 1.0]))[:3],
                     (M_hold @ np.array([-0.45, 1.2 + reach * 0.3, 0.42 + reach * 0.8, 1.0]))[:3]]
        self.arms = []
        for side, sh, hand in zip((1, -1), shoulders, hands):
            pole = (root[:3, :3] @ np.array([side * 1.0, -0.45, -0.35]))      # 팔꿈치는 바깥 뒤로
            elbow, end = _two_bone(sh, hand, pole)
            self.arms.append((sh, elbow, hand))

    def _cloth_mats(self):
        m = self.mats
        wr = []
        for sh, el, hd in self.arms:
            y = _n(hd - el)
            ref = np.array([0.0, 1.0, 0.0]) if abs(y[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
            x = _n(np.cross(y, ref))
            z = np.cross(x, y)
            W = np.eye(4)
            W[:3, 0], W[:3, 1], W[:3, 2] = x, y, z
            W[:3, 3] = el + (hd - el) * 0.62
            wr.append(W)
        return [m["body"], m["chest"], wr[0], wr[1]]

    def _step_cloth(self, dt, gust):
        if not self.cloth:
            return
        if dt > 0.06 and not self.was_dead:                 # 화면 밖이라 몰아서 갱신할 때는 풀지 않고 제자리 모양으로 둔다
            self.cloth.reset(self._cloth_mats())
            return
        top = (self.mats["chest"] @ np.array([0.0, 0.15, 0.0, 1.0]))[:3]
        self.cloth.step(dt, self._cloth_mats(), self.t, gust, np.array([self.px, self.pz]), top)

    # ------------------------------------------------------------ 그리기
    def draw(self, r, tint=(1, 1, 1, 1), emis=(0, 0, 0)):
        a = self.a
        alpha = tint[3] if len(tint) > 3 else 1.0
        if self.t < self.ghost_until:
            alpha *= 0.55
        col = (tint[0], tint[1], tint[2], alpha)
        e = (emis[0] + 0.03, emis[1] + 0.02, emis[2] + 0.05)
        m = self.mats
        sink = m["sink"]
        prog = r.prog
        prog["u_dbl"].value = True
        if self.cloth:
            v = self.cloth.vertices()
            a.cloth.parts[0][1].write(v.tobytes())
            r.draw(a.cloth, _SCALE, tint=col, emissive=e)
        if sink > 0.01:
            shrink = _S(sink)
            r.draw(a.torso, _SCALE @ m["body"] @ shrink, tint=col, emissive=e)
            r.draw(a.chest, _SCALE @ m["chest"] @ shrink, tint=col, emissive=e)
            Mh = _SCALE @ m["head"] @ shrink
            r.draw(a.hood, Mh, tint=col, emissive=e)
            r.draw(a.inner, Mh, tint=(0, 0, 0, alpha), unlit=1.0)
            for sh, el, hd in self.arms:
                c0 = m["body"][:3, 3]
                sh_, el_, hd_ = (c0 + (p - c0) * sink for p in (sh, el, hd))
                r.draw(a.upper, _SCALE @ _seg(sh_, el_, 0.1 * sink), tint=col, emissive=e)
                r.draw(a.elbow, _SCALE @ _T(*el_) @ _S(0.088 * sink), tint=col, emissive=e)
                r.draw(a.fore, _SCALE @ _seg(el_, hd_, 0.1 * sink), tint=col, emissive=e)
                r.draw(a.hand, _SCALE @ _T(*hd_) @ _S(sink), tint=col, emissive=e)
        prog["u_dbl"].value = False
        if self.t >= self.away_until or self.was_dead:
            M = _SCALE @ m["scythe"]
            r.draw(a.shaft, M, tint=col, emissive=e)
            r.draw(a.blade, M, tint=col, emissive=(e[0] + 0.05, e[1] + 0.06, e[2] + 0.1))
            ec = self._edge_color()
            r.draw(a.edge, M, tint=(ec[0], ec[1], ec[2], alpha), unlit=1.0)

    def _edge_color(self):
        """날끝 빛: 천천히 숨 쉬듯 밝아졌다 어두워지고, 죽으면 꺼진다."""
        if self.was_dead:
            k = max(0.0, 1.0 - self.dead_clock / 0.6)
        else:
            k = (1.15 + 0.35 * math.sin(self.t * 3.0)) * (0.8 + 0.2 * math.sin(self.t * 5.0 + 1.0))
        return (SOUL[0] * k, SOUL[1] * k, SOUL[2] * k)


def _seg(a, b, th):
    d = np.asarray(b) - np.asarray(a)
    ln = float(np.linalg.norm(d))
    if ln < 1e-5:
        return _T(*a) @ _S(th, 1e-4, th)
    return _T(*a) @ _from_to((0, 1, 0), d / ln) @ _S(th, ln, th)


def _two_bone(root, target, pole_hint, l1=UPPER, l2=FORE):
    root = np.asarray(root, float)
    d = np.asarray(target, float) - root
    dl = float(np.linalg.norm(d))
    if dl < 1e-5:
        d, dl = np.array([0.0, -1.0, 0.0]), 1e-5
    else:
        d = d / dl
    dc = min(l1 + l2 - 0.01, max(abs(l1 - l2) + 0.01, dl))
    cos_a = (l1 * l1 + dc * dc - l2 * l2) / (2 * l1 * dc)
    sin_a = math.sqrt(max(0.0, 1 - cos_a * cos_a))
    pole = np.asarray(pole_hint, float) - d * float(np.dot(pole_hint, d))
    if float(np.dot(pole, pole)) < 1e-6:
        pole = np.array([0.0, -1.0, 0.0]) - d * d[1]
    pole /= max(1e-9, float(np.linalg.norm(pole)))
    return root + d * (l1 * cos_a) + pole * (l1 * sin_a), root + d * dc
