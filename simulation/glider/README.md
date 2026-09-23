# NovaPhy 气动滑翔机 3D 仿真（glider\_sim）

> 📦 **运行环境（WSL / Docker / 无 novaPhy 兜底）与 novaPhy 交付包的放置方式，见上级
> [`simulation/README.md`](../README.md)。本文件只讲气动模型与纯 Python 用法。**

在 **novaPhy** 物理引擎（`novaphy` wheel 0.4.0，CPU 版）上做一架**符合空气动力学**的
滑翔机 6 自由度仿真。`sim_service.py` 为无界面服务入口，供 **PBL 科创平台**后端调用：
输出 3D 航迹图、遥测曲线图、遥测 CSV、`summary.json` 与**固定机位 MP4 飞行回放**。

> ⚠️ **本机运行限制**：交付的 `novaphy-0.4.0-cp311-cp311-linux_x86_64.whl` 是
> **Linux x86\_64 + CPython 3.11 专用**。当前开发机是 Windows + Python 3.13，
> 无法加载该 wheel。因此工程采用 **双后端** 设计：
>
> * `backend_novaphy.py` —— 真正的 novaPhy 物理后端（目标 Linux 环境运行）；
>
> * `backend_reference.py` —— 纯 numpy 6DOF 参考后端（Windows / 无 novaPhy 时自动使用）。
>
> 两个后端走**完全相同**的气动与控制器代码（`aero.py` / `sim_core.py`），
> 只替换“刚体动力学积分”这一段，因此本机看到的参考后端结果可代表 novaPhy 后端的行为。

***

## 1. 快速开始（headless 服务）

直接用 `sim_service.py`（供 PBL 平台调用，也可命令行独立运行；无 novaPhy 时自动回退纯 numpy 参考后端）：

```bash
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --alt 150 --outdir output/sim1
# 加 --video 生成固定机位 MP4 飞行回放
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --video --video-fps 10 --outdir output/sim2
```

输出到 `--outdir`：

* `trajectory3d.png` —— 世界系 3D 航迹（竖直轴 = 高度、地面在下方；长航程时竖直方向按显示比例拉伸并在图内注明）

* `flight_telemetry.png` —— 高度 / 空速 / 迎角 / 下沉率 / L/D 随时间变化

* `flight_telemetry.csv` —— 全量遥测

* `summary.json` —— 参数与结果摘要（reason / glide\_time / distance 等）

* `flight_replay.mp4` —— 固定机位飞行回放（`--video` 时生成）

常用参数：`--dihedral`、`--cg`、`--speed`、`--alt`、`--timeout`、`--backend`、
`--video/--video-fps/--video-max`、`--renderer mpl|gl`（默认 `mpl`，可用环境变量
`GLIDER_RENDERER` 覆盖）。

***

## 2. OpenGL 渲染途径（`--renderer gl`）

在 matplotlib 渲染之外提供一条 **GPU 渲染途径**（`render_gl.py`，基于 moderngl），
产出同样的 `flight_replay.mp4`：

```bash
# 默认：程序化盒体模型 + 内置着色器
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --alt 150 --video \
    --renderer gl --video-fps 10 --outdir output/gl1

# 使用自定义 OBJ 模型 + 外部着色器目录（热替换，无需改 Python）
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --video \
    --renderer gl --model assets/airplane.obj --shader-dir my_shaders --outdir output/gl2
```

相关参数：

| 参数                | 默认值        | 说明                                                                   |
| ----------------- | ---------- | -------------------------------------------------------------------- |
| `--renderer`      | `mpl`      | `mpl`（matplotlib）\| `gl`（OpenGL）                                     |
| `--gl-size`       | `1280x720` | 渲染分辨率（H.264 要求偶数尺寸）                                                  |
| `--gl-aa`         | `1`        | 超采样抗锯齿倍数                                                             |
| `--gl-camera`     | `fixed`    | `fixed`（固定机位）\| `chase`（追逐机位）                                        |
| `--gl-scale`      | `0`        | 飞机显示放大（0 = 按机位自动：fixed→6.0 / chase→1.0）                              |
| `--gl-vert`       | `3.0`      | 固定机位**竖直增强**：放大高度波动以接近 matplotlib 观感（设 `1` 恢复真实等比例）                  |
| `--model`         | 空          | 外部模型路径（`.obj` 或 `.glb/.gltf`）；为空则找 `assets/airplane.obj`，仍无则用程序化盒体网格 |
| `--model-rot`     | `0 0 0`    | 模型自身坐标系内的朝向修正（度，X→Y→Z）                                               |
| `--model-scale`   | `0`        | 模型显式缩放；0 = 按“最长轴 = 机身长”自动归一化                                         |
| `--shader-dir`    | 空          | 外部 GLSL 着色器目录（含 `aircraft.vert/frag`、`line.vert/frag`）               |
| `--gl-preview`    | 空          | 额外输出首帧 PNG（调试）                                                       |
| `--dump-uniforms` | 否          | 把首帧 uniform 契约快照打印为 JSON（自检）                                         |

GL 不可用（无 GPU / 无显示 / 依赖缺失）时自动回退 matplotlib，MP4 仍会生成，
stderr 打印 `[video] gl 渲染不可用，回退 matplotlib：<原因>`。

### 1.5.1 模型约定

* 默认程序化网格由 `aircraft.py` 的 `Glider.parts()` 派生（7 个盒体，与 mpl 路径同外观）。

* OBJ 模型使用**机体系**坐标：**x 前 / y 上 / z 右翼**，单位米。若模型朝向/比例不符，
  用 `--model-rot` / `--model-scale` 修正；修正烘焙进网格后再按飞机姿态渲染，只做一次。

* `.glb/.gltf` 同样用 `--model` 加载（经 `trimesh` 读取，所有子网格合并为一个，颜色优先取
  顶点色，否则材质 baseColorFactor，再兜底统一灰白）。**单位 / 朝向未知一律归一到机身长**，
  所以大多数建模工具导出的模型（常为 z-up 或米/厘米）都需要用 `--model-rot` 调朝向。

* 不做贴图/MTL：渲染走顶点色 + 光照。需要贴图时在自定义着色器里加 `sampler2D` 即可。

### 2.2 着色器与 uniform 契约

着色器为 GLSL 330，放 `shaders/`（或 `--shader-dir` 指向的目录）：

* `aircraft.vert` / `aircraft.frag` —— 飞机本体；

* `line.vert` / `line.frag` —— 航迹与地面网格（仅 `u_mvp` + `u_color`）。

飞机着色器可声明的 **uniform 契约**（渲染器每帧写入；未声明的会自动跳过）：

**变换类**

| Uniform        | 类型   | 含义                                               |
| -------------- | ---- | ------------------------------------------------ |
| `u_model`      | mat4 | 模型矩阵 `T(u_pos) · R(u_quat) · S(u_scale)`         |
| `u_view`       | mat4 | 世界系 → 相机系                                        |
| `u_proj`       | mat4 | 相机系 → 裁剪空间（透视）                                   |
| `u_mvp`        | mat4 | `u_proj · u_view · u_model`（现成）                  |
| `u_normal_mat` | mat4 | 法线变换 `transpose(inverse(u_view·u_model))` 左上 3×3 |

**姿态 / 飞行状态**

| Uniform                                 | 类型        | 含义                                     |
| --------------------------------------- | --------- | -------------------------------------- |
| `u_pos`                                 | vec3      | 世界位置 `[x, alt, z]` (m)                 |
| `u_quat` / `u_euler`                    | vec4/vec3 | 姿态四元数 xyzw / 欧拉角 `(roll,pitch,yaw)` 弧度 |
| `u_vel` / `u_omega`                     | vec3      | 世界速度 (m/s) / 世界角速度 (rad/s)             |
| `u_alt` / `u_V`                         | float     | 高度 (m) / 空速 (m/s)                      |
| `u_alpha` / `u_beta`                    | float     | 迎角 / 侧滑角 (rad)                         |
| `u_CL` / `u_CD` / `u_sink`              | float     | 升力 / 阻力系数 / 下沉率 (m/s)                  |
| `u_bank` / `u_pitch` / `u_heading`      | float     | 坡度 / 俯仰 / 航向 (deg)                     |
| `u_elevator` / `u_aileron` / `u_rudder` | float     | 三个舵面偏转                                 |
| `u_time` / `u_frame` / `u_scale`        | float/int | 仿真时间 (s) / 帧序号 / 显示放大倍数                |
| `u_highlight`                           | float     | 0/1 异常姿态高亮（失控/失速标红）                    |

**相机 / 屏幕**：`u_cam_eye` / `u_cam_target` / `u_cam_up`（vec3）、
`u_fovy` / `u_near` / `u_far`（float）、`u_resolution`（vec2）。

**光照 / 材质**：`u_light_dir` / `u_light_color` / `u_ambient`（vec3）、
`u_base_color`（vec4，与顶点色相乘）。

> 机器可读清单见 `render_gl.UNIFORM_CONTRACT`；角度约定：`u_euler/u_alpha/u_beta` 为
> **弧度**，`u_bank/u_pitch/u_heading` 为**度**（与 telemetry CSV 一致）。
> 自定义着色器可只用其中一部分属性/uniform；未使用的顶点属性（如 `in_color`）会被
> GLSL 编译器优化掉，渲染器按程序实际声明自动适配。

***

## 3. 在 Linux（x86\_64 + Python 3.11）上使用真正的 novaPhy 后端

```bash
# 1) 准备干净虚拟环境
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# 2) 安装交付的 novaPhy wheel（路径按实际解压位置）
python -m pip install ./novaphy-0.4.0-cp311-cp311-linux_x86_64.whl

# 3) 安装本 demo 的绘图依赖
python -m pip install numpy matplotlib

# 4) 运行（-–backend novaphy 显式指定）
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --video --backend novaphy --outdir output/sim_novaphy
```

`--backend auto` 会先探测 novaPhy 是否可用，可用则优先用它，否则回退 reference。
本项目 3D / 图表 / 回放全部用跨平台 matplotlib 生成，headless 即可出图（无显示环境也可用）。

***

## 4. 气动模型（`aero.py`）——“符合空气动力学”体现在哪

滑翔机整机为**一个自由刚体**（质心在体原点，显式质量/惯量），气动面：
左右主机翼半面、平尾(+升降舵)、垂尾(+方向舵)、机身阻力。

每个面在气动中心 **AC** 处用“局部来流”计算：

$$
V\_{\text{air,AC}} = V\_{\text{body}} + \omega \times r\_{AC} - V\_{\text{wind}}
,\qquad q = \tfrac12 \rho V^2
$$

* **升力**：$L = qS, C\_L(\alpha),\hat l$，$\hat l$ 为与来流垂直的升力方向；

* **阻力**：$D = qS, C\_D(\alpha),\hat a$，$\hat a$ 为来流方向；

* **升力线斜率**（三维机翼）：$a\_0 = \dfrac{2\pi,AR}{AR+2}$；

* **失速**：线性 $C\_L=a\_0\alpha$ 至 $\alpha\_{stall}$，之后衰减（分离）；

* **诱导阻力**：$C\_{D,i}= \dfrac{C\_L^2}{\pi e,AR}$，加上 $C\_{D0}$ 与失速平板阻力；

* **下洗**（平尾）：$\varepsilon \approx \dfrac{2 C\_{L,w}}{\pi AR}$，修正平尾迎角；

* 迎角/侧滑由机体速度分量给出：$\alpha=\arctan2(-v,u)$，$\beta=\arcsin(w/V)$，
  机体轴：x 前、y 上、z 右翼；世界系 Y 向上（与 novaPhy 一致，四元数 xyzw）。

控制器（`sim_core.py`）：升降舵空速保持、副翼机翼水平/协调坡度、方向舵去侧滑+偏航阻尼，
可执行 直飞 / 持续盘旋 / 蛇形 机动。

默认参数（`aircraft.py`）为一架 ~~420 kg、翼展 16 m 的中型滑翔机，仿真结果稳定：
稳态迎角 ≈ 4°、空速恒定、\*\*L/D ≈ 15~~21、下沉率 ≈ 1.5\~2.0 m/s\*\*，与真实滑翔机同量级。

***

## 4. 目录

```
glider_sim/
├─ aircraft.py         # 滑翔机参数与渲染部件
├─ aero.py             # 6DOF 气动模型（面元法 + 失速/诱导阻力/下洗）
├─ spatial.py          # 6DOF 刚体数学（xyzw 四元数、旋转、参考积分器）
├─ sim_core.py         # 后端无关的飞行循环、控制器、遥测
├─ backend_novaphy.py  # ★ novaPhy 后端（ModelBuilder+SolverSemiImplicit）
├─ backend_reference.py# 纯 numpy 参考后端（本地验证）
├─ render.py           # matplotlib 渲染：固定机位/追逐镜头 + MP4/GIF 帧 + HUD
├─ plot_flight.py      # 高度/空速/迎角/下沉/L-D 图表、3D 航迹图
├─ sim_service.py      # ★ PBL 平台入口：headless 模拟 → 图/CSV/summary/MP4 回放
├─ requirements.txt    # Python 依赖清单（numpy/matplotlib 等）
└─ output/             # 生成结果（png/csv/json/mp4）
```

## 6. 常见问题

* **`--backend novaphy`** **报“novaPhy 不可用”**：确认在 Linux x86\_64 + CPython 3.11
  环境，且 `pip install` 成功；可先 `python -c "import novaphy"` 自检。

* **HUD/图表里的中文字体方块**：文本用英文避免 DejaVu 无 CJK 字形。

* **想改机型**：改 `aircraft.py` 的质量/惯量/翼面积/AC 位置即可（气动自动适配）。

* **想看交互式 ViewerGL 窗口**：原交互脚本（`glider_interactive.py` 等）已从本仓库移除，
  平台统一使用 headless 的 `sim_service.py`（matplotlib 出图/回放）。

