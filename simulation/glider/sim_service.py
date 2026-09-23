#!/usr/bin/env python3
"""sim_service.py — 供 PBL 平台后端调用的滑翔机模拟服务（headless，进程内一次性）。

复用 glider_sim 的气动模型与积分后端（aircraft / aero / sim_core），学生提交
  上反角(°)  +  重心前移量(m)  +  初始投放速度(m/s)
后由平台后端 spawn 本脚本，在 --outdir 输出：
  summary.json          指标摘要（含 reason / glide_time / 距离 / 下沉率 / L/D 等）
  flight_telemetry.csv  全量遥测
  flight_telemetry.png  高度/空速/迎角/下沉率/L-D 曲线
  trajectory3d.png      世界系 3D 航迹
最终向 stdout 打印一行 JSON（平台后端据此落库）。

后端自动选择：
  - Linux x86_64 + CPython 3.11 且装有 novaphy wheel → novaPhy 物理后端（默认 prefer）；
  - 其它环境（Windows / 无 novaPhy）→ 纯 numpy reference 后端（行为等价，仅积分实现不同）。
可用 --backend novaphy|reference 强制指定。

示例：
  python sim_service.py --dihedral 5 --cg 0.0 --speed 36 --alt 150 --outdir output/sim1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import sys

# numpy / aircraft / sim_core 均为延迟导入（见 main）：
# --probe 诊断模式需要在依赖缺失时仍能启动并输出环境报告。


def _novaphy_usable():
    try:
        from backend_novaphy import novaphy as _nv
        return _nv is not None
    except Exception:  # noqa: BLE001
        return False


def _detect_backend_name():
    if _novaphy_usable():
        return "novaphy"
    try:
        import numpy  # noqa: F401
        return "reference"
    except Exception:  # noqa: BLE001
        return ""


def _probe(probe_outdir):
    """输出引擎环境探测 JSON（不执行仿真）。"""

    def has(mod):
        try:
            __import__(mod)
            return True
        except Exception:  # noqa: BLE001
            return False

    result = {
        "ready": False,
        "python": platform.python_version(),
        "backend": "",
        "numpy": has("numpy"),
        "matplotlib": has("matplotlib"),
        "ffmpeg": False,
        "novaphy": _novaphy_usable(),
        "opengl": has("moderngl") and has("moderngl_window"),
        "renderer": _default_renderer(),
        "outputWritable": False,
    }
    result["backend"] = "novaphy" if result["novaphy"] else ("reference" if result["numpy"] else "")
    try:
        import imageio_ffmpeg
        result["ffmpeg"] = hasattr(imageio_ffmpeg, "get_ffmpeg_exe")
    except Exception:  # noqa: BLE001
        result["ffmpeg"] = False

    outdir = os.path.abspath(probe_outdir or "output/_probe")
    try:
        os.makedirs(outdir, exist_ok=True)
        probe_file = os.path.join(outdir, ".probe.tmp")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        result["outputWritable"] = True
    except Exception:  # noqa: BLE001
        result["outputWritable"] = False

    # ready = 可完成一次参考/真机仿真：需要 numpy + 后端 + matplotlib + 输出目录可写；
    # ffmpeg 仅影响 MP4 回放（缺失时优雅跳过），不参与 ready 判定。
    result["ready"] = bool(
        result["numpy"] and result["backend"] and result["matplotlib"] and result["outputWritable"]
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _default_renderer():
    """默认渲染途径：环境变量 ``GLIDER_RENDERER``（mpl|gl），默认 matplotlib。"""
    return (os.environ.get("GLIDER_RENDERER") or "mpl").strip().lower()


def _parse_size(text, default=(1280, 720)):
    """解析 ``WxH``（也接受 ``W,H``）；非法时回退默认值。H.264 要求偶数尺寸。"""
    try:
        w, h = (int(v) for v in str(text).lower().replace(",", "x").split("x"))
    except Exception:  # noqa: BLE001
        return default
    if w < 16 or h < 16:
        return default
    return (w - w % 2, h - h % 2)


def _gl_video(tele, glider, out_path, duration, fps, args):
    """GL 渲染分支：失败时向上抛异常，由调用方回退 matplotlib。"""
    from render_gl import make_video_gl

    if args.gl_camera == "chase":
        cfg_view = {"trail": 500, "ground": 300.0, "spacing": 30.0}
    else:
        cfg_view = {"trail": 5000, "spacing": 80.0}
    if float(args.gl_scale) > 0:
        cfg_view["scale"] = float(args.gl_scale)
    # 竖直增强：让固定机位高度波动接近 matplotlib 的观感（--gl-vert 可调，设 1 关闭）
    if float(args.gl_vert) > 0:
        cfg_view["vert"] = float(args.gl_vert)

    make_video_gl(
        tele, glider, out_path, fps=fps, start=0.0, end=duration,
        camera=args.gl_camera, cfg_view=cfg_view, hud=True,
        size=_parse_size(args.gl_size), aa=max(1, int(args.gl_aa)),
        model_path=args.model or None, model_scale=float(args.model_scale),
        model_rot=tuple(float(v) for v in args.model_rot),
        shader_dir=args.shader_dir or None,
        preview_png=args.gl_preview or None, dump_uniforms=bool(args.dump_uniforms),
        # --dump-uniforms 时顺带把"网格来源/上下文/uniform 快照"打到 stdout，便于自检
        progress=print if args.dump_uniforms else (lambda *a, **k: None))


def _pick_backend(name):
    if name == "reference":
        from backend_reference import ReferenceBackend
        return ReferenceBackend
    usable = _novaphy_usable()
    if name == "novaphy":
        if not usable:
            raise SystemExit("novaPhy 后端不可用：请改用 --backend reference，"
                             "或在 Linux x86_64 + CPython 3.11 环境安装 novaphy wheel 后运行。")
        from backend_novaphy import NovaPhyBackend
        return NovaPhyBackend
    if usable:
        from backend_novaphy import NovaPhyBackend
        return NovaPhyBackend
    from backend_reference import ReferenceBackend
    return ReferenceBackend


def write_csv(tele, path):
    keys = ["t", "alt", "V", "alpha", "sink", "CL", "CD", "bank", "pitch"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        n = len(tele["t"])
        for i in range(n):
            w.writerow([float(tele[k][i]) for k in keys])


def write_plots(tele, outdir, backend_name, params):
    from plot_flight import plot_flight, plot_trajectory_3d_view
    tag = f"[{backend_name}]  CG={params['cg']:+.2f}m  dihedral={params['dihedral']}deg  V0={params['speed']}m/s"
    plot_flight(tele, os.path.join(outdir, "flight_telemetry.png"),
                title=f"Glider telemetry  {tag}")
    plot_trajectory_3d_view(tele, os.path.join(outdir, "trajectory3d.png"),
                            title=f"3D flight path  {tag}")


def main(argv=None):
    p = argparse.ArgumentParser(description="PBL 滑翔机模拟服务（headless）")
    p.add_argument("--probe", action="store_true", help="输出引擎环境探测 JSON 后退出")
    p.add_argument("--probe-outdir", default="output/_probe", help="探测输出可写性时使用的目录")
    p.add_argument("--dihedral", type=float, default=0.0, help="机翼上反角 (°)")
    p.add_argument("--cg", type=float, default=0.0,
                   help="重心相对默认沿机体前移量 (m)，>0 靠前（静稳↑/时长短），<0 靠后（易失稳）")
    p.add_argument("--speed", type=float, default=36.0, help="初始投放速度 (m/s)")
    p.add_argument("--alt", type=float, default=150.0, help="投放高度 (m)")
    p.add_argument("--timeout", type=float, default=90.0, help="最长仿真时间 (s)")
    p.add_argument("--autolevel", action=argparse.BooleanOptionalAction, default=False,
                   help="默认关闭横滚/偏航自动保持：考察上反角与重心对被动稳定性的真实影响；"
                        "--autolevel 可开启让飞机更易保持平飞")
    p.add_argument("--backend", default="auto", choices=["auto", "novaphy", "reference"])
    p.add_argument("--video", action="store_true", help="额外渲染 MP4 飞行回放（需 imageio-ffmpeg）")
    p.add_argument("--video-fps", type=int, default=12, help="回放帧率")
    p.add_argument("--video-max", type=float, default=60.0,
                   help="回放最长覆盖仿真秒数（实际取 min(整段时长, 该值))")
    p.add_argument("--renderer", default=_default_renderer(), choices=["mpl", "gl"],
                   help="回放渲染途径：mpl（matplotlib，默认）/ gl（OpenGL，不可用时自动回退 mpl）")
    p.add_argument("--gl-size", default="1280x720", help="GL 渲染分辨率 WxH（H.264 要求偶数）")
    p.add_argument("--gl-aa", type=int, default=1, help="GL 超采样倍数（抗锯齿，>1 更慢）")
    p.add_argument("--gl-camera", default="fixed", choices=["fixed", "chase"],
                   help="GL 机位：fixed 固定世界机位 / chase 追逐机位")
    p.add_argument("--gl-scale", type=float, default=0.0,
                   help="飞机显示放大倍数（0=按机位自动：fixed 6.0 / chase 1.0）")
    p.add_argument("--gl-vert", type=float, default=3.0,
                   help="固定机位竖直增强系数（放大高度波动以接近 matplotlib 观感；设 1 关闭等比例）")
    p.add_argument("--model", default="",
                   help="飞机 OBJ 模型路径；留空则自动用 assets/airplane.obj，缺失时用程序化网格")
    p.add_argument("--model-rot", type=float, nargs=3, default=(0.0, 0.0, 0.0),
                   metavar=("RX", "RY", "RZ"), help="模型朝向修正（度），模型不是 x 前/y 上/z 右时用")
    p.add_argument("--model-scale", type=float, default=0.0,
                   help="模型显式缩放；0=按最长轴自动归一化到机身长度")
    p.add_argument("--shader-dir", default="",
                   help="外部着色器目录（含 aircraft.vert/frag、line.vert/frag），用于热替换")
    p.add_argument("--gl-preview", default="", help="额外输出 GL 首帧 PNG 路径（调试/比对用）")
    p.add_argument("--dump-uniforms", action="store_true",
                   help="把 GL 首帧的完整 uniform 快照打印为 JSON（自检契约）")
    p.add_argument("--outdir", default="output/sim", help="输出目录")
    args = p.parse_args(argv)

    if args.probe:
        return _probe(args.probe_outdir)

    # 正式仿真才导入重依赖（numpy / 气动模型），保证 --probe 在依赖缺失时也能诊断
    from aircraft import Glider
    from sim_core import SimConfig, run_flight, flight_summary

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    glider = Glider(dihedral_deg=float(args.dihedral), cg_x=float(args.cg))
    cfg = SimConfig()
    cfg.start_alt = float(args.alt)
    cfg.start_speed = float(args.speed)
    cfg.V_ref = 31.0
    cfg.sim_time = float(args.timeout)
    cfg.maneuver = "straight"
    if not args.autolevel:
        # 关闭主动横滚/偏航保持，让学生观察布局参数（上反角/重心）产生的被动稳定效果
        cfg.gain_roll = 0.0
        cfg.gain_roll_rate = 0.0
        cfg.gain_beta = 0.0
        cfg.gain_yaw_rate = 0.0

    BackendCls = _pick_backend(args.backend)
    backend = BackendCls(glider)
    tele = run_flight(backend, glider, cfg)
    summary = flight_summary(tele)

    files = {"summary": "summary.json", "csv": "flight_telemetry.csv",
             "telemetry_png": "flight_telemetry.png", "trajectory_png": "trajectory3d.png",
             "video": "flight_replay.mp4"}
    write_csv(tele, os.path.join(outdir, files["csv"]))
    write_plots(tele, outdir, backend.name, {
        "cg": args.cg, "dihedral": args.dihedral, "speed": args.speed})

    # 可选：MP4 飞行回放（依赖 imageio-ffmpeg；缺失/失败时跳过，不影响主结果）
    if args.video:
        vdur = min(float(tele["t"][-1]), max(5.0, float(args.video_max)))
        video_path = os.path.join(outdir, files["video"])
        fps = max(4, int(args.video_fps))
        renderer = args.renderer

        if renderer == "gl":
            try:
                _gl_video(tele, glider, video_path, vdur, fps, args)
                print(f"[video] wrote {files['video']} "
                      f"(gl/{args.gl_camera} @ {args.video_fps}fps)")
            except Exception as exc:  # noqa: BLE001 无 GL 上下文/依赖时优雅回退
                print(f"[video] gl 渲染不可用，回退 matplotlib：{exc}", file=sys.stderr)
                renderer = "mpl"

        if renderer == "mpl":
            try:
                from render import make_video
                make_video(
                    tele, glider, video_path,
                    fps=fps, start=0.0, end=vdur,
                    camera="fixed",
                    cfg_view=dict(spacing=80.0, trail=5000, elev=30, azim=-90,
                                  scale=6.0, ground_color=(0.45, 0.6, 0.45, 0.4),
                                  trail_color=(0.2, 0.45, 0.85, 0.95)),
                    hud=True, figsize=(10.0, 7.5), dpi=100,
                    progress=lambda *a, **k: None)
                print(f"[video] wrote {files['video']} ({vdur:.0f}s @ {args.video_fps}fps)")
            except ImportError as exc:
                print(f"[video] skipped: {exc}", file=sys.stderr)
                files["video"] = None
            except Exception as exc:  # noqa: BLE001
                print(f"[video] failed: {exc}", file=sys.stderr)
                files["video"] = None
    else:
        files["video"] = None

    backend.close()

    result = {
        "params": {
            "dihedral_deg": round(float(args.dihedral), 3),
            "cg_x": round(float(args.cg), 3),
            "speed": round(float(args.speed), 3),
            "alt": round(float(args.alt), 3),
            "autolevel": args.autolevel,
        },
        "backend": backend.name,
        "reason": summary.get("reason", "ok"),
        "glide_time_s": round(summary["time"], 2),
        "distance_m": round(summary["dist"], 1),
        "alt_start": round(summary["alt_start"], 1),
        "alt_end": round(summary["alt_end"], 1),
        "mean_sink_mps": round(summary["sink"], 3),
        "mean_speed_mps": round(summary["speed"], 2),
        "glide_ratio": round(summary["glide_ratio"], 2),
        "steps": int(tele["steps"]),
        "files": files,
    }

    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
