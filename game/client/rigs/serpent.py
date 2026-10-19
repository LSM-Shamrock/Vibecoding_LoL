"""이무기 — 보스러시(DEEP NEST) 2층 보스 '심연의 이무기'의 절차적 리그를 이 게임으로 옮긴 것.

원본: bosses/serpent/rig.py. 몸은 머리가 지나간 길(궤적) 위에 놓이는 고리들을 이은 관이고, 머리를 들면 목이 완만한 S 곡선으로
솟아 코브라 자세가 되며, 잠행하면 머리부터 차례로 땅속으로 가라앉는다. 모든 계산은 원본과 같은 "보스 단위"로 하고 마지막에
SC 배로 줄여 그린다. 이 게임은 챔피언이 한 명이라 몸 길이를 원본(242)보다 훨씬 짧게(BODY_LEN) 줄였다.

이 게임의 렌더러는 씬 그래프가 없어서 머리 부품(두개골/아래턱/독니/혀/눈/지느러미)은 메시 하나씩 만들어 두고 매 프레임
행렬만 계산해 그린다. 몸통 관만 개체마다 정점 버퍼를 매 프레임 다시 쓴다.

챔피언 동작 연결 (SpiderAnim 과 같은 모양):
  update(dt, d, ent)   서버 상태(d)와 화면 위치(ent.x, ent.z, ent.f)로 몸을 갱신
  cast(slot)           스킬 시전 시작 (Q 독 뱉기 / W 돌진 준비 / E 내려찍기 준비 / R 잠행)
  on_fx(kind, ev)      서버 효과 이벤트: lunge(돌진) / serpent_rear(내려찍기 준비) / dive(잠행) / dive_out(솟구침)
  draw(r, tint, emis)  그리기
죽으면 마디마다 흩어지는(원본의 explode) 파편이 된다.
"""
import math
import random
import weakref

import numpy as np
import pygame

from ..geometry import MeshBuilder
from ..gl import Mesh, facing_to_rot
from .spider import _T, _S, _Rx, _Ry, _Rz, _euler, _from_to, _hex, _wrap, _xf, heavy_chain
from . import BIG_SCALE, CHAMP_SCALE, DEATH_FADE, DEATH_SHOW

PI = math.pi
TAU = PI * 2
SC = 0.20 * CHAMP_SCALE * BIG_SCALE      # 보스 단위 -> 이 게임 단위
BODY_LEN = 34.0                 # 머리 중심에서 꼬리 끝까지 (원본 242 를 이 게임 크기로 줄임)
BODY_R = 1.65                   # 몸통 가장 굵은 곳의 반지름
HS = 1.35                       # 머리 크기 배율
HEAD_REST = 0.95                # 머리가 바닥에 얹혀 있을 때 머리 중심 높이
DSEG = 1.0                      # 몸을 이루는 고리 사이 간격
NR = int(BODY_LEN // DSEG) + 1
M = 12                          # 한 고리의 둘레 분할 수
VW = M + 1
TS = 0.4                        # 궤적 점 간격
CAP = int(math.ceil((BODY_LEN + 40) / TS))
GCELL = 3.6                     # 몸이 서로 겹치는 곳을 찾기 위한 공간 격자
GCAP = 14
STACK_GAP = 8                   # 이 고리 수보다 가까운 마디끼리는 겹침으로 보지 않는다
SLAM_REACH = 4.8                # 내려찍기 때 목이 뻗을 수 있는 최대 거리 (이 게임 단위)
EXT_SPAN = 22.0                 # 목을 앞으로 뻗을 때 머리에서 이만큼 뒤까지 끌려온다
WAVE_RISE = 0.3                 # 마디 하나가 잠기는 데 걸리는 시간
ATTACK_TIME = 0.34
HEAVY_POS = 7.0                 # 머리가 이동 목표를 따라가는 속도 (낮을수록 묵직하게 끌려간다)
HEAVY_TURN = 6.0                # 머리 방향이 바뀌는 속도
MAX_TURN = 4.5                  # 머리가 돌 수 있는 최대 각속도 (rad/s)
BODY_TURN = 14.0                # 이동 중 세운 목 바로 뒤 마디가 지나온 길의 방향으로 돌아서는 빠르기 (1/초)
TAIL_TURN = 2.2                 # ... 꼬리 끝은 이만큼만 (낮을수록 빙빙 돌 때 꼬리가 묵직하게 늦게 돈다)
BODY_BEND = math.radians(4.5)   # 이동 중 몸(S자 물결을 넣기 전의 길)이 마디 하나에서 꺾일 수 있는 최대 각도 (작을수록 빳빳)
# 챔피언 자리(선택 원·그림자·히트박스)에 고정하는 몸통 구간: 세운 목이 땅에 닿은 뒤부터 S자 한 물결 길이만큼의 가운데.
# 몸 안의 한 점을 챔피언 자리에 못 박아 두므로, 방향을 바꾸면 머리와 목만 그 둘레로 돌고 몸통은 자리를 벗어나지 않는다.
PIN_K0, PIN_K1 = 10, 19
PIN_RATE = 12.0                 # 고정 위치가 따라붙는 빠르기 (1/초, 프레임 사이 떨림만 거른다)

_SCALE = _S(SC)


def _smooth(k):
    x = min(1.0, max(0.0, k))
    return x * x * (3 - 2 * x)


def _smooth_np(k):
    x = np.clip(k, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _radius_at(sigma):
    """머리 중심에서 sigma 만큼 떨어진 마디의 반지름: 머리에 물리는 가는 목 → 거의 고른 굵기의 몸통 → 서서히 가늘어지는 꼬리"""
    r = 0.9 + (BODY_R - 0.9) * _smooth((sigma - 2.5) / 7)
    if sigma < 3.5:
        r *= 0.5 + 0.5 * _smooth(sigma / 3.5)
    tail = 19.0
    tail_start = BODY_LEN - tail
    if sigma > tail_start:
        r *= max(0.0, 1 - (sigma - tail_start) / tail) ** 0.8
    return max(0.05, r)


RADL = [_radius_at(k * DSEG) for k in range(NR)]
RAD = np.array(RADL, dtype=np.float64)

# ㄴ자 자세: 머리에서 아래로 곧게 내려오다가 둥글게 꺾여 땅에 눕고, 누운 몸은 S자로 구불거린다 (뒤로 차지하는 길이를 줄인다)
BEND_R = 3.4                    # 꺾이는 곳의 반지름
LEAN = math.tan(math.radians(9))   # 세운 몸이 뒤로 기울어진 정도
GND = 1.3                       # 땅에 누운 몸 중심의 대략적인 높이
WAVE_A = 5.6                    # 누운 몸의 S자 폭 (옆으로 벌어지는 최대 거리)
WAVE_K = 0.72                   # S자 물결이 촘촘한 정도 (rad / 거리)
WAVE_HOLD = 5.0                 # 꺾이는 곳에서 이만큼 뒤까지는 S자 없이 빳빳하게 곧다
WAVE_RAMP = 5.0                 # 꺾이는 곳에서 이만큼 지나야 S자 폭이 최대가 된다
WAVE_SQ = 1.6                   # 물결 끝을 납작하게 하는 정도
SWIM_SPD = 3.2                  # 이동 중 S자 물결이 꼬리 쪽으로 흘러가는 속도 (rad/s)
WAVE_SPD = 0.45                 # 물결이 꼬리 쪽으로 흘러가는 속도 (rad/s)
BMAX = 34.0
_BG = np.linspace(0.0, BMAX, 341)
_BRAMP = _smooth_np((_BG - WAVE_HOLD) / WAVE_RAMP)
_SK = np.arange(NR) * DSEG
EXTRA_N = 36                    # 접힌 몸의 꼬리 끝 뒤로 이어 붙이는 여분의 궤적 점 수

# 자세: 머리 높이(lift) / 입(jaw) / 목 지느러미(hood) / 고개 숙임(pitch, + 아래) / 몸 물결(und) / 목을 앞으로 뻗는 거리(ext)
#       / 접힘(fold: 1 이면 ㄴ자로 세우고 뒤는 S자로 접은 자세, 0 이면 머리가 지나온 길을 그대로 따라간다)
IDLE = {'lift': 12.5, 'jaw': 0.0, 'hood': 0.0, 'pitch': 0.22, 'und': 0.3, 'ext': 0.0, 'fold': 1.0}
POSES = {
    'idle': {},
    'move': {'lift': 11.5, 'pitch': 0.3, 'und': 1.3, 'fold': 0.0},      # 달릴 때도 목은 세운 채
    'wind': {'lift': 13.5, 'jaw': 0.45, 'hood': 1.0, 'pitch': -0.12, 'und': 0.1, 'ext': -1.5},        # W 돌진 준비: 몸을 쳐들고 노려본다
    'charge': {'lift': 1.6, 'jaw': 1.0, 'hood': 0.3, 'pitch': 0.12, 'und': 0.0, 'ext': 3.5, 'fold': 0.0},   # W 돌진: 낮게 목을 쭉 뻗고 입을 벌려 달려든다
    'lwind': {'lift': 8.0, 'jaw': 0.6, 'hood': 1.0, 'pitch': 0.0, 'und': 0.0, 'ext': -1.0, 'fold': 0.0},   # W 돌진 직전: 몸을 펴며 고개를 낮춘다
    'spit': {'lift': 13.0, 'jaw': 1.0, 'hood': 1.0, 'pitch': 0.42, 'und': 0.2, 'ext': 3.0},          # Q 독 뱉기
    'rear': {'lift': 17.5, 'jaw': 0.35, 'hood': 1.0, 'pitch': -0.3, 'und': 0.12, 'ext': -3.0},       # E 내려찍기 준비: 높이 치솟는다
    'slam': {'lift': 0.95, 'jaw': 1.0, 'hood': 0.7, 'pitch': 0.9, 'und': 0.1},          # E 내려찍기 (ext 는 목표 거리에 맞춘다: slam_reach)
    'rise': {'lift': 13.0, 'jaw': 0.8, 'hood': 1.0, 'pitch': -0.1, 'und': 0.15},         # R 솟구침
    'bite': {'lift': 8.0, 'jaw': 1.0, 'hood': 0.4, 'pitch': 0.45, 'und': 0.3, 'ext': 3.0},   # 평타: 물기 직전
    'snap': {'lift': 3.0, 'jaw': 0.0, 'hood': 0.2, 'pitch': 0.6, 'und': 0.3, 'ext': 8.0},  # 평타: 덥석
    'stagger': {'lift': 2.0, 'jaw': 0.6, 'hood': 0.0, 'pitch': 0.55, 'und': 0.9},
    'crouch': {'lift': 1.8, 'pitch': 0.3, 'und': 0.2},
    'win': {'lift': 14.0, 'jaw': 0.3, 'hood': 1.0, 'pitch': -0.12, 'und': 0.2},
}
RATES = {'lift': 5.0, 'jaw': 12.0, 'hood': 6.0, 'pitch': 8.0, 'und': 3.0, 'ext': 12.0, 'fold': 4.0}
FAST = {'bite': {'jaw': 26, 'lift': 18, 'pitch': 18, 'ext': 26}, 'snap': {'jaw': 40, 'lift': 24, 'pitch': 22, 'ext': 34},
        'slam': {'lift': 34, 'pitch': 26, 'jaw': 26, 'ext': 30}, 'charge': {'lift': 14, 'jaw': 20, 'pitch': 16, 'fold': 16, 'ext': 14},
        'lwind': {'lift': 22, 'jaw': 22, 'pitch': 20, 'ext': 20, 'fold': 30},
        'rise': {'lift': 14, 'jaw': 16}, 'rear': {'lift': 7.0}, 'wind': {'lift': 10.0, 'ext': 8}, 'spit': {'lift': 14.0, 'pitch': 16, 'jaw': 20},
        'move': {'fold': 6.0}}


# ------------------------------------------------------------------ 메시 도구
def _tri_out(b, p0, p1, p2, color, inside):
    """삼각형을 inside(안쪽 한 점) 에서 멀어지는 쪽이 앞면이 되도록 감아 그린다 (볼록한 도형용)."""
    p0, p1, p2 = np.asarray(p0, float), np.asarray(p1, float), np.asarray(p2, float)
    n = np.cross(p1 - p0, p2 - p0)
    if float(np.dot(n, (p0 + p1 + p2) / 3 - inside)) < 0:
        p1, p2 = p2, p1
    b.tri(tuple(p0), tuple(p1), tuple(p2), color)


def _loft(b, rings, color, caps=(True, True), colorfn=None):
    """같은 점 수의 단면(고리) 목록을 이어 도형을 만든다. 단면은 볼록해야 한다.
    colorfn(구간 번호, 단면 점 번호) 가 있으면 조각마다 색을 따로 정한다."""
    n = len(rings[0])
    rings = [np.asarray(r, float) for r in rings]
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        inside = (r0.mean(axis=0) + r1.mean(axis=0)) / 2
        for j in range(n):
            j2 = (j + 1) % n
            col = colorfn(i, j) if colorfn else color
            _tri_out(b, r0[j], r0[j2], r1[j2], col, inside)
            _tri_out(b, r0[j], r1[j2], r1[j], col, inside)
    allc = np.concatenate(rings).mean(axis=0)
    for k, ring in ((0, rings[0]), (1, rings[-1])):
        if not caps[k]:
            continue
        c = ring.mean(axis=0)
        for j in range(n):
            _tri_out(b, c, ring[j], ring[(j + 1) % n], color, allc)


def _spike(b, base, direction, length, radius, color, seg=4):
    """base 에서 direction 쪽으로 뻗는 뾰족한 원뿔."""
    d = np.asarray(direction, float)
    d = d / max(1e-9, float(np.linalg.norm(d)))
    tmp = MeshBuilder()
    tmp.cylinder((0, 0, 0), radius, length, color, seg, radius_top=0.0)
    _xf(b, tmp, _T(*base) @ _from_to((0, 1, 0), d))


def _tube(b, pts, r0, r1, color, seg=6):
    """꺾은선 pts 를 따라 r0 -> r1 로 가늘어지는 관."""
    n = len(pts) - 1
    for i in range(n):
        a, c = np.asarray(pts[i], float), np.asarray(pts[i + 1], float)
        d = c - a
        ln = float(np.linalg.norm(d))
        if ln < 1e-6:
            continue
        ra = r0 + (r1 - r0) * i / n
        rb = r0 + (r1 - r0) * (i + 1) / n
        tmp = MeshBuilder()
        tmp.cylinder((0, 0, 0), ra, ln, color, seg, radius_top=rb)
        _xf(b, tmp, _T(*a) @ _from_to((0, 1, 0), d / ln))


def _ell(b, center, radii, color, seg=10, rings=7, rot=None):
    tmp = MeshBuilder()
    tmp.sphere((0, 0, 0), 1.0, color, seg, rings, radii)
    m = _T(*center)
    if rot is not None:
        m = m @ rot
    _xf(b, tmp, m)


# ------------------------------------------------------------------ 텍스처
def _body_surface():
    """몸 무늬: 가로(u) 0 = 등 한가운데 → 1 = 배 한가운데 (좌우 대칭으로 감김), 세로(v) = 몸을 따라 반복."""
    W, H, K = 128, 256, 2
    xs = np.linspace(0, 1, W * K)[:, None]
    stops = [(0.0, (0.86, 0.90, 0.87)), (0.34, (0.93, 0.95, 0.92)), (0.6, (0.97, 0.98, 0.95)), (1.0, (1.0, 1.0, 0.98))]
    col = np.zeros((W * K, 3))
    for c in range(3):
        col[:, c] = np.interp(xs[:, 0], [s[0] for s in stops], [s[1][c] for s in stops])
    arr = np.repeat(col[:, None, :], H * K, axis=1)
    surf = pygame.surfarray.make_surface((arr * 255).astype(np.uint8)).convert_alpha()

    def X(v):
        return int(v * K)

    # 비늘 격자
    for k in range(-H, W + H, 16):
        pygame.draw.line(surf, (60, 80, 74, 52), (X(k), 0), (X(k + H), X(H)), K)
        pygame.draw.line(surf, (60, 80, 74, 52), (X(k), X(H)), (X(k + H), 0), K)
    # 등의 큰 얼룩: 마디마디 짙은 청록 타원, 가운데는 옅다
    for cy in (64, 192):
        pygame.draw.ellipse(surf, (46, 98, 92, 255), (X(-34), X(cy - 62), X(68), X(124)))
        pygame.draw.ellipse(surf, (150, 190, 176, 255), (X(-34), X(cy - 62), X(68), X(124)), K * 3)
        pygame.draw.ellipse(surf, (126, 172, 160, 235), (X(-19), X(cy - 36), X(38), X(72)))
        pygame.draw.ellipse(surf, (236, 236, 210, 150), (X(-19), X(cy - 36), X(38), X(72)), K)
    # 옆구리의 눈 모양 점
    for cy in (0, 128, 256):
        pygame.draw.ellipse(surf, (50, 72, 68, 255), (X(70 - 15), X(cy - 24), X(30), X(48)))
        pygame.draw.ellipse(surf, (222, 200, 110, 255), (X(70 - 8), X(cy - 13), X(16), X(26)))
    # 배 비늘판
    for y in range(0, H, 8):
        pygame.draw.line(surf, (84, 74, 40, 90), (X(W * 0.74), X(y)), (X(W), X(y)), K)
    return pygame.transform.smoothscale(surf, (W, H))


def _fin_surface():
    """목 지느러미 막: 뿌리 → 가장자리로 갈수록 투명한 청백색, 가는 줄기 무늬."""
    W, H = 128, 64
    xs = np.linspace(0, 1, W)
    r = np.interp(xs, [0, 0.55, 1], [0.96, 0.66, 0.31])
    g = np.interp(xs, [0, 0.55, 1], [0.94, 0.83, 0.60])
    b = np.interp(xs, [0, 0.55, 1], [0.88, 0.81, 0.64])
    a = np.interp(xs, [0, 0.6, 1], [0.95, 0.78, 0.5])
    img = np.zeros((W, H, 4))
    for i, ch in enumerate((r, g, b, a)):
        img[:, :, i] = ch[:, None]
    for i in range(3):
        y = 8 + i * 22
        img[:, y:y + 2, :3] *= 0.7
        img[:, y:y + 2, 3] = np.minimum(1.0, img[:, y:y + 2, 3] + 0.15)
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    rgb = pygame.surfarray.pixels3d(surf)
    rgb[:] = (img[:, :, :3] * 255).astype(np.uint8)
    del rgb
    al = pygame.surfarray.pixels_alpha(surf)
    al[:] = (img[:, :, 3] * 255).astype(np.uint8)
    del al
    return surf


# ------------------------------------------------------------------ 머리 메시 (렌더러당 한 번)
U = [(-1.9, 0.6, 0.36, -0.4), (-1.1, 1.3, 0.56, -0.52), (-0.2, 1.2, 0.58, -0.52), (0.8, 0.8, 0.44, -0.48),
     (1.8, 0.56, 0.3, -0.44), (2.5, 0.42, 0.2, -0.38), (2.95, 0.3, 0.1, -0.3)]
J = [(0.0, 0.62, 0.1, -0.34), (1.0, 0.86, 0.02, -0.4), (2.0, 0.7, -0.02, -0.36), (3.0, 0.5, -0.04, -0.3),
     (3.8, 0.32, -0.06, -0.22)]
JAW_PIVOT = (0.0, -0.34, -1.0)
FANG_PIVOT = (0.58, -0.42, 1.75)
TONGUE_PIVOT = (0.0, -0.36, 2.9)
HOOD_PIVOT = (0.0, -0.05, -1.7)
MOUTH = (0.0, -0.52, 2.9)


def _lerp_u(z, col):
    mult = 1.3 if col == 1 else 1.0
    for i in range(len(U) - 1):
        if z <= U[i + 1][0]:
            return (U[i][col] + (U[i + 1][col] - U[i][col]) * (z - U[i][0]) / (U[i + 1][0] - U[i][0])) * mult
    return U[-1][col] * mult


def _hw_j(z):
    for i in range(len(J) - 1):
        if z <= J[i + 1][0]:
            return (J[i][1] + (J[i + 1][1] - J[i][1]) * (z - J[i][0]) / (J[i + 1][0] - J[i][0])) * 1.3
    return J[-1][1] * 1.3


def _skull_ring(z, hw, top, bot, topc, n=12, p=0.85):
    """머리 단면: 옆구리는 거의 수직이고 정수리가 둥글게 솟은 납작한 타원 (hw 반폭, topc 정수리, bot 턱 쪽 바닥)."""
    yc = (top + bot) / 2
    out = []
    for i in range(n):
        th = i / n * TAU
        c, s_ = math.cos(th), math.sin(th)
        x = hw * math.copysign(abs(c) ** p, c)
        y = yc + (topc - yc) * abs(s_) ** p if s_ >= 0 else yc - (yc - bot) * abs(s_) ** p
        out.append((x, y, z))
    return out


def _ring_bot_y(ring, x):
    """단면의 아랫면 높이를 가로 위치 x 에서 읽는다."""
    mid = sum(q[1] for q in ring) / len(ring)
    pts = sorted((abs(px_), py_) for px_, py_, _ in ring if py_ <= mid)
    return float(np.interp(abs(x), [q[0] for q in pts], [q[1] for q in pts]))


def _ring_top_y(ring, x):
    """단면의 윗면(정수리 쪽) 높이를 가로 위치 x 에서 읽는다."""
    pts = sorted((abs(px_), py_) for px_, py_, _ in ring if py_ >= sum(q[1] for q in ring) / len(ring))
    return float(np.interp(abs(x), [q[0] for q in pts], [q[1] for q in pts]))


def _head_static(k=0.92):
    """머리에 붙어 같이 움직이는 부분: 두개골, 머리 위 판갑, 콧구멍, 입천장, 윗니, 광대 가시."""
    b = MeshBuilder()
    skull, plate = _hex(0xF2F2EA, k), _hex(0xA9CBBF, k)
    dark, bone, throat = (0.03, 0.07, 0.03), _hex(0xE8DCB0, k), (0.5, 0.07, 0.13)
    def ring_at(z):
        return _skull_ring(z, _lerp_u(z, 1), _lerp_u(z, 2), _lerp_u(z, 3), _lerp_u(z, 2) + (0.2 if -1.4 < z < 1.2 else 0.08))
    rings = [ring_at(z) for z, *_ in U]
    rings.append(_skull_ring(3.12, 0.16, 0.04, -0.2, 0.08))                # 둥근 코끝
    zs = [z for z, *_ in U]

    def crown(i, j):                                                     # 정수리 한가운데 두 조각은 짙은 청록 띠 (이마의 판갑)
        return plate if (j in (2, 3) and -1.3 < zs[i] < 2.2) else skull
    _loft(b, rings, skull, colorfn=crown)
    for sx in (-1, 1):
        _ell(b, (sx * 0.26, 0.22, 2.7), (0.12, 0.085, 0.17), dark, 6, 5)                # 콧구멍
    _ell(b, (0, -0.46, 1.3), (0.5, 0.1, 1.3), throat, 8, 5)                              # 입천장 (입이 벌어지면 붉게 드러난다)
    for i, z in enumerate((0.9, 1.35, 1.8, 2.25, 2.65)):                                 # 윗니
        for sx in (-1, 1):
            tx = _lerp_u(z, 1) * 0.78
            _spike(b, (sx * tx, _ring_bot_y(ring_at(z), tx) + 0.04, z), (sx * 0.05, -1, 0.2), 0.28 + i * 0.02, 0.07, bone)
    for sx in (-1, 1):                                                                   # 턱 관절 뒤로 뻗는 광대 가시
        for i in range(2):
            _spike(b, (sx * 1.17, -0.08 - i * 0.2, -1.0 - i * 0.26), (sx * 0.9, -0.1 - 0.1 * i, -0.6), 0.5 - i * 0.14,
                   0.12 - i * 0.025, plate, 5)
    return b


def _head_jaw(k=0.92):
    """아래턱 (턱 관절 JAW_PIVOT 기준): 턱뼈, 턱 밑의 옅은 능선, 혀 받침, 아랫니."""
    b = MeshBuilder()
    skull, chin = _hex(0xF2F2EA, k), _hex(0xFCFAF0, k)
    bone, throat = _hex(0xE8DCB0, k), (0.5, 0.07, 0.13)
    rings = []
    for z, hw0, top, bot in J:
        hw = hw0 * 1.3
        rings.append([(hw, top, z), (hw, bot, z), (hw * 0.5, bot - 0.05, z), (-hw * 0.5, bot - 0.05, z), (-hw, bot, z),
                      (-hw, top, z)])
    _loft(b, rings, skull)
    _loft(b, [[(-0.52, -0.34, 0.6), (0.52, -0.34, 0.6), (0, -0.46, 0.6)],
              [(-0.65, -0.46, 2.0), (0.65, -0.46, 2.0), (0, -0.58, 2.0)],
              [(-0.26, -0.36, 3.65), (0.26, -0.36, 3.65), (0, -0.42, 3.72)]], chin)
    _ell(b, (0, 0.04, 1.9), (0.5, 0.1, 1.4), throat, 8, 5)
    for i, z in enumerate((1.4, 1.85, 2.3, 2.75, 3.2)):                                  # 아랫니
        for sx in (-1, 1):
            _spike(b, (sx * _hw_j(z) * 0.78, 0.0, z), (-sx * 0.05, 1, 0.15), 0.24 + i * 0.015, 0.06, bone)
    return b


def _head_fang(k=0.92):
    b = MeshBuilder()
    _tube(b, [(0, 0, 0), (0, -0.58, 0.04), (0, -1.3, 0.22)], 0.15, 0.012, _hex(0xE8DCB0, k), 6)
    return b


def _head_tongue():
    b = MeshBuilder()
    col = (0.74, 0.1, 0.25)
    _tube(b, [(0, 0, 0), (0, 0, 1.1), (0, 0, 2.1)], 0.075, 0.05, col, 5)
    return b


def _head_tine(sx):
    b = MeshBuilder()
    _tube(b, [(0, 0, 0), (sx * 0.05, 0, 0.8), (sx * 0.26, 0, 1.6)], 0.05, 0.005, (0.74, 0.1, 0.25), 4)
    return b


def _head_eye():
    b = MeshBuilder()
    _ell(b, (0, 0, 0), (0.5, 0.24, 0.14), (1.0, 1.0, 1.0), 10, 6)
    return b


def _head_gem():
    """이마의 마름모 비늘 (청록으로 빛난다)."""
    b = MeshBuilder()
    pts = [(0, 0.64, 1.05), (0.44, 0.6, 0.55), (0, 0.6, 0.0), (-0.44, 0.6, 0.55)]
    c = np.array([0, 0.67, 0.55])
    for i in range(4):
        _tri_out(b, c, pts[i], pts[(i + 1) % 4], (1.0, 1.0, 1.0), np.array([0, 0.3, 0.55]))
    return b


def _fin_parts():
    """목 지느러미 한 장 (뿌리가 원점, +x 가 바깥): 막 (텍스처) 과 줄기 (뼈 색)."""
    N = 3
    roots, tips = [], []
    for k in range(N):
        t = k / (N - 1)
        a = (t - 0.5) * 1.7
        ln = 3.4 + 0.6 * math.sin(PI * t)
        r = (0.0, 0.15 + 0.25 * math.sin(a), -0.1 * t)
        d = (math.cos(a), math.sin(a), -0.12 - 0.1 * t)
        roots.append(r)
        tips.append((r[0] + d[0] * ln, r[1] + d[1] * ln, r[2] + d[2] * ln))
    mem = MeshBuilder()
    white = (1.0, 1.0, 1.0)
    for k in range(N - 1):
        rm = [(roots[k][i] + roots[k + 1][i]) / 2 for i in range(3)]
        tm = [(tips[k][i] + tips[k + 1][i]) / 2 for i in range(3)]
        mm = tuple(rm[i] + (tm[i] - rm[i]) * 0.62 for i in range(3))
        mem.tri(roots[k], tips[k], mm, white, uva=(0, 0), uvb=(1, 0), uvc=(0.62, 0.5))
        mem.tri(roots[k], mm, roots[k + 1], white, uva=(0, 0), uvb=(0.62, 0.5), uvc=(0, 1))
        mem.tri(roots[k + 1], mm, tips[k + 1], white, uva=(0, 1), uvb=(0.62, 0.5), uvc=(1, 1))
    ribs = MeshBuilder()
    bone = _hex(0xE8DCB0, 0.92)
    for k in range(N):
        o, tp = roots[k], tips[k]
        d = (tp[0] - o[0], tp[1] - o[1], tp[2] - o[2])
        _spike(ribs, o, d, math.hypot(*d) * 1.12, 0.075, bone, 4)
    return mem, ribs


class SerpentAssets:
    def __init__(self, renderer):
        self.r = renderer
        mk = lambda b: Mesh.from_builder(renderer, b)
        self.head, self.jaw, self.fang = mk(_head_static()), mk(_head_jaw()), mk(_head_fang())
        self.tongue, self.tine_l, self.tine_r = mk(_head_tongue()), mk(_head_tine(1)), mk(_head_tine(-1))
        self.eye, self.gem = mk(_head_eye()), mk(_head_gem())
        self.body_tex = renderer.make_texture(_body_surface())
        self.fin_tex = renderer.make_texture(_fin_surface())
        mem, ribs = _fin_parts()
        self.fin = Mesh(renderer, [(mem.array(), self.fin_tex)])
        self.ribs = mk(ribs)
        sh = MeshBuilder()
        sh.disc((0, 0, 0), 1.0, (0, 0, 0), 18)
        self.shadow = mk(sh)
        ch = MeshBuilder()
        ch.sphere((0, 0, 0), 1.0, (0.78, 0.86, 0.8), 8, 6)
        self.chunk = mk(ch)
        # 몸통 관의 위상 (정점 배열의 모양). 위치·법선은 매 프레임 채운다.
        a = (np.arange(NR - 1)[:, None] * VW + np.arange(M)[None, :]).ravel()
        b_, c, d = a + 1, a + VW, a + VW + 1
        self.idx = np.stack([a, c, b_, b_, c, d], axis=1).ravel()
        j = np.arange(VW)
        half = np.where(j <= M // 2, j, M - j)
        uv = np.zeros((NR * VW, 2))
        for k in range(NR):
            uv[k * VW:(k + 1) * VW, 0] = half / (M / 2)
            uv[k * VW:(k + 1) * VW, 1] = (k * DSEG) / 7.0
        tmpl = np.zeros((len(self.idx), 11), dtype="f4")
        tmpl[:, 6:9] = 1.0
        tmpl[:, 9:11] = uv[self.idx]
        self.template = tmpl
        self._pool = []

    def take_tube(self):
        if self._pool:
            return self._pool.pop()
        return Mesh(self.r, [(self.template, self.body_tex)])

    def recycle(self, mesh):
        self._pool.append(mesh)


class _Debris:
    __slots__ = ("mesh", "base", "pos", "ang", "vel", "spin", "tint", "unlit", "rest", "r", "col")


class SerpentAnim:
    bar_h = 3.4 * CHAMP_SCALE * BIG_SCALE + 0.2                             # 게임 장면이 체력바를 달 높이 (세운 머리 위)
    pick_h = 2.8 * CHAMP_SCALE * BIG_SCALE                                 # 마우스로 고를 수 있는 높이

    def __init__(self, assets):
        self.a = assets
        self.tube = assets.take_tube()
        weakref.finalize(self, assets.recycle, self.tube)
        self.t = 0.0
        self.cur = dict(IDLE)
        self.tgt = dict(IDLE)
        self.rate = dict(RATES)
        self.pose_name = 'idle'
        self.px = self.pz = 0.0
        self.yaw = 0.0
        self.s_mix = 0.0
        self.ph_t = 0.0
        self.fold_t = 5.0                                       # 접히는 중인 시간
        self.moving = False
        self.still_t = 0.0
        self.rx = self.rz = None                                # 마디의 (프레임 사이에 이어지는) 위치
        self.rang = None                                        # 이동 중 마디 방향 (묵직하게 돌아서게)
        self.lunge_until = -1.0                                 # W 돌진 자세(몸을 곧게 편다)가 끝나는 시각
        self.se_last = 0.0                                      # 세운 목이 끝나는 곳 (머리에서 몸을 따라 잰 거리)
        self.ofs = None                                         # 그릴 때 더하는 월드 이동 (몸통 고정 구간이 챔피언 자리에 오게)
        self.ent_w = (0.0, 0.0)                                 # 챔피언 자리 (월드 x, z)
        self.extra = None                                       # 겹침으로 올라탄 높이 (프레임 사이 부드럽게)
        self.dt_last = 1.0                                      # 마지막 프레임 시간 (접힘 속도 계산용)
        self.fold_rate = 4.0
        self.byaw = 0.0                                         # 접힌 몸이 따르는 방향 (머리 방향을 천천히 따라간다)
        self.vel = [0.0, 0.0]
        self.speed = 0.0
        self.lift = 0.0                                         # 게임 장면이 그림자 크기에 쓰는 값 (뱀은 뜨지 않는다)
        self.have_pos = False
        self.seq = []                                           # [(끝나는 시각, 자세 이름)]
        self.seq_end = 0.0
        self.last_attack = -9.0
        self.slam_tgt = None                                    # 내려찍기 목표 (보스 단위 x, z): 이동하며 돌아도 머리는 이쪽을 찍는다
        self.slam_reach = 12.0                                  # 내려찍기 때 목을 뻗는 거리 (보스 단위)
        self.won = False
        self.was_dead = False
        self.dead_clock = 0.0
        self.debris = []
        # 궤적 (원형 버퍼)
        self.trx = np.zeros(CAP)
        self.trz = np.zeros(CAP)
        self.trHead = 0
        self.trCount = 0
        self.lastX = self.lastZ = 0.0
        # 잠행 물결
        self.wave = 'none'
        self.waveT = 0.0
        self.wave_speed = 90.0
        self.baseSub = 0.0
        self.auto_emerge = None
        # 고리 상태
        self.cxL = [0.0] * NR
        self.cyL = [0.0] * NR
        self.czL = [0.0] * NR
        self.subL = [0.0] * NR
        self.py = np.zeros(NR)
        self.fn = np.zeros((NR, 3))
        self.fb = np.zeros((NR, 3))
        self.ft = np.zeros((NR, 3))
        self.buf = assets.template.copy()
        # 머리
        self.jaw_cur = 0.0
        self.hood_cur = 0.0
        self.flicking = False
        self.flickT = 9.0
        self.nextFlick = 1.0
        self.ext = 0.0
        self.tongue_rx = 0.1
        self.tongue_ry = 0.0
        self.spread = 0.05
        self.hit_flash = 0.0
        self.M_head = np.eye(4)
        self.head_vis = True
        self.mats = {}
        self.lift_cur = max(HEAD_REST, self.cur['lift'])
        self.layout_line(0.0, 0.0, 0.0)
        self._solve_body()
        self._place_head(0.0)

    # ------------------------------------------------------------ 외부 API (게임·선택 장면이 부른다)
    def _play(self, steps):
        """steps = [(길이(초), 자세 이름), ...] 를 차례로 보여 준다."""
        t = self.t
        self.seq = []
        for dur, name in steps:
            t += max(0.02, dur)
            self.seq.append((t, name))
        self.seq_end = t

    def cast(self, slot):
        if slot == "Q":                                         # 몸을 쳐들었다가 독을 뱉는다
            self._play([(0.2, 'wind'), (0.45, 'spit')])
        elif slot == "W":                                       # 노려본 뒤 돌진 (on_fx('lunge') 가 정확한 시간으로 덮어쓴다)
            self._play([(0.08, 'lwind'), (0.5, 'charge')])
        elif slot == "E":                                       # 높이 치솟았다가 내려찍는다
            self._play([(0.6, 'rear'), (0.45, 'slam')])
        elif slot == "R":
            if self.wave == 'none' and self.baseSub < 1:
                self.dive(0.6)
                self.auto_emerge = self.t + 1.5                 # 서버 이벤트가 없을 때(미리보기)를 위한 안전장치

    def on_fx(self, kind, ev):
        if kind == "lunge":
            # 돌진: 고개를 돌진 방향으로 홱 돌리고, 지나온 길을 머리 뒤 일직선으로 바꿔 S자로 접혀 있던 몸이 쭉 펴지며 따라오게 한다
            delay = float(ev.get("delay", 0.1))
            dur = float(ev.get("dur", 0.3))
            if "x2" in ev:
                dx, dz = ev["x2"] - ev["x"], ev["z2"] - ev["z"]
                if math.hypot(dx, dz) > 0.1:
                    self.yaw = self.byaw = math.atan2(dx, dz)
            self._straight_trail(self.yaw)
            self.lunge_until = self.t + delay + dur + 0.25
            self._play([(delay, 'lwind'), (dur + 0.12, 'charge')])
        elif kind == "serpent_rear":
            if "x2" in ev:
                self.slam_tgt = self.to_rig(ev["x2"], ev["z2"])
                self.slam_reach = min(math.hypot(ev["x2"] - ev["x"], ev["z2"] - ev["z"]), SLAM_REACH) / SC
            self._play([(float(ev.get("dur", 0.75)), 'rear'), (0.45, 'slam')])
        elif kind == "dive":
            sink = float(ev.get("sink", 0.6))
            self.dive(sink)
            self.seq = []
            self.auto_emerge = self.t + sink + float(ev.get("dur", 0.8)) + 0.8
        elif kind == "dive_out":
            self.emerge()
            self._play([(0.55, 'rise')])
            self.auto_emerge = None

    def aim_slam(self, x, z):
        """내려찍기 목표를 (월드 좌표) 대상의 지금 위치로 옮긴다 (대상 지정 E: 쳐든 머리가 대상을 따라간다)."""
        if self.slam_tgt is not None:
            self.slam_tgt = self.to_rig(x, z)

    def leap(self, dur, delay=0.0):
        pass

    def play_key(self, key):
        if key == "attack":
            self.attack()
        else:
            self.cast(key)

    def attack(self, windup=0.0):
        self.last_attack = self.t
        self._play([(0.15, 'bite'), (0.2, 'snap')])

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

    def _draw_scale(self):
        ox, oz = self.ofs if self.ofs is not None else (0.0, 0.0)
        return _T(ox, 0.0, oz) @ _SCALE

    def to_rig(self, x, z):
        """월드 좌표 -> 리그 안쪽 좌표 (보스 단위). 그릴 때 더하는 이동(ofs)을 뺀다."""
        ox, oz = self.ofs if self.ofs is not None else (0.0, 0.0)
        return ((x - ox) / SC, (z - oz) / SC)

    def _update_pin(self, dt):
        """몸통 고정 구간(PIN_K0~PIN_K1)의 가운데가 챔피언 자리에 오도록 그릴 때의 이동(ofs)을 정한다."""
        n = PIN_K1 - PIN_K0
        bx = sum(self.cxL[PIN_K0:PIN_K1]) / n * SC
        bz = sum(self.czL[PIN_K0:PIN_K1]) / n * SC
        tx, tz = self.ent_w[0] - bx, self.ent_w[1] - bz
        if self.ofs is None or math.hypot(tx - self.ofs[0], tz - self.ofs[1]) > 3.0:
            self.ofs = (tx, tz)
        else:
            k = 1 - math.exp(-PIN_RATE * dt)
            self.ofs = (self.ofs[0] + (tx - self.ofs[0]) * k, self.ofs[1] + (tz - self.ofs[1]) * k)

    def mouth(self):
        """머리 앞 입의 월드 위치 (독 뱉기 발사점): (x, y, z)"""
        p = self._draw_scale() @ self.M_head @ np.array([MOUTH[0], MOUTH[1], MOUTH[2], 1.0])
        return float(p[0]), float(p[1]), float(p[2])

    # ------------------------------------------------------------ 잠행
    def dive(self, dur=0.6):
        """머리부터 차례로 땅속으로 (dur 초 안에 꼬리까지)."""
        self.wave = 'dive'
        self.waveT = 0.0
        self.wave_speed = BODY_LEN / max(0.2, dur - WAVE_RISE)

    def emerge(self, dur=0.55):
        """머리부터 차례로 땅 위로."""
        self.wave = 'emerge'
        self.waveT = 0.0
        self.baseSub = 1.0
        self.wave_speed = BODY_LEN / max(0.2, dur - WAVE_RISE)

    @property
    def underground(self):
        return self.wave == 'none' and self.baseSub >= 1

    # ------------------------------------------------------------ 궤적
    def _set_trail(self, pts):
        n = min(CAP, len(pts) // 2 - 1)
        self.px, self.pz = pts[0], pts[1]
        self.trCount = n
        for i in range(n, 0, -1):
            slot = n - i
            self.trx[slot] = pts[i * 2]
            self.trz[slot] = pts[i * 2 + 1]
        self.trHead = n - 1
        self.lastX, self.lastZ = self.px, self.pz

    def _straight_trail(self, yaw):
        """지나온 길만 머리 뒤 일직선으로 바꾼다 (지금 보이는 몸 모양은 그대로 두어, 그 모양에서 곧게 펴지며 따라온다)."""
        dx, dz = math.sin(yaw), math.cos(yaw)
        N = int(math.ceil((BODY_LEN + 12) / TS))
        pts = []
        for i in range(N + 1):
            pts += [self.px - dx * i * TS, self.pz - dz * i * TS]
        self._set_trail(pts)
        self.rang = None

    def layout_line(self, x, z, yaw):
        """머리 뒤로 일직선으로 놓는다. yaw 는 머리가 향하는 방향 (앞 = (sin yaw, cos yaw))."""
        dx, dz = math.sin(yaw), math.cos(yaw)
        N = int(math.ceil((BODY_LEN + 12) / TS))
        pts = []
        for i in range(N + 1):
            pts += [x - dx * i * TS, z - dz * i * TS]
        self._set_trail(pts)
        self.rx = self.rz = None
        self.rang = None

    def _push_trail(self):
        """머리가 이번 프레임에 간 만큼 궤적에 점을 더한다."""
        n = self.trCount
        last = self.trHead % CAP
        lx = self.trx[last] if n > 0 else self.lastX
        lz = self.trz[last] if n > 0 else self.lastZ
        dx, dz = self.px - lx, self.pz - lz
        d = math.hypot(dx, dz)
        if d >= TS:
            steps = min(int(d // TS), 400)
            ux, uz = dx / d, dz / d
            for i in range(1, steps + 1):
                self.trHead = (self.trHead + 1) % CAP
                self.trx[self.trHead] = lx + ux * i * TS
                self.trz[self.trHead] = lz + uz * i * TS
                if self.trCount < CAP:
                    self.trCount += 1
        self.lastX, self.lastZ = self.px, self.pz

    # ------------------------------------------------------------ 몸
    def _solve_body(self):
        """궤적 위에 고리들을 놓고, 겹침을 쌓고, 관 정점을 쓴다."""
        n = self.trCount
        ids = (self.trHead - np.arange(n)) % CAP
        px = np.empty(n + 1)
        pz = np.empty(n + 1)
        px[0], pz[0] = self.px, self.pz
        px[1:] = self.trx[ids]
        pz[1:] = self.trz[ids]
        cum = np.zeros(n + 1)
        np.cumsum(np.hypot(np.diff(px), np.diff(pz)), out=cum[1:])

        L = self.lift_cur
        t = self.t
        und = self.cur['und']
        self.ph_t += self.dt_last * (WAVE_SPD + SWIM_SPD * _smooth(self.s_mix) * min(1.0, self.speed / 3.0))
        hp, sp, y, se = self._pose_curve(L)               # 세운 목(ㄴ자)의 높이 모양: 움직일 때도 목은 이 모양으로 선다
        self.se_last = se
        self.py[:] = y
        sway_amp = min(0.7, max(0.0, (L - 2) * 0.07))

        k = np.arange(NR)
        sg = k * DSEG
        u = sg / max(se, 1.0)
        # 높이가 거의 수직인 마디도 뒤로 조금 기울여 궤적 위에 놓는다 (세운 목이 달릴 때 뒤로 살짝 눕는다)
        dy = np.clip(np.diff(y), -math.cos(math.radians(9)), math.cos(math.radians(9)))
        # 달릴 때도 서 있을 때와 같은 S자 모양을 유지한다: 머리 뒤로 떨어진 거리(hp)만큼 지나온 길 위에 놓고, 옆으로 벌어진 만큼(sp)을 길의 옆쪽으로 민다.
        Ha = np.zeros(NR)                                  # 접혀 있던 몸은 길이 그대로 곧게 풀리며 시작하고, 곧 S자 모양으로 바뀐다
        np.cumsum(np.sqrt(np.maximum(0.0036, DSEG * DSEG - dy * dy)), out=Ha[1:])
        if self.t < self.lunge_until:                      # 돌진 중: S자 물결을 빨리 거둬 몸이 일직선으로 쭉 펴진다
            mx = self.s_mix = max(0.0, self.s_mix - self.dt_last * 12.0)
        else:
            mx = self.s_mix = (0.0 if self.tgt['fold'] > 0.5 else min(1.0, self.s_mix + self.dt_last * 1.6))
        mx = _smooth(mx)
        H = Ha * (1 - mx) + hp * mx
        wob = sp * mx
        m = np.clip(np.searchsorted(cum, H, side='left') - 1, 0, n - 1)
        seg_l = cum[m + 1] - cum[m]
        good = seg_l > 1e-6
        safe = np.where(good, seg_l, 1.0)
        tt = np.minimum(np.where(good, (H - cum[m]) / safe, 0.0), 1.5)
        x = px[m] + (px[m + 1] - px[m]) * tt
        zz = pz[m] + (pz[m + 1] - pz[m]) * tt
        # 접선: 선분이 퇴화한 곳에서는 앞 고리의 것을 이어받는다
        sx0, sz0 = px[0] - px[1], pz[0] - pz[1]
        sl = math.hypot(sx0, sz0)
        t0x, t0z = (sx0 / sl, sz0 / sl) if sl > 1e-6 else (math.sin(self.yaw), math.cos(self.yaw))
        src = np.maximum.accumulate(np.where(good, k, -1))
        valid = src >= 0
        src_c = np.maximum(src, 0)
        tdx_raw = np.where(good, (px[m] - px[m + 1]) / safe, 0.0)
        tdz_raw = np.where(good, (pz[m] - pz[m + 1]) / safe, 0.0)
        tdx = np.where(valid, tdx_raw[src_c], t0x)
        tdz = np.where(valid, tdz_raw[src_c], t0z)
        if self.tgt['fold'] <= 0.5 and self.rx is not None:
            # 달릴 때: 세운 목까지는 지나온 길 그대로, 그 뒤 몸은 꼬리로 갈수록 늦게 돌아서고 빳빳해서
            # 제자리에서 빙빙 돌아도 길을 따라 작게 꼬이지 않고 묵직하게 끌려온다 (S자 물결은 그 위에 얹는다)
            lunging = self.t < self.lunge_until             # 돌진 중에는 몸이 머리를 바짝 따라 곧게 끌려온다
            x, zz, self.rang = heavy_chain(self.rang, x, zz, int(se / DSEG) + 2, self.dt_last,
                                           BODY_TURN * (3 if lunging else 1), TAIL_TURN * (6 if lunging else 1),
                                           None if lunging else BODY_BEND)
            gx_ = np.empty(NR)
            gz_ = np.empty(NR)
            gx_[1:-1], gz_[1:-1] = x[:-2] - x[2:], zz[:-2] - zz[2:]
            gx_[0], gz_[0] = x[0] - x[1], zz[0] - zz[1]
            gx_[-1], gz_[-1] = x[-2] - x[-1], zz[-2] - zz[-1]
            gl_ = np.hypot(gx_, gz_)
            ok_ = gl_ > 1e-6
            tdx = np.where(ok_, gx_ / np.where(ok_, gl_, 1.0), tdx)
            tdz = np.where(ok_, gz_ / np.where(ok_, gl_, 1.0), tdz)
        else:
            self.rang = None
        x = x + (-tdz) * wob
        zz = zz + tdx * wob
        # ㄴ자로 세우고 뒤는 S자로 접은 자세 (fold 가 클수록 이 자세, 0 이면 궤적 그대로)
        # 마디 위치는 프레임 사이에 이어지는 값(rx, rz)으로 들고 있고, 목표 모양으로 부드럽게 다가간다.
        #  - 서 있을 때: 목표 = ㄴ자 + S자 자세 (처음엔 살살, 점점 빠르게 접힌다)
        #  - 달릴 때: 목표 = 머리가 지나온 길 위의 자리 (바짝 따라간다)
        # 서 있는 동안에는 지금 몸 모양을 궤적에 덮어써 두므로, 달리기 시작하면 그 모양에서 줄을 끌어당기듯 펴진다.
        dtl = self.dt_last
        folded = self.tgt['fold'] > 0.5
        if folded:
            fx, fz = math.sin(self.byaw), math.cos(self.byaw)
            tx_ = self.px - fx * hp + fz * sp
            tz_ = self.pz - fz * hp - fx * sp
            kf = self.fold_rate
            vlim = 2.5 + 9.0 * _smooth(self.fold_t / 0.8)
        else:
            tx_, tz_, kf, vlim = x, zz, 25.0, 45.0 + 2.0 * self.speed      # 돌진처럼 머리가 아주 빠를 때는 몸 마디도 그만큼 빨리 따라와야 목이 늘어나지 않는다
        if self.rx is None:
            self.rx, self.rz = tx_.copy(), tz_.copy()
        else:
            ddx = (tx_ - self.rx) * (1 - math.exp(-kf * dtl))
            ddz = (tz_ - self.rz) * (1 - math.exp(-kf * dtl))
            sc = np.minimum(1.0, vlim * dtl / np.maximum(np.hypot(ddx, ddz), 1e-9))
            self.rx = self.rx + ddx * sc
            self.rz = self.rz + ddz * sc
        self.rx[0], self.rz[0] = self.px, self.pz
        x, zz = self.rx.copy(), self.rz.copy()
        if folded:
            self._rewrite_trail(x, zz)
        ex = self.cur['ext']                               # 목을 앞으로 뻗는다 (내려찍기·물기): 머리 쪽 마디일수록 많이 끌려 나온다
        if abs(ex) > 1e-3:
            fall = ex * (1 - _smooth_np(sg / EXT_SPAN))
            x = x + math.sin(self.yaw) * fall
            zz = zz + math.cos(self.yaw) * fall
        # 잠행 물결
        if self.wave != 'none':
            kk = _smooth_np((self.waveT - sg / self.wave_speed) / WAVE_RISE)
            sb = kk if self.wave == 'dive' else 1 - kk
        else:
            sb = np.full(NR, self.baseSub)

        cyl = self._stack_body(x, y, zz, sb)
        extra = np.array(cyl) - y
        if self.extra is None:
            self.extra = extra
        else:
            self.extra += (extra - self.extra) * (1 - math.exp(-9.0 * self.dt_last))
        cyl = (y + self.extra).tolist()
        cy = np.array(cyl) * (1 - sb) - sb * (2 * RAD + 1.8)      # 잠길 때는 세운 몸도 땅속으로 곧게 가라앉는다
        self.cxL, self.czL, self.cyL, self.subL = x.tolist(), zz.tolist(), cy.tolist(), sb.tolist()

        # 고리 틀: T(접선) / N(위쪽 기준) / B = T × N
        ia = np.maximum(k - 1, 0)
        ib = np.minimum(k + 1, NR - 1)
        T = np.stack([x[ia] - x[ib], cy[ia] - cy[ib], zz[ia] - zz[ib]], axis=1)
        Tl = np.linalg.norm(T, axis=1)
        Tl[Tl == 0] = 1.0
        T /= Tl[:, None]
        Tx, Ty, Tz = T[:, 0], T[:, 1], T[:, 2]
        wl = np.sqrt(np.maximum(0.0, 1 - Ty * Ty))
        wlc = np.maximum(wl, 1e-9)
        Wv = np.stack([-Ty * Tx / wlc, (1 - Ty * Ty) / wlc, -Ty * Tz / wlc], axis=1)
        Wn = np.linalg.norm(Wv, axis=1)
        Wn[Wn == 0] = 1.0
        Wv /= Wn[:, None]
        wgt = np.where(wl > 0.3, _smooth_np((wl - 0.3) / 0.4), 0.0)
        Nn = Wv.copy()
        seq = np.nonzero(wgt < 1.0)[0].tolist()           # 거의 수직으로 솟은 곳은 앞 고리의 방향을 이어받는다 (순차 계산)
        if seq:
            Tl_, Wl_, wg_, nl = T.tolist(), Wv.tolist(), wgt.tolist(), Nn.tolist()
            for kk_ in seq:
                nx, ny, nz = (0.0, 1.0, 0.0) if kk_ == 0 else nl[kk_ - 1]
                tx, ty, tz = Tl_[kk_]
                dotp = nx * tx + ny * ty + nz * tz
                pnx, pny, pnz = nx - dotp * tx, ny - dotp * ty, nz - dotp * tz
                pl = math.sqrt(pnx * pnx + pny * pny + pnz * pnz)
                if pl < 1e-4:
                    pnx, pny, pnz = -ty * tx, 1 - ty * ty, -ty * tz
                    pl = math.sqrt(pnx * pnx + pny * pny + pnz * pnz) or 1.0
                pnx, pny, pnz = pnx / pl, pny / pl, pnz / pl
                w = wg_[kk_]
                if w > 0:
                    wx, wy, wz = Wl_[kk_]
                    pnx, pny, pnz = pnx * (1 - w) + wx * w, pny * (1 - w) + wy * w, pnz * (1 - w) + wz * w
                    l2 = math.sqrt(pnx * pnx + pny * pny + pnz * pnz) or 1.0
                    pnx, pny, pnz = pnx / l2, pny / l2, pnz / l2
                nl[kk_] = [pnx, pny, pnz]
            Nn = np.array(nl)
        Bv = np.cross(T, Nn)
        self.fn[:] = Nn
        self.fb[:] = Bv
        self.ft[:] = T

        j = np.arange(VW)
        th = j / M * TAU
        s, c = np.sin(th), np.cos(th)
        ry = RAD[:, None] * c[None, :] * np.where(c > 0, 1.06, 0.8)[None, :]
        rx = RAD[:, None] * s[None, :]
        off = Nn[:, None, :] * ry[:, :, None] + Bv[:, None, :] * rx[:, :, None]
        ctr = np.stack([x, cy, zz], axis=1)
        P = (ctr[:, None, :] + off).reshape(-1, 3)
        ln = np.linalg.norm(off, axis=2, keepdims=True)
        ln[ln < 1e-6] = 1.0
        Nrm = (off / ln).reshape(-1, 3)
        idx = self.a.idx
        self.buf[:, 0:3] = P[idx]
        self.buf[:, 3:6] = Nrm[idx]
        self.tube.parts[0][1].write(self.buf.tobytes())

    def _pose_curve(self, L):
        """ㄴ자 자세의 마디 위치: 머리 기준 뒤쪽 거리 h, 옆 거리 side, 높이 y (보스 단위).
        머리 높이 L 에서 아래로 곧게 내려오다가 반지름 BEND_R 로 꺾여 땅에 눕고, 누운 몸은 S자로 구불거리며 꼬리까지 이어진다."""
        s = _SK
        D = max(0.3, L - GND)
        Rb = min(BEND_R, 0.5 * D)
        sc = D - Rb                                        # 곧게 내려오는 길이
        se = sc + 0.5 * PI * Rb                            # 꺾임이 끝나는 곳
        phi = np.clip((s - sc) / Rb, 0.0, 0.5 * PI)
        c = np.where(s <= sc, L - s, GND + Rb * (1 - np.sin(phi)))
        h = np.where(s > sc, Rb * (1 - np.cos(phi)), 0.0)
        # 누운 몸: 옆으로 흔들리는 폭 lat(b) 를 앞뒤 거리 b 의 함수로 두고, 호 길이로 다시 매겨 마디 간격을 지킨다
        t = self.t
        amp = WAVE_A * (1 + 0.04 * math.sin(t * 0.5)) * _BRAMP
        ph = np.sin(WAVE_K * _BG * (1 + 0.02 * _BG) - self.ph_t)
        lat = amp * np.tanh(WAVE_SQ * ph) / math.tanh(WAVE_SQ)      # 끝이 납작한 물결: 옆으로 확 틀었다가 홱 되돌아온다
        dl = np.gradient(lat, _BG)
        arc = np.zeros_like(_BG)
        np.cumsum(np.sqrt(1 + dl * dl)[1:] * (_BG[1] - _BG[0]), out=arc[1:])
        sig = np.maximum(0.0, s - se)
        h = h + np.interp(sig, arc, _BG)
        side = np.interp(sig, arc, lat)
        bump = np.sin(PI * np.clip(s / max(se, 1.0), 0.0, 1.0))      # 세운 몸이 좌우로 살랑이는 정도 (머리·꺾임에서는 0)
        side = side + 0.5 * math.sin(t * 1.1) * bump * min(1.0, D / 6.0)
        h = h + LEAN * (L - c)
        return h, side, np.maximum(c, RAD * 0.8), se

    def _rewrite_trail(self, x, zz):
        """궤적을 지금 몸의 모양(머리 다음 마디부터 꼬리 끝, 그 뒤는 꼬리 방향으로 곧게)으로 덮어쓴다."""
        tx, tz = x[-1] - x[-2], zz[-1] - zz[-2]
        ln = math.hypot(tx, tz)
        if ln < 1e-6:
            tx, tz, ln = -math.sin(self.byaw), -math.cos(self.byaw), 1.0
        tx, tz = tx / ln, tz / ln
        e = np.arange(1, EXTRA_N + 1) * 1.0
        X = np.concatenate([x[1:], x[-1] + tx * e])
        Z = np.concatenate([zz[1:], zz[-1] + tz * e])
        m = len(X)
        self.trx[:m] = X[::-1]
        self.trz[:m] = Z[::-1]
        self.trHead = m - 1
        self.trCount = m

    def _stack_body(self, x, y, zz, sb):
        """몸이 자기 몸과 겹치는 곳: 머리 쪽 몸이 꼬리 쪽 몸 위로 곡선을 그리며 올라탄다. 높이 리스트를 돌려준다."""
        gxa = np.floor((x - self.px) / GCELL).astype(np.int64).tolist()
        gza = np.floor((zz - self.pz) / GCELL).astype(np.int64).tolist()
        cxl, czl, cyl, subl = x.tolist(), zz.tolist(), y.tolist(), sb.tolist()
        grid = {}
        sqrt = math.sqrt
        for k in range(NR - 1, -1, -1):
            need = cyl[k]
            gx, gz = gxa[k], gza[k]
            if subl[k] < 0.6 and grid:
                rk, xk, zk = RADL[k], cxl[k], czl[k]
                for ax in (gx - 1, gx, gx + 1):
                    for az in (gz - 1, gz, gz + 1):
                        cell = grid.get((ax, az))
                        if cell:
                            for jj in cell:
                                if jj - k < STACK_GAP:
                                    continue
                                lim = (rk + RADL[jj]) * 0.9
                                dx, dz = xk - cxl[jj], zk - czl[jj]
                                d2 = dx * dx + dz * dz
                                if d2 < lim * lim:
                                    req = cyl[jj] + sqrt(lim * lim - d2)
                                    if req > need:
                                        need = req
            cyl[k] = need
            cell = grid.get((gx, gz))
            if cell is None:
                grid[(gx, gz)] = [k]
            elif len(cell) < GCAP:
                cell.append(k)
        # 올라탄 높이의 경사를 제한한다 (가파른 계단 대신 둥근 언덕)
        s = 0.42
        pyl = self.py.tolist()
        for k in range(1, NR):
            e0 = cyl[k - 1] - pyl[k - 1]
            e1 = cyl[k] - pyl[k]
            if e1 < e0 - s:
                cyl[k] = pyl[k] + e0 - s
        for k in range(NR - 2, -1, -1):
            e0 = cyl[k + 1] - pyl[k + 1]
            e1 = cyl[k] - pyl[k]
            if e1 < e0 - s:
                cyl[k] = pyl[k] + e0 - s
        return cyl

    # ------------------------------------------------------------ 머리
    def _place_head(self, dt):
        """머리 부품들의 행렬을 계산한다 (보스 단위)."""
        sub0 = self.subL[0]
        ex = self.cur['ext']
        base = (_T(self.px + math.sin(self.yaw) * ex, self.lift_cur * (1 - sub0) - sub0 * 3, self.pz + math.cos(self.yaw) * ex)
                @ _Ry(self.yaw) @ _Rx(self.cur['pitch']) @ _S(HS))
        self.M_head = base
        self.head_vis = sub0 < 0.98
        jaw = self.jaw_cur
        mats = {'head': base, 'jaw': base @ _T(*JAW_PIVOT) @ _Rx(jaw * 1.5)}
        fa = 1.35 * (1 - _smooth(jaw * 1.7 - 0.15))
        mats['fang_l'] = base @ _T(-FANG_PIVOT[0], FANG_PIVOT[1], FANG_PIVOT[2]) @ _Rx(fa)
        mats['fang_r'] = base @ _T(FANG_PIVOT[0], FANG_PIVOT[1], FANG_PIVOT[2]) @ _Rx(fa)
        # 눈
        for name, sx in (('eye_l', -1), ('eye_r', 1)):
            mats[name] = base @ _T(sx * 0.93, 0.2, 1.0) @ _Ry(sx * 0.5) @ _Rz(sx * 0.25)
        # 목 지느러미: 접으면 목 옆에 뒤로 젖혀 납작하게, 펴면 정면으로 넓게 선다
        op = _smooth(self.hood_cur)
        breathe = 0.02 * math.sin(self.t * 2.3) * op
        hood = base @ _T(*HOOD_PIVOT)
        for name, sx in (('fin_l', -1), ('fin_r', 1)):
            mats[name] = (hood @ _T(sx * 0.95, -0.2, 0) @ _Ry(sx * ((1 - op) * 1.35 + breathe))
                          @ _S(sx * (0.55 + 0.45 * op), 0.5 + 0.5 * op, 0.55 + 0.45 * op))
        # 혀
        if dt > 0:
            self.nextFlick -= dt
            if not self.flicking and self.nextFlick <= 0 and jaw < 0.9 and self.head_vis:
                self.flicking = True
                self.flickT = 0.0
                self.nextFlick = 0.7 + random.random() * 1.5
            if self.flicking:
                self.flickT += dt
                u = self.flickT / 0.55
                if u >= 1:
                    self.flicking = False
                    self.ext = 0.0
                else:
                    if u < 0.2:
                        ext = u / 0.2
                    elif u < 0.72:
                        ext = 1 + 0.08 * math.sin(u * 60)
                    else:
                        ext = 1 - (u - 0.72) / 0.28
                    self.ext = min(1.1, max(0.001, ext))
                    self.tongue_rx = 0.1 + math.sin(u * 22) * 0.2 * (1 - u)
                    self.tongue_ry = math.sin(u * 17 + 1) * 0.1
                    self.spread = 0.05 + 0.4 * _smooth((u - 0.1) / 0.3)
        if self.ext > 0.02:
            tg = base @ _T(*TONGUE_PIVOT) @ _Rx(self.tongue_rx) @ _Ry(self.tongue_ry) @ _S(1, 1, self.ext)
            mats['tongue'] = tg
            mats['tine_l'] = tg @ _T(0, 0, 2.1) @ _Ry(self.spread)
            mats['tine_r'] = tg @ _T(0, 0, 2.1) @ _Ry(-self.spread)
        else:
            for kk in ('tongue', 'tine_l', 'tine_r'):
                mats.pop(kk, None)
        self.mats = mats

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
            self._update_debris(dt)
            return
        if self.was_dead:                                   # 부활: 새 자리에 몸을 곧게 편다
            self.was_dead = False
            self.debris = []
            self.seq = []
            self.wave, self.baseSub, self.auto_emerge = 'none', 0.0, None
            self.byaw = self.yaw
            self.layout_line(self.px, self.pz, self.yaw)
        if a == 2 and self.t - self.last_attack > 0.6 and not self._busy():
            self.attack()
        # 잠행 물결 진행
        if self.wave != 'none':
            self.waveT += dt
            if self.waveT > (BODY_LEN + 0.5) / self.wave_speed + WAVE_RISE + 0.05:
                self.baseSub = 1.0 if self.wave == 'dive' else 0.0
                self.wave = 'none'
        if self.auto_emerge is not None and self.t >= self.auto_emerge and (self.wave == 'dive' or self.baseSub >= 1):
            self.emerge()
            self._play([(0.55, 'rise')])
            self.auto_emerge = None
        # 자세 고르기 (달리다 멈출 때 속도가 문턱 근처에서 떨려도 자세가 깜빡이지 않게, 멈춘 지 0.3초 뒤에야 서 있는 자세로)
        spd_w = self.speed * SC
        if a == 1 or spd_w > 0.9:
            self.moving, self.still_t = True, 0.0
        elif self.moving:
            self.still_t += dt
            if self.still_t > 0.3 and spd_w < 0.4:
                self.moving = False
        if self.seq and self.t < self.seq_end:
            name = next(n for e, n in self.seq if self.t < e)
        elif "air" in st or "stun" in st:
            name = 'stagger'
        elif self.won:
            name = 'win'
        elif d.get("rc", 0) > 0:
            name = 'crouch'
        elif self.moving:
            name = 'move'
        else:
            name = 'idle'
        self.pose_name = name
        self.fold_t = self.fold_t + dt if (name != 'move' and name != 'charge') else 0.0
        p = {**IDLE, **POSES[name]}
        if spd_w > 0.9 and p['fold'] > 0.3:                  # 시전하며 달릴 때는 접힌 몸이 통째로 끌려다니지 않게
            p['fold'] = 0.3
        for k, v in p.items():
            self.tgt[k] = v
            self.rate[k] = FAST.get(name, {}).get(k, RATES[k])
        if name == 'idle':
            self.tgt['lift'] += 0.5 * math.sin(self.t * 1.6)
        elif name == 'slam':
            self.tgt['ext'] = self.slam_reach
        for k in self.cur:
            self.cur[k] += (self.tgt[k] - self.cur[k]) * (1 - math.exp(-self.rate[k] * dt))
        self.byaw += _wrap(self.yaw - self.byaw) * (1 - math.exp(-2.2 * dt))
        self.lift_cur = max(HEAD_REST, self.cur['lift'])
        self.jaw_cur = self.cur['jaw']
        self.hood_cur = self.cur['hood']
        self._push_trail()
        self._solve_body()
        self._update_pin(dt)
        self._place_head(dt)

    lift_cur = HEAD_REST

    def _busy(self):
        return bool(self.seq) and self.t < self.seq_end

    def _track(self, dt, ent):
        self.ent_w = (ent.x, ent.z)
        x, z = ent.x / SC, ent.z / SC
        face = facing_to_rot(ent.f)
        if not self.have_pos:
            self.have_pos = True
            self.yaw = self.byaw = face
            self.layout_line(x, z, face)
            return
        mx, mz = x - self.px, z - self.pz
        moved = math.hypot(mx, mz)
        if moved > 28.0 and self.wave == 'none' and self.baseSub < 1:      # 순간이동 (귀환·플래시·부활): 몸을 새 자리에 곧게 편다
            self.vel = [0.0, 0.0]
            self.layout_line(x, z, self.yaw)
        else:
            k = 1 - math.exp(-10 * dt)
            # 머리가 목표 위치를 바로 따라가지 않고 묵직하게 끌려가 방향을 꺾을 때 몸이 넓게 휘어진다
            ks = 1 - math.exp(-HEAVY_POS * dt)
            sx_, sz_ = mx * ks, mz * ks
            vx, vz = (sx_ / dt, sz_ / dt) if dt > 1e-6 else (0.0, 0.0)
            self.vel[0] += (vx - self.vel[0]) * k
            self.vel[1] += (vz - self.vel[1]) * k
            self.px, self.pz = self.px + sx_, self.pz + sz_
        self.speed = math.hypot(self.vel[0], self.vel[1])
        if self.slam_tgt is not None and self.seq and self.t < self.seq_end and any(n in ('rear', 'slam') for e_, n in self.seq if self.t < e_):
            tdx, tdz = self.slam_tgt[0] - self.px, self.slam_tgt[1] - self.pz
            if math.hypot(tdx, tdz) > 0.5:
                face = math.atan2(tdx, tdz)                     # 시전 중에는 목표 쪽을 보고, 목표까지의 거리만큼 뻗는다
                self.slam_reach = min(math.hypot(tdx, tdz), SLAM_REACH / SC)
        turn = _wrap(face - self.yaw) * (1 - math.exp(-HEAVY_TURN * dt))
        cap = MAX_TURN * dt                                  # 아무리 휙휙 돌려도 이 속도 이상으로는 못 돈다
        self.yaw += max(-cap, min(cap, turn))

    # ------------------------------------------------------------ 그리기
    def draw(self, r, tint=(1, 1, 1, 1), emis=(0, 0, 0)):
        SCL = self._draw_scale()
        alpha = tint[3] if len(tint) > 3 else 1.0
        hf = self.hit_flash
        e = (emis[0] + 0.05 + hf * 0.4, emis[1] + 0.05 + hf * 0.2, emis[2] + 0.045)
        if self.was_dead:
            for db in self.debris:
                M = _T(*db.pos) @ _euler(*db.ang) @ db.base
                if db.tint is not None:
                    r.draw(db.mesh, SCL @ M, tint=(db.tint[0], db.tint[1], db.tint[2], alpha), unlit=1.0)
                else:
                    r.draw(db.mesh, SCL @ M, tint=(tint[0] * db.col[0], tint[1] * db.col[1], tint[2] * db.col[2], alpha), emissive=e)
            return
        a = self.a
        col = (tint[0], tint[1], tint[2], alpha)
        # 몸 그림자 (땅에 붙어 보이게)
        for k in range(NR):
            if self.subL[k] > 0.5:
                continue
            hk = max(0.0, 1.0 - max(0.0, self.cyL[k] - 2.2) / 4.0)      # 높이 솟은 마디의 그림자는 옅게
            if hk <= 0.0:
                continue
            rad = max(RADL[k], 1.0) * 1.35
            r.draw_transparent(a.shadow, SCL @ _T(self.cxL[k], 0.14, self.czL[k]) @ _S(rad), (0, 0, 0, 0.055 * alpha * hk))
        prog = r.prog
        prog["u_dbl"].value = True
        r.draw(self.tube, SCL, tint=col, emissive=e)
        prog["u_dbl"].value = False
        if self.head_vis:
            ms = self.mats
            r.draw(a.head, SCL @ ms['head'], tint=col, emissive=e)
            r.draw(a.jaw, SCL @ ms['jaw'], tint=col, emissive=e)
            r.draw(a.fang, SCL @ ms['fang_l'], tint=col, emissive=e)
            r.draw(a.fang, SCL @ ms['fang_r'], tint=col, emissive=e)
            if 'tongue' in ms:
                r.draw(a.tongue, SCL @ ms['tongue'], tint=col, emissive=e)
                r.draw(a.tine_l, SCL @ ms['tine_l'], tint=col, emissive=e)
                r.draw(a.tine_r, SCL @ ms['tine_r'], tint=col, emissive=e)
            ec, gc = self._eye_color(), self._gem_color()
            for nm in ('eye_l', 'eye_r'):
                r.draw(a.eye, SCL @ ms[nm], tint=(ec[0], ec[1], ec[2], alpha), unlit=1.0)
            r.draw(a.gem, SCL @ ms['head'], tint=(gc[0], gc[1], gc[2], alpha), unlit=1.0)
            prog["u_dbl"].value = True
            for nm in ('fin_l', 'fin_r'):
                r.draw(a.ribs, SCL @ ms[nm], tint=col, emissive=e)
            for nm in ('fin_l', 'fin_r'):
                r.draw_transparent(a.fin, SCL @ ms[nm], (tint[0], tint[1], tint[2], alpha * 0.9), emissive=(0.06, 0.1, 0.1),
                                   unlit=0.45)
            prog["u_dbl"].value = False

    def _eye_color(self):
        k = 1.3 + 0.4 * math.sin(self.t * 4)
        return (1.0 * k, 0.8 * k, 0.22 * k)

    def _gem_color(self):
        q = 0.9 + 0.3 * math.sin(self.t * 3)
        return (0.12 * q, 0.62 * q, 0.5 * q)

    # ------------------------------------------------------------ 사망: 마디별 분해 (원본의 explode)
    def _explode(self):
        r = random.random
        self.wave, self.baseSub, self.auto_emerge = 'none', 0.0, None
        a = self.a
        center = np.array([self.px, 1.5, self.pz])
        parts = []                                         # (메시, 보스 단위 행렬, 빛나는 색)
        ms = self.mats
        for mesh, nm, glow in ((a.head, 'head', None), (a.jaw, 'jaw', None), (a.fang, 'fang_l', None), (a.fang, 'fang_r', None),
                               (a.eye, 'eye_l', 'eye'), (a.eye, 'eye_r', 'eye')):
            if nm in ms:
                parts.append((mesh, ms[nm], glow))
        for nm in ('fin_l', 'fin_r'):
            if nm in ms:
                parts.append((a.fin, ms[nm], None))
        for k in range(3, NR, 3):
            if self.subL[k] >= 0.98 or RADL[k] < 0.2:
                continue
            basis = np.eye(4)
            basis[:3, 0], basis[:3, 1], basis[:3, 2] = self.fb[k], self.fn[k], -self.ft[k]
            M = _T(self.cxL[k], self.cyL[k], self.czL[k]) @ basis @ _S(RADL[k], RADL[k] * 0.9, DSEG * 1.6)
            parts.append((a.chunk, M, None))
        self.debris = []
        for mesh, M, glow in parts:
            db = _Debris()
            db.mesh = mesh
            pos = M[:3, 3].copy()
            base = M.copy()
            base[:3, 3] = 0.0
            db.base = base
            v = pos - center
            v[1] = abs(v[1]) * 0.5 + 0.6
            v /= max(1e-6, float(np.linalg.norm(v)))
            sp = 4 + r() * 9
            db.vel = v * sp + np.array([(r() - 0.5) * 3, 5 + r() * 8, (r() - 0.5) * 3])
            db.pos = pos
            db.ang = np.zeros(3)
            db.spin = np.array([(r() - 0.5) * 12, (r() - 0.5) * 12, (r() - 0.5) * 12])
            db.tint = self._eye_color() if glow else None
            db.col = (0.45, 0.78, 0.72) if (mesh is a.chunk and len(self.debris) % 2) else (1.0, 1.0, 1.0)
            db.unlit = bool(glow)
            db.rest = False
            db.r = max(0.4, float(np.linalg.norm(M[:3, 0])) * 0.6)
            self.debris.append(db)

    def _update_debris(self, dt):
        for db in self.debris:
            if db.rest:
                continue
            db.vel[1] -= 28 * dt
            db.pos += db.vel * dt
            db.ang += db.spin * dt
            if db.pos[1] < min(db.r, 0.6):
                db.pos[1] = min(db.r, 0.6)
                db.vel[1] *= -0.35
                db.vel[0] *= 0.78
                db.vel[2] *= 0.78
                db.spin *= 0.6
                if abs(db.vel[1]) < 1.2 and math.hypot(db.vel[0], db.vel[2]) < 0.6:
                    db.rest = True
