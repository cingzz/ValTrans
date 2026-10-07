# -*- coding: utf-8 -*-
# 作者: cing  ·  https://github.com/cingzz
# 许可: GPL-3.0 + 商业授权（闭源/商用需向作者申请授权），见 LICENSE 与 LICENSE-COMMERCIAL.md
#
"""音频采集：虚拟声卡线路(CABLE Output) 或 整机输出 loopback。

统一输出 16kHz 单声道 float32 块，经回调推给 VAD。
- cable 模式：sounddevice 直接录制 CABLE Output（输入设备）。
- loopback 模式：pyaudiowpatch 对选定输出设备做 WASAPI loopback。
"""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np
import sounddevice as sd
import soxr

TARGET_SR = 16000


def find_device(name_part: str, is_input: bool) -> int | None:
    """按名称子串找 WASAPI 设备索引；找不到返回 None。"""
    for i, d in enumerate(sd.query_devices()):
        if name_part.lower() not in d["name"].lower():
            continue
        host = sd.query_hostapis(d["hostapi"])["name"]
        if "WASAPI" not in host:
            continue
        if is_input and d["max_input_channels"] > 0:
            return i
        if not is_input and d["max_output_channels"] > 0:
            return i
    return None


def find_cable_devices() -> tuple[int | None, int | None]:
    """返回 (CABLE Input 输出设备, CABLE Output 输入设备)。"""
    return find_device("CABLE Input", False), find_device("CABLE Output", True)


class AudioCapture:
    """持续采集 -> 16k 单声道 float32 -> on_block 回调（audio 线程内调用）。

    monitor_relay=True 时（cable 模式），把采集到的原始声音同步回放到系统默认
    输出设备（软件级"侦听"），用户无需在 Windows 声音面板手动设置侦听。
    """

    def __init__(self, on_block: Callable[[np.ndarray], None],
                 mode: str = "cable",
                 cable_name: str = "", loopback_name: str = "",
                 monitor_relay: bool = False):
        self.on_block = on_block
        self.mode = mode
        self.cable_name = cable_name
        self.loopback_name = loopback_name
        self.monitor_relay = monitor_relay
        self._stream = None
        self._relay = None
        self._pa_loop = None          # pyaudiowpatch 循环
        self._thread = None
        self._running = threading.Event()
        self.device_desc = ""

    # ---------- 公共 ----------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        if self.mode == "cable":
            self._start_cable()
        else:
            self._start_loopback()

    def stop(self) -> None:
        self._running.clear()
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._relay is not None:
            try:
                self._relay.stop(); self._relay.close()
            except Exception:
                pass
            self._relay = None
        if self._pa_loop is not None:
            try:
                self._pa_loop.stop_stream(); self._pa_loop.close()
            except Exception:
                pass
            self._pa_loop = None
        pa = getattr(self, "_pa", None)
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass
            self._pa = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ---------- cable 模式 ----------
    def _start_cable(self) -> None:
        dev = find_device(self.cable_name or "CABLE Output", True)
        if dev is None:
            raise RuntimeError("未找到 CABLE Output 设备，请先安装 VB-CABLE 或切换 loopback 模式")
        info = sd.query_devices(dev)
        self.device_desc = f"{info['name']} (WASAPI)"
        sr = int(info["default_samplerate"]) or 48000
        channels = min(2, int(info["max_input_channels"]))

        def callback(indata, frames, t, status):
            if self._relay is not None:
                try:
                    self._relay.write(indata.copy())
                except Exception:
                    pass
            mono = indata.mean(axis=1)
            out = soxr.resample(mono, sr, TARGET_SR).astype(np.float32)
            if self._running.is_set() and len(out):
                self.on_block(out)

        self._stream = sd.InputStream(
            samplerate=sr, channels=channels, dtype="float32",
            device=dev, blocksize=480, callback=callback)
        self._stream.start()
        # 软件级监听回放：CABLE -> 默认输出设备（耳机），无需手动设 Windows 侦听
        if self.monitor_relay:
            try:
                self._relay = sd.OutputStream(
                    samplerate=sr, channels=channels, dtype="float32",
                    blocksize=480)
                self._relay.start()
            except Exception:
                self._relay = None  # 无可用输出设备时静默降级

    # ---------- loopback 模式 ----------
    def _start_loopback(self) -> None:
        import pyaudiowpatch as pw

        pa = pw.PyAudio()
        self._pa = pa
        wasapi = pa.get_host_api_info_by_type(pw.paWASAPI)
        default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        target = default_out
        if self.loopback_name:
            for d in pa.get_loopback_device_info_generator():
                if self.loopback_name.lower() in d["name"].lower():
                    target = d
                    break
        else:
            target = pa.get_device_info_by_index(default_out["index"])
            if not target.get("isLoopbackDevice"):
                for loopback in pa.get_loopback_device_info_generator():
                    if target["name"] in loopback["name"]:
                        target = loopback
                        break
        self.device_desc = f"{target['name']} (loopback)"
        sr = int(target["defaultSampleRate"])
        channels = int(target["maxInputChannels"])

        def cb(in_data, frame_count, time_info, status):
            raw = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
            mono = raw.reshape(-1, channels).mean(axis=1)
            out = soxr.resample(mono, sr, TARGET_SR).astype(np.float32)
            if self._running.is_set() and len(out):
                self.on_block(out)
            return (None, pw.paContinue)

        self._pa_loop = pa.open(
            format=pw.paInt16, channels=channels, rate=sr,
            input=True, input_device_index=target["index"],
            frames_per_buffer=960, stream_callback=cb)
        self._pa_loop.start_stream()   # pyaudio 的 Stream 只有 start_stream()，没有 .start()
