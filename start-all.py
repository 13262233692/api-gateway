import subprocess
import sys
import os
import time
import signal

services = [
    {'name': '注册中心', 'script': 'registry-service.py', 'port': 8001},
    {'name': '限流决策器', 'script': 'rate-limiter-service.py', 'port': 8002},
    {'name': '熔断状态机', 'script': 'circuit-breaker-service.py', 'port': 8003},
    {'name': '统计收集器', 'script': 'metrics-collector-service.py', 'port': 8004}
]

processes = []


def start_service(service):
    script_path = os.path.join(os.path.dirname(__file__), service['script'])
    proc = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return proc


def monitor_output(service, proc):
    def read_output():
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            print(f"[{service['name']}] {line.rstrip()}")

    def read_error():
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            print(f"[{service['name']}][错误] {line.rstrip()}")

    import threading
    threading.Thread(target=read_output, daemon=True).start()
    threading.Thread(target=read_error, daemon=True).start()


def signal_handler(signum, frame):
    print('\n收到停止信号，正在关闭所有服务...')
    for service, proc in processes:
        print(f"停止 {service['name']}...")
        proc.terminate()
    time.sleep(1)
    print('所有服务已停止')
    sys.exit(0)


def main():
    print('=' * 60)
    print('分布式限流与熔断管理中心 - 启动所有服务')
    print('=' * 60)
    print()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    for service in services:
        try:
            proc = start_service(service)
            monitor_output(service, proc)
            processes.append((service, proc))
            time.sleep(1)
            print(f"[{service['name']}] 已启动，端口: {service['port']}")
        except Exception as e:
            print(f"启动服务 {service['name']} 失败: {str(e)}")

    print()
    print('=' * 60)
    print('所有服务启动完成！')
    print('=' * 60)
    print()
    print('服务列表:')
    for s in services:
        prefix = s['script'].split('-')[0]
        print(f"  {s['name']}: http://localhost:{s['port']}")
        print(f"    健康检查: http://localhost:{s['port']}/api/{prefix}/health")
    print()
    print('按 Ctrl+C 停止所有服务')
    print()

    while True:
        for service, proc in processes:
            if proc.poll() is not None:
                print(f"[{service['name']}] 进程退出，代码: {proc.returncode}")
        time.sleep(1)


if __name__ == '__main__':
    main()
