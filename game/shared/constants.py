"""서버와 클라이언트가 함께 쓰는 상수."""
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "data")
ASSET_DIR = os.path.join(ROOT_DIR, "assets")

DEFAULT_PORT = 5555

TICK_RATE = 30            # 서버 시뮬레이션 틱 (Hz)
SNAPSHOT_EVERY = 2        # N틱마다 스냅샷 전송 (15Hz)

BLUE, RED = 0, 1
TEAM_NAMES = {BLUE: "블루팀", RED: "레드팀"}

MAX_TEAM_SIZE = 3
SELECT_TIME = 40.0        # 챔피언 선택 제한 시간 (초)
FINAL_SELECT_TIME = 5.0   # 모두 확정한 뒤 게임 시작까지 (이 동안 소환사 주문을 바꿀 수 있다)

# ---- 칼바람 규칙 ----
START_LEVEL = 1
MAX_LEVEL = 18
START_GOLD = 1400
PASSIVE_GOLD_PER_SEC = 3.0
PASSIVE_XP_PER_SEC = 2.5
KILL_GOLD = 300
FIRST_BLOOD_BONUS = 100
ASSIST_GOLD_RATIO = 0.5   # 어시스트한 챔피언들이 나눠 갖는 골드 = 처치 기본 골드 × 이 비율
# 롤처럼 처치·어시스트 없이 연달아 죽은 챔피언은 처치 골드가 줄어든다 (죽은 횟수 0, 1, 2, ... 6 이상)
DEATH_STREAK_GOLD = (KILL_GOLD, 274, 220, 176, 140, 112, 100)
# 현상금(제압 골드): 죽지 않고 쌓은 처치(1점)·어시스트(0.5점)가 1점을 넘으면 1점마다 붙는 골드와
# 롤처럼 골드(아이템 + 가진 골드)가 상대 팀 평균보다 많이 앞선 만큼 붙는 골드를 더한다. 합쳐서 최대치까지
BOUNTY_PER_POINT = 100
BOUNTY_MAX = 700
BOUNTY_LEAD_FREE = 500    # 이만큼 앞선 것까지는 현상금이 붙지 않는다
BOUNTY_LEAD_RATIO = 0.15  # 그보다 더 앞선 골드의 이 비율이 현상금
BOUNTY_LEAD_MAX = 400
BOUNTY_ASSIST_POINT = 0.5
ASSIST_WINDOW = 10.0      # 이 시간 안에 피해를 준 아군이 어시스트
XP_SHARE_RANGE = 16.0
MINION_GOLD_RANGE = 14.0  # 막타를 친 챔피언이 없으면(미니언·포탑이 처치) 이 거리 안의 적 챔피언들이 골드를 나눠 갖는다

FIRST_WAVE_TIME = 45.0       # 첫 미니언 웨이브 (환영 인사 → '30초 남았습니다' 안내 → 생성 순서가 되도록)
WAVE_INTERVAL = 30.0
INHIBITOR_RESPAWN = 300.0

FOUNTAIN_RADIUS = 7.5     # 상점 이용 가능 범위
FOUNTAIN_HEAL_PCT = 0.085 # 우물 안 초당 체력/마나 회복 (최대치 비율, 협곡 우물처럼)
RECALL_TIME = 8.0         # 귀환 정신집중 시간 (초): 맵 절반 기준 적 진영에서
RECALL_TIME_HOME = 6.0    # ... 우리 진영(맵 절반 기준 우리 우물 쪽)에서는 더 빠르다
FOUNTAIN_LASER_RADIUS = 9.0
FOUNTAIN_LASER_DPS = 1200.0

# ---- 포탑 (롤 기준) ----
TURRET_PERIOD = 1.2             # 공격 속도 0.833
TURRET_CHAMP_DMG = 152.0        # 포탑 → 챔피언 기본 피해 (+분당 9, 14분에 278 까지, 연속 공격 시 40% 씩 최대 120% 증가)
TURRET_DMG_PER_MIN = 9.0
TURRET_DMG_MAX_MIN = 14.0


def turret_damage(t):
    """경기 시간 t(초)의 포탑 기본 피해."""
    return TURRET_CHAMP_DMG + TURRET_DMG_PER_MIN * min(TURRET_DMG_MAX_MIN, t / 60.0)


# ---- 미니언 (롤 기준, 사거리 100 유닛 = 1) ----
MINION_STATS = {
    #           hp,  ad, 사거리, 공속, 이속, 반경, 골드, 경험치, 원거리
    "melee":  (477, 12.0, 1.1, 1.25, 3.25, 0.45, 21, 60, False),
    "caster": (296, 24.0, 5.5, 0.667, 3.25, 0.40, 14, 30, True),
    "cannon": (912, 41.0, 3.0, 1.00, 3.25, 0.60, 60, 93, True),
    "super":  (1600, 230.0, 1.7, 0.85, 3.25, 0.75, 40, 97, False),
    "spiderling": (80, 0, 3.2, 1.0, 3.3, 0.34, 0, 0, True),      # 거미 여왕 E: 고치에서 나오는 새끼 거미 (거미 여왕과 같은 거미줄 평타)
}
MINION_RESIST = {"super": (100.0, -30.0)}      # (방어력, 마법 저항력), 없으면 0

# ---- 항복 ----
SURRENDER_TIME = 480.0          # 이 시간(초)부터 항복 투표를 열 수 있다
SURRENDER_VOTE_TIME = 60.0
SURRENDER_RETRY = 180.0         # 투표가 부결되면 같은 팀은 이만큼 기다려야 다시 열 수 있다
SURRENDER_RATIO = 2.0 / 3.0     # 팀 사람 중 이 비율 이상이 찬성하면 항복

RELIC_FIRST_SPAWN = 60.0
RELIC_RESPAWN = 40.0
RELIC_HEAL_PCT = 0.15
RELIC_RADIUS = 1.0

# ---- 시야 (롤 100 유닛 = 1) ----
SIGHT = {"champion": 12.0, "minion": 10.0, "turret": 13.0, "inhibitor": 8.0, "nexus": 10.0, "fountain": 14.0,
         "cocoon": 3.0}

# ---- 포탑 방패(골드) ----
TURRET_PLATES = 5         # 포탑 체력을 5칸으로 나눠 한 칸 깎일 때마다 근처 적 챔피언에게 골드
PLATE_GOLD = {"outer": 150, "inner": 120, "nexus_t1": 80, "nexus_t2": 80}
PLATE_SHARE_RANGE = 15.0

INVENTORY_SLOTS = 8
SELL_RATIO = 0.7

FLASH_RANGE = 4.0
FLASH_COOLDOWN = 240.0
MARK_RANGE = 16.0
MARK_SPEED = 25.0
MARK_COOLDOWN = 40.0
MARK_RECAST_TIME = 3.0
MARK_DASH_SPEED = 24.0

# 소환사 주문 (점멸·표식 외)
HEAL_COOLDOWN = 240.0
HEAL_BASE = 80.0              # 회복량 = 기본 + 레벨당 × 레벨
HEAL_PER_LEVEL = 14.0
HEAL_RANGE = 6.0              # 이 거리 안의 가장 체력이 낮은 아군 챔피언도 함께 회복
HEAL_ALLY_RATIO = 0.5         # 아군이 받는 회복량 비율
HEAL_SPEED_PCT = 0.30         # 회복 직후 이동 속도 증가
HEAL_SPEED_TIME = 1.0
GHOST_COOLDOWN = 210.0
GHOST_TIME = 8.0
GHOST_SPEED_PCT = 0.30
BARRIER_COOLDOWN = 180.0
BARRIER_BASE = 100.0          # 보호막 = 기본 + 레벨당 × 레벨
BARRIER_PER_LEVEL = 22.0
BARRIER_TIME = 2.0
CLEANSE_COOLDOWN = 210.0
CLEANSE_IMMUNE = 0.5          # 해제 직후 군중 제어 면역 시간
EXHAUST_COOLDOWN = 210.0
EXHAUST_RANGE = 6.5
EXHAUST_TIME = 2.5
EXHAUST_SLOW = 0.30
EXHAUST_DMG_REDUCE = 0.35     # 탈진한 적이 주는 피해 감소
IGNITE_COOLDOWN = 180.0
IGNITE_RANGE = 6.0
IGNITE_TIME = 5.0
IGNITE_BASE = 50.0            # 총 고정 피해 = 기본 + 레벨당 × 레벨 (지속 시간 동안 나눠서)
IGNITE_PER_LEVEL = 20.0
IGNITE_TICK = 0.5
IGNITE_HEAL_CUT = 0.40        # 점화에 걸린 적의 받는 회복량 감소


def xp_to_next(level):
    """level -> level+1 에 필요한 경험치."""
    return 180 + 100 * level


def kill_bounty(points, gold_lead=0.0):
    """죽지 않고 쌓은 처치·어시스트 점수와 골드 우위 -> 현상금(제압 골드)."""
    streak = max(0.0, (points - 1.0) * BOUNTY_PER_POINT)
    lead = min(BOUNTY_LEAD_MAX, max(0.0, (gold_lead - BOUNTY_LEAD_FREE) * BOUNTY_LEAD_RATIO))
    return int(min(BOUNTY_MAX, streak + lead) // 5 * 5)


def kill_gold(points, death_streak, gold_lead=0.0):
    """챔피언을 처치하면 받는 골드: (연속 사망으로 줄어든 기본 골드, 현상금).

    기본 골드 - KILL_GOLD + 현상금 이 롤 점수판의 현상금 숫자 (연달아 죽으면 마이너스)."""
    base = DEATH_STREAK_GOLD[min(death_streak, len(DEATH_STREAK_GOLD) - 1)]
    return base, kill_bounty(points, gold_lead)


def death_timer(level):
    return 4.0 + level * 1.6

DISCOVERY_PORT = 5556       # 같은 네트워크의 열린 방을 알리는 UDP 방송 포트 (호스트 → 로비 화면)
