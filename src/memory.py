"""
双层记忆系统 - 日志 + 关键帧

日志 (Observations): 所有观察的完整记录，永久存储
关键帧 (Keyframes): 重要的瞬间，标记为高亮，可跨时间回顾
"""
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
import threading
import os

logger = logging.getLogger(__name__)

@dataclass
class Observation:
    """观察事件"""
    timestamp: str  # ISO格式
    modality: str   # "vision" 或 "hearing"
    content: str    # 描述内容
    raw_data: Optional[dict] = None  # 原始数据（可选）
    importance: int = 1  # 重要性 1-5
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Observation':
        return cls(**data)


@dataclass
class Keyframe:
    """关键帧 - 重要时刻的永久记录"""
    id: str
    timestamp: str
    modality: str   # "vision" / "hearing" / "event"
    title: str      # 简短标题
    description: str # 详细描述
    tags: List[str] = None
    auto: bool = False  # 是否自动标记
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Keyframe':
        return cls(**data)


class Memory:
    """
    双层记忆系统
    
    Layer 1: 日志 (Observations)
    - 所有观察记录，按时间顺序存储
    - 可查询任意时间段
    - 持久化到 JSON 文件
    
    Layer 2: 关键帧 (Keyframes)
    - 重要时刻的标记
    - 永久存储，跨时间回顾
    - 支持自动标记和手动标记
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        
        # 数据目录
        self.data_dir = Path(self.config.get('data_dir', 'data'))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.observations_file = self.data_dir / 'observations.json'
        self.keyframes_file = self.data_dir / 'keyframes.json'
        
        # 内存中的数据
        self.observations: List[Observation] = []
        self.keyframes: List[Keyframe] = []
        
        self._lock = threading.Lock()
        
        # 北京时区
        self.tz = timezone(timedelta(hours=8))
        
        # 自动标记阈值
        self.auto_keyframe_threshold = self.config.get('auto_keyframe_threshold', 4)
        
        # 加载已有数据
        self._load()
    
    def _load(self):
        """从文件加载数据"""
        # 加载日志
        if self.observations_file.exists():
            try:
                with open(self.observations_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.observations = [Observation.from_dict(o) for o in data]
                logger.info(f"已加载 {len(self.observations)} 条观察记录")
            except Exception as e:
                logger.error(f"加载观察记录失败: {e}")
        
        # 加载关键帧
        if self.keyframes_file.exists():
            try:
                with open(self.keyframes_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.keyframes = [Keyframe.from_dict(k) for k in data]
                logger.info(f"已加载 {len(self.keyframes)} 个关键帧")
            except Exception as e:
                logger.error(f"加载关键帧失败: {e}")
    
    def _save_observations(self):
        """保存日志到文件"""
        try:
            with open(self.observations_file, 'w', encoding='utf-8') as f:
                json.dump([o.to_dict() for o in self.observations], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存观察记录失败: {e}")
    
    def _save_keyframes(self):
        """保存关键帧到文件"""
        try:
            with open(self.keyframes_file, 'w', encoding='utf-8') as f:
                json.dump([k.to_dict() for k in self.keyframes], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存关键帧失败: {e}")
    
    # ==================== 日志 (Observations) ====================
    
    def add(self, modality: str, content: str, importance: int = 1, tags: List[str] = None, raw_data: dict = None, auto_keyframe: bool = True):
        """
        添加观察记录
        
        Args:
            modality: "vision" 或 "hearing"
            content: 描述内容
            importance: 重要性 1-5
            tags: 标签
            raw_data: 原始数据
            auto_keyframe: 是否自动检查并标记关键帧
        """
        with self._lock:
            now = datetime.now(self.tz)
            observation = Observation(
                timestamp=now.isoformat(),
                modality=modality,
                content=content,
                importance=importance,
                tags=tags or [],
                raw_data=raw_data
            )
            self.observations.append(observation)
            
            # 自动标记关键帧
            if auto_keyframe and importance >= self.auto_keyframe_threshold:
                self._create_auto_keyframe(observation)
            
            # 每次都保存（实时持久化）
            self._save_observations()
            
            logger.debug(f"[日志] {modality}: {content[:50]}...")
    
    def _create_auto_keyframe(self, observation: Observation):
        """自动创建关键帧"""
        import uuid
        
        now = datetime.now(self.tz)
        
        # 生成标题
        if observation.modality == 'vision':
            # 从内容提取关键词作为标题
            words = observation.content[:30].split('，')[0].split('.')[0]
            title = f"视觉: {words}"
        else:
            title = f"听觉: {observation.content[:20]}"
        
        keyframe = Keyframe(
            id=str(uuid.uuid4())[:8],
            timestamp=observation.timestamp,
            modality=observation.modality,
            title=title,
            description=observation.content,
            tags=observation.tags + ['auto'],
            auto=True
        )
        
        self.keyframes.append(keyframe)
        logger.info(f"[关键帧] 自动标记: {title}")
        
        # 保存
        self._save_keyframes()
    
    def query(self, modality: str = None, since: datetime = None, until: datetime = None, limit: int = 50) -> List[Observation]:
        """
        查询日志
        
        Args:
            modality: 过滤类型
            since: 开始时间
            until: 结束时间
            limit: 返回数量
        
        Returns:
            观察列表
        """
        with self._lock:
            results = self.observations.copy()
        
        # 过滤
        if modality:
            results = [o for o in results if o.modality == modality]
        
        if since:
            results = [o for o in results if datetime.fromisoformat(o.timestamp) >= since]
        
        if until:
            results = [o for o in results if datetime.fromisoformat(o.timestamp) <= until]
        
        # 按时间排序（最新的在前）
        results = sorted(results, key=lambda x: x.timestamp, reverse=True)
        
        return results[:limit]
    
    def get_recent(self, minutes: int = None, modality: str = None) -> List[Observation]:
        """获取最近的观察"""
        if minutes:
            since = datetime.now(self.tz) - timedelta(minutes=minutes)
            return self.query(modality=modality, since=since, limit=100)
        else:
            return self.query(modality=modality, limit=50)
    
    # ==================== 关键帧 (Keyframes) ====================
    
    def add_keyframe(self, modality: str, title: str, description: str, tags: List[str] = None):
        """
        手动添加关键帧
        
        Args:
            modality: 类型
            title: 标题
            description: 描述
            tags: 标签
        """
        import uuid
        
        with self._lock:
            now = datetime.now(self.tz)
            keyframe = Keyframe(
                id=str(uuid.uuid4())[:8],
                timestamp=now.isoformat(),
                modality=modality,
                title=title,
                description=description,
                tags=tags or [],
                auto=False
            )
            self.keyframes.append(keyframe)
            self._save_keyframes()
            
            logger.info(f"[关键帧] 手动标记: {title}")
            return keyframe.id
    
    def get_keyframes(self, modality: str = None, tags: List[str] = None, limit: int = 20) -> List[Keyframe]:
        """获取关键帧"""
        with self._lock:
            results = self.keyframes.copy()
        
        if modality:
            results = [k for k in results if k.modality == modality]
        
        if tags:
            results = [k for k in results if any(t in k.tags for t in tags)]
        
        # 按时间排序
        results = sorted(results, key=lambda x: x.timestamp, reverse=True)
        
        return results[:limit]
    
    def search_keyframes(self, keyword: str) -> List[Keyframe]:
        """搜索关键帧"""
        keyword = keyword.lower()
        with self._lock:
            results = []
            for k in self.keyframes:
                if keyword in k.title.lower() or keyword in k.description.lower():
                    results.append(k)
            return sorted(results, key=lambda x: x.timestamp, reverse=True)
    
    # ==================== 查询接口 ====================
    
    def get_summary(self) -> str:
        """获取记忆摘要"""
        with self._lock:
            if not self.observations:
                return "我什么还没看到..."
            
            now = datetime.now(self.tz)
            
            # 统计
            vision_count = sum(1 for o in self.observations if o.modality == 'vision')
            hearing_count = sum(1 for o in self.observations if o.modality == 'hearing')
            
            # 最近的重要片段
            important = [o for o in self.observations if o.importance >= 3][:5]
            
            # 关键帧
            recent_keyframes = self.keyframes[:5]
        
        summary_parts = [
            f"📊 统计:",
            f"  👀 视觉 {vision_count} 次",
            f"  👂 听觉 {hearing_count} 次",
            f"  ⭐ 关键帧 {len(self.keyframes)} 个",
        ]
        
        if recent_keyframes:
            summary_parts.append(f"\n⭐ 最近关键帧:")
            for kf in recent_keyframes[:3]:
                time_str = datetime.fromisoformat(kf.timestamp).strftime("%m-%d %H:%M")
                summary_parts.append(f"  • [{time_str}] {kf.title}")
        
        return "\n".join(summary_parts)
    
    def describe_current_state(self) -> str:
        """描述当前状态"""
        recent = self.get_recent(minutes=5)
        
        if not recent:
            return "我还没观察到任何东西..."
        
        vision = [o for o in recent if o.modality == 'vision']
        hearing = [o for o in recent if o.modality == 'hearing']
        
        parts = []
        
        if vision:
            latest = vision[0]
            elapsed = (datetime.now(self.tz) - datetime.fromisoformat(latest.timestamp)).total_seconds()
            
            parts.append(f"👀 {latest.content[:100]}")
            if elapsed < 60:
                parts.append(f"（{int(elapsed)}秒前）")
            else:
                parts.append(f"（{int(elapsed/60)}分钟前）")
        
        if hearing:
            parts.append(f"👂 {hearing[0].content}")
        
        return "\n".join(parts) if parts else "一切平静..."
    
    def answer_question(self, question: str) -> str:
        """回答关于过去的问题"""
        q = question.lower()
        now = datetime.now(self.tz)
        
        # 分析问题类型
        if any(w in q for w in ['关键帧', '记住', '重要', 'highlight']):
            # 关于关键帧
            kfs = self.get_keyframes(limit=10)
            if kfs:
                lines = ["⭐ 关键帧记录:"]
                for kf in kfs[:5]:
                    dt = datetime.fromisoformat(kf.timestamp)
                    lines.append(f"  • {dt.strftime('%m-%d %H:%M')} - {kf.title}")
                return "\n".join(lines)
            return "还没有关键帧记录。"
        
        elif any(w in q for w in ['今天', '早上', '上午', 'today']):
            # 今天
            since = now.replace(hour=0, minute=0, second=0)
            obs = self.query(since=since, limit=20)
            if obs:
                lines = ["📝 今天的观察:"]
                for o in obs[:5]:
                    dt = datetime.fromisoformat(o.timestamp)
                    lines.append(f"  • {dt.strftime('%H:%M')} - {o.content[:60]}")
                return "\n".join(lines)
            return "今天还没有观察记录。"
        
        elif any(w in q for w in ['谁', '有人', '人', 'person']):
            # 关于人
            recent = self.get_recent(minutes=60)
            relevant = [o for o in recent if '人' in o.content or 'person' in o.content.lower()]
            if relevant:
                return f"我看到了: {relevant[0].content}"
            return "最近没有看到人。"
        
        elif any(w in q for w in ['安静', '声音', '响', '听到']):
            # 关于声音
            recent = self.get_recent(minutes=30, modality='hearing')
            if recent:
                return f"我听到: {recent[0].content}"
            return "刚才很安静。"
        
        elif any(w in q for w in ['什么', '动静', '发生']):
            # 关于发生了什么
            recent = self.get_recent(minutes=30)
            if recent:
                lines = []
                for o in recent[:5]:
                    dt = datetime.fromisoformat(o.timestamp)
                    lines.append(f"  • {dt.strftime('%H:%M')} {o.content[:60]}")
                return "📝 " + "\n".join(lines)
            return "我什么也没观察到..."
        
        # 默认返回当前状态
        return self.describe_current_state()
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            return {
                'observations': len(self.observations),
                'keyframes': len(self.keyframes),
                'vision_count': sum(1 for o in self.observations if o.modality == 'vision'),
                'hearing_count': sum(1 for o in self.observations if o.modality == 'hearing'),
            }


# 便捷函数
def create_memory(config: dict = None) -> Memory:
    """创建记忆系统"""
    return Memory(config)
