import time
import threading
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
PORT = 8004
REGISTRY_URL = 'http://localhost:8001'

METRICS_RETENTION = 5 * 60 * 1000
MAX_HISTORY_SIZE = 10000


class ServiceMetrics:
    def __init__(self, service_name):
        self.service_name = service_name
        self.total_requests = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_response_time = 0
        self.min_response_time = float('inf')
        self.max_response_time = 0
        self.request_timestamps = []
        self.successes = []
        self.failures = []
        self.response_times = []
        self.last_request_time = 0
        self.lock = threading.Lock()

    def record_request(self, success, response_time=0, endpoint='default'):
        with self.lock:
            timestamp = int(time.time() * 1000)
            self.total_requests += 1
            self.last_request_time = timestamp
            self.request_timestamps.append(timestamp)

            if success:
                self.success_count += 1
                self.successes.append({
                    'timestamp': timestamp,
                    'endpoint': endpoint,
                    'responseTime': response_time
                })
            else:
                self.failure_count += 1
                self.failures.append({
                    'timestamp': timestamp,
                    'endpoint': endpoint,
                    'responseTime': response_time
                })

            if response_time > 0:
                self.total_response_time += response_time
                self.response_times.append({
                    'timestamp': timestamp,
                    'responseTime': response_time,
                    'success': success
                })
                self.min_response_time = min(self.min_response_time, response_time)
                self.max_response_time = max(self.max_response_time, response_time)

            self.cleanup()

    def cleanup(self):
        now = int(time.time() * 1000)
        cutoff = now - METRICS_RETENTION

        self.request_timestamps = [t for t in self.request_timestamps if t >= cutoff]
        self.successes = [s for s in self.successes if s['timestamp'] >= cutoff]
        self.failures = [f for f in self.failures if f['timestamp'] >= cutoff]
        self.response_times = [r for r in self.response_times if r['timestamp'] >= cutoff]

        if len(self.request_timestamps) > MAX_HISTORY_SIZE:
            excess = len(self.request_timestamps) - MAX_HISTORY_SIZE
            self.request_timestamps = self.request_timestamps[excess:]
            self.successes = self.successes[-MAX_HISTORY_SIZE:]
            self.failures = self.failures[-MAX_HISTORY_SIZE:]
            self.response_times = self.response_times[-MAX_HISTORY_SIZE:]

    def get_stats(self, window_ms=60000):
        with self.lock:
            now = int(time.time() * 1000)
            cutoff = now - window_ms

            recent_requests = [t for t in self.request_timestamps if t >= cutoff]
            recent_successes = [s for s in self.successes if s['timestamp'] >= cutoff]
            recent_failures = [f for f in self.failures if f['timestamp'] >= cutoff]
            recent_response_times = [r for r in self.response_times if r['timestamp'] >= cutoff]

            avg_response_time = (
                sum(r['responseTime'] for r in recent_response_times) / len(recent_response_times)
                if recent_response_times else 0
            )

            error_rate = (
                len(recent_failures) / len(recent_requests)
                if recent_requests else 0
            )

            requests_per_second = (
                len(recent_requests) / (window_ms / 1000)
                if window_ms > 0 else 0
            )

            return {
                'serviceName': self.service_name,
                'totalRequests': self.total_requests,
                'successCount': self.success_count,
                'failureCount': self.failure_count,
                'windowSizeMs': window_ms,
                'windowRequests': len(recent_requests),
                'windowSuccesses': len(recent_successes),
                'windowFailures': len(recent_failures),
                'errorRate': round(error_rate, 4),
                'requestsPerSecond': round(requests_per_second, 2),
                'avgResponseTime': round(avg_response_time, 2),
                'minResponseTime': 0 if self.min_response_time == float('inf') else self.min_response_time,
                'maxResponseTime': self.max_response_time,
                'lastRequestTime': self.last_request_time,
                'requestTimestamps': recent_requests,
                'successes': recent_successes,
                'failures': recent_failures
            }


metrics_store = {}
metrics_store_lock = threading.Lock()


def sync_with_registry():
    try:
        response = requests.get(f"{REGISTRY_URL}/api/registry/services", timeout=2)
        if response.json().get('success'):
            services = response.json().get('services', {})
            with metrics_store_lock:
                for service_name in services.keys():
                    if service_name not in metrics_store:
                        metrics_store[service_name] = ServiceMetrics(service_name)
                        print(f"[统计收集器] 初始化统计: {service_name}")
    except Exception as e:
        print(f"[统计收集器] 同步注册中心失败: {str(e)}")


def cleanup_all_metrics():
    with metrics_store_lock:
        for metrics in metrics_store.values():
            metrics.cleanup()


def background_sync():
    while True:
        sync_with_registry()
        time.sleep(5)


def background_cleanup():
    while True:
        cleanup_all_metrics()
        time.sleep(30)


@app.route('/api/metrics/record', methods=['POST'])
def record():
    data = request.get_json()
    service_name = data.get('serviceName')
    success = data.get('success')
    response_time = data.get('responseTime', 0)
    endpoint = data.get('endpoint', 'default')

    if not service_name or success is None:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, success'
        }), 400

    with metrics_store_lock:
        metrics = metrics_store.get(service_name)
        if not metrics:
            metrics = ServiceMetrics(service_name)
            metrics_store[service_name] = metrics

    metrics.record_request(success, response_time, endpoint)

    return jsonify({
        'success': True,
        'message': '统计数据已记录',
        'serviceName': service_name,
        'recorded': {
            'success': success,
            'responseTime': response_time,
            'endpoint': endpoint,
            'timestamp': int(time.time() * 1000)
        }
    })


@app.route('/api/metrics/service/<service_name>', methods=['GET'])
def get_service_metrics(service_name):
    window_ms = int(request.args.get('windowMs', 60000))

    with metrics_store_lock:
        metrics = metrics_store.get(service_name)
    if not metrics:
        return jsonify({
            'success': False,
            'error': '未找到该服务的统计数据'
        }), 404

    return jsonify({
        'success': True,
        'serviceName': service_name,
        'metrics': metrics.get_stats(window_ms)
    })


@app.route('/api/metrics/all', methods=['GET'])
def get_all_metrics():
    window_ms = int(request.args.get('windowMs', 60000))
    with metrics_store_lock:
        all_metrics = {}

        for service_name, metrics in metrics_store.items():
            all_metrics[service_name] = metrics.get_stats(window_ms)

    return jsonify({
        'success': True,
        'totalServices': len(metrics_store),
        'windowSizeMs': window_ms,
        'metrics': all_metrics
    })


@app.route('/api/metrics/summary', methods=['GET'])
def get_summary():
    window_ms = int(request.args.get('windowMs', 60000))
    summary = []

    with metrics_store_lock:
        for service_name, metrics in metrics_store.items():
            stats = metrics.get_stats(window_ms)
            summary.append({
                'serviceName': service_name,
                'totalRequests': stats['totalRequests'],
                'windowRequests': stats['windowRequests'],
                'successCount': stats['successCount'],
                'failureCount': stats['failureCount'],
                'errorRate': stats['errorRate'],
                'requestsPerSecond': stats['requestsPerSecond'],
                'avgResponseTime': stats['avgResponseTime']
            })

    total_all_requests = sum(s['windowRequests'] for s in summary)
    total_all_success = sum(s['windowSuccesses'] for s in summary) if summary else 0
    total_all_failures = sum(s['windowFailures'] for s in summary) if summary else 0

    return jsonify({
        'success': True,
        'windowSizeMs': window_ms,
        'totalServices': len(metrics_store),
        'totalRequests': total_all_requests,
        'totalSuccesses': total_all_success,
        'totalFailures': total_all_failures,
        'overallErrorRate': round(total_all_failures / total_all_requests, 4) if total_all_requests > 0 else 0,
        'services': summary
    })


@app.route('/api/metrics/reset', methods=['POST'])
def reset():
    data = request.get_json()
    service_name = data.get('serviceName')

    if not service_name:
        with metrics_store_lock:
            metrics_store.clear()
        print('[统计收集器] 已重置所有统计数据')
        return jsonify({
            'success': True,
            'message': '所有统计数据已重置'
        })

    with metrics_store_lock:
        if service_name in metrics_store:
            metrics_store[service_name] = ServiceMetrics(service_name)
            print(f"[统计收集器] 已重置统计数据: {service_name}")
            return jsonify({
                'success': True,
                'message': f'服务 {service_name} 统计数据已重置'
            })

    return jsonify({
        'success': False,
        'error': '未找到该服务的统计数据'
    }), 404


@app.route('/api/metrics/health', methods=['GET'])
def health():
    return jsonify({
        'success': True,
        'service': 'metrics-collector-service',
        'port': PORT,
        'status': 'running',
        'timestamp': int(time.time() * 1000)
    })


if __name__ == '__main__':
    threading.Thread(target=background_sync, daemon=True).start()
    threading.Thread(target=background_cleanup, daemon=True).start()
    sync_with_registry()
    print(f"[统计收集器] 服务启动成功，监听端口: {PORT}")
    print(f"[统计收集器] 健康检查: http://localhost:{PORT}/api/metrics/health")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True, processes=1)
