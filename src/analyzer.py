"""
Analyzer - anomaly detection + AI reasoning via MiniMax chat API.

Responsibilities:
- Detect anomalies in visual/audio observations
- Generate proactive alerts when something noteworthy happens
- Produce periodic status reports
- Answer user queries with contextual reasoning
"""
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# MiniMax API (Anthropic-compatible endpoint)
MINIMAX_API_URL = "https://api.minimaxi.com/anthropic/v1/messages"
MINIMAX_MODEL = "MiniMax-M2.5"

# System prompt for the ambient watcher AI
SYSTEM_PROMPT = """你是 Ambient Watcher 的分析引擎，一个7×24小时环境感知AI。
你的任务是分析观察数据，检测异常，并生成简洁的状态报告。

规则：
- 用中文回答
- 简洁、清晰，不要废话
- 重点关注变化和异常
- 如果没有异常，简短总结即可
- 判断异常时考虑时间上下文（深夜出现人影比白天更值得关注）"""


class Analyzer:
    """
    Core intelligence engine for Phase 2+3.

    Uses MiniMax chat API for reasoning, with local heuristic fallback
    when API is unavailable. Phase 3 adds multimodal fusion and learner
    integration for personalized, context-aware analysis.
    """

    def __init__(self, config: dict = None, memory=None, notifier=None, learner=None):
        self.config = config or {}
        self.memory = memory
        self.notifier = notifier
        self.learner = learner

        # API setup
        self.api_key = os.environ.get('MINIMAX_API_KEY') or self.config.get('api_key')
        self.api_url = self.config.get('api_url', MINIMAX_API_URL)
        self.model = self.config.get('model', MINIMAX_MODEL)

        # Anomaly detection thresholds
        self.scene_change_threshold = self.config.get('scene_change_threshold', 0.3)
        self.volume_spike_threshold = self.config.get('volume_spike_threshold', 0.1)

        # Cooldown to prevent alert spam
        self.anomaly_cooldown = self.config.get('anomaly_cooldown', 60)
        self._last_alert_time = 0.0

        # Track previous state for change detection
        self._prev_scene_description = None
        self._alert_history: List[dict] = []

    # ==================== MiniMax Chat API ====================

    def _chat(self, user_message: str, system_message: str = None) -> Optional[str]:
        """
        Call MiniMax API (Anthropic-compatible messages endpoint).

        Returns the assistant's reply text, or None on failure.
        """
        if not self.api_key:
            return None

        try:
            import requests

            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }

            payload = {
                "model": self.model,
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": user_message},
                ],
            }

            if system_message:
                payload["system"] = system_message

            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get('content', [])
                # Filter for text blocks (skip thinking blocks)
                text_blocks = [b for b in content if b.get('type') == 'text']
                if text_blocks:
                    return text_blocks[0].get('text', '')
            else:
                logger.warning(f"MiniMax API error: {response.status_code} {response.text[:200]}")
                return None

        except Exception as e:
            logger.warning(f"MiniMax API request failed: {e}")
            return None

    # ==================== Anomaly Detection ====================

    def analyze_scene_change(self, prev_description: str, curr_description: str) -> dict:
        """
        Analyze scene change between two observations.

        Uses AI when available, falls back to keyword heuristics.
        """
        # Try AI analysis
        prompt = f"""对比以下两次视觉观察，判断是否有值得注意的变化：

上一次: {prev_description}
这一次: {curr_description}

请回答：
1. 是否有显著变化？（是/否）
2. 变化类型（人物出现/离开、物体移动、光线变化、无变化）
3. 一句话总结"""

        ai_result = self._chat(prompt, SYSTEM_PROMPT)

        if ai_result:
            has_anomaly = any(kw in ai_result for kw in ['是', '出现', '离开', '异常', '变化'])
            return {
                'has_anomaly': has_anomaly,
                'type': 'scene_change',
                'description': ai_result,
                'source': 'ai',
            }

        # Fallback: keyword-based heuristic
        return self._heuristic_scene_change(prev_description, curr_description)

    def _heuristic_scene_change(self, prev: str, curr: str) -> dict:
        """Keyword-based scene change detection (no API needed)."""
        change_keywords = ['人', '检测到', '出现', '消失', '移动']
        prev_has = sum(1 for kw in change_keywords if kw in prev)
        curr_has = sum(1 for kw in change_keywords if kw in curr)

        # Face count changed
        prev_faces = self._extract_face_count(prev)
        curr_faces = self._extract_face_count(curr)

        has_anomaly = False
        description = "场景无明显变化"

        if prev_faces != curr_faces:
            has_anomaly = True
            if curr_faces > prev_faces:
                description = f"检测到新的人物出现（{prev_faces} -> {curr_faces}人）"
            else:
                description = f"有人离开了视野（{prev_faces} -> {curr_faces}人）"
        elif abs(prev_has - curr_has) >= 2:
            has_anomaly = True
            description = "画面内容发生了较大变化"

        return {
            'has_anomaly': has_anomaly,
            'type': 'scene_change',
            'description': description,
            'source': 'heuristic',
        }

    def _extract_face_count(self, description: str) -> int:
        """Extract face count from vision description text."""
        import re
        match = re.search(r'检测到(\d+)个人', description)
        if match:
            return int(match.group(1))
        if '没有检测到人脸' in description:
            return 0
        return -1  # unknown

    def analyze_audio_anomaly(self, volume_history: list) -> dict:
        """
        Detect audio anomalies from volume history.

        Looks for: sudden loud spikes, prolonged silence after activity.
        """
        if len(volume_history) < 5:
            return {'has_anomaly': False, 'type': 'audio', 'description': '数据不足'}

        import numpy as np
        volumes = np.array(volume_history[-30:])  # last 30 samples
        mean_vol = volumes.mean()
        std_vol = volumes.std()
        latest = volumes[-1]

        # Spike detection: latest volume > mean + 3*std
        if std_vol > 0 and latest > mean_vol + 3 * std_vol and latest > self.volume_spike_threshold:
            return {
                'has_anomaly': True,
                'type': 'audio_spike',
                'description': f'突然的响动！音量 {latest:.3f}（平均 {mean_vol:.3f}）',
                'severity': 'high' if latest > 0.3 else 'medium',
            }

        # Sudden silence: was active, now silent
        if len(volumes) >= 10:
            recent = volumes[-5:].mean()
            earlier = volumes[-10:-5].mean()
            if earlier > 0.02 and recent < 0.005:
                return {
                    'has_anomaly': True,
                    'type': 'sudden_silence',
                    'description': '活动后突然安静了',
                    'severity': 'low',
                }

        return {'has_anomaly': False, 'type': 'audio', 'description': '环境音正常'}

    def detect_anomalies(self, recent_observations: list) -> List[dict]:
        """
        Scan recent observations for any anomalies.

        Phase 3: integrates learner for novelty detection and
        time-aware activity pattern checks.

        Args:
            recent_observations: list of Observation objects

        Returns:
            List of anomaly dicts
        """
        anomalies = []

        # Separate by modality
        vision_obs = [o for o in recent_observations if o.modality == 'vision']
        hearing_obs = [o for o in recent_observations if o.modality == 'hearing']

        # Check scene changes
        if len(vision_obs) >= 2:
            result = self.analyze_scene_change(
                vision_obs[1].content,
                vision_obs[0].content,
            )
            if result.get('has_anomaly'):
                anomalies.append(result)

        # Learner-aware novelty detection
        if self.learner and vision_obs:
            latest_desc = vision_obs[0].content
            if self.learner.is_novel(latest_desc):
                anomalies.append({
                    'has_anomaly': True,
                    'type': 'novel_scene',
                    'description': f'场景偏离基线: {latest_desc[:60]}',
                    'severity': 'medium',
                    'source': 'learner',
                })

            # Entity matching
            matched = self.learner.match_entity(latest_desc)
            if matched:
                logger.info(f"识别到已知实体: {matched}")

        # Time-aware activity check
        if self.learner:
            hour = datetime.now(timezone(timedelta(hours=8))).hour

            # Determine current activity level from audio
            activity_level = "normal"
            if hearing_obs:
                latest_audio = hearing_obs[0].content
                if '较大' in latest_audio or '响' in latest_audio:
                    activity_level = "loud"
                elif '安静' in latest_audio:
                    activity_level = "quiet"

            if self.learner.is_unusual_activity(hour, activity_level):
                anomalies.append({
                    'has_anomaly': True,
                    'type': 'unusual_activity',
                    'description': f'{hour}点出现异常活动模式: {activity_level}',
                    'severity': 'high' if hour < 6 or hour > 23 else 'medium',
                    'source': 'learner',
                })

        # Update previous scene description
        if vision_obs:
            self._prev_scene_description = vision_obs[0].content

        return anomalies

    # ==================== Proactive Alerting ====================

    def should_alert(self, anomalies: list) -> bool:
        """Check if we should send an alert (respects cooldown)."""
        if not anomalies:
            return False

        now = time.time()
        if now - self._last_alert_time < self.anomaly_cooldown:
            return False

        return True

    def generate_alert(self, anomalies: list) -> str:
        """
        Generate a human-readable alert message for detected anomalies.

        Uses AI when available, otherwise concatenates anomaly descriptions.
        """
        descriptions = [a.get('description', '') for a in anomalies]
        combined = '\n'.join(f"- {d}" for d in descriptions)

        # Try AI-generated alert
        prompt = f"""以下是检测到的环境异常，请用一句简洁的话总结并建议是否需要关注：

{combined}"""

        ai_result = self._chat(prompt, SYSTEM_PROMPT)
        if ai_result:
            return ai_result

        # Fallback
        return ' | '.join(descriptions)

    def send_alert(self, anomalies: list):
        """Generate and send alert if conditions are met."""
        if not self.should_alert(anomalies):
            return

        self._last_alert_time = time.time()

        alert_text = self.generate_alert(anomalies)

        # Determine severity
        has_high = any(a.get('severity') == 'high' for a in anomalies)
        level = 'alert' if has_high else 'warning'

        if self.notifier:
            self.notifier.notify(level, '环境异常', alert_text)

        # Record in history
        self._alert_history.append({
            'time': time.time(),
            'anomalies': anomalies,
            'alert_text': alert_text,
        })
        # Keep last 50 alerts
        self._alert_history = self._alert_history[-50:]

    # ==================== Multimodal Fusion ====================

    def fuse_observations(self, vision_desc: str, audio_desc: str, volume: float = 0.0) -> str:
        """
        Combine vision and audio observations into a unified context.

        Cross-modal reasoning patterns:
        - See person + silence → normal (reading/working)
        - No one visible + loud noise → suspicious
        - Person leaves + door sound → departure event
        - Multiple people + conversation → social gathering
        """
        parts = []

        if vision_desc:
            parts.append(f"[视觉] {vision_desc}")
        if audio_desc:
            parts.append(f"[听觉] {audio_desc} (音量: {volume:.3f})")

        # Cross-modal pattern matching
        has_person = vision_desc and any(
            kw in vision_desc for kw in ['人', '检测到', 'person', '坐']
        )
        is_loud = volume > 0.05
        is_quiet = volume < 0.005

        inferences = []
        if has_person and is_quiet:
            inferences.append("有人在场但很安静，可能在阅读或工作")
        elif not has_person and is_loud:
            inferences.append("无人可见但有较大声响，需要关注")
        elif has_person and is_loud:
            inferences.append("有人在场且有活动声，正常活动中")

        # Add learner context if available
        if self.learner:
            entity = self.learner.match_entity(vision_desc or "")
            if entity:
                inferences.append(f"识别到: {entity}")

        if inferences:
            parts.append(f"[推断] {'; '.join(inferences)}")

        return " | ".join(parts) if parts else "暂无观察数据"

    # ==================== Status Reports ====================

    def generate_status_report(self, observations: list = None, keyframes: list = None) -> str:
        """
        Generate a periodic status report.

        Phase 3: includes baseline comparison and entity context from learner.
        Uses AI when available for natural language summary.
        """
        if observations is None and self.memory:
            observations = self.memory.get_recent(minutes=5)
        if keyframes is None and self.memory:
            keyframes = self.memory.get_keyframes(limit=5)

        if not observations:
            return "暂无观察数据"

        # Build context
        obs_summary = []
        for o in observations[:10]:
            obs_summary.append(f"[{o.modality}] {o.content[:80]}")
        obs_text = '\n'.join(obs_summary)

        kf_text = ''
        if keyframes:
            kf_lines = [f"- {kf.title}" for kf in keyframes[:5]]
            kf_text = f"\n\n关键帧:\n" + '\n'.join(kf_lines)

        # Learner context for richer AI reports
        learner_context = ''
        if self.learner:
            baseline = self.learner.get_baseline_context()
            entity_ctx = self.learner.get_entity_context()
            if baseline:
                learner_context += f"\n\n场景基线: {baseline}"
            if entity_ctx:
                learner_context += f"\n{entity_ctx}"

        # Try AI summary
        prompt = f"""根据以下最近5分钟的观察数据，生成一份简短的状态报告（3-5句话）：

观察记录:
{obs_text}{kf_text}{learner_context}

请总结：当前环境状态、与平时相比有什么不同、是否有异常、整体氛围。"""

        ai_result = self._chat(prompt, SYSTEM_PROMPT)
        if ai_result:
            return ai_result

        # Fallback: simple summary
        vision_count = sum(1 for o in observations if o.modality == 'vision')
        hearing_count = sum(1 for o in observations if o.modality == 'hearing')

        parts = [f"最近5分钟：视觉观察 {vision_count} 次，听觉观察 {hearing_count} 次。"]

        if observations:
            parts.append(f"最新观察: {observations[0].content[:60]}")

        if self._alert_history:
            recent_alerts = [a for a in self._alert_history if time.time() - a['time'] < 300]
            if recent_alerts:
                parts.append(f"近5分钟有 {len(recent_alerts)} 次异常警报。")

        return ' '.join(parts)

    # ==================== Query Interface ====================

    def answer_query(self, question: str) -> str:
        """
        Answer a user question using memory context + AI reasoning.
        """
        if not self.memory:
            return "记忆系统未初始化"

        # Gather context
        recent = self.memory.get_recent(minutes=30)
        keyframes = self.memory.get_keyframes(limit=10)

        if not recent:
            return "暂无观察数据，无法回答。"

        # Build context
        obs_lines = []
        for o in recent[:20]:
            obs_lines.append(f"[{o.timestamp[-8:]}][{o.modality}] {o.content[:80]}")
        context = '\n'.join(obs_lines)

        kf_context = ''
        if keyframes:
            kf_lines = [f"- [{kf.timestamp[-8:]}] {kf.title}: {kf.description[:60]}" for kf in keyframes[:5]]
            kf_context = "\n\n关键帧:\n" + '\n'.join(kf_lines)

        # Try AI answer
        prompt = f"""用户问题: {question}

以下是最近30分钟的环境观察数据：
{context}{kf_context}

请根据观察数据回答用户的问题。如果数据中没有相关信息，如实说明。"""

        ai_result = self._chat(prompt, SYSTEM_PROMPT)
        if ai_result:
            return ai_result

        # Fallback to memory's built-in answer
        return self.memory.answer_question(question)
