"""plot_flight.py — 飞行遥测 2D 图表（高度剖面 / 空速 / 迎角 / L/D / 俯仰 / 舵面）。

生成 PNG，用于文档说明“气动特性符合预期”（稳定滑翔、恒定迎角/空速等）。
"""

from __future__ import annotations

import os

import numpy as np


def plot_flight(tele, out_png: str, title="Glider flight telemetry (NovaPhy aero model)"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = tele["t"]
    fig, axes = plt.subplots(4, 1, figsize=(11, 11), sharex=True)

    ax = axes[0]
    ax.plot(t, tele["alt"], color="tab:blue", lw=1.2)
    ax.set_ylabel("altitude (m)")
    ax.grid(alpha=0.3)
    ax.set_title(title)

    ax = axes[1]
    ax.plot(t, tele["V"], color="tab:green", lw=1.2, label="airspeed")
    ax.plot(t, np.full_like(t, np.median(tele["V"])),
            "--", color="tab:green", alpha=0.6, label="median")
    ax.set_ylabel("V (m/s)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[2]
    ax.plot(t, np.degrees(tele["alpha"]), color="tab:red", lw=1.2, label="AoA")
    ax.plot(t, tele["sink"], color="tab:orange", lw=1.2, label="sink rate")
    ax.set_ylabel("AoA (deg) / sink (m/s)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[3]
    ld = np.divide(tele["CL"], np.maximum(tele["CD"], 1e-4))
    ax.plot(t, ld, color="tab:purple", lw=1.2, label="L/D")
    ax.axhline(np.median(ld[50:]) if len(ld) > 50 else np.median(ld),
               ls="--", color="tab:purple", alpha=0.6, label="median L/D")
    ax.set_ylabel("L/D")
    ax.set_xlabel("time (s)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_png, dpi=120, facecolor="white")
    plt.close(fig)
    return out_png


def _zup(v):
    """世界坐标 (x, 高度, z) -> matplotlib 3D 坐标 (x, z, 高度)。

    与 render.py 固定机位（draw_world_frame）保持同一约定：mpl 的 z 轴（屏幕竖直
    方向）是高度，地面 = 高度 0 的水平面，铺在画面下方。
    """
    return np.asarray(v, dtype=float)[..., [0, 2, 1]]


def _nice_step(span: float, target: int = 10) -> float:
    """给地面网格选一个 1/2/5×10^k 的“整数感”间距。"""
    import math
    raw = max(float(span), 1e-6) / max(int(target), 1)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        if raw <= m * mag:
            return m * mag
    return 10.0 * mag


def plot_trajectory_3d_view(tele, out_png: str, title="3D flight path (world view)"):
    """世界系整体航迹 3D 图（竖直轴 = 高度、地面在下方，适合看盘旋/滑翔全貌）。

    坐标约定与固定机位回放视频一致：mpl 的 z 轴为高度（向上），地面（高度 0 的
    水平面）画在最下方；水平两轴为世界 X（航迹主方向）与世界 Z（侧向）。
    """
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    pos = np.asarray(tele["pos"], dtype=float)      # 世界系 (x, 高度, z)
    alt = pos[:, 1]
    pts = _zup(pos)                                 # -> mpl (x, z, 高度)

    # ---- 取景：覆盖整段航迹；竖直方向从地面 0 起 ----
    pad = 0.06
    x_span = max(float(pts[:, 0].max() - pts[:, 0].min()), 60.0)
    x0 = float(pts[:, 0].min()) - x_span * pad
    x1 = float(pts[:, 0].max()) + x_span * pad
    # 侧向（世界 Z）以航迹为中心；航迹几乎无侧移时按比例撑开，避免地面退化成一条线
    z_mid = 0.5 * float(pts[:, 1].min() + pts[:, 1].max())
    z_half = max(0.5 * float(pts[:, 1].max() - pts[:, 1].min()),
                 0.08 * (x1 - x0), 40.0)
    y0, y1 = z_mid - z_half, z_mid + z_half
    z0 = 0.0                                        # 地面：竖直轴 0
    z1 = max(float(alt.max()), 1.0) * 1.08 + 8.0

    fig = plt.figure(figsize=(9.5, 7.5))
    ax = fig.add_subplot(111, projection="3d")

    # ---- 地面网格：高度 0 的水平面（画在竖直轴 0 上） ----
    step_x = _nice_step(x1 - x0, 12)
    step_y = _nice_step(max(y1 - y0, step_x), 8)
    segs = []
    xx = math.floor(x0 / step_x) * step_x
    while xx <= x1:
        segs.append([(xx, y0, 0.0), (xx, y1, 0.0)])
        xx += step_x
    yy = math.floor(y0 / step_y) * step_y
    while yy <= y1:
        segs.append([(x0, yy, 0.0), (x1, yy, 0.0)])
        yy += step_y
    if segs:
        ax.add_collection3d(Line3DCollection(
            segs, colors=[(0.45, 0.6, 0.45, 0.55)] * len(segs), linewidths=0.6))

    # ---- 航迹（按高度着色） ----
    seg_arr = np.stack([pts[:-1], pts[1:]], axis=1)
    lc = Line3DCollection(seg_arr, cmap="viridis", linewidth=2.0)
    lc.set_array(alt[:-1])
    ax.add_collection3d(lc)
    cbar = fig.colorbar(lc, ax=ax, shrink=0.6, pad=0.10)
    cbar.set_label("altitude (m)")

    # ---- 投放点 / 终点 ----
    ax.scatter(*pts[0], color="green", s=45, label="release", depthshade=False)
    ax.scatter(*pts[-1], color="red", s=45, label="end", depthshade=False)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_zlim(z0, z1)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Z (m)")
    ax.set_zlabel("altitude (m)")
    ax.set_title(title)
    ax.legend(fontsize=8, loc="upper right")
    ax.view_init(elev=20, azim=-62)

    # 长航程（滑翔比大）时竖直方向按显示比例拉伸，保证下滑过程看得清；图内注明比例
    z_disp = max(z1 - z0, 0.25 * max(x1 - x0, y1 - y0))
    ax.set_box_aspect((x1 - x0, y1 - y0, z_disp))
    if z_disp > 1.05 * (z1 - z0):
        fig.text(0.012, 0.015,
                 f"vertical axis stretched x{z_disp / max(z1 - z0, 1e-9):.1f} for readability",
                 fontsize=8, color="0.35")

    fig.tight_layout()
    fig.savefig(out_png, dpi=120, facecolor="white")
    plt.close(fig)
    return out_png
