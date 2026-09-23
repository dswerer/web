"""render_gl.py — OpenGL（GPU）渲染途径：外部模型 + 顶点/片段着色器 + uniform 契约。

与 :mod:`render`（matplotlib 路径）并列，二者产出同一种 ``flight_replay.mp4``，
可用 ``sim_service.py --renderer gl|mpl`` 切换；matplotlib 路径保留作为兜底与对拍。

渲染流程
--------
1. :func:`create_context` 建隐藏窗口/离屏上下文（moderngl-window -> 裸 glfw -> EGL）；
2. :class:`GliderGLRenderer` 编译 ``shaders/*.vert|frag``、上传网格、逐帧渲染到 FBO；
3. :func:`make_video_gl` 逐帧取 ``(H, W, 3) uint8`` 交给 imageio-ffmpeg 编码 MP4。

坐标约定：世界系 Y 向上，机体系 x 前 / y 上 / z 右翼——与 OpenGL 的 Y-up 天然一致，
不需要像 matplotlib 路径那样做 z-up 换轴。

Uniform 契约
------------
渲染器每帧把下表全部写进飞机着色器；着色器**按需声明**即可使用，
未声明的会被渲染器自动跳过（见 :class:`GliderGLRenderer._set`）。

看 :data:`UNIFORM_CONTRACT` 获取机器可读的清单，``glider/README.md`` 有成表说明。
"""

from __future__ import annotations

import json
import os

import numpy as np

from gl_math import (gl_bytes, mat4_from_pos_quat_scale, mat4_look_at, mat4_mul,
                     mat4_perspective, mat4_rot_xyz, normal_matrix)
from gl_mesh import Mesh, fit_mesh, load_glb, load_obj, procedural_mesh
from render import _flight_view_bounds, _hud_text          # 复用，不复制实现
from spatial import (body_axis_heading, euler_from_quat, quat_conjugate,
                     quat_mul, quat_to_axis_angle, quat_to_matrix)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
SHADER_DIR = os.path.join(_MODULE_DIR, "shaders")
#: 未显式指定 --model 时按序查找的默认模型（存在则优先于程序化网格）
DEFAULT_MODEL_PATH = os.path.join(_MODULE_DIR, "assets", "airplane.obj")
DEFAULT_MODEL_GLB = os.path.join(_MODULE_DIR, "assets", "airplane.glb")

SKY_COLOR = (0.53, 0.72, 0.94)
GROUND_COLOR = (0.42, 0.58, 0.44, 0.85)
TRAIL_COLOR = (0.18, 0.42, 0.86, 0.95)
LIGHT_DIR = (0.30, 0.80, -0.52)
LIGHT_COLOR = (0.95, 0.95, 0.92)
AMBIENT = (0.42, 0.45, 0.50)
BASE_COLOR = (1.0, 1.0, 1.0, 1.0)

#: 逐帧写入的 uniform 契约（着色器可按需声明其中任意项）
UNIFORM_CONTRACT = {
    # ---- 变换（渲染所需的各种变换）----
    "u_model": "mat4  模型矩阵 T(u_pos) @ R(u_quat) @ S(u_scale) @ 模型朝向修正",
    "u_view": "mat4  世界系 -> 相机系",
    "u_proj": "mat4  相机系 -> 裁剪空间（透视）",
    "u_mvp": "mat4  u_proj @ u_view @ u_model（现成，可直接用）",
    "u_normal_mat": "mat4  法线变换 transpose(inverse(u_view@u_model)) 的左上 3x3",
    # ---- 姿态 / 飞行状态（控制飞机姿态所需的所有参数）----
    "u_pos": "vec3  世界位置 [x, alt, z] (m)",
    "u_quat": "vec4  姿态四元数 xyzw",
    "u_euler": "vec3  (roll, pitch, yaw) 弧度",
    "u_vel": "vec3  世界速度 (m/s)",
    "u_omega": "vec3  世界角速度 (rad/s)",
    "u_scale": "float 飞机显示放大倍数",
    "u_alt": "float 高度 (m)",
    "u_V": "float 空速 (m/s)",
    "u_alpha": "float 迎角 (rad)",
    "u_beta": "float 侧滑角 (rad)",
    "u_CL": "float 升力系数",
    "u_CD": "float 阻力系数",
    "u_sink": "float 下沉率 (m/s)",
    "u_bank": "float 坡度 (deg)",
    "u_pitch": "float 俯仰 (deg)",
    "u_heading": "float 航向 (deg)",
    "u_elevator": "float 升降舵偏转",
    "u_aileron": "float 副翼偏转",
    "u_rudder": "float 方向舵偏转",
    "u_time": "float 仿真时间 (s)",
    "u_frame": "int   帧序号",
    "u_highlight": "float 0/1 异常姿态高亮",
    # ---- 相机 / 屏幕 ----
    "u_cam_eye": "vec3  相机位置",
    "u_cam_target": "vec3  相机注视点",
    "u_cam_up": "vec3  相机上向量",
    "u_fovy": "float 竖直视场角 (rad)",
    "u_near": "float 近裁剪面",
    "u_far": "float 远裁剪面",
    "u_resolution": "vec2  渲染分辨率 (px)",
    # ---- 光照 / 材质 ----
    "u_light_dir": "vec3  平行光方向（世界系，指向光源）",
    "u_light_color": "vec3  光色",
    "u_ambient": "vec3  环境光",
    "u_base_color": "vec4  整体染色（与顶点色相乘）",
}

#: 线程序（航迹 / 地面网格）使用的 uniform
LINE_UNIFORM_CONTRACT = {
    "u_mvp": "mat4  投影 @ 视图（线几何直接给世界系顶点）",
    "u_color": "vec4  线颜色",
}


class GLContextError(RuntimeError):
    """无法创建 OpenGL 上下文（无 GPU / 无显示 / 驱动缺失）时抛出。"""


# ---------------------------------------------------------------------------
# 着色器源码（文件缺失时的内联兜底）
# ---------------------------------------------------------------------------

_FALLBACK_AIRCRAFT_VERT = """#version 330
in vec3 in_position; in vec3 in_normal; in vec3 in_color;
uniform mat4 u_model; uniform mat4 u_view; uniform mat4 u_proj; uniform mat4 u_normal_mat;
out vec3 v_normal_world; out vec3 v_color; out vec3 v_world_pos; out vec3 v_local_pos;
void main() {
    vec4 world = u_model * vec4(in_position, 1.0);
    v_world_pos = world.xyz; v_local_pos = in_position;
    v_normal_world = normalize((u_normal_mat * vec4(in_normal, 0.0)).xyz);
    v_color = in_color;
    gl_Position = u_proj * u_view * world;
}
"""

_FALLBACK_AIRCRAFT_FRAG = """#version 330
in vec3 v_normal_world; in vec3 v_color; in vec3 v_world_pos; in vec3 v_local_pos;
uniform vec3 u_light_dir; uniform vec3 u_light_color; uniform vec3 u_ambient;
uniform vec4 u_base_color; uniform float u_highlight; uniform vec3 u_cam_eye; uniform float u_alt;
out vec4 fragColor;
void main() {
    vec3 N = normalize(v_normal_world);
    vec3 V = normalize(u_cam_eye - v_world_pos);
    if (dot(N, V) < 0.0) { N = -N; }
    vec3 base = v_color * u_base_color.rgb;
    vec3 lit = base * (u_ambient + u_light_color * max(dot(N, normalize(u_light_dir)), 0.0));
    float fres = pow(1.0 - clamp(dot(N, V), 0.0, 1.0), 3.0);
    lit += u_light_color * fres * 0.22;
    lit = mix(lit, vec3(0.53, 0.72, 0.94), clamp(u_alt / 4000.0, 0.0, 0.6));
    lit = mix(lit, vec3(0.95, 0.15, 0.15), u_highlight * 0.55);
    fragColor = vec4(clamp(lit, 0.0, 1.0), u_base_color.a);
}
"""

_FALLBACK_LINE_VERT = """#version 330
in vec3 in_position; uniform mat4 u_mvp;
void main() { gl_Position = u_mvp * vec4(in_position, 1.0); }
"""

_FALLBACK_LINE_FRAG = """#version 330
uniform vec4 u_color; out vec4 fragColor;
void main() { fragColor = u_color; }
"""


def _read_shader(name: str, shader_dir: str | None, fallback: str) -> str:
    """读取 ``<shader_dir>/<name>``；文件不存在时返回内联兜底源码。"""
    root = shader_dir or SHADER_DIR
    path = os.path.join(root, name)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return fallback


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------

class _ContextHandle:
    """GL 上下文 + 关闭钩子的薄封装。"""

    def __init__(self, ctx, closer, kind: str, info: str):
        self.ctx = ctx
        self.kind = kind
        self.info = info
        self._closer = closer

    def close(self):
        if self._closer is None:
            return
        closer, self._closer = self._closer, None
        try:
            closer()
        except Exception:  # noqa: BLE001 关闭失败不应影响主流程
            pass


def _ctx_moderngl_window(width: int, height: int, _backend: str) -> _ContextHandle:
    from moderngl_window.context.glfw import Window

    win = Window(size=(width, height), title="glider-gl", visible=False)
    ctx = win.ctx
    info = f"{ctx.info.get('GL_VERSION', '?')} | {ctx.info.get('GL_RENDERER', '?')}"
    return _ContextHandle(ctx, win.close, "moderngl-window(glfw, hidden)", info)


def _ctx_raw_glfw(width: int, height: int, _backend: str) -> _ContextHandle:
    import glfw
    import moderngl

    if not glfw.init():
        raise RuntimeError("glfw.init() 失败（无可用的显示/窗口系统）")
    try:
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        win = glfw.create_window(width, height, "glider-gl", None, None)
        if not win:
            raise RuntimeError("glfw.create_window() 返回空（无法创建 GL 3.3 上下文）")
        glfw.make_context_current(win)
        ctx = moderngl.create_context()
    except Exception:
        glfw.terminate()
        raise

    def _close():
        glfw.destroy_window(win)
        glfw.terminate()

    info = f"{ctx.info.get('GL_VERSION', '?')} | {ctx.info.get('GL_RENDERER', '?')}"
    return _ContextHandle(ctx, _close, "glfw(hidden)", info)


def _ctx_egl(width: int, height: int, _backend: str) -> _ContextHandle:
    import moderngl

    ctx = moderngl.create_context(standalone=True, backend="egl")
    info = f"{ctx.info.get('GL_VERSION', '?')} | {ctx.info.get('GL_RENDERER', '?')}"
    return _ContextHandle(ctx, None, "egl(standalone)", info)


def create_context(width: int, height: int, backend: str | None = None) -> _ContextHandle:
    """按 ``auto -> window -> glfw -> egl`` 顺序尝试创建 GL 上下文。

    ``backend`` 可用 ``GLIDER_GL_CONTEXT`` 环境变量覆盖（``window`` / ``glfw`` / ``egl`` / ``auto``）。
    全部失败时抛 :class:`GLContextError`（调用方据此回退 matplotlib 渲染）。
    """
    want = (backend or os.environ.get("GLIDER_GL_CONTEXT") or "auto").strip().lower()
    order = ["window", "glfw", "egl"] if want in ("auto", "") else [want]
    makers = {"window": _ctx_moderngl_window, "glfw": _ctx_raw_glfw, "egl": _ctx_egl}

    errors = []
    for name in order:
        maker = makers.get(name)
        if maker is None:
            errors.append(f"{name}: 未知的上下文类型")
            continue
        try:
            return maker(width, height, name)
        except Exception as exc:  # noqa: BLE001 逐个降级尝试
            errors.append(f"{name}: {exc}")
    raise GLContextError("无法创建 OpenGL 上下文（" + "; ".join(errors) + "）")


# ---------------------------------------------------------------------------
# 动态线缓冲
# ---------------------------------------------------------------------------

class _LineBatch:
    """一次性线几何的容量可增长的顶点缓冲（每帧整段重写，够用且简单）。"""

    def __init__(self, ctx, program, mode):
        self.ctx = ctx
        self.program = program
        self.mode = mode
        self.vbo = None
        self.vao = None
        self.cap = 0
        self.count = 0

    def upload(self, points: np.ndarray) -> bool:
        """``points`` 为 (N, 3) 世界系顶点；返回是否有可绘制的几何。"""
        if points is None or len(points) < 2:
            self.count = 0
            return False
        data = np.ascontiguousarray(points, dtype=np.float32).tobytes()
        need = len(data)
        if self.vbo is None or need > self.cap:
            if self.vao is not None:
                self.vao.release()
                self.vbo.release()
            self.cap = max(need * 2, 4096)
            self.vbo = self.ctx.buffer(reserve=self.cap)
            self.vao = self.ctx.vertex_array(
                self.program, [(self.vbo, "3f", "in_position")])
        self.vbo.write(data)
        self.count = need // 12
        return True

    def render(self):
        if self.count >= 2 and self.vao is not None:
            self.vao.render(self.mode, vertices=self.count)

    def release(self):
        if self.vao is not None:
            self.vao.release()
            self.vao = None
        if self.vbo is not None:
            self.vbo.release()
            self.vbo = None
        self.count = 0


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------

class GliderGLRenderer:
    """把飞机模型 + 航迹 + 地面网格渲染到一个离屏 FBO。"""

    def __init__(self, width: int, height: int, mesh: Mesh, *,
                 shader_dir: str | None = None, aa: int = 1,
                 gl_backend: str | None = None):
        import moderngl

        self.width = int(width)
        self.height = int(height)
        self.aa = max(1, int(aa))
        self.rw = self.width * self.aa
        self.rh = self.height * self.aa

        self.mesh = mesh
        self.handle = create_context(self.rw, self.rh, gl_backend)
        self.ctx = self.handle.ctx
        self.info = self.handle.info

        self._missing: set[tuple[int, str]] = set()
        self.prog_air = self._build_program(
            "aircraft", _FALLBACK_AIRCRAFT_VERT, _FALLBACK_AIRCRAFT_FRAG, shader_dir)
        self.prog_line = self._build_program(
            "line", _FALLBACK_LINE_VERT, _FALLBACK_LINE_FRAG, shader_dir)

        # ---- 飞机网格 ----
        # 自定义着色器可以只用其中一部分属性（GLSL 编译器会把未使用的顶点属性整体
        # 优化掉，moderngl 此时取该名字会抛 KeyError），因此按"程序实际声明了什么"
        # 组装交错格式，缺位补 12 字节占位，保证偏移与 mesh.interleave() 的
        # pos(3f) | normal(3f) | color(3f) 布局一致。
        names, fmt = [], []
        for name in ("in_position", "in_normal", "in_color"):
            if self.prog_air.get(name, None) is not None:
                names.append(name)
                fmt.append("3f")
            elif names:
                fmt.append("12x")
        if "in_position" not in names:
            raise ValueError("飞机着色器必须声明顶点属性 in_position")

        self.vbo = self.ctx.buffer(mesh.interleave())
        self.ibo = self.ctx.buffer(np.ascontiguousarray(mesh.indices, dtype=np.uint32).tobytes())
        self.vao_air = self.ctx.vertex_array(
            self.prog_air, [(self.vbo, " ".join(fmt), *names)], self.ibo)

        # ---- 线几何 ----
        self.batch_ground = _LineBatch(self.ctx, self.prog_line, moderngl.LINES)
        self.batch_trail = _LineBatch(self.ctx, self.prog_line, moderngl.LINE_STRIP)
        # 投放点(绿) / 落点(红) 标记：每个 marker 是一族菱形折线，单独着色
        self.marker_batch = _LineBatch(self.ctx, self.prog_line, moderngl.LINE_STRIP)
        self._markers: list[tuple[np.ndarray, tuple]] = []

        # ---- 离屏帧缓冲 ----
        self.color_tex = self.ctx.texture((self.rw, self.rh), 3)
        self.depth_tex = self.ctx.depth_texture((self.rw, self.rh))
        self.fbo = self.ctx.framebuffer(
            color_attachments=[self.color_tex], depth_attachment=self.depth_tex)

        # 相机 / 模型矩阵（由 set_camera / set_aircraft 更新）
        self.view = np.eye(4, dtype=np.float32)
        self.proj = np.eye(4, dtype=np.float32)
        self.mvp_line = np.eye(4, dtype=np.float32)
        self.model = np.eye(4, dtype=np.float32)
        self.cam_eye = np.zeros(3, dtype=np.float32)
        self.cam_target = np.zeros(3, dtype=np.float32)
        self.cam_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        self.fovy = np.radians(45.0)
        self.near = 1.0
        self.far = 5000.0
        self._uniform_snapshot: dict = {}

    # ---- 构建 ----

    def _build_program(self, stem: str, fb_vert: str, fb_frag: str, shader_dir: str | None):
        vert = _read_shader(f"{stem}.vert", shader_dir, fb_vert)
        frag = _read_shader(f"{stem}.frag", shader_dir, fb_frag)
        try:
            return self.ctx.program(vertex_shader=vert, fragment_shader=frag)
        except Exception as exc:  # noqa: BLE001 自定义着色器编译失败时退回内联版本
            print(f"[gl] {stem} 着色器编译失败，改用内联默认着色器：{exc}")
            return self.ctx.program(vertex_shader=fb_vert, fragment_shader=fb_frag)

    def _set(self, program, name: str, value):
        """写入 uniform；着色器未声明该名字时静默跳过（并缓存，避免逐帧重试）。

        ``bytes`` 走 ``Uniform.write()``（矩阵专用，见 :func:`gl_bytes`），其余交给
        ``Uniform.value``（标量 / 向量）。GLSL 编译器会优化掉未被使用的 uniform，
        因此"取不到名字"属于正常情况，不算错误。
        """
        key = (id(program), name)
        if key in self._missing:
            return
        try:
            slot = program[name]
        except KeyError:
            self._missing.add(key)
            return
        try:
            if isinstance(value, (bytes, bytearray, memoryview)):
                slot.write(bytes(value))
            else:
                slot.value = value
        except Exception as exc:  # noqa: BLE001 类型不符时给出一次明确提示
            self._missing.add(key)
            print(f"[gl] uniform {name} 写入失败（已跳过）：{exc}")

    # ---- 相机 ----

    def set_camera(self, eye, target, up=(0.0, 1.0, 0.0), fovy=np.radians(45.0),
                   near=1.0, far=5000.0):
        self.cam_eye = np.asarray(eye, dtype=np.float32).reshape(3)
        self.cam_target = np.asarray(target, dtype=np.float32).reshape(3)
        self.cam_up = np.asarray(up, dtype=np.float32).reshape(3)
        self.fovy = float(fovy)
        self.near = float(near)
        self.far = float(far)

        aspect = self.rw / float(self.rh)
        self.view = mat4_look_at(self.cam_eye, self.cam_target, self.cam_up)
        self.proj = mat4_perspective(self.fovy, aspect, self.near, self.far)
        self.mvp_line = mat4_mul(self.proj, self.view)

        self._set(self.prog_air, "u_view", gl_bytes(self.view))
        self._set(self.prog_air, "u_proj", gl_bytes(self.proj))
        self._set(self.prog_line, "u_mvp", gl_bytes(self.mvp_line))
        self._set(self.prog_air, "u_cam_eye", tuple(float(v) for v in self.cam_eye))
        self._set(self.prog_air, "u_cam_target", tuple(float(v) for v in self.cam_target))
        self._set(self.prog_air, "u_cam_up", tuple(float(v) for v in self.cam_up))
        self._set(self.prog_air, "u_fovy", self.fovy)
        self._set(self.prog_air, "u_near", self.near)
        self._set(self.prog_air, "u_far", self.far)
        self._set(self.prog_air, "u_resolution", (float(self.width), float(self.height)))
        self._uniform_snapshot.update({
            "u_cam_eye": [float(v) for v in self.cam_eye],
            "u_cam_target": [float(v) for v in self.cam_target],
            "u_cam_up": [float(v) for v in self.cam_up],
            "u_fovy": self.fovy, "u_near": self.near, "u_far": self.far,
            "u_resolution": [self.width, self.height],
            "u_view": np.asarray(self.view).tolist(),
            "u_proj": np.asarray(self.proj).tolist(),
        })

    # ---- 飞机 ----

    def set_aircraft(self, pos, quat, state: dict, scale: float = 1.0,
                     corr_deg=(0.0, 0.0, 0.0)):
        """上传"控制飞机姿态"的全部参数与相关变换（见 :data:`UNIFORM_CONTRACT`）。"""
        corr = mat4_rot_xyz(corr_deg) if any(abs(float(d)) > 1e-12 for d in corr_deg) else None
        self.model = mat4_from_pos_quat_scale(pos, quat, scale, corr)
        view_model = mat4_mul(self.view, self.model)
        mvp = mat4_mul(self.proj, view_model)
        nrm = normal_matrix(view_model)

        pos = np.asarray(pos, dtype=np.float64).reshape(3)
        quat = np.asarray(quat, dtype=np.float64).reshape(4)

        self._set(self.prog_air, "u_model", gl_bytes(self.model))
        self._set(self.prog_air, "u_mvp", gl_bytes(mvp))
        self._set(self.prog_air, "u_normal_mat", gl_bytes(nrm))

        self._set(self.prog_air, "u_pos", tuple(float(v) for v in pos))
        self._set(self.prog_air, "u_quat", tuple(float(v) for v in quat))
        self._set(self.prog_air, "u_euler", tuple(float(v) for v in state["euler"]))
        self._set(self.prog_air, "u_vel", tuple(float(v) for v in state["vel"]))
        self._set(self.prog_air, "u_omega", tuple(float(v) for v in state["omega"]))
        self._set(self.prog_air, "u_scale", float(scale))
        self._set(self.prog_air, "u_time", float(state["time"]))
        self._set(self.prog_air, "u_frame", int(state["frame"]))

        for name in ("alt", "V", "alpha", "beta", "CL", "CD", "sink",
                     "bank", "pitch", "heading",
                     "elevator", "aileron", "rudder", "highlight"):
            self._set(self.prog_air, f"u_{name}", float(state[name]))

        # 光照 / 材质
        self._set(self.prog_air, "u_light_dir", LIGHT_DIR)
        self._set(self.prog_air, "u_light_color", LIGHT_COLOR)
        self._set(self.prog_air, "u_ambient", AMBIENT)
        self._set(self.prog_air, "u_base_color", BASE_COLOR)

        self._uniform_snapshot.update({
            "u_model": np.asarray(self.model).tolist(),
            "u_mvp": np.asarray(mvp).tolist(),
            "u_normal_mat": np.asarray(nrm).tolist(),
            "u_pos": [float(v) for v in pos],
            "u_quat": [float(v) for v in quat],
            "u_euler": [float(v) for v in state["euler"]],
            "u_vel": [float(v) for v in state["vel"]],
            "u_omega": [float(v) for v in state["omega"]],
            "u_scale": float(scale),
            "u_time": float(state["time"]),
            "u_frame": int(state["frame"]),
            "u_light_dir": list(LIGHT_DIR),
            "u_light_color": list(LIGHT_COLOR),
            "u_ambient": list(AMBIENT),
            "u_base_color": list(BASE_COLOR),
        })
        for name in ("alt", "V", "alpha", "beta", "CL", "CD", "sink",
                     "bank", "pitch", "heading",
                     "elevator", "aileron", "rudder", "highlight"):
            self._uniform_snapshot[f"u_{name}"] = float(state[name])

    def uniform_snapshot(self) -> dict:
        """最近一帧写入的全部 uniform（供 ``--dump-uniforms`` 自检）。"""
        return dict(self._uniform_snapshot)

    # ---- 绘制 ----

    def set_markers(self, markers, scale=1.0):
        """设置投放点(绿) / 落点(红) 标记。

        ``markers``：世界坐标列表，均画为以该点为中心的三向菱形（半宽 ``6*scale`` 米）。
        与 mpl 路径的 ``ax.scatter`` 起止点标记对应，颜色由 mpl 同款绿/红。
        """
        self._markers = []
        p0 = np.asarray(markers[0], dtype=np.float32)
        p1 = np.asarray(markers[1], dtype=np.float32)
        s = 6.0 * float(scale)
        for p, col in ((p0, (0.10, 0.62, 0.22, 1.0)),
                       (p1, (0.86, 0.20, 0.20, 1.0))):
            pts = np.array([
                [0, s, 0], [s, 0, 0], [0, -s, 0], [-s, 0, 0], [0, s, 0],   # x-y 菱形(闭环)
                [s, 0, 0], [0, 0, s], [-s, 0, 0], [0, 0, -s], [s, 0, 0],   # x-z 菱形(闭环)
                [0, s, 0], [0, 0, s], [0, -s, 0], [0, 0, -s], [0, s, 0],   # y-z 菱形(闭环)
            ], dtype=np.float32) + p
            self._markers.append((pts, col))

    def draw(self, ground_lines=None, trail_points=None) -> np.ndarray:
        """渲染一帧并回读像素，返回 ``(height, width, 3) uint8``（与 matplotlib 路径一致）。"""
        import moderngl

        ctx = self.ctx
        self.fbo.use()
        ctx.viewport = (0, 0, self.rw, self.rh)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)     # 薄部件 / 方向不定的 OBJ 更安全
        ctx.clear(*SKY_COLOR, 1.0)

        # 地面网格 + 航迹（纯色线程序）
        if self.batch_ground.upload(ground_lines):
            self._set(self.prog_line, "u_color", GROUND_COLOR)
            self.batch_ground.render()
        if self.batch_trail.upload(trail_points):
            self._set(self.prog_line, "u_color", TRAIL_COLOR)
            self.batch_trail.render()

        # 投放点 / 落点标记（逐条分色渲染）
        for pts, col in self._markers:
            if self.marker_batch.upload(pts):
                self._set(self.prog_line, "u_color", col)
                self.marker_batch.render()

        # 飞机（模型 + 着色器）
        self.vao_air.render(moderngl.TRIANGLES)

        raw = self.fbo.read(components=3)
        img = np.frombuffer(raw, dtype=np.uint8).reshape(self.rh, self.rw, 3)
        img = np.flipud(img)                # GL 行序自下而上
        if self.aa > 1:
            img = _downscale(img, self.width, self.height)
        return np.ascontiguousarray(img)

    def close(self):
        for obj in (self.batch_ground, self.batch_trail, self.marker_batch):
            obj.release()
        for obj in (self.fbo, self.color_tex, self.depth_tex, self.vao_air, self.vbo, self.ibo):
            try:
                obj.release()
            except Exception:  # noqa: BLE001
                pass
        for prog in (self.prog_air, self.prog_line):
            try:
                prog.release()
            except Exception:  # noqa: BLE001
                pass
        self.handle.close()


def _downscale(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """超采样降采样（简单的抗锯齿；Pillow 已是本模块依赖）。"""
    from PIL import Image
    im = Image.fromarray(img).resize((width, height), Image.LANCZOS)
    return np.asarray(im)


# ---------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------

def _hud_font(height: int):
    from PIL import ImageFont
    size = max(11, int(round(height / 64.0)))
    try:
        import matplotlib
        path = os.path.join(os.path.dirname(matplotlib.__file__),
                            "mpl-data", "fonts", "ttf", "DejaVuSansMono.ttf")
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 退回 PIL 默认位图字体
        pass
    return ImageFont.load_default()


def draw_hud(img: np.ndarray, text: str) -> np.ndarray:
    """在帧上叠加半透明白底黑字的 HUD（与 matplotlib 路径的文字内容一致）。"""
    if not text:
        return img
    from PIL import Image, ImageDraw
    im = Image.fromarray(img)
    drawer = ImageDraw.Draw(im, "RGBA")
    font = _hud_font(img.shape[0])
    x0, y0 = max(8, img.shape[1] // 36), max(8, img.shape[0] // 24)
    box = drawer.multiline_textbbox((x0 + 8, y0 + 6), text, font=font, spacing=4)
    drawer.rectangle([x0, y0, box[2] + 8, box[3] + 6],
                     fill=(255, 255, 255, 190), outline=(190, 190, 190, 255))
    drawer.multiline_text((x0 + 8, y0 + 6), text, font=font,
                          fill=(5, 5, 12, 255), spacing=4)
    return np.asarray(im)


# ---------------------------------------------------------------------------
# 网格解析
# ---------------------------------------------------------------------------

def resolve_mesh(glider, model_path: str | None = None, model_scale: float = 0.0,
                 model_rot=(0.0, 0.0, 0.0), log=print) -> Mesh:
    """优先加载外部 OBJ 模型；缺失/失败时退回程序化盒体网格。

    ``model_rot`` / ``model_scale`` 只对外部模型生效（程序化网格的尺寸已与机身一致）。
    """
    path = model_path
    if not path:  # 未显式指定：按 airplane.obj -> airplane.glb 顺序查找默认模型
        for cand in (DEFAULT_MODEL_PATH, DEFAULT_MODEL_GLB):
            if os.path.isfile(cand):
                path = cand
                break
    if path:
        ext = os.path.splitext(path)[1].lower()
        loader = load_glb if ext in (".glb", ".gltf") else load_obj
        try:
            mesh = fit_mesh(loader(path), glider.length,
                            rot_deg=model_rot, scale=model_scale)
            log(f"[gl] loaded model: {path}  ({mesh.triangle_count} tris)")
            return mesh
        except Exception as exc:  # noqa: BLE001 模型有问题不应中断仿真
            log(f"[gl] 模型加载失败({path})，改用程序化网格：{exc}")
    mesh = procedural_mesh(glider)
    log(f"[gl] 使用程序化网格（{mesh.triangle_count} tris）")
    return mesh


# ---------------------------------------------------------------------------
# 逐帧状态
# ---------------------------------------------------------------------------

def _omega_world(tele, idx: int) -> np.ndarray:
    """由相邻帧四元数差分求世界系角速度。"""
    if idx <= 0:
        return np.zeros(3)
    t0, t1 = float(tele["t"][idx - 1]), float(tele["t"][idx])
    dt = t1 - t0
    if dt <= 1e-9:
        return np.zeros(3)
    q0 = np.asarray(tele["quat"][idx - 1], dtype=np.float64)
    q1 = np.asarray(tele["quat"][idx], dtype=np.float64)
    axis, angle = quat_to_axis_angle(quat_mul(q1, quat_conjugate(q0)))
    return axis * (angle / dt)


def frame_state(tele, idx: int, cfg_view: dict, scale: float) -> dict:
    """把第 ``idx`` 帧的遥测整理成 uniform 契约需要的状态字典。"""
    quat = np.asarray(tele["quat"][idx], dtype=np.float64)
    roll, pitch, yaw = euler_from_quat(quat)
    bank = float(tele["bank"][idx])

    if "highlight" in cfg_view:
        highlight = float(cfg_view["highlight"])
    else:
        # 自动：坡度超过 60° 视为接近失控，标红提示
        highlight = 1.0 if abs(bank) > 60.0 else 0.0

    def g(key):
        arr = tele.get(key)
        return float(arr[idx]) if arr is not None and len(arr) > idx else 0.0

    return {
        "time": g("t"),
        "frame": int(idx),
        "pos": np.asarray(tele["pos"][idx], dtype=np.float64),
        "quat": quat,
        "euler": np.array([roll, pitch, yaw], dtype=np.float64),
        "vel": np.asarray(tele["vel"][idx], dtype=np.float64),
        "omega": _omega_world(tele, idx),
        "alt": g("alt"),
        "V": g("V"),
        "alpha": g("alpha"),
        "beta": g("beta"),
        "CL": g("CL"),
        "CD": g("CD"),
        "sink": g("sink"),
        "bank": bank,
        "pitch": g("pitch"),
        "heading": float(np.degrees(body_axis_heading(quat))),
        "elevator": g("elevator"),
        "aileron": g("aileron"),
        "rudder": g("rudder"),
        "highlight": highlight,
        "scale": float(scale),
    }


# ---------------------------------------------------------------------------
# 相机
# ---------------------------------------------------------------------------

def fixed_camera(bounds, aspect, fovy=np.radians(45.0), elev_deg=30.0, azim_deg=-90.0):
    """固定机位：取景覆盖整条飞行走廊（与 matplotlib 固定机位观感一致）。

    ``bounds`` 来自 ``render._flight_view_bounds``：(x0, x1, alt0, alt1, z0, z1)。
    相机朝向按 mpl 的 ``elev/azim`` 定义换算到世界系（Y 上）。

    注意方位角的 **镜像**：mpl 路径把世界 ``(x, alt, z)`` 放进 mpl 的 ``(x, z, alt)``
    布局（见 ``render._u``），这是行列式 -1 的左手嵌入，于是同一个 ``azim`` 在 mpl
    画面上的左右与在世界系里恰好相反。要让 GL 画面里"飞机沿 +x 由左向右飞"（与
    mpl 固定机位视频一致），方位角的正弦项需取反。
    """
    x0, x1, alt0, alt1, z0, z1 = (float(v) for v in bounds)
    center = np.array([(x0 + x1) / 2.0, (alt0 + alt1) / 2.0, (z0 + z1) / 2.0])

    e, a = np.radians(elev_deg), np.radians(azim_deg)
    direction = np.array([np.cos(e) * np.cos(a), np.sin(e), -np.cos(e) * np.sin(a)])

    # 相机基向量与距离无关（始终朝 center 看），因此可先把 8 个角点投到相机系，
    # 再解出"恰好装下整条走廊"的距离——比用包围球保守估计近得多，飞机不会被缩成点。
    f = -direction
    s = np.cross(f, np.array([0.0, 1.0, 0.0]))
    ns = np.linalg.norm(s)
    s = np.array([1.0, 0.0, 0.0]) if ns < 1e-9 else s / ns
    u = np.cross(s, f)

    tan_v = max(float(np.tan(fovy * 0.5)), 1e-6)
    tan_h = tan_v * max(float(aspect), 1e-6)
    corners = np.array([[x, y, z]
                        for x in (x0, x1) for y in (alt0, alt1) for z in (z0, z1)])
    rel = corners - center
    # 角点在相机系下的横向 / 纵向偏移是固定的，只有深度随 dist 平移
    need = np.maximum(np.abs(rel @ s) / tan_h, np.abs(rel @ u) / tan_v)
    dist = max(float(np.max(rel @ f + need)) * 1.06, 1.0)

    eye = center + direction * dist
    return eye, center, dist


def chase_camera(pos, quat, cfg_view):
    """追逐机位：机体后上方 3/4 视角（迁移 matplotlib 路径的机位算法）。"""
    R = quat_to_matrix(quat)
    xb = R[:, 0]
    dist = float(cfg_view.get("dist", 55.0))
    height = float(cfg_view.get("height", 34.0))
    lateral = float(cfg_view.get("lateral", 26.0))

    xz = np.array([xb[0], 0.0, xb[2]], dtype=np.float64)
    n = np.linalg.norm(xz)
    xz = np.array([1.0, 0.0, 0.0]) if n < 1e-6 else xz / n

    up = np.array([0.0, 1.0, 0.0])
    side = np.cross(up, xz)
    sn = np.linalg.norm(side)
    side = -side / sn if sn > 1e-9 else np.array([0.0, 0.0, 1.0])

    pos = np.asarray(pos, dtype=np.float64)
    eye = pos - xz * dist + up * height + side * lateral
    target = pos + xz * 8.0
    return eye, target, dist


def ground_grid(bounds, spacing=80.0) -> np.ndarray:
    """走廊范围内的地面网格线（y=0 水平面），返回 (2N, 3) 顶点供 LINES 绘制。"""
    x0, x1, _alt0, _alt1, z0, z1 = (float(v) for v in bounds)
    pts = []
    x = np.floor(x0 / spacing) * spacing
    while x <= x1 + spacing:
        pts.append((x, 0.0, z0))
        pts.append((x, 0.0, z1))
        x += spacing
    z = np.floor(z0 / spacing) * spacing
    while z <= z1 + spacing:
        pts.append((x0, 0.0, z))
        pts.append((x1, 0.0, z))
        z += spacing
    return np.asarray(pts, dtype=np.float32).reshape(-1, 3)


def ground_patch(glider_pos, size=300.0, spacing=30.0) -> np.ndarray:
    """随飞机移动的地面网格（追逐机位用，对应 ``render._ground_patch``）。"""
    x0 = np.floor((glider_pos[0] - size / 2.0) / spacing) * spacing
    z0 = np.floor((glider_pos[2] - size / 2.0) / spacing) * spacing
    pts = []
    x = x0
    while x <= glider_pos[0] + size / 2.0:
        pts.append((x, 0.0, z0))
        pts.append((x, 0.0, z0 + size))
        x += spacing
    z = z0
    while z <= glider_pos[2] + size / 2.0:
        pts.append((x0, 0.0, z))
        pts.append((x0 + size, 0.0, z))
        z += spacing
    return np.asarray(pts, dtype=np.float32).reshape(-1, 3)


# ---------------------------------------------------------------------------
# MP4 输出（与 render.make_video 同构）
# ---------------------------------------------------------------------------

def make_video_gl(tele, glider, out_path, fps=15, start=0.0, end=None,
                  cfg_view=None, progress=print, hud=False, camera="fixed",
                  size=(1280, 720), aa=1, codec="libx264", quality=6,
                  model_path=None, shader_dir=None, model_scale=0.0,
                  model_rot=(0.0, 0.0, 0.0), preview_png=None, dump_uniforms=False,
                  gl_backend=None) -> str:
    """用 OpenGL 渲染飞行回放 MP4（帧率/取帧/编码与 ``render.make_video`` 完全一致）。

    无法创建 GL 上下文或缺少编码依赖时抛异常，由调用方决定回退 matplotlib。
    """
    try:
        import imageio.v2 as imageio
        import imageio_ffmpeg  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise ImportError("缺少视频编码依赖 imageio-ffmpeg：请先 pip install imageio-ffmpeg") from exc

    cfg_view = {} if cfg_view is None else dict(cfg_view)
    times = tele["t"]
    if end is None:
        end = float(times[-1])
    n_frames = int(round((end - start) * fps))

    width, height = int(size[0]), int(size[1])
    mesh = resolve_mesh(glider, model_path, model_scale, model_rot, log=progress or print)

    renderer = GliderGLRenderer(width, height, mesh, shader_dir=shader_dir, aa=aa,
                               gl_backend=gl_backend)
    if progress:
        progress(f"[gl] 上下文：{renderer.handle.kind} | {renderer.info}")

    # 固定机位：取景盒与地面网格一次算好
    bounds = _flight_view_bounds(tele) if camera == "fixed" else None
    grid = ground_grid(bounds, float(cfg_view.get("spacing", 80.0))) if bounds else None
    trail_n = max(20, int(cfg_view.get("trail", 5000)))
    aspect = width / float(height)

    # 竖直增强（仅固定机位，--gl-vert）：mpl 路径用 set_box_aspect(1,1,1)，
    # matplotlib 会把高度轴拉满整条盒边，使高度波动被明显放大；GL 是真透视等比例
    # 投影，150 m 高度只占总走廊的一小段，竖向波动显得"平"。为靠近 mpl 观感，
    # 把世界 y 乘上 vert 系数，同时同步拉伸取景盒高度上限（地面 y=0 保持不变）。
    vert_k = float(cfg_view.get("vert", 1.0))
    if camera == "fixed" and vert_k != 1.0:
        cam_bounds = (bounds[0], bounds[1], bounds[2], bounds[3] * vert_k,
                      bounds[4], bounds[5])
        pos_view = np.asarray(tele["pos"], dtype=np.float32).copy()
        pos_view[:, 1] *= vert_k
    else:
        vert_k = 1.0
        cam_bounds = bounds
        pos_view = tele["pos"]

    # 投放点 / 落点标记（与 mpl 一致）：绿=起点、红=终点，尺寸随显示放大倍数
    mark_scale = float(cfg_view.get("scale", 6.0)) if camera == "fixed" else 1.0
    renderer.set_markers([pos_view[0], pos_view[-1]], scale=mark_scale)

    writer = imageio.get_writer(
        out_path, fps=fps, codec=codec, quality=quality,
        pixelformat="yuv420p", macro_block_size=None)
    try:
        for k in range(n_frames):
            t = start + k / fps
            idx = int(np.searchsorted(times, t))
            if idx >= len(times):
                break

            pos = np.asarray(pos_view[idx], dtype=np.float64)
            quat = np.asarray(tele["quat"][idx], dtype=np.float64)
            if camera == "fixed":
                scale = float(cfg_view.get("scale", 6.0))
                eye, target, dist = fixed_camera(cam_bounds, aspect)
                grid_frame = grid
            else:
                scale = float(cfg_view.get("scale", 1.0))
                eye, target, dist = chase_camera(pos, quat, cfg_view)
                grid_frame = ground_patch(pos, float(cfg_view.get("ground", 300.0)),
                                          float(cfg_view.get("spacing", 30.0)))

            renderer.set_camera(eye, target, (0.0, 1.0, 0.0), np.radians(45.0),
                                near=max(1.0, dist * 0.01), far=max(100.0, dist * 10.0))
            state = frame_state(tele, idx, cfg_view, scale)
            # 模型朝向修正在 resolve_mesh -> fit_mesh 里已经烘进网格顶点，
            # 这里不再重复传给 corr_deg，避免二次旋转。
            renderer.set_aircraft(pos, quat, state, scale=scale)

            trail = np.asarray(pos_view[max(0, idx - trail_n):idx + 1], dtype=np.float32)
            img = renderer.draw(ground_lines=grid_frame, trail_points=trail)
            if hud:
                img = draw_hud(img, _hud_text(tele, idx))

            if preview_png and k == 0:
                _save_png(img, preview_png)
            if dump_uniforms and k == 0:
                _dump_uniforms(renderer, progress)

            writer.append_data(np.ascontiguousarray(img))
            if progress and (k % max(1, n_frames // 10) == 0):
                progress(f"gl video frame {k}/{n_frames} t={t:.1f}s")
    finally:
        writer.close()
        renderer.close()
    return out_path


def _save_png(img: np.ndarray, path: str) -> str:
    from PIL import Image
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(img).save(path)
    return path


def _dump_uniforms(renderer, progress):
    """把首帧 uniform 快照打印为 JSON（自检契约是否按预期填充）。"""
    snapshot = renderer.uniform_snapshot()
    text = json.dumps(snapshot, ensure_ascii=False)
    if progress:
        progress(f"[gl] uniform 快照（{len(snapshot)} 项）：{text}")
    return snapshot