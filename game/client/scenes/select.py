"""챔피언 선택: 챔피언 목록, 3D 모델 미리보기, 스킬 설명, 확정."""
import math
import time

import pygame

from ...shared import data as gamedata
from ...shared.constants import BLUE, RED, TEAM_NAMES
from ...shared.spells import SPELL_ORDER, SPELLS
from .. import ui
from ..app import WIDTH, Scene
from ..gl import model_matrix
from .game import ability_details, detail_value_x, draw_detail_label, draw_round_portrait, shade

KEYS = ("Q", "W", "E", "R")
SKILL_PANEL = pygame.Rect(24, 548, WIDTH - 48, 150)
ICON = 64                                       # 스킬 아이콘 크기
SPELL_SIZE = 44                                 # 소환사 주문 칸 크기
SPELL_PANEL = pygame.Rect(WIDTH // 2 - 90, 416, 180, 78)
class _PreviewEnt:
    """미리보기용 위치 정보 (절차적 리그의 update 에 넘긴다)."""
    x = 0.0
    z = 0.0

    def __init__(self, f):
        self.f = f


SHOWCASE = ("attack", "Q", "W", "E", "R")       # 선택 화면에서 돌아가며 보여 주는 동작


class SelectScene(Scene):
    def on_enter(self):
        self.deadline = time.time() + (self.app.room or {}).get("select_left", 40)
        self.angle = 0.0
        self.preview = None
        self.pv_anim = {}           # 챔피언 id -> 미리보기 동작 제어기
        self.pv_timer = 1.2         # 다음 동작 시범까지 남은 시간
        self.pv_i = 0
        self.last_left = None       # 마지막으로 소리를 낸 남은 시간(초) — 끝나기 5초 전부터 똑딱 소리
        self.app.audio.play("vo_select")
        self.card_rects = []
        self.btn_lock = ui.Button((WIDTH // 2 - 120, 498, 240, 46), "확정", self.lock, color=(40, 130, 80), size=20)
        # 소환사 주문 두 칸 (D / F). 챔피언을 확정한 뒤에도 게임이 시작되기 전까지 바꿀 수 있다. 칸을 누르면 고를 수 있는 주문 목록이 열린다 — 고른 주문은 이 PC 의 설정으로 저장된다
        cx = WIDTH // 2
        self.spell_rects = {"D": pygame.Rect(cx - 68, 444, SPELL_SIZE, SPELL_SIZE),
                            "F": pygame.Rect(cx + 24, 444, SPELL_SIZE, SPELL_SIZE)}
        self.swap_rect = pygame.Rect(cx - 11, 455, 22, 22)     # 두 칸 사이: 누르면 D/F 주문 자리를 맞바꾼다
        self.picking = None             # 주문 목록이 열려 있는 칸 ("D" / "F")
        self.picker_rects = []          # [(주문 id, rect)]
        self.skill_rects = []           # [(키, rect)] — 마우스를 올리면 상세 설명
        self.send_spells()
        # 처음엔 아무 챔피언도 고르지 않은 상태 (시간이 다 되도록 못 고르면 서버가 기본 챔피언을 정해 준다)

    def me(self):
        room = self.app.room
        if not room:
            return None
        return next((m for m in room["members"] if m["key"] == self.app.my_key), None)

    def pick(self, cid):
        self.preview = cid
        self.app.send({"t": "pick", "champ": cid})
        self.app.models.champion(cid)   # 모델 미리 로드
        self.pv_timer = 1.0
        self.pv_i = 0

    def send_spells(self):
        """고른 소환사 주문을 서버에 알린다 (게임이 시작될 때 이 값으로 들어간다)."""
        self.app.send({"t": "spells", "spells": list(self.app.keybinds.spells)})

    def choose_spell(self, slot, spell):
        self.app.keybinds.set_spell(slot, spell)
        self.send_spells()

    def swap_spells(self):
        self.app.keybinds.swap_spells()
        self.send_spells()

    def lock(self):
        me = self.me()
        if me and me["champ"] and not me["locked"]:
            self.app.audio.play("ui_lock")
        self.app.send({"t": "lock"})

    def on_message(self, msg):
        if msg.get("t") == "room" and msg.get("phase") == "select":
            self.deadline = time.time() + msg.get("select_left", 0)

    def handle_event(self, e):
        me = self.me()
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.swap_rect.collidepoint(e.pos):
            self.picking = None
            self.app.audio.play("ui_select")
            self.swap_spells()
            return
        if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE and self.picking:
            self.picking = None
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.picking:
            for spell, rect in self.picker_rects:
                if rect.collidepoint(e.pos):
                    self.app.audio.play("ui_select")
                    self.choose_spell(self.picking, spell)
                    self.picking = None
                    return
            slot = next((s for s, r in self.spell_rects.items() if r.collidepoint(e.pos)), None)
            if slot is None:
                self.picking = None                 # 목록 밖을 누르면 닫고, 아래 동작(버튼·카드 클릭)은 그대로 처리
            elif slot == self.picking:
                self.picking = None
                self.app.audio.play("ui_close")
                return
            else:
                self.picking = slot
                self.app.audio.play("ui_toggle")
                return
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            slot = next((s for s, r in self.spell_rects.items() if r.collidepoint(e.pos)), None)
            if slot:
                self.picking = slot
                self.app.audio.play("ui_toggle")
                return
        if self.btn_lock.handle(e):
            return
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and me and not me["locked"]:
            for cid, rect in self.card_rects:
                if rect.collidepoint(e.pos):
                    if cid != self.preview:
                        self.app.audio.play("ui_select")
                    self.pick(cid)
        if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN:
            self.lock()

    def update(self, dt):
        self.angle += dt * 0.6
        ca = self.preview_anim()
        if ca:
            ca.update(dt, None, _PreviewEnt(math.pi / 2 - self.angle))     # 리그는 화면 위치/방향을 받아 움직인다 (원점에서 천천히 돈다)
            self.pv_timer -= dt
            if self.pv_timer <= 0:
                ca.play_key(SHOWCASE[self.pv_i % len(SHOWCASE)])
                self.pv_i += 1
                self.pv_timer = 3.2
        left = max(0, int(self.deadline - time.time()))
        if left <= 5 and left != self.last_left:
            if self.last_left is not None and left > 0:
                self.app.audio.play("ui_tick")
            self.last_left = left
        me = self.me()
        self.btn_lock.enabled = bool(me and me["champ"] and not me["locked"])
        if me and me["locked"]:
            self.btn_lock.label = "확정 완료"

    def preview_anim(self):
        """지금 보고 있는 챔피언의 리그 동작 제어기 (리그가 없으면 None)."""
        if not self.preview:
            return None
        if self.preview not in self.pv_anim:
            self.pv_anim[self.preview] = self.app.models.new_champ_anim(self.preview)
        return self.pv_anim[self.preview]

    def render3d(self):
        r = self.app.renderer
        cam = r.camera
        pca = self.preview_anim() if self.preview else None
        cam.tx, cam.ty, cam.tz = 0.0, 1.2, 0.0
        cam.distance = getattr(pca, "preview_dist", 9.4)         # 몸이 아주 긴 리그(용)는 카메라를 더 뒤로
        cam.pitch = math.radians(12)
        cam.yaw = math.pi / 2                  # 길을 따라 바라본다 (옆에서 보면 맵 가장자리 기둥이 챔피언을 가린다)
        r.begin_3d(cam, clear=(0.07, 0.1, 0.17))
        models = self.app.models
        r.draw(models.map, model_matrix(0, -0.02, 0))
        r.draw_transparent(models.disc, model_matrix(0, 0.02, 0, scale=1.4), (0.4, 0.7, 1.0, 0.35))
        r.draw_transparent(models.ring, model_matrix(0, 0.03, 0, scale=1.5), (0.6, 0.85, 1.0, 0.8), additive=True)
        if self.preview:
            ca = self.preview_anim()
            bob = 0.0 if ca else math.sin(self.app.time * 2) * 0.02
            if ca:
                ca.draw(r)
            else:
                r.draw(models.champion(self.preview), model_matrix(0, bob, 0, rot_y=self.angle))

    def draw_ui(self, surf):
        room = self.app.room
        if not room:
            return
        left = max(0, int(self.deadline - time.time()))
        all_locked = bool(room["members"]) and all(m["locked"] for m in room["members"])
        me = self.me()
        if all_locked:
            title = "곧 게임이 시작됩니다"
        elif me and me["locked"]:
            title = "다른 플레이어를 기다리는 중"
        else:
            title = "챔피언을 선택하세요"
        ui.text(surf, title, (WIDTH // 2, 36), 30, anchor="center", bold=True)
        ui.text(surf, f"{left}", (WIDTH // 2, 80), 34, ui.GOLD if left > 10 else ui.RED_C, anchor="center", bold=True)

        # 가운데 위: 챔피언 목록 (초상화 칸)
        self.card_rects = []
        champs = gamedata.champions()
        tile_w, tile_h, cols = 92, 112, 6
        n = len(champs)
        rows = max(1, (n + cols - 1) // cols)
        per_row = min(cols, max(1, n))
        grid = pygame.Rect(0, 0, per_row * tile_w + 24, rows * tile_h + 16)
        grid.midtop = (WIDTH // 2, 104)
        ui.panel(surf, grid, (12, 18, 30, 215), ui.BORDER)
        mouse = ui.mouse_pos()
        taken = {m["champ"] for m in room["members"]
                 if me and m["team"] == me["team"] and m["key"] != me["key"] and m["champ"]}
        for i, (cid, ch) in enumerate(champs.items()):
            r_, c_ = divmod(i, cols)
            in_row = min(cols, n - r_ * cols)
            x0 = WIDTH // 2 - in_row * tile_w // 2
            rect = pygame.Rect(x0 + c_ * tile_w + 4, grid.y + 8 + r_ * tile_h, tile_w - 8, tile_h - 8)
            sel = bool(me and me["champ"] == cid)
            hover = rect.collidepoint(mouse)
            pr = pygame.Rect(0, 0, 72, 72)
            pr.midtop = (rect.centerx, rect.y + 4)
            draw_round_portrait(surf, cid, pr.center, 36, ui.GOLD if sel else (ui.HIGHLIGHT if hover else (110, 120, 145)),
                                cid in taken, tuple(ch.get("color", (200, 200, 200))), ring_w=3 if sel else 2)
            ui.text(surf, ch["name"], (rect.centerx, pr.bottom + 6), 14, ui.GOLD if sel else ui.TEXT, anchor="midtop", bold=sel)
            self.card_rects.append((cid, rect))

        # 왼쪽: 우리 팀, 오른쪽: 상대 팀 (고른 챔피언 · 이름 · 소환사 주문)
        my_team = me["team"] if me else BLUE
        for team, panel in ((my_team, pygame.Rect(24, 24, 300, 520)),
                            (RED if my_team == BLUE else BLUE, pygame.Rect(WIDTH - 324, 24, 300, 520))):
            self.draw_team_panel(surf, panel, team, room, team == my_team)

        # 스킬: 아이콘과 이름만 보여 주고, 마우스를 올리면 자세한 설명이 뜬다
        mouse = ui.mouse_pos()
        tooltip = None
        self.skill_rects = []
        ch = gamedata.champion(self.preview) if self.preview else None
        if not ch:
            ui.panel(surf, SKILL_PANEL)
        if ch:
            ui.panel(surf, SKILL_PANEL)
            ui.text(surf, f"{ch['name']} - {ch['title']}", (44, 558), 20, bold=True)
            ui.text(surf, ch.get("role", ""), (WIDTH - 44, 563), 14, ui.GOLD, anchor="topright")
            colw = (WIDTH - 88) // 4
            for i, k in enumerate(KEYS):
                ab = ch["abilities"][k]
                x = 44 + i * colw
                rect = pygame.Rect(x, 594, ICON, ICON)
                self.skill_rects.append((k, rect))
                hover = rect.collidepoint(mouse)
                icon = ui.icon(f"assets/ui/skills/{ch['id']}_{k}.png", ICON)
                if icon:
                    surf.blit(icon, rect)
                else:
                    pygame.draw.rect(surf, (50, 80, 130), rect, border_radius=10)
                    ui.text(surf, ab["name"][:2], rect.center, 20, anchor="center", bold=True)
                if hover:
                    shade(surf, rect, (255, 255, 255, 38), 10)
                    pygame.draw.rect(surf, ui.HIGHLIGHT, rect, 2, border_radius=10)
                kr = pygame.Rect(rect.x - 4, rect.y - 4, 20, 20)
                pygame.draw.rect(surf, (14, 20, 34), kr, border_radius=5)
                pygame.draw.rect(surf, ui.GOLD, kr, 1, border_radius=5)
                ui.text(surf, k, kr.center, 13, ui.GOLD, anchor="center", bold=True, shadow=False)
                ui.text(surf, ab["name"], (x + ICON + 12, 602), 17, ui.GOLD if hover else ui.TEXT, bold=True)
                cds = ab.get("cooldown", [])
                if cds:
                    cd = f"{cds[0]:g}" if len(set(cds)) == 1 else f"{cds[0]:g}~{cds[-1]:g}"
                    ui.text(surf, f"재사용 {cd}초", (x + ICON + 12, 628), 13, ui.TEXT_DIM)
                if hover:
                    tooltip = ("skill", k, ab, rect)

        self.btn_lock.draw(surf)

        # 소환사 주문 두 칸 (칸을 누르면 고를 수 있는 목록이 열린다)
        binds = self.app.keybinds
        cx = WIDTH // 2
        ui.panel(surf, SPELL_PANEL, (12, 18, 30, 215), ui.BORDER)
        ui.text(surf, "소환사 주문", (cx, 430), 13, ui.TEXT_DIM, anchor="center")
        for slot, rect in self.spell_rects.items():
            sid = binds.spell_at(slot)
            hover = rect.collidepoint(mouse)
            self.draw_spell_icon(surf, rect, sid, hover or self.picking == slot)
            ui.text(surf, binds.name(slot), (rect.x + 4, rect.y + 1), 12, ui.GOLD, bold=True)
            if rect.collidepoint(mouse) and not self.picking:
                tooltip = ("spell", sid, None, SPELL_PANEL, "above")
        self.draw_swap(surf, mouse)
        if self.swap_rect.collidepoint(mouse) and not self.picking:
            tooltip = None
        self.picker_rects = []
        if self.picking:
            tooltip = self.draw_picker(surf, mouse) or tooltip
        if tooltip:
            self.draw_tooltip(surf, tooltip)

    def draw_team_panel(self, surf, panel, team, room, ally):
        """팀 한쪽 목록: 플레이어마다 고른 챔피언 초상화(아직 안 골랐으면 빈 원), 이름, 챔피언 이름, 소환사 주문 (우리 팀만, 상대는 이름만).
        확정한 플레이어는 테두리가 팀 색으로 밝고, 고르는 중이면 흐리다."""
        ui.panel(surf, panel, (12, 18, 30, 220), ui.BORDER)
        col = ui.TEAM_UI[team]
        ui.text(surf, TEAM_NAMES[team], (panel.x + 18, panel.y + 14), 18, col, bold=True)
        members = [m for m in room["members"] if m["team"] == team]
        h = min(104, (panel.height - 56) // max(1, len(members)))
        y = panel.y + 48
        for m in members:
            card = pygame.Rect(panel.x + 10, y, panel.width - 20, h - 8)
            mine = m["key"] == self.app.my_key
            ui.panel(surf, card, (32, 46, 74, 235) if mine else (20, 28, 44, 230),
                     col if m["locked"] else (ui.HIGHLIGHT if mine else ui.BORDER), radius=8)
            pc = (card.x + 12 + 34, card.centery)
            if m["champ"] and ally:                     # 상대 팀이 고른 챔피언은 보이지 않는다 (빈 칸만)
                chd = gamedata.champion(m["champ"]) or {}
                draw_round_portrait(surf, m["champ"], pc, 34, col if m["locked"] else (120, 130, 150), False,
                                    tuple(chd.get("color", (200, 200, 200))), ring_w=3 if m["locked"] else 2)
                if not m["locked"]:
                    shade(surf, pygame.Rect(pc[0] - 34, pc[1] - 34, 68, 68), (0, 0, 0, 90), 34)
                cname = chd.get("name", "")
            else:
                pygame.draw.circle(surf, (14, 18, 28), pc, 34)
                pygame.draw.circle(surf, (80, 90, 110), pc, 34, 2)
                cname = "선택 중..." if ally else ""
            tx = pc[0] + 46
            ui.text(surf, m["name"] + (" (나)" if mine else ""), (tx, card.centery - (12 if cname else 0)), 15,
                    ui.GOLD if mine else ui.TEXT, anchor="midleft", bold=True)
            if cname:
                ui.text(surf, cname, (tx, card.centery + 12), 13, ui.TEXT if m["locked"] else ui.TEXT_DIM, anchor="midleft")
            if ally:                                    # 같은 팀만 소환사 주문이 보인다 (내 것은 지금 고른 것)
                spells = self.app.keybinds.spells if mine else m.get("spells") or []
                for j, sid in enumerate(spells[:2]):
                    sr = pygame.Rect(card.right - 34, card.centery - 31 + j * 32, 28, 28)
                    self.draw_spell_icon(surf, sr, sid)
            y += h

    def draw_swap(self, surf, mouse):
        """두 주문 칸 사이의 자리 바꾸기 버튼 (좌우 화살표)."""
        r = self.swap_rect
        hover = r.collidepoint(mouse)
        pygame.draw.rect(surf, (40, 60, 95) if hover else (22, 32, 52), r, border_radius=6)
        pygame.draw.rect(surf, ui.HIGHLIGHT if hover else ui.BORDER, r, 1, border_radius=6)
        col = ui.GOLD if hover else (190, 200, 215)
        cx, cy = r.center
        for dy, d in ((-4, 1), (4, -1)):               # 위: 오른쪽 화살표, 아래: 왼쪽 화살표
            y = cy + dy
            pygame.draw.line(surf, col, (cx - 6, y), (cx + 6, y), 2)
            tip = cx + 6 * d
            pygame.draw.polygon(surf, col, [(tip + 2 * d, y), (tip - 3 * d, y - 3), (tip - 3 * d, y + 3)])

    def draw_spell_icon(self, surf, rect, sid, highlight=False):
        sp = SPELLS[sid]
        icon = ui.icon(f"assets/ui/spells/{sid}.png", rect.w)
        if icon:
            surf.blit(icon, rect)
        else:
            pygame.draw.rect(surf, tuple(c // 2 for c in sp["color"]), rect, border_radius=8)
            ui.text(surf, sp["name"], rect.center, 14, anchor="center", bold=True)
        if highlight:
            shade(surf, rect, (255, 255, 255, 34), 9)
            pygame.draw.rect(surf, ui.HIGHLIGHT, rect, 2, border_radius=9)

    def draw_picker(self, surf, mouse):
        """소환사 주문 고르기 목록. 마우스가 올라간 주문의 툴팁 정보를 돌려준다."""
        cols, gap = 4, 8
        w = cols * SPELL_SIZE + (cols + 1) * gap
        rows = (len(SPELL_ORDER) + cols - 1) // cols
        h = rows * SPELL_SIZE + (rows + 1) * gap + 22
        slot_rect = self.spell_rects[self.picking]
        panel = pygame.Rect(0, 0, w, h)
        panel.midbottom = (WIDTH // 2, SPELL_PANEL.top - 8)
        ui.panel(surf, panel, (12, 18, 30, 248), ui.BORDER)
        ui.text(surf, f"{self.app.keybinds.name(self.picking)} 칸에 넣을 주문", (panel.centerx, panel.y + 12), 13,
                ui.TEXT_DIM, anchor="center")
        cur = self.app.keybinds.spell_at(self.picking)
        other = self.app.keybinds.spell_at("F" if self.picking == "D" else "D")
        tip = None
        for i, sid in enumerate(SPELL_ORDER):
            rect = pygame.Rect(panel.x + gap + (i % cols) * (SPELL_SIZE + gap),
                               panel.y + 22 + gap + (i // cols) * (SPELL_SIZE + gap), SPELL_SIZE, SPELL_SIZE)
            hover = rect.collidepoint(mouse)
            self.draw_spell_icon(surf, rect, sid, hover)
            if sid == cur:
                pygame.draw.rect(surf, ui.GOLD, rect.inflate(4, 4), 2, border_radius=10)
            elif sid == other:
                shade(surf, rect, (0, 0, 0, 120), 9)           # 다른 칸에서 쓰는 주문 (고르면 자리가 바뀐다)
            self.picker_rects.append((sid, rect))
            if hover:
                tip = ("spell", sid, None, panel, "right")
        _ = slot_rect
        return tip

    # ------------------------------------------------------------------ 툴팁
    def draw_tooltip(self, surf, tip):
        kind, key, ab, anchor = tip[:4]
        side = tip[4] if len(tip) > 4 else "above"
        if kind == "skill":
            title = f"[{key}] {ab['name']}"
            desc = ab.get("desc", "")
            rows = [(label, " / ".join(v) if isinstance(v, list) else v) for label, v in ability_details(ab)]
        else:
            sp = SPELLS[key]
            title, desc, rows = sp["name"], sp["desc"], sp["details"]
        w, pad, lh = 460, 12, 19
        lines = ui.wrap(desc, 14, w - 2 * pad)
        h = pad + 22 + len(lines) * lh + (10 + len(rows) * 20 if rows else 0) + pad
        r = pygame.Rect(0, 0, w, h)
        if side == "right":                 # 주문 목록 옆에 (목록을 가리지 않게)
            r.bottomleft = (anchor.right + 10, anchor.bottom)
        else:
            r.midbottom = (anchor.centerx, anchor.top - 10)
        if kind == "skill":
            r.x = max(8, min(WIDTH - w - 8, anchor.x))
        r.x = max(8, min(WIDTH - w - 8, r.x))
        if r.y < 8:
            r.y = 8
        ui.panel(surf, r, (10, 15, 26, 250), ui.HIGHLIGHT)
        ui.text(surf, title, (r.x + pad, r.y + pad - 2), 17, ui.GOLD, bold=True)
        y = r.y + pad + 24
        for ln in lines:
            ui.text(surf, ln, (r.x + pad, y), 14, ui.TEXT, shadow=False)
            y += lh
        if rows:
            y += 4
            pygame.draw.line(surf, (50, 60, 80), (r.x + pad, y), (r.right - pad, y))
            y += 6
            vx = detail_value_x(rows)
            for label, value in rows:
                draw_detail_label(surf, label, (r.x + pad, y), 13)
                ui.text(surf, value, (r.x + pad + vx, y), 13, ui.TEXT, shadow=False)
                y += 20
