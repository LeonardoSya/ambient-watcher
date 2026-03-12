"""
Ambient Watcher - 主观察循环
7×24小时运行的AI环境感知系统
"""
import time
import threading
import logging
import signal
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

from .config import load_config
from .camera import Camera
from .microphone import Microphone
from .vision import VisionAnalyzer
from .hearing import HearingAnalyzer
from .memory import Memory, Observation
from .analyzer import Analyzer
from .notifier import Notifier
from .learner import Learner

logger = logging.getLogger(__name__)

class AmbientWatcher:
    """
    环境感知主类

    功能:
    - 持续观察视觉环境
    - 持续监听声音
    - 存储短期记忆
    - 分析并理解观察内容
    - 响应查询
    """

    def __init__(self, config_path: str = None):
        # 加载配置
        self.config = load_config(config_path)

        # 数据目录
        data_dir = self.config.get('memory', {}).get('data_dir', 'data')

        # 初始化组件
        self.camera = None
        self.microphone = None
        self.vision = VisionAnalyzer(self.config.get('vision', {}))
        self.hearing = HearingAnalyzer(self.config.get('hearing', {}))
        self.memory = Memory(self.config.get('memory', {}))
        self.notifier = Notifier(self.config.get('notifier', {}))
        self.learner = Learner(
            config=self.config.get('learner', {}),
            data_dir=data_dir,
        )
        self.analyzer = Analyzer(
            config=self.config.get('analyzer', {}),
            memory=self.memory,
            notifier=self.notifier,
            learner=self.learner,
        )
        # 状态
        self.running = False
        self.state = "idle"  # idle, watching, analyzing
        self.last_vision = None
        self.last_vision_bytes = None
        self.last_audio_description = None
        self.volume_history = []
        self._volume_lock = threading.Lock()

        # VLM timing — avoid double-calls between change-trigger and continuous loop
        self.last_vlm_time = 0.0
        self.continuous_vision_interval = self.config.get(
            'watcher', {}
        ).get('continuous_vision_interval', 120)

        # 线程
        self.vision_thread = None
        self.hearing_thread = None
        self.analysis_thread = None
        self.anomaly_thread = None
        self.continuous_vision_thread = None

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 时区
        self.tz = timezone(timedelta(hours=8))

    def _signal_handler(self, signum, frame):
        """处理退出信号"""
        logger.info("收到退出信号，正在关闭...")
        self.stop()
        sys.exit(0)

    def start(self):
        """启动观察"""
        if self.running:
            logger.warning("已经在运行中")
            return

        logger.info("=" * 50)
        logger.info("🌊 Ambient Watcher 启动")
        logger.info("=" * 50)

        self.running = True
        self.state = "watching"

        # 启动视觉观察线程
        if self.config.get('vision', {}).get('enabled', True):
            self.vision_thread = threading.Thread(target=self._vision_loop, daemon=True)
            self.vision_thread.start()
            logger.info("📷 视觉观察已启动")

        # 启动听觉观察线程
        if self.config.get('hearing', {}).get('enabled', True):
            self.hearing_thread = threading.Thread(target=self._hearing_loop, daemon=True)
            self.hearing_thread.start()
            logger.info("🎤 听觉观察已启动")

        # 启动分析线程
        self.analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.analysis_thread.start()
        logger.info("🧠 分析引擎已启动")

        # 启动异常检测线程
        self.anomaly_thread = threading.Thread(target=self._anomaly_check_loop, daemon=True)
        self.anomaly_thread.start()
        logger.info("🔍 异常检测已启动")

        # 启动连续视觉观察线程
        if self.config.get('vision', {}).get('enabled', True):
            self.continuous_vision_thread = threading.Thread(
                target=self._continuous_vision_loop, daemon=True
            )
            self.continuous_vision_thread.start()
            logger.info(f"🔄 连续视觉观察已启动（每 {self.continuous_vision_interval}s）")

        logger.info("✨ 开始观察世界...")

        self.notifier.notify('info', 'Ambient Watcher', '系统已启动，开始观察环境')

    def stop(self):
        """停止观察"""
        if not self.running:
            return

        self.running = False
        self.state = "idle"

        if self.camera:
            self.camera.close()
        if self.microphone:
            self.microphone.close()

        logger.info("🛑 Ambient Watcher 已停止")

    def _vision_loop(self):
        """视觉观察循环"""
        interval = self.config.get('vision', {}).get('capture_interval', 5)

        self.camera = Camera(self.config.get('vision', {}))
        if not self.camera.open():
            logger.error("无法打开摄像头，视觉观察失败")
            return

        while self.running:
            try:
                # 捕获图像
                image_bytes = self.camera.capture_bytes()

                if image_bytes:
                    # 检测变化
                    if self.last_vision_bytes:
                        change_score = self.vision.detect_changes(self.last_vision_bytes, image_bytes)

                        # 如果有显著变化，进行分析
                        if change_score > 0.15:  # 15% 差异阈值
                            logger.info(f"📸 检测到画面变化: {change_score:.1%}")
                            self._analyze_vision(image_bytes, importance=3)

                    self.last_vision_bytes = image_bytes

                time.sleep(interval)

            except Exception as e:
                logger.error(f"视觉循环错误: {e}")
                time.sleep(5)

    def _analyze_vision(self, image_bytes: bytes, importance: int = 1):
        """分析视觉内容"""
        try:
            # 分析图像
            result = self.vision.analyze(image_bytes)

            if result and result.get('success'):
                description = result.get('description', '')

                # Track VLM timing
                if result.get('source') == 'vlm':
                    self.last_vlm_time = time.time()

                # 存储到记忆
                self.memory.add(
                    modality='vision',
                    content=description,
                    importance=importance,
                    tags=['observation', 'visual']
                )

                # Feed learner baseline
                self.learner.update_baseline(description)

                # Record activity level based on vision
                activity = "active" if any(
                    kw in description for kw in ['人', '检测到', '移动']
                ) else "normal"
                self.learner.record_activity(level=activity)

                # 更新状态
                self.last_vision = description

                logger.info(f"👀 {description[:100]}")

                return description

        except Exception as e:
            logger.error(f"视觉分析错误: {e}")

        return None

    def _hearing_loop(self):
        """听觉观察循环"""
        try:
            self.microphone = Microphone(self.config.get('hearing', {}))
            
            # 设置回调
            def audio_callback(audio_data, volume, is_speech):
                try:
                    # 记录音量 (thread-safe)
                    with self._volume_lock:
                        self.volume_history.append(volume)
                        # 只保留最近30个
                        if len(self.volume_history) > 30:
                            self.volume_history = self.volume_history[-30:]
                    
                    # 调试：打印音量
                    if volume > 0.003:
                        logger.debug(f"🔊 音量: {volume:.4f}, 阈值: {self.microphone.silence_threshold}")
                    
                    # 如果有显著声响
                    if volume > 0.003:  # 大幅降低阈值
                        description = self.hearing.describe_ambient(volume)
                        importance = 3 if volume > 0.05 else 1
                        self.memory.add(
                            modality='hearing',
                            content=description,
                            importance=importance,
                            tags=['observation', 'audio', 'anomaly' if volume > 0.05 else 'normal']
                        )
                        self.last_audio_description = description

                        # Record activity level from audio
                        if volume > 0.15:
                            self.learner.record_activity(level="loud")
                        elif volume > 0.003:
                            self.learner.record_activity(level="normal")

                        if volume > 0.01:
                            logger.info(f"👂 {description} (音量: {volume:.3f})")
                    
                except Exception as e:
                    logger.error(f"音频回调错误: {e}")
            
            self.microphone.set_callback(audio_callback)
            
            if not self.microphone.open():
                logger.warning("⚠️ 无法打开麦克风，听觉观察跳过")
                return
            
            # 开始监听
            self.microphone.start()
            
            # 保持线程活跃
            while self.running:
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"🎤 听觉循环异常: {e}")

    def _continuous_vision_loop(self):
        """
        Continuous vision loop — periodic VLM analysis regardless of change.

        Problem solved: Without this, sitting still = no AI vision because the
        change threshold (>15%) is never triggered. This ensures VLM runs at
        least every `continuous_vision_interval` seconds.

        Skips if a change-triggered VLM call happened recently.
        """
        interval = self.continuous_vision_interval

        # Wait for camera to be ready
        time.sleep(10)

        while self.running:
            time.sleep(interval)
            if not self.running:
                break

            try:
                # Skip if VLM was already called recently
                since_last_vlm = time.time() - self.last_vlm_time
                if since_last_vlm < interval * 0.5:
                    logger.debug(
                        f"🔄 Skipping continuous VLM — last call {since_last_vlm:.0f}s ago"
                    )
                    continue

                # Force VLM analysis of current frame
                if self.last_vision_bytes:
                    logger.info("🔄 连续观察: 定时VLM分析")
                    self._analyze_vision(self.last_vision_bytes, importance=2)

            except Exception as e:
                logger.error(f"连续视觉观察错误: {e}")

    def _analysis_loop(self):
        """分析循环 - 定时综合分析 + 状态报告"""
        interval = self.config.get('watcher', {}).get('analysis_interval', 30)

        while self.running:
            time.sleep(interval)

            if not self.running:
                break

            # 进行综合分析
            self._periodic_analysis()

    def _anomaly_check_loop(self):
        """异常检测循环 - 快速扫描"""
        interval = self.config.get('watcher', {}).get('anomaly_check_interval', 10)

        while self.running:
            time.sleep(interval)

            if not self.running:
                break

            try:
                # Check audio anomalies (thread-safe snapshot)
                with self._volume_lock:
                    vol_snapshot = list(self.volume_history)
                if len(vol_snapshot) > 5:
                    audio_result = self.analyzer.analyze_audio_anomaly(vol_snapshot)
                    if audio_result.get('has_anomaly'):
                        self.analyzer.send_alert([audio_result])

                # Check recent observations for anomalies
                recent = self.memory.get_recent(minutes=2)
                if recent:
                    anomalies = self.analyzer.detect_anomalies(recent)
                    if anomalies:
                        self.analyzer.send_alert(anomalies)

            except Exception as e:
                logger.error(f"异常检测错误: {e}")

    def _periodic_analysis(self):
        """周期性分析 - 多模态融合 + 状态报告"""
        try:
            # Build fused context from vision + audio
            vision_desc = self.last_vision or ""
            audio_desc = self.last_audio_description or ""
            volume = self.volume_history[-1] if self.volume_history else 0.0

            fused = self.analyzer.fuse_observations(vision_desc, audio_desc, volume)

            # Store fused observation
            if fused and fused != "暂无观察数据":
                self.memory.add(
                    modality='vision',
                    content=f"[融合分析] {fused[:200]}",
                    importance=2,
                    tags=['fused', 'multimodal'],
                )

            # Generate status report via analyzer (now learner-aware)
            report = self.analyzer.generate_status_report()
            logger.info(f"📊 状态报告: {report[:200]}")

            # Store report as observation
            self.memory.add(
                modality='vision',
                content=f"[状态报告] {report[:200]}",
                importance=1,
                tags=['status', 'report'],
            )

            # Check for volume anomalies (legacy, kept for logging)
            with self._volume_lock:
                vol_snapshot = list(self.volume_history)
            if len(vol_snapshot) > 5:
                anomaly = self.hearing.analyze_volume_change(vol_snapshot)
                if anomaly and anomaly.get('has_anomaly'):
                    logger.warning(f"⚠️ {anomaly.get('description')}")

        except Exception as e:
            logger.error(f"周期性分析错误: {e}")

    # ==================== 公共接口 ====================

    def get_status(self) -> dict:
        """获取状态"""
        stats = self.memory.get_stats()
        return {
            'running': self.running,
            'state': self.state,
            'memory': stats,
            'last_vision': self.last_vision[:100] if self.last_vision else None,
            'last_volume': self.volume_history[-1] if self.volume_history else 0,
            'entities': len(self.learner.get_entities()),
            'continuous_vision_interval': self.continuous_vision_interval,
        }

    def query(self, question: str) -> str:
        """回答问题 (uses AI analyzer when available)"""
        return self.analyzer.answer_query(question)

    def describe_now(self) -> str:
        """描述当前状态"""
        return self.memory.describe_current_state()

    def get_memory_summary(self) -> str:
        """获取记忆摘要"""
        return self.memory.get_summary()


# 全局实例
_watcher: AmbientWatcher = None

def get_watcher(config_path: str = None) -> AmbientWatcher:
    """获取全局观察者实例"""
    global _watcher
    if _watcher is None:
        _watcher = AmbientWatcher(config_path)
    return _watcher

def start_watching(config_path: str = None):
    """便捷启动函数"""
    watcher = get_watcher(config_path)
    watcher.start()
    return watcher

def stop_watching():
    """便捷停止函数"""
    global _watcher
    if _watcher:
        _watcher.stop()
        _watcher = None
