"""인게임 화면.

조작 (롤과 비슷하게)
- 우클릭: 이동 / 적 클릭 시 공격 (누르고 있으면 계속 이동)
- Q W E R: 누르고 있으면 범위 표시, 떼면 마우스 위치로 시전 (즉시형 스킬은 바로 시전)
  · 아군 지정 스킬은 마우스에서 가장 가까운 아군(나 포함)에게, 먼 거리 순간이동 스킬은 미니맵을 눌러도 쓸 수 있다
- Ctrl + Q/W/E/R: 스킬 레벨 업 (HUD 의 + 버튼 클릭도 가능)
- D: 점멸, F: 표식(눈덩이) — 맞힌 뒤 F 를 다시 누르면 대상에게 돌진
- A + 좌클릭: 공격 이동, S: 정지
- B: 귀환 (8초 정신집중, 이동/공격/스킬/피해 시 취소), P: 상점 (사망 중이거나 우물 안에서만 구매, 되돌리기는 상점을 벗어나기 전까지), Tab: 점수판
- 시야: 아군 주변만 보이고(전장의 안개), 부쉬 안의 적은 같은 부쉬에 들어가야 보인다
- Y: 카메라 고정/자유 전환 (처음엔 자유 카메라), F6~F9: 테스트 치트 (체력/마나/쿨타임/레벨), Space: 내 챔피언으로 카메라 이동, 마우스 휠: 줌
- Enter: 채팅 (Enter 로 보내기, Esc 로 취소). 킬·포탑 파괴 같은 알림도 채팅창에 올라온다
"""
import math
import time

import moderngl
import numpy as np
import pygame

from ...shared import data as gamedata
from ...shared import mapdata
from ...shared.spells import DEFAULT_SPELLS, SPELLS
from ...shared.constants import (
    BLUE, FLASH_COOLDOWN, FLASH_RANGE, INVENTORY_SLOTS, MARK_COOLDOWN, MARK_RANGE, MARK_RECAST_TIME, RECALL_TIME, RED,
    SELL_RATIO, SIGHT,
)
from .. import ui
from ..app import HEIGHT, WIDTH, Scene
from ..geometry import MeshBuilder
from ..gl import Mesh, facing_to_rot, model_matrix
from ..procedural import build_bush
from ..rigs import CHAMP_SCALE
from ..rigs.spider import SC as SC_RIG, baby_period
from ..vfx import SUPPORT_FX, SUPPORT_SPELLS, Vfx, fx_color

MINION_KEYS = {0: "minion_melee", 1: "minion_caster", 2: "minion_cannon", 3: "minion_super", 4: "minion_spiderling"}
BABY_PERIOD = baby_period()          # 새끼 거미 걸음 한 주기(초)
ATTACK_SFX_VOL = 0.4                  # 일반 공격·미니언 공격 효과음 배율 (원래 소리의 40%)
MANA_BLUE = (90, 170, 255)         # 마나 표시 글자 색
BABY_ATTACK_TILT = -0.55         # 새끼 거미가 공격할 때 앞을 드는 각도(라디안)
MINION_RADIUS = {0: 0.45, 1: 0.4, 2: 0.6, 3: 0.75, 4: 0.34}
MINION_HEIGHT = {0: 1.2, 1: 1.25, 2: 1.1, 3: 2.0, 4: 0.7}
PROJ_SPEED = {"arrow": 22, "snowball": 25, "turret_shot": 16, "turret_shot_2": 16, "turret_shot_3": 16, "minion_bolt": 14, "cannon_ball": 14,
              "web_shot": 20, "baby_shot": 20, "fire_bolt": 18, "tornado": 9, "scythe": 17}
# 투사체별 (높이, 발광색)
PROJ_LOOK = {"turret_shot": (3.2, (0.3, 0.3, 0.3)), "turret_shot_2": (3.2, (0.5, 0.25, 0.1)), "turret_shot_3": (3.2, (0.7, 0.15, 0.08)), "minion_bolt": (0.8, None), "cannon_ball": (0.8, None),
             "snowball": (1.1, (0.3, 0.3, 0.3)), "web_shot": (1.0, (0.2, 0.2, 0.15)), "baby_shot": (0.8, (0.2, 0.2, 0.15)),
             "fire_bolt": (1.9, (0.9, 0.4, 0.08)), "tornado": (0.0, None)}
RING_THIN = 0.04            # models.py 의 ring_thin 두께 비율 (바깥 반지름의 몇 %가 선 두께인가)
# 투사체 크기 배율 (잘 보이도록 모델보다 키워서 그린다)
PROJ_SCALE = {"arrow": 1.4, "snowball": 1.35, "turret_shot": 1.0, "turret_shot_2": 1.0, "turret_shot_3": 1.0, "minion_bolt": 1.8, "cannon_ball": 1.5,
              "web_shot": 1.3, "baby_shot": 1.0, "fire_bolt": 1.0, "tornado": 1.0}
# 챔피언 머리 위/아래에 붙는 상태 표시 (이름, 색)
STATUS_BADGES = [
    ("silence", "침묵", (150, 90, 220)), ("root", "속박", (160, 120, 60)), ("air", "공중", (120, 190, 255)),
    ("exhaust", "탈진", (190, 140, 230)), ("ignite", "점화", (255, 130, 80)),
    ("immune", "면역", (230, 235, 245)), ("ghost", "유령", (150, 230, 200)),
]
STAT_LABELS = [("ad", "공격력", 1), ("ap", "주문력", 1), ("hp", "체력", 1), ("mana", "마나", 1),
               ("armor", "방어력", 1), ("mr", "마법 저항력", 1), ("attack_speed", "공격 속도 %", 100),
               ("move_speed", "이동 속도", 100), ("ability_haste", "스킬 가속", 1), ("crit", "치명타 %", 100),
               ("life_steal", "생명력 흡수 %", 100), ("hp_regen", "체력 재생", 1)]
SLOTS = ("Q", "W", "E", "R")
# 마우스 아래 유닛 판정 반경 (줌 22 기준 화면 픽셀). 모델보다 넉넉하게 잡아 평타 클릭이 쉽게
HOVER_RADIUS = {"champion": 58, "minion": 38}

HUD_RECT = pygame.Rect(300, 606, 680, 108)
MM_BG = (14, 11, 8, 240)                # 미니맵 바탕: 길 바깥쪽과 같은 어두운 색
MM_PAD = 2                              # 미니맵 좌우 여백 (px)
MINIMAP_X = 58.0                        # 미니맵이 덮는 x 범위 (±)
INV_COLS = 4                            # 인벤토리 4칸 x 2줄
CHAT_X, CHAT_Y, CHAT_W = 12, 572, 440     # 채팅 입력칸 (왼쪽 아래, 로그는 그 위로 쌓임)
CHAT_FONT, CHAT_LINE = 16, 22              # 채팅 글자 크기, 줄 간격
CHAT_SHOW = 10.0                           # 채팅창이 닫혀 있을 때 새 줄이 보이는 시간 (초)
BAR_H = 2.45 * CHAMP_SCALE + 0.2      # 챔피언 체력바 높이
PICK_H = 2.0 * CHAMP_SCALE           # 챔피언을 마우스로 고를 수 있는 높이
# 핑: 종류 -> (이름, 색). 핑 키(G)나 Alt 를 누른 채 좌클릭하면 신호, 누른 채 끌면 방향에 따라 위험 / 가는 중 / 도움 요청 / 실종
PINGS = {"alert": ("신호", (255, 215, 90)), "danger": ("위험", (255, 80, 70)), "omw": ("가는 중", (90, 165, 255)),
         "assist": ("도움 요청", (110, 235, 130)), "missing": ("실종", (255, 190, 60))}
PING_DIRS = (("danger", 0, -1), ("omw", 1, 0), ("assist", 0, 1), ("missing", -1, 0))     # 끄는 방향 -> 핑 종류
PING_TIME = 3.0
CHAT_WHITE = (255, 255, 255)
TURRET_TOP = 4.35              # 포탑 꼭대기 수정 높이: 레이저와 포탄이 여기서 나간다
ZOOM_MAX = 22.0                 # 마우스 휠로 멀리 볼 수 있는 한계 (처음 화면)
MOVE_COLOR = (0.35, 0.65, 1.0)          # 이동 지점 표시 색
MOVE_COLOR_UI = (110, 175, 255)
# 능력치 패널: (아이콘 파일 키, 이름, 값 함수). 아이콘은 assets/ui/stats/<키>.png 를 넣으면 쓰인다.
STAT_ICONS = [
    ("ad", "공격력", lambda st: st["ad"]), ("ap", "주문력", lambda st: st["ap"]),
    ("armor", "방어력", lambda st: st["ar"]), ("mr", "마법 저항력", lambda st: st["mr"]),
    ("attack_speed", "공격 속도", lambda st: st["aspd"]), ("move_speed", "이동 속도", lambda st: st["ms"]),
    ("ability_haste", "스킬 가속", lambda st: st["ah"]), ("crit", "치명타 확률", lambda st: f"{st['cr']}%"),
]
# 아이콘 파일이 없을 때 쓰는 임시 아이콘 (색, 글자)
STAT_FALLBACK = {"ad": ((230, 140, 60), "공"), "ap": ((160, 110, 240), "주"), "armor": ((210, 170, 80), "방"),
                 "mr": ((110, 170, 240), "마"), "attack_speed": ((240, 210, 90), "속"),
                 "move_speed": ((200, 210, 220), "이"), "ability_haste": ((120, 210, 230), "가"),
                 "crit": ((235, 90, 80), "치")}
MINIMAP = pygame.Rect(1000, 606, 270, 108)
TEAMFRAME = pygame.Rect(1000, 392, 270, 208)      # 미니맵 위 팀 프로필 (아군 체력 / 적 사망 표시)
ABILITY_X = {"Q": 392, "W": 454, "E": 516, "R": 578}
SPELL_X = {"D": 652, "F": 702}


def _seg_dist(px, py, a, b):
    """점 (px, py) 와 화면 선분 a-b 사이의 거리."""
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    ll = vx * vx + vy * vy
    k = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / ll))
    return math.hypot(px - (ax + vx * k), py - (ay + vy * k))


# 스킬 상세 설명 (Shift): (데이터 키, 이름, 표시 형식). 값이 리스트면 스킬 레벨별 값, 아니면 고정 값으로 보여준다.
RANK_STATS = [("cooldown", "재사용 대기시간", "{:g}초"), ("mana", "마나 소모", "{:g}"), ("damage", "피해량", "{:g}"), ("damage_per_sec", "초당 피해량", "{:g}"),
              ("cone_damage", "부채꼴 피해량", "{:g}"), ("path_damage", "지나는 길 피해량", "{:g}"),
              ("airborne", "공중에 띄움", "{:g}초"), ("wall_stun", "벽 충돌 기절", "{:g}초"), ("duration", "지속 시간", "{:g}초"),
              ("baby_ad", "새끼 거미 평타 피해", "{:g}"), ("baby_hp", "새끼 거미 체력", "{:g}"), ("cocoon_hp", "고치 체력", "{:g}")]
FLAT_STATS = [("ad_ratio", "공격력 계수", "{:.0%}"), ("damage_per_sec_ad", "초당 피해 공격력 계수", "{:.0%}"),
              ("cone_damage_ad", "부채꼴 피해 공격력 계수", "{:.0%}"), ("path_damage_ad", "지나는 길 피해 공격력 계수", "{:.0%}"), ("bonus_ad_ratio", "추가 공격력 계수", "{:.0%}"),
              ("ap_ratio", "주문력 계수", "{:.0%}"), ("damage_per_sec_ap", "초당 피해 주문력 계수", "{:.0%}"),
              ("cone_damage_ap", "부채꼴 피해 주문력 계수", "{:.0%}"), ("path_damage_ap", "지나는 길 피해 주문력 계수", "{:.0%}"), ("baby_ad_ratio", "새끼 거미 공격력 계수", "{:.0%}"),
              ("range", "사거리", lambda v: f"{v * 100:g}"), ("radius", "범위 반경", lambda v: f"{v * 100:g}"), ("angle", "각도", "{:g}°"),
              ("knock_distance", "밀어내는 거리", lambda v: f"{v * 100:g}"), ("count", "투척 수", "{:g}자루"),
              ("slow", "둔화", "{:.0%}"), ("slow_duration", "둔화 시간", "{:g}초"), ("stun", "기절", "{:g}초"),
              ("root", "속박", "{:g}초"), ("silence", "침묵", "{:g}초"), ("delay", "발동 지연", "{:g}초")]
DAMAGE_TYPES = {"physical": "물리", "magic": "마법", "true": "고정"}
DAMAGE_TAGS = {"physical": "AD", "magic": "AP", "true": "고정"}
# 피해량 행: 데이터 키 -> 피해 유형을 정하는 방법 (없으면 스킬의 damage_type)
DAMAGE_KEYS = {"damage", "damage_per_sec", "cone_damage", "path_damage", "baby_ad"}


TAG_COLORS = {"AD": (240, 150, 70), "AP": (175, 130, 255), "고정": (235, 235, 235)}


def draw_detail_label(surf, label, pos, size=13, color=None):
    """상세 값 행의 이름. 끝의 (AD) / (AP) 는 색을 달리해 그린다."""
    color = color or ui.TEXT_DIM
    for tag, tc in TAG_COLORS.items():
        suffix = f" ({tag})"
        if label.endswith(suffix):
            x = ui.text(surf, label[: -len(suffix)] + " ", pos, size, color).right
            return ui.text(surf, tag, (x, pos[1]), size, tc, bold=True)
    return ui.text(surf, label, pos, size, color)


def detail_value_x(details, size=13, min_x=140):
    """상세 값 열의 시작 위치 (가장 긴 이름 뒤)."""
    return max([min_x] + [ui.font(size).size(label)[0] + 16 for label, _ in details])


def damage_tag(ab, key):
    """피해량 행에 붙일 AD / AP 표시."""
    if key == "baby_ad":
        dtype = "physical"
    else:
        dtype = ab.get("damage_type", "physical")
    return DAMAGE_TAGS.get(dtype, dtype)


_PORTRAITS = {}


def champ_portrait(chid, size, gray=False):
    """assets/ui/portraits/<챔피언id>.png (tools/build_portraits.py 로 생성). 없으면 None. gray=True 면 흑백."""
    key = (chid, size, gray)
    if key not in _PORTRAITS:
        img = ui.icon(f"assets/ui/portraits/{chid}.png", size)
        if img is not None and gray:
            img = img.copy()
            arr = pygame.surfarray.pixels3d(img)
            g = (arr[..., 0] * 0.3 + arr[..., 1] * 0.59 + arr[..., 2] * 0.11).astype("uint8")
            for c in range(3):
                arr[..., c] = g
            del arr
        _PORTRAITS[key] = img
    return _PORTRAITS[key]


_ROUND = {}


def draw_round_portrait(surf, chid, center, r, ring, dead=False, color=(160, 170, 190), ring_w=2):
    """원형 챔피언 초상화 (HUD·점수판·챔피언 선택 공통). 초상화 파일이 없으면 색 원 + 첫 글자."""
    key = (chid, r, dead)
    if key not in _ROUND:
        img = champ_portrait(chid, r * 2, dead)
        if img is not None:
            img = img.copy()
            mask = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(mask, (255, 255, 255, 255), (r, r), r)
            img.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        _ROUND[key] = img
    img = _ROUND[key]
    if img is not None:
        surf.blit(img, (center[0] - r, center[1] - r))
        if dead:
            shade(surf, pygame.Rect(center[0] - r, center[1] - r, r * 2, r * 2), (0, 0, 0, 55), r)
    else:
        data = gamedata.champion(chid) or {}
        col = tuple(v // 3 for v in color) if dead else tuple(color)
        pygame.draw.circle(surf, col, center, r)
        ui.text(surf, (data.get("name") or "?")[0], center, int(r * 0.9), (20, 30, 50) if not dead else (90, 90, 100),
                anchor="center", bold=True, shadow=False)
    if ring_w > 0:
        pygame.draw.circle(surf, ring if not dead else (110, 112, 120), center, r, ring_w)


def draw_hp_ring(surf, center, r, ratio, color, width=3):
    """초상화 둘레의 원형 체력 표시: 12시 방향에서 시계 방향으로 체력 비율만큼 색이 차 있고 나머지는 어둡다.
    4배 크기로 그려 줄여서 가장자리가 매끈하다."""
    k = 4
    size = (r + 2) * 2 * k
    c = size / 2
    img = pygame.Surface((size, size), pygame.SRCALPHA)
    r_out, r_in = r * k, (r - width) * k
    pygame.draw.circle(img, (24, 24, 32, 235), (c, c), r_out)
    pygame.draw.circle(img, (0, 0, 0, 0), (c, c), r_in)
    ratio = max(0.0, min(1.0, ratio))
    if ratio > 0.002:
        n = max(2, int(72 * ratio) + 2)
        a0 = -math.pi / 2
        pts = [(c + math.cos(a0 + math.tau * ratio * i / n) * r_out, c + math.sin(a0 + math.tau * ratio * i / n) * r_out) for i in range(n + 1)]
        pts += [(c + math.cos(a0 + math.tau * ratio * i / n) * r_in, c + math.sin(a0 + math.tau * ratio * i / n) * r_in) for i in range(n, -1, -1)]
        if ratio >= 0.998:
            pygame.draw.circle(img, (*color, 255), (c, c), r_out)
            pygame.draw.circle(img, (0, 0, 0, 0), (c, c), r_in)
        else:
            pygame.draw.polygon(img, (*color, 255), pts)
    small = pygame.transform.smoothscale(img, (size // k, size // k))
    surf.blit(small, (center[0] - size // k // 2, center[1] - size // k // 2))


def shade(surf, rect, color, radius=0):
    """rect 위에 반투명 색(라운드 모서리)을 덮는다."""
    sh = pygame.Surface(pygame.Rect(rect).size, pygame.SRCALPHA)
    pygame.draw.rect(sh, color, sh.get_rect(), border_radius=radius)
    surf.blit(sh, rect)


def _fmt_stat(fmt, v):
    return fmt(v) if callable(fmt) else fmt.format(v)


def ability_details(ab):
    """스킬 데이터 -> [(이름, 값)] — 값이 리스트면 스킬 레벨별 값."""
    rows = []

    def add(key, label, fmt):
        v = ab[key]
        if key in DAMAGE_KEYS:
            label = f"{label} ({damage_tag(ab, key)})"
        rows.append((label, [_fmt_stat(fmt, x) for x in v] if isinstance(v, (list, tuple)) else _fmt_stat(fmt, v)))

    for key, label, fmt in RANK_STATS:
        if key in ab and key != "duration":
            add(key, label, fmt)
    if "duration" in ab:
        add("duration", "지속 시간", "{:g}초")
    for key, label, fmt in FLAT_STATS:
        if key in ab:
            add(key, label, fmt)
    return rows


def draw_item(surf, iid, rect, font_size=14):
    """아이템 아이콘 (assets/items/<id>.png). 파일이 없으면 색 사각형 + 첫 글자."""
    rect = pygame.Rect(rect)
    icon = ui.icon(f"assets/items/{iid}.png", rect.width)
    if icon:
        surf.blit(icon, rect)
        return
    it = gamedata.items()[iid]
    pygame.draw.rect(surf, tuple(it["color"]), rect, border_radius=4)
    ui.text(surf, it["name"][0], rect.center, font_size, (20, 20, 30), anchor="center", bold=True, shadow=False)


def beam_matrix(x0, y0, z0, x1, y1, z1, width):
    """막대 메시(z: 0~1, 단면 1x1)를 (x0,y0,z0) 에서 (x1,y1,z1) 까지 굵기 width 로 늘이는 행렬 (기울기까지 정확히)."""
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    fwd = np.array([dx, dy, dz]) / length
    up = np.array([0.0, 1.0, 0.0]) if abs(fwd[1]) < 0.99 else np.array([1.0, 0.0, 0.0])
    side = np.cross(up, fwd)
    side /= np.linalg.norm(side)
    up2 = np.cross(fwd, side)
    m = np.eye(4, dtype="f4")
    m[:3, 0] = side * width
    m[:3, 1] = up2 * width
    m[:3, 2] = fwd * length
    m[:3, 3] = (x0, y0, z0)
    return m


def sell_text(item):
    """판매 가격 글자 (롤 상점처럼 금액과 비율)."""
    return f"판매 {round(item['cost'] * SELL_RATIO)} G ({round(SELL_RATIO * 100)}%)"


def item_stat_text(item):
    parts = []
    for key, label, mul in STAT_LABELS:
        v = item["stats"].get(key)
        if v:
            parts.append(f"{label} +{round(v * mul)}")
    return ", ".join(parts)


class CEnt:
    """스냅샷 사이를 부드럽게 보간하는 클라이언트 쪽 유닛."""

    def __init__(self, eid, x, z, f=0.0):
        self.id = eid
        self.x = self.tx = x
        self.z = self.tz = z
        self.f = self.tf = f
        self.d = None
        self.swing_t = -10.0        # 마지막 공격 휘두르기 시작 시각 (미니언 무기 모션)
        self.visible = True         # 이번 스냅샷에 포함됐는가 (시야 밖의 적은 빠진다)
        self.lift = 0.0             # 공중에 띄워진 높이 (에어본·외줄)
        self.ca = None              # 뼈대 애니메이션 제어기 (챔피언 전용, models.new_champ_anim)
        self.last_swing = -10.0     # 마지막으로 기본 공격 소리를 낸 시각
        self.ca_dt = 0.0            # 아직 동작 제어기에 넘기지 않은 시간 (화면 밖이면 몰아서 가끔 갱신)
        self.onscreen = True        # 지난 프레임 카메라 기준으로 화면 안(조금 넉넉히)에 있는가

    def set_target(self, x, z, f):
        if math.hypot(x - self.x, z - self.z) > 6.0:      # 순간이동(점멸, 부활 등)
            self.x, self.z = x, z
        self.tx, self.tz, self.tf = x, z, f

    def step(self, dt):
        k = min(1.0, dt * 14.0)
        self.x += (self.tx - self.x) * k
        self.z += (self.tz - self.z) * k
        df = (self.tf - self.f + math.pi) % math.tau - math.pi
        self.f += df * min(1.0, dt * 16.0)


class GameScene(Scene):
    fullscreen = True       # 인게임은 전체 화면 (Alt+Enter 로 전환 가능)
    grab_mouse = True       # 커서를 화면 안에 가둬 화면 끝 카메라 이동이 되게

    def __init__(self, app, start):
        super().__init__(app)
        self.structs = {s["i"]: s for s in start["structures"]}
        self.struct_state = {s["i"]: [s["i"], s["mhp"], 1, 0, 0] for s in start["structures"]}
        self.champ_info = {c["i"]: c for c in start["champions"]}
        self.my_id = next((c["i"] for c in start["champions"] if c["pk"] == start["you"]), None)
        self.my_team = self.champ_info[self.my_id]["tm"] if self.my_id else BLUE
        self.champs = {}
        self.minions = {}
        self.projs = {}
        self.ground_effects = []
        self.ef_total = {}          # 장판 id -> 처음 받은 남은 시간 (예고 연출 진행도 계산용)
        self.zones = []             # 성역·정원·덫·대종 감옥 등 (row, 받은 시각)
        self.anchors = []           # 거미 고치 (row, 받은 시각)
        self.relics = []
        self.fx = []
        self.cast_msg = None               # (안내 문구, 만료 시각)
        self.leap_marks = {}               # 도약 중인 시전자 id -> 착지 범위 표시
        self.vfx = Vfx(app.renderer)           # 그림(스프라이트) 입자 이펙트 (스킬 컨셉 연출)
        self.floaters = []
        self.killfeed = []
        self.announces = []
        self.pings = []             # [{"x","z","k","t","d"}] 같은 팀이 찍은 핑
        self.ping_drag = None       # 핑을 찍으려고 누르고 있는 중: {"pos": 화면 위치, "x", "z"}
        self.kill_banner = None     # (시각, 처치 이벤트, 문구) — 화면 위 가운데에 처치한 쪽 · 문구 · 처치당한 쪽
        self.server_time = 0.0
        self.score = [0, 0]
        self.wave_in = 0.0
        self.winner = None
        self.over_at = 0.0
        self.audio = app.audio
        self.last_kill_at = -99.0   # 내가 마지막으로 처치한 시각 (연속 처치 알림용)
        self.my_ranks = None        # 내 스킬 레벨 / 아이템 수 (올랐는지 알아보려고)
        self.my_item_count = None
        self.foot_t = 0.0           # 다음 발소리까지 남은 시간
        self.shop_was_open = False

        self.shop_open = False
        self.show_score = False
        self.cam_locked = False          # 처음엔 자유 카메라 (Y 로 고정 전환)
        self.aiming = None
        self.amove_pending = False
        self.rmb_down = False
        self.rmb_repeat = 0.0
        self.hover = None
        self.hover_slot = None
        self.click_marker = None
        self.move_dest = None       # 이동 목적지 (도착할 때까지 바닥에 표시)
        self.minimap_drag = False   # 미니맵을 좌클릭한 채로 끌면 카메라 이동
        self.rmb_minimap = False    # 미니맵을 우클릭한 채로 있으면 계속 이동 명령
        self.shop_rects = []
        self.shop_buy_rect = None      # 상점 오른쪽 구매 버튼
        self.shop_undo_rect = None     # 상점 되돌리기 버튼
        self.shop_tip = None           # 상점에서 마우스를 올린 아이템 정보 (마우스, 아이템 id, 가진 아이템)
        self.inv_drag = None           # 인벤토리에서 끌고 있는 칸 번호
        self.hud_slot_rects = []       # HUD 인벤토리 8칸 전부 (빈 칸 포함, 끌어다 놓을 자리)
        self.slam_follow = {}          # 이무기 id -> (내려찍기 대상 id, 끝나는 시각)
        self.shop_sel = None           # 상점에서 고른 아이템 (구매 버튼으로 살 것)
        self.shop_view = None          # 상점 오른쪽에 조합 트리를 보여 주는 아이템
        self.shop_sel_pos = None       # 트리에서 고른 칸 위치
        self.levelup_rects = []
        self.hud_inv_rects = []     # HUD 인벤토리 칸 (상점이 열려 있으면 우클릭 판매)
        self.gold_rect = None       # 골드 글자 (클릭하면 상점 열기/닫기)
        self.hud_tooltip = None     # 상점·점수판 위에 그리도록 마지막에 그린다
        self.chat_lines = []        # (시각, [(글자, 색), ...]) — 플레이어 채팅과 킬·파괴 알림
        self.chat_open = False
        self.chat_in = ui.TextInput((CHAT_X, CHAT_Y, CHAT_W, 26), "", 100, "Enter 로 보내기 · Esc 취소")
        self.zoom = ZOOM_MAX
        self.fake_mouse = None      # 자동 테스트용
        self.binds = app.keybinds
        self.held = set()           # 누르고 있는 행동 (카메라 중심 등)
        self.stat_rects = []

        # 스킬 범위 표시용 사각형 메시 (x: -0.5~0.5, z: 0~1)
        b = MeshBuilder()
        b.rect_xz(-0.5, 0.0, 0.5, 1.0, 0.0, (1, 1, 1))
        self.quad = Mesh.from_builder(app.renderer, b)
        # 선 모양 효과용 막대 (z: 0~1, 단면 1x1) / 세로 기둥 (반지름 1, 높이 1) / 부채꼴 캐시
        b = MeshBuilder()
        b.box((0, 0, 0.5), (1, 1, 1), (1, 1, 1))
        self.beam = Mesh.from_builder(app.renderer, b)
        b = MeshBuilder()
        b.cylinder((0, 0, 0), 1.0, 1.0, (1, 1, 1), seg=16, cap=False)
        self.pillar = Mesh.from_builder(app.renderer, b)
        self.sectors = {}

        for cid, info in self.champ_info.items():
            app.models.champion(info["c"])

        # 부쉬
        # 모든 부쉬가 같은 모양 (크기가 같으면 같은 메시를 공유)
        shapes = {}
        for bx, bz, rx, rz in mapdata.BUSHES:
            if (rx, rz) not in shapes:
                shapes[(rx, rz)] = Mesh.from_builder(app.renderer, build_bush(rx, rz))
        self.bush_meshes = [shapes[(rx, rz)]
                            for i, (bx, bz, rx, rz) in enumerate(mapdata.BUSHES)]
        self.board = {}             # 점수판(Tab): 챔피언 id -> [id, 레벨, 킬, 데스, 어시, CS, 골드, 아이템, 사망, 부활초, 현상금]
        # 시야 격자: 칸 중심 좌표와 각 칸의 부쉬 번호를 미리 계산
        self.vis_nx = int((mapdata.VIS_X1 - mapdata.VIS_X0) / mapdata.VIS_CELL)
        self.vis_nz = int((mapdata.VIS_Z1 - mapdata.VIS_Z0) / mapdata.VIS_CELL)
        xs = mapdata.VIS_X0 + (np.arange(self.vis_nx) + 0.5) * mapdata.VIS_CELL
        zs = mapdata.VIS_Z0 + (np.arange(self.vis_nz) + 0.5) * mapdata.VIS_CELL
        self.vis_x, self.vis_z = np.meshgrid(xs, zs)
        hw = np.array([mapdata.half_width(x) + 0.5 for x in xs])
        self.vis_walk = (np.abs(zs)[:, None] <= hw[None, :]).astype(np.float32)      # 길 안쪽 칸 (미니맵 안개를 여기만)
        # 부쉬는 가장자리가 부드럽게 넘어가도록 칸마다 "부쉬 안쪽 정도"(0~1)를 미리 계산한다
        nb = len(mapdata.BUSHES)
        bsoft = np.zeros((nb,) + self.vis_x.shape, dtype=np.float32)
        for i, (bx, bz, rx, rz) in enumerate(mapdata.BUSHES):
            ell = np.sqrt(((self.vis_x - bx) / rx) ** 2 + ((self.vis_z - bz) / rz) ** 2)
            bsoft[i] = np.clip((1.12 - ell) / 0.24, 0.0, 1.0)
        # 관찰자가 있는 부쉬(-1 = 부쉬 밖)별로, 그 관찰자가 "볼 수 없는" 다른 부쉬 칸의 정도
        self.vis_block = {ob: (np.max(np.delete(bsoft, ob, axis=0), axis=0) if nb > 1 else np.zeros(self.vis_x.shape, np.float32))
                          if ob >= 0 else np.max(bsoft, axis=0) for ob in range(-1, nb)}
        self.vis = np.ones(self.vis_x.shape, dtype=np.float32)
        self.vis_tex = app.renderer.ctx.texture((self.vis_nx, self.vis_nz), 1, dtype="f1")
        self.vis_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.vis_tex.repeat_x = self.vis_tex.repeat_y = False
        self.vis_rect = (mapdata.VIS_X0, mapdata.VIS_Z0, mapdata.VIS_X1 - mapdata.VIS_X0,
                         mapdata.VIS_Z1 - mapdata.VIS_Z0)
        self.vis_timer = 0.0
        self.minimap_fog = None

        cam = app.renderer.camera
        x, z = mapdata.fountain_pos(self.my_team)
        cam.tx, cam.ty, cam.tz = x, 0.0, z
        cam.pitch = math.radians(56)
        cam.yaw = 0.0
        cam.distance = self.zoom

    def on_enter(self):
        # 텍스트 입력(IME)이 켜져 있으면 한글 모드에서 스킬 키가 입력기로 빠져 나가므로 끈다
        pygame.key.stop_text_input()
        self.app.renderer.vision = (self.vis_tex, self.vis_rect)
        self.announce("welcome", 9)

    # ------------------------------------------------------------------ 시야
    def update_vision(self):
        """아군 시야 제공자로 시야 격자를 계산해 셰이더(전장의 안개)와 미니맵에 쓴다.

        서버가 실제로 보내 주는 적 정보도 같은 규칙(시야 반경, 부쉬)을 따른다.
        """
        obs = [(*mapdata.fountain_pos(self.my_team), SIGHT["fountain"])]
        for cid, e in self.champs.items():
            if self.champ_info[cid]["tm"] == self.my_team and e.d and not e.d["dead"]:
                obs.append((e.x, e.z, SIGHT["champion"]))
        for e in self.minions.values():
            if e.d[2] == self.my_team:
                obs.append((e.x, e.z, SIGHT["minion"]))
        for sid, st in self.structs.items():
            if st["tm"] == self.my_team and self.struct_state[sid][2]:
                obs.append((st["x"], st["z"], SIGHT[st["k"]]))
        for row, _ in self.anchors:                      # 내 팀 거미 고치: 주변만 좁게
            if row[1] == self.my_team:
                obs.append((row[2], row[3], SIGHT["cocoon"]))
        # 칸마다 "얼마나 보이는가"(0~1)를 거리에 따라 부드럽게 계산한다 (가장자리를 계단 없이 번지게)
        vis = np.zeros(self.vis_x.shape, dtype=np.float32)
        cell = mapdata.VIS_CELL
        soft = 1.6
        for ox, oz, r in obs:
            reach = r + soft
            i0 = max(0, int((ox - reach - mapdata.VIS_X0) / cell))
            i1 = min(self.vis_nx, int((ox + reach - mapdata.VIS_X0) / cell) + 2)
            j0 = max(0, int((oz - reach - mapdata.VIS_Z0) / cell))
            j1 = min(self.vis_nz, int((oz + reach - mapdata.VIS_Z0) / cell) + 2)
            if i1 <= i0 or j1 <= j0:
                continue
            d = np.hypot(self.vis_x[j0:j1, i0:i1] - ox, self.vis_z[j0:j1, i0:i1] - oz)
            v = np.clip((r + soft * 0.5 - d) / soft, 0.0, 1.0)
            v *= 1.0 - self.vis_block[mapdata.bush_at(ox, oz)][j0:j1, i0:i1]
            np.maximum(vis[j0:j1, i0:i1], v, out=vis[j0:j1, i0:i1])
        self.vis += (vis - self.vis) * 0.5
        self.vis_tex.write(np.rint(self.vis * 255).astype(np.uint8).tobytes())
        # 미니맵용 안개 (안 보이는 곳을 어둡게)
        fog = np.zeros((self.vis_nx, self.vis_nz, 4), dtype=np.uint8)
        fog[..., 3] = ((1.0 - self.vis.T) * 150 * self.vis_walk.T).astype(np.uint8)       # 길 밖은 바탕색 그대로
        surf = pygame.image.frombuffer(np.ascontiguousarray(fog.transpose(1, 0, 2)).tobytes(),
                                       (self.vis_nx, self.vis_nz), "RGBA")
        x0, z0 = self.world_to_minimap(mapdata.VIS_X0, mapdata.VIS_Z0)
        x1, z1 = self.world_to_minimap(mapdata.VIS_X1, mapdata.VIS_Z1)
        self.minimap_fog = (pygame.transform.smoothscale(surf, (max(1, x1 - x0), max(1, z1 - z0))), (x0, z0))

    # ------------------------------------------------------------------ 도우미
    @property
    def me(self):
        e = self.champs.get(self.my_id)
        return e.d if e else None

    def seen_bushes(self):
        """우리 팀 시야 제공자가 들어가 있어 안이 보이는 부쉬 번호들."""
        pts = [(e.x, e.z) for cid, e in self.champs.items()
               if self.champ_info[cid]["tm"] == self.my_team and e.d and not e.d["dead"]]
        pts += [(e.x, e.z) for e in self.minions.values() if e.d[2] == self.my_team]
        pts += [(row[2], row[3]) for row, _ in self.anchors if row[1] == self.my_team]
        return {b for b in (mapdata.bush_at(x, z) for x, z in pts) if b >= 0}

    def view_team(self, team):
        """화면에 보일 팀 색: 내 팀은 어느 쪽이든 항상 파랑, 상대 팀은 빨강."""
        return BLUE if team == self.my_team else RED

    def my_data(self):
        return gamedata.champion(self.champ_info[self.my_id]["c"]) if self.my_id else None

    def mouse_pos(self):
        return self.fake_mouse or ui.mouse_pos()

    def mouse_ground(self):
        mx, my = self.mouse_pos()
        return self.app.renderer.camera.screen_to_ground(mx, my) or (0.0, 0.0)

    def send_cmd(self, **kw):
        self.app.send({"t": "cmd", **kw})

    def max_rank(self, slot, level):
        if slot == "R":
            return sum(1 for lv in (6, 11, 16) if level >= lv)
        return min(5, (level + 1) // 2)

    # ------------------------------------------------------------------ 메시지
    def on_message(self, msg):
        t = msg.get("t")
        if t == "snap":
            self.apply_snapshot(msg)
        elif t == "chat":
            col = ui.TEAM_UI.get(msg.get("team"), ui.TEXT)
            self.add_chat([(f"{msg['name']}: ", col), (msg["text"], ui.TEXT)])
        elif t == "game_over":
            self.winner = msg["winner"]
            self.over_at = time.time()
            self.audio.play_music(None, 2500)       # 결과 화면에서는 BGM 을 서서히 끈다
            self.announce("victory" if self.winner == self.my_team else "defeat", 10, interrupt=True)

    def apply_snapshot(self, s):
        now = time.time()
        self.server_time = s["time"]
        self.score = s["score"]
        self.wave_in = s.get("wave", 0)

        seen = set()
        for d in s["ch"]:
            e = self.champs.get(d["i"])
            if e is None:
                e = self.champs[d["i"]] = CEnt(d["i"], d["x"], d["z"], d["f"])
            if (e.d and e.d["dead"] and not d["dead"]) or not e.visible:
                e.x, e.z = d["x"], d["z"]       # 부활하거나 안개에서 나타나면 바로 그 자리에
            e.set_target(d["x"], d["z"], d["f"])
            if e.visible:
                self.champ_sounds(e, d, now)
            e.d = d
            e.visible = True
            seen.add(d["i"])
        for cid, e in self.champs.items():
            if cid not in seen:
                e.visible = False               # 시야 밖
        self.board = {row[0]: row for row in s.get("sb", [])}
        gone = set(s.get("gone", []))

        seen = set()
        for row in s["mn"]:
            mid = row[0]
            e = self.minions.get(mid)
            if e is None:
                e = self.minions[mid] = CEnt(mid, row[3], row[4], row[5])
            if row[8] == 2 and (e.d is None or e.d[8] != 2) and now - e.swing_t > 0.3:
                e.swing_t = now
                if row[1] in (0, 3):                # 근접 미니언만 휘두르는 소리 (원거리는 투사체 소리)
                    self.sfx("minion_swing", row[3], row[4], ATTACK_SFX_VOL)
            e.set_target(row[3], row[4], row[5])
            e.d = row
            seen.add(mid)
        for mid in list(self.minions):
            if mid not in seen:
                e = self.minions.pop(mid)
                if mid in gone:                 # 죽은 경우만 효과 (시야 밖으로 나간 경우는 그냥 사라짐)
                    self.add_fx("poof", e.x, e.z, 0.4, color=(0.9, 0.9, 1.0))
                    self.sfx("minion_die", e.x, e.z)

        for row in s["st"]:
            old = self.struct_state.get(row[0])
            if old and old[2] and not row[2]:
                info = self.structs[row[0]]
                self.add_fx("burst", info["x"], info["z"], 1.2, radius=4.0, color=(1.0, 0.7, 0.4))
                self.sfx("struct_destroy" if info["k"] == "turret" else "struct_destroy_big", info["x"], info["z"])
            self.struct_state[row[0]] = row

        seenp = set()
        for row in s["pj"]:
            pid, style, team, x, z, dx, dz = row
            sp = PROJ_SPEED.get(style, 18)
            if pid not in self.projs:
                self.sfx(self.audio.projectile_sound(style), x, z)
            self.projs[pid] = {"style": style, "team": team, "x": x, "z": z, "dx": dx, "dz": dz,
                               "vx": dx * sp, "vz": dz * sp, "t": now}
            seenp.add(pid)
        for pid in list(self.projs):
            if pid not in seenp:
                del self.projs[pid]

        self.ground_effects = [(row, now) for row in s["ef"]]
        for row in s["ef"]:
            self.ef_total[row[0]] = max(self.ef_total.get(row[0], 0.0), row[6])
        if len(self.ef_total) > len(s["ef"]) + 8:
            live = {row[0] for row in s["ef"]}
            self.ef_total = {k: v for k, v in self.ef_total.items() if k in live}
        self.zones = [(row, now) for row in s.get("zn", [])]
        self.anchors = [(row, now) for row in s.get("an", [])]
        self.relics = s["rl"]
        for ev in s["ev"]:
            self.handle_event_msg(ev)

    def handle_event_msg(self, ev):
        e = ev.get("e")
        now = time.time()
        if e == "dmg":
            self.dmg_sounds(ev)
            if ev["s"] == self.my_id:
                tgt = self.entity_pos(ev["d"])
                if tgt:
                    col = {"p": (255, 170, 90), "m": (170, 140, 255), "t": (255, 255, 255)}.get(ev["ty"], (255, 255, 255))
                    self.floaters.append({"x": tgt[0], "z": tgt[1], "text": str(ev["v"]), "color": col, "t": now,
                                          "dur": 0.9, "size": 18})
            elif ev["d"] == self.my_id and ev["v"] >= 30:
                tgt = self.entity_pos(ev["d"])
                if tgt:
                    self.floaters.append({"x": tgt[0], "z": tgt[1], "text": f"-{ev['v']}", "color": (255, 80, 80),
                                          "t": now, "dur": 0.8, "size": 15})
        elif e == "cast":
            ch = self.champs.get(ev["d"])
            if ch and ch.ca:
                ch.ca.cast(ev["slot"])
            self.cast_sound(ev["d"], ev["slot"])
            info = self.champ_info.get(ev["d"])
            if ch and info and ch.d and ch.visible:
                self.vfx.ctx(info["tm"] == self.my_team, False)
                try:
                    self.vfx.cast(info["c"], ev["slot"], ch.x, ch.z, ch.f)
                finally:
                    self.vfx.clear_ctx()
        elif e == "gold" and ev["d"] == self.my_id:
            self.sfx("gold")
            self.floaters.append({"x": ev["x"], "z": ev["z"], "text": f"+{ev['v']}", "color": (250, 210, 90),
                                  "t": now, "dur": 1.0, "size": 16})
        elif e == "kill":
            self.killfeed.append((now, ev))
            self.killfeed = self.killfeed[-6:]
            if ev["k"] == self.my_id:
                self.sfx("kill_self")
                self.last_kill_at = now
            self.kill_announce(ev)
            line = [(ev["kn"], ui.TEAM_UI.get(ev["kt"], ui.TEXT)), (" 님이 ", ui.TEXT_DIM),
                    (ev["vn"], ui.TEAM_UI.get(ev["vt"], ui.TEXT)), (" 님을 처치했습니다.", ui.TEXT_DIM)]
            if ev.get("bt"):
                line.append((f" 제압 골드 {ev['bt']}", ui.GOLD))
            self.add_chat(line)
            self.kill_banner = (now, ev, self.kill_banner_text(ev))
        elif e == "ping":
            self.pings.append({"x": ev["x"], "z": ev["z"], "k": ev["k"], "t": now, "d": ev["d"]})
            self.pings = self.pings[-12:]
            self.sfx("ui_ping_danger" if ev["k"] == "danger" else "ui_ping")
            if ev["k"] != "alert":
                info = self.champ_info.get(ev["d"])
                name, col = PINGS.get(ev["k"], ("", ui.TEXT))
                if info:
                    self.add_chat([(info["n"], ui.TEAM_UI.get(info["tm"], ui.TEXT)), (": ", ui.TEXT_DIM), (name, col)])
        elif e == "announce":
            self.announces.append((now, ev["text"], ui.TEXT))
            text = ev["text"]
            self.sfx("inhib_respawn" if "재생성" in text else "ui_notify")
            self.add_chat([(ev["text"], ui.GOLD)])
        elif e == "vo":
            self.vo_event(ev)
        elif e == "levelup":
            self.sfx_unit(ev["d"], "levelup", 1.0 if ev["d"] == self.my_id else 0.45)
            pos = self.entity_pos(ev["d"])
            if pos:
                self.add_fx("ring_up", pos[0], pos[1], 0.8, radius=1.4, color=(1.0, 0.85, 0.4))
                if ev["d"] == self.my_id:
                    self.floaters.append({"x": pos[0], "z": pos[1], "text": "레벨 업!", "color": (255, 220, 120),
                                          "t": now, "dur": 1.4, "size": 20})
        elif e == "heal":
            if ev["d"] == self.my_id:
                self.sfx("heal")
            pos = self.entity_pos(ev["d"])
            if pos and (ev["d"] == self.my_id or ev["v"] >= 20):
                self.floaters.append({"x": pos[0], "z": pos[1], "text": f"+{ev['v']}", "color": (120, 235, 130),
                                      "t": now, "dur": 0.9, "size": 16})
        elif e == "fx":
            self.handle_fx(ev["fx"], ev)

    def handle_fx(self, kind, ev):
        """서버가 보낸 효과 이벤트 -> 화면 효과. ev["tm"] (스킬을 쓴 팀) 으로 아군 파랑 / 적 빨강을 정하고,
        피해 없이 효과만 주는 스킬은 더 연하고 투명하게 그린다."""
        self.fx_sounds(kind, ev)
        if kind == "leap":                                      # 점프 덮치기: 몸을 공중 자세로
            ch = self.champs.get(ev.get("d"))
            if ch and ch.ca:
                ch.ca.leap(ev.get("dur", 0.5), ev.get("delay", 0.0))
        if kind == "spit" and ev.get("style") != "fire":         # 독 뱉기: 리그가 있으면 실제 입 위치에서 나가게
            ch = self.champs.get(ev.get("d"))
            if ch and ch.ca and hasattr(ch.ca, "mouth") and ch.visible:
                mx_, my_, mz_ = ch.ca.mouth()
                ev = dict(ev, mx=mx_, my=my_, mz=mz_)
        if kind in ("lunge", "serpent_rear", "dive", "dive_out", "sky_dive",    # 이무기: 돌진·내려찍기 준비·잠행·솟구침 자세를 몸에 알린다
                    "reap", "scythe_throw", "scythe_catch"):                    # 사신: 내려치기 준비 시간, 낫이 손을 떠남 / 돌아옴
            ch = self.champs.get(ev.get("d"))
            if ch and ch.ca and hasattr(ch.ca, "on_fx"):
                ch.ca.on_fx(kind, ev)
            if kind == "serpent_rear" and ev.get("tg"):        # 대상 지정 내려찍기: 쳐든 동안 머리가 대상을 따라간다
                self.slam_follow[ev["d"]] = (ev["tg"], time.time() + float(ev.get("dur", 0.75)) + 0.15)
        if kind == "sky_dive":                                  # 불꽃 비행: 시전하는 순간부터 날아가는 동안 지면에 길(바깥·안쪽 바)과 착지 범위 표시
            self.leap_marks[ev.get("d")] = {"tg": None, "x": ev["x2"], "z": ev["z2"], "r": ev["r"], "zr": ev.get("zr", 0.0), "tm": ev.get("tm"),
                                            "ox": ev["x"], "oz": ev["z"], "w": ev.get("w", 5.0), "w2": ev.get("w2", 3.0),
                                            "end": time.time() + ev.get("rise", 1.0) + ev.get("dur", 1.0)}
        if kind == "dive" and ev.get("r"):                      # 잠행: 솟구칠 자리에 범위 표시
            self.leap_marks[ev.get("d")] = {"tg": None, "x": ev["x2"], "z": ev["z2"], "r": ev["r"], "zr": 0.0, "tm": ev.get("tm"),
                                            "end": time.time() + ev.get("sink", 0.6) + ev.get("dur", 0.8)}
        if kind == "leap" and ev.get("r"):
            self.leap_marks[ev.get("d")] = {"tg": ev.get("tg"), "x": ev["x2"], "z": ev["z2"], "r": ev["r"], "zr": ev.get("zr", 0.0),
                                            "tm": ev.get("tm"), "end": time.time() + ev.get("delay", 0.0) + ev.get("dur", 0.5)}
        tm = ev.get("tm")
        style = ev.get("style")
        if kind == "spell":
            support = style in SUPPORT_SPELLS
        else:
            support = kind in SUPPORT_FX
        ally = None if tm is None else tm == self.my_team
        self.fx_ctx = (ally, support)
        try:
            if not self.vfx.play(kind, ev, ally, support):      # 컨셉 이펙트가 없는 효과만 단순 효과로
                self.build_fx(kind, ev)
        finally:
            self.fx_ctx = None

    def build_fx(self, kind, ev):
        x, z = ev["x"], ev["z"]
        rr = ev.get("r", 2.0)
        if kind == "flash":
            self.add_fx("poof", x, z, 0.5, color=(1.0, 1.0, 0.6))
            self.add_fx("poof", ev["x2"], ev["z2"], 0.5, color=(1.0, 1.0, 0.6))
        elif kind == "spell":
            style = ev.get("style")
            if style == "heal":
                self.add_fx("ring_up", x, z, 0.9, radius=1.1, color=(0.5, 1.0, 0.6))
                self.add_fx("poof", x, z, 0.5, color=(0.7, 1.0, 0.75))
            elif style == "ghost":
                self.add_fx("ring_up", x, z, 0.8, radius=1.2, color=(0.7, 0.8, 1.0))
            elif style == "barrier":
                self.add_fx("ring_up", x, z, 0.8, radius=1.1, color=(1.0, 0.8, 0.4))
                self.add_fx("poof", x, z, 0.4, color=(1.0, 0.85, 0.5))
            elif style == "cleanse":
                self.add_fx("ring_up", x, z, 0.8, radius=1.0, color=(0.85, 0.97, 1.0))
                self.add_fx("poof", x, z, 0.5, color=(0.9, 1.0, 1.0))
            elif style == "exhaust":
                self.add_fx("ring_up", x, z, 0.8, radius=1.1, color=(0.75, 0.5, 1.0))
                self.add_fx("poof", x, z, 0.4, color=(0.7, 0.5, 0.9))
            elif style == "ignite":
                self.add_fx("burst", x, z, 0.6, radius=1.4, color=(1.0, 0.5, 0.25))
                self.add_fx("ring_up", x, z, 0.8, radius=0.9, color=(1.0, 0.6, 0.3))
        elif kind == "relic":
            self.add_fx("ring_up", x, z, 0.8, radius=1.6, color=(0.4, 1.0, 0.5))
        elif kind == "recall":
            self.add_fx("ring_up", x, z, 0.7, radius=1.4, color=(0.4, 0.7, 1.0))
            self.add_fx("ring_up", ev["x2"], ev["z2"], 0.9, radius=1.6, color=(0.4, 0.7, 1.0))
        elif kind == "plate":
            self.add_fx("burst", x, z, 0.6, radius=2.2, color=(1.0, 0.82, 0.35))
        elif kind == "slam":
            col = (1, 0.8, 0.5)
            self.add_fx("burst", x, z, 0.5, radius=rr, color=col)
            self.add_fx("shards", x, z, 0.7, radius=rr, color=col)
        elif kind == "wallhit":
            self.add_fx("burst", x, z, 0.4, radius=1.3, color=(1.0, 0.7, 0.3))
        elif kind.endswith("_hit"):
            style = kind[:-4]
            col = (0.95, 0.97, 1.0) if style == "snowball" else (0.9, 0.95, 1.0)
            self.add_fx("poof", x, z, 0.35, color=col)

    def add_chat(self, parts):
        self.chat_lines.append((time.time(), parts))
        self.chat_lines = self.chat_lines[-40:]

    # ---- 채팅 입력
    def open_chat(self):
        self.chat_open = True
        self.chat_in.value = ""
        self.chat_in.composing = ""
        self.chat_in.focused = True
        self.aiming = None
        self.amove_pending = False
        self.held.clear()
        pygame.key.start_text_input()       # 한글 입력
        pygame.key.set_text_input_rect(self.chat_in.rect)

    def close_chat(self, send=False):
        text = self.chat_in.value.strip()
        if send and text:
            self.app.send({"t": "chat", "text": text})
        self.chat_open = False
        self.chat_in.focused = False
        self.chat_in.composing = ""
        pygame.key.stop_text_input()        # 다시 게임 키가 입력기로 새지 않게

    def handle_chat_event(self, e):
        """채팅 입력 중 키보드 이벤트. 처리했으면 True (게임 조작으로 넘기지 않음)."""
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not self.chat_in.composing:
                self.close_chat(send=True)
                return True
            if e.key == pygame.K_ESCAPE:
                self.close_chat()
                return True
            self.chat_in.handle(e)
            return True
        if e.type in (pygame.KEYUP, pygame.TEXTINPUT, pygame.TEXTEDITING):
            self.chat_in.handle(e)
            return True
        return False

    def entity_pos(self, eid):
        e = self.champs.get(eid) or self.minions.get(eid)
        if e:
            return e.x, e.z
        s = self.structs.get(eid)
        if s:
            return s["x"], s["z"]
        return None

    # ------------------------------------------------------------------ 효과음
    def sfx(self, name, x=None, z=None, vol=1.0):
        """소리 재생. x, z 를 주면 월드의 그 위치에서 나는 소리 (카메라에서 멀면 작게, 아주 멀면 안 들림)."""
        if name:
            world = not name.startswith(("ui_", "vo_"))     # 화면(UI)·아나운서 소리는 그대로, 게임 속 소리는 조금 줄여서
            self.audio.play(name, None if x is None else (x, z), vol, world=world)

    def announce(self, name, prio=1, interrupt=False):
        """아나운서 음성 (assets/sounds/announcer/). 이름은 vo_ 를 뺀 것."""
        self.audio.announce("vo_" + name, prio, interrupt)

    STREAK_ALLY = {3: "spree", 4: "rampage", 5: "unstoppable", 6: "dominating", 7: "legend_arrives"}
    STREAK_ENEMY = {3: "e_spree", 5: "e_unstoppable", 6: "e_dominating", 7: "e_godlike", 8: "e_legendary"}

    def kill_announce(self, ev):
        """킬 한 번에 아나운서 한 마디: 멀티킬 > 연속킬 끊기(마무리) > 선취점 > 연속 처치 > 내가 죽음/아군 사망/내가 처치."""
        mine = self.my_team
        ally = ev["kt"] == mine
        me_dead = ev["v"] == self.my_id
        cands = []
        mk, ks = ev.get("mk", 0), ev.get("ks", 0)
        if mk >= 2:
            base = {2: "double", 3: "triple", 4: "quadra"}.get(mk, "penta")
            cands.append((10 + mk, base if ally else "e_" + base))
        if ev.get("sd") and ally:
            cands.append((8, "shutdown"))
        if ev.get("fb"):
            cands.append((7, "first_blood"))
        if ks >= 3:
            if ally:
                name = self.STREAK_ALLY.get(ks, "legendary_kill" if ks >= 8 else None)
            else:
                name = self.STREAK_ENEMY.get(ks, "e_legendary_kill" if ks >= 9 else None)
            if name:
                cands.append((6, name))
        if me_dead:
            cands.append((5, "you_slain" if ev.get("ke", True) else "you_executed"))
        elif ev["vt"] == mine:
            cands.append((3, "ally_slain"))
        elif ev["k"] == self.my_id:
            cands.append((3, "slain_enemy"))
        if cands:
            prio, name = max(cands)
            self.announce(name, prio)

    # 롤 아나운서 문구 (나무위키 '소환사의 협곡' 아나운서 대사). 연속 처치는 3킬부터 8킬 이상까지
    STREAK_TEXT = {3: "학살 중입니다!", 4: "미쳐 날뛰고 있습니다!", 5: "도저히 막을 수 없습니다!",
                   6: "전장의 지배자!", 7: "전장의 화신!", 8: "전설의 출현!"}
    STREAK_TEXT_ENEMY = {3: "적이 학살 중입니다!", 4: "적이 미쳐 날뛰고 있습니다!", 5: "적을 도저히 막을 수 없습니다!",
                         6: "적이 전장을 지배하고 있습니다!", 7: "적은 전장의 화신입니다!", 8: "적은 전설적입니다!"}
    MULTI_TEXT = {2: "더블 킬!", 3: "트리플 킬!", 4: "쿼드라 킬!", 5: "펜타 킬!"}

    def team_wiped(self, team, victim):
        """이번 처치로 team 의 챔피언이 모두 죽었는가 (마무리)."""
        for cid, info in self.champ_info.items():
            if info["tm"] != team or cid == victim:
                continue
            row = self.board.get(cid)
            if not (row and row[8]):
                return False
        return True

    def kill_banner_text(self, ev):
        """처치 알림 문구 (롤 아나운서와 같게): 멀티킬 > 마무리 > 제압 > 퍼스트 블러드 > 연속 처치 > 기본 문구."""
        mk, ks = ev.get("mk", 0), ev.get("ks", 0)
        ally = ev["kt"] == self.my_team
        if mk >= 2:
            text = self.MULTI_TEXT.get(mk, "펜타 킬!")
            return text if ally else "적 " + text
        if ev.get("ke", True) and self.team_wiped(ev["vt"], ev["v"]):
            return "마무리!"
        if ev.get("sd"):
            return "제압 되었습니다!"
        if ev.get("fb"):
            return "퍼스트 블러드!"
        if ks >= 3:
            table = self.STREAK_TEXT if ally else self.STREAK_TEXT_ENEMY
            return table.get(min(ks, 8))
        if not ev.get("ke", True):
            return "처형 되었습니다!"
        if ev["v"] == self.my_id:
            return "적에게 당했습니다!"
        return "적을 처치했습니다!" if ally else "아군이 당했습니다!"

    @staticmethod
    def ping_kind(start, end):
        """핑 누른 곳(start)에서 놓은 곳(end)까지 끈 방향 -> 핑 종류 (조금만 움직였으면 신호)."""
        dx, dy = end[0] - start[0], end[1] - start[1]
        if math.hypot(dx, dy) < 24:
            return "alert"
        return max(PING_DIRS, key=lambda d: d[1] * dx + d[2] * dy)[0]

    def draw_ping_wheel(self, surf):
        """핑을 누른 채 끌기 시작하면: 누른 자리 둘레에 네 방향 핑 모양과 이름 (끄는 쪽이 크고 밝게). 그냥 누르기만 하면 안 보인다."""
        pd = self.ping_drag
        if not pd:
            return
        cx, cy = pd["pos"]
        mouse = ui.mouse_pos()
        if math.hypot(mouse[0] - cx, mouse[1] - cy) < 24:
            return
        cur = self.ping_kind(pd["pos"], mouse)
        layer = pygame.Surface((240, 240), pygame.SRCALPHA)        # 아주 옅은 바탕 원
        pygame.draw.circle(layer, (10, 14, 24, 55), (120, 120), 114)
        pygame.draw.circle(layer, (150, 165, 200, 70), (120, 120), 114, 2)
        surf.blit(layer, (cx - 120, cy - 120))
        pygame.draw.line(surf, (230, 230, 240), (cx, cy), mouse, 2)
        for kind, dx, dy in PING_DIRS:
            name, col = PINGS[kind]
            on = kind == cur
            p = (cx + dx * 72, cy + dy * 72)
            self.draw_ping_badge(surf, (p[0], p[1] - 8), kind, 1.35 if on else 0.95)
            ui.text(surf, name, (p[0], p[1] + 20), 14 if on else 12, col if on else CHAT_WHITE, anchor="center", bold=on)

    def draw_ping_badge(self, surf, center, kind, size=1.0):
        """핑 표시 (둥근 배지 + 모양): 신호 !, 위험 X, 가는 중 화살표, 도움 요청 +, 실종 ?"""
        _name, col = PINGS.get(kind, PINGS["alert"])
        r = int(15 * size)
        x, y = int(center[0]), int(center[1])
        pygame.draw.circle(surf, (12, 16, 26), (x, y), r + 3)
        pygame.draw.circle(surf, col, (x, y), r)
        dark = (20, 22, 30)
        k = r * 0.5
        if kind == "danger":
            pygame.draw.line(surf, dark, (x - k, y - k), (x + k, y + k), max(2, r // 4))
            pygame.draw.line(surf, dark, (x - k, y + k), (x + k, y - k), max(2, r // 4))
        elif kind == "omw":
            pygame.draw.polygon(surf, dark, [(x - k, y - k), (x + k * 1.1, y), (x - k, y + k)])
        elif kind == "assist":
            pygame.draw.line(surf, dark, (x - k, y), (x + k, y), max(2, r // 4))
            pygame.draw.line(surf, dark, (x, y - k), (x, y + k), max(2, r // 4))
        else:
            ui.text(surf, "?" if kind == "missing" else "!", (x, y), int(r * 1.4), dark, anchor="center", bold=True,
                    shadow=False)

    def draw_pings_2d(self, surf):
        """화면 위 핑 배지 (땅에서 조금 위)와 미니맵 핑."""
        now = time.time()
        self.pings = [p for p in self.pings if now - p["t"] < PING_TIME]
        cam = self.app.renderer.camera
        for p in self.pings:
            age = now - p["t"]
            pop = 1.0 + 0.6 * max(0.0, 1 - age / 0.25)
            sp = cam.world_to_screen(p["x"], 1.6, p["z"])
            if sp:
                self.draw_ping_badge(surf, sp, p["k"], pop)
            mp = self.world_to_minimap(p["x"], p["z"])
            col = PINGS.get(p["k"], PINGS["alert"])[1]
            k = (age % 1.0)
            pygame.draw.circle(surf, col, mp, int(4 + 10 * k), 2)
            pygame.draw.circle(surf, col, mp, 3)

    def draw_kill_banner(self, surf):
        """처치 알림: 왼쪽 처치한 챔피언, 가운데 문구, 오른쪽 처치당한 챔피언 (3초 동안, 끝에 서서히 사라짐)."""
        if not self.kill_banner:
            return False
        t, ev, text = self.kill_banner
        age = time.time() - t
        if age > 3.2:
            self.kill_banner = None
            return False
        alpha = max(0.0, min(1.0, (3.2 - age) / 0.5)) * min(1.0, age / 0.12)
        ally = ev["kt"] == self.my_team
        tw = ui.font(28, True).size(text)[0]
        w = max(420, tw + 200)
        layer = pygame.Surface((w, 76), pygame.SRCALPHA)
        # 처치한 쪽: 챔피언이면 초상화, 포탑·미니언이면 회색 원에 이름 한 글자
        kc = (38, 38)
        kinfo = self.champ_info.get(ev["k"])
        if kinfo:
            draw_round_portrait(layer, kinfo["c"], kc, 30, ui.TEAM_UI.get(ev["kt"], ui.TEXT),
                                color=(gamedata.champion(kinfo["c"]) or {}).get("color", (200, 200, 200)))
        else:
            pygame.draw.circle(layer, (70, 74, 86), kc, 30)
            ui.text(layer, (ev.get("kn") or "?")[:2], kc, 15, ui.TEXT, anchor="center", bold=True)
        pygame.draw.circle(layer, ui.TEAM_UI.get(ev["kt"], ui.TEXT), kc, 31, 3)
        vc = (w - 38, 38)
        vinfo = self.champ_info.get(ev["v"])
        if vinfo:
            draw_round_portrait(layer, vinfo["c"], vc, 30, ui.TEAM_UI.get(ev["vt"], ui.TEXT), False,
                                (gamedata.champion(vinfo["c"]) or {}).get("color", (200, 200, 200)))
        pygame.draw.circle(layer, ui.TEAM_UI.get(ev["vt"], ui.TEXT), vc, 31, 3)
        # 배경 없이 글자만: 어두운 테두리를 둘러 바닥이 밝아도 읽히게
        col = ui.GOLD if ally else (255, 150, 140)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            ui.text(layer, text, (w // 2 + ox, 38 + oy), 28, (10, 8, 14), anchor="center", bold=True, shadow=False)
        ui.text(layer, text, (w // 2, 38), 28, col, anchor="center", bold=True, shadow=False)
        layer.set_alpha(int(255 * alpha))
        surf.blit(layer, (WIDTH // 2 - w // 2, 92))
        return True

    def vo_event(self, ev):
        """서버가 보낸 상황 안내: 포탑·억제기 파괴, 억제기 재생성 예고, 미니언 생성."""
        key, tm = ev.get("key"), ev.get("tm")
        mine = tm == self.my_team
        if key == "minions_30":
            self.announce("minions_30", 4)
        elif key == "minions_spawned":
            self.announce("minions_spawned", 4)
        elif key == "turret_down" and not mine:
            self.announce("turret_destroyed", 6)
        elif key == "inhib_down":
            self.announce("inhib_lost" if mine else "inhib_destroyed", 7)
        elif key == "inhib_soon":
            self.announce("inhib_respawn_soon" if mine else "e_inhib_respawn_soon", 4)

    def sfx_unit(self, uid, name, vol=1.0):
        """유닛 위치에서 나는 소리. 내 챔피언의 소리는 화면 어디를 보고 있든 들린다."""
        if not name:
            return
        if uid == self.my_id:
            self.sfx(name, vol=vol)
            return
        pos = self.entity_pos(uid)
        if pos:
            self.sfx(name, pos[0], pos[1], vol)

    def champ_sounds(self, e, d, now):
        """스냅샷 사이의 상태 변화로 나는 소리: 기본 공격, 사망, 부활, 귀환 시작, 스킬 레벨업, 아이템 구매·판매."""
        old = e.d
        cid = d["i"]
        if old is not None:
            if d["a"] == 2:
                period = 1.0 / max(0.2, (d.get("s") or {}).get("aspd", 1.0))
                if old["a"] != 2 or now - e.last_swing > period * 0.9:
                    e.last_swing = now
                    self.sfx_unit(cid, self.audio.attack_sound(self.champ_info[cid]["c"], "swing"), ATTACK_SFX_VOL)
            if d["dead"] and not old["dead"]:
                self.sfx_unit(cid, "death")
            elif old["dead"] and not d["dead"]:
                self.sfx_unit(cid, "respawn")
            if d.get("rc", 0) > 0 and not old.get("rc", 0):
                self.sfx_unit(cid, "recall_start")
        if cid == self.my_id:
            ranks = d["ab"]
            if self.my_ranks is not None and any(ranks.get(k, 0) > self.my_ranks.get(k, 0) for k in ranks):
                self.sfx("skill_up")
            self.my_ranks = dict(ranks)
            n = len(d["it"])
            if self.my_item_count is not None and n != self.my_item_count:
                self.sfx("ui_buy" if n > self.my_item_count else "ui_sell")
            self.my_item_count = n

    def dmg_sounds(self, ev):
        """피해 이벤트: 내가 맞는 소리, 기본 공격이 맞는 소리 (스킬이 맞는 소리는 효과(fx) 이벤트가 맡는다)."""
        src, dst = ev["s"], ev["d"]
        if dst == self.my_id and ev["v"] >= 4:
            self.sfx("hurt")
        pos = self.entity_pos(dst)
        if not ev.get("b") or pos is None:
            return
        ch = self.champ_info.get(src)
        if ch:
            name, vol = self.audio.attack_sound(ch["c"], "hit"), ATTACK_SFX_VOL
        elif src in self.structs:
            name, vol = "hit_plate", 0.8
        else:
            name, vol = "hit_generic", 0.5 * ATTACK_SFX_VOL
        self.sfx(name, pos[0], pos[1], vol)

    def cast_sound(self, uid, slot):
        info = self.champ_info.get(uid)
        ab = ((gamedata.champion(info["c"]) or {}).get("abilities", {}).get(slot)) if info else None
        if ab:
            self.sfx_unit(uid, self.audio.cast_sound(ab))

    def fx_sounds(self, kind, ev):
        name = self.audio.fx_sound(kind, ev.get("style"))
        if not name:
            return
        if kind == "turret_lock":
            if ev.get("d") == self.my_id:
                self.sfx(name)                              # 포탑에 타게팅되면 본인에게만 경고음
        elif kind == "relic" and ev.get("d") == self.my_id:
            self.sfx(name)
        elif kind in ("recall", "flash", "teleport") and "x2" in ev:
            self.sfx(name, ev["x2"], ev["z2"])          # 도착한 곳에서 소리
        else:
            self.sfx(name, ev["x"], ev["z"])

    def cast_fail_reason(self, slot):
        """지금 이 스킬이 발동하지 않을 이유 (배우지 않음 / 기절·침묵 / 쿨타임 / 마나 부족 / 대상 없음). 쓸 수 있으면 None."""
        me, data = self.me, self.my_data()
        if not me or not data or me["dead"]:
            return None
        ab = data["abilities"][slot]
        rank = me["ab"].get(slot, 0)
        if rank <= 0:
            return "아직 배우지 않은 스킬입니다"
        if "stun" in me["st"]:
            return "기절 상태에서는 스킬을 쓸 수 없습니다"
        if "silence" in me["st"]:
            return "침묵 상태에서는 스킬을 쓸 수 없습니다"
        cd = me["cd"].get(slot, 0)
        if cd > 0:
            return f"아직 재사용 대기 중입니다 ({cd:.1f}초)"
        if me["mp"] < gamedata.rank_value(ab, "mana", rank, 0):
            return "마나가 부족합니다"
        if gamedata.aim_mode(ab) == "enemy" and self.aim_enemy(ab.get("range", 0.0)) is None:
            return "지정한 대상이 없습니다"
        return None

    def cast_blocked(self, slot):
        return self.cast_fail_reason(slot) is not None

    def show_cast_msg(self, text):
        self.cast_msg = (text, time.time() + 1.8)

    def draw_cast_msg(self, surf):
        """스킬 UI 바로 위에 뜨는 안내 문구 (스킬이 발동하지 않았을 때). 박스 없이 글자만."""
        if not self.cast_msg:
            return
        text, until = self.cast_msg
        left = until - time.time()
        if left <= 0:
            self.cast_msg = None
            return
        a = int(255 * min(1.0, left / 0.4))
        fnt = ui.font(18, True)
        pos = (HUD_RECT.centerx, HUD_RECT.top - 58)
        img = fnt.render(text, True, (255, 150, 140))
        shadow = fnt.render(text, True, (20, 8, 10))
        img.set_alpha(a)
        shadow.set_alpha(a)
        r = img.get_rect(center=pos)
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (2, 2)):
            surf.blit(shadow, r.move(ox, oy))
        surf.blit(img, r)

    def add_fx(self, kind, x, z, dur, radius=1.0, color=(1, 1, 1), **extra):
        al = 1.0
        ctx = getattr(self, "fx_ctx", None)
        if ctx:
            color, al = fx_color(color, ctx[0], ctx[1])
        self.fx.append({"kind": kind, "x": x, "z": z, "t": time.time(), "dur": dur, "r": radius, "color": color,
                        "al": al, **extra})

    def sector_mesh(self, angle_deg):
        """+Z 방향을 향하는 반지름 1, 각도 angle_deg 의 부채꼴 (스킬 범위 표시용)."""
        key = max(4, int(round(angle_deg)))
        mesh = self.sectors.get(key)
        if mesh is None:
            b = MeshBuilder()
            half = math.radians(key) / 2
            n = max(6, key // 5)
            up = (0, 1, 0)
            for i in range(n):
                a0 = -half + 2 * half * i / n
                a1 = -half + 2 * half * (i + 1) / n
                b.tri((0, 0, 0), (math.sin(a0), 0, math.cos(a0)), (math.sin(a1), 0, math.cos(a1)),
                      (1, 1, 1), up, up, up)
            mesh = self.sectors[key] = Mesh.from_builder(self.app.renderer, b)
        return mesh

    # ------------------------------------------------------------------ 입력
    def enemy_targetable(self, kind, eid):
        if kind == "champion":
            d = self.champs[eid].d
            return d and not d["dead"] and self.champ_info[eid]["tm"] != self.my_team
        if kind == "minion":
            return self.minions[eid].d[2] != self.my_team
        if kind == "structure":
            st = self.struct_state[eid]
            return self.structs[eid]["tm"] != self.my_team and st[2] and st[3]
        if kind == "anchor":
            return any(row[0] == eid and row[1] != self.my_team for row, _ in self.anchors)
        return False

    def find_hover(self):
        """마우스 아래에 있는 유닛 (kind, id)."""
        cam = self.app.renderer.camera
        mx, my = self.mouse_pos()
        zoom_k = 22.0 / max(1.0, cam.distance)
        best, best_d = None, 1e9
        cands = []
        for eid, e in self.champs.items():
            if e.visible and e.d and not e.d["dead"]:
                cands.append(("champion", eid, e.x, e.z, getattr(e.ca, "pick_h", PICK_H) if e.ca else PICK_H, HOVER_RADIUS["champion"]))
        for eid, e in self.minions.items():
            cands.append(("minion", eid, e.x, e.z, MINION_HEIGHT[e.d[1]], HOVER_RADIUS["minion"]))
        for eid, s in self.structs.items():
            if self.struct_state[eid][2]:
                h = 4.0 if s["k"] == "turret" else 2.0
                cands.append(("structure", eid, s["x"], s["z"], h, 60 if s["k"] != "turret" else 50))
        for row, _ in self.anchors:
            cands.append(("anchor", row[0], row[2], row[3], 1.0, 44))
        for kind, eid, x, z, h, rad in cands:
            # 발밑~머리 위 세로 선분과의 거리로 판정해, 모델 어디를 눌러도 / 조금 빗나가도 잡히게
            a = cam.world_to_screen(x, 0.0, z)
            b = cam.world_to_screen(x, h, z)
            if a is None or b is None:
                continue
            d = _seg_dist(mx, my, a, b) / (rad * zoom_k)   # 판정 반경 대비 거리 (작을수록 가까움)
            if d < 1.0 and d < best_d:
                best, best_d = (kind, eid), d
        return best

    def slot_rects(self):
        rects = [(slot, pygame.Rect(ABILITY_X[slot], 614, 54, 54)) for slot in SLOTS]
        rects += [(slot, pygame.Rect(SPELL_X[slot], 619, 44, 44)) for slot in ("D", "F")]
        return rects

    def find_hover_slot(self):
        """마우스가 올라가 있는 스킬/주문 아이콘 (롤처럼 범위 미리보기용)."""
        mouse = self.mouse_pos()
        return next((slot for slot, rect in self.slot_rects() if rect.collidepoint(mouse)), None)

    def right_click(self, repeat=False, attack_move=False):
        """우클릭(또는 A + 좌클릭): 적 위면 공격, 아니면 이동(공격 이동)."""
        if self.my_id is None or not self.me or self.me["dead"]:
            return
        hov = self.hover
        if hov and self.enemy_targetable(*hov):
            if not repeat:
                self.send_cmd(c="attack", id=hov[1])
                self.move_dest = None
            return
        x, z = self.mouse_ground()
        self.issue_move(x, z, cmd="amove" if attack_move else "move", marker=not repeat)

    def issue_move(self, x, z, cmd="move", marker=True):
        """이동 명령 + 바닥 이동 지점 표시."""
        if self.my_id is None or not self.me or self.me["dead"]:
            return
        x, z = mapdata.clamp_to_map(x, z, 0.5)
        self.send_cmd(c=cmd, x=round(x, 2), z=round(z, 2))
        self.move_dest = (x, z)
        if marker:
            self.click_marker = (x, z, time.time())

    def aim_of(self, slot):
        """슬롯의 스킬 조준 방식 (line/cone/ground/teleport/circle/enemy/self)."""
        data = self.my_data()
        if not data or slot not in SLOTS:
            return "line"
        return gamedata.aim_mode(data["abilities"][slot])

    def aim_target(self, slot):
        """스킬을 쓸 지점. 먼 거리 순간이동 스킬은 미니맵 위에서도 지정할 수 있다."""
        mouse = self.mouse_pos()
        if self.aim_of(slot) == "teleport" and MINIMAP.collidepoint(mouse):
            return self.minimap_to_world(*mouse)
        return self.mouse_ground()

    def cast_slot(self, slot):
        why = self.cast_fail_reason(slot)
        if why:
            self.sfx("cast_fail")
            self.show_cast_msg(why)
        x, z = self.aim_target(slot)
        self.send_cmd(c="cast", slot=slot, x=round(x, 2), z=round(z, 2))

    def handle_event(self, e):
        if self.app.settings_ui.handle_event(e):
            return
        if self.chat_open and self.handle_chat_event(e):
            return
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.open_chat()
            return
        if e.type == pygame.KEYDOWN:
            cheat = {pygame.K_F9: "cheat_lv", pygame.K_F8: "cheat_cd", pygame.K_F7: "cheat_mana", pygame.K_F6: "cheat_hp"}.get(e.key)
            if cheat:                                             # 테스트용 치트: F9 레벨+1, F8 쿨타임 초기화, F7 마나 최대, F6 체력 최대
                self.send_cmd(c=cheat)
                return
            if e.key == pygame.K_ESCAPE:
                # ESC: 열린 것(상점/조준)을 먼저 닫고, 없으면 설정 창
                if self.shop_open or self.aiming:
                    self.shop_open = False
                    self.aiming = None
                else:
                    self.open_settings()
                return
            mods = pygame.key.get_mods()
            act = self.binds.action(e)
            if act:
                self.held.add(act)
            if act in SLOTS:
                slot = act
                if mods & pygame.KMOD_CTRL:
                    self.send_cmd(c="level", slot=slot)
                    return
                data = self.my_data()
                if data and gamedata.is_instant(data["abilities"][slot]):
                    self.cast_slot(slot)
                else:
                    self.aiming = slot
                return
            if act in ("D", "F"):
                x, z = self.mouse_ground()
                self.send_cmd(c="spell", slot=act, x=round(x, 2), z=round(z, 2))
            elif act == "stop":
                self.send_cmd(c="stop")
                self.move_dest = None
            elif act == "recall":
                self.send_cmd(c="recall")
                self.move_dest = None
            elif act == "attack_move":
                self.amove_pending = True
            elif act == "shop":
                self.shop_open = not self.shop_open
            elif act == "score":
                self.show_score = True
            elif act == "cam_lock":
                self.cam_locked = not self.cam_locked
        elif e.type == pygame.KEYUP:
            act = self.binds.action(e)
            self.held.discard(act)
            if act == "score":
                self.show_score = False
            elif act == "attack_move":
                self.amove_pending = False      # 누르고 있는 동안만 공격 범위 표시
            elif self.aiming and act == self.aiming:
                self.cast_slot(self.aiming)
                self.aiming = None
        elif e.type == pygame.MOUSEBUTTONDOWN:
            if e.button == 1 and ("ping" in self.held or pygame.key.get_mods() & pygame.KMOD_ALT):
                # 핑: 화면(또는 미니맵)을 누른 자리에 찍는다. 놓을 때 끈 방향으로 종류가 정해진다
                if MINIMAP.collidepoint(e.pos):
                    px, pz = self.minimap_to_world(*e.pos)
                elif HUD_RECT.collidepoint(e.pos):
                    return
                else:
                    px, pz = self.mouse_ground()
                self.ping_drag = {"pos": e.pos, "x": px, "z": pz}
                self.aiming = None
                return
            if e.button == 1:
                if not self.aiming:                         # 인벤토리 아이템을 끌어서 자리 바꾸기
                    hit = next((i for i, rect in self.hud_inv_rects if rect.collidepoint(e.pos)), None)
                    if hit is not None:
                        self.inv_drag = hit
                        return
                if self.aiming and self.aim_of(self.aiming) == "teleport" and MINIMAP.collidepoint(e.pos):
                    self.cast_slot(self.aiming)         # 미니맵을 눌러 먼 곳으로 시전
                    self.aiming = None
                    return
                if self.click_ui(e.pos):
                    return
                if self.aiming:
                    self.cast_slot(self.aiming)
                    self.aiming = None
                elif self.amove_pending:
                    # A + 좌클릭: 적을 누르면 그 적을 공격, 땅을 누르면 공격 이동
                    self.right_click(attack_move=True)
            elif e.button == 3:
                self.aiming = None
                if MINIMAP.collidepoint(e.pos):
                    x, z = self.minimap_to_world(*e.pos)
                    self.issue_move(x, z)
                    self.rmb_down = True
                    self.rmb_minimap = True
                    self.rmb_repeat = 0.15
                    return
                if self.shop_open and self.shop_panel().collidepoint(e.pos):
                    self.shop_right_click(e.pos)
                    return
                if self.shop_open:
                    hit = next((i for i, rect in self.hud_inv_rects if rect.collidepoint(e.pos)), None)
                    if hit is not None:
                        self.send_cmd(c="sell", slot=hit)
                        return
                if HUD_RECT.collidepoint(e.pos):
                    return
                self.rmb_down = True
                self.rmb_minimap = False
                self.rmb_repeat = 0.15
                self.right_click()
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 3:
            self.rmb_down = False
            self.rmb_minimap = False
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.ping_drag:
            pd, self.ping_drag = self.ping_drag, None
            kind = self.ping_kind(pd["pos"], e.pos)
            self.send_cmd(c="ping", x=round(pd["x"], 2), z=round(pd["z"], 2), k=kind)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.minimap_drag = False
            if self.inv_drag is not None:
                src, self.inv_drag = self.inv_drag, None
                dst = next((i for i, rect in self.hud_slot_rects if rect.collidepoint(e.pos)), None)
                if dst is not None and dst != src:
                    self.audio.play("ui_click")
                    self.send_cmd(c="swap", a=src, b=dst)
        elif e.type == pygame.MOUSEMOTION and self.minimap_drag:
            self.minimap_camera(e.pos)
        elif e.type == pygame.MOUSEWHEEL:
            self.zoom = max(16.0, min(ZOOM_MAX, self.zoom - e.y * 2.0))     # 처음 화면보다 넓게는 볼 수 없다

    # ---- 설정 (ESC): 시작 화면·로비와 같은 설정 창 (app.settings_ui)
    @property
    def settings_open(self):
        return self.app.settings_ui.open

    def open_settings(self):
        self.app.settings_ui.show()
        self.aiming = None
        self.amove_pending = False
        self.rmb_down = False
        self.held.clear()

    def click_ui(self, pos):
        for slot, rect in self.levelup_rects:
            if rect.collidepoint(pos):
                self.send_cmd(c="level", slot=slot)
                return True
        if self.shop_open:
            if self.shop_panel().collidepoint(pos):
                # 롤처럼 좌클릭은 고르기만 하고, 오른쪽의 구매 버튼으로 산다 (우클릭은 바로 구매)
                if self.shop_buy_rect and self.shop_buy_rect.collidepoint(pos):
                    self.buy_item(self.shop_sel)
                    return True
                if self.shop_undo_rect and self.shop_undo_rect.collidepoint(pos):
                    if self.me and self.me.get("ud") and self.me.get("shop"):
                        self.audio.play("ui_click")
                        self.send_cmd(c="undo")
                    else:
                        self.audio.play("ui_error")
                    return True
                for iid, rect, nav in self.shop_rects:
                    if rect.collidepoint(pos):
                        if iid != self.shop_sel:
                            self.audio.play("ui_select")
                        self.shop_sel = iid
                        self.shop_sel_pos = None if nav else rect.topleft     # 같은 재료가 여러 칸이면 누른 칸만 표시
                        if nav:                     # 트리 안의 재료를 누르면 트리는 그대로 두고 고르기만 한다
                            self.shop_view = iid
                        break
                return True
        me = self.me
        if self.gold_rect and self.gold_rect.collidepoint(pos) and me:
            self.shop_open = not self.shop_open
            return True
        if MINIMAP.collidepoint(pos):
            self.minimap_drag = True
            self.minimap_camera(pos)
            return True
        if HUD_RECT.collidepoint(pos):
            return True
        return False

    def minimap_camera(self, pos):
        """미니맵 위치로 카메라 이동 (미니맵 밖으로 끌어도 가장자리까지 따라감)."""
        px = max(MINIMAP.left, min(MINIMAP.right - 1, pos[0]))
        py = max(MINIMAP.top, min(MINIMAP.bottom - 1, pos[1]))
        x, z = self.minimap_to_world(px, py)
        cam = self.app.renderer.camera
        cam.tx, cam.tz = x, z
        self.cam_locked = False

    def shop_right_click(self, pos):
        for iid, rect, nav in self.shop_rects:
            if rect.collidepoint(pos):
                self.shop_sel = iid
                self.shop_sel_pos = None if nav else rect.topleft
                if nav:
                    self.shop_view = iid
                self.buy_item(iid)
                return

    def buy_item(self, iid):
        """상점 구매 요청. 신발을 이미 가졌거나 인벤토리가 가득 차면 이유를 알려 주고 보내지 않는다.
        돈이 모자라면 서버가 살 수 있는 재료부터 산다 (그것도 없으면 보내지 않는다)."""
        me = self.me
        if me:
            ok, _used, _price, why = gamedata.can_buy(list(me["it"]), iid, INVENTORY_SLOTS)
            if not ok:
                self.audio.play("ui_error")
                self.app.toast(why, 2.0)
                return
            if not gamedata.purchase_plan(list(me["it"]), iid, me["g"], INVENTORY_SLOTS):
                self.audio.play("ui_error")
                return
        self.send_cmd(c="buy", item=iid)

    # ------------------------------------------------------------------ 갱신
    def target_height(self, uid):
        """포탑이 노리는 대상의 몸 한가운데 높이 (챔피언 / 미니언)."""
        return CHAMP_SCALE * 1.0 if uid in self.champs else 0.5

    def turret_shot_height(self, team, x, z):
        """포탑 포탄의 높이: 쏜 포탑(같은 팀, 가장 가까운) 꼭대기 수정에서 그 포탑이 노리는 대상까지 거리에 비례해 내려간다."""
        best, bd = None, mapdata.TURRET_RANGE + 3.0
        for sid, s in self.structs.items():
            if s["k"] != "turret" or s["tm"] != team or not self.struct_state[sid][2]:
                continue
            d = math.hypot(x - s["x"], z - s["z"])
            if d < bd:
                best, bd = sid, d
        if best is None:
            return 1.0
        s = self.structs[best]
        tid = self.struct_state[best][4]
        tgt = self.champs.get(tid) or self.minions.get(tid)
        if tgt is None:
            return max(1.0, TURRET_TOP - bd * 0.4)
        total = math.hypot(tgt.x - s["x"], tgt.z - s["z"]) or 1.0
        k = max(0.0, min(1.0, bd / total))
        return TURRET_TOP + (self.target_height(tid) - TURRET_TOP) * k

    def on_screen(self, x, z, margin=260):
        """(x, z) 가 지금 화면 안(가장자리에서 margin 픽셀 바깥까지 포함)에 보이는가. 긴 몸(용·이무기)을 생각해 넉넉히 본다."""
        p = self.app.renderer.camera.world_to_screen(x, 0.8, z)
        return p is not None and -margin <= p[0] <= WIDTH + margin and -margin <= p[1] <= HEIGHT + margin

    def update(self, dt):
        self.audio.tick_vo()
        for cid, e in self.champs.items():
            e.step(dt)
            st = e.d["st"] if e.d else ()
            want = (1.1 if not e.ca else 2.0) if "air" in st else 0.0
            e.lift += (want - e.lift) * min(1.0, dt * 12.0)
            if e.d and e.ca is None:
                e.ca = self.app.models.new_champ_anim(self.champ_info[cid]["c"]) or False
            if e.ca:
                # 화면 안의 챔피언만 매 프레임 움직임을 계산하고, 화면 밖·시야 밖은 0.1초마다 몰아서 계산한다 (리그 계산이 무겁다)
                e.onscreen = e.visible and self.on_screen(e.x, e.z)
                e.ca_dt += dt
                if e.onscreen or e.ca_dt >= 0.1:
                    e.ca.update(e.ca_dt, e.d, e)
                    e.ca_dt = 0.0
                if self.winner is not None and self.champ_info[cid]["tm"] == self.winner and not e.d["dead"]:
                    e.ca.win()
        for e in self.minions.values():
            e.step(dt)
        now_ = time.time()
        for sid, (tid, until) in list(self.slam_follow.items()):
            ch, tgt = self.champs.get(sid), self.champs.get(tid)
            if now_ > until or not ch or not ch.ca or not tgt or not tgt.visible:
                del self.slam_follow[sid]
            elif hasattr(ch.ca, "aim_slam"):
                ch.ca.aim_slam(tgt.x, tgt.z)
        self.vis_timer -= dt
        if self.vis_timer <= 0:
            self.vis_timer = 0.1
            self.update_vision()
        self.hover = self.find_hover()
        self.hover_slot = self.find_hover_slot()

        if self.rmb_down:
            self.rmb_repeat -= dt
            if self.rmb_repeat <= 0:
                self.rmb_repeat = 0.15
                if self.rmb_minimap:
                    mp = ui.mouse_pos()
                    if MINIMAP.collidepoint(mp):
                        self.issue_move(*self.minimap_to_world(*mp), marker=False)
                else:
                    self.right_click(repeat=True)
        if self.minimap_drag:
            if pygame.mouse.get_pressed()[0]:
                self.minimap_camera(ui.mouse_pos())
            else:
                self.minimap_drag = False

        # 목적지 도착 / 사망 시 이동 표시 제거
        me = self.champs.get(self.my_id)
        if self.move_dest and (not me or not me.d or me.d["dead"]
                               or math.hypot(me.x - self.move_dest[0], me.z - self.move_dest[1]) < 0.6):
            self.move_dest = None

        cam = self.app.renderer.camera
        cam.distance += (self.zoom - cam.distance) * min(1.0, dt * 10)
        keys = pygame.key.get_pressed()
        me = self.champs.get(self.my_id)
        if me and (self.cam_locked or "cam_center" in self.held):
            cam.tx += (me.x - cam.tx) * min(1.0, dt * 10)
            cam.tz += (me.z - cam.tz) * min(1.0, dt * 10)
        elif not self.minimap_drag and not self.settings_open:
            # 롤처럼 커서를 화면 끝에 대면 그 방향으로 카메라 이동 (방향키도 가능)
            ex, ey = self.app.mouse_edge()
            if keys[pygame.K_LEFT]:
                ex = -1
            if keys[pygame.K_RIGHT]:
                ex = 1
            if keys[pygame.K_UP]:
                ey = -1
            if keys[pygame.K_DOWN]:
                ey = 1
            speed = 32.0 * dt * (cam.distance / 22.0)
            cam.tx = max(-58, min(58, cam.tx + ex * speed))
            cam.tz = max(-15, min(15, cam.tz + ey * speed))

        self.audio.listener = (cam.tx, cam.tz)
        d = me.d if me else None
        if d and not d["dead"] and d["a"] == 1 and "air" not in d["st"]:
            self.foot_t -= dt
            if self.foot_t <= 0:
                self.foot_t = 0.4 / min(1.6, max(0.8, d["s"]["ms"] / 345))
                self.sfx("footstep")
        else:
            self.foot_t = 0.0
        if self.shop_open != self.shop_was_open:
            self.shop_was_open = self.shop_open
            self.sfx("ui_open" if self.shop_open else "ui_close")
        now = time.time()
        self.fx = [f for f in self.fx if now - f["t"] < f["dur"]]
        self.floaters = [f for f in self.floaters if now - f["t"] < f["dur"]]
        self.announces = [a for a in self.announces if now - a[0] < 3.0][-3:]

    # ------------------------------------------------------------------ 3D
    def render3d(self):
        r = self.app.renderer
        m = self.app.models
        cam = r.camera
        r.begin_3d(cam)
        r.draw(m.map, model_matrix())
        now = time.time()
        t = self.app.time
        self.vfx.tick(now)

        # 우물 범위 표시
        for team in (BLUE, RED):
            fx, fz = mapdata.fountain_pos(team)
            col = (0.3, 0.6, 1.0) if self.view_team(team) == BLUE else (1.0, 0.35, 0.3)
            r.draw_transparent(m.ring_thin, model_matrix(fx, 0.06, fz, scale=7.5), (*col, 0.5))

        hov_id = self.hover[1] if self.hover else None

        # 부쉬: 우리 팀이 안을 보고 있는 부쉬(아군 챔피언·미니언·새끼 거미·고치가 들어가 있음)는 반투명
        seen_bushes = self.seen_bushes()
        for i, (bx, bz, rx, rz) in enumerate(mapdata.BUSHES):
            if i in seen_bushes:
                r.draw_transparent(self.bush_meshes[i], model_matrix(bx, 0, bz), (1, 1, 1, 0.45), unlit=0.0)
            else:
                r.draw(self.bush_meshes[i], model_matrix(bx, 0, bz))

        # 구조물
        for sid, s in self.structs.items():
            st = self.struct_state[sid]
            alive = st[2]
            meshes = m.team_meshes[self.view_team(s["tm"])]
            emis = (0.18, 0.18, 0.18) if sid == hov_id else (0, 0, 0)
            if s["k"] == "turret":
                mesh = meshes["turret"] if alive else m.rubble
            elif s["k"] == "inhibitor":
                mesh = meshes["inhibitor"] if alive else meshes["inhibitor_dead"]
            else:
                mesh = meshes["nexus"] if alive else meshes["nexus_dead"]
            r.draw(mesh, model_matrix(s["x"], 0, s["z"], rot_y=0.0), emissive=emis)
            if alive and s["k"] == "turret":
                # 포탑 사거리: 내 챔피언이 가까이 있으면 표시 (적 포탑은 빨강, 아군 포탑은 파랑)
                me = self.champs.get(self.my_id)
                if me and me.d and not me.d["dead"] and math.hypot(me.x - s["x"], me.z - s["z"]) < mapdata.TURRET_RANGE + 4:
                    # 서버는 "사거리 + 대상 반지름" 안이면 공격한다. 선의 안쪽 가장자리를 그 거리에 맞추고
                    # 두께는 바깥쪽으로 그려서, 선을 밟고 있어도 (선 위는 이미 사거리 밖이라) 공격받지 않게 한다.
                    inner = mapdata.TURRET_RANGE + ((self.my_data() or {}).get("stats", {}).get("radius", 0.55))
                    ring_col = (1.0, 0.3, 0.25, 0.7) if s["tm"] != self.my_team else (0.35, 0.65, 1.0, 0.55)
                    r.draw_transparent(m.ring_thin, model_matrix(s["x"], 0.05, s["z"], scale=inner / (1.0 - RING_THIN)), ring_col)
            if alive and s["k"] == "turret" and st[4]:
                # 포탑이 노리는 대상: 포탑 꼭대기에서 대상까지 가는 레이저 선 (적 포탑 빨강 · 아군 포탑 파랑)
                tgt = self.champs.get(st[4]) or self.minions.get(st[4])
                if tgt is not None and getattr(tgt, "visible", True) and math.hypot(tgt.x - s["x"], tgt.z - s["z"]) < mapdata.TURRET_RANGE + 3:
                    ty = self.target_height(st[4])
                    dx, dy, dz = tgt.x - s["x"], ty - TURRET_TOP, tgt.z - s["z"]
                    horiz = math.hypot(dx, dz)
                    length = math.sqrt(horiz * horiz + dy * dy)
                    lcol = (1.0, 0.18, 0.15) if s["tm"] != self.my_team else (0.25, 0.55, 1.0)
                    if length > 0.1:
                        flick = 0.75 + 0.2 * math.sin(t * 20)
                        r.draw_transparent(self.beam, beam_matrix(s["x"], TURRET_TOP, s["z"], tgt.x, ty, tgt.z, 0.025),
                                           (*lcol, flick), unlit=1.0)
            if alive and not st[3] and s["tm"] != self.my_team:
                # 무적 구조물: 보호막
                r.draw_transparent(m.orb, model_matrix(s["x"], 1.5, s["z"], scale=s["r"] + 0.7),
                                   (0.6, 0.7, 1.0, 0.08), additive=True)

        # 유물
        for rid, x, z, active in self.relics:
            # 생성 위치 바닥 표시 (없을 때도 보임)
            r.draw_transparent(m.disc, model_matrix(x, 0.035, z, scale=0.2), (0.6, 0.6, 0.62, 0.35))
            r.draw_transparent(m.ring_thin, model_matrix(x, 0.04, z, scale=0.2), (0.7, 0.7, 0.72, 0.7))
            if active:
                r.draw_transparent(m.shadow, model_matrix(x, 0.03, z, scale=0.4), (0, 0, 0, 0.3))
                r.draw(m.relic, model_matrix(x, 0.9 + math.sin(t * 2 + rid) * 0.15, z, rot_y=t * 1.5),
                       emissive=(0.1, 0.45, 0.15))
                r.draw_transparent(m.ring, model_matrix(x, 0.05, z, scale=0.5), (0.4, 1.0, 0.5, 0.6), additive=True)

        # 미니언
        for mid, e in self.minions.items():
            row = e.d
            code, team, anim = row[1], row[2], row[8]
            key = MINION_KEYS[code]
            bob = abs(math.sin(t * 9 + mid)) * 0.08 if anim == 1 else 0.0
            if code == 4:                                          # 새끼 거미: 통통 튀지 않고 다리를 움직이며 달린다
                bob = 0.0
                if anim == 1:
                    key = "minion_spiderling_walk"
            rot = facing_to_rot(e.f)
            rad = MINION_RADIUS[code]
            r.draw_transparent(m.shadow, model_matrix(e.x, 0.03, e.z, scale=rad * 1.1), (0, 0, 0, 0.3))
            if code == 4:                                          # 새끼 거미는 작아서 발밑 팀 색 고리로 편을 구분
                r.draw_transparent(m.ring, model_matrix(e.x, 0.05, e.z, scale=0.5),
                                   (0.3, 0.6, 1.0, 0.8) if team == self.my_team else (1.0, 0.3, 0.3, 0.8))
            emis = (0.2, 0.2, 0.2) if mid == hov_id else (0, 0, 0)
            mesh_ = m.team_meshes[self.view_team(team)][key]
            if isinstance(mesh_, list):                        # 새끼 거미: 거미 여왕과 같은 걸음의 한 주기를 돌려 가며 그린다
                mesh_ = mesh_[int(((t + mid * 0.137) % BABY_PERIOD) / BABY_PERIOD * len(mesh_)) % len(mesh_)]
            tilt, hop = 0.0, 0.0
            if code == 4 and now - e.swing_t < 0.4:                # 새끼 거미 공격: 앞을 들었다가 내리찍는다 (메인 거미 평타처럼)
                k = (now - e.swing_t) / 0.4
                tilt = BABY_ATTACK_TILT * math.sin(math.pi * k) * (1.0 if k < 0.55 else 0.6)
                hop = 0.05 * math.sin(math.pi * k)
            r.draw(mesh_, model_matrix(e.x, bob + hop, e.z, rot_y=rot, rot_x=tilt), emissive=emis)
            weapon = m.minion_weapons[team].get(key)
            if weapon:
                # 무기는 손을 축으로 따로 그려, 공격할 때 뒤로 젖혔다가 앞으로 휘두른다
                wmesh, (px, py, pz) = weapon
                c, s_ = math.cos(rot), math.sin(rot)
                wx, wz = c * px + s_ * pz, -s_ * px + c * pz
                r.draw(wmesh, model_matrix(e.x + wx, bob + py, e.z + wz, rot_y=rot,
                                           rot_x=self.swing_angle(now - e.swing_t)), emissive=emis)

        # 챔피언
        for cid, e in self.champs.items():
            d = e.d
            if not d or not e.visible or not e.onscreen:
                continue
            info = self.champ_info[cid]
            mesh = m.champion(info["c"])
            ca = e.ca or None
            if d["dead"]:
                # 죽은 뒤 잠깐 쓰러진 모습을 보여 주고 서서히 사라진다
                if ca and ca.corpse_visible:
                    ca.draw(r, (1.0, 1.0, 1.0, ca.alpha))
                continue
            st = d["st"]
            self.vfx.status(st, e.x, e.z, e.lift, info["tm"] == self.my_team, d.get("sh", 0) > 0)
            if cid == self.my_id:
                ring_col = (0.6, 1.0, 0.3, 0.9)
            elif info["tm"] == self.my_team:
                ring_col = (0.3, 0.6, 1.0, 0.85)
            else:
                ring_col = (1.0, 0.3, 0.3, 0.85)
            lift = e.lift
            big = 1.6 if ca else 1.0                           # 거미 같은 큰 몸은 그림자도 크게
            if big > 1:
                lift = ca.lift * SC_RIG + e.lift               # 점프 중 높이는 리그가 직접 계산한다 (+ 에어본)
            r.draw_transparent(m.shadow, model_matrix(e.x, 0.03, e.z, scale=0.65 * big * CHAMP_SCALE),
                               (0, 0, 0, 0.35 / (1 + lift)))
            r.draw_transparent(m.ring, model_matrix(e.x, 0.05, e.z, scale=0.85), ring_col)
            anim = d["a"]
            bob = abs(math.sin(t * 10 + cid)) * 0.06 if anim == 1 else 0.0
            tilt = 0.08 if anim == 1 else 0.0
            if ca:
                bob = tilt = 0.0           # 몸 움직임은 리그가 맡는다
            tint = [1.0, 1.0, 1.0, 1.0]
            emis = [0.0, 0.0, 0.0]
            if "slow" in st:
                tint = [0.75, 0.85, 1.15, 1.0]
            if "silence" in st:
                tint = [tint[0] * 0.85, tint[1] * 0.7, tint[2] * 1.1, 1.0]
            if "root" in st:
                tint = [tint[0] * 0.8, tint[1] * 0.95, tint[2] * 0.7, 1.0]
            if "ghost" in st:
                tint = [0.65, 1.0, 0.9, 0.55]
            if "buff" in st:
                emis = [0.05, 0.12, 0.25]
            if "air" in st and not ca:
                tilt = 0.35 * math.sin(t * 9)
            if cid == hov_id:
                emis = [v + 0.15 for v in emis]
            if ca:
                r.y_offset = e.lift + (0.12 * math.sin(t * 6 + cid) * min(1.0, e.lift) if e.lift > 0.05 else 0.0)
                ca.draw(r, tuple(tint), emis)
                r.y_offset = 0.0
            else:
                r.draw(mesh, model_matrix(e.x, bob + lift, e.z, rot_y=facing_to_rot(e.f), rot_x=tilt, scale=CHAMP_SCALE),
                       tint=tuple(tint), emissive=emis)
            head = 2.15 * CHAMP_SCALE + lift
            mid = 1.0 * CHAMP_SCALE + lift                      # 몸 한가운데 높이 (보호막·강화 구)
            if "stun" in st:
                for k in range(3):
                    a = t * 5 + k * math.tau / 3
                    r.draw(m.orb, model_matrix(e.x + math.cos(a) * 0.4, head, e.z + math.sin(a) * 0.4, scale=0.08),
                           tint=(1, 0.9, 0.3, 1), unlit=1.0)
            if "silence" in st:
                r.draw_transparent(m.ring, model_matrix(e.x, head + 0.05, e.z, scale=0.38, rot_y=t * 3),
                                   (0.75, 0.5, 1.0, 0.95), additive=True)
                r.draw_transparent(m.ring, model_matrix(e.x, head + 0.12, e.z, scale=0.25, rot_y=-t * 3),
                                   (0.9, 0.7, 1.0, 0.8), additive=True)
            if "root" in st:
                r.draw_transparent(m.ring, model_matrix(e.x, 0.07, e.z, scale=0.6), (0.5, 0.75, 0.3, 0.9))
                for k in range(6):
                    a = k / 6 * math.tau + 0.3
                    r.draw(m.relic, model_matrix(e.x + math.cos(a) * 0.5, 0.25, e.z + math.sin(a) * 0.5, scale=0.55,
                                                 rot_y=a), tint=(0.5, 0.75, 0.3, 1))
            if d.get("sh", 0) > 0:
                sc, col = (0.7, 0.9, 1.0, 0.17), 0.9
                sc = (*fx_color(sc[:3], info["tm"] == self.my_team, False)[0], sc[3])      # 아군 파랑 / 적 빨강
                r.draw_transparent(m.orb, model_matrix(e.x, mid, e.z, scale=col * CHAMP_SCALE), sc, additive=True)
            if "immune" in st:
                r.draw_transparent(m.orb, model_matrix(e.x, mid, e.z, scale=0.9 * CHAMP_SCALE), (1.0, 1.0, 1.0, 0.13),
                                   additive=True)
            if d.get("rc", 0) > 0:
                # 귀환 중: 발밑 원 + 위로 올라가는 고리
                k = 1 - d["rc"] / max(0.1, d.get("rct", RECALL_TIME))
                r.draw_transparent(m.disc, model_matrix(e.x, 0.06, e.z, scale=1.1), (0.35, 0.6, 1.0, 0.25 + 0.2 * k),
                                   additive=True)
                for j in range(2):
                    ph = (t * 0.8 + j * 0.5) % 1.0
                    r.draw_transparent(m.ring, model_matrix(e.x, 0.1 + ph * 2.2, e.z, scale=0.9),
                                       (0.45, 0.7, 1.0, 0.8 * (1 - ph)), additive=True)

        # 핑: 바닥에서 퍼지는 고리 + 빛기둥
        now_p = time.time()
        for pg in self.pings:
            age = now_p - pg["t"]
            if age >= PING_TIME:
                continue
            col = tuple(c / 255 for c in PINGS.get(pg["k"], PINGS["alert"])[1])
            fade = max(0.0, 1 - age / PING_TIME)
            for j in range(2):
                ph = ((age * 1.4) + j * 0.5) % 1.0
                r.draw_transparent(m.ring, model_matrix(pg["x"], 0.08, pg["z"], scale=0.6 + ph * 1.6),
                                   (*col, 0.9 * (1 - ph) * fade), additive=True)
            r.draw_transparent(self.pillar, model_matrix(pg["x"], 0.0, pg["z"], sx=0.12, sy=1.4, sz=0.12), (*col, 0.5 * fade),
                               additive=True)

        # 투사체
        for p in self.projs.values():
            age = min(0.15, now - p["t"])
            x, z = p["x"] + p["vx"] * age, p["z"] + p["vz"] * age
            if p["style"] == "tornado":                           # 용의 회오리: 겹겹이 도는 반투명 원뿔대
                self.draw_tornado(r, m, x, z, t)
                self.vfx.projectile(p, x, 1.0, z, p["team"] == self.my_team)
                continue
            if p["style"] == "scythe":                            # 사신의 낫: 수평으로 빙글빙글 돌며 날아간다
                ally = p["team"] == self.my_team
                r.draw(m.proj["scythe"], model_matrix(x, 1.15, z, rot_y=-t * 17.0),
                       tint=(0.85, 0.92, 1.0, 1) if ally else (1.0, 0.85, 0.85, 1),
                       emissive=(0.05, 0.12, 0.3) if ally else (0.3, 0.06, 0.08))
                self.vfx.projectile(p, x, 1.15, z, ally)
                continue
            mesh = m.proj.get(p["style"], m.proj["minion_bolt"])
            y, emis = PROJ_LOOK.get(p["style"], (1.1, None))
            if p["style"].startswith("turret_shot"):
                y = self.turret_shot_height(p["team"], x, z)      # 꼭대기 수정에서 나와 대상 쪽으로 내려간다
            emis = emis or (0, 0, 0)
            rot = math.atan2(p["dx"], p["dz"])
            tint = (1, 1, 1, 1)
            if p["style"] not in ("minion_bolt", "cannon_ball", "turret_shot", "turret_shot_2", "turret_shot_3", "fire_bolt"):
                # 챔피언 투사체: 아군은 푸른 빛, 적은 붉은 빛을 더한다
                if p["team"] == self.my_team:
                    tint, emis = (0.8, 0.9, 1.0, 1), tuple(min(1.0, e + g) for e, g in zip(emis, (0.04, 0.16, 0.42)))
                else:
                    tint, emis = (1.0, 0.8, 0.78, 1), tuple(min(1.0, e + g) for e, g in zip(emis, (0.42, 0.07, 0.05)))
            if p["style"] in ("minion_bolt", "cannon_ball", "turret_shot", "turret_shot_2", "turret_shot_3"):
                # 미니언·포탑 투사체는 팀 색 (블루 / 레드)
                blue = self.view_team(p["team"]) == BLUE
                tint = (0.4, 0.65, 1.0, 1) if blue else (1.0, 0.4, 0.35, 1)
                emis = (0.1, 0.2, 0.45) if blue else (0.45, 0.12, 0.1)
            r.draw(mesh, model_matrix(x, y, z, rot_y=rot, scale=PROJ_SCALE.get(p["style"], 1.3)), tint=tint, emissive=emis)
            if p["style"] not in ("minion_bolt", "cannon_ball"):       # 미니언 투사체는 꼬리·빛 없이 구만
                self.vfx.projectile(p, x, y, z, p["team"] == self.my_team)

        # 장판 (스킬 예고 등)
        for row, recv in self.ground_effects:
            eid, style, team, x, z, radius, remaining = row
            left = remaining - (now - recv)
            total = max(0.05, self.ef_total.get(eid, 0.8))
            prog = 1 - max(0.0, left) / total
            pulse = 0.25 + 0.15 * math.sin(t * 12)
            col, al = fx_color((0.75, 0.9, 1.0) if team == self.my_team else (1.0, 0.45, 0.35), team == self.my_team, False)
            r.draw_transparent(m.disc, model_matrix(x, 0.06, z, scale=radius), (*col, pulse * al))
            r.draw_transparent(m.ring, model_matrix(x, 0.07, z, scale=radius), (*col, 0.9 * al))
            if left > 0:
                r.draw_transparent(m.disc, model_matrix(x, 0.08, z, scale=radius * max(0.0, prog)), (*col, 0.35 * al))

        # 오래 남는 장판: 독 거미줄 / 독 웅덩이 / 불길 웅덩이
        for row, recv in self.zones:
            zid, style, team, x, z, radius, remaining, total = row
            left = remaining - (now - recv)
            if left <= 0:
                continue
            ally = team == self.my_team
            if style == "web":                                  # 독 거미줄 둥지 (거미 여왕): 바닥 거미줄 + 독 방울
                col = fx_color((0.7, 0.95, 0.35), ally, False)[0]
                self.vfx.web_zone(x, z, radius, ally, left, total)
            elif style == "venom":                              # 독 웅덩이 (이무기): 끈적한 독액 바닥 + 거품
                self.vfx.venom_zone(x, z, radius, ally, left, total)
            elif style == "fire":                               # 불길 웅덩이 (용): 그을린 바닥 + 용암 균열 + 불꽃
                self.vfx.fire_zone(x, z, radius, ally, left, total)

        # 새끼 거미 고치: 부화가 가까울수록 흔들리고 커진다
        for row, recv in self.anchors:
            aid, team, x, z, hp, remaining = row[:6]
            left = remaining - (now - recv)
            total = max(0.1, row[7])
            p = max(0.0, min(1.0, 1.0 - left / total))
            wob = math.sin(t * (8 + 24 * p)) * 0.12 * p
            r.draw_transparent(m.shadow, model_matrix(x, 0.03, z, scale=0.6), (0, 0, 0, 0.3))
            r.draw_transparent(m.ring, model_matrix(x, 0.05, z, scale=0.8),
                               (0.3, 0.6, 1.0, 0.85) if team == self.my_team else (1.0, 0.3, 0.3, 0.85))
            r.draw(m.cocoon, model_matrix(x, 0.0, z, rot_y=aid, rot_x=wob, scale=1.0 + 0.12 * p * math.sin(t * 20)),
                   emissive=(0.12 + 0.35 * p * p + (0.2 if aid == hov_id else 0), 0.07 + 0.2 * p * p, 0.02))

        # 로컬 이펙트
        for f in self.fx:
            k = (now - f["t"]) / f["dur"]
            col = f["color"]
            al = f.get("al", 1.0)
            if f["kind"] == "burst":
                r.draw_transparent(m.disc, model_matrix(f["x"], 0.09, f["z"], scale=f["r"] * (0.4 + 0.6 * k)),
                                   (*col, 0.6 * (1 - k) * min(1.0, 3.5 / max(1.0, f["r"])) * al), additive=True)
                r.draw_transparent(m.ring, model_matrix(f["x"], 0.1, f["z"], scale=f["r"] * (0.6 + 0.6 * k)),
                                   (*col, (1 - k) * al), additive=True)
            elif f["kind"] == "ring_up":
                r.draw_transparent(m.ring, model_matrix(f["x"], 0.1 + k * 1.5, f["z"], scale=f["r"] * (1 - 0.3 * k)),
                                   (*col, (1 - k) * al), additive=True)
            elif f["kind"] == "poof":
                r.draw_transparent(m.orb, model_matrix(f["x"], 1.0, f["z"], scale=0.25 + k * 0.6),
                                   (*col, 0.6 * (1 - k) * al), additive=True)
            elif f["kind"] == "shards":
                tc = (min(1.4, col[0] * 0.5 + 0.55), min(1.4, col[1] * 0.5 + 0.55), min(1.4, col[2] * 0.5 + 0.55), 1)
                for i in range(10):
                    a = i / 10 * math.tau + f["x"]
                    rr = f["r"] * (0.2 + 0.8 * ((i * 37) % 10) / 10)
                    r.draw(m.relic, model_matrix(f["x"] + math.cos(a) * rr, (1 - k) * 2.5, f["z"] + math.sin(a) * rr,
                                                 scale=0.4, rot_y=a), tint=tc, emissive=(0.3, 0.4, 0.5))

        self.vfx.draw(cam)

        # 클릭 표시 (줄어드는 고리) + 도착할 때까지 남는 목적지 표시
        if self.click_marker:
            x, z, ct = self.click_marker
            k = (now - ct) / 0.45
            if k < 1:
                col = MOVE_COLOR
                r.draw_transparent(m.ring, model_matrix(x, 0.06, z, scale=0.9 * (1 - k) + 0.15), (*col, 1 - k),
                                   additive=True)
                r.draw_transparent(m.disc, model_matrix(x, 0.055, z, scale=0.35 * (1 - k) + 0.05),
                                   (*col, 0.6 * (1 - k)), additive=True)
        if self.move_dest:
            x, z = self.move_dest
            pulse = 0.5 + 0.2 * math.sin(t * 6)
            r.draw_transparent(m.ring, model_matrix(x, 0.06, z, scale=0.32), (*MOVE_COLOR, pulse), additive=True)
            r.draw_transparent(m.disc, model_matrix(x, 0.055, z, scale=0.08), (*MOVE_COLOR, 0.9), additive=True)

        self.draw_leap_marks()
        self.draw_indicators()

    @staticmethod
    def swing_angle(age, dur=0.45):
        """미니언 무기 휘두르기 각도: 뒤로 젖혔다가(-) 앞으로 내려친 뒤(+) 제자리로."""
        if age < 0 or age > dur:
            return 0.0
        k = age / dur
        if k < 0.3:
            return -0.7 * (k / 0.3)
        if k < 0.55:
            p = (k - 0.3) / 0.25
            return -0.7 + 2.0 * (1 - (1 - p) ** 2)
        return 1.3 * (1 - (k - 0.55) / 0.45)

    def cursor_kind(self):
        """평상시 손, 공격할 수 있는 대상 위(또는 공격 이동 대기) 칼, 대상 지정 스킬 조준 중 조준경."""
        if self.settings_open or self.chat_open:
            return "default"
        mouse = self.mouse_pos()
        if self.aiming and self.aiming in SLOTS and self.aim_of(self.aiming) == "enemy":
            return "target"
        if HUD_RECT.collidepoint(mouse) or MINIMAP.collidepoint(mouse) or (self.shop_open and self.shop_panel().collidepoint(mouse)):
            return "default"
        if self.amove_pending:
            return "attack"
        hov = self.hover
        if hov and self.me and not self.me["dead"] and self.enemy_targetable(*hov):
            return "attack"
        return "default"

    def aim_enemy(self, rng):
        """마우스에 가장 가까운 (사거리 안, 보이는) 적 챔피언 — 서버의 pick_enemy_champion 과 같은 규칙."""
        me = self.champs.get(self.my_id)
        if not me:
            return None
        mx, mz = self.mouse_ground()
        best, bd = None, 1e9
        for cid, e in self.champs.items():
            if not e.visible or not e.d or e.d["dead"] or self.champ_info[cid]["tm"] == self.my_team:
                continue
            if math.hypot(e.x - me.x, e.z - me.z) > rng + 0.6:
                continue
            dd = math.hypot(e.x - mx, e.z - mz)
            if dd < bd:
                best, bd = e, dd
        return best

    def draw_serpent_slam_area(self, x, z, ab, col):
        """이무기 내려찍기 범위: 안쪽 = 피해·기절, 바깥쪽(더 넓고 연함) = 충격파."""
        m = self.app.models
        r = self.app.renderer
        wr = ab.get("wave_radius", 0.0)
        if wr > 0:
            r.draw_transparent(m.disc, model_matrix(x, 0.05, z, scale=wr), (*col, 0.07))
            r.draw_transparent(m.ring_thin, model_matrix(x, 0.06, z, scale=wr), (*col, 0.4))
        rad = ab.get("radius", 2.0)
        r.draw_transparent(m.disc, model_matrix(x, 0.07, z, scale=rad), (*col, 0.22))
        r.draw_transparent(m.ring, model_matrix(x, 0.08, z, scale=rad), (*col, 0.9))

    def draw_slam_area(self, x, z, ab, col, strength=1.0, rings=True):
        """내려찍기 범위: 안쪽 = 광역 피해, 바깥쪽(더 넓고 연함) = 장판."""
        m = self.app.models
        r = self.app.renderer
        zr = (ab.get("zone") or {}).get("radius", 0.0)
        if zr > 0:
            r.draw_transparent(m.disc, model_matrix(x, 0.05, z, scale=zr), (*col, 0.07 * strength))
            if rings:
                r.draw_transparent(m.ring_hair, model_matrix(x, 0.06, z, scale=zr), (*col, 0.35 * strength))
        br = ab.get("radius", 0.0)
        if br > 0:
            r.draw_transparent(m.disc, model_matrix(x, 0.07, z, scale=br), (*col, 0.2 * strength))
            if rings:
                r.draw_transparent(m.ring_hair, model_matrix(x, 0.08, z, scale=br), (*col, 0.9 * strength))

    TORNADO_S = 0.3                                          # 원본 회오리(반지름 약 5)를 이 게임 크기로 줄이는 배율

    def draw_tornado(self, r, m, x, z, t):
        """보스러시 용의 회오리 (9겹, 겹마다 색이 번갈고 투명도가 줄며, 겹마다 다른 속도로 돈다). 가산 합성."""
        s = self.TORNADO_S
        r.prog["u_dbl"].value = True
        for i, mesh in enumerate(m.tornado_layers):
            k = i / 8
            spin = t * 9 * (1 + i * 0.18)
            sway = math.sin(t * 5.4 + i * 0.7) * 0.075 * i * s
            col = (0.875, 0.918, 1.0) if i % 2 else (0.66, 0.74, 0.86)
            r.draw_transparent(mesh, model_matrix(x + sway, (0.05 + i * 0.95) * s, z, rot_y=spin, sx=s, sy=0.95 * s, sz=s),
                               (*col, (0.5 - 0.22 * k) * 0.85), additive=True)
        r.prog["u_dbl"].value = False

    def draw_leap_marks(self):
        """덮쳐 내려찍기 도약 중: 착지할 자리(대상 위치)에 피해 범위와 장판 범위를 보여 준다."""
        now = time.time()
        for cid in list(self.leap_marks):
            mk = self.leap_marks[cid]
            if now > mk["end"]:
                del self.leap_marks[cid]
                continue
            tg = self.champs.get(mk["tg"]) if mk.get("tg") is not None else None
            x, z = (tg.x, tg.z) if tg is not None else (mk["x"], mk["z"])
            ally = mk["tm"] == self.my_team
            col = (0.5, 0.8, 1.0) if ally else (1.0, 0.4, 0.3)
            pulse = 0.75 + 0.25 * math.sin(now * 14)
            if "ox" in mk:                                   # 지나갈 길: 바깥 바(넓음, 연함) + 안쪽 바(2배 피해, 진함)
                dx, dz = mk["x"] - mk["ox"], mk["z"] - mk["oz"]
                ln, a = math.hypot(dx, dz), math.atan2(dx, dz)
                r = self.app.renderer
                r.draw_transparent(self.quad, model_matrix(mk["ox"], 0.05, mk["oz"], rot_y=a, sx=mk["w"], sy=1, sz=ln), (*col, 0.12 * pulse))
                r.draw_transparent(self.quad, model_matrix(mk["ox"], 0.055, mk["oz"], rot_y=a, sx=mk["w2"], sy=1, sz=ln), (*col, 0.2 * pulse))
            self.draw_slam_area(x, z, {"radius": mk["r"], "zone": {"radius": mk["zr"]}}, col, pulse, rings=False)

    def draw_indicators(self):
        r = self.app.renderer
        m = self.app.models
        self.ind_range = None               # 미니맵에 같이 보여줄 사거리 (x, z, 반지름, 색)
        me = self.champs.get(self.my_id)
        if not me or not me.d or me.d["dead"]:
            return
        if self.amove_pending:
            rng = 5.5
            data = self.my_data()
            if data:
                rng = data["stats"]["attack_range"] + 0.55
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (1.0, 0.5, 0.4, 0.8))
            self.ind_range = (me.x, me.z, rng, (1.0, 0.5, 0.4))
        # 조준 중인 스킬, 아니면 마우스를 올린 스킬 아이콘의 범위와 조준 바를 보여준다 (롤과 같은 방식)
        slot = self.aiming or self.hover_slot
        if not slot:
            return
        spell = None
        if slot in ("D", "F"):
            spell = (me.d.get("spl") or DEFAULT_SPELLS)[0 if slot == "D" else 1]
        if spell == "flash":
            ab = {"type": "dash", "range": FLASH_RANGE, "width": 0.0}
        elif spell == "mark":
            ab = {"type": "skillshot", "range": MARK_RANGE, "width": 0.7}
        elif spell:
            sp = SPELLS[spell]
            ab = {"type": "spell", "aim": "enemy" if sp["aim"] == "enemy" else "self",
                  "range": sp.get("range", 0.0), "radius": sp.get("radius")}
        else:
            ab = self.my_data()["abilities"][slot]
        mode = gamedata.aim_mode(ab)
        key = slot
        mx, mz = self.aim_target(slot) if not spell else self.mouse_ground()
        dx, dz = mx - me.x, mz - me.z
        dist = math.hypot(dx, dz) or 1.0
        ang = math.atan2(dx, dz)
        # 재사용 대기 중이면 빨간색
        cd = me.d["cd"].get(key, 0) if me.d else 0
        if spell == "mark" and me.d and me.d["mk"]:
            cd = 0                          # 표식 적중 후 돌진(재사용)은 가능
        unlearned = not spell and bool(me.d) and me.d["ab"].get(slot, 0) <= 0     # 아직 배우지 않은 스킬도 빨갛게
        col = (1.0, 0.32, 0.28) if (cd > 0 or unlearned) else (0.55, 0.85, 1.0)
        typ = ab["type"]
        rng = ab.get("range", ab.get("length", 0.0))
        shown = rng or ab.get("radius") or 0.0
        if shown and shown > 0:
            self.ind_range = (me.x, me.z, shown, col)
        if mode == "line":
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (*col, 0.45))
            length = min(dist, rng) if typ == "dash" else rng
            width = ab.get("width", 0.9)
            if width > 0:
                r.draw_transparent(self.quad, model_matrix(me.x, 0.07, me.z, rot_y=ang, sx=width, sy=1, sz=length),
                                   (*col, 0.35))
            if typ == "dash":                                # 점멸: 도착 지점
                ex, ez = me.x + dx / dist * length, me.z + dz / dist * length
                r.draw_transparent(m.ring, model_matrix(ex, 0.08, ez, scale=0.6), (*col, 0.9))
        elif mode == "cone":
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (*col, 0.35))
            crng = ab.get("cone_range", rng)                 # 부채꼴 바람의 실제 사거리 (회오리는 더 멀리 간다)
            r.draw_transparent(self.sector_mesh(ab.get("angle", 60)), model_matrix(me.x, 0.07, me.z, rot_y=ang, scale=crng),
                               (*col, 0.2 if typ == "volley" else 0.32))
            if typ == "tornado":                             # 한가운데로 굴러가는 회오리 길 (부채꼴 위에 바로 겹쳐 보여 준다)
                r.draw_transparent(self.quad, model_matrix(me.x, 0.08, me.z, rot_y=ang, sx=ab.get("width", 2.6), sy=1, sz=rng),
                                   (*col, 0.4))
            if typ == "volley":                              # 독침: 실제로 날아가는 침 길 하나하나를 선으로 (너비 = 침 너비)
                n = max(1, int(ab.get("count", 5)))
                spread = math.radians(ab.get("spread", 55))
                for j in range(n):
                    a_j = ang + ((j / (n - 1) - 0.5) * spread if n > 1 else 0.0)
                    r.draw_transparent(self.quad, model_matrix(me.x, 0.075, me.z, rot_y=a_j, sx=ab.get("width", 0.4), sy=1, sz=rng),
                                       (*col, 0.4))
        elif mode == "ground":
            radius = ab.get("radius", ab.get("trigger_radius", 1.0))
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (*col, 0.6))
            k = min(1.0, rng / dist)
            ex, ez = me.x + dx * k, me.z + dz * k
            if typ == "cocoon":                              # 고치: 마우스 위치에 시전 방향과 수직(T자)으로 나란한 원
                n = max(1, int(ab.get("count", 3)))
                gap = ab.get("spacing", 1.7)
                dl = max(1e-6, math.hypot(dx, dz))
                ux_, uz_ = dx / dl, dz / dl
                px_, pz_ = -uz_, ux_
                stem = min(dist, rng)
                r.draw_transparent(self.beam, model_matrix(me.x, 0.07, me.z, rot_y=ang, sx=0.12, sy=0.05, sz=stem),
                                   (*col, 0.3))
                for j in range(n):
                    off = (j - (n - 1) / 2) * gap
                    cx_, cz_ = ex + px_ * off, ez + pz_ * off
                    r.draw_transparent(m.disc, model_matrix(cx_, 0.07, cz_, scale=radius), (*col, 0.25))
                    r.draw_transparent(m.ring, model_matrix(cx_, 0.08, cz_, scale=radius), (*col, 0.9))
            elif typ == "sky_dive":                          # 불꽃 비행: 자신↔착지 지점 사이 일자 길 — 바깥 바(넓음) + 안쪽 바(2배 피해)
                ln = min(dist, rng)
                r.draw_transparent(self.quad, model_matrix(me.x, 0.07, me.z, rot_y=ang, sx=ab.get("path_width", 5.0), sy=1, sz=ln), (*col, 0.2))
                r.draw_transparent(self.quad, model_matrix(me.x, 0.075, me.z, rot_y=ang, sx=ab.get("inner_width", 3.0), sy=1, sz=ln), (*col, 0.3))
                r.draw_transparent(m.disc, model_matrix(ex, 0.07, ez, scale=radius), (*col, 0.25))
                r.draw_transparent(m.ring, model_matrix(ex, 0.08, ez, scale=radius), (*col, 0.9))
            else:
                r.draw_transparent(m.disc, model_matrix(ex, 0.07, ez, scale=radius), (*col, 0.25))
                r.draw_transparent(m.ring, model_matrix(ex, 0.08, ez, scale=radius), (*col, 0.9))
        elif mode == "circle":                                # 자기 중심 광역: 누르는 동안 자기 둘레 범위를 보여 준다
            radius = ab.get("radius", 3.0)
            r.draw_transparent(m.disc, model_matrix(me.x, 0.07, me.z, scale=radius), (*col, 0.22))
            r.draw_transparent(m.ring, model_matrix(me.x, 0.08, me.z, scale=radius), (*col, 0.9))
        elif mode == "teleport":
            radius = ab.get("radius", 2.0)
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (*col, 0.6))     # 최대 사거리
            k = min(1.0, rng / dist)
            ex, ez = me.x + dx * k, me.z + dz * k
            r.draw_transparent(self.beam, model_matrix(me.x, 0.07, me.z, rot_y=ang, sx=0.18, sy=0.05,
                                                       sz=min(dist, rng)), (*col, 0.45))
            r.draw_transparent(m.disc, model_matrix(ex, 0.07, ez, scale=radius), (*col, 0.25))
            r.draw_transparent(m.ring, model_matrix(ex, 0.08, ez, scale=radius), (*col, 0.9))
            r.draw_transparent(self.pillar, model_matrix(ex, 0.0, ez, sx=0.4, sy=5.0, sz=0.4), (*col, 0.25),
                               additive=True)
        elif mode == "enemy":
            # 대상 지정: 마우스에 가장 가까운 (사거리 안) 적 챔피언을 표시. 대상이 없으면 사거리 원을 빨갛게 보여 준다.
            best = self.aim_enemy(rng)
            rcol = col if best is not None else (1.0, 0.32, 0.28)
            r.draw_transparent(m.ring_thin, model_matrix(me.x, 0.06, me.z, scale=rng), (*rcol, 0.5 if best is not None else 0.8))
            if best is None:
                r.draw_transparent(m.disc, model_matrix(me.x, 0.055, me.z, scale=rng), (*rcol, 0.07))
                if typ == "leap_slam":                       # 대상이 없어도 마우스 위치(사거리 안으로 제한) 기준으로 범위를 보여 준다
                    k = min(1.0, rng / dist)
                    self.draw_slam_area(me.x + dx * k, me.z + dz * k, ab, rcol)
                elif typ == "serpent_slam":
                    k = min(1.0, rng / dist)
                    self.draw_serpent_slam_area(me.x + dx * k, me.z + dz * k, ab, rcol)
            else:
                r.draw_transparent(m.ring, model_matrix(best.x, 0.09, best.z, scale=1.05), (1.0, 0.45, 0.35, 0.95))
                r.draw_transparent(m.disc, model_matrix(best.x, 0.08, best.z, scale=1.0), (1.0, 0.45, 0.35, 0.22))
                if typ == "leap_slam":                       # 덮쳐 내려찍기: 광역 피해 범위(진하게) + 그보다 넓은 장판 범위(연하게)
                    self.draw_slam_area(best.x, best.z, ab, (1.0, 0.45, 0.35) if cd <= 0 and not unlearned else col)
                elif typ == "serpent_slam":                  # 이무기 내려찍기: 기절 범위(진하게) + 충격파 범위(연하게)
                    self.draw_serpent_slam_area(best.x, best.z, ab, (1.0, 0.45, 0.35) if cd <= 0 and not unlearned else col)
        else:   # self (즉시 시전): 효과 범위가 있으면 내 주변에 표시
            radius = ab.get("radius")
            if radius:
                r.draw_transparent(m.disc, model_matrix(me.x, 0.07, me.z, scale=radius), (*col, 0.18))
                r.draw_transparent(m.ring, model_matrix(me.x, 0.08, me.z, scale=radius), (*col, 0.85))
            else:
                r.draw_transparent(m.ring, model_matrix(me.x, 0.07, me.z, scale=1.2), (*col, 0.8))

    # ------------------------------------------------------------------ 2D
    def draw_ui(self, surf):
        self.draw_world_bars(surf)
        self.draw_floaters(surf)
        self.draw_top(surf)
        self.draw_killfeed(surf)
        self.draw_announces(surf)
        self.draw_hud(surf)
        self.draw_team_frames(surf)
        self.draw_minimap(surf)
        self.draw_pings_2d(surf)
        self.draw_ping_wheel(surf)
        self.draw_chat(surf)
        me = self.me
        if me and me["dead"] and self.winner is None:
            shade = pygame.Surface((WIDTH, 120), pygame.SRCALPHA)
            shade.fill((20, 20, 30, 150))
            surf.blit(shade, (0, 230))
            ui.text(surf, f"부활까지 {math.ceil(me['rt'])}초", (WIDTH // 2, 270), 34, (230, 230, 240), anchor="center",
                    bold=True)
        if me and not me["dead"] and me.get("rc", 0) > 0:
            k = 1 - me["rc"] / max(0.1, me.get("rct", RECALL_TIME))
            r = pygame.Rect(WIDTH // 2 - 130, 560, 260, 14)
            ui.bar(surf, r, k, (90, 150, 255))
            ui.text(surf, f"귀환 {me['rc']:.1f}", (r.centerx, r.y - 3), 14, anchor="midbottom", bold=True)
        if self.shop_open:
            self.draw_shop(surf)
            if self.shop_tip:
                self.draw_item_tooltip(surf, *self.shop_tip)
        if self.show_score:
            self.draw_scoreboard(surf)
        if self.winner is not None:
            self.draw_game_over(surf)
        if getattr(self, "stat_tip", None) and not self.settings_open:
            self.draw_stat_tooltip(surf, *self.stat_tip)
        elif self.hud_tooltip and not self.settings_open:
            mouse, tip = self.hud_tooltip
            self.draw_tooltip(surf, mouse, *tip)
        self.app.settings_ui.draw(surf)

    def draw_world_bars(self, surf):
        cam = self.app.renderer.camera
        for sid, s in self.structs.items():
            st = self.struct_state[sid]
            if not st[2]:
                continue
            h = {"turret": 5.2, "inhibitor": 2.8, "nexus": 5.8}[s["k"]]
            p = cam.world_to_screen(s["x"], h, s["z"])
            if not p:
                continue
            col = ui.TEAM_UI[s["tm"]] if s["tm"] != self.my_team else (90, 170, 255)
            if s["tm"] != self.my_team:
                col = (230, 70, 60)
            w = 90 if s["k"] != "nexus" else 120
            x0 = int(p[0] - w // 2)
            ui.bar(surf, (x0, p[1], w, 9), st[1] / s["mhp"], col)
            # 포탑은 방패(골드) 한 칸 간격, 나머지 구조물은 1000 단위
            unit = s["mhp"] / s["pl"] if s.get("pl") else 1000
            self.draw_hp_ticks(surf, x0, int(p[1]), w, 9 if s.get("pl") else 5, st[1], s["mhp"], unit)
            if not st[3]:
                ui.text(surf, "무적", (p[0], p[1] - 4), 12, ui.TEXT_DIM, anchor="midbottom")
        for mid, e in self.minions.items():
            row = e.d
            if row[6] >= row[7]:
                continue
            p = cam.world_to_screen(e.x, MINION_HEIGHT[row[1]] + 0.2, e.z)
            if p:
                col = (90, 170, 255) if row[2] == self.my_team else (230, 70, 60)
                ui.bar(surf, (p[0] - 18, p[1], 36, 5), row[6] / row[7], col)
        for cid, e in self.champs.items():
            d = e.d
            if not d or d["dead"] or not e.visible:
                continue
            p = cam.world_to_screen(e.x, getattr(e.ca, "bar_h", BAR_H) if e.ca else BAR_H, e.z)     # 머리가 높이 솟는 리그(이무기)는 체력바도 높이
            if not p:
                continue
            info = self.champ_info[cid]
            if cid == self.my_id:
                col = (120, 220, 80)
            elif info["tm"] == self.my_team:
                col = (90, 170, 255)
            else:
                col = (230, 70, 60)
            x0, y0 = int(p[0] - 52), int(p[1])
            pygame.draw.rect(surf, (10, 10, 16, 220), (x0 - 22, y0 - 2, 128, 21))
            pygame.draw.rect(surf, (30, 30, 40, 255), (x0 - 22, y0 - 2, 20, 21))
            ui.text(surf, str(d["lv"]), (x0 - 12, y0 + 8), 13, ui.TEXT, anchor="center", bold=True, shadow=False)
            ui.bar(surf, (x0, y0, 104, 11), d["hp"] / max(1, d["mhp"]), col, border=None)
            self.draw_shield_segment(surf, x0, y0, 104, 11, d["hp"], d["mhp"], d.get("sh", 0))
            self.draw_hp_ticks(surf, x0, y0, 104, 5, d["hp"], d["mhp"], 250)
            ui.bar(surf, (x0, y0 + 12, 104, 5), d["mp"] / max(1, d["mmp"]), (80, 140, 255), border=None)
            ui.text(surf, info["n"], (p[0], y0 - 4), 13, ui.TEXT, anchor="midbottom")
            self.draw_status_badges(surf, p[0], y0 + 20, d["st"])
        # 거미 고치: 미니언과 같은 일반 체력바
        for row, recv in self.anchors:
            aid, team, ax, az, ahp, remaining = row[:6]
            p = cam.world_to_screen(ax, 1.3, az)
            if p:
                col = (90, 170, 255) if team == self.my_team else (230, 70, 60)
                mhp = row[8] if len(row) > 8 else max(1, ahp)
                ui.bar(surf, (int(p[0]) - 20, int(p[1]), 40, 5), ahp / max(1, mhp), col)

    @staticmethod
    def draw_shield_segment(surf, x0, y0, w, h, hp, mhp, shield):
        """체력바 위에 보호막 구간을 덧그린다 (체력 바로 뒤, 꽉 차 있으면 오른쪽 끝에서부터)."""
        if shield <= 0 or mhp <= 0:
            return
        sw = max(2, min(w, int(w * shield / mhp)))
        sx = x0 + int(w * hp / mhp)
        sx = min(sx, x0 + w - sw)
        pygame.draw.rect(surf, (235, 238, 250), (sx, y0, sw, h))
        pygame.draw.rect(surf, (140, 150, 180), (sx, y0, sw, h), 1)

    @staticmethod
    def draw_status_badges(surf, cx, y, statuses):
        """체력바 아래에 상태 이상·강화 이름표를 작게 늘어놓는다."""
        shown = [(label, col) for key, label, col in STATUS_BADGES if key in statuses][:4]
        if not shown:
            return
        font = ui.font(11, True)
        widths = [font.size(label)[0] + 8 for label, _ in shown]
        x = int(cx - (sum(widths) + 3 * (len(shown) - 1)) / 2)
        for (label, col), wd in zip(shown, widths):
            rect = pygame.Rect(x, int(y), wd, 14)
            pygame.draw.rect(surf, tuple(int(v * 0.4) for v in col), rect, border_radius=3)
            pygame.draw.rect(surf, col, rect, 1, border_radius=3)
            ui.text(surf, label, rect.center, 11, (245, 245, 250), anchor="center", bold=True, shadow=False)
            x += wd + 3

    @staticmethod
    def draw_hp_ticks(surf, x0, y0, w, h, hp, mhp, unit):
        """체력바에 unit 체력마다 눈금선을 긋는다 (남은 체력 부분에만)."""
        if mhp <= 0:
            return
        step = w * unit / mhp
        xx = x0 + step
        while xx < x0 + w * hp / mhp:
            pygame.draw.line(surf, (0, 0, 0), (int(xx), y0), (int(xx), y0 + h))
            xx += step

    def draw_floaters(self, surf):
        cam = self.app.renderer.camera
        now = time.time()
        for f in self.floaters:
            k = (now - f["t"]) / f["dur"]
            p = cam.world_to_screen(f["x"], 2.0 + k * 1.2, f["z"])
            if p:
                ui.text(surf, f["text"], p, f["size"], f["color"], anchor="center", bold=True)

    def draw_top(self, surf):
        # 롤처럼 우측 상단: 팀 킬 (우리 vs 상대) | 내 K/D/A | 경기 시간
        r = pygame.Rect(WIDTH - 286, 6, 280, 32)
        ui.panel(surf, r, (14, 20, 34, 120), None, radius=4)
        y = r.centery
        ours, theirs = self.my_team, 1 - self.my_team
        ui.text(surf, str(self.score[ours]), (r.x + 30, y), 18, ui.TEAM_UI[ours], anchor="center", bold=True)
        ui.text(surf, "vs", (r.x + 55, y), 12, ui.TEXT_DIM, anchor="center")
        ui.text(surf, str(self.score[theirs]), (r.x + 80, y), 18, ui.TEAM_UI[theirs], anchor="center", bold=True)
        pygame.draw.line(surf, (50, 56, 70), (r.x + 106, r.y + 6), (r.x + 106, r.bottom - 6))
        me = self.me
        if me:
            ui.text(surf, f"{me['k']}/{me['d']}/{me['as']}", (r.x + 158, y), 15, anchor="center", bold=True)
        pygame.draw.line(surf, (50, 56, 70), (r.x + 210, r.y + 6), (r.x + 210, r.bottom - 6))
        mm, ss = divmod(int(self.server_time), 60)
        ui.text(surf, f"{mm:02d}:{ss:02d}", (r.right - 35, y), 16, anchor="center", bold=True)

    def draw_killfeed(self, surf):
        now = time.time()
        y = 48
        for t, ev in self.killfeed:
            if now - t > 8:
                continue
            kc = ui.TEAM_UI.get(ev["kt"], ui.TEXT)
            vc = ui.TEAM_UI.get(ev["vt"], ui.TEXT)
            kw = ui.font(14).size(ev["kn"])[0]
            vw = ui.font(14).size(ev["vn"])[0]
            w = kw + vw + 64
            x0 = WIDTH - 6 - w
            ui.panel(surf, (x0, y - 2, w, 26), (14, 20, 34, 120), None, radius=4)
            ui.text(surf, ev["kn"], (x0 + 10, y + 11), 14, kc, anchor="midleft")
            ui.text(surf, "▶", (x0 + 10 + kw + 20, y + 11), 12, ui.TEXT_DIM, anchor="center")
            ui.text(surf, ev["vn"], (x0 + 10 + kw + 40, y + 11), 14, vc, anchor="midleft")
            y += 30

    def draw_chat(self, surf):
        """왼쪽 아래 채팅창. 닫혀 있으면 최근 줄만 잠깐 보이고 흐려진다."""
        now = time.time()
        if self.chat_open:
            lines = self.chat_lines[-10:]
            bg = pygame.Surface((CHAT_W, 10 * CHAT_LINE + 8), pygame.SRCALPHA)
            bg.fill((8, 12, 22, 140))
            surf.blit(bg, (CHAT_X, CHAT_Y - 10 * CHAT_LINE - 10))
        else:
            lines = [ln for ln in self.chat_lines[-8:] if now - ln[0] < CHAT_SHOW]
        y = CHAT_Y - 6
        for t, parts in reversed(lines):
            fade = 1.0 if self.chat_open else max(0.0, min(1.0, (CHAT_SHOW - (now - t)) / 2.0))
            x = CHAT_X + 6
            for text, col in parts:                          # 어두워지지 않고 투명해지며 사라진다
                if col in (ui.TEXT, ui.TEXT_DIM):
                    col = CHAT_WHITE                         # 팀 색(파랑·빨강)·금색이 아닌 일반 글자는 흰색
                img = ui.render_text(text, CHAT_FONT, col, False).copy()
                sh = ui.render_text(text, CHAT_FONT, (0, 0, 0), False).copy()
                img.set_alpha(int(255 * fade))
                sh.set_alpha(int(255 * fade))
                rc = img.get_rect(bottomleft=(x, y))
                surf.blit(sh, rc.move(1, 1))
                surf.blit(img, rc)
                x = rc.right
            y -= CHAT_LINE
        if self.chat_open:
            self.chat_in.draw(surf)

    def draw_announces(self, surf):
        now = time.time()
        y = 190 if self.draw_kill_banner(surf) else 110
        for t, text, col in self.announces:
            ui.text(surf, text, (WIDTH // 2, y), 24, col, anchor="center", bold=True)
            y += 34

    # ---- 하단 HUD
    def draw_hud(self, surf):
        me = self.me
        data = self.my_data()
        self.levelup_rects = []
        if not me or not data:
            return
        ui.panel(surf, HUD_RECT, (14, 20, 34, 235), ui.BORDER)
        self.draw_cast_msg(surf)
        # 초상화
        draw_round_portrait(surf, self.champ_info[self.my_id]["c"], (338, 650), 30, (230, 230, 240),
                            color=data.get("color", (200, 200, 200)))
        pygame.draw.circle(surf, (20, 25, 40), (360, 678), 13)
        ui.text(surf, str(me["lv"]), (360, 678), 14, anchor="center", bold=True)
        # 경험치
        xp_ratio = me["xp"] / max(1, me["xpn"]) if me["lv"] < 18 else 1
        pygame.draw.arc(surf, (180, 120, 255), (306, 618, 64, 64), -math.pi / 2, -math.pi / 2 + math.tau * xp_ratio, 3)

        # 스킬
        mouse = ui.mouse_pos()
        tooltip = None
        for slot in SLOTS:
            x = ABILITY_X[slot]
            rect = pygame.Rect(x, 614, 54, 54)
            ab = data["abilities"][slot]
            rank = me["ab"][slot]
            cd = me["cd"][slot]
            mana_ok = rank > 0 and me["mp"] >= ab.get("mana", [0])[rank - 1]
            icon = ui.icon(f"assets/ui/skills/{data['id']}_{slot}.png", 54)
            if icon:
                surf.blit(icon, rect)
                radius = 9
                if rank <= 0:
                    shade(surf, rect, (0, 0, 0, 165), radius)       # 아직 배우지 않은 스킬은 어둡게
            else:
                radius = 6
                pygame.draw.rect(surf, (40, 70, 110) if rank > 0 else (35, 38, 48), rect, border_radius=6)
                ui.text(surf, ab["name"][:2], rect.center, 16, (220, 235, 255) if rank else ui.TEXT_DIM,
                        anchor="center", bold=True)
            if rank > 0 and cd > 0:
                shade(surf, rect, (0, 0, 0, 160), radius)
                ui.text(surf, f"{cd:.0f}" if cd >= 1 else f"{cd:.1f}", rect.center, 20, anchor="center", bold=True)
            elif rank > 0 and not mana_ok:                   # 마나 부족: 쿨타임처럼 어둡게 + 필요 마나를 파란 글씨로
                shade(surf, rect, (0, 0, 0, 160), radius)
                ui.text(surf, f"{ab.get('mana', [0])[rank - 1]:g}", rect.center, 20, MANA_BLUE, anchor="center", bold=True)
            if self.aiming == slot:
                pygame.draw.rect(surf, ui.HIGHLIGHT, rect, 2, border_radius=radius)
            elif not icon:
                pygame.draw.rect(surf, ui.BORDER, rect, 1, border_radius=radius)
            ui.text(surf, self.binds.name(slot), (x + 3, 614), 12, ui.GOLD, bold=True)
            # 랭크 표시
            maxr = len(ab["cooldown"])
            for i in range(maxr):
                px = x + 4 + i * (46 / maxr)
                pygame.draw.rect(surf, (255, 210, 90) if i < rank else (60, 64, 76), (int(px), 671, int(46 / maxr) - 2, 4))
            # 레벨업 버튼
            if me["sp"] > 0 and rank < self.max_rank(slot, me["lv"]):
                lr = pygame.Rect(x + 15, 588, 24, 22)
                pygame.draw.rect(surf, (230, 190, 70), lr, border_radius=4)
                ui.text(surf, "+", lr.center, 18, (40, 30, 10), anchor="center", bold=True, shadow=False)
                self.levelup_rects.append((slot, lr))
            if rect.collidepoint(mouse):
                cost = ab.get("mana", [0])[max(0, rank - 1)]
                tooltip = ([(f"[{self.binds.name(slot)}] {ab['name']}  ·  ", ui.GOLD), (f"마나 {cost}", MANA_BLUE),
                            (f"  ·  {ab['cooldown'][max(0, rank - 1)]}초", ui.GOLD)], ab.get("desc", ""), ability_details(ab), rank)
        # 소환사 주문
        spl = me.get("spl") or DEFAULT_SPELLS
        for slot in ("D", "F"):
            sid = spl[0 if slot == "D" else 1]
            sp = SPELLS[sid]
            marked = sid == "mark" and me["mk"]
            x = SPELL_X[slot]
            rect = pygame.Rect(x, 619, 44, 44)
            icon = ui.icon(f"assets/ui/spells/{sid}.png", 44)
            if icon:
                surf.blit(icon, rect)
            else:
                pygame.draw.rect(surf, tuple(c // 2 for c in sp["color"]), rect, border_radius=6)
                ui.text(surf, sp["name"], rect.center, 14, anchor="center", bold=True)
            cd = me["cd"][slot]
            if marked:
                pygame.draw.rect(surf, ui.HIGHLIGHT, rect, 3, border_radius=8)     # 재사용(돌진) 가능
            elif cd > 0:
                shade(surf, rect, (0, 0, 0, 170), 8)
                ui.text(surf, f"{cd:.0f}", rect.center, 17, anchor="center", bold=True)
            if not marked and not icon:
                pygame.draw.rect(surf, ui.BORDER, rect, 1, border_radius=6)
            ui.text(surf, self.binds.name(slot), (x + 3, 619), 11, ui.GOLD, bold=True)
            if rect.collidepoint(mouse):
                tooltip = (f"[{self.binds.name(slot)}] {sp['name']}", sp["desc"], sp["details"], 0)

        # 체력 / 마나
        ui.bar(surf, (392, 680, 356, 15), me["hp"] / max(1, me["mhp"]), (70, 190, 70))
        self.draw_shield_segment(surf, 392, 680, 356, 15, me["hp"], me["mhp"], me.get("sh", 0))
        ui.text(surf, f"{me['hp']} / {me['mhp']}" + (f"  (+{me['sh']})" if me.get("sh", 0) > 0 else ""),
                (570, 687), 12, anchor="center", shadow=True)
        ui.bar(surf, (392, 697, 356, 11), me["mp"] / max(1, me["mmp"]), (70, 120, 230))
        ui.text(surf, f"{me['mp']} / {me['mmp']}", (570, 702), 10, anchor="center", shadow=True)

        # 아이템 (4칸 x 2줄, 신발도 한 칸을 차지한다). 끌어서 다른 칸에 놓으면 자리가 바뀐다
        self.hud_inv_rects = []
        self.hud_slot_rects = []
        if self.inv_drag is not None and self.inv_drag >= len(me["it"]):
            self.inv_drag = None
        for i in range(INVENTORY_SLOTS):
            x = 764 + (i % INV_COLS) * 37
            y = 616 + (i // INV_COLS) * 38
            rect = pygame.Rect(x, y, 34, 34)
            self.hud_slot_rects.append((i, rect))
            drop = self.inv_drag is not None and i != self.inv_drag and rect.collidepoint(mouse)
            pygame.draw.rect(surf, (45, 60, 90) if drop else (25, 30, 42), rect, border_radius=4)
            if i < len(me["it"]):
                it = gamedata.items()[me["it"][i]]
                draw_item(surf, me["it"][i], rect.inflate(-2, -2))
                self.hud_inv_rects.append((i, rect))
                if i == self.inv_drag:                  # 끌고 있는 아이템의 원래 칸은 어둡게
                    dim = pygame.Surface(rect.size, pygame.SRCALPHA)
                    dim.fill((0, 0, 0, 150))
                    surf.blit(dim, rect.topleft)
                if rect.collidepoint(mouse) and self.inv_drag is None:
                    tooltip = (it["name"], f"{item_stat_text(it)}\n{sell_text(it)}")
            pygame.draw.rect(surf, ui.HIGHLIGHT if drop else ui.BORDER, rect, 1, border_radius=4)
        if self.inv_drag is not None:                   # 끌고 있는 아이템은 마우스를 따라온다
            draw_item(surf, me["it"][self.inv_drag], pygame.Rect(mouse[0] - 16, mouse[1] - 16, 32, 32))
        self.gold_rect = ui.text(surf, f"{me['g']} G", (914, 706), 18, ui.GREEN_C if me.get("shop") else ui.GOLD,
                                 anchor="bottomleft", bold=True)

        # 능력치
        st = me["s"]
        self.stat_tip = None
        ui.panel(surf, (160, 606, 136, 108), (14, 20, 34, 225), ui.BORDER)
        for i, (key, label, value) in enumerate(STAT_ICONS):
            x = 168 + (i % 2) * 64
            y = 614 + (i // 2) * 24
            icon_rect = pygame.Rect(x, y, 20, 20)
            icon = ui.icon(f"assets/ui/stats/{key}.png", 20)
            if icon:
                surf.blit(icon, icon_rect)
            else:
                col, ch = STAT_FALLBACK[key]
                pygame.draw.rect(surf, col, icon_rect, border_radius=4)
                ui.text(surf, ch, icon_rect.center, 12, (20, 20, 30), anchor="center", bold=True, shadow=False)
            ui.text(surf, str(value(st)), (x + 26, y + 10), 13, anchor="midleft", shadow=False)
            if pygame.Rect(x, y, 60, 20).collidepoint(mouse):
                self.stat_tip = (mouse, key, label, me)

        self.hud_tooltip = (mouse, tooltip) if tooltip else None

    def draw_stat_tooltip(self, surf, mouse, key, label, me):
        """롤식 능력치 툴팁: 설명 + '공격력: 81 (기본 59+추가 22)'."""
        st, base = me["s"], me.get("sb", {})
        sk = {"ad": "ad", "ap": "ap", "armor": "ar", "mr": "mr", "attack_speed": "aspd",
              "move_speed": "ms", "ability_haste": "ah", "crit": "cr"}[key]
        total = st[sk]
        b = base.get(sk, 0.0)
        pct = key == "crit"
        if key == "attack_speed":
            fmt = lambda v: f"{v:.2f}"
        elif pct:
            fmt = lambda v: f"{v:g}%"
        else:
            fmt = lambda v: f"{round(v):g}"
        bonus = total - b
        DESC = {
            "ad": ("기본 공격으로 가하는 ", "물리 피해", (255, 140, 70), "를 나타냅니다. 또한, 일부 스킬로 가하는 피해량을 증가시킵니다."),
            "ap": ("스킬과 효과로 가하는 ", "마법 피해", (130, 190, 255), "를 증가시킵니다."),
            "armor": ("받는 ", "물리 피해", (255, 140, 70), "를 줄여줍니다."),
            "mr": ("받는 ", "마법 피해", (130, 190, 255), "를 줄여줍니다."),
            "attack_speed": ("초당 ", "기본 공격", (255, 140, 70), " 횟수를 나타냅니다."),
            "move_speed": ("초당 ", "이동 거리", (200, 215, 230), "를 나타냅니다. (100 = 기본 이동 속도 기준)"),
            "ability_haste": ("스킬의 ", "재사용 대기시간", (120, 210, 230), "을 줄여줍니다."),
            "crit": ("기본 공격이 ", "치명타", (235, 90, 80), "로 적중할 확률입니다."),
        }[key]
        W = 360
        body = "".join(DESC[:1]) + DESC[1] + DESC[3]
        lines = ui.wrap(body, 13, W - 24)
        R = max(40, len(lines) * 19 + 20)              # 세 영역(이름 / 설명 / 수치)의 높이를 똑같이
        h = R * 3
        r = pygame.Rect(0, 0, W, h)
        r.bottomleft = (mouse[0] - 10, mouse[1] - 10)
        r.x = max(4, min(WIDTH - W - 4, r.x)); r.y = max(4, r.y)
        ui.panel(surf, r, (12, 18, 30, 245), ui.BORDER)
        for k in (1, 2):
            pygame.draw.line(surf, (150, 125, 60), (r.x + 8, r.y + R * k), (r.right - 8, r.y + R * k))
        ui.text(surf, label, (r.x + 12, r.y + R // 2), 15, ui.TEXT, anchor="midleft", bold=True)
        # 설명: 키워드 색 강조 (줄이 키워드 중간에서 갈리면 그 줄은 기본색)
        pre, kw, kcol, post = DESC
        y = r.y + R + (R - len(lines) * 19) // 2
        for line in lines:
            x = r.x + 12
            rest = line
            while rest:
                j = rest.find(kw)
                if j < 0:
                    ui.text(surf, rest, (x, y), 13, ui.TEXT, shadow=False); break
                if j:
                    x = ui.text(surf, rest[:j], (x, y), 13, ui.TEXT, shadow=False).right
                x = ui.text(surf, kw, (x, y), 13, kcol, shadow=False).right
                rest = rest[j + len(kw):]
            y += 19
        cy = r.y + R * 2 + R // 2
        parts = [(f"{label}: ", ui.TEXT, False), (fmt(total), (110, 230, 120), True)]
        if key != "move_speed" and not (abs(bonus) < 1e-6 and b == 0):
            col = (110, 230, 120) if bonus >= 0 else (255, 110, 100)
            parts += [(" (기본 ", ui.TEXT, False), (fmt(b), (90, 190, 255), False),
                      ("+" if bonus >= 0 else "-", ui.TEXT, False), (fmt(abs(bonus)), col, False), (")", ui.TEXT, False)]
        x = r.x + 12
        for t_, col_, bd in parts:
            x = ui.text(surf, t_, (x, cy), 14, col_, anchor="midleft", bold=bd, shadow=False).right

    def draw_tooltip(self, surf, mouse, title, body, details=None, rank=0):
        """HUD 툴팁. details 가 있으면 Shift 를 누르고 있는 동안 상세 값(레벨별 값은 현재 레벨 강조)을 보여준다."""
        shift = bool(details) and bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        lines = ui.wrap(body, 13, 320) if body else []
        h = 30 + len(lines) * 17 + (10 + len(details) * 20 if shift else 0)
        if isinstance(title, list):
            title_w = sum(ui.font(14, True).size(t)[0] for t, _ in title)
        else:
            title_w = ui.font(14, True).size(title)[0]
        vx = detail_value_x(details) + 10 if details else 150
        w = (max(400, vx + 250) if shift else 340) if body else title_w + 20
        r = pygame.Rect(0, 0, w, h)
        r.bottomleft = (mouse[0] - 20, 580 if body else mouse[1] - 8)
        r.x = max(4, min(WIDTH - w - 4, r.x))
        ui.panel(surf, r, (12, 18, 30, 245), ui.BORDER)
        if isinstance(title, list):
            tx = r.x + 10
            for t, col in title:
                tx = ui.text(surf, t, (tx, r.y + 6), 14, col, bold=True).right
        else:
            ui.text(surf, title, (r.x + 10, r.y + 6), 14, ui.GOLD, bold=True)
        if details and not shift:
            ui.text(surf, "Shift 상세", (r.right - 10, r.y + 8), 11, ui.TEXT_DIM, anchor="topright")
        ui.text_block(surf, body, (r.x + 10, r.y + 26), 320, 13, ui.TEXT, 3)
        if not shift:
            return
        y = r.y + 30 + len(lines) * 17 + 4
        pygame.draw.line(surf, (50, 60, 80), (r.x + 10, y), (r.right - 10, y))
        y += 6
        for label, value in details:
            mana_row = label == "마나 소모"
            draw_detail_label(surf, label, (r.x + 10, y), 13, MANA_BLUE if mana_row else ui.TEXT_DIM)
            if isinstance(value, list):
                x = r.x + vx
                for i, v in enumerate(value):
                    cur = i == rank - 1
                    x = ui.text(surf, v, (x, y), 13, MANA_BLUE if mana_row else (ui.GOLD if cur else ui.TEXT), bold=cur).right
                    if i < len(value) - 1:
                        x = ui.text(surf, " / ", (x, y), 13, ui.TEXT_DIM).right
            else:
                ui.text(surf, value, (r.x + vx, y), 13, MANA_BLUE if mana_row else ui.TEXT)
            y += 20

    # ---- 미니맵
    def world_to_minimap(self, x, z):
        mx = MINIMAP.x + MM_PAD + (x + MINIMAP_X) / (2 * MINIMAP_X) * (MINIMAP.width - 2 * MM_PAD)
        my = MINIMAP.centery + z * (MINIMAP.width - 2 * MM_PAD) / (2 * MINIMAP_X)      # 가로·세로 같은 축척 (비율 왜곡 없음)
        return int(mx), int(my)

    def minimap_ellipse(self, x, z, radius):
        """월드의 원(반지름 radius)을 미니맵에 그릴 타원 영역으로. 미니맵은 가로·세로 축척이 달라 타원이 된다."""
        cx, cy = self.world_to_minimap(x, z)
        rx = radius / (2 * MINIMAP_X) * (MINIMAP.width - 2 * MM_PAD)
        ry = rx
        return pygame.Rect(int(cx - rx), int(cy - ry), max(2, int(rx * 2)), max(2, int(ry * 2)))

    def minimap_to_world(self, sx, sy):
        x = (sx - MINIMAP.x - MM_PAD) / (MINIMAP.width - 2 * MM_PAD) * (2 * MINIMAP_X) - MINIMAP_X
        z = (sy - MINIMAP.centery) * (2 * MINIMAP_X) / (MINIMAP.width - 2 * MM_PAD)
        return mapdata.clamp_to_map(x, z)

    def portrait(self, surf, rect, cid, level, dead, ring):
        """롤식 팀 프로필 아이콘: 원형 초상화, 팀색 테두리, 좌하단 레벨, 죽으면 흑백."""
        info = self.champ_info[cid]
        data = gamedata.champion(info["c"]) or {}
        draw_round_portrait(surf, info["c"], rect.center, rect.w // 2, ring, dead, data.get("color", (160, 170, 190)))
        lp = (rect.x + 7, rect.bottom - 7)
        pygame.draw.circle(surf, (12, 16, 26), lp, 9)
        pygame.draw.circle(surf, ring if not dead else (110, 112, 120), lp, 9, 1)
        ui.text(surf, str(level), lp, 11, (230, 235, 245) if not dead else (150, 152, 160),
                anchor="center", bold=True, shadow=False)

    def draw_team_frames(self, surf):
        """롤식 팀 프로필: 미니맵 바로 위. 아래줄=아군(자신 제외, 죽으면 자신도) 아이콘+짧은 체력/마나 바,
        윗줄=죽은 적 아이콘(흑백+부활 초). 죽은 아군은 흑백+부활 초."""
        if not self.champ_info or not self.me:
            return
        SZ, GAP = 52, 7
        allies = [cid for cid, i in self.champ_info.items() if i["tm"] == self.my_team]
        enemies = [cid for cid, i in self.champ_info.items() if i["tm"] != self.my_team]

        def state(cid):
            e = self.champs.get(cid)
            d = e.d if e else None
            row = self.board.get(cid)
            lv = (d["lv"] if d else (row[1] if row else 1))
            dead = bool(row[8]) if row else (bool(d["dead"]) if d else False)
            if d and d.get("dead"):
                dead = True
            rt = (row[9] if row else (d["rt"] if d else 0)) if dead else 0
            return e, d, lv, dead, rt

        ally_rows = []
        for cid in allies:
            st = state(cid)
            if cid == self.my_id and not st[3]:
                continue                       # 자신은 평소엔 표시 안 함
            ally_rows.append((cid, st))
        dead_enemies = [(cid, state(cid)) for cid in enemies if state(cid)[3]]

        right = MINIMAP.right
        y_bottom = TEAMFRAME.bottom
        ROW_H = SZ + 12                         # 아이콘 + 바 2줄
        if ally_rows:
            n = len(ally_rows)
            x0 = right - n * SZ - (n - 1) * GAP
            y0 = y_bottom - ROW_H
            for i, (cid, (e, d, lv, dead, rt)) in enumerate(ally_rows):
                r = pygame.Rect(x0 + i * (SZ + GAP), y0, SZ, SZ)
                self.portrait(surf, r, cid, lv, dead, ui.BLUE_C if cid != self.my_id else (255, 220, 110))
                if dead:
                    ui.text(surf, f"{rt:.0f}", r.center, 24, (255, 255, 255), anchor="center", bold=True)
                elif d:
                    ratio = d["hp"] / max(1, d["mhp"])
                    col = (80, 210, 100) if ratio > 0.35 else (240, 190, 70) if ratio > 0.15 else (240, 80, 70)
                    pygame.draw.rect(surf, (10, 14, 20), (r.x, r.bottom + 2, SZ, 12))
                    pygame.draw.rect(surf, col, (r.x + 1, r.bottom + 3, int((SZ - 2) * max(0, min(1, ratio))), 6))
                    mr = d["mp"] / max(1, d["mmp"])
                    pygame.draw.rect(surf, (70, 130, 255), (r.x + 1, r.bottom + 10, int((SZ - 2) * max(0, min(1, mr))), 3))
        if dead_enemies:
            n = len(dead_enemies)
            x0 = right - n * SZ - (n - 1) * GAP
            y0 = y_bottom - (ROW_H if ally_rows else 0) - SZ - 8
            for i, (cid, (e, d, lv, dead, rt)) in enumerate(dead_enemies):
                r = pygame.Rect(x0 + i * (SZ + GAP), y0, SZ, SZ)
                self.portrait(surf, r, cid, lv, True, ui.RED_C)
                ui.text(surf, f"{rt:.0f}", r.center, 24, (255, 255, 255), anchor="center", bold=True)

    def draw_minimap(self, surf):
        ui.panel(surf, MINIMAP, MM_BG, ui.BORDER, radius=4)
        pts_top, pts_bot = [], []
        x = -mapdata.LANE_END
        while x <= mapdata.LANE_END + 1e-6:
            hw = mapdata.half_width(x)
            pts_top.append(self.world_to_minimap(x, -hw))
            pts_bot.append(self.world_to_minimap(x, hw))
            x += 4.0
        pygame.draw.polygon(surf, (128, 110, 84), pts_top + pts_bot[::-1])             # 사암 길
        # 부활 지점 원과 주위 기둥
        for team in (BLUE, RED):
            fx, fz = mapdata.fountain_pos(team)
            fc = ui.TEAM_UI[self.view_team(team)]
            c0 = self.world_to_minimap(fx, fz)
            pygame.draw.ellipse(surf, tuple(int(v * 0.45) for v in fc),
                                self.minimap_ellipse(fx, fz, 5.5))
            pygame.draw.ellipse(surf, fc, self.minimap_ellipse(fx, fz, 5.5), 1)
            for px, pz in mapdata.fountain_pillars(team):
                pp = self.world_to_minimap(px, pz)
                pygame.draw.circle(surf, (205, 195, 170), pp, 2)
        for sid, s in self.structs.items():
            st = self.struct_state[sid]
            col = ui.TEAM_UI[self.view_team(s["tm"])] if st[2] else (60, 60, 70)
            p = self.world_to_minimap(s["x"], s["z"])
            size = 4 if s["k"] == "turret" else 6
            pygame.draw.rect(surf, col, (p[0] - size // 2, p[1] - size // 2, size, size))
        for rid, x, z, active in self.relics:
            if active:
                pygame.draw.circle(surf, (90, 230, 120), self.world_to_minimap(x, z), 3)
        for e in self.minions.values():
            col = (120, 170, 255) if self.view_team(e.d[2]) == BLUE else (255, 120, 110)
            p = self.world_to_minimap(e.x, e.z)
            pygame.draw.rect(surf, col, (p[0] - 1, p[1] - 1, 2, 2))
        if self.minimap_fog:
            surf.blit(self.minimap_fog[0], self.minimap_fog[1])
        for cid, e in sorted(self.champs.items(), key=lambda kv: kv[0] == self.my_id):     # 내 챔피언이 맨 위
            if not e.d or e.d["dead"] or not e.visible:
                continue
            info = self.champ_info[cid]
            p = self.world_to_minimap(e.x, e.z)
            mine = cid == self.my_id
            data = gamedata.champion(info["c"]) or {}
            # 각 챔피언의 얼굴 아이콘 (테두리는 팀 색, 내 챔피언은 금색으로 더 굵게)
            ring_col = ui.GREEN_C if mine else ui.TEAM_UI[self.view_team(info["tm"])]
            draw_round_portrait(surf, info["c"], p, 8, ring_col, color=data.get("color", (160, 170, 190)), ring_w=0)
            draw_hp_ring(surf, p, 11, e.d["hp"] / max(1, e.d["mhp"]), ring_col, 3)
        # 내 이동 경로
        me = self.champs.get(self.my_id)
        if self.move_dest and me:
            a = self.world_to_minimap(me.x, me.z)
            b = self.world_to_minimap(*self.move_dest)
            pygame.draw.line(surf, MOVE_COLOR_UI, a, b, 1)
            pygame.draw.circle(surf, MOVE_COLOR_UI, b, 3)
        if self.click_marker and time.time() - self.click_marker[2] < 0.45:
            k = (time.time() - self.click_marker[2]) / 0.45
            p = self.world_to_minimap(self.click_marker[0], self.click_marker[1])
            pygame.draw.circle(surf, MOVE_COLOR_UI, p, int(9 - 6 * k), 1)
        rngi = getattr(self, "ind_range", None)
        if rngi:
            ix, iz, ir, ic = rngi
            col8 = tuple(int(v * 255) for v in ic)
            rect = self.minimap_ellipse(ix, iz, ir)
            ov = pygame.Surface(rect.size, pygame.SRCALPHA) if rect.w > 1 and rect.h > 1 else None
            if ov:
                pygame.draw.ellipse(ov, (*col8, 45), ov.get_rect())
                pygame.draw.ellipse(ov, (*col8, 230), ov.get_rect(), 1)
                surf.set_clip(MINIMAP.inflate(-4, -4))
                surf.blit(ov, rect.topleft)
                surf.set_clip(None)
        cam = self.app.renderer.camera
        a = self.world_to_minimap(cam.tx - 14, cam.tz - 8)
        b = self.world_to_minimap(cam.tx + 14, cam.tz + 8)
        pygame.draw.rect(surf, (220, 220, 230), (a[0], a[1], b[0] - a[0], b[1] - a[1]), 1)

    # ---- 상점
    def shop_panel(self):
        return pygame.Rect(WIDTH // 2 - 480, 36, 960, 548)

    def draw_shop(self, surf):
        """롤식 상점: 왼쪽 신발 칸, 가운데 아이템 목록, 오른쪽 고른 아이템의 정보·조합 트리·구매 버튼.

        좌클릭으로 고르고(오른쪽에 표시) 구매 버튼으로 사며, 우클릭은 바로 산다. 오른쪽 트리의 재료도 같은 방식으로 살 수 있다.
        """
        me = self.me
        p = self.shop_panel()
        ui.panel(surf, p, (12, 18, 30, 245), ui.BORDER)
        ui.text(surf, "상점", (p.x + 20, p.y + 14), 24, bold=True)
        can = bool(me and me.get("shop"))
        if not can:
            ui.text(surf, "우물 / 사망 시 구매 가능", (p.x + 90, p.y + 22), 14, ui.RED_C)
        if me:
            ui.text(surf, f"{me['g']} G", (p.right - 20, p.y + 16), 22, ui.GOLD, anchor="topright", bold=True)
        self.shop_rects = []
        self.shop_buy_rect = None
        self.shop_undo_rect = None
        self.shop_tip = None
        mouse = ui.mouse_pos()
        its = gamedata.items()
        owned = list(me["it"]) if me else []
        gold = me["g"] if me else 0
        tier1 = [i for i, it in its.items() if it.get("tier", 1) == 1 and not it.get("boots")]
        boots = [i for i, it in its.items() if it.get("boots")]
        tier2 = [i for i, it in its.items() if it.get("tier", 1) >= 2 and not it.get("boots")]
        if self.shop_view not in its:
            self.shop_view = tier2[0] if tier2 else next(iter(its))
        if self.shop_sel not in its:
            self.shop_sel = self.shop_view
        sel = self.shop_sel
        top = p.y + 56

        # 왼쪽: 신발 (하나만 살 수 있다)
        bx = pygame.Rect(p.x + 14, top, 196, p.bottom - top - 14)
        ui.panel(surf, bx, (16, 24, 40, 235), (60, 75, 105), radius=6)
        ui.text(surf, "신발", (bx.x + 12, bx.y + 10), 15, ui.GOLD, bold=True)
        y = bx.y + 38
        for iid in boots:
            rect = pygame.Rect(bx.x + 8, y, bx.width - 16, 50)
            self.draw_shop_entry(surf, rect, iid, owned, gold, mouse, sel, row=True)
            y += 56
        # 되돌리기 (롤처럼 상점 왼쪽 아래)
        ub = pygame.Rect(bx.x + 8, bx.bottom - 54, bx.width - 16, 44)
        uok = can and bool(me and me.get("ud"))
        uhover = ub.collidepoint(mouse)
        pygame.draw.rect(surf, ((70, 90, 130) if uhover else (52, 68, 102)) if uok else (40, 44, 56), ub, border_radius=6)
        pygame.draw.rect(surf, ui.HIGHLIGHT if uok and uhover else ui.BORDER, ub, 1, border_radius=6)
        ui.text(surf, "되돌리기", ub.center, 16, ui.TEXT if uok else ui.TEXT_DIM, anchor="center", bold=True)
        self.shop_undo_rect = ub

        # 가운데: 아이템 목록 (아이콘 + 가격)
        mid = pygame.Rect(bx.right + 10, top, 408, p.bottom - top - 14)
        ui.panel(surf, mid, (16, 24, 40, 235), (60, 75, 105), radius=6)
        cell_w, cell_h, cols = 66, 84, 6
        y = mid.y + 10
        for title, ids in (("기본 아이템", tier1), ("상위 아이템", tier2)):
            ui.text(surf, title, (mid.x + 12, y), 15, ui.GOLD, bold=True)
            y += 28
            for k, iid in enumerate(ids):
                rect = pygame.Rect(mid.x + 6 + (k % cols) * cell_w, y + (k // cols) * cell_h, cell_w - 4, cell_h - 6)
                self.draw_shop_entry(surf, rect, iid, owned, gold, mouse, sel)
            y += ((len(ids) + cols - 1) // cols) * cell_h + 12

        # 오른쪽: 고른 아이템
        area = pygame.Rect(mid.right + 10, top, p.right - mid.right - 24, p.bottom - top - 14)
        self.draw_shop_detail(surf, area, self.shop_view, sel, owned, gold, can, mouse)

        # 마우스를 올린 아이템 정보 (이름 · 가격 · 능력치 · 판매 가격)
        hov = next((iid for iid, r, _nav in self.shop_rects if r.collidepoint(mouse)), None)
        if hov:
            self.shop_tip = (mouse, hov, owned)

    def draw_shop_entry(self, surf, rect, iid, owned, gold, mouse, sel, row=False):
        """상점의 아이템 칸 하나. row=True 면 아이콘 + 이름 + 가격 한 줄, 아니면 아이콘 + 가격."""
        it = gamedata.items()[iid]
        allowed, used, price, _why = gamedata.can_buy(owned, iid, INVENTORY_SLOTS)
        ok = allowed and gold >= price
        hover = rect.collidepoint(mouse)
        chosen = iid == sel
        bg = (50, 74, 115, 245) if chosen else ((36, 52, 82, 240) if hover else (22, 32, 50, 230))
        ui.panel(surf, rect, bg, ui.GOLD if chosen else (ui.HIGHLIGHT if hover else ui.BORDER), radius=5)
        size = 38 if row else 48
        ir = pygame.Rect(0, 0, size, size)
        if row:
            ir.midleft = (rect.x + 6, rect.centery)
        else:
            ir.midtop = (rect.centerx, rect.y + 6)
        draw_item(surf, iid, ir)
        if not ok:
            dim = pygame.Surface(ir.size, pygame.SRCALPHA)
            dim.fill((0, 0, 0, 110))
            surf.blit(dim, ir.topleft)
        pc = ui.GOLD if ok else (150, 110, 90)
        if row:
            ui.text(surf, it["name"], (ir.right + 8, rect.y + 7), 13, ui.TEXT if ok else ui.TEXT_DIM, bold=True)
            ui.text(surf, f"{price} G", (ir.right + 8, rect.y + 27), 13, pc)
            if not allowed:
                ui.text(surf, "보유 중", (rect.right - 6, rect.y + 28), 11, (230, 120, 100), anchor="topright", shadow=False)
        else:
            ui.text(surf, f"{price}", (rect.centerx, ir.bottom + 5), 13, pc, anchor="midtop")
        if used and allowed:                       # 가진 재료가 쓰인다 (그만큼 싸짐)
            pygame.draw.circle(surf, (110, 220, 130), (ir.right - 4, ir.y + 4), 4)
        self.shop_rects.append((iid, rect, True))

    def draw_shop_detail(self, surf, area, view, sel, owned, gold, can, mouse):
        """오른쪽 창: 위에 고른 아이템(sel)의 이름·가격·능력치, 가운데에 view 아이템의 조합 트리와 상위 아이템, 아래에 구매 버튼.

        트리 안의 재료를 누르면 트리(view)는 그대로 두고 그 재료만 골라진다 (구매 버튼으로 산다).
        """
        its = gamedata.items()
        it = its[sel]
        ui.panel(surf, area, (16, 24, 40, 235), (60, 75, 105), radius=6)
        x, y = area.x + 12, area.y + 12
        draw_item(surf, sel, (x, y, 52, 52))
        ui.text(surf, it["name"], (x + 62, y + 4), 17, ui.GOLD, bold=True)
        allowed, used, price, _why = gamedata.can_buy(owned, sel, INVENTORY_SLOTS)
        cost_txt = f"{price} G" + (f"  (총 {it['cost']} G)" if price != it["cost"] else "")
        ui.text(surf, cost_txt, (x + 62, y + 30), 14, ui.GOLD if gold >= price else (200, 130, 110))
        ui.text(surf, sell_text(it), (area.right - 12, y + 4), 13, ui.TEXT_DIM, anchor="topright")
        y += 62
        for line in ui.wrap(item_stat_text(it), 13, area.width - 24):
            ui.text(surf, line, (x, y), 13, ui.TEXT)
            y += 18
        y += 10

        # 조합 트리: 위에 view 아이템, 아래에 재료 (가진 재료는 초록 테두리)
        vit = its[view]
        comps = vit.get("from", [])
        pygame.draw.line(surf, (60, 75, 105), (area.x + 10, y), (area.right - 10, y))
        y += 16
        s_top, s_c = 44, 40
        top_r = pygame.Rect(0, 0, s_top, s_top)
        top_r.midtop = (area.centerx, y)
        self.draw_tree_node(surf, top_r, view, view in owned, mouse, sel)
        # 목표 아이템 밑에도 재료처럼 값: 가진 재료를 빼고 지금 내야 하는 가격 (이미 가졌으면 초록)
        _vok, _vused, vprice, _vwhy = gamedata.can_buy(owned, view, INVENTORY_SLOTS)
        vcol = (120, 220, 140) if view in owned else (ui.GOLD if gold >= vprice else (200, 130, 110))
        ui.text(surf, f"{vprice}", (top_r.centerx, top_r.bottom + 4), 12, vcol, anchor="midtop", shadow=False)
        y = top_r.bottom + 26
        if comps:
            n = len(comps)
            gap = 16
            total = n * s_c + (n - 1) * gap
            cy = top_r.bottom + 46
            mid_y = top_r.bottom + 30
            pygame.draw.line(surf, (90, 100, 130), (top_r.centerx, top_r.bottom + 20), (top_r.centerx, mid_y), 2)
            left_items = list(owned)
            for k, c in enumerate(comps):
                r = pygame.Rect(area.centerx - total // 2 + k * (s_c + gap), cy, s_c, s_c)
                have = c in left_items
                if have:
                    left_items.remove(c)
                pygame.draw.line(surf, (90, 100, 130), (r.centerx, mid_y), (r.centerx, r.top), 2)
                pygame.draw.line(surf, (90, 100, 130), (top_r.centerx, mid_y), (r.centerx, mid_y), 2)
                self.draw_tree_node(surf, r, c, have, mouse, sel)
                ui.text(surf, f"{its[c]['cost']}", (r.centerx, r.bottom + 4), 12,
                        (120, 220, 140) if have else ui.GOLD, anchor="midtop", shadow=False)
            y = cy + s_c + 26

        # view 아이템이 재료로 들어가는 상위 아이템 (누르면 그 아이템의 트리로 간다)
        ups = gamedata.upgrades_of(view)
        if ups:
            pygame.draw.line(surf, (60, 75, 105), (area.x + 10, y), (area.right - 10, y))
            y += 10
            ui.text(surf, "상위 아이템", (x, y), 13, ui.TEXT_DIM)
            y += 22
            for k, u in enumerate(ups):
                r = pygame.Rect(x + 3 + (k % 5) * 50, y + 3 + (k // 5) * 50, 38, 38)
                self.draw_tree_node(surf, r, u, False, mouse, sel, nav=True)
            y += ((len(ups) + 4) // 5) * 50

        # 구매 버튼 (돈이 모자라도 살 수 있는 재료가 있으면 켜진다)
        btn = pygame.Rect(area.x + 12, area.bottom - 58, area.width - 24, 46)
        ok = can and bool(gamedata.purchase_plan(owned, sel, gold, INVENTORY_SLOTS))
        hover = btn.collidepoint(mouse)
        col = ((60, 150, 90) if hover else (44, 124, 72)) if ok else (48, 52, 64)
        pygame.draw.rect(surf, col, btn, border_radius=6)
        pygame.draw.rect(surf, ui.HIGHLIGHT if ok and hover else ui.BORDER, btn, 1, border_radius=6)
        ui.text(surf, f"구매   {price} G", btn.center, 18, ui.TEXT if ok else ui.TEXT_DIM, anchor="center", bold=True)
        self.shop_buy_rect = btn

    def draw_item_tooltip(self, surf, mouse, iid, owned):
        """상점 아이템 위에 마우스를 올렸을 때: 이름 · 가격(재료로 깎인 값) · 능력치 · 재료 · 판매 가격."""
        its = gamedata.items()
        it = its[iid]
        _ok, _used, price, _why = gamedata.can_buy(owned, iid, INVENTORY_SLOTS)
        lines = [(it["name"], 15, ui.GOLD, True),
                 (f"{price} G" + (f"  (총 {it['cost']} G)" if price != it["cost"] else ""), 13, ui.GOLD, False)]
        for ln in ui.wrap(item_stat_text(it), 13, 260):
            lines.append((ln, 13, ui.TEXT, False))
        if it.get("from"):
            lines.append((" + ".join(its[c]["name"] for c in it["from"]), 12, ui.TEXT_DIM, False))
        lines.append((sell_text(it), 12, ui.TEXT_DIM, False))
        w = max(ui.font(sz, b).size(t)[0] for t, sz, _c, b in lines) + 24
        h = sum(sz + 7 for _t, sz, _c, _b in lines) + 14
        r = pygame.Rect(mouse[0] + 18, mouse[1] + 18, w, h)
        if r.right > WIDTH - 4:
            r.right = mouse[0] - 10
        if r.bottom > HEIGHT - 4:
            r.bottom = mouse[1] - 10
        ui.panel(surf, r, (12, 18, 30, 248), ui.BORDER, radius=5)
        y = r.y + 8
        for t, sz, col, b in lines:
            ui.text(surf, t, (r.x + 12, y), sz, col, bold=b)
            y += sz + 7

    def draw_tree_node(self, surf, r, iid, have, mouse, sel, nav=False):
        """조합 트리 / 상위 아이템 칸. 누르면 그 아이템을 고르고(nav 면 그 아이템의 트리로 이동), 우클릭하면 바로 산다."""
        hover = r.collidepoint(mouse)
        chosen = iid == sel and self.shop_sel_pos in (None, r.topleft)
        border = ui.GOLD if chosen else ((90, 210, 110) if have else (ui.HIGHLIGHT if hover else (80, 85, 105)))
        pygame.draw.rect(surf, (30, 34, 46), r.inflate(6, 6), border_radius=5)
        pygame.draw.rect(surf, border, r.inflate(6, 6), 2 if hover or chosen or have else 1, border_radius=5)
        draw_item(surf, iid, r)
        if have:
            pygame.draw.circle(surf, (90, 210, 110), (r.right - 2, r.y + 2), 6)
            pygame.draw.lines(surf, (12, 30, 16), False, [(r.right - 5, r.y + 2), (r.right - 3, r.y + 4), (r.right + 1, r.y - 1)], 2)
        self.shop_rects.append((iid, r, nav))

    # ---- 점수판
    def draw_scoreboard(self, surf):
        """Tab 점수판 (롤처럼): 위에 팀 요약, 아래 블루팀은 왼쪽 / 레드팀은 오른쪽에 플레이어별 정보.

        시야와 상관없이 모두 보인다 (레벨, K/D/A, 현상금, CS, 아이템).
        """
        items = gamedata.items()
        per_team = max(sum(1 for c in self.champ_info.values() if c["tm"] == t) for t in (BLUE, RED))
        p = pygame.Rect(WIDTH // 2 - 600, 104, 1200, 82 + per_team * 90)
        ui.panel(surf, p, (10, 14, 24, 238), ui.BORDER)
        mouse = ui.mouse_pos()
        col_w = (p.width - 36) // 2
        cols = {BLUE: p.x + 12, RED: p.x + 24 + col_w}

        # ---- 위쪽 요약: 블루 포탑 | 킬 · 시간 · 킬 | 레드 포탑
        rows_by_team = {team: [self.board[cid] for cid in self.champ_info
                               if self.champ_info[cid]["tm"] == team and cid in self.board] for team in (BLUE, RED)}
        towers = {team: sum(1 for sid, st in self.structs.items()
                            if st["k"] == "turret" and st["tm"] != team and not self.struct_state[sid][2])
                  for team in (BLUE, RED)}
        cy = p.y + 30
        for team in (BLUE, RED):
            col = ui.TEAM_UI[team]
            left = team == BLUE
            x = cols[team] + (12 if left else col_w - 12)
            anchor = "midleft" if left else "midright"
            pygame.draw.rect(surf, col, (x - (0 if left else 4), cy - 10, 4, 20), border_radius=2)
            info = f"포탑 {towers[team]}"
            ix = x + (14 if left else -14)
            ui.text(surf, info, (ix, cy + 1), 15, ui.TEXT_DIM, anchor=anchor)
        mm, ss = divmod(int(self.server_time), 60)
        ui.text(surf, f"{self.score[BLUE]}", (p.centerx - 60, cy), 28, ui.BLUE_C, anchor="center", bold=True)
        ui.text(surf, f"{mm:02d}:{ss:02d}", (p.centerx, cy), 15, ui.TEXT_DIM, anchor="center")
        ui.text(surf, f"{self.score[RED]}", (p.centerx + 60, cy), 28, ui.RED_C, anchor="center", bold=True)
        pygame.draw.line(surf, (40, 50, 70), (p.x + 12, p.y + 58), (p.right - 12, p.y + 58))

        # ---- 플레이어 줄 (팀마다 한 열)
        tip = None
        for team in (BLUE, RED):
            x0 = cols[team]
            y = p.y + 70
            for row_data in rows_by_team[team]:
                cid, lv, k, dth, a, cs, _gold, inv, dead, rt, bounty = row_data[:11]
                spells = row_data[11] if len(row_data) > 11 else DEFAULT_SPELLS
                info = self.champ_info[cid]
                ch = gamedata.champion(info["c"])
                row = pygame.Rect(x0, y, col_w, 84)
                mine = cid == self.my_id
                pygame.draw.rect(surf, (32, 46, 74) if mine else (18, 25, 40), row, border_radius=6)
                pygame.draw.rect(surf, ui.TEAM_UI[team], (row.x, row.y, 4, row.height), border_radius=2)
                if mine:
                    pygame.draw.rect(surf, ui.HIGHLIGHT, row, 1, border_radius=6)
                # 소환사 주문 두 개 (세로). 같은 팀은 재사용 대기 시간도 보인다
                cdd = (self.champs[cid].d or {}).get("cd", {}) if team == self.my_team and cid in self.champs else {}
                for j, (slot, sid) in enumerate(zip(("D", "F"), spells)):
                    sr = pygame.Rect(row.x + 10, row.centery - 33 + j * 34, 32, 32)
                    self.draw_spell_small(surf, sr, sid, cdd.get(slot, 0) if team == self.my_team else 0)
                # 초상화 + 레벨 (사망 시 어둡게 + 부활 시간)
                pc = (row.x + 76, row.centery)
                draw_round_portrait(surf, info["c"], pc, 26, ui.TEAM_UI[team], dead, ch.get("color", (200, 200, 200)))
                if dead:
                    ui.text(surf, f"{math.ceil(rt)}", pc, 18, ui.RED_C, anchor="center", bold=True)
                lvp = (pc[0] + 19, pc[1] + 19)
                pygame.draw.circle(surf, (14, 18, 28), lvp, 10)
                ui.text(surf, str(lv), lvp, 12, anchor="center", bold=True)
                # 이름 / 챔피언
                ui.text(surf, info["n"] + (" (나)" if mine else ""), (row.x + 112, row.centery - 11), 15,
                        ui.TEXT_DIM if dead else ui.TEXT, anchor="midleft", bold=True)
                ui.text(surf, ch["name"], (row.x + 112, row.centery + 12), 12, ui.TEXT_DIM, anchor="midleft")
                # K/D/A 와 그 밑에 현상금, 오른쪽에 CS
                ui.text(surf, f"{k} / {dth} / {a}", (row.x + 258, row.centery - 9), 16, anchor="center", bold=True)
                ui.text(surf, f"현상금 {bounty}", (row.x + 258, row.centery + 13), 12,
                        (240, 150, 70) if bounty else ui.TEXT_DIM, anchor="center", bold=bool(bounty))
                ui.text(surf, f"CS {cs}", (row.x + 334, row.centery), 14, ui.TEXT, anchor="center")
                # 아이템 (인벤토리처럼 4칸 x 2줄)
                for i in range(INVENTORY_SLOTS):
                    iid = inv[i] if i < len(inv) else None
                    ix, iy = row.x + 380 + (i % INV_COLS) * 36, row.y + 7 + (i // INV_COLS) * 36
                    ir = pygame.Rect(ix, iy, 34, 34)
                    pygame.draw.rect(surf, (10, 13, 20), ir, border_radius=4)
                    if iid is not None:
                        draw_item(surf, iid, ir.inflate(-2, -2), 13)
                        if ir.collidepoint(mouse):
                            tip = (items[iid]["name"], ir)
                    pygame.draw.rect(surf, ui.BORDER, ir, 1, border_radius=4)
                y += 90
        if tip:
            name, ir = tip
            w = ui.font(14, True).size(name)[0] + 20
            r = pygame.Rect(ir.centerx - w // 2, ir.y - 30, w, 26)
            ui.panel(surf, r, (12, 18, 30, 250), ui.BORDER, radius=4)
            ui.text(surf, name, r.center, 14, ui.GOLD, anchor="center", bold=True)

    @staticmethod
    def draw_spell_small(surf, rect, sid, cd=0.0):
        """작은 소환사 주문 아이콘. cd > 0 이면 어둡게 덮고 남은 초를 쓴다."""
        icon = ui.icon(f"assets/ui/spells/{sid}.png", rect.w)
        if icon:
            surf.blit(icon, rect)
        else:
            sp = SPELLS.get(sid, {})
            pygame.draw.rect(surf, tuple(c // 2 for c in sp.get("color", (120, 120, 120))), rect, border_radius=5)
            ui.text(surf, sp.get("name", "?")[:1], rect.center, 13, anchor="center", bold=True)
        if cd > 0:
            shade(surf, rect, (0, 0, 0, 165), 5)
            ui.text(surf, f"{math.ceil(cd)}", rect.center, 13, ui.TEXT, anchor="center", bold=True)

    def draw_game_over(self, surf):
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((5, 8, 16, 150))
        surf.blit(shade, (0, 0))
        win = self.winner == self.my_team
        ui.text(surf, "승리" if win else "패배", (WIDTH // 2, HEIGHT // 2 - 40), 96,
                (255, 220, 120) if win else (220, 90, 90), anchor="center", bold=True)
