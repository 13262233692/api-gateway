import time
import requests

BASE_URL = 'http://localhost:8002'

def sleep(ms):
    time.sleep(ms / 1000)

print('=' * 60)
print('测试: 令牌桶限流功能验证')
print('=' * 60)
print()

service_name = 'test-service'
endpoint = 'test-endpoint'

# 重置
print('1. 重置所有限流器...')
response = requests.post(f"{BASE_URL}/api/ratelimit/reset", json={}, timeout=3)
print(f"   ✓ {response.json()['message']}")
print()

# 配置严格的限流参数: 容量=5，每10秒补充1个令牌
print('2. 配置限流器 (容量=5, 速率=1/10秒)...')
response = requests.post(
    f"{BASE_URL}/api/ratelimit/configure",
    json={
        'serviceName': service_name,
        'endpoint': endpoint,
        'capacity': 5,
        'refillRate': 1,
        'refillInterval': 10000
    },
    timeout=3
)
config = response.json()['config']
print(f"   ✓ 配置完成: 容量={config['capacity']}, 速率={config['refillRate']}/{config['refillInterval']}ms")
print()

# 查看初始状态
print('3. 初始状态:')
response = requests.get(
    f"{BASE_URL}/api/ratelimit/state",
    params={'serviceName': service_name, 'endpoint': endpoint},
    timeout=3
)
state = response.json()['state']
print(f"   令牌数: {state['tokens']}/{state['capacity']}")
print()

# 连续发送10个请求，间隔10ms（总耗时约100ms，远小于10秒补充间隔）
print('4. 连续发送 10 个请求 (间隔 10ms):')
print('   期望: 前5个通过，后5个被限流')
print()

allowed = 0
blocked = 0

start_time = time.time()

for i in range(1, 11):
    try:
        response = requests.post(
            f"{BASE_URL}/api/ratelimit/check",
            json={'serviceName': service_name, 'endpoint': endpoint, 'tokens': 1},
            timeout=3
        )
        data = response.json()
        if data['allowed']:
            allowed += 1
            print(f"    请求 {i}: ✓ 通过 (剩余令牌: {data['remainingTokens']})")
        else:
            blocked += 1
            print(f"    请求 {i}: ✗ 被限流 (剩余令牌: {data['remainingTokens']})")
    except Exception as e:
        print(f"    请求 {i}: 错误 - {str(e)}")
    sleep(10)

end_time = time.time()
total_time = (end_time - start_time) * 1000

print()
print(f"   结果: 通过 {allowed} 个, 限流 {blocked} 个, 总耗时 {int(total_time)}ms")
print()

# 验证结果
if allowed == 5 and blocked == 5:
    print("   ✓✓✓ 限流功能正常！前5个通过，后5个被限流 ✓✓✓")
else:
    print(f"   ✗✗✗ 限流功能异常！期望通过5个，实际通过{allowed}个 ✗✗✗")
print()

# 查看最终状态
print('5. 最终状态:')
response = requests.get(
    f"{BASE_URL}/api/ratelimit/state",
    params={'serviceName': service_name, 'endpoint': endpoint},
    timeout=3
)
state = response.json()['state']
print(f"   令牌数: {state['tokens']}/{state['capacity']}")
print()

print('=' * 60)
print('测试完成')
print('=' * 60)
