"""설정 창 (조작키 / 마우스 / 사운드). 인게임 ESC, 시작 화면·로비·대기실의 설정 버튼이 같은 창을 연다.

앱에 하나만 두고(app.settings_ui) 장면들이 함께 쓴다. 열려 있으면 장면은 입력을 이 창에 먼저 넘기고, 화면 맨 위에 그린다.
"""
import pygame

from . import ui
from .keybinds import ACTIONS

SETTINGS_TABS = [("keys", "조작키"), ("mouse", "마우스"), ("sound", "사운드")]


class SettingsPanel:
    def __init__(self, app):
        self.app = app
        self.open = False
        self.tab = "keys"               # keys(조작키) / mouse(마우스) / sound(사운드)
        self.rebinding = None           # 새 키를 기다리는 행동
        self.rects = []                 # [(종류, rect)] 탭·버튼·키 칸
        self.slider_rects = {}          # 막대 (volume 소리 크기 / sens 마우스 감도)
        self.slider_drag = None         # 끌고 있는 막대

    @property
    def rect(self):
        w, h = 640, 600
        from .app import HEIGHT, WIDTH
        return pygame.Rect(WIDTH // 2 - w // 2, max(10, (HEIGHT - h) // 2 - 10), w, h)

    def surrender_fn(self):
        """인게임이면 항복 투표 함수, 아니면 None."""
        scene = self.app.scene
        if scene is None or getattr(scene, "winner", 0) is not None:
            return None
        return getattr(scene, "request_surrender", None)

    def sfx(self, name):
        self.app.audio.play(name)

    def show(self):
        self.sfx("ui_open")
        self.open = True
        self.rebinding = None
        self.slider_drag = None

    def close(self):
        if self.open:
            self.open = False
            self.rebinding = None
            self.slider_drag = None
            self.sfx("ui_close")

    # ------------------------------------------------------------ 입력
    def handle_event(self, e):
        """열려 있으면 입력을 받아 처리한다 (처리했으면 True — 장면은 그 입력을 쓰지 않는다)."""
        if not self.open:
            return False
        binds = self.app.keybinds
        audio = self.app.audio
        if e.type == pygame.KEYDOWN:
            if self.rebinding:
                if e.key != pygame.K_ESCAPE:
                    binds.assign(self.rebinding, e)
                self.rebinding = None
            elif e.key == pygame.K_ESCAPE:
                self.close()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.rebinding = None
            for kind, rect in self.slider_rects.items():
                if rect.inflate(12, 22).collidepoint(e.pos):
                    self.slider_drag = kind
                    self.set_slider_from_mouse(kind, e.pos[0])
                    return True
            for kind, rect in self.rects:
                if rect.collidepoint(e.pos):
                    if kind == "close":
                        self.close()
                    elif kind.startswith("tab:"):
                        if self.tab != kind[4:]:
                            self.tab = kind[4:]
                            self.sfx("ui_select")
                    elif kind == "surrender":
                        fn = self.surrender_fn()
                        if fn:
                            fn()
                        self.close()
                    elif kind == "reset":
                        binds.reset()
                        self.sfx("ui_click")
                    elif kind == "mute":
                        audio.muted = not audio.muted
                        audio.save_settings()
                        self.sfx("ui_toggle")
                    else:
                        self.rebinding = kind
                        self.sfx("ui_click")
                    break
        elif e.type == pygame.MOUSEMOTION and self.slider_drag:
            self.set_slider_from_mouse(self.slider_drag, e.pos[0])
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.slider_drag:
            kind, self.slider_drag = self.slider_drag, None
            if kind == "volume":
                audio.save_settings()
                self.sfx("ui_confirm")                  # 바꾼 크기로 들려 준다
            else:
                self.app.save_mouse_sens()
        return True

    def set_slider_from_mouse(self, kind, mx):
        from .app import SENS_MAX, SENS_MIN
        r = self.slider_rects.get(kind)
        if r is None:
            return
        k = max(0.0, min(1.0, (mx - r.x) / max(1, r.width)))
        audio = self.app.audio
        if kind == "volume":
            audio.set_volume(k)
            if audio.muted and audio.volume > 0:
                audio.muted = False
        else:
            self.app.set_mouse_sens(SENS_MIN + (SENS_MAX - SENS_MIN) * k)

    # ------------------------------------------------------------ 그리기
    def draw(self, surf):
        if not self.open:
            return
        from .app import HEIGHT, WIDTH
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 140))
        surf.blit(shade, (0, 0))
        p = self.rect
        ui.panel(surf, p, (12, 18, 30, 245), ui.BORDER)
        ui.text(surf, "설정", (p.x + 24, p.y + 16), 22, bold=True)
        mouse = ui.mouse_pos()
        self.rects = []
        self.slider_rects = {}
        # 탭: 왼쪽 세로 목록 (조작키 / 마우스 / 사운드), 오른쪽이 내용
        for i, (tab, label) in enumerate(SETTINGS_TABS):
            tr = pygame.Rect(p.x + 20, p.y + 64 + i * 44, 124, 36)
            on = self.tab == tab
            pygame.draw.rect(surf, (45, 75, 125) if on else ((34, 46, 70) if tr.collidepoint(mouse) else (22, 30, 46)),
                             tr, border_radius=6)
            pygame.draw.rect(surf, ui.HIGHLIGHT if on else ui.BORDER, tr, 1, border_radius=6)
            ui.text(surf, label, tr.center, 16, ui.TEXT if on else ui.TEXT_DIM, anchor="center", bold=on)
            self.rects.append(("tab:" + tab, tr))
        pygame.draw.line(surf, ui.BORDER, (p.x + 160, p.y + 64), (p.x + 160, p.bottom - 20))
        body = pygame.Rect(p.x + 180, p.y + 64, p.right - 24 - (p.x + 180), p.height - 64 - 72)
        if self.tab == "sound":
            self.draw_sound(surf, body, mouse)
        elif self.tab == "mouse":
            self.draw_mouse(surf, body)
        else:
            self.draw_keys(surf, body, mouse)
        buttons = [("close", "닫기", pygame.Rect(p.right - 144, p.bottom - 52, 120, 36))]
        if self.tab == "keys":
            buttons.insert(0, ("reset", "기본값", pygame.Rect(body.x, p.bottom - 52, 120, 36)))
        if self.surrender_fn():
            buttons.append(("surrender", "항복", pygame.Rect(p.x + 20, p.bottom - 52, 124, 36)))
        for kind, label, rect in buttons:
            pygame.draw.rect(surf, (40, 60, 95) if rect.collidepoint(mouse) else (28, 38, 58), rect, border_radius=6)
            pygame.draw.rect(surf, ui.BORDER, rect, 1, border_radius=6)
            ui.text(surf, label, rect.center, 16, anchor="center")
            self.rects.append((kind, rect))

    def draw_keys(self, surf, body, mouse):
        binds = self.app.keybinds
        y = body.y
        for action, label in ACTIONS:
            ui.text(surf, label, (body.x + 6, y + 14), 15, anchor="midleft")
            box = pygame.Rect(body.right - 146, y, 140, 28)
            waiting = self.rebinding == action
            hover = box.collidepoint(mouse)
            pygame.draw.rect(surf, (40, 60, 95) if waiting or hover else (24, 32, 48), box, border_radius=4)
            pygame.draw.rect(surf, ui.HIGHLIGHT if waiting else ui.BORDER, box, 1, border_radius=4)
            ui.text(surf, "키 입력..." if waiting else binds.name(action), box.center, 15,
                    ui.GOLD if waiting else ui.TEXT, anchor="center", bold=not waiting)
            self.rects.append((action, box))
            y += 32

    def draw_slider(self, surf, kind, x, y, k, label, on=True):
        """이름 + 끌 수 있는 막대 + 값 글자. k 는 0~1."""
        track = pygame.Rect(x, y, 300, 14)
        self.slider_rects[kind] = track
        pygame.draw.rect(surf, (24, 32, 48), track, border_radius=6)
        pygame.draw.rect(surf, ui.BORDER, track, 1, border_radius=6)
        fill = pygame.Rect(track.x, track.y, int(track.width * k), track.height)
        if fill.width > 0:
            pygame.draw.rect(surf, (90, 140, 230) if on else (80, 85, 100), fill, border_radius=6)
        pygame.draw.circle(surf, ui.HIGHLIGHT, (track.x + int(track.width * k), track.centery), 8)
        ui.text(surf, label, (track.right + 18, track.centery), 16, anchor="midleft")

    def draw_mouse(self, surf, body):
        from .app import SENS_MAX, SENS_MIN
        y = body.y + 8
        ui.text(surf, "마우스 감도", (body.x + 6, y), 17, bold=True)
        sens = self.app.mouse_sens
        self.draw_slider(surf, "sens", body.x + 6, y + 40, (sens - SENS_MIN) / (SENS_MAX - SENS_MIN), f"{sens:.1f}")

    def draw_sound(self, surf, body, mouse):
        # 효과음 크기: 막대를 끌어서 바꾸고, 아래 버튼으로 끄고 켠다
        audio = self.app.audio
        y = body.y + 8
        ui.text(surf, "효과음 크기", (body.x + 6, y), 17, bold=True)
        shown = 0.0 if audio.muted else audio.volume
        self.draw_slider(surf, "volume", body.x + 6, y + 40, shown, f"{round(shown * 100)}%", not audio.muted)
        mute_box = pygame.Rect(body.x + 6, y + 84, 160, 34)
        pygame.draw.rect(surf, (40, 60, 95) if mute_box.collidepoint(mouse) else (24, 32, 48), mute_box, border_radius=4)
        pygame.draw.rect(surf, ui.BORDER, mute_box, 1, border_radius=4)
        ui.text(surf, "소리 켜기" if audio.muted else "소리 끄기", mute_box.center, 16, anchor="center")
        self.rects.append(("mute", mute_box))


def settings_button(app, rect=None):
    """시작 화면·로비·대기실의 설정 버튼 (기본 자리: 오른쪽 위)."""
    from .app import WIDTH
    return ui.Button(rect or (WIDTH - 130, 16, 110, 38), "설정", app.settings_ui.show, color=(50, 62, 95))
