#!/usr/bin/env python3
"""
Ambient Watcher - CLI Entry Point

Usage:
    python main.py start           # Start watching
    python main.py status          # Show current status
    python main.py query "问题"    # Ask a question about the environment
"""
import argparse
import logging
import sys
import time

from src.watcher import AmbientWatcher


def setup_logging(level: str = "INFO"):
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_start(args):
    """Start the ambient watcher."""
    setup_logging(args.log_level)

    watcher = AmbientWatcher(config_path=args.config)
    watcher.start()

    try:
        # Keep main thread alive
        while watcher.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()


def cmd_status(args):
    """Show status from a running watcher (reads memory directly)."""
    setup_logging("WARNING")

    from src.memory import Memory
    from src.config import load_config

    config = load_config(args.config)
    memory = Memory(config.get('memory', {}))
    stats = memory.get_stats()
    summary = memory.get_summary()

    print("=" * 40)
    print("  Ambient Watcher Status")
    print("=" * 40)
    print(f"  Observations: {stats['observations']}")
    print(f"  Keyframes:    {stats['keyframes']}")
    print(f"  Vision:       {stats['vision_count']}")
    print(f"  Hearing:      {stats['hearing_count']}")
    print("=" * 40)
    print()
    print(summary)


def cmd_query(args):
    """Answer a question using memory + AI."""
    setup_logging("WARNING")

    from src.memory import Memory
    from src.config import load_config
    from src.analyzer import Analyzer
    from src.notifier import Notifier
    from src.learner import Learner

    config = load_config(args.config)
    data_dir = config.get('memory', {}).get('data_dir', 'data')
    memory = Memory(config.get('memory', {}))
    notifier = Notifier(config.get('notifier', {}))
    learner = Learner(config=config.get('learner', {}), data_dir=data_dir)
    analyzer = Analyzer(
        config=config.get('analyzer', {}),
        memory=memory,
        notifier=notifier,
        learner=learner,
    )

    question = ' '.join(args.question)
    if not question:
        print("请提供问题，例如: python main.py query '刚才发生了什么？'")
        sys.exit(1)

    answer = analyzer.answer_query(question)
    print(answer)


def cmd_learn(args):
    """Teach the system about a known entity."""
    setup_logging("WARNING")

    from src.config import load_config
    from src.learner import Learner

    config = load_config(args.config)
    data_dir = config.get('memory', {}).get('data_dir', 'data')
    learner = Learner(config=config.get('learner', {}), data_dir=data_dir)

    text = ' '.join(args.text)
    if not text:
        print("请提供描述，例如: python main.py learn '这个人是Seiya，戴眼镜'")
        sys.exit(1)

    # Parse "这个人是Seiya" or "Seiya: glasses, black hair"
    if '是' in text:
        parts = text.split('是', 1)
        name = parts[1].strip().split('，')[0].split(',')[0].strip()
        description = text
    elif ':' in text or '：' in text:
        sep = ':' if ':' in text else '：'
        parts = text.split(sep, 1)
        name = parts[0].strip()
        description = parts[1].strip()
    else:
        name = text.split()[0] if text.split() else text
        description = text

    learner.learn_entity(name, description)
    print(f"已学习: {name} = {description}")

    # Show all known entities
    entities = learner.get_entities()
    if entities:
        print(f"\n已知实体 ({len(entities)}):")
        for n, d in entities.items():
            print(f"  - {n}: {d}")


def cmd_baseline(args):
    """Show the scene baseline profile."""
    setup_logging("WARNING")

    from src.config import load_config
    from src.learner import Learner

    config = load_config(args.config)
    data_dir = config.get('memory', {}).get('data_dir', 'data')
    learner = Learner(config=config.get('learner', {}), data_dir=data_dir)

    print("=" * 40)
    print("  Scene Baseline Profile")
    print("=" * 40)
    print()
    print(learner.get_baseline_summary())
    print()

    # Show entities
    entities = learner.get_entities()
    if entities:
        print("已知实体:")
        for name, desc in entities.items():
            print(f"  - {name}: {desc}")
        print()

    # Show activity patterns
    print(learner.get_activity_summary())


def cmd_history(args):
    """Show recent observations with timestamps."""
    setup_logging("WARNING")

    from datetime import datetime
    from src.memory import Memory
    from src.config import load_config

    config = load_config(args.config)
    memory = Memory(config.get('memory', {}))

    minutes = args.minutes
    limit = args.limit
    recent = memory.get_recent(minutes=minutes)

    if not recent:
        print("暂无观察记录")
        return

    print("=" * 50)
    print(f"  Recent Observations (last {minutes} min)")
    print("=" * 50)

    for obs in recent[:limit]:
        try:
            dt = datetime.fromisoformat(obs.timestamp)
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = obs.timestamp[-8:]

        icon = "👀" if obs.modality == "vision" else "👂"
        importance_stars = "★" * obs.importance
        tags_str = f" [{','.join(obs.tags)}]" if obs.tags else ""

        print(f"  {time_str} {icon} {importance_stars} {obs.content[:70]}{tags_str}")

    print(f"\n  Total: {len(recent)} observations")


def main():
    parser = argparse.ArgumentParser(
        description="Ambient Watcher - AI环境感知系统",
    )
    subparsers = parser.add_subparsers(dest='command', help='命令')

    # start
    start_parser = subparsers.add_parser('start', help='启动观察')
    start_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    start_parser.add_argument('--log-level', '-l', default='INFO', help='日志级别')
    start_parser.set_defaults(func=cmd_start)

    # status
    status_parser = subparsers.add_parser('status', help='查看状态')
    status_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    status_parser.set_defaults(func=cmd_status)

    # query
    query_parser = subparsers.add_parser('query', help='查询问题')
    query_parser.add_argument('question', nargs='+', help='问题内容')
    query_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    query_parser.set_defaults(func=cmd_query)

    # learn
    learn_parser = subparsers.add_parser('learn', help='教系统认识实体')
    learn_parser.add_argument('text', nargs='+', help='描述，如 "这个人是Seiya" 或 "Seiya: 戴眼镜"')
    learn_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    learn_parser.set_defaults(func=cmd_learn)

    # baseline
    baseline_parser = subparsers.add_parser('baseline', help='查看场景基线')
    baseline_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    baseline_parser.set_defaults(func=cmd_baseline)

    # history
    history_parser = subparsers.add_parser('history', help='查看近期观察历史')
    history_parser.add_argument('--minutes', '-m', type=int, default=30, help='查看最近N分钟')
    history_parser.add_argument('--limit', '-n', type=int, default=20, help='显示条数')
    history_parser.add_argument('--config', '-c', default=None, help='配置文件路径')
    history_parser.set_defaults(func=cmd_history)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
