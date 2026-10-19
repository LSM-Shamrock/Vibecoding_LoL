"""moderngl 기반 렌더러: 셰이더, 메시, 카메라, pygame 2D 오버레이."""
import math

import moderngl
import numpy as np
import pygame

from .geometry import MeshBuilder

MESH_VS = """
#version 330
uniform mat4 u_vp;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_nrm;
in vec3 in_col;
in vec2 in_uv;
out vec3 v_nrm;
out vec3 v_col;
out vec2 v_uv;
out vec3 v_wpos;
void main() {
    vec4 w = u_model * vec4(in_pos, 1.0);
    v_wpos = w.xyz;
    v_nrm = mat3(u_model) * in_nrm;
    v_col = in_col;
    v_uv = in_uv;
    gl_Position = u_vp * w;
}
"""

MESH_FS = """
#version 330
uniform vec3 u_light;
uniform vec4 u_tint;
uniform vec3 u_emissive;
uniform float u_unlit;
uniform bool u_use_tex;
uniform bool u_soft;         // 이펙트 그림: 반투명 가장자리를 버리지 않고 그대로 섞는다
uniform bool u_dbl;          // 양면 재질: 뒷면은 법선을 뒤집어 밝게 (보스 모델)
uniform sampler2D u_tex;
uniform vec3 u_cam;
uniform vec3 u_fog_color;
uniform float u_fog;
uniform bool u_use_vis;      // 전장의 안개: 시야 밖은 어둡게
uniform sampler2D u_vis;     // 시야 격자 (r: 1 보임, 0 안 보임)
uniform vec4 u_vis_rect;     // 격자가 덮는 월드 범위 (x0, z0, 폭, 높이)
in vec3 v_nrm;
in vec3 v_col;
in vec2 v_uv;
in vec3 v_wpos;
out vec4 f_color;
void main() {
    vec3 base = v_col;
    float a = 1.0;
    if (u_use_tex) {
        vec4 tx = texture(u_tex, v_uv);
        base *= tx.rgb;
        a = tx.a;
        if (a < 0.35 && !u_soft) discard;
    }
    base *= u_tint.rgb;
    vec3 n = normalize(v_nrm);
    if (u_dbl && !gl_FrontFacing) n = -n;
    float diff = max(dot(n, -u_light), 0.0);
    float hemi = 0.5 + 0.5 * n.y;
    vec3 view = normalize(u_cam - v_wpos);
    float rim = pow(1.0 - max(dot(n, view), 0.0), 3.0) * 0.25;
    // 황혼빛: 그림자는 보랏빛, 햇빛은 따뜻한 주황
    vec3 amb = vec3(0.29, 0.28, 0.33) + vec3(0.27, 0.26, 0.26) * hemi;
    vec3 sun = vec3(0.66, 0.58, 0.47) * diff;
    vec3 lit = base * (amb + sun) + vec3(1.0, 0.72, 0.5) * rim;
    vec3 c = mix(lit, base, u_unlit) + u_emissive;
    float dist = length(u_cam - v_wpos);
    float fog = clamp((dist - 45.0) / 70.0, 0.0, 1.0) * u_fog;
    c = mix(c, u_fog_color, fog);
    if (u_use_vis) {
        vec2 vuv = (v_wpos.xz - u_vis_rect.xy) / u_vis_rect.zw;
        if (vuv.x >= 0.0 && vuv.x <= 1.0 && vuv.y >= 0.0 && vuv.y <= 1.0) {
            float v = texture(u_vis, vuv).r;
            v = v * v * (3.0 - 2.0 * v);                  // 가장자리를 더 부드럽게
            c = mix(c * vec3(0.30, 0.32, 0.42), c, v);
        }
    }
    f_color = vec4(c, a * u_tint.a);
}
"""

OVERLAY_VS = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

# UI 표면(pygame, 위아래가 뒤집힌 BGRA 그대로)을 받아 위아래를 바로잡고 미리 곱한 알파로 바꾸는 패스
PREMUL_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    vec4 c = texture(u_tex, vec2(v_uv.x, 1.0 - v_uv.y));
    f_color = vec4(c.rgb * c.a, c.a);
}
"""

OVERLAY_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    f_color = texture(u_tex, v_uv);
}
"""


# ---------------------------------------------------------------- 행렬
def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), dtype="f4")
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def look_at(eye, target, up=(0, 1, 0)):
    eye = np.array(eye, dtype="f4")
    target = np.array(target, dtype="f4")
    up = np.array(up, dtype="f4")
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4, dtype="f4")
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def model_matrix(x=0.0, y=0.0, z=0.0, rot_y=0.0, scale=1.0, sx=None, sy=None, sz=None, rot_x=0.0):
    c, s = math.cos(rot_y), math.sin(rot_y)
    sx = scale if sx is None else sx
    sy = scale if sy is None else sy
    sz = scale if sz is None else sz
    m = np.array([
        [c * sx, 0, s * sz, x],
        [0, sy, 0, y],
        [-s * sx, 0, c * sz, z],
        [0, 0, 0, 1],
    ], dtype="f4")
    if rot_x:
        cx, sxr = math.cos(rot_x), math.sin(rot_x)
        rx = np.array([[1, 0, 0, 0], [0, cx, -sxr, 0], [0, sxr, cx, 0], [0, 0, 0, 1]], dtype="f4")
        m = m @ rx
    return m


def facing_to_rot(facing):
    """서버 facing(각도, (cos,sin)=(dx,dz)) → 모델의 +Z 가 그 방향을 보도록 하는 Y 회전."""
    return math.atan2(math.cos(facing), math.sin(facing))


def gl_bytes(m):
    return m.T.astype("f4").tobytes()


# ---------------------------------------------------------------- 메시
class Mesh:
    """여러 부분 메시(각자 텍스처 가능)의 묶음."""

    def __init__(self, renderer, parts, bounds=None):
        self.parts = []   # (vao, vbo, texture or None)
        ctx = renderer.ctx
        for arr, tex in parts:
            if len(arr) == 0:
                continue
            vbo = ctx.buffer(np.ascontiguousarray(arr, dtype="f4").tobytes())
            vao = ctx.vertex_array(renderer.prog, [(vbo, "3f 3f 3f 2f", "in_pos", "in_nrm", "in_col", "in_uv")])
            self.parts.append((vao, vbo, tex))
        self.bounds = bounds

    @classmethod
    def from_builder(cls, renderer, builder):
        arr = builder.array()
        return cls(renderer, [(arr, None)], bounds_of(arr))

    def release(self):
        for vao, vbo, tex in self.parts:
            vao.release()
            vbo.release()


def bounds_of(arr):
    if len(arr) == 0:
        return (np.zeros(3), np.zeros(3))
    return arr[:, :3].min(axis=0), arr[:, :3].max(axis=0)


# ---------------------------------------------------------------- 카메라
class Camera:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.tx = 0.0
        self.ty = 0.0
        self.tz = 0.0
        self.distance = 26.0
        self.pitch = math.radians(56)
        self.yaw = 0.0
        self.fov = 38.0
        self.update()

    def eye(self):
        horiz = math.cos(self.pitch) * self.distance
        return (self.tx + math.sin(self.yaw) * horiz,
                self.ty + math.sin(self.pitch) * self.distance,
                self.tz + math.cos(self.yaw) * horiz)

    def update(self):
        self.view = look_at(self.eye(), (self.tx, self.ty, self.tz))
        self.proj = perspective(self.fov, self.width / self.height, 1.0, 300.0)      # 가까운 면을 너무 당기면 깊이 정밀도가 떨어져 바닥 그림자가 깜빡인다
        self.vp = self.proj @ self.view
        self.inv_vp = np.linalg.inv(self.vp)

    def world_to_screen(self, x, y, z):
        p = self.vp @ np.array([x, y, z, 1.0], dtype="f4")
        if p[3] <= 0.01:
            return None
        nx, ny = p[0] / p[3], p[1] / p[3]
        return (float((nx * 0.5 + 0.5) * self.width), float((1 - (ny * 0.5 + 0.5)) * self.height))

    def screen_to_ground(self, sx, sy, plane_y=0.0):
        nx = sx / self.width * 2 - 1
        ny = 1 - sy / self.height * 2
        p0 = self.inv_vp @ np.array([nx, ny, -1, 1], dtype="f4")
        p1 = self.inv_vp @ np.array([nx, ny, 1, 1], dtype="f4")
        p0 = p0[:3] / p0[3]
        p1 = p1[:3] / p1[3]
        d = p1 - p0
        if abs(d[1]) < 1e-6:
            return None
        t = (plane_y - p0[1]) / d[1]
        hit = p0 + d * t
        return float(hit[0]), float(hit[2])


# ---------------------------------------------------------------- 렌더러
class Renderer:
    def __init__(self, ctx, width, height):
        self.ctx = ctx
        self.width = width
        self.height = height
        self.prog = ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        light = tuple(np.array([-0.35, -1.0, -0.45]) / np.linalg.norm([-0.35, -1.0, -0.45]))
        prog = self.prog
        prog["u_light"].value = light
        prog["u_fog_color"].value = (0.70, 0.84, 1.0)
        prog["u_fog"].value = 0.0           # 우주 배경: 안개 없음
        prog["u_tex"].value = 0
        prog["u_soft"].value = False
        prog["u_dbl"].value = False
        self._uni = {}                      # id(프로그램) -> ({유니폼 이름: 핸들}, {지난번 값})
        self.camera = Camera(width, height)
        self._white = ctx.texture((1, 1), 4, b"\xff\xff\xff\xff")
        self.overlay = Overlay(ctx, width, height)
        self.sky = SpaceSky(ctx)
        self.time = 0.0
        self.unit_quad = None
        self.vision = None              # (텍스처, (x0, z0, 폭, 높이)) — 설정되면 시야 밖을 어둡게
        # 실제 창(프레임버퍼) 크기와, 논리 화면(width x height)이 그려질 영역
        self.window_size = (width, height)
        self.viewport = (0, 0, width, height)
        self.scale = 1.0

    def set_window_size(self, w, h):
        """창 크기에 맞춰 논리 화면을 비율 유지(레터박스)로 배치한다."""
        self.window_size = (w, h)
        s = min(w / self.width, h / self.height)
        vw, vh = int(round(self.width * s)), int(round(self.height * s))
        self.viewport = ((w - vw) // 2, (h - vh) // 2, vw, vh)
        self.scale = s

    def to_logical(self, pos):
        """창 좌표 -> 논리 화면 좌표 (UI·카메라 계산용)."""
        vx, vy, vw, vh = self.viewport
        _, h = self.window_size
        top = h - vy - vh
        return ((pos[0] - vx) / self.scale, (pos[1] - top) / self.scale)

    def end_overlay(self):
        self.ctx.viewport = self.viewport
        self.overlay.end(scaled=abs(self.scale - 1.0) > 1e-3)

    def begin_3d(self, camera=None, clear=(0.01, 0.012, 0.03), sky=True):
        for _u, last in self._uni.values():
            last.clear()                    # 다른 곳에서 유니폼을 바꿨을 수도 있으니 프레임마다 처음엔 다시 쓴다
        cam = camera or self.camera
        cam.update()
        self.ctx.viewport = (0, 0, *self.window_size)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.ctx.viewport = self.viewport
        self.ctx.clear(*clear, 1.0, viewport=self.viewport)
        if sky:
            self.sky.draw(cam, self.time)
        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.ctx.disable(moderngl.CULL_FACE)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.fbo.depth_mask = True
        vp = gl_bytes(cam.vp)
        eye = tuple(float(v) for v in cam.eye())
        prog = self.prog
        prog["u_vp"].write(vp)
        if self.vision:
            tex, rect = self.vision
            tex.use(1)
            prog["u_vis"].value = 1
            prog["u_vis_rect"].value = rect
            prog["u_use_vis"].value = True
        else:
            prog["u_use_vis"].value = False
        prog["u_cam"].value = eye

    y_offset = 0.0

    def draw(self, mesh, model, tint=(1, 1, 1, 1), emissive=(0, 0, 0), unlit=0.0, soft=False):
        if mesh is None:
            return
        prog = self.prog
        if self.y_offset:
            model = model.copy()
            model[1, 3] += self.y_offset            # 리그 챔피언 에어본 등: 그리는 전체를 위로 띄운다
        # 유니폼 핸들은 프로그램마다 한 번만 찾아 두고, 값이 지난번과 같으면 다시 쓰지 않는다 (그리기 호출이 많아 꽤 아낀다)
        U = self._uni.get(id(prog))
        if U is None:
            U = self._uni[id(prog)] = ({n: prog[n] for n in ("u_model", "u_tint", "u_emissive", "u_unlit", "u_soft", "u_use_tex")}, {})
        uni, last = U
        uni["u_model"].write(gl_bytes(model))
        t4 = (float(tint[0]), float(tint[1]), float(tint[2]), float(tint[3]) if len(tint) == 4 else 1.0)
        if last.get("t") != t4:
            uni["u_tint"].value = last["t"] = t4
        em = (float(emissive[0]), float(emissive[1]), float(emissive[2]))
        if last.get("e") != em:
            uni["u_emissive"].value = last["e"] = em
        ul = float(unlit)
        if last.get("l") != ul:
            uni["u_unlit"].value = last["l"] = ul
        sf = bool(soft)
        if last.get("s") != sf:
            uni["u_soft"].value = last["s"] = sf
        for vao, vbo, tex in mesh.parts:
            ut = tex is not None
            if ut:
                tex.use(0)
            if last.get("x") != ut:
                uni["u_use_tex"].value = last["x"] = ut
            vao.render(moderngl.TRIANGLES)

    def draw_transparent(self, mesh, model, tint, emissive=(0, 0, 0), unlit=1.0, additive=False):
        """지면 장식/이펙트용: 깊이 쓰기 없이 블렌딩.
        (깊이 쓰기는 Context 가 아니라 Framebuffer 의 depth_mask 로 끈다. 예전에는 ctx.depth_mask 라고 써서
        아무 효과가 없었고, 투명한 먼지 그림의 네모 전체가 깊이를 써서 뒤에 그리는 이펙트를 네모로 잘라 먹었다.)"""
        fbo = self.ctx.fbo
        fbo.depth_mask = False
        if additive:
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        self.draw(mesh, model, tint, emissive, unlit, soft=True)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        fbo.depth_mask = True

    def make_texture(self, surface_or_bytes, size=None, pixelated=False):
        if isinstance(surface_or_bytes, pygame.Surface):
            size = surface_or_bytes.get_size()
            data = pygame.image.tobytes(surface_or_bytes, "RGBA", True)
        else:
            data = surface_or_bytes
        tex = self.ctx.texture(size, 4, data)
        if pixelated:
            # 픽셀아트 텍스처: 보간 없이 또렷하게
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        else:
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.repeat_x = True
        tex.repeat_y = True
        return tex

    def mesh(self, builder):
        return Mesh.from_builder(self, builder)


SKY_VS = """
#version 330
in vec2 in_pos;
out vec2 v_ndc;
void main() {
    v_ndc = in_pos;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

SKY_FS = """
#version 330
uniform mat4 u_inv_vp;
uniform float u_time;
in vec2 v_ndc;
out vec4 f_color;

float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i + vec3(0, 0, 0)), hash(i + vec3(1, 0, 0)), f.x),
                   mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
                   mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = p * 2.03 + vec3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return v;
}

// 황혼의 하늘: 아래는 노을빛 구름 바다, 위는 보랏빛에서 남색으로 번지는 하늘, 지평선 근처에 큰 해
void main() {
    vec4 pn = u_inv_vp * vec4(v_ndc, -1.0, 1.0);
    vec4 pf = u_inv_vp * vec4(v_ndc, 1.0, 1.0);
    vec3 ro = pn.xyz / pn.w;
    vec3 d = normalize(pf.xyz / pf.w - ro);

    vec3 sun_dir = normalize(vec3(-0.45, 0.16, -0.88));
    vec3 sun_col = vec3(1.0, 0.95, 0.8);
    float sd = max(dot(d, sun_dir), 0.0);

    // 하늘
    float h = clamp(d.y, -1.0, 1.0);
    vec3 horizon = vec3(0.80, 0.91, 1.0);
    vec3 mid = vec3(0.46, 0.70, 0.96);
    vec3 zenith = vec3(0.14, 0.40, 0.86);
    vec3 sky = mix(horizon, mid, smoothstep(0.0, 0.25, h));
    sky = mix(sky, zenith, smoothstep(0.2, 0.9, h));
    sky += sun_col * (pow(sd, 6.0) * 0.18 + pow(sd, 90.0) * 0.9);
    sky = mix(sky, vec3(1.0, 0.95, 0.8), smoothstep(0.9993, 0.9997, sd));

    vec3 col = sky;
    // 아래쪽: 플랫폼 아래로 펼쳐진 구름 바다 (월드에 고정돼서 카메라가 움직이면 시차가 생긴다)
    if (d.y < -0.01) {
        float plane_y = -46.0;
        float t = (plane_y - ro.y) / d.y;
        vec2 wp = ro.xz + d.xz * t;
        float n1 = fbm(vec3(wp * 0.035, u_time * 0.015));
        float n2 = fbm(vec3(wp * 0.11 + 7.0, 1.0 + u_time * 0.02));
        float cl = smoothstep(0.32, 0.72, n1 * 0.75 + n2 * 0.35);
        vec3 deep = vec3(0.38, 0.55, 0.80);                       // 구름 틈의 깊은 안개
        vec3 lit = vec3(1.0, 1.0, 1.0);                         // 해를 받은 구름 윗면
        vec3 shade = vec3(0.70, 0.80, 0.94);
        float rim = clamp((n1 - fbm(vec3((wp + sun_dir.xz * 4.0) * 0.035, u_time * 0.015))) * 6.0 + 0.5, 0.0, 1.0);
        vec3 cloud = mix(shade, lit, rim);
        vec3 below = mix(deep, cloud, cl);
        float far = smoothstep(0.0, 0.35, -d.y);                 // 지평선에 가까울수록 노을 안개에 묻힌다
        below = mix(horizon * 0.95, below, far);
        col = below;
    }
    // 먼 하늘의 얇은 구름 띠
    if (d.y > 0.0) {
        float c = fbm(vec3(d.x * 3.0 / (d.y + 0.35), d.z * 3.0 / (d.y + 0.35), u_time * 0.01));
        col = mix(col, mix(vec3(0.95, 0.98, 1.0), horizon, 0.4), smoothstep(0.52, 0.8, c) * 0.35 * (1.0 - h));
    }
    f_color = vec4(col, 1.0);
}
"""


class SpaceSky:
    """화면 전체에 황혼 하늘과 구름 바다를 셰이더로 그린다 (텍스처 불필요)."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.prog = ctx.program(vertex_shader=SKY_VS, fragment_shader=SKY_FS)
        tri = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")
        self.vbo = ctx.buffer(tri.tobytes())
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "2f", "in_pos")])

    def draw(self, cam, t):
        self.ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.prog["u_inv_vp"].write(gl_bytes(cam.inv_vp.astype("f4")))
        self.prog["u_time"].value = float(t)
        self.vao.render(moderngl.TRIANGLES)


class Overlay:
    """pygame Surface 에 2D UI 를 그리고 텍스처로 올려 화면 위에 덮는다."""

    def __init__(self, ctx, width, height):
        self.ctx = ctx
        self.surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self.texture = ctx.texture((width, height), 4)
        self.texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.prog = ctx.program(vertex_shader=OVERLAY_VS, fragment_shader=OVERLAY_FS)
        quad = np.array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1], dtype="f4")
        self.vbo = ctx.buffer(quad.tobytes())
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "2f", "in_pos")])
        # 빠른 길: 표면 메모리(BGRA, 위에서부터)를 복사·변환 없이 그대로 올리고, 순서 바꾸기·위아래 뒤집기·알파 곱하기는 GPU 가 한다
        self.fast = (self.surface.get_masks() == (0xFF0000, 0xFF00, 0xFF, 0xFF000000)
                     and self.surface.get_pitch() == width * 4)
        if self.fast:
            self.raw = ctx.texture((width, height), 4)
            self.raw.swizzle = "BGRA"
            self.raw.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self.premul_fbo = ctx.framebuffer(color_attachments=[self.texture])
            self.prog_premul = ctx.program(vertex_shader=OVERLAY_VS, fragment_shader=PREMUL_FS)
            self.vao_premul = ctx.vertex_array(self.prog_premul, [(self.vbo, "2f", "in_pos")])

    def begin(self):
        self.surface.fill((0, 0, 0, 0))
        return self.surface

    def end(self, scaled=False):
        # 확대 표시(전체 화면) 시 글자 가장자리가 검게 번지지 않도록 미리 곱한 알파로 올린다
        if self.fast:
            vp, screen = self.ctx.viewport, self.ctx.fbo
            self.raw.write(self.surface.get_view("0"))
            self.ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
            self.premul_fbo.use()
            self.raw.use(0)
            self.prog_premul["u_tex"].value = 0
            self.vao_premul.render(moderngl.TRIANGLES)
            screen.use()
            self.ctx.viewport = vp
        else:
            self.texture.write(pygame.image.tobytes(self.surface.premul_alpha(), "RGBA", True))
        f = moderngl.LINEAR if scaled else moderngl.NEAREST
        self.texture.filter = (f, f)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.texture.use(0)
        self.prog["u_tex"].value = 0
        self.vao.render(moderngl.TRIANGLES)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA


def unit_builder_disc():
    b = MeshBuilder()
    b.disc((0, 0, 0), 1.0, (1, 1, 1), 40)
    return b


def unit_builder_ring(thickness=0.12):
    b = MeshBuilder()
    b.ring((0, 0, 0), 1.0 - thickness, 1.0, (1, 1, 1), 48)
    return b
