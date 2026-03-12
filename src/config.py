"""
Ambient Watcher 配置
"""
import copy
import json
import os
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"
DEFAULT_CONFIG = CONFIG_DIR / "default.json"

DEFAULT_SETTINGS = {
    "vision": {
        "enabled": True,
        "capture_interval": 5,  # 秒
        "device_name": "0",     # avfoundation 设备编号
        "width": 1920,
        "height": 1080,
        "framerate": 30,
        "jpeg_quality": 5,      # ffmpeg mjpeg q, 2-31, lower=better
        "save_snapshots": False,
    },
    "hearing": {
        "enabled": True,
        "sample_rate": 44100,
        "chunk_duration": 1,  # 秒
        "silence_threshold": 0.01,
    },
    "memory": {
        "duration_minutes": 15,
        "max_events": 1000,
    },
    "watcher": {
        "log_level": "INFO",
        "analysis_interval": 30,  # 综合分析间隔（秒）
        "anomaly_check_interval": 10,  # 异常检查间隔（秒）
        "continuous_vision_interval": 120,  # 连续视觉观察间隔（秒）
    },
    "analyzer": {
        "anomaly_cooldown": 60,  # 警报冷却（秒）
        "scene_change_threshold": 0.3,
        "volume_spike_threshold": 0.1,
    },
    "notifier": {
        "macos_notification": True,
        "sound_on_alert": True,
        "min_interval": 5,
    },
    "learner": {
        "baseline_window": 50,  # 基线滑动窗口大小
        "novelty_threshold": 0.5,  # 新颖度阈值 (0-1)
    },
}

def load_config(config_path: str = None) -> dict:
    """加载配置"""
    if config_path is None:
        config_path = DEFAULT_CONFIG

    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, 'r') as f:
            user_config = json.load(f)
        # 合并配置
        config = copy.deepcopy(DEFAULT_SETTINGS)
        for key, value in user_config.items():
            if key in config and isinstance(config[key], dict):
                config[key].update(value)
            else:
                config[key] = value
        return config

    return copy.deepcopy(DEFAULT_SETTINGS)

def save_config(config: dict, config_path: str = None):
    """保存配置"""
    if config_path is None:
        config_path = DEFAULT_CONFIG
    
    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
