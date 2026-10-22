"""pygame 2D UI: 폰트, 텍스트, 버튼, 입력창."""
import os
import sys

import pygame

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "fonts")
# 게임에 같이 들어 있는 Noto Sans KR (OFL). 맑은 고딕은 작은 크기에서 ㅏ·ㅓ 세로 획이 사라지는 문제가 있어 맨 뒤 대체용.
FONT_CANDIDATES = [
    os.path.join(_FONT_DIR, "NotoSansKR-Regular.otf"),
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
BOLD_CANDIDATES = [os.path.join(_FONT_DIR, "NotoSansKR-Bold.otf"), r"C:\Windows\Fonts\malgunbd.ttf"]

# 색상 테마
BG = (12, 18, 32)
PANEL = (18, 28, 48, 225)
PANEL_LIGHT = (30, 46, 74, 235)
BORDER = (0, 0, 0)
HIGHLIGHT = (235, 240, 250)      # 선택/포커스 테두리
GOLD = (230, 200, 120)
TEXT = (225, 235, 250)
TEXT_DIM = (140, 160, 190)
BLUE_C = (80, 150, 255)
RED_C = (255, 90, 85)
GREEN_C = (90, 220, 110)
TEAM_UI = {0: BLUE_C, 1: RED_C}

_fonts = {}
_text_cache = {}
_mouse_mapper = None
_mouse_source = None
_sfx = None
_hot = None         # 마우스가 올라가 있는 버튼 (자리 기준). 매 프레임 버튼을 새로 만들어도 소리가 반복되지 않게 전역으로 기억


def set_sfx(fn):
    """효과음 재생 함수 연결 (app.audio.play). 버튼 클릭·마우스 올림 소리에 쓴다."""
    global _sfx
    _sfx = fn


def sfx(name, **kw):
    if _sfx:
        _sfx(name, **kw)


def set_mouse_mapper(fn):
    """창 좌표 -> 논리 화면 좌표 변환 함수 (전체 화면 확대 대응)."""
    global _mouse_mapper
    _mouse_mapper = fn


def set_mouse_source(fn):
    """창 좌표 커서 위치를 돌려주는 함수 연결 (인게임 마우스 감도를 적용한 가상 커서)."""
    global _mouse_source
    _mouse_source = fn


def mouse_pos():
    pos = _mouse_source() if _mouse_source else pygame.mouse.get_pos()
    if _mouse_mapper:
        x, y = _mouse_mapper(pos)
        return int(x), int(y)
    return pos


def _font_path(bold):
    for p in (BOLD_CANDIDATES if bold else []) + FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


class _SuperFont:
    """작은 글자용 폰트: 2배 크기로 그린 뒤 절반으로 줄인다.
    말굿 고딕을 작은 크기로 바로 그리면 힌팅 때문에 ㅏ·ㅓ 의 세로 획이 사라져 글자가 깨져 보인다."""
    S = 2

    def __init__(self, path, size, bold):
        if path:
            self.f = pygame.font.Font(path, size * self.S)
        else:
            self.f = pygame.font.SysFont("malgungothic,applegothic,nanumgothic,notosanscjkkr,arial", size * self.S, bold=bold)

    def size(self, s):
        w, h = self.f.size(s)
        return (w + 1) // self.S, (h + 1) // self.S

    def render(self, s, aa, color, *a):
        big = self.f.render(s, True, color)
        w, h = big.get_size()
        if w < self.S:                          # 빈 글자: 0 폭 그림을 줄이면 pygame 이 죽는다
            return pygame.Surface((1, max(1, h // self.S)), pygame.SRCALPHA)
        return pygame.transform.smoothscale(big, (max(1, w // self.S), max(1, h // self.S)))

    def get_height(self):
        return self.f.get_height() // self.S

    def get_linesize(self):
        return self.f.get_linesize() // self.S


def font(size, bold=False):
    key = (size, bold)
    f = _fonts.get(key)
    if f is None:
        path = _font_path(bold)
        if size <= 16:
            f = _SuperFont(path, size, bold)
        elif path:
            f = pygame.font.Font(path, size)
        else:
            f = pygame.font.SysFont("malgungothic,applegothic,nanumgothic,notosanscjkkr,arial", size, bold=bold)
        _fonts[key] = f
    return f


def render_text(s, size=16, color=TEXT, bold=False):
    key = (s, size, color, bold)
    surf = _text_cache.get(key)
    if surf is None:
        if len(_text_cache) > 3000:
            _text_cache.clear()
        surf = font(size, bold).render(str(s), True, color)
        _text_cache[key] = surf
    return surf


def text(surface, s, pos, size=16, color=TEXT, anchor="topleft", bold=False, shadow=True):
    surf = render_text(s, size, color, bold)
    rect = surf.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    if shadow:
        sh = render_text(s, size, (0, 0, 0), bold)
        surface.blit(sh, rect.move(1, 1))
    surface.blit(surf, rect)
    return rect


NO_LINE_START = ",.!?)]}%·、。」』》:;"      # 줄 맨 앞에 오면 보기 싫은 글자 (앞 줄에 붙여 둔다)


def wrap(s, size, width, bold=False):
    f = font(size, bold)
    lines = []
    for para in str(s).split("\n"):
        cur = ""
        for ch in para:
            if f.size(cur + ch)[0] > width and cur and ch not in NO_LINE_START:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def text_block(surface, s, pos, width, size=14, color=TEXT, line_gap=4):
    x, y = pos
    for line in wrap(s, size, width):
        text(surface, line, (x, y), size, color, shadow=False)
        y += size + line_gap
    return y


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_icons = {}


def icon(path, size):
    """프로젝트 기준 경로의 이미지를 size x size 로 읽어 둔다. 파일이 없으면 None."""
    key = (path, size)
    if key not in _icons:
        full = os.path.join(_ROOT, path)
        img = None
        if os.path.exists(full):
            try:
                img = pygame.transform.smoothscale(pygame.image.load(full).convert_alpha(), (size, size))
            except (pygame.error, ValueError):
                img = None
        _icons[key] = img
    return _icons[key]


def panel(surface, rect, color=PANEL, border=BORDER, radius=8, width=1):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, border, rect, width, border_radius=radius)


def bar(surface, rect, ratio, color, back=(20, 20, 28, 220), border=(0, 0, 0)):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, back, rect)
    if ratio > 0:
        r = rect.copy()
        r.width = max(1, int(rect.width * max(0.0, min(1.0, ratio))))
        pygame.draw.rect(surface, color, r)
    if border:
        pygame.draw.rect(surface, border, rect, 1)


class Button:
    def __init__(self, rect, label, on_click, enabled=True, color=(40, 80, 140), size=17, tooltip=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.enabled = enabled
        self.color = color
        self.size = size
        self.tooltip = tooltip
        self.visible = True

    def handle(self, e):
        if not (self.visible and self.enabled):
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.rect.collidepoint(e.pos):
            sfx("ui_click")
            self.on_click()
            return True
        return False

    def draw(self, surface):
        if not self.visible:
            return
        global _hot
        hover = self.rect.collidepoint(mouse_pos())
        key = (self.rect.x, self.rect.y, self.rect.w, self.rect.h)
        if hover:
            if _hot != key:
                _hot = key
                if self.enabled:
                    sfx("ui_hover")
        elif _hot == key:
            _hot = None
        if not self.enabled:
            col = (45, 50, 62)
        elif hover:
            col = tuple(min(255, c + 35) for c in self.color)
        else:
            col = self.color
        pygame.draw.rect(surface, col, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=6)
        text(surface, self.label, self.rect.center, self.size, TEXT if self.enabled else TEXT_DIM, anchor="center")


_clip_buf = [""]      # 클립보드를 쓸 수 없을 때를 위한 게임 안 임시 보관


def clip_get():
    """클립보드의 글자를 읽는다 (윈도우는 직접, 그 외엔 pygame.scrap, 안 되면 게임 안 보관값)."""
    try:
        if sys.platform == "win32":
            import ctypes
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            u32.GetClipboardData.restype = ctypes.c_void_p
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            if u32.OpenClipboard(None):
                try:
                    h = u32.GetClipboardData(13)             # CF_UNICODETEXT
                    if h:
                        p = k32.GlobalLock(h)
                        if p:
                            try:
                                return ctypes.wstring_at(p)
                            finally:
                                k32.GlobalUnlock(h)
                finally:
                    u32.CloseClipboard()
        else:
            import pygame.scrap
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
            if raw:
                return raw.decode("utf-8", "ignore").replace("\x00", "")
    except Exception:
        pass
    return _clip_buf[0]


def clip_set(txt):
    _clip_buf[0] = txt
    try:
        if sys.platform == "win32":
            import ctypes
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            data = (txt + "\0").encode("utf-16-le")
            h = k32.GlobalAlloc(0x0002, len(data))           # GMEM_MOVEABLE
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            if u32.OpenClipboard(None):
                try:
                    u32.EmptyClipboard()
                    u32.SetClipboardData(13, h)
                finally:
                    u32.CloseClipboard()
        else:
            import pygame.scrap
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT, txt.encode("utf-8"))
    except Exception:
        pass


def _is_word_char(ch):
    return ch.isalnum() or ch == "_"


class TextInput:
    """한 줄 입력창: 커서 이동(←→ Home End, 클릭), 선택(Shift+방향키, 드래그, 더블클릭), Ctrl+A/C/V/X, Ctrl+Backspace/Delete, Delete.

    charset 을 주면 그 글자만 입력/붙여넣기 된다 (예: 포트는 숫자만)."""

    def __init__(self, rect, value="", max_len=16, placeholder="", charset=None):
        self.rect = pygame.Rect(rect)
        self.max_len = max_len
        self.placeholder = placeholder
        self.charset = charset
        self.focused = False
        self.composing = ""
        self.value = value
        self.anchor = None          # 선택 시작 (None 이면 선택 없음)
        self.scroll = 0
        self._drag = False
        self._last_click = 0

    # -------------------------------------------------------------- 내용
    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
        self.cursor = len(v)
        self.anchor = None

    def _filter(self, txt):
        txt = txt.replace("\r", "").replace("\n", "").replace("\t", "")
        if self.charset is not None:
            txt = "".join(ch for ch in txt if ch in self.charset)
        return txt

    def sel_range(self):
        if self.anchor is None or self.anchor == self.cursor:
            return None
        return (min(self.anchor, self.cursor), max(self.anchor, self.cursor))

    def delete_selection(self):
        r = self.sel_range()
        self.anchor = None
        if not r:
            return False
        self._value = self._value[:r[0]] + self._value[r[1]:]
        self.cursor = r[0]
        return True

    def insert(self, txt):
        txt = self._filter(txt)
        self.delete_selection()
        room = self.max_len - len(self._value)
        if room <= 0 or not txt:
            return
        txt = txt[:room]
        self._value = self._value[:self.cursor] + txt + self._value[self.cursor:]
        self.cursor += len(txt)

    def select_all(self):
        self.anchor, self.cursor = 0, len(self._value)

    def _move(self, pos, select):
        pos = max(0, min(len(self._value), pos))
        if select:
            if self.anchor is None:
                self.anchor = self.cursor
        else:
            self.anchor = None
        self.cursor = pos

    def _word_left(self, i):
        v = self._value
        while i > 0 and not _is_word_char(v[i - 1]):
            i -= 1
        while i > 0 and _is_word_char(v[i - 1]):
            i -= 1
        return i

    def _word_right(self, i):
        v = self._value
        while i < len(v) and not _is_word_char(v[i]):
            i += 1
        while i < len(v) and _is_word_char(v[i]):
            i += 1
        return i

    def _index_at(self, x):
        """화면 x 좌표에 가장 가까운 글자 사이 위치."""
        rel = x - (self.rect.x + 10) + self.scroll
        f = font(17)
        best, best_d = 0, 1e9
        for i in range(len(self._value) + 1):
            d = abs(f.size(self._value[:i])[0] - rel)
            if d < best_d:
                best, best_d = i, d
        return best

    def _focus(self):
        self.focused = True
        sfx("ui_click")
        pygame.key.start_text_input()
        pygame.key.set_text_input_rect(self.rect)
        pygame.key.set_repeat(380, 35)

    def _blur(self):
        self.focused = False
        self.anchor = None
        self._drag = False
        pygame.key.stop_text_input()
        pygame.key.set_repeat()

    # -------------------------------------------------------------- 이벤트
    def handle(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            was = self.focused
            inside = self.rect.collidepoint(e.pos)
            if inside and not was:
                self._focus()
            elif was and not inside:
                self._blur()
            if inside:
                now = pygame.time.get_ticks()
                if was and now - self._last_click < 350:
                    self.select_all()                       # 더블클릭: 전체 선택
                    self._drag = False
                else:
                    self._move(self._index_at(e.pos[0]), False)
                    self.anchor = self.cursor
                    self._drag = True
                self._last_click = now
            return inside
        if e.type == pygame.MOUSEMOTION and self._drag and self.focused:
            self._move(self._index_at(e.pos[0]), True)
            if self.anchor == self.cursor:
                self.anchor = self.cursor
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if self._drag and self.anchor == self.cursor:
                self.anchor = None
            self._drag = False
            return False
        if not self.focused:
            return False
        if e.type == pygame.TEXTINPUT:
            self.composing = ""
            self.insert(e.text)
            return True
        if e.type == pygame.TEXTEDITING:
            self.composing = e.text
            return True
        if e.type == pygame.KEYDOWN:
            if self.composing:                               # 조합 중인 한글은 입력기에 맡긴다
                return e.key not in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB)
            mods = e.mod
            ctrl = bool(mods & pygame.KMOD_CTRL) or bool(mods & pygame.KMOD_META)
            shift = bool(mods & pygame.KMOD_SHIFT)
            k = e.key
            if ctrl and k == pygame.K_a:
                self.select_all()
            elif ctrl and k in (pygame.K_c, pygame.K_x):
                r = self.sel_range()
                if r:
                    clip_set(self._value[r[0]:r[1]])
                    if k == pygame.K_x:
                        self.delete_selection()
            elif ctrl and k == pygame.K_v or (shift and k == pygame.K_INSERT):
                self.insert(clip_get() or "")
            elif k == pygame.K_BACKSPACE:
                if not self.delete_selection() and self.cursor > 0:
                    to = self._word_left(self.cursor) if ctrl else self.cursor - 1
                    self._value = self._value[:to] + self._value[self.cursor:]
                    self.cursor = to
            elif k == pygame.K_DELETE:
                if not self.delete_selection() and self.cursor < len(self._value):
                    to = self._word_right(self.cursor) if ctrl else self.cursor + 1
                    self._value = self._value[:self.cursor] + self._value[to:]
            elif k == pygame.K_LEFT:
                r = self.sel_range()
                if r and not shift:
                    self.anchor, self.cursor = None, r[0]
                else:
                    self._move(self._word_left(self.cursor) if ctrl else self.cursor - 1, shift)
            elif k == pygame.K_RIGHT:
                r = self.sel_range()
                if r and not shift:
                    self.anchor, self.cursor = None, r[1]
                else:
                    self._move(self._word_right(self.cursor) if ctrl else self.cursor + 1, shift)
            elif k in (pygame.K_HOME, pygame.K_UP):
                self._move(0, shift)
            elif k in (pygame.K_END, pygame.K_DOWN):
                self._move(len(self._value), shift)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
                self._blur()
            else:
                return ctrl                                  # 그 밖의 Ctrl 조합은 게임 단축키로 새지 않게 삼킨다
            return True
        return False

    # -------------------------------------------------------------- 그리기
    def draw(self, surface):
        pygame.draw.rect(surface, (10, 16, 28, 240), self.rect, border_radius=5)
        pygame.draw.rect(surface, HIGHLIGHT if self.focused else BORDER, self.rect, 1, border_radius=5)
        f = font(17)
        v, c = self._value, self.cursor
        shown = v[:c] + self.composing + v[c:] if self.focused else v
        y = self.rect.centery
        inner_w = self.rect.w - 20
        cur_px = f.size(v[:c] + self.composing)[0]
        if cur_px - self.scroll > inner_w:
            self.scroll = cur_px - inner_w
        elif cur_px < self.scroll:
            self.scroll = cur_px
        if f.size(shown)[0] <= inner_w:
            self.scroll = 0
        old_clip = surface.get_clip()
        surface.set_clip(self.rect.inflate(-8, -4).clip(old_clip))
        x0 = self.rect.x + 10 - self.scroll
        sel = self.sel_range() if self.focused else None
        if sel:
            a, b = f.size(v[:sel[0]])[0], f.size(v[:sel[1]])[0]
            pygame.draw.rect(surface, (50, 90, 160), (x0 + a, y - 11, b - a, 22))
        if shown:
            text(surface, shown, (x0, y), 17, TEXT, anchor="midleft", shadow=False)
        else:
            text(surface, self.placeholder, (self.rect.x + 10, y), 17, TEXT_DIM, anchor="midleft", shadow=False)
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            x = x0 + cur_px + 1
            pygame.draw.line(surface, TEXT, (x, y - 10), (x, y + 10), 1)
        surface.set_clip(old_clip)
