"""
听觉理解 - 分析声音内容
"""
import base64
import json
import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

class HearingAnalyzer:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.api_key = self.config.get('api_key', None)
        self.sample_rate = self.config.get('sample_rate', 16000)
    
    def transcribe(self, audio_data: bytes) -> Optional[dict]:
        """
        语音转文字
        
        Args:
            audio_data: WAV音频字节
        
        Returns:
            转写结果
        """
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            
            # 准备音频数据
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            payload = {
                "model": "speech-01-turbo",
                "task": "transcribe",
                "language": "zh",
                "audio": f"data:audio/wav;base64,{audio_base64}"
            }
            
            response = requests.post(
                "https://api.minimax.chat/v1/audio/transcriptions",
                headers=headers,
                files={"file": ("audio.wav", audio_data, "audio/wav")},
                data={"model": "speech-01-turbo", "language": "zh"},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'text': result.get('text', ''),
                    'raw': result
                }
            else:
                logger.error(f"语音API错误: {response.status_code}")
                return None
                
        except ImportError:
            logger.warning("requests库未安装")
            return None
        except Exception as e:
            logger.error(f"语音转写失败: {e}")
            return None
    
    def detect_sound_type(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        检测声音类型
        
        Returns:
            声音类型: "silence", "speech", "noise", "unknown"
        """
        # 归一化
        audio_float = audio_data.astype(np.float32) / 32768.0
        
        # 计算特征
        volume = np.abs(audio_float).mean()
        
        # 简单的音量判断
        if volume < 0.01:
            return "silence"
        elif volume > 0.3:
            return "loud"
        else:
            return "ambient"
    
    def analyze_volume_change(self, volumes: list) -> Optional[dict]:
        """
        分析音量变化模式
        
        Args:
            volumes: 音量历史列表
        
        Returns:
            分析结果
        """
        if len(volumes) < 3:
            return None
        
        volumes = np.array(volumes)
        
        # 检测是否有显著变化
        mean_vol = volumes.mean()
        std_vol = volumes.std()
        
        # 检测峰值
        peaks = []
        for i, vol in enumerate(volumes):
            if vol > mean_vol + 2 * std_vol:
                peaks.append(i)
        
        if len(peaks) > 0:
            return {
                'has_anomaly': True,
                'type': 'sudden_loud',
                'peak_indices': peaks,
                'description': f"检测到{len(peaks)}次异常响动"
            }
        
        return {
            'has_anomaly': False,
            'type': 'normal',
            'description': '环境音正常'
        }
    
    def describe_ambient(self, volume: float) -> str:
        """
        描述当前环境声音
        
        Args:
            volume: 当前音量 (0-1)
        
        Returns:
            描述文本
        """
        if volume < 0.01:
            return "非常安静"
        elif volume < 0.05:
            return "安静"
        elif volume < 0.15:
            return "有轻微声响"
        elif volume < 0.3:
            return "有正常对话或活动声"
        else:
            return "声音较大"


# 便捷函数
def detect_anomaly(volumes: list) -> Optional[dict]:
    """检测音量异常"""
    analyzer = HearingAnalyzer()
    return analyzer.analyze_volume_change(volumes)
