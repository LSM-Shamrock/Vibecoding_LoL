"""겁화의 용 — 보스러시(DEEP NEST) 3층 보스의 절차적 리그를 이 게임으로 옮긴 것.

원본: bosses/dragon/rig.py + legs.py. 원본은 하늘을 나는 보스라서 몸통이 머리가 지나간 3D 궤적을 따라가지만, 이 게임은 땅 위의 MOBA 라서
  · 몸통: 가슴(챔피언 위치)이 지나간 땅 위의 길(궤적)을 몸통 마디들이 따라오고, 앞쪽은 가슴에서 머리까지 완만한 S 자로 솟는 목이다.
          서 있을 때는 몸이 머리가 보는 방향으로 천천히 돌아서고, 꼬리는 좌우 · 상하로 일렁인다.
  · 다리 4개: 원본의 거미식 IK + 발걸음 (대각선 두 다리씩 한 조). 발이 땅에 고정됐다가 몸이 멀어지면 호를 그리며 옮겨 디딘다.
  · 날개: 어깨 → 팔꿈치 → 손목 → 손가락뼈 4개 + 날개막 (부챗살 격자). 평소엔 접어 두고, 시전할 때 활짝 펴 퍼덕이거나 휘두른다.
  · 머리: 두개골 · 뿔 · 갈기 · 귀지느러미 · 수염 · 아래턱 · 입속 불빛. 등 가시, 꼬리 칼날, 가슴 · 이마의 보석.
모든 계산은 원본과 같은 "보스 단위"로 하고 마지막에 SC 배로 줄여 그린다. 이 게임의 렌더러는 scene graph 가 없어서 부품마다 메시를 만들어 두고
매 프레임 행렬만 계산해 그린다 (몸통 관과 날개막은 정점 버퍼를 매 프레임 다시 쓴다).

챔피언 동작 연결 (SerpentAnim 과 같은 모양):
  update(dt, d, ent)   서버 상태(d)와 화면 위치(ent.x, ent.z, ent.f)로 몸을 갱신
  cast(slot)           스킬 시전 시작 (Q 불 뱉기 / W 날갯짓 돌풍 / E 날개 휘두르기 / R 유성우)
  draw(r, tint, emis)  그리기
죽으면 머리 · 몸 조각이 흩어진다.
"""
import math
import random

import numpy as np

from ..geometry import MeshBuilder
from ..gl import Mesh, facing_to_rot
from .spider import _S, _T, _Rx, _Ry, _euler, _from_to, _wrap, heavy_chain
from . import dragon_assets as A
from . import BIG_SCALE, CHAMP_SCALE, DEATH_FADE, DEATH_SHOW

PI = math.pi
TAU = PI * 2
SC = 0.075 * CHAMP_SCALE * BIG_SCALE      # 보스 단위 -> 이 게임 단위

# ───────────────────────── 치수 (원본과 같은 이름) ─────────────────────────
FULL_LEN = 112.0                # 꼬리를 줄이기 전의 몸 길이 (마디 위치 · 굵기 비율의 기준)
DS = 0.8                        # 마디 간격
NR_FULL = int(math.floor(FULL_LEN / DS)) + 1
TAIL_K = 0.6                    # 꼬리 길이 배율 (처음의 0.6 = 절반의 1.2배)
M = A.M
VW = A.VW
PLATE = A.PLATE
TS = 0.4                        # 궤적 점 간격
RS = 1.5                        # 몸통 굵기 배율
HS = 2.0                        # 머리 배율
WS = 2.5                        # 날개 배율
ARM = [4.8, 6.6]
FING = [13.0, 11.8, 9.6, 7.4]


def _at(u):
    return int(math.floor(u * (NR_FULL - 1) + 0.5))


IW = _at(0.18)                  # 날개가 붙는 마디
IH = _at(0.434)                 # 날개막 뒤쪽이 붙는 마디
IFL = _at(0.229)                # 앞다리
IHL = _at(0.37)                 # 뒷다리
KC = (IFL + IHL) // 2           # 챔피언 위치(가슴 한가운데)에 놓이는 마디
TAIL_TURN0 = 14.0               # 가슴 바로 뒤 마디가 지나온 길의 방향으로 돌아서는 빠르기 (1/초)
TAIL_TURN1 = 4.0                # ... 꼬리 끝은 이만큼 (낮을수록 빙빙 돌 때 꼬리가 늦게 돈다)
BODY_BEND = math.radians(2.2)   # 가슴~뒷다리 몸통이 마디 하나에서 꺾일 수 있는 최대 각도 (작을수록 확 꺾이지 않는다)
TAIL_BEND = math.radians(5.0)   # 꼬리는 이만큼까지 (몸통보다 부드럽게 휜다)
NR = IHL + int(round((NR_FULL - 1 - IHL) * TAIL_K)) + 1       # 뒷다리 뒤의 꼬리만 TAIL_K 배로 줄인다
_BENDS = np.where(np.arange(NR - 1) < IHL, BODY_BEND, TAIL_BEND)       # 마디 사이(k -> k+1)마다 꺾일 수 있는 최대 각도
BODY_LEN = (NR - 1) * DS
CAP = int(math.ceil((BODY_LEN + 30) / TS))

BODY_H = 16.0                   # 서 있을 때 몸통 중심 높이
TAIL_END_H = 3.2                # 꼬리 끝 높이
LEG_STEP = 4.2                  # 발이 이만큼 홈에서 멀어지면 한 걸음
EXT_SPAN = 26                   # 목을 앞으로 뻗을 때 머리에서 이 마디 수만큼 뒤까지 끌려온다


def _clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _smooth(k):
    c = min(1.0, max(0.0, k))
    return c * c * (3 - 2 * c)


def _smooth_np(k):
    c = np.clip(k, 0.0, 1.0)
    return c * c * (3 - 2 * c)


def _lerp(a, b, k):
    return a + (b - a) * k


def _radius_at(s):
    """마디 반지름: 가는 목 → 두툼한 가슴 → 허리 → 길게 가늘어지는 꼬리"""
    s0 = IHL * DS
    if s > s0:                                                  # 줄어든 꼬리도 원래 꼬리와 같은 모양으로 가늘어진다
        s = s0 + (s - s0) / TAIL_K
    u = s / FULL_LEN
    if u < 0.22:
        r = 1.15 + 1.0 * _smooth(u / 0.22)
    elif u < 0.56:
        r = 2.15 - 0.55 * _smooth((u - 0.22) / 0.34)
    else:
        k = (u - 0.56) / 0.44
        r = 1.6 * math.pow(max(0.0, 1 - k), 1.15) + 0.08
    return r * RS


FADE_NECK = 28
FADE_TAIL = 20
BULK = np.zeros(NR)
for _i in range(NR):
    _up = 1.0 if _i >= IFL else _smooth((_i - (IFL - FADE_NECK)) / FADE_NECK)
    _down = 1.0 if _i <= IHL else 1 - _smooth((_i - IHL) / FADE_TAIL)
    BULK[_i] = min(_up, _down)
THICK = 0.45
WIDER = 0.35
R_BULK = _radius_at(IFL * DS) * (1 + THICK)
RAD = np.array([_radius_at(i * DS) * (1 - BULK[i]) + R_BULK * BULK[i] for i in range(NR)])
RADL = RAD.tolist()
_SK = np.arange(NR) * DS
_KK = np.arange(NR)

# 정점 각도 상수
_AJ = ((np.arange(VW) + 0.5) / M) * TAU
_COSA, _SINA = np.cos(_AJ), np.sin(_AJ)
_PK = (np.arange(NR) % PLATE) / PLATE
_LAM = np.where(_PK == 0, 0.86, 0.97 + 0.13 * _PK)
_TOPK = 1 + 0.2 * (np.maximum(0.0, _SINA[None, :] - 0.4) * np.where(_PK < 0.6, 1.0, 0.7)[:, None])
_SPI = 4 + np.arange((NR - 8) // PLATE) * PLATE + 2
_SPSZ = np.array([0.8 + i * 0.05 if i < 14 else _clamp(RADL[i] * 0.6 + 0.4, 0.6, 2.7) for i in _SPI]) * 0.8

# ───────────────────────── 자세 ─────────────────────────
# neck: 머리 높이 / body: 몸통 높이 가감 / pitch: 고개 숙임(+ 아래) / jaw 입 / fire 입속 불빛 / ext: 머리를 앞으로 뻗는 거리
# wsw/wsp/wel: 날개를 지정한 각도로 휘두르기 (섞는 정도 / 뒤로 젖힌 각 (음수 = 앞으로) / 위로 든 각)
# und: 꼬리 일렁임 / wfold: 날개 접힘(1 = 몸에 붙임) / whz,wamp: 날갯짓 횟수·진폭 / wraise: 날개 들림 / wspread: 손가락 벌림 / swing: 휘두르기
IDLE = {'neck': 41.0, 'body': 0.0, 'pitch': 0.3, 'jaw': 0.0, 'fire': 0.0, 'ext': 0.0, 'und': 0.5, 'wfold': 0.8, 'whz': 0.0, 'wamp': 0.0,
        'wraise': 0.8, 'wspread': 1.0, 'swing': 0.0, 'wsw': 0.0, 'wsp': 0.0, 'wel': 0.0}
POSES = {
    'idle': {},
    'move': {'neck': 39.0, 'pitch': 0.32, 'und': 0.95},
    'wind': {'neck': 33.0, 'pitch': -0.4, 'jaw': 0.55, 'fire': 0.8, 'wfold': 0.55, 'whz': 1.3, 'wamp': 0.25, 'wraise': 0.3, 'und': 0.3},   # Q 준비: 고개를 치켜든다
    'spit': {'neck': 30.5, 'pitch': 0.08, 'jaw': 1.0, 'fire': 1.0, 'ext': 4.5, 'wfold': 0.55, 'wamp': 0.2, 'whz': 1.0, 'wraise': 0.3, 'und': 0.3},
    'gustwind': {'neck': 31.0, 'pitch': -0.25, 'jaw': 0.3, 'body': 1.5, 'wfold': 0.0, 'wraise': 0.5, 'wamp': 0.0, 'whz': 0.0, 'wspread': 1.0,
                 'wsw': 1.0, 'wsp': 0.35, 'wel': 1.45, 'und': 0.3},                                            # W 준비: 날개를 머리 위로 높이 치켜든다
    'gust': {'neck': 24.0, 'pitch': 0.3, 'jaw': 0.5, 'body': -1.5, 'ext': 3.0, 'wfold': 0.0, 'wamp': 0.0, 'whz': 0.0, 'wspread': 1.0,
             'wsw': 1.0, 'wsp': -0.85, 'wel': -0.35, 'und': 0.3},                                               # W: 앞으로 크게 휘둘러 내리친다
    'sweepwind': {'neck': 24.0, 'pitch': 0.25, 'jaw': 0.3, 'wfold': 0.0, 'whz': 0.5, 'wamp': 0.3, 'wraise': 0.5, 'und': 0.3},              # E 준비
    'sweep': {'neck': 25.0, 'pitch': 0.3, 'jaw': 0.5, 'wfold': 0.0, 'swing': 1.0, 'whz': 0.9, 'wamp': 0.6, 'und': 0.3},
    'skyrise': {'neck': 38.0, 'pitch': -0.6, 'jaw': 0.7, 'fire': 0.6, 'body': 2.0, 'wfold': 0.0, 'whz': 2.6, 'wamp': 1.0, 'wraise': 0.35, 'und': 0.3},   # R: 하늘로 솟구친다
    'skycruise': {'neck': 22.0, 'pitch': 0.8, 'jaw': 1.0, 'fire': 1.0, 'ext': 3.0, 'wfold': 0.0, 'whz': 2.0, 'wamp': 0.8, 'wraise': 0.3, 'und': 0.2},   # R: 높이 뜬 채 아래로 불을 쏟으며 날아간다
    'skyland': {'neck': 30.0, 'pitch': 0.15, 'jaw': 0.8, 'fire': 0.8, 'body': -3.0, 'wfold': 0.0, 'whz': 0.7, 'wamp': 0.45, 'wraise': 0.6, 'und': 0.3},
    'puffwind': {'neck': 29.0, 'pitch': -0.12, 'jaw': 0.5, 'fire': 0.7, 'wfold': 0.8, 'und': 0.4},              # 평타: 입에 불씨가 모인다
    'puff': {'neck': 28.0, 'pitch': 0.05, 'jaw': 0.9, 'fire': 1.0, 'ext': 2.5, 'wfold': 0.8, 'und': 0.4},          # 평타: 작은 불꽃을 뱉는다
    'roar': {'neck': 36.0, 'pitch': -0.6, 'jaw': 1.0, 'fire': 1.0, 'body': 1.8, 'wfold': 0.0, 'whz': 0.8, 'wamp': 0.35, 'wraise': 0.6, 'und': 0.3},
    'bite': {'neck': 22.0, 'pitch': 0.45, 'jaw': 1.0, 'ext': 9.0, 'wfold': 0.9, 'und': 0.4},
    'snap': {'neck': 18.0, 'pitch': 0.7, 'jaw': 0.05, 'ext': 14.0, 'wfold': 0.9, 'und': 0.4},
    'stagger': {'neck': 17.0, 'pitch': 0.55, 'jaw': 0.45, 'body': -4.5, 'wfold': 0.75, 'wraise': -0.4, 'und': 0.2},
    'win': {'neck': 34.0, 'pitch': -0.5, 'jaw': 0.6, 'fire': 0.6, 'wfold': 0.0, 'whz': 0.7, 'wamp': 0.3, 'wraise': 0.55, 'und': 0.3},
}
RATES = {'neck': 5.0, 'body': 5.0, 'pitch': 7.0, 'jaw': 12.0, 'fire': 6.0, 'ext': 14.0, 'und': 2.5, 'wfold': 5.0, 'whz': 3.0, 'wamp': 4.0,
         'wraise': 6.0, 'wspread': 4.0, 'swing': 6.0, 'wsw': 8.0, 'wsp': 8.0, 'wel': 8.0}
FAST = {'bite': {'jaw': 26, 'neck': 18, 'pitch': 18, 'ext': 26}, 'snap': {'jaw': 40, 'neck': 24, 'pitch': 22, 'ext': 34},
        'spit': {'jaw': 20, 'neck': 14, 'pitch': 14}, 'gust': {'wsw': 18, 'wsp': 16, 'wel': 16, 'neck': 14, 'pitch': 14, 'ext': 18, 'body': 12}, 'gustwind': {'wsw': 14, 'wsp': 12, 'wel': 12, 'wfold': 14, 'wraise': 12},
        'skycruise': {'neck': 10, 'pitch': 10, 'jaw': 16, 'fire': 12, 'ext': 10}, 'puff': {'jaw': 30, 'neck': 20, 'pitch': 20, 'ext': 24}, 'puffwind': {'jaw': 20, 'neck': 14}, 'sweep': {'swing': 9.0, 'wfold': 9.0},
        'roar': {'jaw': 14, 'neck': 7}}
ATTACK_TIME = 0.34


# ───────────────────────── 보조 ─────────────────────────
def _basis(xa, ya, za, pos):
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = xa, ya, za, pos
    return m


def _unit(v):
    l = np.sqrt((v * v).sum(axis=-1, keepdims=True))
    return v / np.maximum(l, 1e-12), l[..., 0]


def _seg_mats(d, sx, sy, sz, pos):
    """+Y 를 방향 d(단위벡터)로 돌리는 최소 회전에 (sx, sy, sz) 배율을 곱한 행렬들 (n,4,4)."""
    n = len(d)
    vx, vz, c = d[:, 2], -d[:, 0], d[:, 1]
    k = 1.0 / np.maximum(1.0 + c, 1e-6)
    xa = np.stack([1 - vz * vz * k, vz, vx * vz * k], axis=1)
    ya = d
    za = np.stack([vx * vz * k, -vx, 1 - vx * vx * k], axis=1)
    flip = c < -0.9999
    if flip.any():
        xa = xa.copy()
        ya = ya.copy()
        za = za.copy()
        xa[flip] = (1, 0, 0)
        ya[flip] = (0, -1, 0)
        za[flip] = (0, 0, -1)
    out = np.zeros((n, 4, 4))
    out[:, :3, 0] = xa * np.asarray(sx)[:, None]
    out[:, :3, 1] = ya * np.asarray(sy)[:, None]
    out[:, :3, 2] = za * np.asarray(sz)[:, None]
    out[:, :3, 3] = pos
    out[:, 3, 3] = 1.0
    return out


def _solve_two_bone(hip, target, l1, l2, pole):
    d = target - hip
    dist = float(np.linalg.norm(d))
    if dist < 1e-5:
        d, dist = np.array([0.0, -1.0, 0.0]), 1e-5
    else:
        d = d / dist
    dc = min(l1 + l2 - 0.02, max(abs(l1 - l2) + 0.02, dist))
    cos_a = (l1 * l1 + dc * dc - l2 * l2) / (2 * l1 * dc)
    sin_a = math.sqrt(max(0.0, 1 - cos_a * cos_a))
    p = pole - d * float(pole @ d)
    if float(p @ p) < 1e-6:
        p = np.array([1.0, 0.0, 0.0])
        p = p - d * float(d[0])
    p = p / max(1e-9, float(np.linalg.norm(p)))
    return hip + d * (l1 * cos_a) + p * (l1 * sin_a), hip + d * dc


def _stroke(ph):
    """날갯짓 곡선: 아래로 빠르게 내리치고(전체의 40%) 위로는 느리게 들어올린다. +1 = 위 끝, -1 = 아래 끝"""
    p = ph - math.floor(ph)
    D = 0.4
    if p < D:
        x = p / D
        return 1 - 2 * (1 - (1 - x) * (1 - x))
    x = (p - D) / (1 - D)
    return -1 + 2 * (x * x * (3 - 2 * x))


# ───────────────────────── 다리 (원본 legs.py) ─────────────────────────
KL, KT, KS, LEG_S, LEN_K = 4.5, 16.0, 8.0, 0.75, 1.25
L2 = 2.6 * KL * LEG_S * LEN_K
L1 = L2 * 0.8                   # 허벅지는 종아리보다 길어 보이지 않도록 조금 짧게
UP_T = 0.24 * KT * LEG_S
LO_T = 0.23 * KT * LEG_S
KNEE_R = KS * LEG_S * 0.4
GROUPS = [0, 1, 1, 0]
SIDE = [1, -1, 1, -1]
FORE = [True, True, False, False]
TURN = PI / 4
HIND_IN = 30 * PI / 180
HOME_ANGLE = [0.5 + TURN, 0.5 + TURN, -0.35 + TURN + HIND_IN, -0.35 + TURN + HIND_IN]
HOME_R = 9 * 1.25
FOOT_Y = 0.9


class _Gait:
    """발걸음: 발은 월드에 고정됐다가 홈에서 멀어지면 호를 그리며 새로 디딘다 (원본 procedural/gait)."""

    def __init__(self, count, groups):
        self.n, self.groups = count, groups
        self.feet = np.zeros((count, 3))
        self.frm = np.zeros((count, 3))
        self.to = np.zeros((count, 3))
        self.t = [0.0] * count
        self.dur = [0.2] * count
        self.stepping = [False] * count
        self.lift_now = [0.0] * count

    def snap(self, homes):
        self.feet[:] = homes
        self.stepping = [False] * self.n
        self.lift_now = [0.0] * self.n

    def update(self, dt, homes, vel, threshold, step_time, lift, lead):
        for i in range(self.n):
            if not self.stepping[i]:
                continue
            self.t[i] += dt / self.dur[i]
            k = min(1.0, self.t[i])
            e = k * k * (3 - 2 * k)
            self.feet[i] = self.frm[i] + (self.to[i] - self.frm[i]) * e
            if k >= 1:
                self.stepping[i] = False
                self.feet[i] = self.to[i]
        for i in range(self.n):
            if self.stepping[i]:
                continue
            d = math.hypot(self.feet[i][0] - homes[i][0], self.feet[i][2] - homes[i][2])
            if d <= threshold:
                continue
            blocked = any(self.stepping[j] and self.groups[j] != self.groups[i] for j in range(self.n))
            if blocked and d < threshold * 2.4:
                continue
            self.frm[i] = self.feet[i]
            self.to[i] = (homes[i][0] + vel[0] * lead, homes[i][1], homes[i][2] + vel[1] * lead)
            self.t[i] = 0.0
            self.dur[i] = step_time
            self.stepping[i] = True
            self.lift_now[i] = lift

    def get(self, i):
        f = self.feet[i].copy()
        if self.stepping[i]:
            f[1] += math.sin(PI * min(1.0, self.t[i])) * self.lift_now[i]
        return f


# ───────────────────────── 날개막 조각 ─────────────────────────
class _Panel:
    pass


def _make_panel(assets, K, N):
    nv = 1 + K * N
    uv = np.zeros((nv, 2), dtype=np.float32)
    uv[0] = (0.5, 0)
    rr, kk = np.meshgrid(np.arange(1, N + 1), np.arange(K), indexing='ij')
    v = (1 + (rr - 1) * K + kk).ravel()
    uv[v, 0] = (kk / K).ravel()
    uv[v, 1] = (rr / N).ravel()
    idx = []
    for k in range(K):
        idx += [0, 1 + k, 1 + ((k + 1) % K)]
    for r_ in range(1, N):
        for k in range(K):
            a0 = 1 + (r_ - 1) * K + k
            a1 = 1 + (r_ - 1) * K + ((k + 1) % K)
            b0 = a0 + K
            b1 = a1 + K
            idx += [a0, b0, a1, a1, b0, b1]
    p = _Panel()
    p.K, p.N = K, N
    p.idx = np.array(idx, dtype=np.int64)
    tmpl = np.zeros((len(idx), 11), dtype="f4")
    tmpl[:, 6:9] = 1.0
    tmpl[:, 9:11] = uv[p.idx]
    p.buf = tmpl
    p.mesh = Mesh(assets.r, [(tmpl.copy(), assets.mem_tex)])
    p.pos = np.zeros((nv, 3))
    p.bnd = np.zeros((K, 3))
    p.fr = (np.arange(1, N + 1) / N)[:, None]
    p.kk = np.arange(K)[None, :]
    p.lift = p.fr * (1.2 - 0.5 * p.fr)
    p.arg0 = p.fr * 8 + p.kk * 0.9
    p.fco = p.fr
    return p


def _build_wing_specs(assets):
    panels = [_make_panel(assets, K, N) for K, N in ((14, 5), (14, 5), (14, 5), (20, 6), (9, 2))]
    MID = 12
    specs = []
    for pi in range(3):
        specs.append(([(2, MID + pi, 2, -1), (MID + pi, 3 + pi, 2, -1), (3 + pi, 4 + pi, 6, 2), (4 + pi, MID + pi + 1, 2, -1), (MID + pi + 1, 2, 2, -1)], 1.0))
    specs.append(([(0, 1, 3, -1), (1, 2, 3, -1), (2, MID + 3, 2, -1), (MID + 3, 6, 2, -1), (6, 10, 7, 2), (10, 0, 3, -1)], 1.1))
    specs.append(([(0, 1, 3, -1), (1, 2, 3, -1), (2, 0, 3, -1)], 1.0))
    for pn, (segs, bk) in zip(panels, specs):
        ia, ib, tt, bi, bs_ = [], [], [], [], []
        for a_, b_, n_, bt in segs:
            for k in range(n_):
                t_ = k / n_
                ia.append(a_)
                ib.append(b_)
                tt.append(t_)
                bi.append(max(bt, 0))
                bs_.append(math.sin(PI * t_) * bk if bt >= 0 else 0.0)
        assert len(ia) == pn.K
        pn.spec = (np.array(ia), np.array(ib), np.array(tt)[:, None], np.array(bi), np.array(bs_)[:, None])
    return panels


class _Debris:
    __slots__ = ("mesh", "base", "pos", "ang", "vel", "spin", "tint", "unlit", "rest", "r", "col")


# ───────────────────────── 본체 ─────────────────────────
class DragonAnim:
    @property
    def bar_h(self):                                            # 게임 장면이 체력바를 달 높이 (날아오르면 따라 오른다)
        return 2.75 * CHAMP_SCALE * BIG_SCALE + 0.2 + self.air * SC

    pick_h = 1.5 * CHAMP_SCALE * BIG_SCALE                                               # 마우스로 고를 수 있는 높이
    preview_dist = 12.0                                         # 챔피언 선택 화면 카메라 거리 (몸이 길어서 멀리서)

    def __init__(self, assets):
        self.a = assets
        self.panels = [_build_wing_specs(assets) for _ in range(2)]
        self.t = 0.0
        self.yaw = 0.0
        self.byaw = 0.0                                         # 몸이 따르는 방향 (머리 방향을 천천히 따라간다)
        self.px = self.pz = 0.0
        self.vel = [0.0, 0.0]
        self.speed = 0.0
        self.lift = 0.0
        self.have_pos = False
        self.dt_last = 1.0
        self.moving = False
        self.still_t = 0.0
        self.cur = dict(IDLE)
        self.tgt = dict(IDLE)
        self.rate = dict(RATES)
        self.seq = []
        self.seq_end = 0.0
        self.pose_name = 'idle'
        self.last_attack = -9.0
        self.won = False
        self.was_dead = False
        self.dead_clock = 0.0
        self.debris = []
        self.hit_flash = 0.0
        self.flap_ph = 0.0
        self.tr = np.zeros((CAP, 2))                            # 궤적 (가슴이 지나온 길, 가까운 것부터)
        self.last_push = (0.0, 0.0)
        self.tail_ang = None                                    # 꼬리 마디의 (프레임 사이에 이어지는) 방향
        self.P = np.zeros((NR, 3))
        self.T = np.tile([0.0, 0.0, 1.0], (NR, 1))
        self.U = np.tile([0.0, 1.0, 0.0], (NR, 1))
        self.Rv = np.tile([1.0, 0.0, 0.0], (NR, 1))
        self.body = a = assets.take_body()
        self.buf = assets.body_template.copy()
        self.gait = _Gait(4, GROUPS)
        self.legs_ready = False
        self.hip_prev = [np.zeros(3) for _ in range(4)]
        self.leg_draw = []                                      # (hip, knee, end, paw 행렬) × 4
        self.wing_draw = []                                     # (메시, 행렬) 목록 (날개 뼈대)
        self.wing_tips = [np.zeros(3), np.zeros(3)]
        self.M_head = np.eye(4)
        self.mats = {}
        self.air = 0.0                                          # 하늘로 떠오른 높이 (보스 단위)
        self.tilt = 0.0                                         # 몸 앞뒤 기울기 (+ = 코가 아래)
        self.sky = None                                         # R 시간표: (시작, 오르는 시간, 내리꽂는 시간, 최고 높이)
        self.BM = np.eye(4)
        self.cur_fire = 0.0
        self.jaw_cur = 0.0
        self.look = 0.0
        self.wh_t = random.random() * 6
        self.layout_line(0.0, 0.0, 0.0)
        self._solve_body()
        self._place_head()

    # ------------------------------------------------------------ 챔피언 동작 연결
    def _play(self, steps):
        t = self.t
        self.seq = []
        for dur, name in steps:
            t += max(0.02, dur)
            self.seq.append((t, name))
        self.seq_end = t

    def cast(self, slot):
        if slot == "Q":                                         # 고개를 치켜들었다가 불을 뱉는다
            self._play([(0.3, 'wind'), (0.55, 'spit')])
        elif slot == "W":                                       # 날개를 펴고 힘차게 퍼덕인다
            self._play([(0.35, 'gustwind'), (0.7, 'gust')])
        elif slot == "E":                                       # 날개를 크게 휘두른다
            self._play([(0.3, 'sweepwind'), (0.55, 'sweep')])
        # R 은 서버의 sky_dive 이벤트(on_fx)가 시간표를 알려 준다

    def on_fx(self, kind, ev):
        if kind == "sky_dive":                                  # 날아올랐다가(rise) 내리꽂히고(dur) 내려앉는다
            rise, dur = ev.get("rise", 0.9), ev.get("dur", 0.6)
            self.sky = (self.t, rise, dur, ev.get("h", 6.5) / SC)
            self._play([(rise, 'skyrise'), (dur, 'skycruise'), (0.6, 'skyland')])

    def leap(self, dur, delay=0.0):
        pass

    def play_key(self, key):
        if key == "attack":
            self.attack()
        else:
            self.cast(key)

    def attack(self, windup=0.0):
        self.last_attack = self.t
        self._play([(0.12, 'puffwind'), (0.26, 'puff')])

    def win(self):
        self.won = True

    def flash(self, strength=1.0):
        self.hit_flash = max(self.hit_flash, strength)

    @property
    def corpse_visible(self):
        return self.dead_clock < DEATH_SHOW

    @property
    def alpha(self):
        if self.was_dead:
            return max(0.0, min(1.0, (DEATH_SHOW - self.dead_clock) / DEATH_FADE))
        return 1.0

    def mouth(self):
        """머리 앞 입의 월드 위치 (불 뱉기 발사점): (x, y, z)"""
        p = _S(SC) @ self.BM @ self.M_head @ np.array([A.MOUTH[0], A.MOUTH[1], A.MOUTH[2], 1.0])
        return float(p[0]), float(p[1]), float(p[2])

    def release(self):
        self.a.recycle(self.body)

    # ------------------------------------------------------------ 몸 배치
    def layout_line(self, x, z, yaw):
        """가슴을 (x, z) 에 두고 몸통을 뒤쪽으로 곧게 편다 (등장 · 순간이동 · 부활)."""
        self.px, self.pz = x, z
        self.yaw = self.byaw = yaw
        k = (np.arange(CAP) + 1) * TS
        self.tr[:, 0] = x - math.sin(yaw) * k
        self.tr[:, 1] = z - math.cos(yaw) * k
        self.last_push = (x, z)
        self.legs_ready = False
        self.tail_ang = None

    def _push_trail(self):
        dx, dz = self.px - self.last_push[0], self.pz - self.last_push[1]
        d = math.hypot(dx, dz)
        n = int(d / TS)
        if n <= 0:
            return
        ux, uz = dx / d, dz / d
        i = np.arange(1, n + 1)[:, None] * TS
        pts = np.concatenate([self.last_push[0] + ux * i, self.last_push[1] + uz * i], axis=1)
        self.tr = np.concatenate([pts[::-1], self.tr])[:CAP]
        self.last_push = (float(pts[-1, 0]), float(pts[-1, 1]))

    def _straighten_trail(self, dt):
        """서 있는 동안 궤적을 천천히 '머리 방향 뒤쪽의 곧은 줄'로 편다 (그래야 몸이 제자리에서 돌아선다)."""
        rate = 1.6 * max(0.0, 1.0 - self.speed / 5.0)
        if rate <= 0.0:
            return
        pts = np.concatenate([[[self.px, self.pz]], self.tr])
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        dist = np.cumsum(seg)
        fx, fz = math.sin(self.byaw), math.cos(self.byaw)
        tgt = np.stack([self.px - fx * dist, self.pz - fz * dist], axis=1)
        self.tr += (tgt - self.tr) * (1 - math.exp(-rate * dt))

    def _profile_y(self):
        """마디마다 몸의 높이 (보스 단위): 머리 → 휘어 내려온 목 → 가슴(수평) → 꼬리 끝."""
        c = self.cur
        Hb = BODY_H + c['body'] + 0.35 * math.sin(self.t * 1.7)
        Hh = c['neck']
        dH = Hh - Hb
        u = np.clip(1 - _KK / IFL, 0.0, 1.0)
        swan = 2 * u - u * u
        mixk = _clamp((abs(dH) - 24.0) / 10.0, 0.0, 1.0)
        f = swan * (1 - mixk) + u * mixk
        y = Hb + dH * f
        tk = np.clip((_KK - IHL) / (NR - 1 - IHL), 0.0, 1.0)
        y = np.where(_KK > IHL, Hb - (Hb - TAIL_END_H) * np.power(_smooth_np(tk), 1.1), y)
        return y

    def _solve_body(self):
        dt = self.dt_last
        c = self.cur
        y = self._profile_y()
        dy = np.clip(y[:-1] - y[1:], -0.97 * DS, 0.97 * DS)
        step = np.sqrt(np.maximum(0.0036, DS * DS - dy * dy))               # 마디 사이의 수평 거리
        # 가슴 앞쪽 (목·머리): 가슴의 진행 방향에서 머리가 보는 방향으로 완만하게 휘며 뻗는다
        pts = np.concatenate([[[self.px, self.pz]], self.tr])
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        bx = float(np.interp(6.0, cum, pts[:, 0]))
        bz = float(np.interp(6.0, cum, pts[:, 1]))
        cdx, cdz = self.px - bx, self.pz - bz
        cl = math.hypot(cdx, cdz)
        dcx, dcz = (cdx / cl, cdz / cl) if cl > 1e-4 else (math.sin(self.byaw), math.cos(self.byaw))
        dhx, dhz = math.sin(self.yaw), math.cos(self.yaw)
        k = np.arange(KC)
        m = _smooth_np(1.5 * (1 - k / KC))
        fx = (1 - m) * dcx + m * dhx
        fz = (1 - m) * dcz + m * dhz
        fl = np.maximum(np.hypot(fx, fz), 1e-9)
        fx, fz = fx / fl, fz / fl
        rx = np.cumsum((fx * step[:KC])[::-1])[::-1]                         # 가슴에서 k 번 마디까지의 앞쪽 변위
        rz = np.cumsum((fz * step[:KC])[::-1])[::-1]
        X = np.zeros(NR)
        Z = np.zeros(NR)
        X[:KC] = self.px + rx
        Z[:KC] = self.pz + rz
        H = np.concatenate([[0.0], np.cumsum(step[KC:])])                    # 가슴 뒤쪽: 지나온 길을 따라간다
        X[KC:] = np.interp(H, cum, pts[:, 0])
        Z[KC:] = np.interp(H, cum, pts[:, 1])
        # 가슴 뒤 몸통·꼬리: 끝으로 갈수록 늦게 돌아서고, 몸통은 빳빳해서 확 꺾이지 않으며 꼬리는 그보다 부드럽게 휜다
        X, Z, self.tail_ang = heavy_chain(self.tail_ang, X, Z, KC + 1, dt, TAIL_TURN0, TAIL_TURN1, _BENDS)
        # 머리를 앞으로 뻗기 (물어뜯기): 머리 쪽 마디일수록 많이 끌려 나온다
        ex = c['ext']
        if abs(ex) > 1e-3:
            fall = ex * (1 - _smooth_np(_KK / EXT_SPAN))
            X = X + dhx * fall
            Z = Z + dhz * fall
        # 꼬리로 갈수록 커지는 일렁임 (좌우 · 상하)
        T0x = np.empty(NR)
        T0z = np.empty(NR)
        T0x[1:-1], T0z[1:-1] = X[:-2] - X[2:], Z[:-2] - Z[2:]
        T0x[0], T0z[0] = X[0] - X[1], Z[0] - Z[1]
        T0x[-1], T0z[-1] = X[-2] - X[-1], Z[-2] - Z[-1]
        tl = np.maximum(np.hypot(T0x, T0z), 1e-9)
        T0x, T0z = T0x / tl, T0z / tl
        und = c['und']
        ramp = _smooth_np(_SK / 110.0)
        amp = und * (0.3 + 4.6 * ramp)
        lat = amp * np.sin(self.t * 2.5 - _SK * 0.1)
        ver = amp * 0.45 * np.sin(self.t * 2.0 - _SK * 0.085 + 1.3)
        X = X + T0z * lat                                                    # R = (tz, 0, -tx)
        Z = Z - T0x * lat
        y = np.maximum(y + ver, RAD * 0.78 + 0.1)
        P = self.P
        P[:, 0], P[:, 1], P[:, 2] = X, y, Z
        # 마디마다 앞(T) · 위(U) · 오른쪽(Rv) 축
        T = self.T
        T[1:-1] = P[:-2] - P[2:]
        T[0] = P[0] - P[1]
        T[-1] = P[-2] - P[-1]
        T /= np.maximum(np.sqrt((T * T).sum(axis=1)), 1e-12)[:, None]
        up = np.array([0.0, 1.0, 0.0])
        U = up[None, :] - T[:, 1:2] * T
        U /= np.maximum(np.sqrt((U * U).sum(axis=1)), 1e-12)[:, None]
        self.U[:] = U
        R = np.stack([U[:, 1] * T[:, 2] - U[:, 2] * T[:, 1], U[:, 2] * T[:, 0] - U[:, 0] * T[:, 2], U[:, 0] * T[:, 1] - U[:, 1] * T[:, 0]], axis=1)
        self.Rv[:] = R / np.maximum(np.sqrt((R * R).sum(axis=1)), 1e-12)[:, None]
        # 몸통 관 정점
        rr = RAD * _LAM * (1 + 0.012 * np.sin(self.t * 2.4 - _KK * 0.25))
        rv = rr[:, None] * _TOPK
        xw = (_COSA[None, :] * rv * (1 + WIDER * BULK[:, None]))[:, :, None]
        yw = (_SINA[None, :] * rv * 0.9)[:, :, None]
        V = (P[:, None, :] + self.Rv[:, None, :] * xw + self.U[:, None, :] * yw).reshape(-1, 3)
        idx = self.a.body_idx
        pa, pb, pc = V[idx[0::3]], V[idx[1::3]], V[idx[2::3]]
        e1, e2 = pb - pa, pc - pa
        fn = np.stack([e1[:, 1] * e2[:, 2] - e1[:, 2] * e2[:, 1], e1[:, 2] * e2[:, 0] - e1[:, 0] * e2[:, 2], e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]],
                      axis=1)
        fn /= np.maximum(np.sqrt((fn * fn).sum(axis=1)), 1e-12)[:, None]
        self.buf[:, 0:3] = V[idx]
        self.buf[:, 3:6] = np.repeat(fn, 3, axis=0)
        self.body.parts[0][1].write(self.buf.tobytes())
        self._update_wings()
        self._update_legs(dt)

    # ------------------------------------------------------------ 머리
    def _place_head(self, dt=0.0):
        c = self.cur
        pos = self.P[0]
        stun = 1.0 if self.pose_name == 'stagger' else 0.0
        self.look += (0.0 - self.look) * min(1.0, dt * 4)
        base = (_T(float(pos[0]), float(pos[1]), float(pos[2])) @ _Ry(self.yaw + self.look) @ _Rx(c['pitch'] + 0.03 * math.sin(self.t * 1.3)) @ _S(HS))
        self.M_head = base
        mats = {'head': base, 'fins': base}
        mats['jaw'] = base @ _T(*A.JAW_PIVOT) @ _Rx(c['jaw'] * 0.72 + 0.03 * math.sin(self.t * 3) + stun * 0.18)
        for i, (wx, wy, wz) in enumerate(A.WHISKER_POS):
            side = 1 if wx > 0 else -1
            wr = _Ry(side * (0.1 + 0.05 * math.sin(self.t * 2.2 + i)))
            wx_ = _Rx(0.1 * math.sin(self.t * 2.9 + i * 1.7) + min(0.5, self.speed * 0.012))
            mats['wh%d' % i] = base @ _T(wx, wy, wz) @ wx_ @ wr
        mats['eye_l'] = base @ _T(0.98, 0.52, 0.75)
        mats['eye_r'] = base @ _T(-0.98, 0.52, 0.75)
        mats['gem_f'] = base @ _T(0, 1.02, 0.55) @ _Rx(-0.35)
        self.mats = mats

    # ------------------------------------------------------------ 날개
    def _update_wings(self):
        c = self.cur
        stun = 1.0 if self.pose_name == 'stagger' else 0.0
        fold = _clamp(c['wfold'], 0.0, 1.0)
        amp = c['wamp']
        hz = c['whz']
        ph = self.flap_ph / TAU
        f0 = _stroke(ph)
        f_vel = (_stroke(ph + 0.012) - _stroke(ph - 0.012)) / 0.024
        fr = ph - math.floor(ph)
        up_w = math.sin(PI * ((fr - 0.4) / 0.6)) if fr > 0.4 else 0.0
        amp_k = min(1.0, amp * 2.2)
        len_k = (1 - 0.42 * fold) * (1 - 0.13 * up_w * amp_k)
        billow = _clamp(-f_vel * hz * 0.045 * min(1.0, amp * 1.6), -0.5, 0.95) + 0.05 * (1 - fold)
        ripple = 0.012 + 0.014 * amp_k
        sw = _clamp(c['swing'], 0.0, 1.0)
        i = IW
        c0, R, U, T = self.P[i], self.Rv[i], self.U[i], self.T[i]
        rad = RADL[i]
        hip, hip_r, hip_u = self.P[IH], self.Rv[IH], self.U[IH]

        def dir_(side, sweep, elev):
            ce = math.cos(elev)
            return R * (side * math.cos(sweep) * ce) + U * math.sin(elev) + T * (-math.sin(sweep) * ce)

        up_v, t_v = U[None, :], T[None, :]
        bs = WS / 0.95
        self.wing_draw = []
        self.panel_draw = []
        for wi, side in enumerate((1, -1)):
            allp = np.zeros((16, 3))
            p, mids = allp[:12], allp[12:16]
            bias = 0.12 + c['wraise'] - stun * 0.9
            amp_e = amp * (1 - stun)
            e_a = _lerp(bias + amp_e * f0, -0.3 + 1.25 * f0, sw)
            s7 = _stroke(ph - 0.07)
            e_b = _lerp(bias * 0.9 + amp_e * s7 * 1.08, -0.3 + 1.25 * s7 * 1.08, sw)
            sweep_a = _lerp(_lerp(0.95, 1.38, fold), 0.25, sw)
            sweep_b = _lerp(_lerp(-0.18, 1.45, fold), 0.0, sw)
            ws = _clamp(c['wsw'], 0.0, 1.0)
            if ws > 1e-3:                                       # W: 지정한 각도로 크게 휘두르기
                e_a = _lerp(e_a, c['wel'], ws)
                e_b = _lerp(e_b, c['wel'] * 0.8 - 0.1, ws)
                sweep_a = _lerp(sweep_a, c['wsp'], ws)
                sweep_b = _lerp(sweep_b, c['wsp'] - 0.15, ws)
            S = c0 + R * (side * rad * 0.55) + U * (rad * 0.7)
            E = S + dir_(side, sweep_a, e_a) * (ARM[0] * WS * len_k)
            Wr = E + dir_(side, sweep_b, e_b) * (ARM[1] * WS * len_k)
            p[0], p[1], p[2] = S, E, Wr
            spread_k = _lerp(0.55, 1, c['wspread']) * (1 - fold) * (1 - 0.3 * up_w * amp_k)
            for k in range(4):
                sweep_f = _lerp(_lerp(0.12 + k * 0.4 * spread_k + 0.1 * (1 - spread_k), 1.5, fold), 0.02 + k * 0.28, sw)
                sk = _stroke(ph - 0.15 - 0.05 * k)
                elev_f = _lerp(bias * 0.8 + amp_e * sk * (1.05 + 0.1 * k) - 0.04 * k, -0.3 + 1.25 * sk * (1.05 + 0.1 * k), sw)
                if ws > 1e-3:
                    sweep_f = _lerp(sweep_f, c['wsp'] - 0.3 + k * 0.3, ws)
                    elev_f = _lerp(elev_f, c['wel'] * 0.85 - 0.05 * k, ws)
                p[3 + k] = Wr + dir_(side, sweep_f, elev_f) * (FING[k] * WS * len_k)
                mids[k] = Wr + (p[3 + k] - Wr) * 0.52
                mids[k][1] += (0.5 + billow) * 0.028 * FING[k] * WS * len_k * amp_k
            p[10] = hip + hip_r * (side * RADL[IH] * 0.8) + hip_u * (RADL[IH] * 0.1)
            np.maximum(p[:, 1], 0.12, out=p[:, 1])
            np.maximum(mids[:, 1], 0.12, out=mids[:, 1])
            # 날개막
            scal = 0.2 + 0.1 * up_w * amp_k + 0.04 * math.sin(self.t * 2 + side)
            sizes = [FING[0] * WS * len_k * 0.06, FING[1] * WS * len_k * 0.06, FING[2] * WS * len_k * 0.06, FING[3] * WS * len_k * 0.06,
                     ARM[1] * WS * 0.05]
            bills = [billow] * 4 + [billow * 0.5]
            rips = [ripple] * 4 + [ripple * 0.5]
            bows = [scal] * 4 + [0.0]
            for pn, size, bl, rp, bw in zip(self.panels[wi], sizes, bills, rips, bows):
                self._fill_panel(pn, allp, bw, bl, rp, size)
                self.panel_draw.append(pn)
            # 뼈대 · 갑옷 띠 · 관절 · 발톱
            self.wing_tips[wi] = p[3].copy()
            self._wing_parts(p, mids, bs, up_v, t_v)

    def _fill_panel(self, pn, allp, bow_k, billow, ripple, size):
        ia, ib, tt, bi, bs_ = pn.spec
        A_ = allp[ia]
        q = A_ + (allp[ib] - A_) * tt
        q += (allp[bi] - q) * (bs_ * bow_k)
        pn.bnd[:] = q
        bnd, K = pn.bnd, pn.K
        center = bnd.mean(axis=0)
        cx, cy, cz = center.tolist()
        a = bnd[K // 4] - center
        b = bnd[(K * 3) // 4] - center
        nx, ny, nz = a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]
        l = math.sqrt(nx * nx + ny * ny + nz * nz)
        if l > 1e-12:
            nx, ny, nz = nx / l, ny / l, nz / l
        else:
            nx, ny, nz = 0.0, 1.0, 0.0
        if ny < 0:
            nx, ny, nz = -nx, -ny, -nz
        pos = pn.pos
        pos[0] = (cx + nx * billow * 0.3 * size, cy + billow * 0.3 * size, cz + nz * billow * 0.3 * size)
        f = pn.fr
        off = billow * size * pn.lift + ripple * size * np.sin(pn.arg0 - self.t * 7) * pn.fco
        sag = -0.035 * size * 2 * f * (1 - f)
        v = pos[1:].reshape(f.shape[0], K, 3)
        v[:, :, 0] = cx + (bnd[:, 0][None, :] - cx) * f + off * nx
        v[:, :, 1] = np.maximum(cy + (bnd[:, 1][None, :] - cy) * f + off * ny + sag, 0.1)
        v[:, :, 2] = cz + (bnd[:, 2][None, :] - cz) * f + off * nz
        idx = pn.idx
        pa, pb, pc = pos[idx[0::3]], pos[idx[1::3]], pos[idx[2::3]]
        e1, e2 = pb - pa, pc - pa
        fn = np.stack([e1[:, 1] * e2[:, 2] - e1[:, 2] * e2[:, 1], e1[:, 2] * e2[:, 0] - e1[:, 0] * e2[:, 2], e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]],
                      axis=1)
        fn /= np.maximum(np.sqrt((fn * fn).sum(axis=1)), 1e-12)[:, None]
        pn.buf[:, 0:3] = pos[idx]
        pn.buf[:, 3:6] = np.repeat(fn, 3, axis=0)
        pn.mesh.parts[0][1].write(pn.buf.tobytes())

    def _wing_parts(self, p, mids, bs, up_v, t_v):
        a = self.a
        draw = self.wing_draw
        A_ = np.empty((10, 3))
        B_ = np.empty((10, 3))
        rad = np.empty(10)
        A_[0], B_[0], rad[0] = p[0], p[1], 0.42 * bs
        A_[1], B_[1], rad[1] = p[1], p[2], 0.36 * bs
        A_[2::2] = p[2]
        B_[2::2] = mids
        A_[3::2] = mids
        B_[3::2] = p[3:7]
        ks = np.arange(4)
        rad[2::2] = (0.2 - ks * 0.012) * bs * 1.05
        rad[3::2] = (0.15 - ks * 0.01) * bs
        d, L = _unit(B_ - A_)
        zero = L < 1e-4
        L = np.where(zero, 0.0, L)
        rad = np.where(zero, 0.0, rad)
        d[zero] = (0, 1, 0)
        for m_ in _seg_mats(d, rad, L, rad, A_):
            draw.append((a.bone, m_))
        ca = np.array([p[0], p[0], p[1], p[1]])
        cb = np.array([p[1], p[1], p[2], p[2]])
        cr = np.array([0.42, 0.42, 0.36, 0.36]) * bs * 1.5
        ct = np.array([0.1, 0.58, 0.1, 0.6])
        cl = np.array([0.3, 0.22, 0.3, 0.22])
        d, L = _unit(cb - ca)
        zero = L < 1e-4
        rr = np.where(zero, 0.0, cr * (1 - 0.38 * ct))
        sy = np.where(zero, 0.0, L * cl)
        d[zero] = (0, 1, 0)
        for m_ in _seg_mats(d, rr, sy, rr, ca + (cb - ca) * ct[:, None]):
            draw.append((a.cuff, m_))
        js = np.array([0.62, 0.5, 0.52]) * bs
        for q in range(3):
            jp = p[q]
            sa, ca_ = math.sin(jp[0] * 0.3), math.cos(jp[0] * 0.3)
            sb, cb_ = math.sin(jp[2] * 0.3), math.cos(jp[2] * 0.3)
            draw.append((a.joint, _basis(np.array([cb_, sa * sb, -ca_ * sb]) * js[q], np.array([0, ca_, sa]) * js[q],
                                         np.array([sb, -sa * cb_, ca_ * cb_]) * js[q], jp)))
        d, _ = _unit(p[3:7] - mids)
        cs = 1.6 + (3 - ks) * 0.25
        for m_ in _seg_mats(d, cs, cs, cs, p[3:7]):
            draw.append((a.claw, m_))
        d, _ = _unit((p[2] - p[1])[None, :])
        d = d + up_v * 0.6 + t_v * 0.5
        d, _ = _unit(d)
        s5 = np.array([5.5])
        draw.append((a.thumb, _seg_mats(d, s5, s5, s5, p[2][None, :])[0]))

    # ------------------------------------------------------------ 다리
    def _update_legs(self, dt):
        fore = (self.P[IFL], self.Rv[IFL], self.U[IFL], self.T[IFL], RADL[IFL])
        hind = (self.P[IHL], self.Rv[IHL], self.U[IHL], self.T[IHL], RADL[IHL])
        hips, homes = [], np.zeros((4, 3))
        crouch = _clamp(-self.cur['body'] / 6.0, 0.0, 1.0)
        for i in range(4):
            c_, R_, U_, T_, rad = fore if FORE[i] else hind
            s = SIDE[i]
            hip = c_ + R_ * (s * rad * 0.8) + U_ * (-rad * (0.3 if FORE[i] else 0.5))
            hips.append(hip)
            a = HOME_ANGLE[i]
            r = HOME_R * (1 + 0.35 * crouch)
            home = hip + R_ * (s * r * math.cos(a)) + T_ * (r * math.sin(a))
            home[1] = FOOT_Y
            homes[i] = home
        if not self.legs_ready:
            self.gait.snap(homes)
            self.legs_ready = True
        vel = (self.vel[0], self.vel[1])
        spd = math.hypot(*vel)
        if any(math.hypot(self.gait.feet[i][0] - homes[i][0], self.gait.feet[i][2] - homes[i][2]) > 45 for i in range(4)):
            self.gait.snap(homes)
        self.gait.update(dt, homes, vel, LEG_STEP, max(0.12, 0.2 - spd * 0.012), 1.05 * KL * LEG_S, 0.12)
        self.leg_draw = []
        for i in range(4):
            c_, R_, U_, T_, rad = fore if FORE[i] else hind
            s = SIDE[i]
            a = HOME_ANGLE[i]
            foot = self.gait.get(i)
            pole = R_ * (s * math.cos(a)) + T_ * (-math.sin(a) if FORE[i] else math.sin(a))
            pole[1] = 0.0
            pl = float(np.linalg.norm(pole))
            pole = pole / pl * 0.45 if pl > 1e-3 else np.array([s * 0.45, 0, 0])
            pole[1] = 1.0
            knee, end = _solve_two_bone(hips[i], foot, L1, L2, pole)
            bz = np.array([T_[0], 0.0, T_[2]])
            bl = float(np.linalg.norm(bz))
            bz = bz / bl if bl > 1e-3 else np.array([0.0, 0.0, 1.0])
            bx = np.array([bz[2], 0.0, -bz[0]])                              # (0,1,0) × bz
            paw = _basis(bx * 0.75, np.array([0, 0.75, 0]), bz * 0.75, end + np.array([0, -0.6, 0]))
            self.leg_draw.append((hips[i], knee, end, paw))

    # ------------------------------------------------------------ 매 프레임
    def update(self, dt, d, ent=None):
        dt = min(dt, 0.1)
        self.t += dt
        self.dt_last = dt
        d = d or {}
        st = d.get("st", ())
        a = d.get("a", 0)
        dead = bool(d.get("dead"))
        if ent is not None:
            self._track(dt, ent)
        self.hit_flash = max(0.0, self.hit_flash - dt * 10)
        if dead:
            if not self.was_dead:
                self.was_dead = True
                self.dead_clock = 0.0
                self._explode()
            self.dead_clock += dt
            self.air = self.tilt = self.lift = 0.0
            self.sky = None
            self.BM = np.eye(4)
            self._update_debris(dt)
            return
        if self.was_dead:                                   # 부활: 새 자리에 몸을 곧게 편다
            self.was_dead = False
            self.debris = []
            self.seq = []
            self.layout_line(self.px, self.pz, self.yaw)
        if a == 2 and self.t - self.last_attack > 0.6 and not self._busy():
            self.attack()
        spd_w = self.speed * SC
        if a == 1 or spd_w > 0.9:
            self.moving, self.still_t = True, 0.0
        elif self.moving:
            self.still_t += dt
            if self.still_t > 0.25 and spd_w < 0.4:
                self.moving = False
        if self.seq and self.t < self.seq_end:
            name = next(n for e, n in self.seq if self.t < e)
        elif "air" in st or "stun" in st:
            name = 'stagger'
        elif self.won:
            name = 'win'
        elif self.moving:
            name = 'move'
        else:
            name = 'idle'
        self.pose_name = name
        p = {**IDLE, **POSES[name]}
        for k, v in p.items():
            self.tgt[k] = v
            self.rate[k] = FAST.get(name, {}).get(k, RATES[k])
        if name == 'idle':
            self.tgt['neck'] += 0.6 * math.sin(self.t * 1.4)
            self.tgt['pitch'] += 0.04 * math.sin(self.t * 0.9)
        for k in self.cur:
            self.cur[k] += (self.tgt[k] - self.cur[k]) * (1 - math.exp(-self.rate[k] * dt))
        # 날개 퍼덕임 (접혀 있을 때는 아주 천천히 숨쉬듯)
        self.flap_ph += dt * TAU * max(0.0, self.cur['whz'])
        self.byaw += _wrap(self.yaw - self.byaw) * (1 - math.exp(-(2.2 if not self.moving else 5.0) * dt))
        a_t, tl_t = 0.0, 0.0
        if self.sky:
            t0, rise, dur, H = self.sky
            age = self.t - t0
            if age < rise:
                u = age / rise
                a_t, tl_t = H * (1 - (1 - u) ** 2), -0.3 * math.sin(PI * u)
            elif age < rise + dur:
                u = (age - rise) / dur                          # 높이 뜬 채 수평 비행, 마지막 20% 에서 내려앉는다
                a_t = H if u < 0.8 else H * (1 - _smooth((u - 0.8) / 0.2))
                tl_t = 0.3 if u < 0.8 else 0.3 + 0.4 * _smooth((u - 0.8) / 0.2)
            else:
                self.sky = None
        self.air += (a_t - self.air) * (1 - math.exp(-14 * dt))
        self.tilt += (tl_t - self.tilt) * (1 - math.exp(-9 * dt))
        self.lift = self.air * SC / 0.075
        bm = _T(0.0, self.air, 0.0)
        if abs(self.tilt) > 1e-3:
            bm = bm @ _T(self.px, BODY_H, self.pz) @ _Ry(self.yaw) @ _Rx(self.tilt) @ _Ry(-self.yaw) @ _T(-self.px, -BODY_H, -self.pz)
        self.BM = bm
        self._push_trail()
        if not self.moving:
            self._straighten_trail(dt)
        self._solve_body()
        self._place_head(dt)

    def _busy(self):
        return bool(self.seq) and self.t < self.seq_end

    def _track(self, dt, ent):
        x, z = ent.x / SC, ent.z / SC
        face = facing_to_rot(ent.f)
        if not self.have_pos:
            self.have_pos = True
            self.layout_line(x, z, face)
            return
        mx, mz = x - self.px, z - self.pz
        moved = math.hypot(mx, mz)
        if moved > 40.0:                                      # 순간이동 (귀환·플래시·부활): 몸을 새 자리에 곧게 편다
            self.vel = [0.0, 0.0]
            self.layout_line(x, z, self.yaw)
        else:
            k = 1 - math.exp(-10 * dt)
            vx, vz = (mx / dt, mz / dt) if dt > 1e-6 else (0.0, 0.0)
            self.vel[0] += (vx - self.vel[0]) * k
            self.vel[1] += (vz - self.vel[1]) * k
            self.px, self.pz = x, z
        self.speed = math.hypot(self.vel[0], self.vel[1])
        self.yaw += _wrap(face - self.yaw) * (1 - math.exp(-12 * dt))

    # ------------------------------------------------------------ 그리기
    def draw(self, r, tint=(1, 1, 1, 1), emis=(0, 0, 0)):
        SCL0 = _S(SC)
        SCL = SCL0 @ self.BM
        alpha = tint[3] if len(tint) > 3 else 1.0
        hf = self.hit_flash
        e = (emis[0] + 0.2 + hf * 0.45, emis[1] + 0.06 + hf * 0.2, emis[2] + 0.015)
        if self.was_dead:
            for db in self.debris:
                Mx = _T(*db.pos) @ _euler(*db.ang) @ db.base
                if db.tint is not None:
                    r.draw(db.mesh, SCL @ Mx, tint=(db.tint[0], db.tint[1], db.tint[2], alpha), unlit=1.0)
                else:
                    r.draw(db.mesh, SCL @ Mx, tint=(tint[0] * db.col[0], tint[1] * db.col[1], tint[2] * db.col[2], alpha), emissive=e)
            return
        a = self.a
        col = (tint[0], tint[1], tint[2], alpha)
        prog = r.prog
        prog["u_dbl"].value = True
        # 몸 그림자
        for k in range(8, NR, 6):
            r.draw_transparent(a.shadow, SCL0 @ _T(float(self.P[k][0]), 0.14, float(self.P[k][2])) @ _S(RADL[k] * 1.5 + 1.0), (0, 0, 0, 0.05 * alpha))
        r.draw(self.body, SCL, tint=col, emissive=e)
        # 등 가시 · 꼬리 칼날
        i = _SPI
        Ci, Ui, Ti, Ri = self.P[i], self.U[i], self.T[i], self.Rv[i]
        tv = Ui - 0.35 * Ti
        tv /= np.maximum(np.sqrt((tv * tv).sum(axis=1)), 1e-12)[:, None]
        tv2 = np.cross(Ri, tv)
        tv2 /= np.maximum(np.sqrt((tv2 * tv2).sum(axis=1)), 1e-12)[:, None]
        for q in range(len(i)):
            sz = _SPSZ[q]
            r.draw(a.spine, SCL @ _basis(Ri[q] * sz * 0.9, tv[q] * sz, tv2[q] * sz, Ci[q] + Ui[q] * RADL[i[q]] * 0.72), tint=col, emissive=e)
        ee = NR - 1
        r.draw(a.tail_blade, SCL @ _basis(self.Rv[ee] * 2.4, self.U[ee] * 2.4, self.T[ee] * 2.4, self.P[ee]), tint=col, emissive=e)
        # 가슴 보석 (배 쪽 표면)
        gi = IFL - 7
        gc = self.P[gi]
        nb = -self.U[gi]
        nz = np.cross(self.Rv[gi], self.T[gi])
        if float(nz @ nb) < 0:
            nz = -nz
        gm = _basis(self.Rv[gi], self.T[gi], nz, gc + nb * RADL[gi] * 0.97)
        gcol = self._gem_color()
        r.draw(a.gem_c_bezel, SCL @ gm @ _T(0, 0, -0.2), tint=col, emissive=e)
        r.draw(a.gem_c, SCL @ gm, tint=(gcol[0], gcol[1], gcol[2], alpha), unlit=1.0)
        # 날개
        for pn in self.panel_draw:
            r.draw(pn.mesh, SCL, tint=(1, 1, 1, alpha * 0.96), emissive=(0.18 + hf * 0.3, 0.05, 0.01))
        for mesh, Mx in self.wing_draw:
            r.draw(mesh, SCL @ Mx, tint=col, emissive=e)
        # 다리
        for hip, knee, end, paw in self.leg_draw:
            for (a_, b_, th, mesh) in ((hip, knee, UP_T, a.upper), (knee, end, LO_T, a.lower)):
                dd = b_ - a_
                ln = float(np.linalg.norm(dd))
                if ln < 1e-5:
                    continue
                r.draw(mesh, SCL @ _T(*a_) @ _from_to((0, 1, 0), dd / ln) @ _S(th, ln, th), tint=col, emissive=e)
            r.draw(a.knee, SCL @ _T(*knee) @ _S(KNEE_R), tint=col, emissive=e)
            r.draw(a.paw, SCL @ paw, tint=col, emissive=e)
        # 머리
        ms = self.mats
        r.draw(a.head, SCL @ ms['head'], tint=col, emissive=e)
        r.draw(a.fins, SCL @ ms['fins'], tint=col, emissive=(0.35 + e[0], e[1] + 0.1, e[2]))
        r.draw(a.jaw, SCL @ ms['jaw'], tint=col, emissive=e)
        fire = _clamp(self.cur['fire'], 0.0, 1.0)
        r.draw(a.mouth, SCL @ ms['jaw'], tint=(1, 1, 1, alpha), unlit=0.4 + 0.6 * fire, emissive=(0.3 * fire, 0.05 * fire, 0))
        for q in range(4):
            r.draw(a.whisker[0 if A.WHISKER_POS[q][0] > 0 else 1], SCL @ ms['wh%d' % q], tint=col, emissive=e)
        ec = self._eye_color(fire)
        for nm in ('eye_l', 'eye_r'):
            r.draw(a.eye, SCL @ ms[nm], tint=(ec[0], ec[1], ec[2], alpha), unlit=1.0)
        r.draw(a.gem_f_bezel, SCL @ ms['gem_f'], tint=col, emissive=e)
        r.draw(a.gem_f, SCL @ ms['gem_f'], tint=(gcol[0], gcol[1], gcol[2], alpha), unlit=1.0)
        prog["u_dbl"].value = False
        if fire > 0.03:                                          # 입속 불빛
            gr = 0.5 * (0.4 + fire * 2.4 * (0.92 + 0.08 * math.sin(self.t * 40)))
            r.draw_transparent(a.orb, SCL @ ms['jaw'] @ _T(0, 0.35 - 0.1 - gr * 0.2, 1.9) @ _S(gr * 1.2), (2.2, 0.9, 0.2, 0.55 * fire * alpha), additive=True)

    def _eye_color(self, fire):
        k = (1.0 + 0.3 * fire) * (1.0 + 0.1 * math.sin(self.t * 4))
        return (2.2 * k, 1.7 * k, 0.4 * k)

    def _gem_color(self):
        k = 0.85 + 0.25 * math.sin(self.t * 3.2) + self.hit_flash * 0.8
        return (2.6 * k, 2.0 * k, 0.3 * k)

    # ------------------------------------------------------------ 사망: 조각이 흩어진다
    def _explode(self):
        r = random.random
        a = self.a
        center = np.array([self.px, 4.0, self.pz])
        parts = []
        ms = self.mats
        for mesh, nm, glow in ((a.head, 'head', None), (a.fins, 'fins', None), (a.jaw, 'jaw', None), (a.eye, 'eye_l', 'eye'), (a.eye, 'eye_r', 'eye')):
            if nm in ms:
                parts.append((mesh, ms[nm], glow))
        for k in range(2, NR, 3):
            basis = np.eye(4)
            basis[:3, 0], basis[:3, 1], basis[:3, 2] = self.Rv[k], self.U[k], self.T[k]
            Mx = _T(*self.P[k]) @ basis @ _S(RADL[k] * 0.9, RADL[k] * 0.8, DS * 1.6)
            parts.append((a.chunk, Mx, None))
        for mesh, Mx in self.wing_draw[::2]:
            parts.append((mesh, Mx, None))
        for hip, knee, end, paw in self.leg_draw:
            parts.append((a.paw, paw, None))
        self.debris = []
        for mesh, Mx, glow in parts:
            db = _Debris()
            db.mesh = mesh
            pos = Mx[:3, 3].copy()
            base = Mx.copy()
            base[:3, 3] = 0.0
            db.base = base
            v = pos - center
            v[1] = abs(v[1]) * 0.5 + 0.6
            v /= max(1e-6, float(np.linalg.norm(v)))
            sp = 4 + r() * 10
            db.vel = v * sp + np.array([(r() - 0.5) * 3, 5 + r() * 9, (r() - 0.5) * 3])
            db.pos = pos
            db.ang = np.zeros(3)
            db.spin = np.array([(r() - 0.5) * 12, (r() - 0.5) * 12, (r() - 0.5) * 12])
            db.tint = self._eye_color(0.5) if glow else None
            db.col = (1.0, 0.7, 0.55) if (mesh is a.chunk and len(self.debris) % 2) else (1.0, 1.0, 1.0)
            db.unlit = bool(glow)
            db.rest = False
            db.r = max(0.5, float(np.linalg.norm(Mx[:3, 0])) * 0.5)
            self.debris.append(db)

    def _update_debris(self, dt):
        for db in self.debris:
            if db.rest:
                continue
            db.vel[1] -= 28 * dt
            db.pos += db.vel * dt
            db.ang += db.spin * dt
            if db.pos[1] < min(db.r, 0.8):
                db.pos[1] = min(db.r, 0.8)
                db.vel[1] *= -0.35
                db.vel[0] *= 0.78
                db.vel[2] *= 0.78
                db.spin *= 0.6
                if abs(db.vel[1]) < 1.2 and math.hypot(db.vel[0], db.vel[2]) < 0.6:
                    db.rest = True


class DragonAssets(A.DragonAssets):
    def __init__(self, renderer):
        super().__init__(renderer, NR)
