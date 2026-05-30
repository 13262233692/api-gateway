import time
import random
import string
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)
PORT = 8001

service_registry = {}
registry_lock = threading.Lock()
SERVICE_TIMEOUT = 30000


def generate_instance_id():
    return f"inst_{int(time.time() * 1000)}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=9))}"


def clean_expired_services():
    now = int(time.time() * 1000)
    with registry_lock:
        expired_services = []
        for service_name, instances in service_registry.items():
            healthy_instances = [
                inst for inst in instances
                if now - inst['lastHeartbeat'] < SERVICE_TIMEOUT
            ]
            if not healthy_instances:
                expired_services.append(service_name)
            else:
                service_registry[service_name] = healthy_instances
        for service_name in expired_services:
            del service_registry[service_name]


@app.route('/api/registry/register', methods=['POST'])
def register():
    data = request.get_json()
    service_name = data.get('serviceName')
    address = data.get('address')
    port = data.get('port')
    metadata = data.get('metadata', {})

    if not service_name or not address or not port:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, address, port'
        }), 400

    instance_id = generate_instance_id()
    service_instance = {
        'instanceId': instance_id,
        'serviceName': service_name,
        'address': address,
        'port': port,
        'metadata': metadata,
        'status': 'healthy',
        'registeredAt': int(time.time() * 1000),
        'lastHeartbeat': int(time.time() * 1000)
    }

    with registry_lock:
        if service_name not in service_registry:
            service_registry[service_name] = []
        service_registry[service_name].append(service_instance)

    print(f"[注册中心] 服务注册: {service_name} [{instance_id}] @ {address}:{port}")

    return jsonify({
        'success': True,
        'instanceId': instance_id,
        'serviceName': service_name,
        'message': '服务注册成功'
    })


@app.route('/api/registry/heartbeat', methods=['POST'])
def heartbeat():
    data = request.get_json()
    service_name = data.get('serviceName')
    instance_id = data.get('instanceId')

    if not service_name or not instance_id:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, instanceId'
        }), 400

    with registry_lock:
        instances = service_registry.get(service_name)
        if not instances:
            return jsonify({
                'success': False,
                'error': '服务不存在'
            }), 404

        instance = next((inst for inst in instances if inst['instanceId'] == instance_id), None)
        if not instance:
            return jsonify({
                'success': False,
                'error': '服务实例不存在'
            }), 404

        instance['lastHeartbeat'] = int(time.time() * 1000)
        instance['status'] = 'healthy'

    return jsonify({
        'success': True,
        'message': '心跳更新成功'
    })


@app.route('/api/registry/unregister', methods=['POST'])
def unregister():
    data = request.get_json()
    service_name = data.get('serviceName')
    instance_id = data.get('instanceId')

    if not service_name or not instance_id:
        return jsonify({
            'success': False,
            'error': '缺少必填字段: serviceName, instanceId'
        }), 400

    with registry_lock:
        instances = service_registry.get(service_name)
        if not instances:
            return jsonify({
                'success': False,
                'error': '服务不存在'
            }), 404

        index = next((i for i, inst in enumerate(instances) if inst['instanceId'] == instance_id), -1)
        if index == -1:
            return jsonify({
                'success': False,
                'error': '服务实例不存在'
            }), 404

        instances.pop(index)
        if not instances:
            del service_registry[service_name]

    print(f"[注册中心] 服务注销: {service_name} [{instance_id}]")

    return jsonify({
        'success': True,
        'message': '服务注销成功'
    })


@app.route('/api/registry/services', methods=['GET'])
def get_all_services():
    clean_expired_services()
    with registry_lock:
        result = {}
        for service_name, instances in service_registry.items():
            result[service_name] = [{
                'instanceId': inst['instanceId'],
                'address': inst['address'],
                'port': inst['port'],
                'metadata': inst['metadata'],
                'status': inst['status']
            } for inst in instances]

        total_instances = sum(len(insts) for insts in service_registry.values())

    return jsonify({
        'success': True,
        'services': result,
        'totalServices': len(service_registry),
        'totalInstances': total_instances
    })


@app.route('/api/registry/services/<service_name>', methods=['GET'])
def get_service(service_name):
    clean_expired_services()
    with registry_lock:
        instances = service_registry.get(service_name)

        if not instances:
            return jsonify({
                'success': False,
                'error': '服务不存在'
            }), 404

        return jsonify({
            'success': True,
            'serviceName': service_name,
            'instances': [{
                'instanceId': inst['instanceId'],
                'address': inst['address'],
                'port': inst['port'],
                'metadata': inst['metadata'],
                'status': inst['status']
            } for inst in instances]
        })


@app.route('/api/registry/health', methods=['GET'])
def health():
    return jsonify({
        'success': True,
        'service': 'registry-service',
        'port': PORT,
        'status': 'running',
        'timestamp': int(time.time() * 1000)
    })


if __name__ == '__main__':
    print(f"[注册中心] 服务启动成功，监听端口: {PORT}")
    print(f"[注册中心] 健康检查: http://localhost:{PORT}/api/registry/health")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False, threaded=True, processes=1)
