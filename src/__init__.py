"""
Ambient Watcher - 环境感知系统
7×24小时运行的AI观察者
"""

from .watcher import AmbientWatcher, get_watcher, start_watching, stop_watching
from .memory import Memory, Observation
from .camera import Camera
from .microphone import Microphone
from .vision import VisionAnalyzer
from .hearing import HearingAnalyzer
from .config import load_config, save_config

__version__ = "0.1.0"
__all__ = [
    'AmbientWatcher',
    'get_watcher',
    'start_watching', 
    'stop_watching',
    'Memory',
    'Observation',
    'Camera',
    'Microphone',
    'VisionAnalyzer',
    'HearingAnalyzer',
    'load_config',
    'save_config',
]
