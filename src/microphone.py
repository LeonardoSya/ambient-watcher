"""
麦克风控制 - 捕获环境声音
改进版：使用轮询而非回调，更加可靠
"""
import pyaudio
import numpy as np
import logging
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class Microphone:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.audio = None
        self.stream = None
        self.sample_rate = self.config.get('sample_rate', 44100)
        self.chunk_duration = self.config.get('chunk_duration', 0.5)
        self.chunk_size = int(self.sample_rate * self.chunk_duration)
        self.silence_threshold = self.config.get('silence_threshold', 0.002)
        self.device_keyword = self.config.get('device_keyword', 'MacBook')
        self.callback: Optional[Callable] = None

        # 轮询模式
        self._running = False
        self._thread = None
    
    def open(self) -> bool:
        """打开麦克风"""
        try:
            self.audio = pyaudio.PyAudio()
            
            # 先测试哪个设备可用
            device_index = self._find_input_device()
            if device_index is None:
                logger.error("没有找到可用的麦克风设备")
                return False
            
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size
            )
            
            logger.info(f"麦克风已打开: {self.sample_rate}Hz, 设备: {device_index}")
            return True
        except Exception as e:
            logger.error(f"打开麦克风失败: {e}")
            return False
    
    def _find_input_device(self) -> Optional[int]:
        """查找可用的麦克风设备（只选匹配 device_keyword 的本机设备）"""
        keyword = self.device_keyword.lower()
        blocked_keywords = ['iphone', 'ipad']

        try:
            # 第一轮：找匹配 keyword 的设备
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] <= 0:
                    continue
                name_lower = info['name'].lower()

                # 跳过被封锁的设备
                if any(blocked in name_lower for blocked in blocked_keywords):
                    logger.debug(f"跳过设备: {info['name']} (blocked)")
                    continue

                if keyword in name_lower:
                    # 使用设备的原生采样率
                    native_rate = int(info['defaultSampleRate'])
                    if native_rate != self.sample_rate:
                        logger.info(f"调整采样率: {self.sample_rate} -> {native_rate} (设备原生)")
                        self.sample_rate = native_rate
                        self.chunk_size = int(self.sample_rate * self.chunk_duration)
                    logger.info(f"选择麦克风: {info['name']} ({native_rate}Hz)")
                    return i

            # 第二轮：找任何非 iPhone/iPad 的设备
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] <= 0:
                    continue
                name_lower = info['name'].lower()
                if any(blocked in name_lower for blocked in blocked_keywords):
                    continue

                native_rate = int(info['defaultSampleRate'])
                if native_rate != self.sample_rate:
                    self.sample_rate = native_rate
                    self.chunk_size = int(self.sample_rate * self.chunk_duration)
                logger.info(f"使用麦克风: {info['name']} ({native_rate}Hz)")
                return i

        except Exception as e:
            logger.error(f"查找设备失败: {e}")
        return None
    
    def start(self):
        """开始监听"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("🎤 麦克风监听已开始")
    
    def stop(self):
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("🎤 麦克风监听已停止")
    
    def _poll_loop(self):
        """轮询监听循环"""
        while self._running:
            try:
                if not self.stream or not self.stream.is_active():
                    time.sleep(0.5)
                    continue
                
                # 读取音频数据
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                # 转换为numpy数组
                audio_data = np.frombuffer(data, dtype=np.int16)
                # 归一化到 [-1, 1]
                audio_float = audio_data.astype(np.float32) / 32768.0
                
                # 计算音量
                volume = np.abs(audio_float).mean()
                
                # 检测是否非静音
                is_speech = volume > self.silence_threshold
                
                # 如果有显著声音，调用回调
                if self.callback and is_speech:
                    self.callback(audio_data, volume, is_speech)
                
            except Exception as e:
                logger.error(f"麦克风读取错误: {e}")
                time.sleep(1)
    
    def set_callback(self, callback: Callable):
        """设置音频回调"""
        self.callback = callback
    
    def close(self):
        """关闭麦克风"""
        self.stop()
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio:
            self.audio.terminate()
        self.stream = None
        self.audio = None
        logger.info("麦克风已关闭")
    
    def get_volume(self) -> float:
        """获取当前音量"""
        if not self.stream or not self.stream.is_active():
            return 0.0
        
        try:
            data = self.stream.read(self.chunk_size, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            audio_float = audio_data.astype(np.float32) / 32768.0
            return float(np.abs(audio_float).mean())
        except Exception:
            return 0.0
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def list_microphones() -> list:
    """列出可用麦克风（排除 iPhone/iPad）"""
    audio = pyaudio.PyAudio()
    blocked_keywords = ['iphone', 'ipad']
    devices = []
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            name_lower = info['name'].lower()
            if any(b in name_lower for b in blocked_keywords):
                continue
            devices.append({'index': i, 'name': info['name']})
    audio.terminate()
    return devices
