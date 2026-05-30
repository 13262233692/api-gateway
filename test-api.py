import time
import requests

BASE_URLS = {
    'registry': 'http://localhost:8001',
    'rateLimiter': 'http://localhost:8002',
    'circuitBreaker': 'http://localhost:8003',
    'metrics': 'http://localhost:8004'
}


def sleep(ms):
    time.sleep(ms / 1000)


def test_health_checks():
    print('=' * 60)
    print('测试 1: 健康检查')
    print('=' * 60)

    checks = [
        {'name': '注册中心', 'url': f"{BASE_URLS['registry']}/api/registry/health"},
        {'name': '限流决策器', 'url': f"{BASE_URLS['rateLimiter']}/api/ratelimit/health"},
        {'name': '熔断状态机', 'url': f"{BASE_URLS['circuitBreaker']}/api/circuit/health"},
        {'name': '统计收集器', 'url': f"{BASE_URLS['metrics']}/api/metrics/health"}
    ]

    for check in checks:
        try:
            response = requests.get(check['url'], timeout=3)
            print(f"✓ {check['name']}: {response.json()['status']}")
        except Exception as e:
            print(f"✗ {check['name']}: 失败 - {str(e)}")
    print()


def test_service_registry():
    print('=' * 60)
    print('测试 2: 服务注册与发现')
    print('=' * 60)

    test_services = [
        {'serviceName': 'order-service', 'address': '127.0.0.1', 'port': 9001, 'metadata': {'version': '1.0'}},
        {'serviceName': 'payment-service', 'address': '127.0.0.1', 'port': 9002, 'metadata': {'version': '1.0'}},
        {'serviceName': 'user-service', 'address': '127.0.0.1', 'port': 9003, 'metadata': {'version': '2.0'}}
    ]

    registered_instances = []

    for svc in test_services:
        try:
            response = requests.post(f"{BASE_URLS['registry']}/api/registry/register", json=svc, timeout=3)
            print(f"✓ 注册服务: {svc['serviceName']} -> 实例ID: {response.json()['instanceId']}")
            registered_instances.append({**svc, 'instanceId': response.json()['instanceId']})
        except Exception as e:
            print(f"✗ 注册服务失败 {svc['serviceName']}: {str(e)}")

    sleep(1000)

    try:
        response = requests.get(f"{BASE_URLS['registry']}/api/registry/services", timeout=3)
        data = response.json()
        print(f"✓ 查询所有服务: {data['totalServices']} 个服务, {data['totalInstances']} 个实例")
        print('  服务列表:', ', '.join(data['services'].keys()))
    except Exception as e:
        print(f"✗ 查询服务失败: {str(e)}")

    print()
    return registered_instances


def test_rate_limiting():
    print('=' * 60)
    print('测试 3: 令牌桶限流')
    print('=' * 60)

    service_name = 'order-service'
    endpoint = 'createOrder'

    try:
        config_response = requests.post(
            f"{BASE_URLS['rateLimiter']}/api/ratelimit/configure",
            json={
                'serviceName': service_name,
                'endpoint': endpoint,
                'capacity': 10,
                'refillRate': 2,
                'refillInterval': 1000
            },
            timeout=3
        )
        config = config_response.json()['config']
        print(f"✓ 配置限流器: {service_name}/{endpoint}")
        print(f"  配置: 容量={config['capacity']}, 速率={config['refillRate']}/秒")
    except Exception as e:
        print(f"✗ 配置限流器失败: {str(e)}")

    print()
    print('  连续发送 15 个请求测试限流:')

    allowed = 0
    blocked = 0

    for i in range(1, 16):
        try:
            response = requests.post(
                f"{BASE_URLS['rateLimiter']}/api/ratelimit/check",
                json={'serviceName': service_name, 'endpoint': endpoint, 'tokens': 1},
                timeout=3
            )
            data = response.json()
            if data['allowed']:
                allowed += 1
                print(f"    请求 {i}: ✓ 通过 (剩余令牌: {data['remainingTokens']})")
            else:
                blocked += 1
                print(f"    请求 {i}: ✗ 被限流")
        except Exception as e:
            print(f"    请求 {i}: 错误 - {str(e)}")
        sleep(50)

    print()
    print(f"  结果: 通过 {allowed} 个, 限流 {blocked} 个")

    print()
    print('  等待 2 秒让令牌桶补充...')
    sleep(2000)

    try:
        state_response = requests.get(
            f"{BASE_URLS['rateLimiter']}/api/ratelimit/state",
            params={'serviceName': service_name, 'endpoint': endpoint},
            timeout=3
        )
        state = state_response.json()['state']
        print(f"✓ 查询限流状态: 令牌={state['tokens']}/{state['capacity']}")
    except Exception as e:
        print(f"✗ 查询限流状态失败: {str(e)}")

    print()


def test_circuit_breaker():
    print('=' * 60)
    print('测试 4: 熔断器状态机')
    print('=' * 60)

    service_name = 'payment-service'

    try:
        config_response = requests.post(
            f"{BASE_URLS['circuitBreaker']}/api/circuit/configure",
            json={
                'serviceName': service_name,
                'failureThreshold': 3,
                'failureRateThreshold': 0.5,
                'openTimeout': 5000,
                'halfOpenMaxRequests': 2,
                'windowSize': 10000
            },
            timeout=3
        )
        config = config_response.json()['config']
        print(f"✓ 配置熔断器: {service_name}")
        print(f"  配置: 失败阈值={config['failureThreshold']}, 错误率阈值={config['failureRateThreshold'] * 100}%")
    except Exception as e:
        print(f"✗ 配置熔断器失败: {str(e)}")

    print()
    print('  记录 5 次失败请求触发熔断:')

    for i in range(1, 6):
        try:
            requests.post(
                f"{BASE_URLS['metrics']}/api/metrics/record",
                json={
                    'serviceName': service_name,
                    'success': False,
                    'responseTime': int(__import__('random').random() * 100) + 50
                },
                timeout=3
            )

            requests.post(
                f"{BASE_URLS['circuitBreaker']}/api/circuit/record",
                json={'serviceName': service_name, 'success': False},
                timeout=3
            )

            check_response = requests.post(
                f"{BASE_URLS['circuitBreaker']}/api/circuit/check",
                json={'serviceName': service_name},
                timeout=3
            )
            check_data = check_response.json()
            print(f"    请求 {i}: 失败, 熔断器状态: {check_data['state']}, 允许: {check_data['allowed']}")
        except Exception as e:
            print(f"    请求 {i}: 错误 - {str(e)}")
        sleep(200)

    sleep(1000)

    try:
        state_response = requests.get(
            f"{BASE_URLS['circuitBreaker']}/api/circuit/state",
            params={'serviceName': service_name},
            timeout=3
        )
        state = state_response.json()['state']
        print()
        print(f"✓ 查询熔断器状态: {state['state']}")
        print(f"  失败计数: {state['failureCount']}")
        print(f"  错误率: {state['failureRate'] * 100:.2f}%")
        if state['state'] == 'OPEN':
            print(f"  距离重置: {state['timeUntilReset']}ms")
    except Exception as e:
        print(f"✗ 查询熔断器状态失败: {str(e)}")

    print()


def test_metrics():
    print('=' * 60)
    print('测试 5: 统计数据收集')
    print('=' * 60)

    service_name = 'user-service'

    print('  记录 10 个请求 (7 成功, 3 失败):')

    for i in range(1, 11):
        is_success = i not in [3, 6, 9]
        try:
            requests.post(
                f"{BASE_URLS['metrics']}/api/metrics/record",
                json={
                    'serviceName': service_name,
                    'success': is_success,
                    'responseTime': int(__import__('random').random() * 200) + 20,
                    'endpoint': '/api/user/get' if is_success else '/api/user/create'
                },
                timeout=3
            )
            print(f"    请求 {i}: {'✓ 成功' if is_success else '✗ 失败'}")
        except Exception as e:
            print(f"    请求 {i}: 错误 - {str(e)}")
        sleep(100)

    print()

    try:
        metrics_response = requests.get(
            f"{BASE_URLS['metrics']}/api/metrics/service/{service_name}",
            timeout=3
        )
        metrics = metrics_response.json()['metrics']
        print(f"✓ 查询服务统计: {service_name}")
        print(f"  总请求数: {metrics['totalRequests']}")
        print(f"  成功: {metrics['successCount']}, 失败: {metrics['failureCount']}")
        print(f"  错误率: {metrics['errorRate'] * 100:.2f}%")
        print(f"  平均响应时间: {metrics['avgResponseTime']}ms")
        print(f"  QPS: {metrics['requestsPerSecond']}")
    except Exception as e:
        print(f"✗ 查询统计数据失败: {str(e)}")

    print()

    try:
        summary_response = requests.get(
            f"{BASE_URLS['metrics']}/api/metrics/summary",
            timeout=3
        )
        summary = summary_response.json()
        print(f"✓ 全局统计摘要")
        print(f"  服务总数: {summary['totalServices']}")
        print(f"  总请求数: {summary['totalRequests']}")
        print(f"  总体错误率: {summary['overallErrorRate'] * 100:.2f}%")
    except Exception as e:
        print(f"✗ 查询摘要失败: {str(e)}")

    print()


def test_integration():
    print('=' * 60)
    print('测试 6: 端到端集成流程')
    print('=' * 60)

    service_name = 'integration-test-service'

    print('  1. 注册服务...')
    instance_id = None
    try:
        reg_response = requests.post(
            f"{BASE_URLS['registry']}/api/registry/register",
            json={'serviceName': service_name, 'address': '127.0.0.1', 'port': 9100},
            timeout=3
        )
        instance_id = reg_response.json()['instanceId']
        print(f"     ✓ 服务已注册, 实例ID: {instance_id}")
    except Exception as e:
        print(f"     ✗ 注册失败: {str(e)}")
        return

    sleep(5000)

    print('  2. 配置限流和熔断规则...')
    try:
        requests.post(
            f"{BASE_URLS['rateLimiter']}/api/ratelimit/configure",
            json={'serviceName': service_name, 'capacity': 5, 'refillRate': 1},
            timeout=3
        )
        requests.post(
            f"{BASE_URLS['circuitBreaker']}/api/circuit/configure",
            json={'serviceName': service_name, 'failureThreshold': 3, 'failureRateThreshold': 0.5},
            timeout=3
        )
        print('     ✓ 规则配置完成')
    except Exception as e:
        print(f"     ✗ 配置失败: {str(e)}")

    print('  3. 模拟请求流程 (限流检查 -> 处理 -> 统计记录 -> 熔断记录)...')
    for i in range(1, 9):
        try:
            rate_check = requests.post(
                f"{BASE_URLS['rateLimiter']}/api/ratelimit/check",
                json={'serviceName': service_name},
                timeout=3
            )
            if not rate_check.json()['allowed']:
                print(f"     请求 {i}: ✗ 被限流")
                continue

            circuit_check = requests.post(
                f"{BASE_URLS['circuitBreaker']}/api/circuit/check",
                json={'serviceName': service_name},
                timeout=3
            )
            if not circuit_check.json()['allowed']:
                print(f"     请求 {i}: ✗ 被熔断 (状态: {circuit_check.json()['state']})")
                continue

            is_success = i < 5
            response_time = int(__import__('random').random() * 150) + 30

            requests.post(
                f"{BASE_URLS['metrics']}/api/metrics/record",
                json={'serviceName': service_name, 'success': is_success, 'responseTime': response_time},
                timeout=3
            )

            requests.post(
                f"{BASE_URLS['circuitBreaker']}/api/circuit/record",
                json={'serviceName': service_name, 'success': is_success},
                timeout=3
            )

            print(f"     请求 {i}: {'✓ 成功' if is_success else '✗ 失败'} ({response_time}ms) [熔断: {circuit_check.json()['state']}]")
        except Exception as e:
            print(f"     请求 {i}: 错误 - {str(e)}")
        sleep(300)

    print()
    print('  4. 最终状态查询:')

    try:
        rate_state = requests.get(
            f"{BASE_URLS['rateLimiter']}/api/ratelimit/state",
            params={'serviceName': service_name},
            timeout=3
        ).json()['state']

        circuit_state = requests.get(
            f"{BASE_URLS['circuitBreaker']}/api/circuit/state",
            params={'serviceName': service_name},
            timeout=3
        ).json()['state']

        metrics_state = requests.get(
            f"{BASE_URLS['metrics']}/api/metrics/service/{service_name}",
            timeout=3
        ).json()['metrics']

        print(f"     限流: 令牌={rate_state['tokens']}/{rate_state['capacity']}")
        print(f"     熔断: 状态={circuit_state['state']}, 错误率={circuit_state['failureRate'] * 100:.2f}%")
        print(f"     统计: 总请求={metrics_state['totalRequests']}, 错误率={metrics_state['errorRate'] * 100:.2f}%")
    except Exception as e:
        print(f"     查询状态失败: {str(e)}")

    print()


def run_all_tests():
    print()
    print('╔' + '═' * 58 + '╗')
    print('║' + ' ' * 10 + '分布式限流与熔断管理中心 - 综合测试' + ' ' * 10 + '║')
    print('╚' + '═' * 58 + '╝')
    print()

    try:
        test_health_checks()
        test_service_registry()
        test_rate_limiting()
        test_circuit_breaker()
        test_metrics()
        test_integration()

        print('=' * 60)
        print('✓ 所有测试完成！')
        print('=' * 60)
    except Exception as e:
        print(f'测试过程中发生错误: {str(e)}')
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == '__main__':
    run_all_tests()
