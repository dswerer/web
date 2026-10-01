# NovaPhy 气动滑翔机 3D 仿真（glider\_sim）

> 📦 **运行环境（WSL / Docker / 无 novaPhy 兜底）与 novaPhy 交付包的放置方式，见上级
> [`simulation/README.md`](../README.md)。本文件只讲气动模型与纯 Python 用法。**

在 **novaPhy** 物理引擎（`novaphy` wheel 0.4.0，CPU 版）上做一架**符合空气动力学**的
滑翔机 6 自由度仿真。`sim_service.py` 为无界面服务入口，供 **PBL 科创平台**后端调用：
输出 3D 航迹图、遥测曲线图、遥测 CSV、`summary.json` 与**逐帧轨迹数据**（供前端渲染回放）；
另有 `--gl-preview` / `--gl-live` 渲染调试通道（GLB + OpenGL 延迟渲染，见第 7 节）。

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
# 课程组扩展参数：机翼面积 / 质量 / 平尾偏角 / 垂尾偏角（见第 4 节）
python sim_service.py --dihedral 5 --wing-area 24 --mass 480 --elevator 2 --rudder 8 --outdir output/sim3
```

输出到 `--outdir`：
- `trajectory3d.png` —— 世界系 3D 航迹（竖直轴 = 高度、地面在下方；长航程时竖直方向按显示比例拉伸并在图内注明）
- `flight_telemetry.png` —— 高度 / 空速 / 迎角 / 下沉率 / L/D 随时间变化
- `flight_telemetry.csv` —— 全量遥测
- `summary.json` —— 参数与结果摘要（reason / glide_time / distance 等）
- `flight_trace.npz` —— 最小向量接口轨迹（见第 5 节；供后置渲染 / 分析，无需重跑仿真）
- `flight_trace.bin` —— ftrc 二进制轨迹（Node 解析入库 / 前端 three.js 直读的交换格式）

常用参数：`--dihedral`、`--cg`、`--speed`、`--alt`、`--wing-area`、`--mass`、
`--elevator`、`--rudder`、`--timeout`、`--backend`。
渲染调试：`--renderer mpl|gl`（`--gl-preview` 单帧预览 / `--gl-live` 实时窗口；GL 参数表见第 7 节）。

***

## 2. 在 Linux（x86\_64 + Python 3.11）上使用真正的 novaPhy 后端

```bash
# 1) 准备干净虚拟环境
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# 2) 安装交付的 novaPhy wheel（路径按实际解压位置）
python -m pip install ./novaphy-0.4.0-cp311-cp311-linux_x86_64.whl

# 3) 安装本 demo 的绘图依赖
python -m pip install numpy matplotlib

# 4) 运行（-–backend novaphy 显式指定）
python sim_service.py --dihedral 6 --cg 0.1 --speed 36 --backend novaphy --outdir output/sim_novaphy
```

`--backend auto` 会先探测 novaPhy 是否可用，可用则优先用它，否则回退 reference。
本项目图表全部用跨平台 matplotlib 生成，headless 即可出图（无显示环境也可用）；
飞行回放不在此生成，由前端消费轨迹数据渲染（见第 5 节与 `RENDER_API.md`）。

***

## 3. 气动模型（`aero.py`）——“符合空气动力学”体现在哪

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

控制器（`sim_core.py`）：升降舵空速保持（或“手动尾翼”固定偏角模式，见第 4 节）、副翼机翼
水平/协调坡度、方向舵去侧滑+偏航阻尼，可执行 直飞 / 持续盘旋 / 蛇形 机动。

默认参数（`aircraft.py`）为一架 ~420 kg、翼展 16 m 的中型滑翔机（可用 `--wing-area` /
`--mass` 调整，见第 4 节），仿真结果稳定：
稳态迎角 ≈ 4°、空速恒定、**L/D ≈ 15~21、下沉率 ≈ 1.5~2.0 m/s**，与真实滑翔机同量级。

***

## 4. 学生可调设计参数与尾翼控制（课程组需求）

除已有的 上反角 / 重心 / 投放速度 外，`sim_service.py` 另开放 4 个设计参数：

| 参数 | 物理量 | 平台 UI 范围 | 默认 | 语义 |
| --- | --- | --- | --- | --- |
| `--wing-area` | 主翼面积 (m²) | 10 ~ 30 | 17.5 | 按比例缩放（翼展/弦长同步 ×√(S/17.5)，展弦比不变）；面积越大升力越大、可慢速滑翔 |
| `--mass` | 整机质量 (kg) | 250 ~ 700 | 420 | 课程组“重力”参数；质量越大配平速度越高、下沉越快（惯量按质量一阶缩放） |
| `--elevator` | 水平尾翼偏角 (°) | -15 ~ +15 | 0 | >0 上抬（抬头），<0 下压（俯冲）；**非 0 时进入“手动尾翼模式”** |
| `--rudder` | 垂直尾翼偏角 (°) | -15 ~ +15 | 0 | >0 机头右偏、<0 左偏；直接叠加到方向舵通道 |

**翼载联动（教学口径）**：目标巡航速度随“质量/面积”自动调整，保证“面积大→飞得慢、沉得慢”
“质量大→飞得快、沉得快”符合直觉；默认参数下仍为 31 m/s：

$$V_{ref} = 31 \cdot \sqrt{\frac{m}{420} \cdot \frac{17.5}{S}}$$

**手动尾翼模式**（`cfg.elevator_deg ≠ 0`）：升降舵脱离自动空速保持回路，转为
“学生固定偏角 + 俯仰阻尼”——“拉杆/推杆”的俯仰与速度后果才**直接可见**
（实测：+4° 上抬即会失速/失控，−2° 下压 9 秒俯冲触地）。方向舵偏角直接叠加
（默认 0 时行为与原来完全一致）。

**姿态辅助**（`--tail-assist`，默认开启；`--no-tail-assist` 关闭）：手动尾翼模式下
保留横滚回中与偏航阻尼。原因（实测）：方向舵 +8° 无辅助时 25 秒螺旋坠地
（横滚发散掩盖了“偏航”效果），有辅助时 72 秒平稳右转 103°——效果干净可解释。

**成功/失败案例覆盖**（150 m 投放、默认其余参数，参考后端实测）：

| 参数 | 成功案例 | 失败/极端案例 |
| --- | --- | --- |
| 面积 | S=30 → 飘 100 s 未落地（下沉 1.0 m/s） | S=10 → 31.8 s 快速落地（下沉 4.7 m/s） |
| 质量 | m=340 → 84 s；m=700 → 46 s 加速降落 | m=250 → 飘 100 s 未落地 |
| 平尾 | +1° → 77 s / 2387 m；+2° → 飘 100 s | +4° → 失速/重着陆；-2° → 9 s 俯冲触地 |
| 垂尾 | ±2° → 轻转 25°；+8° → 右转 103°；±15° → 回转 212° | （全范围平稳，无失败） |

> 注：接近失速/失控边界的组合（如平尾 +4°）在 novaPhy 与参考后端下失效模式可能
> 略有不同（混沌边缘的正常表现），但都属“失败案例”。

---

## 5. 最小向量接口与渲染数据契约

物理仿真与渲染按「面向接口」解耦，数据契约见 `flight_trace.py`：

```
FlightTrace 帧向量（11 列）：[t, x, y, z, qx, qy, qz, qw, vx, vy, vz]
  t = 仿真时间 (s)      x,y,z = 世界系位置（y 为高度, m）
  qx,qy,qz,qw = 姿态四元数（xyzw）    vx,vy,vz = 世界系速度 (m/s)
```

- **物理仿真侧**（`sim_core.run_flight` → `FlightRun`）原生给出最小向量接口：
  - `run.trace`：`FlightTrace`——渲染 / 回放 / 外部消费的**唯一数据源**；
  - `run.tele`：扩展遥测（气动系数 / 舵面 / 姿态角等），仅供图表与 CSV 使用。
- **渲染侧（前端 three.js）**只消费接口数据：逐帧位置 / 姿态 / 速度已足够驱动实时回放
  （位置即世界坐标、姿态直接使用 xyzw 四元数）；L/D 等增强显示走**可选扩展通道**
  （CL/CD 随 ftrc 二进制携带），通道不可用时消费方须优雅降级。
- **轨迹可落盘 / 可复放**：仿真产物含 `flight_trace.npz` / `flight_trace.bin`，
  任何进程都能**不重跑物理仿真**、读取轨迹渲染回放或做后置分析。

- **序列化往返**：`FlightTrace.save/load`（.npz，含元信息与扩展通道）与
  `FlightTrace.save_bin/load_bin`（ftrc 二进制：20B 头 `FTRC + version + count + dim + extra_dim` +
  float32 矩阵，Node/浏览器可直接解析）；`FlightTrace.load` 按文件头自动识别两种格式。
- **平台链路（数据库优先）**：`flight_trace.bin` 经后端存入数据库（`glider_trajectories`）→
  接口 `GET /api/glider/simulations/:id/trace`（JSON / ftrc 二进制）→ **前端 three.js 渲染回放**。
  轨迹在库中可重复读取，与模拟进程解耦；接口细节、字段说明与 JS 解析示例见 **`RENDER_API.md`**。
- **“最小”的边界**：只含渲染所必需的运动状态（时间 + 位置 + 姿态 + 速度）；
  加速度、角速度、舵面、气动系数均不属于接口，可由状态向量另行派生。

## 6. 目录

```
glider/
├─ aircraft.py         # 滑翔机参数与渲染部件（parts() = 渲染几何接口）
├─ aero.py             # 6DOF 气动模型（面元法 + 失速/诱导阻力/下洗）
├─ spatial.py          # 6DOF 刚体数学（xyzw 四元数、旋转、参考积分器）
├─ flight_trace.py     # ★ 最小向量接口：物理仿真 ↔ 渲染的数据契约（可序列化）
├─ RENDER_API.md       # ★ 渲染接入指南：trace 接口 / ftrc 格式 / three.js 解析示例
├─ sim_core.py         # 后端无关的飞行循环、控制器；产出 FlightRun(trace + tele)
├─ backend_novaphy.py  # ★ novaPhy 后端（ModelBuilder+SolverSemiImplicit）
├─ backend_reference.py# 纯 numpy 参考后端（本地验证）
├─ plot_flight.py      # 高度/空速/迎角/下沉/L-D 图表、3D 航迹图（消费扩展遥测）
├─ sim_service.py      # ★ PBL 平台入口：headless 模拟 → 图/CSV/summary/轨迹 npz·bin
├─ gldeferred.py       # ★ OpenGL 延迟渲染（--renderer gl）：GLB 模型 + G-buffer + FrameSink
├─ gl_math.py          # 渲染数学薄适配层（内部全用 pyGLM，不手写线性代数）
├─ gl_mesh.py          # GLB/OBJ 网格加载：节点变换烘焙、颜色、归一化、轴转换
├─ glshaders/          # 延迟管线着色器（gbuffer / lighting / flat / blit）
├─ assets/             # 默认 GLB 模型与天空贴图（airplane.glb / skyview.jpg；缺失回退盒体）
├─ samples/            # 样例轨迹文件（联调用；见 RENDER_API.md 第 6 节）
├─ requirements.txt    # Python 依赖清单（numpy/matplotlib 等）
└─ output/             # 生成结果（png/csv/json/npz/bin）
```

## 7. OpenGL 延迟渲染途径（`--renderer gl`）

除默认 matplotlib 图表外，另有基于 **OpenGL 延迟渲染** 的渲染调试途径：加载 **GLB 模型**
（默认 `assets/airplane.glb`），几何 pass 写 G-buffer（位置/法线/反照率 MRT），
光照 pass 全屏三角形着色（太阳 + 半球环境光 + Blinn 高光 + 雾 + 程序化地面网格 + 天空渐变），
overlay pass 画拖尾丝带与起/终点标记。

**帧缓冲与呈现解耦**：渲染结果始终进离屏 FBO，由 `FrameSink` 协议负责呈现——
`VideoSink`（MP4，当前未接入服务端流程）/ `PngSink`（单帧 PNG）/ `WindowSink`（`--gl-live` 原生 glfw 实时窗口），
未来新增呈现方式（流媒体等）只需新写 Sink，管线零改动。

### 快速开始

```bash
# 姿态链路自检（纯数学，不跑仿真、不建 GL 上下文；退出码非 0 = 姿态有误）
python sim_service.py --gl-pose-check

# 单帧 PNG 预览（最快迭代环；t 秒可选，缺省 0）
python sim_service.py --speed 28 --gl-preview 8 --outdir output/sim_prev

# 用规范静态姿态目检（level / pitch20 / bank30 / yaw90）
python sim_service.py --speed 28 --gl-preview --gl-pose-set bank30 --gl-camera chase

# 实时调试窗口（chase 机位默认，ESC / 关窗退出）
python sim_service.py --speed 28 --timeout 20 --gl-live
```

### GL 参数表（`sim_service.py`）

| 参数                                           | 默认                    | 说明                                                         |
| -------------------------------------------- | --------------------- | ---------------------------------------------------------- |
| `--renderer {mpl,gl}`                        | mpl                   | 渲染途径；优先级 **arg > 环境变量** **`GLIDER_RENDERER`** **> 默认 mpl** |
| `--gl-model PATH`                            | airplane.glb          | GLB/OBJ 模型；默认模型缺失/失败自动回退程序化盒体；**显式指定失败直接报错**（不静默换模型）       |
| `--gl-model-fwd {+x,-x,+y,-y,+z,-z}`         | -x                    | 模型机头轴（airplane.glb 实测：垂尾在 +x 端、机头在 -x）                     |
| `--gl-model-up {+x,-x,+y,-y,+z,-z}`          | +y                    | 模型上轴                                                       |
| `--gl-model-rot YAW,PITCH,ROLL`              | 0,0,0                 | 模型姿态微调（度，叠加在轴转换之后）                                         |
| `--gl-model-scale F\|0`                      | 0                     | 模型缩放；0 = auto（最长包围盒边归一到机身长度）                               |
| `--gl-model-center {bbox,origin}`            | bbox                  | 居中方式：bbox 减包围盒中心（模型原点=COM），origin 保留原点                     |
| `--gl-camera {fixed,chase,chase2}`           | fixed                 | 机位：fixed 走廊全景（1280×720）/ chase 后上方跟随（1024×576）/ chase2 低空平视跟随（视线近水平平行于地面，1024×576） |
| `--gl-size WxH`                              | 按机位                   | 渲染分辨率覆盖                                                    |
| `--gl-vert K`                                | fixed 3.0 / chase 1.0 | 场景竖直增强系数；**只作用于视图矩阵，模型姿态保持物理正确**                           |
| `--gl-trail-state {alt,none}`                | alt                   | 拖尾着色：alt = 高空暖橙 → 低空亮绿渐变，none = 恒定蓝                         |
| `--gl-trail-width PX`                        | 4                     | 拖尾屏幕像素宽度；0 = 关闭拖尾                                          |
| `--gl-skybox / --no-gl-skybox`               | 开                     | 使用等距柱状环境贴图（assets/skyview.jpg）作为天空；关闭退回渐变天空                       |
| `--gl-hud / --no-gl-hud`                     | 开                     | 回放叠加飞行数据 HUD                                               |
| `--gl-preview [T]`                           | -                     | 仿真后输出 t=T 秒单帧 PNG 到 `<outdir>/gl_preview.png`              |
| `--gl-pose-set {level,pitch20,bank30,yaw90}` | -                     | 配合 `--gl-preview`：用规范静态姿态替代该时刻真实姿态                         |
| `--gl-live`                                  | -                     | 仿真后在原生 glfw 窗口实时播放（默认 chase 机位）                            |
| `--gl-pose-check`                            | -                     | 姿态链路端到端自检后退出（详见下节）                                         |

### GLB 模型约定与姿态处理

模型从文件到画面经过四步，全部在 `gl_mesh.py` 的 `fit_parts` 中**烘焙进顶点**；
之后的模型矩阵 `T(pos)·R(quat)·S(scale)` 是纯物理量，不含任何隐藏旋转：

1. **轴转换 R\_conv**（`--gl-model-fwd/--gl-model-up`）：把"模型自身的前/上"对齐到
   机体 x 前 / y 上（右手系，`model_fwd×model_up → body +z`），解决不同建模软件
   朝向不一的问题；
2. **微调**（`--gl-model-rot`）：轴对齐后的小角度修正（度）；
3. **联合归一化**（`--gl-model-scale/--gl-model-center`）：多部件整体包围盒居中、
   最长边缩放到 `aircraft.Glider.length` 量级（多部件一起变换，防止散架）；
4. **逐帧姿态**：物理仿真输出的四元数 `tele["quat"]`（xyzw）经 pyGLM `mat4_cast`
   生成旋转；法线用 `mat3(u_model)` 变换后归一化。

**`--gl-pose-check`** **姿态保险栓**：对 level / pitch20° / bank30° / yaw90° 四个规范姿态
× 三轴（机头/上/右翼），断言渲染链
`T(pos)·R_glm(quat)·S(k)·(R_total @ model_axis)` 与物理链
`pos + k·quat_rotate(quat, R_total @ model_axis)` 逐项一致（float64，容差 1e-9；
`quat_rotate` 与物理积分同源）。任何轴约定漂移都会在此暴露，退出码非 0。

### 回退行为

* `--gl-preview / --gl-live` 依赖缺失或 GL 上下文创建失败 → 告警后跳过该调试通道（仿真与图表不受影响）；

* **默认模型** `airplane.glb` 缺失/损坏 → stderr 告警 + 程序化盒体（尺寸与机身一致）；

* **显式** **`--gl-model`** 加载失败 → 直接报错（不静默换模型，姿态问题要显式暴露）；

* 不装 GL 依赖（moderngl/trimesh/pyglm）时默认 mpl 路径完全不受影响。

***

## 8. 常见问题

* **`--backend novaphy`** **报“novaPhy 不可用”**：确认在 Linux x86\_64 + CPython 3.11
  环境，且 `pip install` 成功；可先 `python -c "import novaphy"` 自检。
* **HUD/图表里的中文字体方块**：文本用英文避免 DejaVu 无 CJK 字形。
* **想改机型**：改 `aircraft.py` 的质量/惯量/翼面积/AC 位置即可（气动自动适配）。
* **想看交互式 ViewerGL 窗口**：原交互脚本（`glider_interactive.py` 等）已从本仓库移除，
  平台统一使用 headless 的 `sim_service.py`（matplotlib 出图）。
* **回放渲染缺 L/D 数据**：L/D 需要气动系数，属可选扩展通道；`sim_service.py` 产出的
  `flight_trace.npz` / `flight_trace.bin` 自带 `CL/CD` 通道；自行构造的轨迹若无该通道需自行降级。
