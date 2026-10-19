"""코드로 만드는 로우폴리 모델들 (미니언·구조물·맵 등). 모든 모델은 발밑이 원점, 앞쪽이 +Z.

챔피언 모델은 champion_models.py 에 있다.
"""
import math
import random

from ..shared import mapdata
from .geometry import MeshBuilder

TEAM_COLORS = {0: (0.25, 0.55, 1.0), 1: (1.0, 0.32, 0.3)}
STONE = (0.80, 0.75, 0.66)          # 밝은 석회암 (신전 구조물)
STONE_DARK = (0.50, 0.45, 0.38)
SNOW = (0.88, 0.92, 0.98)


def _mix(a, b, t):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


# ------------------------------------------------------------------ 챔피언
def build_mannequin(color):
    """챔피언 모델 파일이 없을 때 쓰는 단순 인형."""
    b = MeshBuilder()
    dark = _mix(color, (0.1, 0.1, 0.15), 0.6)
    for sx in (-1, 1):
        b.box((0.14 * sx, 0.42, 0), (0.18, 0.84, 0.2), dark)
        b.box((0.36 * sx, 1.1, 0), (0.13, 0.55, 0.14), color)
    b.box((0, 1.15, 0), (0.52, 0.65, 0.3), color, taper=0.9)
    b.sphere((0, 1.65, 0), 0.2, (0.95, 0.85, 0.75))
    b.box((0, 1.65, 0.19), (0.2, 0.06, 0.04), (0.1, 0.1, 0.1))
    return b


# ------------------------------------------------------------------ 미니언
def build_minion(mtype, team, frame=0):
    tc = TEAM_COLORS[team]
    metal = (0.62, 0.66, 0.74)
    dark = (0.22, 0.24, 0.3)
    b = MeshBuilder()
    if mtype == "melee":
        for sx in (-1, 1):
            b.box((0.12 * sx, 0.18, 0), (0.13, 0.36, 0.15), dark)
        b.box((0, 0.58, 0), (0.46, 0.46, 0.34), tc, taper=0.85)
        b.sphere((0, 0.95, 0), 0.17, metal, seg=10, rings=6)
        b.box((0, 0.95, 0.15), (0.24, 0.05, 0.04), (0.1, 0.1, 0.12))
        b.cone((0, 1.08, 0), 0.08, 0.16, tc, seg=6)
        b.box((-0.3, 0.6, 0.12), (0.06, 0.4, 0.3), tc)
    elif mtype == "caster":
        b.cylinder((0, 0, 0), 0.3, 0.75, tc, seg=10, radius_top=0.16)
        b.sphere((0, 0.88, 0), 0.15, (0.85, 0.8, 0.75), seg=10, rings=6)
        b.cone((0, 0.96, 0), 0.22, 0.4, _mix(tc, (0.1, 0.1, 0.2), 0.4), seg=10)
    elif mtype == "cannon":
        b.box((0, 0.42, 0), (0.85, 0.42, 1.0), dark)
        b.box((0, 0.66, 0), (0.7, 0.1, 0.85), tc)
        for sx in (-1, 1):
            for sz in (-1, 1):
                b.sphere((0.46 * sx, 0.24, 0.33 * sz), 0.22, (0.3, 0.25, 0.2), seg=10, rings=6, scale=(0.4, 1, 1))
        b.box((0, 0.82, 0.25), (0.24, 0.24, 1.0), metal)
        b.cylinder((0, 0.7, -0.15), 0.2, 0.3, metal, seg=8)
    elif mtype == "spiderling":                       # 거미 여왕의 새끼 거미 (원본 BossRush 의 Baby 와 같은 생김새)
        return build_spiderling(team, frame)
    else:  # super
        for sx in (-1, 1):
            b.box((0.22 * sx, 0.35, 0), (0.25, 0.7, 0.3), dark)
            b.sphere((0.48 * sx, 1.45, 0), 0.22, tc, seg=8, rings=5)
            b.box((0.55 * sx, 1.05, 0.05), (0.2, 0.6, 0.22), metal)
        b.box((0, 1.1, 0), (0.85, 0.8, 0.55), tc, taper=0.85)
        b.sphere((0, 1.72, 0), 0.25, metal, seg=10, rings=6)
        b.box((0, 1.74, 0.22), (0.3, 0.06, 0.05), (1.0, 0.85, 0.3))
        b.box((0.62, 1.0, 0.45), (0.12, 0.12, 0.9), metal)
    return b


# ------------------------------------------------------------------ 새끼 거미 (거미 여왕을 줄인 모양, 같은 걸음걸이)
def build_spiderling(team, frame=0):
    """모양과 다리 움직임은 rigs/spider.py 의 build_baby 가 만든다 (거미 여왕의 걸음 알고리즘으로 뽑은 한 주기의 프레임)."""
    from .rigs.spider import build_baby
    return build_baby(frame)


def baby_frames():
    from .rigs.spider import BABY_FRAMES
    return BABY_FRAMES


# 무기를 따로 만드는 미니언: 몸통과 분리해 공격할 때 휘두른다.
# 반환: (builder, 손 위치) — builder 의 원점이 손(회전축)이다.
MINION_WEAPON_PIVOT = {"melee": (0.32, 0.62, -0.05), "caster": (0.3, 0.55, 0.08)}


def build_minion_weapon(mtype, team):
    tc = TEAM_COLORS[team]
    b = MeshBuilder()
    if mtype == "melee":
        b.box((0, 0, 0.27), (0.06, 0.06, 0.6), (0.62, 0.66, 0.74))      # 앞으로 뻗은 검
    elif mtype == "caster":
        b.box((0, 0, 0), (0.05, 1.0, 0.05), (0.45, 0.32, 0.2))          # 지팡이
        b.sphere((0, 0.53, 0), 0.09, _mix(tc, (1, 1, 1), 0.5), seg=8, rings=5)
    else:
        return None
    return b, MINION_WEAPON_PIVOT[mtype]


# ------------------------------------------------------------------ 부쉬
def build_bush(rx, rz, seed=7):
    """타원 범위를 빈틈없이 채우는 둥근 잎 덤불. 원점이 부쉬 중심.

    촘촘한 육각 격자에 비슷한 크기의 잎 덩어리(납작한 구)를 서로 겹치게 깐다.
    같은 seed 면 항상 같은 모양.
    """
    rng = random.Random(seed)
    b = MeshBuilder()
    dark, light = (0.18, 0.42, 0.26), (0.36, 0.64, 0.36)

    def blob(x, z, r, y):
        b.sphere((x, y, z), r, _mix(dark, light, rng.uniform(0, 1)), seg=8, rings=5, scale=(1.0, 0.8, 1.0))

    # 아래층: 간격(0.55)보다 반지름(0.42~)이 커서 이웃끼리 겹친다 → 빈 곳이 없다
    step_x, step_z = 0.55, 0.48
    zi = 0
    z = -rz
    while z <= rz + 1e-6:
        x = -rx + (step_x / 2 if zi % 2 else 0.0)
        while x <= rx + 1e-6:
            k = (x / rx) ** 2 + (z / rz) ** 2          # 0 = 가운데, 1 = 가장자리
            if k <= 0.92:
                r = 0.42 + rng.uniform(-0.03, 0.03)
                blob(x + rng.uniform(-0.06, 0.06), z + rng.uniform(-0.06, 0.06), r, r * 0.6)
            x += step_x
        z += step_z
        zi += 1
    return b


# ------------------------------------------------------------------ 구조물
def build_turret(team):
    tc = TEAM_COLORS[team]
    b = MeshBuilder()
    b.cylinder((0, 0, 0), 1.25, 0.45, STONE_DARK, seg=8, smooth=False)
    b.box((0, 1.9, 0), (1.15, 3.0, 1.15), STONE, taper=0.72, rot_y=math.pi / 4)
    for k in range(4):
        a = k * math.pi / 2
        b.box((math.cos(a) * 0.62, 1.0, math.sin(a) * 0.62), (0.22, 1.6, 0.22), STONE_DARK, taper=0.6)
    b.cylinder((0, 3.35, 0), 0.75, 0.35, STONE_DARK, seg=8, smooth=False)
    for k in range(6):
        a = k / 6 * math.tau
        b.box((math.cos(a) * 0.62, 3.85, math.sin(a) * 0.62), (0.16, 0.5, 0.16), _mix(tc, (1, 1, 1), 0.3), taper=0.4)
    b.octahedron((0, 4.35, 0), 0.42, 1.1, _mix(tc, (1, 1, 1), 0.35), seg=6)
    return b


def build_rubble():
    b = MeshBuilder()
    rng = random.Random(7)
    b.cylinder((0, 0, 0), 1.25, 0.35, STONE_DARK, seg=8, smooth=False)
    for _ in range(7):
        a = rng.random() * math.tau
        r = rng.uniform(0.2, 1.1)
        b.box((math.cos(a) * r, 0.45, math.sin(a) * r), (rng.uniform(0.3, 0.6),) * 3, STONE, rot_y=rng.random() * 3)
    return b


def build_inhibitor(team, alive=True):
    tc = TEAM_COLORS[team] if alive else (0.3, 0.3, 0.35)
    b = MeshBuilder()
    b.cylinder((0, 0, 0), 1.7, 0.3, STONE_DARK, seg=12, smooth=False)
    for k in range(6):
        a = k / 6 * math.tau
        b.box((math.cos(a) * 1.35, 0.9, math.sin(a) * 1.35), (0.28, 1.4, 0.28), STONE, taper=0.6, rot_y=-a)
    if alive:
        b.sphere((0, 1.35, 0), 0.75, _mix(tc, (1, 1, 1), 0.25), seg=14, rings=10)
        b.ring((0, 1.35, 0), 0.95, 1.1, _mix(tc, (1, 1, 1), 0.6))
    else:
        b.sphere((0, 0.45, 0), 0.5, tc, seg=8, rings=5, scale=(1, 0.4, 1))
    return b


def build_nexus(team, alive=True):
    tc = TEAM_COLORS[team] if alive else (0.3, 0.3, 0.35)
    b = MeshBuilder()
    b.cylinder((0, 0, 0), 2.6, 0.5, STONE_DARK, seg=10, smooth=False)
    b.cylinder((0, 0.5, 0), 1.9, 0.6, STONE, seg=10, smooth=False, radius_top=1.5)
    if alive:
        b.cylinder((0, 1.1, 0), 0.8, 1.6, STONE_DARK, seg=10, smooth=False, radius_top=0.55)      # 가운데 기둥 (수정 바로 아래)
        b.octahedron((0, 4.1, 0), 1.1, 2.8, _mix(tc, (1, 1, 1), 0.25), seg=6)
        for k in range(4):
            a = k / 4 * math.tau + 0.4
            b.octahedron((math.cos(a) * 1.9, 1.5, math.sin(a) * 1.9), 0.3, 0.8, _mix(tc, (1, 1, 1), 0.5), seg=4)
    else:
        rng = random.Random(3)
        for _ in range(6):
            a = rng.random() * math.tau
            b.octahedron((math.cos(a) * 1.2, 1.2, math.sin(a) * 1.2), 0.4, 0.9, tc, seg=4)
    return b


def build_relic():
    b = MeshBuilder()
    b.octahedron((0, 0, 0), 0.35, 0.8, (0.4, 1.0, 0.55), seg=6)
    return b


# ------------------------------------------------------------------ 투사체 / 이펙트
def build_arrow(color):
    b = MeshBuilder()
    b.box((0, 0, -0.1), (0.06, 0.06, 0.7), color)
    b.octahedron((0, 0, 0.3), 0.09, 0.09, color, seg=4)
    return b


def build_orb(color, r=0.18):
    b = MeshBuilder()
    b.sphere((0, 0, 0), r, color, seg=8, rings=6)
    return b


def build_shadow():
    b = MeshBuilder()
    b.disc((0, 0, 0), 1.0, (0, 0, 0), 20)
    return b


# ------------------------------------------------------------------ 맵
PANEL_A = (0.56, 0.49, 0.38)        # 사암 바닥 타일 두 가지 (체스판처럼 번갈아)
PANEL_B = (0.51, 0.44, 0.34)
MOSS = (0.34, 0.44, 0.25)
GROUT = (0.27, 0.22, 0.17)          # 타일 사이 줄눈
HULL = (0.30, 0.24, 0.19)           # 플랫폼 옆면·밑면 (흙과 바위)
WALL = (0.66, 0.60, 0.50)           # 낮은 석벽
RUNE = (0.95, 0.74, 0.34)           # 바닥에 새긴 금빛 룬 선
FIRE = (1.0, 0.62, 0.2)


def _edge_box(b, p0, p1, y, size_y, size_z, color):
    """두 점 p0-p1 (xz) 을 잇는 방향으로 놓인 박스."""
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dz)
    ang = math.atan2(-dz, dx)
    b.box(((p0[0] + p1[0]) / 2, y, (p0[1] + p1[1]) / 2), (length + 0.02, size_y, size_z), color, rot_y=ang)


def _column(b, x, z, h, rng, ruined=False, flame=True, r=0.3):
    """신전 기둥: 받침 + 둥근 몸통 + 머리장식. 무너진 기둥은 끝이 깨지고 조각이 굴러다닌다."""
    b.box((x, 0.14, z), (r * 3.0, 0.28, r * 3.0), STONE_DARK)
    if ruined:
        h = h * rng.uniform(0.35, 0.6)
        b.cylinder((x, 0.28, z), r, h, STONE, seg=8, smooth=False)
        b.box((x, 0.28 + h, z), (r * 1.4, 0.18, r * 1.1), STONE, rot_y=rng.random() * 3)
        for _ in range(3):
            a = rng.random() * math.tau
            d = rng.uniform(0.6, 1.5)
            b.box((x + math.cos(a) * d, 0.12, z + math.sin(a) * d), (rng.uniform(0.2, 0.45), 0.22, rng.uniform(0.2, 0.4)),
                  _mix(STONE, STONE_DARK, rng.random()), rot_y=rng.random() * 3)
        return
    b.cylinder((x, 0.28, z), r, h, STONE, seg=8, smooth=False)
    b.cylinder((x, 0.28, z), r * 1.15, 0.22, STONE_DARK, seg=8, smooth=False)
    b.box((x, 0.28 + h + 0.1, z), (r * 2.8, 0.2, r * 2.8), STONE)
    if flame:                                                    # 머리 위 화로의 불
        b.cylinder((x, 0.28 + h + 0.2, z), r * 0.8, 0.16, STONE_DARK, seg=8, radius_top=r * 1.15, smooth=False)
        b.octahedron((x, 0.28 + h + 0.55, z), 0.28, 0.9, FIRE, seg=5)
        b.octahedron((x, 0.28 + h + 0.5, z), 0.15, 0.62, (1.0, 0.9, 0.5), seg=4)


def _float_island(b, rng, pos, r, ruin=False):
    """떠 있는 돌섬: 이끼 낀 윗면 + 아래로 뾰족한 바위. 큰 섬에는 무너진 유적이 얹혀 있다."""
    x, y, z = pos
    rock = _mix((0.36, 0.30, 0.25), (0.56, 0.47, 0.38), rng.random())
    b.cylinder((x, y - r * 1.5, z), r * 0.22, r * 1.5, rock, seg=7, radius_top=r * 1.1, smooth=False)
    b.cylinder((x, y - 0.02, z), r * 1.14, 0.22 * min(1.5, r), _mix(MOSS, (0.5, 0.6, 0.3), rng.random() * 0.5), seg=9,
               smooth=False)
    if ruin:
        for k in range(rng.randint(1, 3)):
            a = rng.random() * math.tau
            d = rng.uniform(0, r * 0.7)
            h = rng.uniform(1.0, 2.6)
            cx, cz = x + math.cos(a) * d, z + math.sin(a) * d
            b.cylinder((cx, y + 0.2, cz), 0.3, h, STONE, seg=7, smooth=False)
            b.box((cx, y + 0.2 + h + 0.08, cz), (0.85, 0.16, 0.85), STONE_DARK)
        if rng.random() < 0.6:                                   # 무너진 아치 한 쌍
            cx, cz = x + rng.uniform(-r, r) * 0.4, z + rng.uniform(-r, r) * 0.4
            b.box((cx - 0.7, y + 0.9, cz), (0.4, 1.8, 0.45), STONE)
            b.box((cx + 0.7, y + 0.6, cz), (0.4, 1.2, 0.45), STONE)
            b.box((cx - 0.15, y + 1.95, cz), (1.8, 0.35, 0.5), STONE_DARK, rot_y=0.15)


def _clip_poly(poly, f):
    """볼록 다각형을 반평면 f(p) >= 0 으로 자른다 (Sutherland-Hodgman). p=(x,z)."""
    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        fp, fq = f(p), f(q)
        if fp >= 0:
            out.append(p)
        if (fp >= 0) != (fq >= 0):
            t = fp / (fp - fq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _floor_tiles(b, rng, end, step, tile=2.0):
    """바닥: 폭이 변해도 항상 같은 크기의 정사각 타일 격자. 가장자리 타일만 길 윤곽으로 잘린다.
    줄눈 선을 그리지 않고(깜빡임 방지) 타일마다 색을 달리해 무늬를 낸다."""
    n = (0, 1, 0)
    nx = int(round(2 * end / tile))
    nz = int(math.ceil(mapdata.BASE_HALF_WIDTH / tile))
    for i in range(nx):
        x0 = -end + i * tile
        x1 = x0 + tile
        # 윤곽은 step 간격 선분이라 타일 안에서 직선이다
        k = math.floor((x0 + end) / step + 1e-6)
        xa = -end + k * step
        ha, hb = mapdata.half_width(xa), mapdata.half_width(xa + step)
        slope = (hb - ha) / step
        for j in range(-nz, nz):
            z0, z1 = j * tile, (j + 1) * tile
            poly = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
            poly = _clip_poly(poly, lambda p: ha + slope * (p[0] - xa) - p[1])
            poly = _clip_poly(poly, lambda p: ha + slope * (p[0] - xa) + p[1])
            if len(poly) < 3:
                continue
            base = PANEL_A if (i + j) % 2 == 0 else PANEL_B          # 타일은 두 가지 색만 번갈아 쓴다
            for m in range(1, len(poly) - 1):
                tri = [poly[0], poly[m], poly[m + 1]]
                (ax, az), (bx, bz), (cx, cz) = tri
                if (bx - ax) * (cz - az) - (bz - az) * (cx - ax) > 0:
                    tri = [poly[0], poly[m + 1], poly[m]]
                b.tri(*[(p[0], 0.0, p[1]) for p in tri], base, n, n, n)


def build_map():
    """하늘 위에 떠 있는 고대 신전 유적 (칼바람 나락 배치 그대로): 사암 타일 길, 석벽과 기둥(화로), 떠 있는 돌섬."""
    rng = random.Random(42)
    b = MeshBuilder()
    end = mapdata.LANE_END
    depth = 1.4
    step = 2.0

    # 라인 바닥 패널 + 옆면(두께)
    x, ix = -end, 0
    while x < end - 1e-6:
        x1 = x + step
        hw0, hw1 = mapdata.half_width(x), mapdata.half_width(x1)
        for side in (-1, 1):
            a0, a1 = (x, side * hw0), (x1, side * hw1)
            # 옆면
            b.quad((a0[0], 0, a0[1]), (a1[0], 0, a1[1]), (a1[0], -depth, a1[1]), (a0[0], -depth, a0[1]), HULL)
            # 낮은 석벽 (군데군데 무너져 있다)
            if rng.random() > 0.07:
                _edge_box(b, (x, side * (hw0 + 0.25)), (x1, side * (hw1 + 0.25)), 0.32, 0.64, 0.46, WALL)
                _edge_box(b, (x, side * (hw0 + 0.25)), (x1, side * (hw1 + 0.25)), 0.68, 0.1, 0.6, _mix(WALL, (1, 1, 1), 0.15))
            else:
                b.box((x + 1.0, 0.1, side * (hw0 + 0.25)), (rng.uniform(0.3, 0.6), 0.2, 0.4), WALL, rot_y=rng.random() * 3)
        # 바닥면
        b.quad((x, -depth, -hw0), (x1, -depth, -hw1), (x1, -depth, hw1), (x, -depth, hw0), HULL)
        x = x1
        ix += 1
    _floor_tiles(b, rng, end, step)
    # 양 끝 마감
    for sx in (-1, 1):
        hw = mapdata.half_width(end)
        b.quad((sx * end, 0, -hw), (sx * end, 0, hw), (sx * end, -depth, hw), (sx * end, -depth, -hw), HULL)

    # 가장자리 신전 기둥 (불 켠 화로) — 가끔은 무너져 있다
    for k in range(-5, 6):
        px = k * 10.0
        for side in (-1, 1):
            hw = mapdata.half_width(px)
            pz = side * (hw + 0.45)
            _column(b, px, pz, 2.7, rng, ruined=rng.random() < 0.25, r=0.38)

    # 플랫폼 아래: 매달린 바위 기둥 (흙과 뿌리)
    for k in range(-10, 11):
        px = k * 5.5 + rng.uniform(-1, 1)
        hw = mapdata.half_width(px)
        w = rng.uniform(1.5, 3.0)
        h = rng.uniform(1.5, 4.5)
        pz = rng.uniform(-hw * 0.6, hw * 0.6)
        b.box((px, -depth - h / 2, pz), (w, h, w * rng.uniform(1.0, 2.2)), _mix(HULL, (0.45, 0.36, 0.28), rng.random()),
              taper=rng.uniform(1.4, 2.0))
        if rng.random() < 0.35:
            b.octahedron((px, -depth - h - 0.3, pz), 0.3, 0.55, (0.95, 0.65, 0.25), seg=6)      # 매달린 호박빛 등

    # 우물(본진) 제단: 석조 단 + 룬 고리 + 팀 색 불꽃 기둥 + 중앙 수정
    for team in (0, 1):
        fx, fz = mapdata.fountain_pos(team)
        tc = TEAM_COLORS[team]
        b.cylinder((fx, -depth, fz), 6.0, depth + 0.02, _mix((0.66, 0.58, 0.47), tc, 0.2), seg=24, smooth=False)
        b.cylinder((fx, -depth - 2.5, fz), 3.0, 2.5, HULL, seg=12, radius_top=4.6, smooth=False)
        b.ring((fx, 0.04, fz), 5.0, 5.5, _mix(tc, (1, 1, 1), 0.3))
        b.ring((fx, 0.045, fz), 3.2, 3.5, RUNE)
        for cx, cz in mapdata.fountain_pillars(team):
            _column(b, cx, cz, 2.8, rng, flame=False, r=0.38)
            b.octahedron((cx, 3.75, cz), 0.26, 0.75, _mix(tc, (1, 1, 1), 0.4), seg=4)

    # 주변에 떠 있는 돌섬과 바위 조각 (큰 섬에는 무너진 유적)
    for i in range(46):
        if rng.random() < 0.65:
            side = rng.choice((-1, 1))
            pos = (rng.uniform(-120, 120), rng.uniform(-24, 3), side * rng.uniform(17, 70))
        else:
            pos = (rng.uniform(-110, 110), rng.uniform(-40, -10), rng.uniform(-16, 16))
        r = rng.uniform(1.4, 5.0)
        _float_island(b, rng, pos, r, ruin=(r > 2.8 and rng.random() < 0.7))
    rock_a, rock_b = (0.38, 0.31, 0.25), (0.58, 0.49, 0.4)
    for _ in range(70):
        side = rng.choice((-1, 1))
        pos = (rng.uniform(-120, 120), rng.uniform(-32, 4), side * rng.uniform(15, 60))
        r = rng.uniform(0.3, 1.6)
        b.sphere(pos, r, _mix(rock_a, rock_b, rng.random()), seg=7, rings=5,
                 scale=(rng.uniform(0.7, 1.4), rng.uniform(0.6, 1.1), rng.uniform(0.7, 1.4)))
    return b


# ------------------------------------------------------------------ 스킬 메시 (거미 고치, 용의 회오리)
def build_cocoon():
    """거미 여왕의 새끼 거미 고치: 누런 비단으로 감싼 알 + 바닥에 퍼진 거미줄."""
    b = MeshBuilder()
    silk, band = (0.93, 0.86, 0.68), (0.78, 0.68, 0.48)
    b.sphere((0, 0.5, 0), 0.5, silk, seg=12, rings=8, scale=(0.85, 1.15, 0.85))
    for j, y in enumerate((0.3, 0.5, 0.7)):
        w = (0.43, 0.46, 0.4)[j]
        b.ring((0, y, 0), w - 0.03, w + 0.03, band, seg=14)
    b.ring((0, 0.03, 0), 0.3, 0.62, (0.85, 0.82, 0.74), seg=16)
    return b


def build_tornado_layer(i, n=9, seg=12):
    """보스러시 용의 회오리 한 겹: 위로 갈수록 넓어지는 속 빈 원뿔대. 겹마다 반지름이 0.5 씩 커지고, 줄무늬가 있어 돌면 소용돌이로 보인다."""
    b = MeshBuilder()
    r0, r1 = 0.7 + i * 0.5, 0.7 + (i + 1) * 0.5
    for j in range(seg):
        a0, a1 = j / seg * math.tau, (j + 1) / seg * math.tau
        c = (1.0, 1.0, 1.0) if j % 2 else (0.62, 0.62, 0.62)
        p = lambda r, a, y: (math.cos(a) * r, y, math.sin(a) * r)
        b.quad(p(r0, a0, 0.0), p(r0, a1, 0.0), p(r1, a1, 1.0), p(r1, a0, 1.0), c)
    return b
