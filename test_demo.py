#!/usr/bin/env python3
"""
Ambient Watcher 测试模式
使用模拟数据演示功能，不需要摄像头权限
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.memory import Memory
from src.config import load_config

# 北京时区
tz = timezone(timedelta(hours=8))

def simulate_observations(memory: Memory):
    """模拟一些观察数据"""
    print("🎭 模拟观察数据...")
    
    observations = [
        ("vision", "我看到你坐在桌前，盯着屏幕敲代码", 2),
        ("vision", "你拿起手机看了一眼，又放下", 3),
        ("hearing", "键盘敲击声", 1),
        ("vision", "你站了起来，走向冰箱", 3),
        ("hearing", "冰箱门打开的声音", 2),
        ("vision", "你拿着饮料走回来坐下", 2),
        ("vision", "你对着屏幕笑了，可能看到了有趣的内容", 4),
        ("hearing", "你轻声哼起了歌", 3),
        ("vision", "你继续敲代码，眉头微皱", 2),
        ("hearing", "门铃声响起", 5),
        ("vision", "你起身去开门", 4),
    ]
    
    for modality, content, importance in observations:
        memory.add(modality, content, importance=importance)
        time.sleep(0.1)
    
    print(f"   已添加 {len(observations)} 条模拟观察\n")

def test_query(memory: Memory):
    """测试各种查询"""
    print("🔍 测试查询功能:\n")
    
    questions = [
        "刚才发生了什么？",
        "今天有啥重要的事？",
        "关键帧",
        "谁在家？",
        "有什么动静？",
    ]
    
    for q in questions:
        print(f"❓ 问: {q}")
        answer = memory.answer_question(q)
        print(f"💬 答: {answer}")
        print()

def test_keyframes(memory: Memory):
    """测试关键帧"""
    print("⭐ 测试关键帧:")
    
    # 手动添加一个关键帧
    memory.add_keyframe(
        modality="event",
        title="你出门了",
        description="下午2点左右，你拿起外套走出家门",
        tags=["manual", "leave"]
    )
    
    # 查看关键帧
    kfs = memory.get_keyframes(limit=5)
    print(f"\n   共有 {len(kfs)} 个关键帧:")
    for kf in kfs:
        dt = datetime.fromisoformat(kf.timestamp).strftime("%m-%d %H:%M")
        print(f"   • [{dt}] {kf.title}")

def test_stats(memory: Memory):
    """测试统计"""
    print("\n📊 统计信息:")
    stats = memory.get_stats()
    for k, v in stats.items():
        print(f"   {k}: {v}")

def main():
    print("=" * 50)
    print("🎭 Ambient Watcher 测试模式")
    print("=" * 50 + "\n")
    
    # 创建内存系统
    config = load_config()
    memory = Memory(config.get('memory', {}))
    
    # 模拟数据
    simulate_observations(memory)
    
    # 测试查询
    test_query(memory)
    
    # 测试关键帧
    test_keyframes(memory)
    
    # 测试统计
    test_stats(memory)
    
    print("\n" + "=" * 50)
    print("✅ 测试完成!")
    print("=" * 50)
    print("""
📝 数据已保存到: ambient-watcher/data/
   - observations.json (日志)
   - keyframes.json (关键帧)

🚀 回家后运行:
   cd ambient-watcher
   python3 main.py start
   
   然后授权摄像头权限即可真正开始观察世界！
    """)

if __name__ == '__main__':
    main()
