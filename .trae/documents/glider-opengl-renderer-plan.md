# 为 glider 仿真加入 OpenGL 渲染路径

## 1. 摘要

在 `simulation/glider/` 现有 matplotlib 渲染（`render.py`）之外，新增一条 **OpenGL（GPU）渲染途径**：

* 使用 **moderngl + moderngl-window** 创建隐藏窗口/离屏上下文，渲染到 FBO；

* 逐帧渲染 → 复用现有 **imageio-ffmpeg** 编码为 `flight_replay.mp4`，**接入现有回放管线**；

* 支持**可替换的外部 GLSL 顶点/片段着色器**（`shaders/*.vert|frag`）；

* 支持**读取飞机模型**：优先加载 `assets/` 下的 OBJ 模型，缺失时回退到由 `aircraft.parts()` 派生的程序化三角网格；

* 通过 **uniform 契约** 把"控制飞机姿态所需的所有参数 + 渲染所需的各种变换"完整暴露给着色器（详见第 5 节）。

前端 `Simulator.jsx` 播放逻辑、后端文件白名单**均无需改动**。

***

## 2. 现状分析

### 2.1 现有渲染链路（将被兼容保留）

| 文件                                 | 职责                                                                                                                                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `simulation/glider/aircraft.py`    | 滑翔机几何/质量/气动面；`Glider.parts()` 返回 7 个盒体部件 `(name, center, half, rgba)`                                                                                                                                        |
| `simulation/glider/render.py`      | matplotlib 渲染：`draw_world_frame`（固定机位）/`draw_scene`（追逐机位）、`make_video`（MP4）、`render_frames`（PNG 序列）、`make_gif`；`_flight_view_bounds` 计算固定机位取景盒；`_hud_text` 生成 HUD 文本（纯函数，可复用）                                |
| `simulation/glider/sim_service.py` | headless 入口：`run_flight` → CSV/PNG/`summary.json`；`--video` 时调 `render.make_video(camera="fixed", cfg_view=dict(spacing=80, trail=5000, elev=30, azim=-90, scale=6.0, ...), hud=True)`；`--probe` 输出环境探测 JSON |
| `simulation/glider/plot_flight.py` | 2D 遥测曲线 + 3D 航迹图（本任务不动）                                                                                                                                                                                      |
| `simulation/glider/spatial.py`     | `quat_to_matrix` 等刚体数学（GL 侧复用）                                                                                                                                                                               |

### 2.2 坐标约定（GL 侧的重要优势）

* 世界系 **Y 向上**，机体系 **x 前 / y 上 / z 右翼**（`aircraft.py` 头部注释、`aero.py`）。

* OpenGL 默认也是 Y-up，因此 **无需像 matplotlib 那样做 z-up 换轴**（`render._u` / `plot_flight._zup` 那一层可以完全省掉）。

### 2.3 环境现状（已实测）

* 系统 `python` = `C:\Python314\python.exe`（3.14.7）；**Anaconda =** **`C:\Users\DSwer\anaconda3\python.exe`（3.13.9）**，已装 numpy 2.3.5 / matplotlib 3.10.6 / imageio / **imageio-ffmpeg 0.6.0** / pillow 12.3.0。

* **未安装任何 GL 绑定库**（无 moderngl / moderngl-window / glfw / PyOpenGL / trimesh）。

* GPU：**NVIDIA RTX 5060 Laptop** + Intel Arc 140T。

* 仓库内**无任何** **`.obj/.glb`** **飞机模型文件**。

### 2.4 平台接线现状

* `backend/controllers/gliderController.js`：`GLIDER_VIDEO/GLIDER_VIDEO_FPS/GLIDER_VIDEO_MAX` 控制 `--video*`；spawn `sim_service.py`（原生 或 `wsl:<distro>:<python>`）。

* 文件白名单 `ALLOWED_FILES = {trajectory3d.png, flight_telemetry.png, flight_telemetry.csv, summary.json, flight_replay.mp4}`（新增产物默认不可下载，安全）。

* `frontend/src/pages/glider/Simulator.jsx` 只消费 `trajectory3d.png` / `flight_telemetry.png` / `flight_replay.mp4`。

***

## 3. 已确认决策（来自用户）

| 项     | 决策                                                                                           |
| ----- | -------------------------------------------------------------------------------------------- |
| 产物与接入 | **接入现有回放管线**：GL 离屏渲染逐帧 → 仍输出 `flight_replay.mp4`；`sim_service.py` 新增 `--renderer gl` 切换；前端不动 |
| GL 绑定 | **moderngl + moderngl-window**                                                               |
| 模型来源  | **两者都支持，默认程序化**：`assets/` 有模型则优先加载（OBJ），否则用 `aircraft.parts()` 派生的三角网格                       |

***

## 4. 依赖与环境

写入 `simulation/glider/requirements.txt`（追加，保留原有条目）：

```
# OpenGL 渲染途径（--renderer gl）
moderngl>=5.10
moderngl-window>=2.4
glfw>=2.6
```

安装（本机 Anaconda）：

```powershell
& "C:\Users\DSwer\anaconda3\python.exe" -m pip install moderngl moderngl-window glfw
```

**上下文创建策略（实现时按序尝试，全部封装在** **`render_gl._create_context()`** **内）**：

1. 首选 `moderngl_window.context.glfw.Window(..., visible=False)`（隐藏窗口，Windows 可用）；
2. 若不可用，回退 `glfw.create_window(..., GLFW_VISIBLE=False)` + `moderngl.create_context()`（直接附着当前 GL 上下文，规避 moderngl-window 在 3.13 上的兼容风险）；
3. Linux/WSL 无显示环境：尝试 `moderngl.create_context(standalone=True, backend="egl")`；失败的兜底见 §9。
4. 允许环境变量 `GLIDER_GL_CONTEXT=auto|window|glfw|egl` 强制指定，默认 `auto`。

***

## 5. Uniform 契约（本任务核心）

所有 uniform 由 `render_gl.GliderGLRenderer.set_aircraft(...)` / `set_camera(...)` 逐帧写入。**契约以** **`render_gl.UNIFORM_CONTRACT`（模块级 dict）登记并在** **`glider/README.md`** **中成表文档化**，供他人自行编写着色器。

### 5.1 变换类（渲染所需的各种变换）

| Uniform        | 类型   | 含义                                                                                  |
| -------------- | ---- | ----------------------------------------------------------------------------------- |
| `u_model`      | mat4 | 模型矩阵：`T(u_pos) · R(u_quat) · S(u_scale) · M_corr`（`M_corr` = `--model-rot` 的模型朝向修正） |
| `u_view`       | mat4 | 世界系 → 相机系（`look_at(u_cam_eye, u_cam_target, u_cam_up)`）                             |
| `u_proj`       | mat4 | 相机系 → 裁剪空间（透视，`u_fovy/u_near/u_far`）                                                |
| `u_mvp`        | mat4 | `u_proj · u_view · u_model`（现成，供想直接用的自定义着色器）                                        |
| `u_normal_mat` | mat4 | `transpose(inverse(u_view · u_model))` 的左上 3×3（法线变换）                                |

顶点着色器中默认写法：

```glsl
gl_Position = u_proj * u_view * u_model * vec4(in_position, 1.0);
```

### 5.2 姿态与飞行状态（控制飞机姿态所需的所有参数，全部显式暴露）

| Uniform                                 | 类型    | 来源（`tele` 字段 / 推导）                                 |
| --------------------------------------- | ----- | -------------------------------------------------- |
| `u_pos`                                 | vec3  | 世界位置 `[x, alt, z]`（`tele["pos"][idx]`）             |
| `u_quat`                                | vec4  | 姿态四元数 xyzw（`tele["quat"][idx]`）                    |
| `u_euler`                               | vec3  | `(roll, pitch, yaw)` 弧度（`spatial.euler_from_quat`） |
| `u_vel`                                 | vec3  | 世界速度（`tele["vel"][idx]`）                           |
| `u_omega`                               | vec3  | 角速度（世界系；由相邻帧四元数差分求得）                               |
| `u_alt`                                 | float | 高度 m                                               |
| `u_V`                                   | float | 空速 m/s                                             |
| `u_alpha` / `u_beta`                    | float | 迎角 / 侧滑角 rad                                       |
| `u_CL` / `u_CD`                         | float | 升力 / 阻力系数                                          |
| `u_sink`                                | float | 下沉率 m/s                                            |
| `u_bank` / `u_pitch` / `u_heading`      | float | 坡度 / 俯仰 / 航向（度）                                    |
| `u_elevator` / `u_aileron` / `u_rudder` | float | 三个舵面偏转（供着色器做舵面动画/高亮）                               |
| `u_time`                                | float | 当前仿真时间 s                                           |
| `u_frame`                               | int   | 帧序号                                                |

### 5.3 相机 / 屏幕

| Uniform                                   | 类型    | 含义        |
| ----------------------------------------- | ----- | --------- |
| `u_cam_eye` / `u_cam_target` / `u_cam_up` | vec3  | 相机基元      |
| `u_fovy` / `u_near` / `u_far`             | float | 透视参数      |
| `u_resolution`                            | vec2  | 渲染分辨率（像素） |

### 5.4 光照 / 材质 / 风格

| Uniform                       | 类型    | 含义                                            |
| ----------------------------- | ----- | --------------------------------------------- |
| `u_light_dir`                 | vec3  | 平行光方向（世界系，归一化）                                |
| `u_light_color` / `u_ambient` | vec3  | 光色 / 环境光                                      |
| `u_base_color`                | vec4  | 整体染色（与顶点色相乘）                                  |
| `u_scale`                     | float | 飞机显示放大倍数（固定机位默认 6.0，追逐机位默认 1.0）               |
| `u_highlight`                 | float | 0/1，高亮（如失控/失速标红），由 `--gl-highlight-on` 触发条件控制 |

### 5.5 线程序（`line.vert` / `line.frag`，用于航迹与地面网格）

| Uniform   | 类型   |
| --------- | ---- |
| `u_mvp`   | mat4 |
| `u_color` | vec4 |

**不做贴图**（MVP 用顶点色 + 光照即可），需贴图时用户可自行改着色器 + 加 `sampler2D`——在 `glider/README.md` 中说明扩展方式。

***

## 6. 新增文件

### 6.1 `simulation/glider/gl_math.py`（纯 numpy，无 GL 依赖）

* `mat4_identity()` / `mat4_mul(a, b)`

* `mat4_from_pos_quat_scale(pos, quat, scale, corr=None)` — 由 `spatial.quat_to_matrix` 组装

* `mat4_translate(v)` / `mat4_scale(s)` / `mat4_rot_xyz(deg)`

* `mat4_look_at(eye, target, up)`

* `mat4_perspective(fovy_rad, aspect, near, far)`

* `normal_matrix(model_view)` — `inverse` 转置取左上 3×3，扩成 mat4

* 全部返回 `np.float32` 数组（`tobytes()` 直接喂 moderngl）

**为什么**：GL 需要 4×4 矩阵，`spatial.py` 只有 3×3 旋转与四元数；这些是纯数学，独立成模块便于单测/复用。

### 6.2 `simulation/glider/gl_mesh.py`

* `Mesh` 数据类：`positions (N,3) f4`、`normals (N,3) f4`、`colors (N,3) f4`、`indices (M,) u4`

* `box_mesh(center, half, rgba)` — 一个盒体 → 12 三角形（每面 2 三角，面法线），带顶点色

* `procedural_mesh(glider)` — 遍历 `glider.parts()`，拼成单个 Mesh（`colors` 取 rgba\[:3]）

* `load_obj(path, color=(0.82,0.82,0.86))` — OBJ 解析：

  * 支持 `v` / `vn` / `f`；面格式 `v`、`v/vt`、`v//vn`、`v/vt/vn`；四边形/多边形按扇形三角化；负索引

  * 无 `vn` 时用 Newell 法按三角面计算并累加平均法线

  * 忽略 `mtllib/usemtl/vt`（不贴图），全网格统一顶点色

* `fit_mesh(mesh, target_len, rot_deg=(0,0,0), scale=0.0)` — 把模型归一化到"最长轴 = `glider.length`（7.2 m）"并居中；`scale>0` 时用显式缩放

* `mesh_to_obj(mesh, path)` — 仅用于验证（把程序化网格导出为 OBJ 再回读）

### 6.3 `simulation/glider/render_gl.py`（OpenGL 渲染核心）

```python
class GLContextError(RuntimeError): ...

def _create_context(width, height, backend="auto") -> (ctx, cleanup_fn)

class GliderGLRenderer:
    def __init__(self, width, height, *, mesh, shader_dir=None, aa=1,
                 model_path=None, model_scale=0.0, model_rot=(0,0,0), gpu_mesh=None)
    # 内部：编译 aircraft / line 两个 program；建 FBO(color tex + depth tex)；上传 VAO/VBO/EBO
    def set_camera(self, eye, target, up, fovy, near, far)
    def set_aircraft(self, pos, quat, state: dict)      # state 内含 §5.2 全部标量/向量
    def set_style(self, light_dir, base_color, scale, highlight)
    def draw(self, ground_segments, trail_points, trail_count) -> np.ndarray  # (H,W,3) u8
    def close(self)
```

要点：

* **着色器加载**：`shaders/aircraft.vert|frag`、`shaders/line.vert|frag`；`--shader-dir` 可指向外部目录（热替换，无需改 Python）；文件缺失时用模块内内联默认 GLSL 兜底。

* **渲染状态**：`ctx.enable(moderngl.DEPTH_TEST)`；**关闭背面剔除**（薄部件/单面 OBJ 更安全）；`ctx.clear((0.53,0.72,0.94))`（天蓝底）。

* **FBO**：`ctx.framebuffer(color_attachments=[ctx.texture((w,h),3)], depth_attachment=ctx.depth_texture((w,h)))`；`aa>1` 时按 `aa` 倍超采样渲染，再用 `PIL.Image.resize`（LANCZOS）降采样回目标尺寸（简单的抗锯齿方案，避开 MSAA resolve 的 GL 细节）。

* **像素回读**：`fbo.read(components=3)` → `np.frombuffer(...).reshape(h,w,3)` → **`np.flipud`**（GL 行序自下而上）→ 得到 `(H,W,3) uint8`，与 `render.make_video` 喂给 imageio 的格式完全一致。

* **HUD**：复用 `render._hud_text(tele, idx)` 生成文本，`PIL.ImageDraw` 叠加半透明白底黑字（字体优先用 matplotlib 自带的 `DejaVuSansMono.ttf`，找不到则 PIL 默认字体）。

* **相机**：

  * `fixed`：复用 `render._flight_view_bounds(tele)` 得到走廊包围盒 → 以其中心为 target，`fovy=45°`，按包围盒半对角线自动求 `dist`，`up=+Y`，`elev=30°/azim=-90°`（与现有 mpl 固定机位观感一致）；`near=max(1.0, dist*0.01)`、`far=dist*10`。

  * `chase`：`eye = pos - fwd*dist + up*height + side*lateral`、`target = pos + fwd*8`（迁移 `render.draw_scene` 的机位逻辑）。

  * 世界 Y-up 直接可用，无需换轴。

### 6.4 `simulation/glider/shaders/`

* `aircraft.vert`：`in_position/in_normal/in_color` → 输出 `v_normal_world`、`v_color`、`v_world_pos`；用 `u_proj*u_view*u_model` 定位，用 `u_normal_mat` 变换法线。

* `aircraft.frag`：Lambert + 环境光 + 简单的边缘补光（fresnel 提亮，让白色机身在天空底色下更立体）；`u_highlight>0.5` 时混入红色。

* `line.vert` / `line.frag`：`u_mvp` + `u_color`，flat 输出。

所有 GLSL 顶部写注释列出可用 uniform（对应 §5 契约）。

### 6.5 `simulation/glider/render_gl.py` 对外函数（与 `render.make_video` 同构）

```python
def make_video_gl(tele, glider, out_path, fps=15, start=0.0, end=None,
                  cfg_view=None, progress=print, hud=False, camera="fixed",
                  size=(1280, 720), aa=1, codec="libx264", quality=6,
                  model_path=None, shader_dir=None, model_scale=0.0,
                  model_rot=(0,0,0), preview_png=None, dump_uniforms=False) -> str
```

* 帧率/时长/`end` 计算、`np.searchsorted` 取帧索引、`imageio.get_writer(fps, codec, pixelformat="yuv420p", macro_block_size=None)`、`w.append_data(rgb)`、进度回调——与 `render.make_video` 完全一致，保证两条路径可对拍。

* `preview_png`：额外落一张首帧 PNG（验证用）。

* `dump_uniforms`：把首帧的完整 uniform 字典打印为 JSON（证明契约生效）。

***

## 7. 修改文件

### 7.1 `simulation/glider/sim_service.py`

1. 新增参数：

| 参数             | 默认                                 | 说明                                          |
| -------------- | ---------------------------------- | ------------------------------------------- |
| `--renderer`   | `mpl`                              | `mpl` \| `gl`                               |
| `--gl-size`    | `1280x720`                         | 渲染分辨率（H.264 要求偶数）                           |
| `--gl-aa`      | `1`                                | 超采样倍数                                       |
| `--gl-camera`  | `fixed`                            | `fixed` \| `chase`                          |
| `--gl-scale`   | `0`（0=按机位自动：fixed→6.0 / chase→1.0） | 飞机显示放大                                      |
| `--model`      | 空                                  | OBJ 路径；为空则自动找 `assets/airplane.obj`，再退程序化网格 |
| `--shader-dir` | 空                                  | 外部着色器目录                                     |
| `--gl-preview` | 空                                  | 额外输出首帧 PNG 路径（调试）                           |

1. `--video` 分支改为按 `args.renderer` 分派：`gl` 走 `render_gl.make_video_gl`，捕获 `GLContextError/ImportError/Exception` → stderr 打印 `[video] gl 渲染不可用，回退 matplotlib：<原因>`，再走原 `render.make_video`（与现有 imageio-ffmpeg 缺失时的"优雅跳过"风格一致）。

2. `--probe` 输出**追加字段**（向后兼容，现有 `computeReady` 逻辑不变）：
   `"opengl": has("moderngl") and has("moderngl_window")`、`"renderer": <当前默认渲染器>`。

3. `summary.json` 的 `files` 结构不变（`video` 字段仍指向 `flight_replay.mp4`），保证后端 `toDto` / 前端零改动。

### 7.2 `simulation/glider/requirements.txt`

追加 §4 的三条依赖（注释说明仅供 `--renderer gl`）。

### 7.3 `simulation/glider/README.md`

新增一节「OpenGL 渲染途径（`--renderer gl`）」：命令示例、**完整 uniform 契约表（§5）**、如何替换着色器、如何放入自定义 OBJ 模型（默认路径 `assets/airplane.obj`，需符合机体系 x 前 / y 上 / z 右，或配 `--model-rot`/`--model-scale`）、无 GL 环境时的回退行为。

### 7.4 `simulation/README.md`

* 「目录结构」补 `gl_math.py` / `gl_mesh.py` / `render_gl.py` / `shaders/`；

* 环境变量表新增 `GLIDER_RENDERER`（`mpl`|`gl`，默认 `mpl`）；

* 一句话说明 WSL/Docker 下 GL 需要 WSLg 或 EGL，不可用时自动回退 matplotlib。

### 7.5 `backend/controllers/gliderController.js`

* 新增 `const GLIDER_RENDERER = process.env.GLIDER_RENDERER || 'mpl';`（在 `GLIDER_BACKEND` 附近）；

* 在 `flags` 里当 `GLIDER_RENDERER === 'gl'` 时推入 `'--renderer', 'gl'`；

* 其余（并发、超时、白名单、`toDto`）**不动**。

> 决策：平台默认仍为 `mpl`（保证既有 Linux/WSL/Docker 部署零风险），由运维在 `backend/.env` 置 `GLIDER_RENDERER=gl` 启用；本地开发直接用 `--renderer gl`。

### 7.6 `backend/.env.example`

「滑翔机物理引擎」一节补 `GLIDER_RENDERER=mpl` 及注释。

***

## 8. 假设与决策

1. **不做贴图/MTL/GLTF**：OBJ + 顶点色 + 光照即可满足"读取模型 + 顶点/片段着色器 + uniform 暴露"。需贴图时改着色器自行加 `sampler2D`。
2. **不做交互式窗口**：本次只做离线出帧 → MP4（用户已选）。`GliderGLRenderer` 的 API 设计保持与窗口无关，将来想加交互式查看器可直接复用。
3. **`render.py`** **不改**：matplotlib 路径原样保留作为对拍/兜底；`_flight_view_bounds` / `_hud_text` 以 import 方式复用，不复制实现。
4. **关闭背面剔除**：薄部件与单面 OBJ 更安全；性能不是瓶颈。
5. **`draw()`** **每帧重建线几何开销可忽略**：航迹点数 ≤ 5000，ground 网格 ≤ 100 段，直接 `buffer.orphan()` + 重写即可，不引入复杂缓冲管理。
6. **angles/units**：`tele["bank"]/["pitch"]` 已是**度**；`u_alpha/u_beta/u_euler` 用**弧度**（与 GLSL 三角函数一致）。该约定写进 README。
7. **分辨率默认 1280×720**（H.264 需偶数尺寸；比现有 mpl 1000×750 略大，画面更清晰）。

***

## 9. 风险与回退

| 风险                                | 应对                                                                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------- |
| moderngl-window 与 Python 3.13 不兼容 | `_create_context()` 提供 `glfw + moderngl.create_context()` 直连路径；`GLIDER_GL_CONTEXT` 可强制指定 |
| WSL / Docker 无 GL 上下文             | `--probe` 暴露 `opengl` 字段；运行期捕获异常 → stderr 警告 + **自动回退 matplotlib**，产物仍完整                 |
| OBJ 模型单位/朝向不符                     | 默认按最长轴自动归一化到 7.2 m；`--model-rot` / `--model-scale` 手工修正                                  |
| GL 输出与 mpl 输出观感差异大                | `--gl-preview` 落首帧 PNG，人工比对；相机参数（elev/azim/fovy/scale）与 mpl 固定机位对齐                       |

***

## 10. 验证步骤

1. **装依赖**

   ```powershell
   & "C:\Users\DSwer\anaconda3\python.exe" -m pip install moderngl moderngl-window glfw
   ```
2. **上下文自检**：`python -c "import render_gl; ..."` 创建隐藏窗口 + 读回一帧纯色（确认 GL 上下文与像素回读正确，含 `flipud`）。
3. **数学自检**：`mat4_perspective(45°, 16/9, 1, 1000) @ mat4_look_at(...)` 把已知点投影到 NDC，断言落点符号正确。
4. **网格自检**：`mesh_to_obj(procedural_mesh(Glider()), tmp.obj)` 再 `load_obj(tmp.obj)`，断言三角形数与包围盒一致（覆盖程序化与 OBJ 两条路）。
5. **端到端跑通**（GL 路径）：

   ```powershell
   cd simulation\glider
   & "C:\Users\DSwer\anaconda3\python.exe" sim_service.py --dihedral 6 --cg 0.1 --speed 36 --alt 150 `
     --renderer gl --video --video-fps 10 --video-max 12 --gl-preview output\_gl\preview.png `
     --dump-uniforms --outdir output\_gl
   ```

   期望：stdout 一行 JSON（`reason` 正常）、`output/_gl/flight_replay.mp4` 生成、**无** matplotlib 回退警告、stdout 打印的 uniform JSON 含 §5 全部键。
6. **视觉比对**：读取 `output/_gl/preview.png`（GL）与 `output/_chase/trajectory3d.png` / 既有 `_demo2/flight_replay.mp4` 首帧比对——飞机姿态、航迹、地面网格方向一致（特别是**飞机在航迹上、地面在下方、机头朝航迹前进方向**）。
7. **着色器热替换**：把 `shaders/aircraft.frag` 里 `u_base_color` 改成纯红，重跑步骤 5，确认重新编译生效。
8. **OBJ 路径**：用 `mesh_to_obj` 导出的 OBJ 当 `--model` 跑一次，确认加载分支生效（日志打印"loaded model: …"）。
9. **回退路径**：设 `GLIDER_GL_CONTEXT=egl` 强制不可用，确认 stderr 出现回退警告且 `flight_replay.mp4` 仍由 matplotlib 生成。
10. **回归**：`--renderer mpl`（默认）跑一次，产物与改动前一致；`python sim_service.py --probe` 输出含新增 `opengl`/`renderer` 字段且 `ready` 仍为 true。

