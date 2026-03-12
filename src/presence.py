"""
Presence Detection - 在场检测模块

基于多帧融合和在场分数算法，检测用户离开/返回事件
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
import json
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class PresenceEvent:
    """在场状态变化事件"""
    timestamp: str
    event_type: str  # "arrived", "left"
    confidence: float  # 置信度 0-1
    details: str

class PresenceDetector:
    """
    在场检测器
    
    算法:
    1. 统计最近N分钟内"检测到人"的比例 (presence_score)
    2. 当 score 从低变高 = 用户返回 (arrived)
    3. 当 score 从高变低 = 用户离开 (left)
    """
    
    def __init__(
        self,
        lookback_minutes: int = 15,  # 回看15分钟
        presence_threshold: float = 0.3,  # >30%检测到人=在场
        left_threshold: float = 0.1,  # <10%检测到人=离开
        cooldown_minutes: int = 10,  # 事件之间至少间隔10分钟
    ):
        self.lookback_minutes = lookback_minutes
        self.presence_threshold = presence_threshold
        self.left_threshold = left_threshold
        self.cooldown_minutes = cooldown_minutes
        
        # 状态
        self.last_event: Optional[PresenceEvent] = None
        self.last_event_time: Optional[datetime] = None
        
    def _parse_timestamp(self, ts_str: str) -> datetime:
        """解析ISO时间戳"""
        if ts_str.endswith('+08:00'):
            ts_str = ts_str[:-6]
        return datetime.fromisoformat(ts_str)
        
    def calculate_presence_score(self, observations: List[dict]) -> float:
        """
        计算在场分数
        
        Returns:
            0.0-1.0 之间的人数检测比例
        """
        if not observations:
            return 0.0
            
        # 过滤最近N分钟的观察
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self.lookback_minutes)
        
        recent_obs = []
        for obs in observations:
            try:
                obs_time = self._parse_timestamp(obs.get('timestamp', ''))
                if obs_time.tzinfo is None:
                    obs_time = obs_time.replace(tzinfo=timezone.utc)
                if obs_time >= cutoff:
                    recent_obs.append(obs)
            except:
                continue
                
        if not recent_obs:
            return 0.0
            
        # 统计"检测到人"的次数
        person_count = 0
        for obs in recent_obs:
            content = obs.get('content', '')
            # 检测关键词
            if '检测到' in content and '个人' in content and '没有' not in content:
                person_count += 1
            elif '检测到1个人' in content or '检测到2个人' in content:
                person_count += 1
                
        return person_count / len(recent_obs)
        
    def detect_event(self, observations: List[dict]) -> Optional[PresenceEvent]:
        """
        检测在场状态变化事件
        
        Returns:
            PresenceEvent 如果检测到状态变化, 否则 None
        """
        # 检查冷却时间
        if self.last_event_time:
            now = datetime.now(timezone.utc)
            if (now - self.last_event_time).total_seconds() < self.cooldown_minutes * 60:
                return None
                
        # 计算当前在场分数
        current_score = self.calculate_presence_score(observations)
        
        # 根据上一次事件判断
        if self.last_event is None:
            # 首次运行，记录初始状态
            if current_score >= self.presence_threshold:
                self.last_event = PresenceEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="initial_present",
                    confidence=current_score,
                    details=f"初始状态: 在场 (score={current_score:.2f})"
                )
            else:
                self.last_event = PresenceEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="initial_absent",
                    confidence=1 - current_score,
                    details=f"初始状态: 不在场 (score={current_score:.2f})"
                )
            self.last_event_time = datetime.now(timezone.utc)
            return None
            
        # 状态变化检测
        # 从不在场变为在场 = 返回
        if current_score >= self.presence_threshold and self.last_event.event_type in ['initial_absent', 'left']:
            event = PresenceEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="arrived",
                confidence=current_score,
                details=f"用户返回 (score={current_score:.2f})"
            )
            self.last_event = event
            self.last_event_time = datetime.now(timezone.utc)
            logger.info(f"PresenceDetector: Arrived detected (score={current_score:.2f})")
            return event
            
        # 从在场变为不在场 = 离开
        if current_score <= self.left_threshold and self.last_event.event_type in ['initial_present', 'arrived']:
            event = PresenceEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="left",
                confidence=1 - current_score,
                details=f"用户离开 (score={current_score:.2f})"
            )
            self.last_event = event
            self.last_event_time = datetime.now(timezone.utc)
            logger.info(f"PresenceDetector: Left detected (score={current_score:.2f})")
            return event
            
        return None
        
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "last_event": asdict(self.last_event) if self.last_event else None,
            "config": {
                "lookback_minutes": self.lookback_minutes,
                "presence_threshold": self.presence_threshold,
                "left_threshold": self.left_threshold,
                "cooldown_minutes": self.cooldown_minutes,
            }
        }


def load_observations(data_path: str = "data/observations.json") -> List[dict]:
    """加载观察记录"""
    path = Path(data_path)
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    
    detector = PresenceDetector(
        lookback_minutes=5,
        presence_threshold=0.3,
        left_threshold=0.1,
        cooldown_minutes=5,
    )
    
    observations = load_observations()
    print(f"Loaded {len(observations)} observations")
    
    # 计算当前分数
    score = detector.calculate_presence_score(observations)
    print(f"Current presence score: {score:.2f}")
    
    # 检测事件
    event = detector.detect_event(observations)
    if event:
        print(f"Event detected: {event.event_type} at {event.timestamp}")
        print(f"Details: {event.details}")
    
    # 状态
    print(f"\nStatus: {detector.get_status()}")
