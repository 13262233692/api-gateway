import time
import threading
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
PORT = 8002
REGISTRY_URL = 'http://localhost:8001'


class TokenBucket:
    def __init__(self, capacity, refill_rate, refill_interval=1000):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self.last_refill = int(time.time() * 1000)
        self.lock = threading.Lock()

    def refill(self):
        now = int(time.time() * 1000)
        elapsed = now - self.last_refill
        if elapsed >= self.refill_interval:
            tokens_to_add = (elapsed // self.refill_interval) * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now

    def try_consume(self, tokens=1):
        with self.lock:
            self.refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return {'allowed': True, 'remainingTokens': self.tokens, 'capacity': self.capacity}
            return {'allowed': False, 'remainingTokens': self.tokens, 'capacity': self.capacity}

    def get_state(self):
        with self.lock:
            return {
                'tokens': self.tokens,
                'capacity': self.capacity,
                'refillRate': self.refill_rate,
                'refillInterval': self.refill_interval,
                'lastRefill': self.last_refill
            }


rate_limits = {}
rate_limits_lock = threading.Lock()
DEFAULT_CAPACITY = 100
DEFAULT_REFILL_RATE = 10


def get_bucket_key(service_name, endpoint='default'):
    return f"{service_name}:{endpoint}"


def sync_with_registry():
    try:
        response = requests.get(f"{REGISTRY_URL}/api/registry/services", timeout=2)
        if response.json().get('success'):
            services = response.json().get('services', {})
            with rate_limits_lock:
                for service_name in services.keys():
                    key = get_bucket_key(service_name)
                    if key not in rate_limits:
                        rate_limits[key] = TokenBucket(DEFAULT_CAPACITY, DEFAULT_REFILL_RATE)
                        print(f"[限流决策器] 初始化限流器: {service_name}")
    except Exception as e:
        print(f"[限流决策器] 同步注册中心失败: {str(e)}")


def background_sync():
    while True:
        sync_with_registry()
        time.sleep(5)


@app.route('/api/ratelimit/configure', methods=['POST'])
def configure():
    data = request.get_json()
    service_name = data.get('serviceName')
    endpoint = data.get('endpoint', 'default')
    capacity = data.get('capacity')
    refill_rate = data.get('refillRate')
    refill_interval = data.get('refillInterval', 1000)

    if not service_name or not capacity or not refill_rate:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, capacity, refillRate'
        }), 400

    key = get_bucket_key(service_name, endpoint)
    with rate_limits_lock:
        rate_limits[key] = TokenBucket(capacity, refill_rate, refill_interval)

    print(f"[限流决策器] 配置限流器: {key} [容量:{capacity}, 速率:{refill_rate}/{refill_interval}ms]")

    return jsonify({
        'success': True,
        'message': '限流规则配置成功',
        'serviceName': service_name,
        'endpoint': endpoint,
        'config': {'capacity': capacity, 'refillRate': refill_rate, 'refillInterval': refill_interval}
    })


@app.route('/api/ratelimit/check', methods=['POST'])
def check():
    data = request.get_json()
    service_name = data.get('serviceName')
    endpoint = data.get('endpoint', 'default')
    tokens = data.get('tokens', 1)

    if not service_name:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName'
        }), 400

    key = get_bucket_key(service_name, endpoint)
    with rate_limits_lock:
        bucket = rate_limits.get(key)
        if not bucket:
            bucket = TokenBucket(DEFAULT_CAPACITY, DEFAULT_REFILL_RATE)
            rate_limits[key] = bucket
            print(f"[限流决策器] 自动创建默认限流器: {key}")

    result = bucket.try_consume(tokens)

    if not result['allowed']:
        print(f"[限流决策器] 请求被限流: {key}")

    return jsonify({
        'success': True,
        'allowed': result['allowed'],
        'serviceName': service_name,
        'endpoint': endpoint,
        'remainingTokens': result['remainingTokens'],
        'capacity': result['capacity'],
        'message': '请求允许通过' if result['allowed'] else '请求被限流，请稍后重试'
    })


@app.route('/api/ratelimit/state', methods=['GET'])
def get_state():
    service_name = request.args.get('serviceName')
    endpoint = request.args.get('endpoint', 'default')

    if not service_name:
        with rate_limits_lock:
            all_states = {}
            for key, bucket in rate_limits.items():
                all_states[key] = bucket.get_state()
        return jsonify({
            'success': True,
            'totalBuckets': len(rate_limits),
            'states': all_states
        })

    key = get_bucket_key(service_name, endpoint)
    with rate_limits_lock:
        bucket = rate_limits.get(key)

    if not bucket:
        return jsonify({
            'success': False,
            'error': '未找到该服务的限流配置'
        }), 404

    return jsonify({
        'success': True,
        'serviceName': service_name,
        'endpoint': endpoint,
        'state': bucket.get_state()
    })


@app.route('/api/ratelimit/reset', methods=['POST'])
def reset():
    data = request.get_json()
    service_name = data.get('serviceName')
    endpoint = data.get('endpoint', 'default')

    if not service_name:
        with rate_limits_lock:
            rate_limits.clear()
        print('[限流决策器] 已重置所有限流器')
        return jsonify({
            'success': True,
            'message': '所有限流器已重置'
        })

    key = get_bucket_key(service_name, endpoint)
    with rate_limits_lock:
        if key in rate_limits:
            del rate_limits[key]
            print(f"[限流决策器] 已重置限流器: {key}")
            return jsonify({
                'success': True,
                'message': f'限流器 {key} 已重置'
            })

    return jsonify({
        'success': False,
        'error': '未找到该服务的限流配置'
    }), 404


@app.route('/api/ratelimit/health', methods=['GET'])
def health():
    return jsonify({
        'success': True,
        'service': 'rate-limiter-service',
        'port': PORT,
        'status': 'running',
        'timestamp': int(time.time() * 1000)
    })


if __name__ == '__main__':
    sync_thread = threading.Thread(target=background_sync, daemon=True)
    sync_thread.start()
    sync_with_registry()
    print(f"[限流决策器] 服务启动成功，监听端口: {PORT}")
    print(f"[限流决策器] 健康检查: http://localhost:{PORT}/api/ratelimit/health")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True, processes=1)
