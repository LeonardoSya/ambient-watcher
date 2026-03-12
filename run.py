#!/usr/bin/env python3
"""
Ambient Watcher - 后台运行模式
"""
import logging
import sys
import time
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.watcher import get_watcher

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

running = True

def signal_handler(signum, frame):
    global running
    logger.info("收到退出信号...")
    running = False

def main():
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🌊 Ambient Watcher 后台模式启动")
    print("=" * 40)
    
    # 创建并启动 watcher
    watcher = get_watcher()
    watcher.start()
    
    print("✅ 已启动观察")
    print("输入以下命令测试:")
    print("  python3 main.py describe  - 描述当前")
    print("  python3 main.py summary  - 记忆摘要")
    print("  python3 main.py query '你的问题'")
    print("  python3 main.py status   - 查看状态")
    print("=" * 40)
    print("按 Ctrl+C 停止\n")
    
    # 保持运行
    try:
        while running:
            time.sleep(10)
            
            # 每30秒打印一次状态
            status = watcher.get_status()
            logger.info(f"状态: {status['state']}, 记忆: {status['memory']}")
            
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("正在停止...")
        watcher.stop()
        print("✅ 已停止")

if __name__ == '__main__':
    main()
