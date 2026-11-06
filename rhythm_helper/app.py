from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import mss
import numpy as np

from . import PRODUCT_NAME
from .binding_manager import BindingManager
from .engine import Action, Engine
from .hotkeys import GlobalHotkeys
from .keybinds import display as key_label
from .notice import ensure_accepted
from .readiness import WindowReadiness
from .settings import DEFAULTS, geometry, load_config, save_config
from .status import StatusDisplay, beep
from .vision import Detector, Observation
from .windows_io import (
    KeyboardOutput,
    WindowUnavailableError,
    activate_window,
    enable_dpi_awareness,
    find_game_windows,
    foreground_client_rect,
    foreground_window,
    is_elevated,
    is_numlock_on,
    key_is_down,
    window_elevation,
)

PROJECT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)


def draw_observation(frame, detector: Detector, observation: Observation):
    canvas = frame.copy()
    line = round(detector.hit_y)
    cv2.line(canvas, (0, line), (canvas.shape[1] - 1, line), (0, 220, 0), 2)
    for lane, x in enumerate(detector.lane_x):
        x = round(x)
        cv2.line(canvas, (x, 0), (x, canvas.shape[0] - 1), (120, 120, 120), 1)
        label = "ASDJKL"[lane] + (" TAIL" if observation.tail_present[lane] else "")
        cv2.putText(canvas, label, (x - 25, line + 30), 0, 0.6, (0, 255, 0), 2)
    for head in observation.heads:
        center = (round(detector.lane_x[head.lane]), round(head.y))
        color = {"tap": (0, 220, 255), "hold": (255, 70, 210), "end": (255, 220, 0)}[head.kind]
        cv2.circle(canvas, center, round(48 * detector.scale), color, 2)
        cv2.putText(canvas, head.kind, (center[0] + 30, center[1]), 0, 0.6, color, 2)
    return canvas


def read_image(path: Path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")
    return image


def inspect_image(path: Path, output: Path | None, settings: dict) -> None:
    frame = read_image(path)
    detector = Detector(*geometry(settings, frame.shape[1], frame.shape[0]))
    observation = detector.detect(frame)
    print(
        json.dumps(
            {
                "heads": [
                    {"key": settings["keys"][h.lane], "type": h.kind, "y": round(h.y, 2)}
                    for h in observation.heads
                ],
                "tail_present": dict(zip(settings["keys"], observation.tail_present, strict=True)),
                "hold_support": dict(
                    zip(settings["keys"], observation.hold_support or [0.0] * 6, strict=True)
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2.imencode(".png", draw_observation(frame, detector, observation))
        if not ok:
            raise RuntimeError("标注图片编码失败。")
        encoded.tofile(output)
        print(f"标注已保存：{output}")


def calibrate_frame(
    frame, settings: dict, path: Path, *, controls=None, demo=False, screen_rect=None, gui=None
) -> bool:
    from .calibration_ui import choose_calibration

    height, width = frame.shape[:2]

    def save_points(points):
        (x1, y1), (x2, y2) = points
        if demo:
            xs, line, scale = geometry(DEFAULTS, width, height)
            for name, (x, y), target in zip(("A", "L"), points, (xs[0], xs[-1]), strict=True):
                if math.hypot(x - target, y - line) > 18 * scale:
                    return f"请点击“重选”，再点 {name} 字上方白圆的中心。"
        if x2 - x1 < width * 0.2 or abs(y1 - y2) > height * 0.035:
            return "请重新选择同一条判定线上的两个圆心，先点最左边，再点最右边。"
        candidate = dict(settings)
        candidate["lane_x"] = [(x1 + (x2 - x1) * i / 5) / width for i in range(6)]
        candidate["hit_y"] = (y1 + y2) / 2 / height
        try:
            save_config(path, candidate)
        except ValueError as error:
            return f"请重新选择圆心：{error}"
        except OSError as error:
            return f"保存失败：{error}"
        settings.update(candidate)
        message = f"已保存{'教程' if demo else '游戏'}校准：{path}"
        if gui:
            gui.publish("log", message)
        else:
            print(message, flush=True)
        return None

    if gui:
        return gui.open_picker(
            lambda modal_controls, parent: choose_calibration(
                frame,
                settings,
                save_points,
                controls=modal_controls,
                demo=demo,
                screen_rect=screen_rect,
                parent=parent,
            ),
            controls,
        )
    return choose_calibration(
        frame, settings, save_points, controls=controls, demo=demo, screen_rect=screen_rect
    )


def calibrate(capture, rect, settings: dict, path: Path, controls=None, gui=None) -> bool:
    left, top, width, height = rect
    frame = np.asarray(capture.grab({"left": left, "top": top, "width": width, "height": height}))[
        :, :, :3
    ].copy()
    return calibrate_frame(frame, settings, path, controls=controls, screen_rect=rect, gui=gui)


def practice_calibration(config_path: Path, controls=None, gui=None) -> bool:
    from .calibration_demo import demo_frame

    practice_path = config_path.with_name("calibration-practice.json")
    return calibrate_frame(
        demo_frame(), dict(DEFAULTS), practice_path, controls=controls, demo=True, gui=gui
    )


def runtime(settings: dict, path: Path, *, dry_run: bool, gui=None) -> None:
    def log(message, *, flush=False, file=None):
        if gui:
            gui.publish("log", message)
        else:
            print(message, flush=flush, file=file)

    enable_dpi_awareness()
    cv2.setNumThreads(1)
    output = None if dry_run else KeyboardOutput()
    display = None
    try:
        display = StatusDisplay()
    except (OSError, RuntimeError) as error:
        log(f"状态条不可用：{error}；请查看运行日志。", flush=True)
    active = False
    pending = None
    pending_since = 0.0
    last_window_trace = None
    target = 0
    target_name = ""
    rect = None
    engine = None
    detector = None
    region = None
    controls = BindingManager(settings, path, GlobalHotkeys)
    toggle = key_label(controls.bindings["toggle"])
    calibration = key_label(controls.bindings["calibrate"])
    if display:
        display.toggle_label = toggle
    readiness = WindowReadiness()
    control_count = 0
    pressed_at: dict[str, tuple[float, str]] = {}
    helper_elevated = None
    try:
        helper_elevated = is_elevated()
    except OSError:
        pass
    permission = {True: "管理员", False: "普通权限", None: "权限未知"}[helper_elevated]
    mode = "仅识别，不发键" if dry_run else "实际按键"
    log(f"{PRODUCT_NAME} v0.9 · {mode} · {permission} · 初始停止", flush=True)
    log(f"{toggle} 开始/停止，{calibration} 游戏校准。可在主窗口修改快捷键。")
    log("绿色状态条表示正在演奏，灰色表示已停止。", flush=True)

    def report(state: str, detail: str, *, sound: bool = True) -> None:
        nonlocal display
        labels = {
            "idle": "未启动",
            "waiting": "等待原神",
            "running": "运行中",
            "paused": "已停止",
            "error": "错误",
        }
        log(f"[{labels[state]}] {detail}", flush=True)
        if gui:
            gui.publish("status", (state, detail))
        if display and (not gui or target):
            try:
                display.update(state, detail, rect)
            except (OSError, RuntimeError) as error:
                log(f"状态条更新失败：{error}", flush=True)
                display.close()
                display = None
        if sound:
            beep(state)

    def stop() -> None:
        nonlocal active, pending
        active, pending = False, None
        readiness.reset()
        if engine:
            engine.stop()
        if output:
            output.release_all()
        pressed_at.clear()

    def select_game():
        games = find_game_windows()
        if not games:
            return None
        foreground = foreground_window()
        for candidate in games:
            if candidate.hwnd == foreground:
                return candidate
        for candidate in games:
            if candidate.hwnd == target:
                return candidate
        if len(games) == 1:
            return games[0]
        raise ValueError(f"找到多个原神窗口，请切到要操作的游戏后再按{toggle}。")

    def request(action: str) -> None:
        nonlocal target, target_name, pending, pending_since, last_window_trace
        stop()
        if action == "start" and controls.service is None:
            raise ValueError("快捷键尚未注册。请打开“快捷键设置”选择可用的按键。")
        candidate = None if action == "tutorial" else select_game()
        if candidate is None:
            if action not in ("calibrate", "tutorial"):
                raise ValueError("未找到原神窗口，请先启动原神并进入游戏。")
            report("paused", "已打开校准练习。可用 Alt+Tab 切到校准窗口。", sound=False)
            saved = (
                practice_calibration(path, controls, gui=gui)
                if gui
                else practice_calibration(path, controls)
            )
            report(
                "paused",
                f"练习已保存；进入原神后按 {calibration} 正式校准。" if saved else "已取消练习。",
            )
            return
        target = candidate.hwnd
        target_name = candidate.title or "原神"
        game_elevated = window_elevation(target)
        game_permission = {True: "管理员", False: "普通权限", None: "权限未知"}[game_elevated]
        log(f"[权限] 助手：{permission}；原神：{game_permission}；窗口 0x{target:X}", flush=True)
        if action == "start" and game_elevated is True and helper_elevated is False and not dry_run:
            raise ValueError("原神以管理员身份运行，请以管理员身份打开助手。")
        pending, pending_since = action, time.perf_counter()
        last_window_trace = None
        if foreground_window() != target:
            activate_window(target)
        instruction = "开始识别" if action == "start" else "打开校准"
        report("waiting", f"已找到 {target_name}；切回游戏后自动{instruction}。")

    press_count = 0

    def emit(actions: list[Action]) -> None:
        nonlocal press_count
        for action in actions:
            if output:
                if action.down:
                    if foreground_window() != target:
                        raise RuntimeError("原神失去焦点，已停止输入。")
                    if gui:
                        if not gui.press(output, action.key):
                            break
                    else:
                        output.press(action.key)
                else:
                    output.release(action.key)
            if action.down:
                press_count += 1
                pressed_at[action.key] = (time.perf_counter(), action.reason)
                if action.reason == "hold":
                    report("running", f"正在长按 {action.key.upper()}，等待长条终点。", sound=False)
                log(f"按下 {action.key.upper()} ({action.reason})", flush=True)
            else:
                began, kind = pressed_at.pop(action.key, (time.perf_counter(), ""))
                duration = max(0, time.perf_counter() - began)
                log(
                    f"松开 {action.key.upper()} ({action.reason}，持续 {duration:.3f} 秒)",
                    flush=True,
                )
                if kind == "hold":
                    report(
                        "running",
                        f"长按 {action.key.upper()} 已松开，持续 {duration:.2f} 秒。",
                        sound=False,
                    )

    now = time.perf_counter()
    diagnostic = logging.getLogger("rhythm.diagnostic")
    diagnostic.setLevel(logging.INFO)
    diagnostic.propagate = False
    diagnostic_handler = None
    try:
        log_dir = path.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        diagnostic_handler = RotatingFileHandler(
            log_dir / "rhythm.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
        diagnostic.addHandler(diagnostic_handler)
        diagnostic.info("%s v0.9 · %s", PRODUCT_NAME, time.strftime("%Y-%m-%d %H:%M:%S"))
        log(f"诊断日志：{log_dir / 'rhythm.log'}", flush=True)
    except OSError as error:
        log(f"诊断日志不可用：{error}", flush=True)
    last_diagnostic = now
    last_status = last_idle_status = last_note = now
    frame_count = seen_frames = slow_frames = 0
    report("idle", f"点击开始，或在游戏中按 {toggle}。", sound=False)
    try:
        try:
            controls.start()
            log(f"[热键] {toggle} / {calibration} 全局注册成功。", flush=True)
        except RuntimeError as error:
            if not gui:
                raise
            report("error", f"{error} 可在“快捷键设置”更换。")
        with mss.mss() as capture:
            while True:
                if gui and gui.closing:
                    break
                started = time.perf_counter()
                if display:
                    display.pump()
                try:
                    commands = controls.poll()
                    if gui:
                        commands = gui.route(commands, controls.bindings)
                        if "stop" in commands:
                            commands = [
                                cmd
                                for cmd in commands
                                if isinstance(cmd, tuple)
                                or cmd in ("stop", "edit_begin", "edit_end")
                            ]
                except RuntimeError as error:
                    stop()
                    report("error", str(error))
                    controls.close()
                    if gui:
                        continue
                    raise
                try:
                    # Preserve every physical press; MOD_NOREPEAT already filters auto-repeat.
                    # Handle the whole batch before arming, so two queued toggles cancel safely.
                    for command in commands:
                        if command == "edit_begin":
                            stop()
                            report("paused", "正在设置快捷键。", sound=False)
                        elif command == "edit_end":
                            state = "paused" if controls.service else "error"
                            detail = (
                                f"按 {toggle} 开始演奏。"
                                if controls.service
                                else "请先在快捷键设置中注册可用的按键。"
                            )
                            report(state, detail, sound=False)
                        elif isinstance(command, tuple):
                            stop()
                            try:
                                controls.apply(command[1])
                            except (OSError, RuntimeError, ValueError) as error:
                                gui.publish("hotkeys", (False, str(error), dict(controls.bindings)))
                                report("error", str(error), sound=False)
                            else:
                                toggle = key_label(controls.bindings["toggle"])
                                calibration = key_label(controls.bindings["calibrate"])
                                if display:
                                    display.toggle_label = toggle
                                detail = f"已保存。{toggle} 启停，{calibration} 游戏校准。"
                                gui.publish("hotkeys", (True, detail, dict(controls.bindings)))
                                report("paused", detail, sound=False)
                        elif command == "toggle":
                            control_count += 1
                            log(f"[热键] 已收到{toggle}，第 {control_count} 次。", flush=True)
                            if active or pending:
                                stop()
                                report("paused", f"全部按键已松开；{toggle} 再次开始。")
                            else:
                                request("start")
                        elif command == "stop":
                            stop()
                            report("paused", "已停止，全部按键已松开。")
                        elif command == "start":
                            if not (active or pending):
                                request("start")
                        elif command in ("calibrate", "tutorial"):
                            request(command)
                    if pending:
                        if started - pending_since > 60:
                            stop()
                            report("paused", f"等待游戏超时；切回原神后再按{toggle}。")
                        elif foreground_window() != target:
                            readiness.reset()
                            trace = ("foreground", foreground_window())
                            if trace != last_window_trace:
                                last_window_trace = trace
                                log(
                                    f"[窗口] 等待前台：目标=0x{target:X}，当前=0x{trace[1]:X}",
                                    flush=True,
                                )
                        else:
                            try:
                                candidate_rect = foreground_client_rect(target)
                            except WindowUnavailableError:
                                candidate_rect = None
                            trace = ("rect", candidate_rect)
                            if trace != last_window_trace:
                                last_window_trace = trace
                                log(
                                    f"[窗口] 目标=0x{target:X}，客户区={candidate_rect}", flush=True
                                )
                                report(
                                    "waiting", "原神恢复中，等待画面稳定后自动开始。", sound=False
                                )
                            if not readiness.observe(target, candidate_rect, started):
                                # Fullscreen restore may momentarily report foreground + iconic.
                                # Keep the user's start request while waiting for a stable frame.
                                time.sleep(0.015)
                                continue
                            # Verify this HWND still belongs to Genshin after a focus transition.
                            if not any(game.hwnd == target for game in find_game_windows()):
                                raise ValueError("原神窗口已关闭或变化，请重新开始。")
                            left, top, width, height = candidate_rect
                            rect = candidate_rect
                            action, pending = pending, None
                            if action == "calibrate":
                                report(
                                    "paused",
                                    f"按 Alt+Tab 可切到「{PRODUCT_NAME} · 校准」窗口。",
                                    sound=False,
                                )
                                saved = calibrate(capture, rect, settings, path, controls, gui=gui)
                                controls.poll()  # Discard commands queued during calibration close.
                                report(
                                    "paused",
                                    f"校准已保存；{toggle} 开始。" if saved else "校准已取消。",
                                )
                            else:
                                if any(key_is_down(ord(k.upper())) for k in settings["keys"]):
                                    raise ValueError(f"请先松开六个轨道按键，再按{toggle}。")
                                xs, hit_y, scale = geometry(settings, width, height)
                                crop_top = max(0, int(hit_y - 500 * scale))
                                crop_bottom = min(height, int(hit_y + 80 * scale))
                                detector = Detector(xs, hit_y - crop_top, scale)
                                engine = Engine(
                                    hit_y - crop_top,
                                    scale=scale,
                                    keys=tuple(settings["keys"]),
                                    lead_ms=settings["input_lead_ms"],
                                    tap_ms=settings["tap_ms"],
                                    release_grace_ms=settings["release_grace_ms"],
                                    max_hold_seconds=settings["max_hold_seconds"],
                                )
                                region = {
                                    "left": left,
                                    "top": top + crop_top,
                                    "width": width,
                                    "height": crop_bottom - crop_top,
                                }
                                active = True
                                frame_count = seen_frames = slow_frames = press_count = 0
                                last_status = last_note = time.perf_counter()
                                report(
                                    "running", f"已绑定 {target_name} · {width}x{height} · {mode}"
                                )
                    if active:
                        if foreground_window() != target:
                            stop()
                            report("paused", f"已切出原神，全部按键已松开；{toggle} 继续。")
                        elif foreground_client_rect(target) != rect:
                            stop()
                            report("paused", f"游戏位置或尺寸改变；{toggle} 重新绑定。")
                        else:
                            capture_started = time.perf_counter()
                            frame = np.asarray(capture.grab(region))[:, :, :3]
                            observed_at = (capture_started + time.perf_counter()) / 2
                            observation = detector.detect(frame)
                            if observation.heads:
                                last_note = observed_at
                                seen_frames += 1
                            action_at = time.perf_counter()
                            actions = engine.step(observation, observed_at, action_at=action_at)
                            emit(actions)
                            if diagnostic_handler and (
                                actions or action_at - last_diagnostic >= 0.1
                            ):
                                diagnostic.info(
                                    json.dumps(
                                        {
                                            "t": round(action_at, 4),
                                            "latency_ms": round(
                                                (action_at - observed_at) * 1000, 2
                                            ),
                                            "heads": [
                                                (h.lane, h.kind, round(h.y, 1))
                                                for h in observation.heads
                                            ],
                                            "tail": observation.tail_present,
                                            "support": observation.hold_support,
                                            "actions": [(a.key, a.down, a.reason) for a in actions],
                                            "held": {
                                                lane: {
                                                    "kind": s.kind,
                                                    "end_at": s.end_at,
                                                    "speed": s.speed,
                                                    "not_before": s.not_before,
                                                }
                                                for lane, s in engine.pressed.items()
                                            },
                                        }
                                    )
                                )
                                last_diagnostic = action_at
                            frame_count += 1
                            elapsed = time.perf_counter() - started
                            slow_frames = slow_frames + 1 if elapsed > 0.12 else 0
                            if slow_frames >= 3:
                                raise RuntimeError("截图持续过慢，请降低游戏分辨率。")
                            if observed_at - last_status >= 1:
                                fps = frame_count / (observed_at - last_status)
                                counter = "模拟" if dry_run else "发键"
                                detail = (
                                    f"{fps:.0f} FPS | 音符帧 {seen_frames} | "
                                    f"{counter} {press_count} 次"
                                )
                                holds = [
                                    f"{key.upper()} {observed_at - began:.1f}s"
                                    for key, (began, kind) in pressed_at.items()
                                    if kind == "hold"
                                ]
                                if holds:
                                    detail = f"{fps:.0f} FPS | 长按 " + ", ".join(holds)
                                if not holds and observed_at - last_note >= 5:
                                    detail = (
                                        f"{fps:.0f} FPS | 未见音符：进入演奏或 {calibration} 校准"
                                    )
                                if float(frame.mean()) < 3:
                                    detail = "画面偏黑：请切换无边框窗口模式"
                                report("running", detail, sound=False)
                                last_status, frame_count, seen_frames = observed_at, 0, 0
                    elif not pending and started - last_idle_status >= 5:
                        needs_numlock = any("NumPad" in key for key in controls.bindings.values())
                        if controls.service and needs_numlock and not is_numlock_on():
                            report(
                                "idle",
                                "数字小键盘快捷键需要开启 Num Lock；也可在快捷键设置中更换。",
                                sound=False,
                            )
                        last_idle_status = started
                except WindowUnavailableError:
                    # Active gameplay must stop immediately on a minimize/focus race.
                    stop()
                    report("paused", f"原神正在切换窗口，已松开按键；{toggle}继续。")
                except (
                    OSError,
                    ValueError,
                    RuntimeError,
                    cv2.error,
                    mss.exception.ScreenShotError,
                ) as error:
                    stop()
                    report("error", str(error))
                interval = 1 / settings["target_fps"] if active else 0.015
                time.sleep(max(0, interval - (time.perf_counter() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        for attempt in range(3):
            try:
                stop()
                break
            except OSError as error:
                if attempt == 2:
                    log(f"松键失败：{error}；请手动按下并松开 A/S/D/J/K/L。", file=sys.stderr)
                time.sleep(0.02)
        try:
            if controls:
                controls.close()
        finally:
            if display:
                display.close()
            log("已退出。", flush=True)
            if diagnostic_handler:
                diagnostic.removeHandler(diagnostic_handler)
                diagnostic_handler.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{PRODUCT_NAME}（Windows 六轨音符识别与按键）")
    parser.add_argument("--config", type=Path, default=PROJECT / "config.json")
    parser.add_argument("--dry-run", action="store_true", help="只识别并打印动作，不发送按键")
    parser.add_argument("--inspect", type=Path, help="离线分析一张游戏截图")
    parser.add_argument("--output", type=Path, help="离线标注结果 PNG 路径")
    parser.add_argument("--calibration-demo", action="store_true", help="用示例画面练习校准")
    args = parser.parse_args()
    try:
        interactive = args.inspect is None or args.calibration_demo
        if not ensure_accepted(interactive=interactive):
            if not interactive:
                print(
                    "请先打开助手主窗口并点击使用声明中的“我接受”，再运行 --inspect。",
                    file=sys.stderr,
                )
                return 1
            return 0
        if args.calibration_demo:
            enable_dpi_awareness()
            practice_calibration(args.config)
            return 0
        settings = load_config(args.config)
        if args.inspect:
            inspect_image(args.inspect, args.output, settings)
        else:
            from .main_ui import run_ui

            enable_dpi_awareness()
            run_ui(settings, args.config, dry_run=args.dry_run)
    except (OSError, ValueError, RuntimeError, cv2.error, mss.exception.ScreenShotError) as error:
        if args.inspect and sys.stderr is not None:
            print(f"错误：{error}", file=sys.stderr)
            return 1
        raise
    return 0
