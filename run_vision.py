"""
Ambient Watcher - 后台运行模式
带麦克风调试输出
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

# 设置麦克风模块的日志
mic_logger = logging.getLogger('src.microphone')
mic_logger.setLevel(logging.DEBUG)

running = True

def signal_handler(signum, frame):
    global running
    logger.info("收到退出信号...")
    running = False

def main():
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🌊 Ambient Watcher 启动")
    print("=" * 50)
    
    # 创建 watcher
    watcher = get_watcher()
    
    # 禁用麦克风，只用视觉（调试用）
    watcher.config['hearing']['enabled'] = False
    
    watcher.start()
    
    print("✅ 已启动（视觉模式）")
    print("=" * 50)
    
    # 保持运行
    try:
        while running:
            time.sleep(10)
            
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
