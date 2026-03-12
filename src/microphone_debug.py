"""
麦克风控制 - 调试版
"""
import pyaudio
import numpy as np
import logging
import threading
import time
import wave
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class Microphone:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.audio = None
        self.stream = None
        self.sample_rate = self.config.get('sample_rate', 16000)
        self.chunk_duration = self.config.get('chunk_duration', 0.5)
        self.chunk_size = int(self.sample_rate * self.chunk_duration)
        self.silence_threshold = self.config.get('silence_threshold', 0.002)
        self.callback: Optional[Callable] = None
        
        self._running = False
        self._thread = None
        
        # 调试
        self.debug = True
    
    def open(self) -> bool:
        """打开麦克风"""
        try:
            self.audio = pyaudio.PyAudio()
            
            # 查找设备
            device_index = self._find_input_device()
            if device_index is None:
                logger.error("没有找到可用的麦克风设备")
                return False
            
            # 获取设备信息
            device_info = self.audio.get_device_info_by_index(device_index)
            logger.info(f"麦克风设备: {device_info['name']}")
            
            # 打开流 - 使用更小的chunk
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=int(self.sample_rate),
                input=True,
                input_device_index=device_index,
                frames_per_buffer=1024,  # 更小的buffer
                start=True
            )
            
            logger.info(f"✅ 麦克风已打开: {self.sample_rate}Hz")
            return True
        except Exception as e:
            logger.error(f"打开麦克风失败: {e}")
            return False
    
    def _find_input_device(self) -> Optional[int]:
        """查找可用的麦克风设备"""
        try:
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    logger.info(f"发现输入设备 {i}: {info['name']}")
                    if 'macbook' in info['name'].lower():
                        return i
            # 返回第一个
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
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
        logger.info("🎤 监听线程已启动")
    
    def stop(self):
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("🎤 监听已停止")
    
    def _poll_loop(self):
        """轮询监听循环"""
        logger.info("🎤 开始轮询...")
        
        consecutive_errors = 0
        
        while self._running:
            try:
                if not self.stream or not self.stream.is_active():
                    logger.warning("流不活跃，等待...")
                    time.sleep(1)
                    continue
                
                # 读取数据
                try:
                    data = self.stream.read(1024, exception_on_overflow=False)
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    if consecutive_errors < 5:
                        logger.warning(f"读取错误 ({consecutive_errors}): {e}")
                    time.sleep(0.5)
                    continue
                
                # 转换为numpy
                audio_data = np.frombuffer(data, dtype=np.int16)
                audio_float = audio_data.astype(np.float32) / 32768.0
                
                # 计算音量
                volume = float(np.abs(audio_float).mean())
                
                # 调试输出
                if self.debug and volume > 0.001:
                    logger.info(f"🔊 音量: {volume:.5f} (阈值: {self.silence_threshold})")
                
                # 调用回调
                if self.callback and volume > self.silence_threshold:
                    try:
                        self.callback(audio_data, volume, True)
                    except Exception as e:
                        logger.error(f"回调错误: {e}")
                
            except Exception as e:
                logger.error(f"轮询错误: {e}")
                time.sleep(1)
        
        logger.info("🎤 轮询结束")
    
    def set_callback(self, callback: Callable):
        """设置回调"""
        self.callback = callback
    
    def close(self):
        """关闭"""
        self.stop()
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass
        self.stream = None
        self.audio = None
        logger.info("🔇 麦克风已关闭")


def list_microphones():
    """列出设备"""
    audio = pyaudio.PyAudio()
    devices = []
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            devices.append({'index': i, 'name': info['name']})
    audio.terminate()
    return devices


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("🎤 麦克风调试工具")
    print("=" * 40)
    
    # 列出设备
    devices = list_microphones()
    print(f"可用设备: {devices}")
    
    # 创建并测试
    mic = Microphone({'silence_threshold': 0.001})
    mic.debug = True
    
    def callback(data, vol, is_speech):
        print(f"   >>> 回调触发! 音量: {vol:.5f}")
    
    mic.set_callback(callback)
    
    if mic.open():
        print("麦克风已打开，开始监听...")
        mic.start()
        
        # 监听30秒
        for i in range(30):
            time.sleep(1)
            print(f"秒数: {i+1}")
        
        mic.close()
    else:
        print("无法打开麦克风")
