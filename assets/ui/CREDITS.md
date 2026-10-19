# 아이콘 출처

스킬·소환사 주문·능력치 아이콘의 그림 모양은 **game-icons.net** (https://game-icons.net) 의 아이콘입니다.
작가는 **Lorc**, **Delapouite**, **sbed** 이고, 라이선스는 **CC BY 3.0** (https://creativecommons.org/licenses/by/3.0/) 입니다.
이 라이선스는 출처(작가와 사이트 이름)를 밝히면 자유롭게 쓰고 고쳐 쓸 수 있게 합니다. 이 게임에서는 원본 SVG 에
색을 입히고 둥근 사각형 배경과 테두리를 붙여 PNG 로 만들었습니다 (`tools/build_icons.py`).

> Icons by Lorc, Delapouite and sbed — https://game-icons.net — licensed under CC BY 3.0.

아이콘을 바꾸려면 `tools/build_icons.py` 위쪽의 표에서 "작가/아이콘 이름" 만 고치고 다시 실행하세요 (README 참고).

## 챔피언 스킬 (`assets/ui/skills/<챔피언>_<키>.png`)

| 챔피언 | 키 | 스킬 | 아이콘 (작가) |
|---|---|---|---|
| 거미 여왕 | Q | 독침 뿌리기 | [divergence](https://game-icons.net/1x1/lorc/divergence.html) — Lorc |
| 거미 여왕 | W | 거미줄 장판 | [spider-web](https://game-icons.net/1x1/lorc/spider-web.html) — Lorc |
| 거미 여왕 | E | 새끼 거미 고치 | [big-egg](https://game-icons.net/1x1/sbed/big-egg.html) — sbed |
| 거미 여왕 | R | 덮쳐 내려찍기 | [spider-alt](https://game-icons.net/1x1/carl-olsen/spider-alt.html) — Carl Olsen (거미 그림만 사용, 점프 궤적·착지 표시는 직접 그림) |
| 이무기 | Q | 독 뱉기 | [droplet-splash](https://game-icons.net/1x1/lorc/droplet-splash.html) — Lorc |
| 이무기 | W | 일직선 돌진 | [bestial-fangs](https://game-icons.net/1x1/lorc/bestial-fangs.html) — Lorc |
| 이무기 | E | 내려찍기 | [earth-spit](https://game-icons.net/1x1/lorc/earth-spit.html) — Lorc |
| 이무기 | R | 잠행 | [sea-serpent](https://game-icons.net/1x1/lorc/sea-serpent.html) — Lorc (뱀 그림만 사용, 가라앉는 효과·물결은 직접 그림) |
| 용 | Q | 화염 뱉기 | [fire-zone](https://game-icons.net/1x1/lorc/fire-zone.html) — Lorc |
| 용 | W | 날개 돌풍 | [wind-slap](https://game-icons.net/1x1/lorc/wind-slap.html) — Lorc |
| 용 | E | 날개 후려치기 | [bat-wing](https://game-icons.net/1x1/lorc/bat-wing.html) — Lorc |
| 용 | R | 유성우 | [burning-meteor](https://game-icons.net/1x1/lorc/burning-meteor.html) — Lorc |

## 소환사 주문 (`assets/ui/spells/<이름>.png`)

| 주문 | 아이콘 (작가) |
|---|---|
| 점멸 (`flash`) | 직접 그림 (`tools/build_icons.py` 의 `flash_blink`: 번쩍이는 별 + 빛줄기) |
| 표식 (`mark`) | [frozen-orb](https://game-icons.net/1x1/lorc/frozen-orb.html) — Lorc |
| 회복 (`heal`) | [health-increase](https://game-icons.net/1x1/sbed/health-increase.html) — sbed |
| 유체화 (`ghost`) | [ghost](https://game-icons.net/1x1/lorc/ghost.html) — Lorc |
| 방어막 (`barrier`) | [bordered-shield](https://game-icons.net/1x1/lorc/bordered-shield.html) — Lorc |
| 정화 (`cleanse`) | [holy-water](https://game-icons.net/1x1/delapouite/holy-water.html) — Delapouite |
| 탈진 (`exhaust`) | [snail](https://game-icons.net/1x1/lorc/snail.html) — Lorc |
| 점화 (`ignite`) | [fire-spell-cast](https://game-icons.net/1x1/delapouite/fire-spell-cast.html) — Delapouite |

## 능력치 (`assets/ui/stats/<키>.png`)

단순한 평면 아이콘으로 직접 그렸습니다 (`tools/build_icons.py` 의 `simple_stat`): 공격력 칼, 주문력 별, 방어력 방패,
마법 저항력 테두리 방패 + 구슬, 공격 속도 », 이동 속도 장화, 스킬 가속 모래시계, 치명타 조준경.

## 마우스 커서 (`assets/ui/cursors/*.png`, `tools/build_cursors.py`)

| 커서 | 쓰는 때 | 아이콘 (작가) |
|---|---|---|
| `default` | 평상시 (손가락으로 가리키는 손) | [hand-pointing](https://phosphoricons.com) — Phosphor Icons (MIT 라이선스, https://github.com/phosphor-icons/core) |
| `attack` | 공격할 수 있는 대상 위 | [broadsword](https://game-icons.net/1x1/lorc/broadsword.html) — Lorc |
| `target` | 대상 지정 스킬 조준 중 | [crosshair](https://game-icons.net/1x1/delapouite/crosshair.html) — Delapouite |
