"""gl_mesh.py — OpenGL 渲染用的三角网格：程序化盒体生成 + OBJ 读写（纯 numpy）。

坐标约定与 ``aircraft.py`` 一致：机体系 x 前 / y 上 / z 右翼；单位米。

- :func:`procedural_mesh` 把 ``Glider.parts()`` 的每个盒体展开成 12 个三角形，
  在没有任何模型文件时提供可用的默认外观。
- :func:`load_obj` 读取外部飞机模型（支持 ``v`` / ``vn`` / ``f``，含 ``v/vt``、
  ``v//vn``、``v/vt/vn``、负索引、四边形与多边形扇形三角化；无 ``vn`` 时按面法线
  平滑累加生成）。不解析 ``mtllib/usemtl/vt``——渲染走顶点色 + 光照，不做贴图。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from gl_math import mat4_rot_xyz

DEFAULT_MODEL_COLOR = (0.82, 0.83, 0.88)


@dataclass
class Mesh:
    """三角网格（顶点属性一一对应，索引为三角形列表）。"""

    positions: np.ndarray   # (N, 3) float32
    normals: np.ndarray     # (N, 3) float32
    colors: np.ndarray      # (N, 3) float32
    indices: np.ndarray     # (M,)   uint32

    @property
    def triangle_count(self) -> int:
        return int(len(self.indices) // 3)

    def interleave(self) -> bytes:
        """按 ``pos(3f) + normal(3f) + color(3f)`` 交错打包，供 VBO 上传。"""
        data = np.concatenate(
            [self.positions, self.normals, self.colors], axis=1
        ).astype(np.float32)
        return np.ascontiguousarray(data).tobytes()

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.positions.min(axis=0), self.positions.max(axis=0)


def _empty() -> Mesh:
    return Mesh(
        positions=np.zeros((0, 3), dtype=np.float32),
        normals=np.zeros((0, 3), dtype=np.float32),
        colors=np.zeros((0, 3), dtype=np.float32),
        indices=np.zeros((0,), dtype=np.uint32),
    )


def _concat(meshes: list[Mesh]) -> Mesh:
    """把多个网格拼成一个（索引整体偏移）。"""
    meshes = [m for m in meshes if len(m.positions)]
    if not meshes:
        return _empty()
    pos, nrm, col, idx = [], [], [], []
    base = 0
    for m in meshes:
        pos.append(m.positions)
        nrm.append(m.normals)
        col.append(m.colors)
        idx.append(m.indices + base)
        base += len(m.positions)
    return Mesh(
        positions=np.concatenate(pos).astype(np.float32),
        normals=np.concatenate(nrm).astype(np.float32),
        colors=np.concatenate(col).astype(np.float32),
        indices=np.concatenate(idx).astype(np.uint32),
    )


# ---------------------------------------------------------------------------
# 程序化盒体
# ---------------------------------------------------------------------------

# 单位立方体的 6 个面，每面 4 个角点（逆时针，法线朝外）+ 面法线
_BOX_FACES = (
    ((0.0, 0.0, 1.0), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
    ((0.0, 0.0, -1.0), ((1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1))),
    ((1.0, 0.0, 0.0), ((1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1))),
    ((-1.0, 0.0, 0.0), ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1))),
    ((0.0, 1.0, 0.0), ((-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1))),
    ((0.0, -1.0, 0.0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
)


def box_mesh(center, half, rgba) -> Mesh:
    """一个轴对齐盒体 -> 12 个三角形（每面独立法线，24 顶点）。"""
    c = np.asarray(center, dtype=np.float32).reshape(3)
    h = np.asarray(half, dtype=np.float32).reshape(3)
    rgb = np.asarray(rgba, dtype=np.float32).reshape(-1)[:3]

    pos, nrm, idx = [], [], []
    for normal, corners in _BOX_FACES:
        n = np.asarray(normal, dtype=np.float32)
        base = len(pos)
        for sx, sy, sz in corners:
            pos.append(c + np.array([sx, sy, sz], dtype=np.float32) * h)
            nrm.append(n)
        idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])

    n_v = len(pos)
    return Mesh(
        positions=np.asarray(pos, dtype=np.float32),
        normals=np.asarray(nrm, dtype=np.float32),
        colors=np.tile(rgb, (n_v, 1)).astype(np.float32),
        indices=np.asarray(idx, dtype=np.uint32),
    )


def procedural_mesh(glider) -> Mesh:
    """由 ``Glider.parts()`` 派生整机网格（默认外观，无需模型文件）。"""
    return _concat([box_mesh(center, half, rgba) for _n, center, half, rgba in glider.parts()])


# ---------------------------------------------------------------------------
# OBJ 读写
# ---------------------------------------------------------------------------

def _newell_normal(pts: np.ndarray) -> np.ndarray:
    """多边形面法线（Newell 法，天然处理非平面多边形）。"""
    n = np.zeros(3, dtype=np.float64)
    m = len(pts)
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return n


def load_obj(path: str, color=DEFAULT_MODEL_COLOR) -> Mesh:
    """读取 OBJ 文件为单色 :class:`Mesh`。解析失败/无面时抛 ``ValueError``。"""
    verts: list[list[float]] = []
    norms: list[list[float]] = []
    faces: list[list[tuple[int, int | None]]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line[0] == "#":
                continue
            tok = line.split()
            head = tok[0]
            if head == "v" and len(tok) >= 4:
                verts.append([float(tok[1]), float(tok[2]), float(tok[3])])
            elif head == "vn" and len(tok) >= 4:
                norms.append([float(tok[1]), float(tok[2]), float(tok[3])])
            elif head == "f" and len(tok) >= 4:
                face: list[tuple[int, int | None]] = []
                for item in tok[1:]:
                    parts = item.split("/")
                    try:
                        vi = int(parts[0])
                    except ValueError:
                        continue
                    vi = vi - 1 if vi > 0 else len(verts) + vi
                    ni: int | None = None
                    if len(parts) >= 3 and parts[2]:
                        try:
                            raw_ni = int(parts[2])
                            ni = raw_ni - 1 if raw_ni > 0 else len(norms) + raw_ni
                        except ValueError:
                            ni = None
                    face.append((vi, ni))
                if len(face) >= 3:
                    faces.append(face)

    if not verts or not faces:
        raise ValueError(f"OBJ 中未找到有效顶点/面：{path}")

    v_arr = np.asarray(verts, dtype=np.float64)
    n_v = len(v_arr)

    # 校验索引范围，越界的面直接丢弃
    valid_faces = [
        f for f in faces
        if all(0 <= vi < n_v and (ni is None or 0 <= ni < len(norms)) for vi, ni in f)
    ]
    if not valid_faces:
        raise ValueError(f"OBJ 面索引越界：{path}")

    # 无 vn 时：按面法线对共享顶点平滑累加
    if not norms:
        acc = np.zeros((n_v, 3), dtype=np.float64)
        for face in valid_faces:
            pts = v_arr[[vi for vi, _ in face]]
            acc[[vi for vi, _ in face]] += _newell_normal(pts)
        ln = np.linalg.norm(acc, axis=1, keepdims=True)
        acc = np.divide(acc, np.where(ln < 1e-12, 1.0, ln))
        acc[ln[:, 0] < 1e-12] = np.array([0.0, 1.0, 0.0])
        n_arr = acc
    else:
        n_arr = np.asarray(norms, dtype=np.float64)

    # 按 (顶点, 法线) 去重，拼装非索引顶点表 + 三角形索引
    keymap: dict[tuple[int, int], int] = {}
    out_pos: list[np.ndarray] = []
    out_nrm: list[np.ndarray] = []
    out_idx: list[int] = []

    def resolve(vi: int, ni: int | None) -> int:
        n_idx = ni if ni is not None else vi      # 平滑法线时法线与顶点同号
        key = (vi, n_idx)
        got = keymap.get(key)
        if got is None:
            got = len(out_pos)
            out_pos.append(v_arr[vi])
            out_nrm.append(n_arr[n_idx])
            keymap[key] = got
        return got

    for face in valid_faces:
        a = resolve(*face[0])
        for k in range(1, len(face) - 1):
            out_idx.extend([a, resolve(*face[k]), resolve(*face[k + 1])])

    rgb = np.asarray(color, dtype=np.float32).reshape(-1)[:3]
    pos_f = np.asarray(out_pos, dtype=np.float32)
    nrm_f = np.asarray(out_nrm, dtype=np.float32)
    return Mesh(
        positions=pos_f,
        normals=nrm_f,
        colors=np.tile(rgb, (len(pos_f), 1)).astype(np.float32),
        indices=np.asarray(out_idx, dtype=np.uint32),
    )


def load_glb(path: str, color=DEFAULT_MODEL_COLOR) -> Mesh:
    """读取 GLB / GLTF 模型（经 ``trimesh``），合并所有子网格为 :class:`Mesh`。

    - 顶点：`position` 取 `normal`（无时用三角面法线累加平滑分摊，与 :func:`load_obj` 一致）；
    - 颜色：优先用顶点的 vertex colors（`visual.vertex_colors`），否则沿用材质 baseColorFactor，
      再兜底统一 `color`；
    - 单位 / 朝向未知：由调用方 ``fit_mesh`` 归一化并做朝向修正。
    """
    import trimesh  # 懒加载：无 trimesh 时仅 OBJ/程序化网格可用

    loaded = trimesh.load(path, force=None, process=True)
    geoms = loaded.geometry.values() if isinstance(loaded, trimesh.Scene) else [loaded]
    geoms = [g for g in geoms if getattr(g, "faces", None) is not None and len(g.faces)]
    if not geoms:
        raise ValueError(f"GLB 中未找到有效网格：{path}")

    rgb0 = np.asarray(color, dtype=np.float32).reshape(-1)[:3]
    pos, nrm, col, idx, base = [], [], [], [], 0
    for g in geoms:
        v = np.asarray(g.vertices, dtype=np.float32)
        f = np.asarray(g.faces, dtype=np.uint32)
        n = getattr(g, "vertex_normals", None)
        if n is None or np.asarray(n).shape[0] != len(v):   # 无法线：累加平滑分摊
            tri = np.asarray(getattr(g, "triangle_normals", None), dtype=np.float64)
            if tri.shape != (len(f), 3):
                tri = _face_normals(f, v)
            acc = np.zeros((len(v), 3), dtype=np.float64)
            acc_rep = np.repeat(tri, 3, axis=0)
            np.add.at(acc, f.ravel(), acc_rep)
            ln = np.linalg.norm(acc, axis=1, keepdims=True)
            n = np.divide(acc, np.where(ln < 1e-12, 1.0, ln)).astype(np.float32)
        else:
            n = np.asarray(n, dtype=np.float32)

        vc = getattr(getattr(g, "visual", None), "vertex_colors", None)
        if vc is not None and len(vc) == len(v):
            rgb = np.asarray(vc, dtype=np.float32)[:, :3] / 255.0
        else:
            rgb = np.tile(rgb0, (len(v), 1)).astype(np.float32)
        pos.append(v); nrm.append(n); col.append(rgb)
        idx.append(f.astype(np.uint32) + base); base += len(v)

    return Mesh(
        positions=np.concatenate(pos).astype(np.float32),
        normals=np.concatenate(nrm).astype(np.float32),
        colors=np.concatenate(col).astype(np.float32),
        indices=np.concatenate(idx).astype(np.uint32),
    )


def _face_normals(faces, verts):
    """按面计算单位法线（用于无法线、无 triangle_normals 时的兜底）。"""
    v = verts[faces]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]).astype(np.float64)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, np.where(ln < 1e-12, 1.0, ln))


def mesh_to_obj(mesh: Mesh, path: str) -> str:
    """把网格写成 OBJ（仅用于验证/调试：导出程序化网格后可再读回比对）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# generated by gl_mesh.mesh_to_obj\n")
        for p in mesh.positions:
            fh.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
        for n in mesh.normals:
            fh.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
        for i in range(0, len(mesh.indices), 3):
            tri = [int(mesh.indices[i + k]) + 1 for k in range(3)]
            fh.write("f " + " ".join(f"{t}//{t}" for t in tri) + "\n")
    return path


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def fit_mesh(mesh: Mesh, target_len: float, rot_deg=(0.0, 0.0, 0.0), scale: float = 0.0) -> Mesh:
    """模型朝向修正 + 居中 + 缩放到目标长度。

    - ``rot_deg``：模型自身坐标系内的朝向修正（度），按 X→Y→Z 依次旋转；
    - ``scale > 0`` 时使用显式缩放，否则按"最长轴 = ``target_len``"自动归一化（应对 OBJ 单位未知）；
    - 归一化后模型几何中心与机体系原点（质心）重合。
    """
    if len(mesh.positions) == 0:
        return mesh

    rot = np.asarray(mat4_rot_xyz(rot_deg), dtype=np.float64)[:3, :3]
    pos = mesh.positions.astype(np.float64) @ rot.T
    nrm = mesh.normals.astype(np.float64) @ rot.T

    center = 0.5 * (pos.min(axis=0) + pos.max(axis=0))
    pos = pos - center

    if scale > 0:
        s = float(scale)
    else:
        longest = float((pos.max(axis=0) - pos.min(axis=0)).max())
        s = float(target_len) / longest if longest > 1e-9 else 1.0
    pos *= s

    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, np.where(ln < 1e-12, 1.0, ln))

    return Mesh(
        positions=pos.astype(np.float32),
        normals=nrm.astype(np.float32),
        colors=mesh.colors.copy(),
        indices=mesh.indices.copy(),
    )