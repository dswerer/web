# 滑翔机飞行轨迹接口 · 渲染接入指南

> **读者对象**：负责飞行回放渲染的开发者（前端 three.js）。
> **目标**：把一次试飞的**逐帧位置 / 姿态 / 速度**数据取到手并渲染回放。
> **设计原则**：物理仿真与渲染完全解耦——仿真只产出数据，渲染只消费数据；
> 渲染侧可自由选择任何技术（three.js / WebGPU / 其它），只需遵守本文的数据契约。

---

## 1. 数据链路一图流

```
学生提交试飞参数（前端表单）
  → 后端 spawn 物理仿真（simulation/glider/sim_service.py；novaPhy / numpy 参考后端）
  → 产出 flight_trace.bin（ftrc 二进制：逐帧状态向量，含 CL/CD）
  → 后端入库（SQLite glider_trajectories 表，zlib 压缩存储）
  → HTTP 接口按需读取（本文件第 2 节）
  → 前端渲染回放（three.js：位置 + 四元数直接驱动飞机模型）
```

点击「开始试飞」后，前端**轮询状态**（通常 20~60 秒，视引擎与机器环境），`status` 变为
`success` 后即可取轨迹数据渲染。**新试飞不再生成任何视频文件**（如你的环境中已存在
旧记录，其 `flight_replay.mp4` 仍可播放，仅为兼容保留）。

---

## 2. HTTP 接口

统一前缀 `/api`（开发环境直连 `http://localhost:3000/api`，生产经 Nginx 同源反代）。
除签名播放地址外均需登录态；渲染者**推荐直接使用项目已封装的 axios client**
（`frontend/src/api/client.js`，自动携带 `Authorization: Bearer <token>` 并处理 401 刷新）。

### 2.1 轮询试飞状态

```http
GET /api/glider/simulations/:id
```

响应（节选）：

```json
{
  "id": 7,
  "status": "success",            // running | success | error
  "state": "landed",              // ok | landed | hard_landing | crashed(roll) | stalled/slow | timedout
  "glide_time_s": 75.47,
  "wing_area": 20, "mass": 500,   // 本次试飞的设计参数
  "result": { "distance_m": 2417.3, "glide_ratio": 16.4, "files": { "...": "..." } },
  "error": null
}
```

> 渲染时机：**仅在 `status === 'success'` 时取轨迹**（running 期间数据尚未入库；
> error 时可能没有轨迹数据）。前端现有轮询逻辑为每 2 秒一次，可直接复用。

### 2.2 取逐帧轨迹（渲染数据源）★

```http
GET /api/glider/simulations/:id/trace            # JSON（默认）
GET /api/glider/simulations/:id/trace?format=bin # ftrc 二进制（推荐）
```

**权限**：学生本人 / 其课程导师 / 管理员可读；无权限或无轨迹数据返回 `404`。

**JSON 响应**（`Content-Type: application/json`）：

```json
{
  "simulation_id": 7,
  "format": "ftrc-f32/1",
  "count": 9057,                  // 帧数
  "dim": 11,                      // 状态维度（固定 11）
  "extra_dim": 2,                 // 扩展列数量（CL/CD；可能为 0，需优雅降级）
  "columns": ["t","x","y","z","qx","qy","qz","qw","vx","vy","vz","CL","CD"],
  "frames": [
    [0, 0, 150, 0, 0.01745, 0, 0, 0.9998, 35.98, 1.26, 0, 0.62, 0.031],
    [0.00833, 0.3, 149.98, 0, "..."]
  ]
}
```

- `frames[i]` 为一帧，数值与 `columns` 一一对应（行主序、无表头）。
- JSON 体积较大（约 13×N 个浮点数，75 秒级试飞 ≈ 2 MB），**生产渲染建议走二进制**。

**二进制响应**（`?format=bin`，`Content-Type: application/octet-stream`）：
直接返回原始 ftrc 字节（格式见第 3 节），浏览器侧用 `ArrayBuffer` 接收，
整体比 JSON 小约 60%，且无需解析 JSON。

### 2.3 提交试飞（自测用，可跳过）

```http
POST /api/glider/simulate        # 仅学生角色；body: { dihedral_deg, cg_x, speed, wing_area, mass, elevator_deg, rudder_deg, course_id, lesson_id }
```

提交后返回 `{ id, status: "running" }`，轮询 2.1 至 `success`。

### 2.4 其它相关接口（图片 / 历史视频，非渲染必需）

- `GET /api/glider/simulations/:id/files/:name` —— 结果图片 / CSV / summary.json 下载（blob）。
- `GET /api/glider/simulations/:id/stream-url` —— MP4 回放的短期签名播放地址（仅旧版后端
  产生的历史记录才有；新试飞不再生成视频）。

---

## 3. ftrc 二进制格式（v1）

固定 **20 字节头** + **float32 小端矩阵**（行主序，无 padding、无对齐填充）：

| 偏移 | 类型 | 写入值 | 含义 |
| ---: | --- | --- | --- |
| 0 | char[4] | `"FTRC"` | magic（校验用） |
| 4 | uint32 LE | `1` | 版本号（当前 v1） |
| 8 | uint32 LE | `N` | 帧数 `count` |
| 12 | uint32 LE | `11` | 状态维度 `dim` |
| 16 | uint32 LE | `0~2` | 扩展维度 `extra_dim`（当前为 2：CL、CD） |
| 20 | float32 LE × N×(11+extra_dim) | — | 每帧一行：`[t,x,y,z,qx,qy,qz,qw,vx,vy,vz, CL,CD]` |

- **文件大小公式**：`20 + N × (11 + extra_dim) × 4`（样例文件 8729 帧 ≈ 454 KB）。
- 第 `i` 帧第 `c` 列在字节偏移 `20 + (i × stride + c) × 4`，`stride = 11 + extra_dim`。
- 消费方应校验 magic 与长度后使用；`extra_dim` 可能为 0（无 CL/CD），两种情况都要支持。

---

## 4. 数据语义（渲染要点）

### 4.1 列定义

| 列 | 含义 | 单位 | 备注 |
| --- | --- | --- | --- |
| `t` | 仿真时间 | s | 从 0 开始，**固定步长 1/120 s（120 Hz）**，均匀 |
| `x, y, z` | 世界系质心位置 | m | **Y 向上**（y = 高度）；投放点 `(0, 150, 0)` |
| `qx, qy, qz, qw` | 世界系姿态四元数 | — | **xyzw 顺序**（与 three.js 一致）；机体系→世界系旋转 |
| `vx, vy, vz` | 世界系线速度 | m/s | 空速 `V = ‖v‖`；下沉率 `= -vy` |
| `CL, CD` | 升力 / 阻力系数 | — | 扩展列（可缺省）；`L/D = CL / CD` 可做 HUD |

### 4.2 坐标系与姿态（重要）

- 世界系 **Y 向上**，X/Z 水平——**与 three.js 默认坐标系一致**，位置可直接使用，无需变换。
- 投放：位置 `(0, 150, 0)`，机头朝向 **+X**（方位角 0°），初始俯仰 −2°、横滚 +2°（稳定性扰动）。
- 飞行中方向会变化（转弯 / 侧漂），**不要假设始终沿 +X 飞行**；一律以逐帧四元数为准。
- **机体系约定**：`x` 前（机头）、`y` 上、`z` 右翼。按此约定建模飞机，
  再把每帧四元数应用到模型上，机头即正确朝向前进方向。
  例：默认平飞时四元数接近单位四元数 `(0,0,0,1)`。
- 地面位于 `y = 0`；`landed` 的末帧高度约 `1.5 m`（触地判定高度）。

### 4.3 飞机几何参考（自建模型用）

默认机型：翼展 16 m、机长 7.2 m、翼面积 17.5 m²、质量 420 kg（`wing_area` 变化时
翼展按 `√(S/17.5)` 等比缩放）。渲染模型比例不影响数据，只要场景单位统一为米。

---

## 5. JS 接入示例

### 5.1 取二进制并解析

```js
// 项目已在 frontend/src/api/glider.js 封装好（自动带 token）：
//   gliderAPI.trace(id, 'bin')  → ArrayBuffer（ftrc 二进制，推荐）
//   gliderAPI.trace(id)         → JSON
import { gliderAPI } from '../api/glider';

const buf = await gliderAPI.trace(simId, 'bin');  // ArrayBuffer
const dv = new DataView(buf);

// —— 解析 20B 头 ——
const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
if (magic !== 'FTRC') throw new Error('不是 ftrc 数据');
const version  = dv.getUint32(4, true);
const count    = dv.getUint32(8, true);
const dim      = dv.getUint32(12, true);
const extraDim = dv.getUint32(16, true);
if (version !== 1 || dim !== 11) throw new Error('ftrc 版本/维度不支持');

// —— 帧矩阵（小端 float32；浏览器几乎均为小端，可直接视图） ——
const stride = dim + extraDim;                      // 通常 13
const data = new Float32Array(buf, 20, count * stride);

function frameAt(i) {
  const o = i * stride;
  return {
    t: data[o],
    pos: [data[o + 1], data[o + 2], data[o + 3]],           // (x, y=高度, z)
    quat: [data[o + 4], data[o + 5], data[o + 6], data[o + 7]], // (qx,qy,qz,qw)
    vel: [data[o + 8], data[o + 9], data[o + 10]],
    CL: extraDim > 0 ? data[o + 11] : null,
    CD: extraDim > 1 ? data[o + 12] : null,
  };
}
```

> 若需兼容大端环境，改用 `dv.getFloat32(20 + k * 4, true)` 逐值读取（偏移为 4 的倍数，
> 无对齐问题）。

### 5.2 three.js 应用一帧

```js
const f = frameAt(i);

mesh.position.set(f.pos[0], f.pos[1], f.pos[2]);       // 直接使用（Y-up）
mesh.quaternion.set(f.quat[0], f.quat[1], f.quat[2], f.quat[3]); // set(x,y,z,w)，顺序即 xyzw
```

### 5.3 回放控制建议（可选）

- **采样均匀 120 Hz**：给定回放时间 `t`，索引 `i ≈ t × 120`，无需二分；
  连续播放时按帧号 +1 即可。
- 时间缩放：真实 72 秒的回放可加速（如 2×）或用进度条拖动。
- 插值（若要求平滑）：位置线性插值；姿态用四元数 `slerp`
  （three.js：`q.slerpQuaternions(qa, qb, u)`）。
- 轨迹拖尾：`BufferGeometry.setDrawRange(0, i)` 逐帧增长；地面网格放在 `y = 0`。
- 相机：环绕轨道相机以轨迹包围盒为中心（轨迹可达 2 km 量级，记得调整 far / 比例）。

---

## 6. 如何获得联调数据（重要）

> ⚠️ **数据库与试飞产物不在版本库中**（`backend/database/*.db`、`backend/uploads/` 均被
> gitignore）：**换了机器 / 重新克隆仓库后不存在任何现成试飞记录**——接口数据必须由本机
> 跑出的试飞产生。联调有两条路径：

### 路径 1：用仓库自带的样例文件（零门槛，建议先把这条跑通）

`simulation/glider/samples/flight_trace_sample.bin` —— 一次真实仿真产出的 ftrc 文件
（默认参数，**8729 帧 / 72.73 s / 含 CL·CD**）。**无需启动任何服务、无需数据库**：
直接读取该文件（`fetch()` 或本地文件均可），按第 3、5 节解析即可得到完整帧序列，
先把 three.js 渲染调通。

### 路径 2：本机跑一次完整试飞（联调接口 / 页面时）

1. **初始化本地库**（含种子账号与一门已报名课程）：
   `cd backend && npm run db:init` → 得到 `student_wang / student123`（王小明）等账号。
2. **配置仿真引擎**（二选一，结果行为等价）：
   - 真 novaPhy（Linux / WSL）：见 `simulation/README.md`「三种运行方式」；
   - 纯 numpy 参考后端（任何环境，最快）：
     `pip install -r simulation/glider/requirements.txt`，并在 `backend/.env` 设
     `GLIDER_PYTHON=<本机 python 路径>`、`GLIDER_BACKEND=reference`。
3. **启动前后端**（`start-dev.bat` 或分别 `npm run dev`），浏览器用
   `student_wang / student123` 登录 →「滑翔机模拟实验室」→ 提交一次试飞。
4. **等 `status = success`**（通常 20~60 秒）→ 调 `/trace` 取本机数据；
   点开右侧历史列表中这条记录还能看到结果图片（3D 航迹 / 遥测图）。

---

## 7. 渲染前自检清单

- [ ] 记录 `status === 'success'` 且 trace 请求返回 200（404 = 无权限或无轨迹）。
- [ ] magic === `"FTRC"`、version === 1、`buf.byteLength === 20 + count × (11+extraDim) × 4`。
- [ ] 首帧 `t ≈ 0`、`y ≈ 150`（投放高度）；末帧 `y` 接近地面（landed 时 ≈ 1.5）。
- [ ] `extra_dim === 0` 时必须仍能渲染（跳过 HUD 的 L/D 等）。

---

## 8. 相关文件索引

| 文件 | 作用 |
| --- | --- |
| `simulation/glider/flight_trace.py` | ★ 数据契约权威定义（列 / 格式 / 单位 / 坐标系） |
| `simulation/glider/sim_service.py` | 物理仿真入口（产出 `flight_trace.bin` / `.npz`） |
| `backend/controllers/gliderController.js` | 接口实现（`exports.trace`、入库 `storeTrajectory`） |
| `frontend/src/pages/glider/Simulator.jsx` | 试飞页面（轮询逻辑；回放区待接入 three.js） |
| `frontend/src/api/glider.js` | 前端 API 封装（已提供 `trace(id, format)`） |
| `simulation/glider/samples/` | ★ 样例轨迹文件（联调用，见第 6 节路径 1） |
| `simulation/glider/README.md` | 物理模型与参数说明 |
