"""절차적 리그 챔피언: 뼈대 모델 파일 없이 코드로 몸을 만들고 매 프레임 계산(IK 등)으로 움직이는 챔피언.

챔피언 JSON 의 model.rig 에 이름을 적으면 models.new_champ_anim() 이 여기서 만든다.
    "spider"  - 동굴 여왕 거미 (보스러시 DEEP NEST 의 1층 보스를 이식)
    "serpent" - 심연의 이무기 (같은 곳의 2층 보스를 이식: 길을 따라오는 긴 몸 + 코브라 목 + 땅속 잠행)
    "dragon"  - 겁화의 용 (같은 곳의 3층 보스를 이식: 네 다리로 걷는 몸 + 접었다 펴는 날개 + 긴 목)
"""

CHAMP_SCALE = 0.8       # 인게임 챔피언 모델 크기 배율
BIG_SCALE = 0.75        # 몸이 아주 큰 리그(용·이무기)는 여기에 이만큼 더 줄인다
DEATH_SHOW = 2.2        # 죽은 뒤 쓰러진 모습을 보여 주는 시간 (초)
DEATH_FADE = 0.6        # 그중 마지막 몇 초 동안 서서히 사라진다


def make_rig(name, renderer, cache):
    """리그 동작 제어기를 만든다. 메시는 렌더러당 한 번만 만들어 cache 에 둔다."""
    if name == "spider":
        from .spider import SpiderAnim, SpiderAssets
        if "spider" not in cache:
            cache["spider"] = SpiderAssets(renderer)
        return SpiderAnim(cache["spider"])
    if name == "serpent":
        from .serpent import SerpentAnim, SerpentAssets
        if "serpent" not in cache:
            cache["serpent"] = SerpentAssets(renderer)
        return SerpentAnim(cache["serpent"])
    if name == "dragon":
        from .dragon import DragonAnim, DragonAssets
        if "dragon" not in cache:
            cache["dragon"] = DragonAssets(renderer)
        return DragonAnim(cache["dragon"])
    return None
