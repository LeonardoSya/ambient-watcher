"""
摄像头控制 - ffmpeg 捕获 + AVFoundation 硬件控制

架构:
- ffmpeg (avfoundation): 负责图像数据流捕获
- MacCameraControl (AVFoundation native): 负责硬件参数（zoom, Center Stage）

启动时自动：
1. 关闭 Center Stage（防止系统自动裁切放大）
2. 设置 videoZoomFactor = 1.0（最广角）
3. 然后用 ffmpeg 正常拍照
"""
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

# 尝试导入硬件控制（可选依赖）
try:
    from .mac_camera_control import MacCameraControl
    HAS_NATIVE_CONTROL = True
except ImportError:
    HAS_NATIVE_CONTROL = False
    logger.info("MacCameraControl 不可用，跳过硬件级缩放控制")


class Camera:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.device_name = self.config.get('device_name', '0')
        self.width = self.config.get('width', 1920)
        self.height = self.config.get('height', 1080)
        self.framerate = self.config.get('framerate', 30)
        self.jpeg_quality = self.config.get('jpeg_quality', 5)
        self._opened = False
        self._hw_control = None  # MacCameraControl 实例

    def open(self) -> bool:
        """验证摄像头可用，并初始化硬件控制（最广角 + 关闭 Center Stage）"""
        try:
            result = subprocess.run(
                [FFMPEG_BIN, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True, timeout=5
            )
            device_output = result.stderr
            if "AVFoundation video devices" not in device_output:
                logger.error("ffmpeg 未检测到 avfoundation 设备")
                return False

            self._opened = True
            logger.info(f"摄像头就绪: 设备={self.device_name}, {self.width}x{self.height}")

            # 硬件级控制：设置最广角 + 关闭 Center Stage
            self._init_hardware_control()

            return True
        except FileNotFoundError:
            logger.error(f"ffmpeg 未找到: {FFMPEG_BIN}")
            return False
        except Exception as e:
            logger.error(f"摄像头检查失败: {e}")
            return False

    def _init_hardware_control(self):
        """初始化 AVFoundation 硬件控制"""
        if not HAS_NATIVE_CONTROL:
            return

        try:
            self._hw_control = MacCameraControl(self.config)
            if self._hw_control.open():
                # 关闭 Center Stage（防止自动裁切放大）
                if self._hw_control.is_center_stage_enabled():
                    self._hw_control.enable_center_stage(False)
                    logger.info("已关闭 Center Stage")

                # 设置最广角
                self._hw_control.set_widest_fov()
                zoom = self._hw_control.get_zoom()
                logger.info(f"已设置最广角: zoom={zoom}")
            else:
                logger.warning("MacCameraControl 打开失败，跳过硬件控制")
                self._hw_control = None
        except Exception as e:
            logger.warning(f"硬件控制初始化失败: {e}")
            self._hw_control = None

    def set_zoom(self, factor: float) -> bool:
        """设置缩放（需要 MacCameraControl）"""
        if self._hw_control:
            return self._hw_control.set_zoom(factor)
        logger.warning("硬件控制不可用，无法设置缩放")
        return False

    def get_zoom_info(self) -> dict:
        """获取缩放信息"""
        if self._hw_control:
            return {
                'current': self._hw_control.get_zoom(),
                'min': self._hw_control.get_min_zoom(),
                'max': self._hw_control.get_max_zoom(),
            }
        return {'current': 1.0, 'min': 1.0, 'max': 1.0}

    def close(self):
        """关闭摄像头"""
        self._opened = False
        if self._hw_control:
            self._hw_control.close()
            self._hw_control = None
        logger.info("摄像头已关闭")

    def capture_bytes(self) -> Optional[bytes]:
        """捕获一帧并返回 JPEG 字节"""
        if not self._opened:
            return None

        try:
            # 使用 pipe 输出 JPEG，避免临时文件
            cmd = [
                FFMPEG_BIN,
                "-f", "avfoundation",
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", str(self.framerate),
                "-i", str(self.device_name),
                "-frames:v", "1",
                "-q:v", str(self.jpeg_quality),
                "-f", "image2",
                "-vcodec", "mjpeg",
                "pipe:1"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0 and len(result.stdout) > 0:
                return result.stdout

            # 有时 ffmpeg 返回非零但 stdout 仍有数据
            if len(result.stdout) > 1000:
                return result.stdout

            logger.error(f"ffmpeg 拍照失败: {result.stderr.decode('utf-8', errors='replace')[-200:]}")
            return None

        except subprocess.TimeoutExpired:
            logger.error("ffmpeg 拍照超时")
            return None
        except Exception as e:
            logger.error(f"捕获失败: {e}")
            return None

    def capture_frame(self):
        """捕获一帧并返回 numpy 数组（BGR 格式，兼容 OpenCV）"""
        image_bytes = self.capture_bytes()
        if image_bytes is None:
            return None

        try:
            import cv2
            import numpy as np
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            logger.error(f"帧解码失败: {e}")
            return None

    def save_snapshot(self, path: str) -> bool:
        """保存快照到文件"""
        if not self._opened:
            return False

        try:
            cmd = [
                FFMPEG_BIN,
                "-f", "avfoundation",
                "-video_size", f"{self.width}x{self.height}",
                "-framerate", str(self.framerate),
                "-i", str(self.device_name),
                "-frames:v", "1",
                "-update", "1",
                "-q:v", str(self.jpeg_quality),
                "-y", str(path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )

            if Path(path).exists() and Path(path).stat().st_size > 0:
                return True

            logger.error(f"保存快照失败: {result.stderr.decode('utf-8', errors='replace')[-200:]}")
            return False

        except Exception as e:
            logger.error(f"保存快照失败: {e}")
            return False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def list_cameras() -> list:
    """列出可用摄像头（通过 ffmpeg avfoundation）"""
    try:
        result = subprocess.run(
            [FFMPEG_BIN, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5
        )

        devices = []
        in_video = False
        for line in result.stderr.splitlines():
            if "AVFoundation video devices" in line:
                in_video = True
                continue
            if "AVFoundation audio devices" in line:
                break
            if in_video and "[" in line:
                # 提取设备编号和名称
                parts = line.split("]")
                if len(parts) >= 2:
                    idx_part = parts[-2].split("[")[-1].strip()
                    name = parts[-1].strip()
                    try:
                        devices.append({
                            'index': int(idx_part),
                            'name': name
                        })
                    except ValueError:
                        pass

        return devices

    except Exception as e:
        logger.error(f"列出摄像头失败: {e}")
        return []
