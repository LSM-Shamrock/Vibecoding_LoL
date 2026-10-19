"""3D 모델 파일 로더 + 모델 라이브러리.

지원 형식
- .obj (+ .mtl, 텍스처 map_Kd)      : 자체 파서 (추가 설치 불필요)
- .glb / .gltf / .ply / .stl / .off : trimesh 사용 (pip install trimesh pillow)

로드한 모델은 설정의 height 에 맞게 크기를 맞추고, 발밑이 y=0, 중심이 원점에 오도록 정규화한다.
챔피언은 코드로 몸을 만들고 움직이는 절차적 리그(game/client/rigs)로 그린다.
"""
import logging
import math
import os
import traceback

import numpy as np
import pygame

from ..shared import data as gamedata
from ..shared.constants import ROOT_DIR
from . import procedural
from .gl import Mesh, bounds_of

# trimesh 는 scipy 가 없으면 경고 로그를 크게 남기지만 동작에는 문제가 없다
logging.getLogger("trimesh").setLevel(logging.ERROR)


def resolve_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(ROOT_DIR, path)


# ------------------------------------------------------------------ OBJ
def _load_mtl(path):
    mats = {}
    cur = None
    if not os.path.exists(path):
        return mats
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split()
            if not parts or parts[0].startswith("#"):
                continue
            if parts[0] == "newmtl":
                cur = {"kd": (1.0, 1.0, 1.0), "map": None, "d": 1.0}
                mats[" ".join(parts[1:])] = cur
            elif cur is None:
                continue
            elif parts[0] == "Kd" and len(parts) >= 4:
                cur["kd"] = tuple(float(v) for v in parts[1:4])
            elif parts[0] == "map_Kd" and len(parts) >= 2:
                cur["map"] = os.path.join(os.path.dirname(path), parts[-1])
    return mats


def load_obj(path):
    """반환: [(정점배열(N,11), 텍스처 이미지 경로 또는 None)]"""
    pos, nrm, uvs, cols = [], [], [], []
    groups = {}        # 재질 이름 -> 정점 리스트
    mats = {}
    cur = "__default__"
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line or line[0] == "#":
                continue
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == "v":
                pos.append((float(parts[1]), float(parts[2]), float(parts[3])))
                if len(parts) >= 7:
                    cols.append((float(parts[4]), float(parts[5]), float(parts[6])))
                else:
                    cols.append(None)
            elif tag == "vn":
                nrm.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vt":
                uvs.append((float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0))
            elif tag == "mtllib":
                mats.update(_load_mtl(os.path.join(os.path.dirname(path), " ".join(parts[1:]))))
            elif tag == "usemtl":
                cur = " ".join(parts[1:])
            elif tag == "f":
                idx = []
                for p in parts[1:]:
                    sp = p.split("/")
                    vi = int(sp[0])
                    ti = int(sp[1]) if len(sp) > 1 and sp[1] else None
                    ni = int(sp[2]) if len(sp) > 2 and sp[2] else None
                    vi = vi - 1 if vi > 0 else len(pos) + vi
                    if ti is not None:
                        ti = ti - 1 if ti > 0 else len(uvs) + ti
                    if ni is not None:
                        ni = ni - 1 if ni > 0 else len(nrm) + ni
                    idx.append((vi, ti, ni))
                g = groups.setdefault(cur, [])
                for k in range(1, len(idx) - 1):
                    g.append((idx[0], idx[k], idx[k + 1]))

    out = []
    for mname, tris in groups.items():
        mat = mats.get(mname, {"kd": (0.8, 0.8, 0.8), "map": None})
        kd = mat["kd"]
        arr = np.zeros((len(tris) * 3, 11), dtype="f4")
        i = 0
        for tri in tris:
            p = [np.array(pos[v[0]]) for v in tri]
            fn = np.cross(p[1] - p[0], p[2] - p[0])
            ln = np.linalg.norm(fn)
            fn = fn / ln if ln > 1e-12 else np.array([0.0, 1.0, 0.0])
            for (vi, ti, ni), pp in zip(tri, p):
                arr[i, 0:3] = pp
                arr[i, 3:6] = nrm[ni] if ni is not None and ni < len(nrm) else fn
                c = cols[vi]
                arr[i, 6:9] = c if c is not None else kd
                if ti is not None and ti < len(uvs):
                    arr[i, 9:11] = uvs[ti]
                i += 1
        tex = mat.get("map")
        out.append((arr, tex if tex and os.path.exists(tex) else None))
    return out


# ------------------------------------------------------------------ trimesh (glTF 등)
def load_with_trimesh(path):
    import trimesh  # 선택 의존성

    scene = trimesh.load(path, force="scene")
    out = []
    for node in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node]
        geom = scene.geometry.get(geom_name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        verts = trimesh.transformations.transform_points(geom.vertices, transform)
        rot = transform[:3, :3]
        normals = geom.vertex_normals @ rot.T
        ln = np.linalg.norm(normals, axis=1, keepdims=True)
        normals = normals / np.maximum(ln, 1e-9)
        faces = geom.faces.reshape(-1)
        n = len(faces)
        arr = np.zeros((n, 11), dtype="f4")
        arr[:, 0:3] = verts[faces]
        arr[:, 3:6] = normals[faces]
        arr[:, 6:9] = 1.0
        image = None
        visual = geom.visual
        try:
            if visual.kind == "texture":
                if visual.uv is not None and len(visual.uv) == len(geom.vertices):
                    arr[:, 9:11] = visual.uv[faces]
                mat = visual.material
                image = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
                factor = getattr(mat, "baseColorFactor", None)
                if factor is not None:
                    f = np.array(factor[:3], dtype="f4")
                    arr[:, 6:9] = f / 255.0 if f.max() > 1.0 else f
                if image is None:
                    col = visual.to_color().vertex_colors
                    arr[:, 6:9] = col[faces, :3] / 255.0
            elif visual.kind in ("vertex", "face"):
                col = visual.vertex_colors
                arr[:, 6:9] = col[faces, :3] / 255.0
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        out.append((arr, image))
    return out


def _pil_to_surface(img):
    img = img.convert("RGBA")
    return pygame.image.frombytes(img.tobytes(), img.size, "RGBA")


# ------------------------------------------------------------------ 정규화
def normalize(parts, height=None, rotation_y=0.0, offset=(0, 0, 0), scale=None, up_axis="y", keep_origin=False):
    """keep_origin=True 면 모델이 만들어진 원점(발밑 중앙)을 그대로 쓴다 — 무기가 한쪽으로 튀어나온 모델도 몸이 중앙에 선다."""
    if str(up_axis).lower() == "z":
        # Z 가 위쪽인 모델 (블렌더 기본 내보내기 등) -> Y 위쪽으로 변환
        conv = []
        for arr, tex in parts:
            a = arr.copy()
            a[:, [0, 1, 2]] = arr[:, [0, 2, 1]] * np.array([1, 1, -1], dtype="f4")
            a[:, [3, 4, 5]] = arr[:, [3, 5, 4]] * np.array([1, 1, -1], dtype="f4")
            conv.append((a, tex))
        parts = conv
    allp = np.concatenate([a[:, :3] for a, _ in parts])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    size_y = hi[1] - lo[1]
    if scale is None:
        scale = (height / size_y) if (height and size_y > 1e-6) else 1.0
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    floor = lo[1]
    if keep_origin:
        cx, cz, floor = 0.0, 0.0, 0.0
    ang = math.radians(rotation_y)
    c, s = math.cos(ang), math.sin(ang)
    rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype="f4")
    out = []
    for arr, tex in parts:
        a = arr.copy()
        p = a[:, :3] - np.array([cx, floor, cz], dtype="f4")
        p *= scale
        a[:, :3] = p @ rot.T + np.array(offset, dtype="f4")
        a[:, 3:6] = a[:, 3:6] @ rot.T
        out.append((a, tex))
    return out


# ------------------------------------------------------------------ 라이브러리
class ModelLibrary:
    def __init__(self, renderer):
        self.r = renderer
        self.cache = {}
        self.messages = []          # 로딩 결과 (화면 표시/디버그용)
        self.from_file = set()      # 모델 파일로 불러온 월드 모델 키
        self.rig_assets = {}        # 절차적 리그 이름 -> 메시 묶음
        self._build_defaults()

    def _mesh(self, builder):
        return Mesh.from_builder(self.r, builder)

    def _build_defaults(self):
        P = procedural
        self.map = self._mesh(P.build_map())
        self.shadow = self._mesh(P.build_shadow())
        from .gl import unit_builder_disc, unit_builder_ring
        self.disc = self._mesh(unit_builder_disc())
        self.ring = self._mesh(unit_builder_ring(0.1))
        self.ring_hair = self._mesh(unit_builder_ring(0.035))    # R 범위 표시용: ring(0.1) 의 약 1/3 두께
        self.ring_thin = self._mesh(unit_builder_ring(0.04))     # 두께 비율 0.04 (scenes/game.py 의 RING_THIN 과 같게)
        self.relic = self._mesh(P.build_relic())
        self.rubble = self._mesh(P.build_rubble())
        self.proj = {
            "arrow": self._mesh(P.build_arrow((0.85, 0.95, 1.0))),
            "snowball": self._mesh(P.build_orb((0.95, 0.97, 1.0), 0.28)),
            "turret_shot": self._mesh(P.build_orb((1.0, 0.85, 0.5), 0.3)),
            "turret_shot_2": self._mesh(P.build_orb((1.0, 0.6, 0.3), 0.38)),         # 같은 대상을 연속으로 맞히는 중: 더 크고 붉은 포탄
            "turret_shot_3": self._mesh(P.build_orb((1.0, 0.3, 0.2), 0.48)),
            # 거미 여왕: 거미줄 덩어리, 독침
            "web": self._mesh(P.build_orb((0.96, 0.9, 0.78), 0.36)),
            "web_shot": self._mesh(P.build_orb((0.96, 0.9, 0.78), 0.05)),
            "baby_shot": self._mesh(P.build_orb((0.96, 0.9, 0.78), 0.022)),
            "spine": self._mesh(P.build_arrow((1.0, 0.45, 0.25))),
            "minion_bolt": self._mesh(P.build_orb((1.0, 1.0, 1.0), 0.06)),
            "cannon_ball": self._mesh(P.build_orb((0.55, 0.55, 0.6), 0.09)),
            "fire_bolt": self._mesh(P.build_orb((1.0, 0.62, 0.18), 0.1)),
        }
        # 용의 회오리: 9겹 원뿔대 (보스러시 원본과 같은 구성)
        self.tornado_layers = [self._mesh(P.build_tornado_layer(i)) for i in range(9)]
        self.cocoon = self._mesh(P.build_cocoon())
        self.orb = self._mesh(P.build_orb((1, 1, 1), 1.0))
        self.team_meshes = {}
        for team in (0, 1):
            self.team_meshes[team] = {
                "minion_melee": self._world_or_default("minion_melee", lambda t=team: P.build_minion("melee", t)),
                "minion_caster": self._world_or_default("minion_caster", lambda t=team: P.build_minion("caster", t)),
                "minion_cannon": self._world_or_default("minion_cannon", lambda t=team: P.build_minion("cannon", t)),
                "minion_super": self._world_or_default("minion_super", lambda t=team: P.build_minion("super", t)),
                "minion_spiderling": self._mesh(P.build_minion("spiderling", team)),
                "minion_spiderling_walk": [self._mesh(P.build_minion("spiderling", team, frame=f)) for f in range(P.baby_frames())],
                "turret": self._world_or_default("turret", lambda t=team: P.build_turret(t)),
                "inhibitor": self._world_or_default("inhibitor", lambda t=team: P.build_inhibitor(t)),
                "inhibitor_dead": self._mesh(P.build_inhibitor(team, alive=False)),
                "nexus": self._world_or_default("nexus", lambda t=team: P.build_nexus(t)),
                "nexus_dead": self._mesh(P.build_nexus(team, alive=False)),
            }
        # 기본 도형 미니언의 무기 (모델 파일을 쓰는 미니언은 무기가 모델에 포함돼 있으므로 없음)
        self.minion_weapons = {}
        for team in (0, 1):
            weapons = {}
            for mtype in ("melee", "caster", "cannon", "super"):
                key = f"minion_{mtype}"
                if key in self.from_file:
                    continue
                built = P.build_minion_weapon(mtype, team)
                if built:
                    weapons[key] = (self._mesh(built[0]), built[1])
            self.minion_weapons[team] = weapons

    def _world_or_default(self, key, builder_fn):
        cfg = gamedata.world_models().get(key)
        if cfg and cfg.get("file"):
            mesh = self.load_file(cfg["file"], cfg)
            if mesh is not None:
                self.from_file.add(key)
                return mesh
        return self._mesh(builder_fn())

    def load_file(self, path, cfg=None):
        """모델 파일을 Mesh 로 읽는다. 실패하면 None."""
        cfg = cfg or {}
        full = resolve_path(path)
        key = (full, cfg.get("height"), cfg.get("rotation_y"), tuple(cfg.get("offset", (0, 0, 0))), cfg.get("scale"),
               cfg.get("up_axis"), cfg.get("pixelated"), cfg.get("keep_origin"))
        if key in self.cache:
            return self.cache[key]
        mesh = None
        if not os.path.exists(full):
            self.messages.append(f"모델 파일 없음: {path}")
        else:
            try:
                ext = os.path.splitext(full)[1].lower()
                if ext == ".obj":
                    raw = load_obj(full)
                    parts = [(a, pygame.image.load(t) if t else None) for a, t in raw]
                else:
                    raw = load_with_trimesh(full)
                    parts = [(a, _pil_to_surface(img) if img is not None else None) for a, img in raw]
                if not parts:
                    raise ValueError("메시가 비어 있습니다")
                arrs = normalize([(a, None) for a, _ in parts], cfg.get("height", 1.8), cfg.get("rotation_y", 0),
                                 cfg.get("offset", (0, 0, 0)), cfg.get("scale"), cfg.get("up_axis", "y"),
                                 bool(cfg.get("keep_origin", False)))
                gpu_parts = []
                for (arr, _), (_, surf) in zip(arrs, parts):
                    tex = (self.r.make_texture(surf, pixelated=cfg.get("pixelated", False))
                           if surf is not None else None)
                    gpu_parts.append((arr, tex))
                allarr = np.concatenate([a for a, _ in arrs])
                mesh = Mesh(self.r, gpu_parts, bounds_of(allarr))
                tri = sum(len(a) for a, _ in arrs) // 3
                self.messages.append(f"모델 로드: {path} ({tri} 삼각형)")
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.messages.append(f"모델 로드 실패: {path} ({e})")
        for m in self.messages[-1:]:
            print("[모델]", m)
        self.cache[key] = mesh
        return mesh

    def new_champ_anim(self, cid):
        """챔피언 한 명(한 판의 한 캐릭터)용 리그 동작 제어기. 리그가 없으면 None."""
        rig = self.rig_name(cid)
        if not rig:
            return None
        from .rigs import make_rig
        return make_rig(rig, self.r, self.rig_assets)

    def rig_name(self, cid):
        """챔피언의 절차적 리그 이름 (model.rig)."""
        return ((gamedata.champion(cid) or {}).get("model") or {}).get("rig")

    def champion(self, cid):
        """챔피언 자리 메시. 몸은 new_champ_anim() 의 리그가 그리고, 리그가 없으면 단순 인형으로 그린다."""
        key = ("champ", cid)
        if key in self.cache:
            return self.cache[key]
        data = gamedata.champion(cid) or {}
        col = tuple(c / 255 for c in data.get("color", (200, 200, 200)))
        mesh = self._mesh(procedural.build_mannequin(col))
        self.cache[key] = mesh
        return mesh
