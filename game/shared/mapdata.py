"""칼바람 나락(모티브) 맵 정의.

좌표계: x축이 라인 방향(블루팀 -x, 레드팀 +x), z축이 라인 폭 방향, y는 높이.
1 유닛 ≈ 롤의 100 유닛.
"""
import math

from .constants import BLUE, RED

LANE_END = 57.0          # 맵 끝 (x 절댓값) — 우물 원과 기둥 뒤까지 바닥이 이어지게
LANE_HALF_WIDTH = 7.5    # 라인 구간 절반 폭
BASE_HALF_WIDTH = 11.5   # 본진 구간 절반 폭
BASE_START = 28.0        # |x| 가 이 이상이면 본진 구간으로 넓어짐
BASE_BLEND = 6.0

FOUNTAIN_X = 50.0
PILLAR_RING = 6.6        # 우물 제단 기둥이 놓인 반지름
PILLAR_RADIUS = 0.45     # 기둥 충돌 반지름 (포탑처럼 길을 막는다)


def team_dir(team):
    """해당 팀이 공격해 나가는 x 방향."""
    return 1.0 if team == BLUE else -1.0


def fountain_pos(team):
    return (-FOUNTAIN_X if team == BLUE else FOUNTAIN_X, 0.0)


def fountain_pillars(team):
    """우물 제단 기둥 위치. 8개 중 앞쪽(맵 중앙 방향) 3개와 뒤쪽 1개를 뺀 4개만 남긴다."""
    fx, fz = fountain_pos(team)
    drop = {0, 1, 7, 4} if team == BLUE else {4, 3, 5, 0}
    out = []
    for k in range(8):
        if k in drop:
            continue
        a = k / 8 * math.tau
        out.append((fx + math.cos(a) * PILLAR_RING, fz + math.sin(a) * PILLAR_RING))
    return out


def half_width(x):
    ax = abs(x)
    t = (ax - BASE_START) / BASE_BLEND
    t = max(0.0, min(1.0, t))
    t = t * t * (3 - 2 * t)
    return LANE_HALF_WIDTH + (BASE_HALF_WIDTH - LANE_HALF_WIDTH) * t


def clamp_to_map(x, z, radius=0.0):
    x = max(-LANE_END + radius, min(LANE_END - radius, x))
    hw = half_width(x) - radius
    z = max(-hw, min(hw, z))
    return x, z


# 구조물: (key, kind, x(블루 기준, 음수), z, max_hp, radius, 선행조건 key 목록)
# 선행조건 구조물이 모두 파괴되어야 피해를 받을 수 있다. 넥서스는 억제기도 선행조건이라 억제기가 재생성되면 다시 무적이 된다.
_STRUCTURE_LAYOUT = [
    ("inner", "turret", -21.4, 0.0, 3600, 1.1, []),
    ("inhib", "inhibitor", -28.4, 0.0, 4000, 1.6, ["inner"]),
    ("nexus_t1", "turret", -35.0, -2.6, 2700, 1.0, ["inhib"]),
    ("nexus_t2", "turret", -35.0, 2.6, 2700, 1.0, ["inhib"]),
    ("nexus", "nexus", -39.0, 0.0, 5500, 2.4, ["nexus_t1", "nexus_t2", "inhib"]),
]


def structure_layout():
    """양 팀의 구조물 목록을 돌려준다."""
    out = []
    for team in (BLUE, RED):
        sign = 1.0 if team == BLUE else -1.0
        for key, kind, x, z, hp, r, req in _STRUCTURE_LAYOUT:
            out.append({
                "key": key, "kind": kind, "team": team,
                "x": x * sign, "z": z, "hp": hp, "radius": r, "requires": list(req),
            })
    return out


RELIC_POSITIONS = [(-24.0, 5.0), (-12.0, -5.0), (12.0, 5.0), (24.0, -5.0)]

TURRET_RANGE = 7.5

# 부쉬(수풀): (x, z, 반지름 x, 반지름 z) 타원. 안에 있는 유닛은 같은 부쉬 안에 있는 적에게만 보인다.
BUSHES = [
    (-6.0, 5.6, 3.0, 1.9), (6.0, -5.6, 3.0, 1.9),
    (-17.0, -5.6, 3.0, 1.9), (17.0, 5.6, 3.0, 1.9),
]


def bush_at(x, z):
    """(x, z) 가 들어 있는 부쉬 번호 (없으면 -1)."""
    for i, (bx, bz, rx, rz) in enumerate(BUSHES):
        if ((x - bx) / rx) ** 2 + ((z - bz) / rz) ** 2 <= 1.0:
            return i
    return -1


# 시야 격자 (클라이언트 전장의 안개 표시용): 맵을 덮는 범위와 칸 크기
VIS_X0, VIS_X1 = -58.0, 58.0
VIS_Z0, VIS_Z1 = -13.0, 13.0
VIS_CELL = 0.25


def spawn_points(team, count):
    fx, fz = fountain_pos(team)
    pts = []
    for i in range(count):
        ang = (i / max(1, count)) * math.tau + 0.3
        pts.append((fx + math.cos(ang) * 2.2, fz + math.sin(ang) * 2.2))
    return pts


def minion_spawn(team):
    return (-33.5 if team == BLUE else 33.5, 0.0)
