"""
Mac 摄像头原生控制 - 通过 AVFoundation 控制硬件级缩放和 Center Stage

这个模块独立于 ffmpeg 捕获流程，专门负责硬件参数控制：
- videoZoomFactor: 控制视野宽窄（1.0 = 最广角）
- Center Stage: Apple 人物追踪居中功能
- 格式选择: 选择最佳传感器格式

与 camera.py 配合使用：camera.py 负责图像数据流（ffmpeg），
本模块负责硬件参数设置（AVFoundation）。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import AVFoundation as AVF
    import CoreMedia
    HAS_AVFOUNDATION = True
except ImportError:
    HAS_AVFOUNDATION = False
    logger.warning("pyobjc-framework-AVFoundation 未安装，硬件控制不可用")


class MacCameraControl:
    """
    Mac 摄像头硬件控制

    通过 AVFoundation API 直接控制摄像头硬件参数，
    与 ffmpeg 捕获流程并行工作。

    使用方式:
        ctrl = MacCameraControl()
        ctrl.open()                    # 获取设备引用
        ctrl.set_zoom(1.0)            # 最广角
        ctrl.enable_center_stage(False) # 关闭 Center Stage 防止自动裁切
        # ... ffmpeg 正常拍照 ...
        ctrl.close()
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.device = None
        self._device_name_filter = self.config.get('device_keyword', 'MacBook')
        self._blocked_keywords = ['iphone', 'ipad']

    def open(self, device_uid: str = None) -> bool:
        """
        获取摄像头设备引用

        Args:
            device_uid: 指定设备 UID，默认自动选择
        """
        if not HAS_AVFOUNDATION:
            logger.error("AVFoundation 不可用")
            return False

        try:
            if device_uid:
                self.device = AVF.AVCaptureDevice.deviceWithUniqueID_(device_uid)
            else:
                self.device = self._find_device()

            if self.device is None:
                logger.error("未找到可用摄像头")
                return False

            logger.info(f"摄像头控制已连接: {self.device.localizedName()}")
            return True

        except Exception as e:
            logger.error(f"打开摄像头控制失败: {e}")
            return False

    def close(self):
        """释放设备引用"""
        self.device = None

    def _find_device(self):
        """查找本机摄像头（排除 iPhone/iPad）"""
        devices = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
        keyword = self._device_name_filter.lower()

        # 优先匹配关键词
        for d in devices:
            name = d.localizedName().lower()
            if any(b in name for b in self._blocked_keywords):
                continue
            if keyword in name:
                return d

        # 回退：第一个非 iPhone 设备
        for d in devices:
            name = d.localizedName().lower()
            if any(b in name for b in self._blocked_keywords):
                continue
            return d

        return None

    # ==================== 缩放控制 ====================

    def get_zoom(self) -> float:
        """获取当前缩放因子"""
        if not self.device:
            return 1.0
        return float(self.device.videoZoomFactor())

    def get_min_zoom(self) -> float:
        """获取最小缩放（最广角）"""
        if not self.device:
            return 1.0
        return float(self.device.minAvailableVideoZoomFactor())

    def get_max_zoom(self) -> float:
        """获取最大缩放"""
        if not self.device:
            return 1.0
        return float(self.device.maxAvailableVideoZoomFactor())

    def set_zoom(self, factor: float) -> bool:
        """
        设置缩放因子

        Args:
            factor: 缩放值，1.0 = 最广角，越大越放大

        Returns:
            是否成功
        """
        if not self.device:
            logger.error("设备未打开")
            return False

        min_z = self.get_min_zoom()
        max_z = self.get_max_zoom()
        factor = max(min_z, min(factor, max_z))

        try:
            ok, err = self.device.lockForConfiguration_(None)
            if not ok:
                logger.error(f"无法锁定设备配置: {err}")
                return False

            self.device.setVideoZoomFactor_(factor)
            self.device.unlockForConfiguration()
            logger.info(f"缩放已设置: {factor:.1f} (范围 {min_z:.1f}-{max_z:.1f})")
            return True

        except Exception as e:
            logger.error(f"设置缩放失败: {e}")
            return False

    def set_widest_fov(self) -> bool:
        """设置为最广角视野"""
        return self.set_zoom(self.get_min_zoom())

    # ==================== Center Stage ====================

    def is_center_stage_supported(self) -> bool:
        """检查是否支持 Center Stage"""
        if not HAS_AVFOUNDATION:
            return False

        if not self.device:
            return False

        try:
            fmt = self.device.activeFormat()
            if fmt and hasattr(fmt, 'isCenterStageSupported'):
                return bool(fmt.isCenterStageSupported())
        except Exception:
            pass

        return False

    def is_center_stage_enabled(self) -> bool:
        """检查 Center Stage 是否开启"""
        if not HAS_AVFOUNDATION:
            return False

        try:
            return bool(AVF.AVCaptureDevice.isCenterStageEnabled())
        except Exception:
            return False

    def enable_center_stage(self, enabled: bool) -> bool:
        """
        启用/禁用 Center Stage

        注意: Center Stage 开启后系统会自动调整 zoom，
        可能覆盖手动设置的 videoZoomFactor。
        对于 Ambient Watcher，建议关闭以保持最广角。

        Args:
            enabled: True=开启, False=关闭
        """
        if not HAS_AVFOUNDATION:
            return False

        if not self.is_center_stage_supported():
            logger.warning("当前设备/格式不支持 Center Stage")
            return False

        try:
            # 设置控制模式为应用级别
            AVF.AVCaptureDevice.setCenterStageControlMode_(
                AVF.AVCaptureCenterStageControlModeCooperative
            )
            AVF.AVCaptureDevice.setCenterStageEnabled_(enabled)
            status = "开启" if enabled else "关闭"
            logger.info(f"Center Stage 已{status}")
            return True

        except Exception as e:
            logger.error(f"设置 Center Stage 失败: {e}")
            return False

    # ==================== 格式控制 ====================

    def get_formats(self) -> list:
        """获取所有支持的视频格式"""
        if not self.device:
            return []

        result = []
        for fmt in self.device.formats():
            desc = fmt.formatDescription()
            dims = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
            result.append({
                'width': dims.width,
                'height': dims.height,
                'max_zoom': float(fmt.videoMaxZoomFactor()),
                'center_stage': bool(fmt.isCenterStageSupported()) if hasattr(fmt, 'isCenterStageSupported') else False,
                'format_obj': fmt,
            })
        return result

    def set_format_by_resolution(self, width: int, height: int) -> bool:
        """
        选择指定分辨率的传感器格式

        Args:
            width: 目标宽度
            height: 目标高度
        """
        if not self.device:
            return False

        for fmt_info in self.get_formats():
            if fmt_info['width'] == width and fmt_info['height'] == height:
                try:
                    ok, err = self.device.lockForConfiguration_(None)
                    if not ok:
                        logger.error(f"无法锁定配置: {err}")
                        return False

                    self.device.setActiveFormat_(fmt_info['format_obj'])
                    self.device.unlockForConfiguration()
                    logger.info(f"格式已设置: {width}x{height}")
                    return True

                except Exception as e:
                    logger.error(f"设置格式失败: {e}")
                    return False

        logger.warning(f"未找到格式: {width}x{height}")
        return False

    # ==================== 状态查询 ====================

    def get_status(self) -> dict:
        """获取当前设备完整状态"""
        if not self.device:
            return {'connected': False}

        fmt = self.device.activeFormat()
        dims = None
        if fmt:
            desc = fmt.formatDescription()
            d = CoreMedia.CMVideoFormatDescriptionGetDimensions(desc)
            dims = {'width': d.width, 'height': d.height}

        return {
            'connected': True,
            'name': self.device.localizedName(),
            'uid': self.device.uniqueID(),
            'zoom': float(self.device.videoZoomFactor()),
            'min_zoom': float(self.device.minAvailableVideoZoomFactor()),
            'max_zoom': float(self.device.maxAvailableVideoZoomFactor()),
            'center_stage_supported': self.is_center_stage_supported(),
            'center_stage_enabled': self.is_center_stage_enabled(),
            'active_format': dims,
            'formats_count': len(self.device.formats()),
        }

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# 便捷函数
# ============================================================

def set_widest_fov(device_keyword: str = 'MacBook') -> bool:
    """一键设置最广角（关闭 Center Stage + zoom=1.0）"""
    ctrl = MacCameraControl({'device_keyword': device_keyword})
    if not ctrl.open():
        return False

    ctrl.enable_center_stage(False)
    result = ctrl.set_widest_fov()
    ctrl.close()
    return result


def list_devices() -> list:
    """列出可用的 Mac 摄像头（排除 iPhone）"""
    if not HAS_AVFOUNDATION:
        return []

    devices = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
    result = []
    for d in devices:
        name = d.localizedName()
        if 'iphone' in name.lower() or 'ipad' in name.lower():
            continue
        result.append({
            'name': name,
            'uid': d.uniqueID(),
            'zoom_range': (
                float(d.minAvailableVideoZoomFactor()),
                float(d.maxAvailableVideoZoomFactor())
            ),
        })
    return result
