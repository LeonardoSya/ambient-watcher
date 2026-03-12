"""
Learner - personalized scene learning and adaptive baseline.

Responsibilities:
- Maintain a running baseline of "normal" scene descriptions
- Learn and recognize known entities (people, objects)
- Track activity patterns by time-of-day
- Persist all learned data to data/learner.json
"""
import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Beijing timezone
_TZ = timezone(timedelta(hours=8))


class Learner:
    """
    Adaptive learning engine for personalized environment understanding.

    Three subsystems:
    1. Scene Baseline — running average of "normal" descriptions
    2. Known Entities — "Seiya: glasses, black hair"
    3. Activity Patterns — time-of-day histogram of activity levels
    """

    def __init__(self, config: dict = None, data_dir: str = "data"):
        self.config = config or {}
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store_path = self.data_dir / "learner.json"

        # Config
        self.baseline_window = self.config.get("baseline_window", 50)
        self.novelty_threshold = self.config.get("novelty_threshold", 0.5)

        # State
        self._baseline_descriptions: list[str] = []
        self._entities: dict[str, str] = {}  # name -> description
        self._activity_histogram: dict[str, Counter] = {}  # hour_str -> Counter of levels
        self._lock = threading.Lock()

        self._load()

    # ==================== Persistence ====================

    def _load(self):
        """Load learned data from disk."""
        if not self.store_path.exists():
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._baseline_descriptions = data.get("baseline", [])
            self._entities = data.get("entities", {})
            # Restore histogram: JSON keys are strings
            raw_hist = data.get("activity_histogram", {})
            self._activity_histogram = {
                k: Counter(v) for k, v in raw_hist.items()
            }
            logger.info(
                f"Learner loaded: {len(self._baseline_descriptions)} baseline samples, "
                f"{len(self._entities)} entities"
            )
        except Exception as e:
            logger.warning(f"Failed to load learner data: {e}")

    def _save(self):
        """Persist learned data to disk (atomic write)."""
        try:
            import tempfile
            data = {
                "baseline": self._baseline_descriptions,
                "entities": self._entities,
                "activity_histogram": {
                    k: dict(v) for k, v in self._activity_histogram.items()
                },
            }
            # Write to temp file, then rename for atomicity
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.data_dir), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(self.store_path))
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as e:
            logger.warning(f"Failed to save learner data: {e}")

    # ==================== Scene Baseline ====================

    def update_baseline(self, description: str):
        """
        Feed a new scene description into the running baseline.

        Keeps the last `baseline_window` descriptions as the "normal" profile.
        """
        with self._lock:
            self._baseline_descriptions.append(description)
            # Trim to window
            if len(self._baseline_descriptions) > self.baseline_window:
                self._baseline_descriptions = self._baseline_descriptions[
                    -self.baseline_window:
                ]
            self._save()

    def is_novel(self, description: str) -> bool:
        """
        Check if a description deviates significantly from the baseline.

        Uses keyword overlap ratio: if the new description shares less than
        `novelty_threshold` of its keywords with the baseline, it's novel.
        """
        with self._lock:
            if len(self._baseline_descriptions) < 5:
                return False  # Not enough data to judge

            # Build baseline keyword set
            baseline_keywords = set()
            for desc in self._baseline_descriptions[-20:]:
                baseline_keywords.update(self._extract_keywords(desc))

            if not baseline_keywords:
                return False

            # Check overlap
            current_keywords = set(self._extract_keywords(description))
            if not current_keywords:
                return False

            overlap = len(current_keywords & baseline_keywords) / len(current_keywords)
            return overlap < self.novelty_threshold

    def get_baseline_summary(self) -> str:
        """
        Generate a human-readable summary of the scene baseline.

        Returns keyword frequency profile and sample count.
        """
        with self._lock:
            if not self._baseline_descriptions:
                return "暂无场景基线数据，系统还在学习中..."

            # Keyword frequency
            keyword_counter: Counter = Counter()
            for desc in self._baseline_descriptions:
                keyword_counter.update(self._extract_keywords(desc))

            top_keywords = keyword_counter.most_common(10)
            sample_count = len(self._baseline_descriptions)

            lines = [
                f"场景基线（基于 {sample_count} 次观察）:",
                "",
                "常见特征:",
            ]
            for kw, count in top_keywords:
                pct = count / sample_count * 100
                lines.append(f"  - {kw}: {pct:.0f}% 出现率")

            # Latest description as reference
            lines.append(f"\n最近场景: {self._baseline_descriptions[-1][:80]}")

            return "\n".join(lines)

    def get_baseline_context(self) -> str:
        """
        Get a compact baseline context string for AI prompts.

        Returns the 3 most recent baseline descriptions concatenated.
        """
        with self._lock:
            if not self._baseline_descriptions:
                return ""
            recent = self._baseline_descriptions[-3:]
            return " | ".join(d[:60] for d in recent)

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """
        Extract meaningful keywords from a Chinese/mixed description.

        Simple approach: split on punctuation, filter short tokens.
        """
        # Split on Chinese/English punctuation and whitespace
        tokens = re.split(r"[，。！？、；：\s,.\-!?;:]+", text)
        # Keep tokens with length >= 2 (meaningful in Chinese)
        return [t for t in tokens if len(t) >= 2]

    # ==================== Known Entities ====================

    def learn_entity(self, name: str, description: str):
        """
        Teach the system about a known entity.

        Example: learn_entity("Seiya", "glasses, black hair, developer")
        """
        with self._lock:
            self._entities[name] = description
            self._save()
        logger.info(f"Learned entity: {name} = {description}")

    def get_entities(self) -> dict[str, str]:
        """Return all known entities."""
        with self._lock:
            return dict(self._entities)

    def match_entity(self, description: str) -> Optional[str]:
        """
        Try to match a scene description to a known entity.

        Returns the entity name if keywords match, None otherwise.
        """
        with self._lock:
            if not self._entities:
                return None

            desc_lower = description.lower()
            best_match = None
            best_score = 0

            for name, entity_desc in self._entities.items():
                entity_keywords = self._extract_keywords(entity_desc.lower())
                if not entity_keywords:
                    continue
                matches = sum(1 for kw in entity_keywords if kw in desc_lower)
                score = matches / len(entity_keywords)
                if score > best_score and score >= 0.3:
                    best_score = score
                    best_match = name

            return best_match

    def forget_entity(self, name: str) -> bool:
        """Remove a known entity."""
        with self._lock:
            if name in self._entities:
                del self._entities[name]
                self._save()
                return True
            return False

    # ==================== Activity Patterns ====================

    def record_activity(self, hour: int = None, level: str = "normal"):
        """
        Record an activity observation at a given hour.

        Args:
            hour: 0-23 (defaults to current hour)
            level: "quiet", "normal", "active", "loud"
        """
        if hour is None:
            hour = datetime.now(_TZ).hour

        hour_key = str(hour)

        with self._lock:
            if hour_key not in self._activity_histogram:
                self._activity_histogram[hour_key] = Counter()
            self._activity_histogram[hour_key][level] += 1
            self._save()

    def is_unusual_activity(self, hour: int = None, level: str = "normal") -> bool:
        """
        Check if the given activity level is unusual for this hour.

        Returns True if this level has never been seen at this hour,
        or accounts for less than 10% of observations at this hour.
        """
        if hour is None:
            hour = datetime.now(_TZ).hour

        hour_key = str(hour)

        with self._lock:
            if hour_key not in self._activity_histogram:
                return False  # No data for this hour yet

            hist = self._activity_histogram[hour_key]
            total = sum(hist.values())
            if total < 5:
                return False  # Not enough data

            count = hist.get(level, 0)
            ratio = count / total
            return ratio < 0.1

    def get_activity_summary(self) -> str:
        """Get a readable summary of activity patterns."""
        with self._lock:
            if not self._activity_histogram:
                return "暂无活动模式数据"

            lines = ["活动模式:"]
            for hour in sorted(self._activity_histogram.keys(), key=int):
                hist = self._activity_histogram[hour]
                total = sum(hist.values())
                dominant = hist.most_common(1)[0] if hist else ("unknown", 0)
                lines.append(
                    f"  {hour.zfill(2)}:00 — {dominant[0]} "
                    f"({dominant[1]}/{total} 次)"
                )
            return "\n".join(lines)

    # ==================== Entity Context for AI ====================

    def get_entity_context(self) -> str:
        """
        Build context string of known entities for AI prompts.

        Used by Analyzer to include entity knowledge in reasoning.
        """
        with self._lock:
            if not self._entities:
                return ""
            lines = ["已知人物/物体:"]
            for name, desc in self._entities.items():
                lines.append(f"  - {name}: {desc}")
            return "\n".join(lines)
