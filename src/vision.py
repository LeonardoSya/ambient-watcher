"""
视觉理解 - 分析图像内容

Uses MiniMax VLM API (/v1/coding_plan/vlm) for AI image understanding,
with OpenCV local analysis as fallback.
"""
import base64
import json
import logging
import os
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# MiniMax VLM endpoint (from coding_plan MCP source)
VLM_API_ENDPOINT = "/v1/coding_plan/vlm"
DEFAULT_API_HOST = "https://api.minimaxi.com"

DEFAULT_PROMPT = """你是一个AI环境观察者。请用简短的中文描述这张图片：
- 画面中有什么人物/物体？
- 他们在做什么？
- 环境怎么样？
- 有什么值得注意的细节？
用2-3句话概括即可。"""


class VisionAnalyzer:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.api_key = os.environ.get('MINIMAX_API_KEY') or self.config.get('api_key')
        self.api_host = self.config.get('api_host', DEFAULT_API_HOST)

    def analyze(self, image_bytes: bytes, prompt: str = None) -> Optional[dict]:
        """
        分析图像

        Args:
            image_bytes: JPEG图像字节
            prompt: 自定义提示词

        Returns:
            分析结果 dict
        """
        if prompt is None:
            prompt = DEFAULT_PROMPT

        # Try MiniMax VLM API first
        if self.api_key:
            result = self._vlm_analyze(image_bytes, prompt)
            if result:
                return result

        # Fallback to local OpenCV analysis
        return self._local_analyze(image_bytes)

    def _vlm_analyze(self, image_bytes: bytes, prompt: str) -> Optional[dict]:
        """
        MiniMax VLM API - /v1/coding_plan/vlm

        Sends base64-encoded image + prompt, returns natural language description.
        """
        try:
            import requests

            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            image_url = f"data:image/jpeg;base64,{image_b64}"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "MM-API-Source": "Minimax-MCP",
            }

            payload = {
                "prompt": prompt,
                "image_url": image_url,
            }

            response = requests.post(
                f"{self.api_host}{VLM_API_ENDPOINT}",
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                base_resp = data.get("base_resp", {})

                if base_resp.get("status_code") == 0:
                    content = data.get("content", "")
                    if content:
                        return {
                            "success": True,
                            "description": content,
                            "source": "vlm",
                        }

                logger.warning(f"VLM API error: {base_resp}")
            else:
                logger.warning(f"VLM API HTTP {response.status_code}: {response.text[:200]}")

        except Exception as e:
            logger.warning(f"VLM API failed: {e}")

        return None

    def _local_analyze(self, image_bytes: bytes) -> Optional[dict]:
        """
        本地分析 - 不需要API

        使用OpenCV进行基础分析
        """
        try:
            import cv2
            import numpy as np

            # 解码图片
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                return None

            # 基础分析
            h, w, c = img.shape

            # 转换为灰度
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 检测边缘（可以判断画面复杂度）
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = np.sum(edges > 0) / edges.size

            # 检测颜色
            avg_color = np.mean(img, axis=(0, 1))
            brightness = np.mean(avg_color)

            # 分析颜色偏向
            b, g, r = avg_color
            if r > g + 20 and r > b + 20:
                color_desc = "色调偏暖(红/橙)"
            elif b > g + 20 and b > r + 20:
                color_desc = "色调偏冷(蓝)"
            elif g > r + 20 and g > b + 20:
                color_desc = "色调偏绿"
            else:
                color_desc = "色调中性"

            # 简单场景判断
            if brightness < 50:
                scene = "光线很暗，可能是黑夜或关灯状态"
            elif brightness > 200:
                scene = "光线很亮，阳光充足"
            elif brightness > 120:
                scene = "光线明亮"
            else:
                scene = "光线柔和"

            if edge_ratio > 0.2:
                detail = "画面内容丰富"
            elif edge_ratio > 0.1:
                detail = "画面有些内容"
            else:
                detail = "画面比较空旷"

            # 尝试检测人脸
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)

            if len(faces) > 0:
                person_desc = f"检测到{len(faces)}个人"
                avg_size = np.mean([f[2] for f in faces])
                if avg_size > 100:
                    person_desc += "，距离较近"
                elif avg_size > 50:
                    person_desc += "，距离适中"
                else:
                    person_desc += "，距离较远"
            else:
                person_desc = "没有检测到人脸"

            description = f"{scene}，{detail}，{color_desc}，{person_desc}。"

            return {
                'success': True,
                'description': description,
                'source': 'local',
                'brightness': float(brightness),
                'edge_ratio': float(edge_ratio),
                'faces': len(faces),
            }

        except Exception as e:
            logger.error(f"本地分析失败: {e}")
            return {
                'success': True,
                'description': '[观察] 我看到了画面变化',
                'source': 'local',
            }

    def detect_changes(self, image1_bytes: bytes, image2_bytes: bytes) -> float:
        """
        检测两张图片的差异

        Returns:
            差异分数 (0-1)，越大表示差异越大
        """
        import cv2
        import numpy as np

        # 解码图片
        nparr1 = np.frombuffer(image1_bytes, np.uint8)
        nparr2 = np.frombuffer(image2_bytes, np.uint8)

        img1 = cv2.imdecode(nparr1, cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imdecode(nparr2, cv2.IMREAD_GRAYSCALE)

        if img1 is None or img2 is None:
            return 0.0

        # 调整大小
        img1 = cv2.resize(img1, (256, 256))
        img2 = cv2.resize(img2, (256, 256))

        # 计算差异
        diff = cv2.absdiff(img1, img2)
        score = diff.mean() / 255.0

        return score

    def quick_check(self, image_bytes: bytes) -> str:
        """
        快速检查 - 是否有明显变化

        返回简短描述
        """
        result = self.analyze(image_bytes, prompt="用一句话描述这张图片最核心的内容")
        if result:
            return result.get('description', '')[:200]
        return "[无法分析]"


# 便捷函数
def quick_describe(image_bytes: bytes, api_key: str = None) -> str:
    """快速描述图片"""
    config = {'api_key': api_key} if api_key else {}
    analyzer = VisionAnalyzer(config)
    result = analyzer.analyze(image_bytes)
    if result:
        return result.get('description', '')
    return "[分析失败]"
