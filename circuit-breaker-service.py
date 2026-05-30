import time
import threading
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
PORT = 8003
METRICS_URL = 'http://localhost:8004'
REGISTRY_URL = 'http://localhost:8001'

CIRCUIT_STATE = {
    'CLOSED': 'CLOSED',
    'OPEN': 'OPEN',
    'HALF_OPEN': 'HALF_OPEN'
}


class CircuitBreaker:
    def __init__(self, service_name, config=None):
        config = config or {}
        self.service_name = service_name
        self.state = CIRCUIT_STATE['CLOSED']
        self.failure_threshold = config.get('failureThreshold', 5)
        self.failure_rate_threshold = config.get('failureRateThreshold', 0.5)
        self.open_timeout = config.get('openTimeout', 30000)
        self.half_open_max_requests = config.get('halfOpenMaxRequests', 3)
        self.window_size = config.get('windowSize', 60000)
        self.last_state_change = int(time.time() * 1000)
        self.half_open_requests = 0
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self.total_requests = 0
        self.lock = threading.Lock()

    def check_metrics(self):
        try:
            response = requests.get(f"{METRICS_URL}/api/metrics/service/{self.service_name}", timeout=2)
            data = response.json()
            if data.get('success'):
                metrics = data.get('metrics', {})
                now = int(time.time() * 1000)
                timestamps = metrics.get('requestTimestamps', [])
                recent_requests = [t for t in timestamps if now - t < self.window_size]
                failures = metrics.get('failures', [])
                recent_failures = [f for f in failures if now - f.get('timestamp', 0) < self.window_size]

                self.total_requests = len(recent_requests)
                self.failure_count = len(recent_failures)
                self.success_count = len(recent_requests) - len(recent_failures)
        except Exception as e:
            print(f"[熔断状态机] 获取统计数据失败: {self.service_name} - {str(e)}")

    def get_failure_rate(self):
        if self.total_requests == 0:
            return 0
        return self.failure_count / self.total_requests

    def evaluate_state(self):
        with self.lock:
            self.check_metrics()
            now = int(time.time() * 1000)

            if self.state == CIRCUIT_STATE['CLOSED']:
                failure_rate = self.get_failure_rate()
                if (self.failure_count >= self.failure_threshold and
                        failure_rate >= self.failure_rate_threshold):
                    self.transition_to(CIRCUIT_STATE['OPEN'])

            elif self.state == CIRCUIT_STATE['OPEN']:
                if now - self.last_state_change >= self.open_timeout:
                    self.transition_to(CIRCUIT_STATE['HALF_OPEN'])
                    self.half_open_requests = 0

            elif self.state == CIRCUIT_STATE['HALF_OPEN']:
                if self.half_open_requests >= self.half_open_max_requests:
                    half_open_failure_rate = self.get_failure_rate()
                    if half_open_failure_rate >= self.failure_rate_threshold:
                        self.transition_to(CIRCUIT_STATE['OPEN'])
                    else:
                        self.transition_to(CIRCUIT_STATE['CLOSED'])

    def transition_to(self, new_state):
        if self.state != new_state:
            print(f"[熔断状态机] {self.service_name} 状态变化: {self.state} -> {new_state}")
            self.state = new_state
            self.last_state_change = int(time.time() * 1000)
            if new_state == CIRCUIT_STATE['HALF_OPEN']:
                self.half_open_requests = 0

    def allow_request(self):
        with self.lock:
            if self.state == CIRCUIT_STATE['OPEN']:
                return {'allowed': False, 'state': self.state, 'reason': '熔断器已打开'}

            if self.state == CIRCUIT_STATE['HALF_OPEN']:
                if self.half_open_requests >= self.half_open_max_requests:
                    return {'allowed': False, 'state': self.state, 'reason': '半开状态请求数已达上限'}
                self.half_open_requests += 1

            return {'allowed': True, 'state': self.state, 'reason': '请求允许通过'}

    def record_success(self):
        with self.lock:
            self.success_count += 1
            self.failure_count = max(0, self.failure_count - 1)
            if self.state == CIRCUIT_STATE['HALF_OPEN']:
                self.evaluate_state()

    def record_failure(self):
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = int(time.time() * 1000)
            self.evaluate_state()

    def get_state_info(self):
        with self.lock:
            return {
                'serviceName': self.service_name,
                'state': self.state,
                'failureThreshold': self.failure_threshold,
                'failureRateThreshold': self.failure_rate_threshold,
                'failureRate': self.get_failure_rate(),
                'openTimeout': self.open_timeout,
                'halfOpenMaxRequests': self.half_open_max_requests,
                'halfOpenRequests': self.half_open_requests,
                'failureCount': self.failure_count,
                'successCount': self.success_count,
                'totalRequests': self.total_requests,
                'lastStateChange': self.last_state_change,
                'lastFailureTime': self.last_failure_time,
                'timeUntilReset': max(0, self.open_timeout - (int(time.time() * 1000) - self.last_state_change))
                if self.state == CIRCUIT_STATE['OPEN'] else 0
            }


circuit_breakers = {}
circuit_breakers_lock = threading.Lock()


def sync_with_registry():
    try:
        response = requests.get(f"{REGISTRY_URL}/api/registry/services", timeout=2)
        if response.json().get('success'):
            services = response.json().get('services', {})
            with circuit_breakers_lock:
                for service_name in services.keys():
                    if service_name not in circuit_breakers:
                        circuit_breakers[service_name] = CircuitBreaker(service_name)
                        print(f"[熔断状态机] 初始化熔断器: {service_name}")
    except Exception as e:
        print(f"[熔断状态机] 同步注册中心失败: {str(e)}")


def evaluate_all_circuits():
    with circuit_breakers_lock:
        for breaker in circuit_breakers.values():
            breaker.evaluate_state()


def background_sync():
    while True:
        sync_with_registry()
        time.sleep(5)


def background_evaluate():
    while True:
        evaluate_all_circuits()
        time.sleep(3)


@app.route('/api/circuit/configure', methods=['POST'])
def configure():
    data = request.get_json()
    service_name = data.get('serviceName')

    if not service_name:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName'
        }), 400

    config = {}
    if 'failureThreshold' in data:
        config['failureThreshold'] = data['failureThreshold']
    if 'failureRateThreshold' in data:
        config['failureRateThreshold'] = data['failureRateThreshold']
    if 'openTimeout' in data:
        config['openTimeout'] = data['openTimeout']
    if 'halfOpenMaxRequests' in data:
        config['halfOpenMaxRequests'] = data['halfOpenMaxRequests']
    if 'windowSize' in data:
        config['windowSize'] = data['windowSize']

    with circuit_breakers_lock:
        breaker = CircuitBreaker(service_name, config)
        circuit_breakers[service_name] = breaker

    print(f"[熔断状态机] 配置熔断器: {service_name} {config}")

    return jsonify({
        'success': True,
        'message': '熔断器配置成功',
        'serviceName': service_name,
        'config': breaker.get_state_info()
    })


@app.route('/api/circuit/check', methods=['POST'])
def check():
    data = request.get_json()
    service_name = data.get('serviceName')

    if not service_name:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName'
        }), 400

    with circuit_breakers_lock:
        breaker = circuit_breakers.get(service_name)
        if not breaker:
            breaker = CircuitBreaker(service_name)
            circuit_breakers[service_name] = breaker
            print(f"[熔断状态机] 自动创建熔断器: {service_name}")

    result = breaker.allow_request()

    return jsonify({
        'success': True,
        'allowed': result['allowed'],
        'state': result['state'],
        'serviceName': service_name,
        'message': result['reason']
    })


@app.route('/api/circuit/record', methods=['POST'])
def record():
    data = request.get_json()
    service_name = data.get('serviceName')
    success = data.get('success')

    if not service_name or success is None:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, success'
        }), 400

    with circuit_breakers_lock:
        breaker = circuit_breakers.get(service_name)
        if not breaker:
            breaker = CircuitBreaker(service_name)
            circuit_breakers[service_name] = breaker

    if success:
        breaker.record_success()
    else:
        breaker.record_failure()

    return jsonify({
        'success': True,
        'serviceName': service_name,
        'recorded': 'success' if success else 'failure',
        'currentState': breaker.state
    })


@app.route('/api/circuit/state', methods=['GET'])
def get_state():
    service_name = request.args.get('serviceName')

    if not service_name:
        with circuit_breakers_lock:
            all_states = {}
            for name, breaker in circuit_breakers.items():
                all_states[name] = breaker.get_state_info()
        return jsonify({
            'success': True,
            'totalCircuits': len(circuit_breakers),
            'states': all_states
        })

    with circuit_breakers_lock:
        breaker = circuit_breakers.get(service_name)
    if not breaker:
        return jsonify({
            'success': False,
            'error': '未找到该服务的熔断器'
        }), 404

    return jsonify({
        'success': True,
        'serviceName': service_name,
        'state': breaker.get_state_info()
    })


@app.route('/api/circuit/reset', methods=['POST'])
def reset():
    data = request.get_json()
    service_name = data.get('serviceName')

    if not service_name:
        with circuit_breakers_lock:
            circuit_breakers.clear()
        print('[熔断状态机] 已重置所有熔断器')
        return jsonify({
            'success': True,
            'message': '所有熔断器已重置'
        })

    with circuit_breakers_lock:
        if service_name in circuit_breakers:
            circuit_breakers[service_name] = CircuitBreaker(service_name)
            print(f"[熔断状态机] 已重置熔断器: {service_name}")
            return jsonify({
                'success': True,
                'message': f'熔断器 {service_name} 已重置'
            })

    return jsonify({
        'success': False,
        'error': '未找到该服务的熔断器'
    }), 404


@app.route('/api/circuit/health', methods=['GET'])
def health():
    return jsonify({
        'success': True,
        'service': 'circuit-breaker-service',
        'port': PORT,
        'status': 'running',
        'timestamp': int(time.time() * 1000)
    })


if __name__ == '__main__':
    threading.Thread(target=background_sync, daemon=True).start()
    threading.Thread(target=background_evaluate, daemon=True).start()
    sync_with_registry()
    print(f"[熔断状态机] 服务启动成功，监听端口: {PORT}")
    print(f"[熔断状态机] 健康检查: http://localhost:{PORT}/api/circuit/health")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True, processes=1)
