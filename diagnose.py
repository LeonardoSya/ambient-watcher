#!/usr/bin/env python3
"""
Ambient Watcher 诊断脚本
测试摄像头和麦克风是否可正常调用（使用 ffmpeg + pyaudio）
"""
import subprocess
import shutil
import numpy as np
import os
import sys

FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def diagnose_camera():
    print("=" * 50)
    print("  Camera Diagnostics (ffmpeg avfoundation)")
    print("=" * 50)

    # 检查 ffmpeg
    if not os.path.isfile(FFMPEG_BIN):
        print(f"  [FAIL] ffmpeg not found: {FFMPEG_BIN}")
        return False

    # 列出可用设备
    try:
        result = subprocess.run(
            [FFMPEG_BIN, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5
        )
    except Exception as e:
        print(f"  [FAIL] ffmpeg error: {e}")
        return False

    devices = []
    in_video = False
    for line in result.stderr.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            break
        if in_video and "[" in line:
            parts = line.split("]")
            if len(parts) >= 2:
                idx_part = parts[-2].split("[")[-1].strip()
                name = parts[-1].strip()
                try:
                    idx = int(idx_part)
                    is_blocked = "iphone" in name.lower() or "ipad" in name.lower()
                    tag = " (BLOCKED)" if is_blocked else ""
                    devices.append({"index": idx, "name": name, "blocked": is_blocked})
                    print(f"  [{idx}] {name}{tag}")
                except ValueError:
                    pass

    if not devices:
        print("  [FAIL] No video devices found")
        return False

    # 使用第一个非 iPhone 设备测试
    test_device = None
    for d in devices:
        if not d["blocked"]:
            test_device = d
            break

    if test_device is None:
        print("  [FAIL] No usable (non-iPhone) device found")
        return False

    # 测试不同分辨率
    test_resolutions = [
        (1920, 1080, "1080p"),
        (1280, 720, "720p"),
        (640, 480, "480p"),
    ]

    print(f"\n  Testing device [{test_device['index']}] {test_device['name']}:")
    best_res = None
    for w, h, name in test_resolutions:
        cmd = [
            FFMPEG_BIN,
            "-f", "avfoundation",
            "-video_size", f"{w}x{h}",
            "-framerate", "30",
            "-i", str(test_device["index"]),
            "-frames:v", "1",
            "-f", "image2",
            "-vcodec", "mjpeg",
            "pipe:1"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=10)
            if res.returncode == 0 and len(res.stdout) > 1000:
                print(f"    {name} ({w}x{h}) -> OK ({len(res.stdout) / 1024:.0f} KB)")
                if best_res is None:
                    best_res = (w, h, res.stdout)
            else:
                print(f"    {name} ({w}x{h}) -> FAIL")
        except subprocess.TimeoutExpired:
            print(f"    {name} ({w}x{h}) -> TIMEOUT")
        except Exception as e:
            print(f"    {name} ({w}x{h}) -> ERROR: {e}")

    # 保存最佳分辨率的测试图
    if best_res:
        w, h, jpeg_data = best_res
        out_path = "data/diagnose_camera.jpg"
        with open(out_path, "wb") as f:
            f.write(jpeg_data)
        print(f"\n  [OK] Best resolution: {w}x{h}")
        print(f"  [OK] Test image saved: {out_path}")
    else:
        print("\n  [FAIL] No resolution worked")
        return False

    # 测试 AVFoundation 硬件控制
    print("\n  Hardware control (AVFoundation):")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from src.mac_camera_control import MacCameraControl
        ctrl = MacCameraControl({"device_keyword": "MacBook"})
        if ctrl.open():
            status = ctrl.get_status()
            print(f"    Device: {status.get('name', '?')}")
            print(f"    Zoom: {status.get('zoom', '?')} (range {status.get('min_zoom', '?')}-{status.get('max_zoom', '?')})")
            print(f"    Center Stage: {'ON' if status.get('center_stage_enabled') else 'OFF'}")
            print(f"    Supported: {'Yes' if status.get('center_stage_supported') else 'No'}")
            ctrl.close()
        else:
            print("    [WARN] Could not open hardware control")
    except ImportError:
        print("    [INFO] pyobjc-framework-AVFoundation not available")
    except Exception as e:
        print(f"    [WARN] Hardware control error: {e}")

    return True


def diagnose_microphone():
    print("\n" + "=" * 50)
    print("  Microphone Diagnostics (PyAudio)")
    print("=" * 50)

    try:
        import pyaudio
    except ImportError:
        print("  [FAIL] pyaudio not installed")
        return False

    audio = pyaudio.PyAudio()
    blocked_keywords = ["iphone", "ipad"]

    # 列出所有输入设备
    input_devices = []
    print("  Available input devices:")
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        if info["maxInputChannels"] <= 0:
            continue
        name_lower = info["name"].lower()
        is_blocked = any(b in name_lower for b in blocked_keywords)
        tag = " (BLOCKED)" if is_blocked else ""
        default = ""
        try:
            if i == audio.get_default_input_device_info()["index"]:
                default = " (default)"
        except Exception:
            pass
        print(f"    [{i}] {info['name']} - {info['maxInputChannels']}ch, {int(info['defaultSampleRate'])}Hz{default}{tag}")
        if not is_blocked:
            input_devices.append(info)

    if not input_devices:
        print("  [FAIL] No usable input device found")
        audio.terminate()
        return False

    # 找 MacBook 设备或第一个可用设备
    test_device = input_devices[0]
    for d in input_devices:
        if "macbook" in d["name"].lower():
            test_device = d
            break

    device_idx = int(test_device["index"])
    sample_rate = int(test_device["defaultSampleRate"])

    print(f"\n  Testing: [{device_idx}] {test_device['name']}")
    print(f"  Sample rate: {sample_rate}Hz")

    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=1024,
        )

        print("  Recording 2 seconds...")
        frames = []
        for _ in range(int(sample_rate / 1024 * 2)):
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        audio_data = np.frombuffer(b"".join(frames), dtype=np.int16)
        audio_float = audio_data.astype(np.float32) / 32768.0

        rms = float(np.sqrt(np.mean(audio_float**2)))
        peak = float(np.max(np.abs(audio_float)))

        print(f"\n  [OK] Recording succeeded!")
        print(f"  Samples: {len(audio_data)}")
        print(f"  RMS volume: {rms:.6f}")
        print(f"  Peak: {peak:.6f}")

        if rms < 0.0001:
            print("  [WARN] Volume extremely low - mic may be muted or permissions missing")
        elif rms < 0.001:
            print("  [OK] Environment is quiet")
        else:
            print("  [OK] Ambient sound detected")

        audio.terminate()
        return True

    except Exception as e:
        print(f"  [FAIL] Recording failed: {e}")
        audio.terminate()
        return False


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)

    cam_ok = diagnose_camera()
    mic_ok = diagnose_microphone()

    print("\n" + "=" * 50)
    print("  Results")
    print("=" * 50)
    print(f"  Camera:     {'OK' if cam_ok else 'FAIL'}")
    print(f"  Microphone: {'OK' if mic_ok else 'FAIL'}")
