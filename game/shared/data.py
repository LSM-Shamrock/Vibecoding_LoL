"""챔피언 / 아이템 데이터 로더 (서버·클라이언트 공용)."""
import glob
import json
import os

from .constants import DATA_DIR

_champions = None
_items = None
_world_models = None


def champions():
    """{champion_id: data} — data/champions/*.json 을 모두 읽는다."""
    global _champions
    if _champions is None:
        _champions = {}
        for path in sorted(glob.glob(os.path.join(DATA_DIR, "champions", "*.json"))):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _champions[data["id"]] = data
    return _champions


def champion(cid):
    return champions().get(cid)


def default_champion_id():
    return next(iter(champions()))


def buy_plan(owned, iid):
    """롤식 아이템 트리: iid(2단계)를 살 때 가진 하위 아이템(from)을 재료로 써서 값을 깎는다.
    반환: (재료로 쓰이는 아이템 id 목록, 지불할 가격). 1단계 아이템은 재료 없이 정가."""
    its = items()
    item = its[iid]
    left = list(owned)
    used = []
    price = item["cost"]
    for comp in item.get("from", []):
        if comp in left:
            left.remove(comp)
            used.append(comp)
            price -= its[comp]["cost"]
    return used, price


def is_boots(iid):
    """신발류(기본 신발 + 그 상위 신발)인가. 신발은 하나만 살 수 있다."""
    return bool(items().get(iid, {}).get("boots"))


def can_buy(owned, iid, slots):
    """(살 수 있는가, 재료 목록, 가격, 이유). 신발은 이미 하나 가졌으면 그 신발을 재료로 쓰는 상위 신발만 살 수 있다.
    신발도 인벤토리 한 칸을 차지하므로, 재료로 빠지는 것을 빼고 slots 칸이 남아 있어야 한다."""
    if iid not in items():
        return False, [], 0, "없는 아이템"
    used, price = buy_plan(owned, iid)
    if is_boots(iid):
        have = [i for i in owned if is_boots(i)]
        if have and not any(b in used for b in have):
            return False, used, price, "신발은 하나만 살 수 있습니다"
    if len(owned) - len(used) >= slots:
        return False, used, price, "인벤토리가 가득 찼습니다"
    return True, used, price, ""


def purchase_plan(owned, iid, gold, slots):
    """구매 버튼을 눌렀을 때 실제로 살 아이템 순서 (롤 상점처럼).
    iid 를 살 돈이 있으면 [iid], 모자라면 아직 없는 재료 중 비싼 것부터 살 수 있는 만큼
    (재료도 못 사면 그 재료의 재료로 내려간다 — 3단계 아이템). 살 게 없으면 []."""
    ok, used, price, _why = can_buy(owned, iid, slots)
    if not ok:
        return []
    if gold >= price:
        return [iid]
    plan, _inv, _left = _plan_parts(owned, iid, gold, slots)
    return plan


def _plan_parts(owned, iid, gold, slots):
    """iid 의 빠진 재료를 살 수 있는 만큼 산다: (구매 순서, 산 뒤 인벤토리, 남은 골드)."""
    its = items()
    _ok, used, _price, _why = can_buy(owned, iid, slots)
    missing = list(its[iid].get("from", []))
    for comp in used:
        missing.remove(comp)
    plan, inv, left = [], list(owned), gold
    for comp in sorted(missing, key=lambda i: -its[i]["cost"]):
        ok2, used2, price2, _ = can_buy(inv, comp, slots)
        if ok2 and left >= price2:
            for u in used2:
                inv.remove(u)
            inv.append(comp)
            left -= price2
            plan.append(comp)
        elif its[comp].get("from"):
            sub, inv, left = _plan_parts(inv, comp, left, slots)
            plan += sub
    return plan, inv, left


def contains(have, iid):
    """have 아이템이 iid 이거나 iid 를 재료로 (몇 단계 아래든) 품고 있는가."""
    if have == iid:
        return True
    return any(contains(c, iid) for c in items().get(have, {}).get("from", []))


def upgrades_of(iid):
    """iid 를 재료로 쓰는 상위 아이템 id 목록."""
    return [i for i, it in items().items() if iid in it.get("from", [])]


def items():
    """{item_id: data} — 입력 순서를 유지한다."""
    global _items
    if _items is None:
        with open(os.path.join(DATA_DIR, "items.json"), encoding="utf-8") as f:
            _items = {it["id"]: it for it in json.load(f)}
    return _items


def world_models():
    global _world_models
    if _world_models is None:
        path = os.path.join(DATA_DIR, "world_models.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _world_models = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        else:
            _world_models = {}
    return _world_models


# ---------------------------------------------------------------- 스킬 데이터 도우미
def rank_value(ab, key, rank, default=0.0):
    """스킬 값: 리스트면 스킬 레벨(rank, 1부터)에 맞는 값, 아니면 그대로."""
    v = ab.get(key, default)
    if isinstance(v, (list, tuple)):
        if not v:
            return default
        return v[max(0, min(len(v) - 1, rank - 1))]
    return v


# 스킬 type 별 조준 방식 (클라이언트의 조준 표시·즉시 시전 여부와 봇 판단에 쓴다)
#   line     방향 지정 (직선)        cone     방향 지정 (부채꼴)
#   ground   바닥 지점 지정          teleport 먼 거리 지점 지정 (미니맵 클릭 가능)
#   circle   누르고 있으면 자기 둘레 범위(radius)를 보여 주고, 떼면 시전 (자기 중심 광역)
#   self     누르면 바로 시전
AIM_BY_TYPE = {
    "volley": "cone", "zone": "ground", "cocoon": "ground", "leap_slam": "ground",
    "spit_pool": "ground", "lunge": "line", "serpent_slam": "ground", "dive": "teleport",
    "tornado": "cone", "wing_sweep": "circle", "sky_dive": "ground",
    "scythe_sweep": "cone", "scythe_throw": "line", "execute": "enemy",
}


def aim_mode(ab):
    return ab.get("aim") or AIM_BY_TYPE.get(ab.get("type"), "line")


def is_instant(ab):
    """키를 누르자마자 시전되는 스킬인가 (조준 불필요)."""
    return aim_mode(ab) == "self"
