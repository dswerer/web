"""gl_math.py — OpenGL 渲染所需的 4x4 矩阵工具（纯 numpy，不依赖任何 GL 库）。

约定
----
- 矩阵按 **行主序** 存放在 numpy 数组里（``M[row, col]``），向量按 **列向量** 参与乘法：
  ``p' = M @ p``。这与线性代数书写习惯一致，便于阅读与单测。
- 送给 OpenGL 时必须转成 **列主序** 字节流，统一走 :func:`gl_bytes`（内部做转置），
  因此调用方永远不用关心 GL 的内存布局。
- 角度：入参 ``deg`` 为度，``fovy`` 为弧度。
"""

from __future__ import annotations

import numpy as np

from spatial import quat_to_matrix


# ---------------------------------------------------------------------------
# 基础构造
# ---------------------------------------------------------------------------

def mat4_identity() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def mat4_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """矩阵乘 ``a @ b``（先应用 b，再应用 a）。"""
    return np.asarray(a, dtype=np.float32) @ np.asarray(b, dtype=np.float32)


def mat4_translate(v) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = np.asarray(v, dtype=np.float32).reshape(3)
    return m


def mat4_scale(s) -> np.ndarray:
    """尺度矩阵：``s`` 为标量时三轴等比，为长度 3 时逐轴缩放。"""
    arr = np.asarray(s, dtype=np.float32)
    if arr.ndim == 0:
        arr = np.full(3, float(arr), dtype=np.float32)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[1, 1], m[2, 2] = arr[0], arr[1], arr[2]
    return m


def _rot_x(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def _rot_y(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def _rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def mat4_rot_xyz(deg) -> np.ndarray:
    """绕 X、Y、Z 依次旋转（度），等价于 ``Rz @ Ry @ Rx``（先绕 X 转）。"""
    rx, ry, rz = (np.radians(float(d)) for d in np.asarray(deg, dtype=np.float64).reshape(3))
    return mat4_mul(_rot_z(rz), mat4_mul(_rot_y(ry), _rot_x(rx)))


def mat4_from_pos_quat_scale(pos, quat, scale=1.0, corr: np.ndarray | None = None) -> np.ndarray:
    """模型矩阵：``T(pos) @ R(quat) @ S(scale) @ corr``。

    ``corr`` 为模型自身坐标系内的朝向修正（例如 OBJ 模型不是 x 前/y 上/z 右时用
    ``--model-rot`` 生成），缺省为单位阵。
    """
    rot = np.eye(4, dtype=np.float32)
    rot[:3, :3] = quat_to_matrix(quat).astype(np.float32)
    m = mat4_mul(mat4_translate(pos), rot)
    m = mat4_mul(m, mat4_scale(scale))
    if corr is not None:
        m = mat4_mul(m, np.asarray(corr, dtype=np.float32))
    return m


# ---------------------------------------------------------------------------
# 相机与投影
# ---------------------------------------------------------------------------

def mat4_look_at(eye, target, up) -> np.ndarray:
    """视图矩阵（世界系 -> 相机系）：相机看向 -z，x 右、y 上。"""
    eye = np.asarray(eye, dtype=np.float64).reshape(3)
    target = np.asarray(target, dtype=np.float64).reshape(3)
    up = np.asarray(up, dtype=np.float64).reshape(3)

    f = target - eye
    nf = np.linalg.norm(f)
    f = np.array([0.0, 0.0, -1.0]) if nf < 1e-9 else f / nf

    s = np.cross(f, up)
    ns = np.linalg.norm(s)
    s = np.array([1.0, 0.0, 0.0]) if ns < 1e-9 else s / ns

    u = np.cross(s, f)

    m = np.eye(4, dtype=np.float32)
    m[0, :3] = s.astype(np.float32)
    m[1, :3] = u.astype(np.float32)
    m[2, :3] = (-f).astype(np.float32)
    m[0, 3] = float(-np.dot(s, eye))
    m[1, 3] = float(-np.dot(u, eye))
    m[2, 3] = float(np.dot(f, eye))
    return m


def mat4_perspective(fovy_rad: float, aspect: float, near: float, far: float) -> np.ndarray:
    """透视投影矩阵（相机系 -> 裁剪空间）。"""
    aspect = float(aspect) if abs(float(aspect)) > 1e-9 else 1.0
    near = max(float(near), 1e-4)
    far = max(float(far), near * 1.0001)
    t = np.tan(float(fovy_rad) * 0.5)
    t = t if abs(t) > 1e-9 else 1e-6

    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = 1.0 / (aspect * t)
    m[1, 1] = 1.0 / t
    m[2, 2] = -(far + near) / (far - near)
    m[2, 3] = -2.0 * far * near / (far - near)
    m[3, 2] = -1.0
    return m


def normal_matrix(model_view: np.ndarray) -> np.ndarray:
    """法线变换矩阵：``transpose(inverse(MV[:3,:3]))``，扩成 4x4 便于统一上传。"""
    mv = np.asarray(model_view, dtype=np.float64)
    try:
        n = np.linalg.inv(mv[:3, :3]).T
    except np.linalg.LinAlgError:
        n = np.eye(3)
    m = np.eye(4, dtype=np.float32)
    m[:3, :3] = n.astype(np.float32)
    return m


# ---------------------------------------------------------------------------
# 上传辅助
# ---------------------------------------------------------------------------

def gl_bytes(m: np.ndarray) -> bytes:
    """把行主序 numpy 矩阵转成 GL 需要的列主序 float32 字节流。

    moderngl 的 ``uniform.write()`` 按 GL 约定解释内存，因此这里必须转置；
    所有 uniform 上传都应经过本函数，调用方无需关心布局。
    """
    arr = np.asarray(m, dtype=np.float32)
    return np.ascontiguousarray(arr.T).tobytes()


def transform_points(m: np.ndarray, pts) -> np.ndarray:
    """用 4x4 矩阵变换点集（N,3），返回齐次除法后的 (N,3)。主要用于自检。"""
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    hom = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
    out = hom @ np.asarray(m, dtype=np.float64).T
    w = out[:, 3:4]
    w = np.where(np.abs(w) < 1e-12, 1.0, w)
    return out[:, :3] / w