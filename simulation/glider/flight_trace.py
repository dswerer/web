"""flight_trace.py — 物理仿真对外的最小向量接口（数据契约）。

本模块是「物理仿真」与「渲染 / 回放」之间**唯一**的数据契约：

    FlightTrace = 逐帧刚体状态向量序列
    帧向量布局（11 列）：
        [t, x, y, z, qx, qy, qz, qw, vx, vy, vz]

约定（与 spatial.py / aircraft.py / novaPhy 一致）：
  - 世界系 Y 向上；四元数顺序 xyzw；
  - 单位：米、米/秒、秒；
  - (x, y, z) 为质心位置（y = 高度），(vx, vy, vz) 为世界系线速度。

设计原则
--------
- **最小**：只包含渲染/回放所必需的运动状态（时间 + 位置 + 姿态 + 速度），
  不含气动系数、舵面、角速度等引擎内部细节；这些可由状态向量另行派生。
- **单向依赖**：本模块只依赖 numpy，不导入任何仿真/渲染代码；
  仿真侧（sim_core）负责生产 FlightTrace，渲染侧（前端 three.js 回放 / 后置分析工具）只消费 FlightTrace。
- **可选扩展通道 extras**：不属于最小接口，仅用于 HUD 等增强显示
  （如 CL/CD 用于显示 L/D）。缺失时消费方必须能优雅降级。
- **可序列化**：save()/load() 落盘为 .npz（含 meta 与 extras），
  支持「先算物理、后置渲染」：任何进程拿到 trace 文件即可渲染回放或做后置分析。
"""

from __future__ import annotations

import json
import struct

import numpy as np

# 最小向量契约：帧向量列名与维度（顺序即数组列序，勿随意调整）
STATE_COLUMNS = ("t", "x", "y", "z", "qx", "qy", "qz", "qw", "vx", "vy", "vz")
STATE_DIM = len(STATE_COLUMNS)

# 序列化格式标识（.npz 内的 "format" 键）
TRACE_FORMAT = "flight-trace/1"

# extras 通道在 .npz 中的键前缀
_EXTRA_PREFIX = "extra__"

# ---------------------------------------------------------------------------
# ftrc 二进制交换格式（Node / 浏览器可直接解析，无需 numpy）
#   头部 20 字节：magic "FTRC" + version u32 + count u32 + dim u32 + extra_dim u32
#   数据：count × (dim + extra_dim) 的 float32 小端、行主序
#   扩展列按 BIN_EXTRA_COLUMNS 顺序（当前 CL/CD，供 HUD 显示 L/D）
# ---------------------------------------------------------------------------
BIN_MAGIC = b"FTRC"
BIN_VERSION = 1
BIN_EXTRA_COLUMNS = ("CL", "CD")
_BIN_HEADER = struct.Struct("<4sIIII")


class FlightTrace:
    """物理仿真产出的最小向量接口：逐帧刚体状态向量序列。

    所有对外访问均为只读；消费方（渲染、回放、分析）不得修改帧数据。
    """

    def __init__(self, frames, meta=None, extras=None):
        """
        frames : array_like, shape (N, 11)
            每行 = [t, x, y, z, qx, qy, qz, qw, vx, vy, vz]（见 STATE_COLUMNS）。
        meta : dict | None
            描述性元信息（机型/参数/后端/reason 等），不参与渲染计算。
        extras : dict[str, array_like] | None
            可选扩展通道（如 {"CL": (...), "CD": (...)}），长度须与帧数一致。
        """
        frames = np.asarray(frames, dtype=float)
        if frames.size == 0:
            frames = np.zeros((0, STATE_DIM), dtype=float)
        if frames.ndim != 2 or frames.shape[1] != STATE_DIM:
            raise ValueError(
                f"FlightTrace 帧矩阵必须是 (N, {STATE_DIM})：{STATE_COLUMNS}，"
                f"实际 shape={frames.shape}"
            )
        self._frames = frames
        self.meta = dict(meta or {})
        self.extras = {}
        for name, arr in (extras or {}).items():
            arr = np.asarray(arr, dtype=float)
            if arr.shape[0] != frames.shape[0]:
                raise ValueError(
                    f"扩展通道 {name!r} 长度 {arr.shape[0]} 与帧数 {frames.shape[0]} 不一致"
                )
            self.extras[str(name)] = arr

    # ------------------------------------------------------------------
    # 基本属性（只读）
    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return int(self._frames.shape[0])

    @property
    def count(self) -> int:
        """帧数。"""
        return len(self)

    @property
    def times(self) -> np.ndarray:
        """(N,) 每帧仿真时间 t (s)。"""
        return self._frames[:, 0]

    @property
    def positions(self) -> np.ndarray:
        """(N, 3) 世界系质心位置 (x, y, z)，y 为高度。"""
        return self._frames[:, 1:4]

    @property
    def quaternions(self) -> np.ndarray:
        """(N, 4) 世界系姿态四元数 xyzw。"""
        return self._frames[:, 4:8]

    @property
    def velocities(self) -> np.ndarray:
        """(N, 3) 世界系线速度 (vx, vy, vz)。"""
        return self._frames[:, 8:11]

    @property
    def t_start(self) -> float:
        """首帧时间 (s)；空轨迹为 0。"""
        return float(self._frames[0, 0]) if len(self) else 0.0

    @property
    def t_end(self) -> float:
        """末帧时间 (s)；空轨迹为 0。"""
        return float(self._frames[-1, 0]) if len(self) else 0.0

    @property
    def duration(self) -> float:
        """轨迹时长 (s)。"""
        return self.t_end - self.t_start

    # ------------------------------------------------------------------
    # 帧级访问
    # ------------------------------------------------------------------
    def state_at(self, i: int) -> np.ndarray:
        """第 i 帧的最小状态向量 [t, x, y, z, qx, qy, qz, qw, vx, vy, vz]（副本）。"""
        return self._frames[int(i)].copy()

    def index_at(self, t: float) -> int:
        """时间 t 对应的帧索引（t 之后的最近一帧）。

        语义与 ``np.searchsorted(times, t)`` 一致：返回值 == count 表示 t 超出末尾，
        调用方需自行判断。
        """
        return int(np.searchsorted(self._frames[:, 0], float(t)))

    def window(self, start_s: float, end_s: float) -> "FlightTrace":
        """返回时间窗口 [start_s, end_s] 内的子轨迹（含边界帧）。"""
        i0 = self.index_at(start_s)
        i1 = int(np.searchsorted(self._frames[:, 0], float(end_s), side="right"))
        return FlightTrace(
            self._frames[i0:i1],
            meta=self.meta,
            extras={k: v[i0:i1] for k, v in self.extras.items()},
        )

    # ------------------------------------------------------------------
    # 可选扩展通道
    # ------------------------------------------------------------------
    def channel(self, name: str):
        """取扩展通道数组；不存在返回 None（消费方须能优雅降级）。"""
        return self.extras.get(str(name))

    # ------------------------------------------------------------------
    # 序列化（.npz）
    # ------------------------------------------------------------------
    def save(self, path) -> str:
        """落盘为 .npz（frames + meta + extras + format），返回路径字符串。"""
        arrays = {
            "format": np.array(TRACE_FORMAT),
            "frames": self._frames,
            "meta_json": np.array(json.dumps(self.meta, ensure_ascii=False)),
        }
        for name, arr in self.extras.items():
            arrays[_EXTRA_PREFIX + name] = arr
        np.savez_compressed(path, **arrays)
        return str(path)

    def save_bin(self, path) -> str:
        """写出 ftrc 二进制（Node / 浏览器直读；含可选扩展列），返回路径字符串。"""
        extras = [self.extras[name] for name in BIN_EXTRA_COLUMNS if name in self.extras]
        header = _BIN_HEADER.pack(BIN_MAGIC, BIN_VERSION, len(self), STATE_DIM, len(extras))
        mat = np.column_stack([self._frames, *extras]) if extras else self._frames
        with open(path, "wb") as f:
            f.write(header)
            f.write(np.ascontiguousarray(mat, dtype="<f4").tobytes())
        return str(path)

    @classmethod
    def load(cls, path) -> "FlightTrace":
        """读取轨迹文件：按文件头自动识别 ftrc 二进制（.bin）与 .npz。"""
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic == BIN_MAGIC:
            return cls.load_bin(path)
        return cls._load_npz(path)

    @classmethod
    def load_bin(cls, path) -> "FlightTrace":
        """读取 ftrc 二进制；扩展列按 BIN_EXTRA_COLUMNS 还原为 extras。"""
        with open(path, "rb") as f:
            head = f.read(_BIN_HEADER.size)
            if len(head) != _BIN_HEADER.size:
                raise ValueError(f"ftrc 文件头不完整：{path}")
            magic, version, count, dim, extra_dim = _BIN_HEADER.unpack(head)
            if magic != BIN_MAGIC:
                raise ValueError(f"不是 ftrc 文件（magic={magic!r}）：{path}")
            if version != BIN_VERSION:
                raise ValueError(f"不支持的 ftrc 版本 {version}：{path}")
            if dim != STATE_DIM or extra_dim > len(BIN_EXTRA_COLUMNS):
                raise ValueError(f"ftrc 维度不符合契约（dim={dim}, extra_dim={extra_dim}）：{path}")
            data = f.read(int(count) * int(dim + extra_dim) * 4)
        mat = np.frombuffer(data, dtype="<f4").astype(float)
        if mat.size != int(count) * int(dim + extra_dim):
            raise ValueError(f"ftrc 数据长度不足：{path}")
        mat = mat.reshape(int(count), int(dim + extra_dim))
        extras = {name: mat[:, dim + i]
                  for i, name in enumerate(BIN_EXTRA_COLUMNS[:extra_dim])}
        return cls(mat[:, :dim], extras=extras)

    @classmethod
    def _load_npz(cls, path) -> "FlightTrace":
        """读取 save() 落盘的 .npz 轨迹文件。"""
        with np.load(path, allow_pickle=False) as z:
            frames = z["frames"]
            meta = {}
            if "meta_json" in z.files:
                meta = json.loads(str(z["meta_json"]))
            extras = {
                k[len(_EXTRA_PREFIX):]: z[k]
                for k in z.files
                if k.startswith(_EXTRA_PREFIX)
            }
        return cls(frames, meta=meta, extras=extras)
