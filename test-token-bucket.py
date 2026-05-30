import time
import threading
import sys
sys.path.insert(0, 'd:\\SOLO\\api-gateway')

import importlib.util
spec = importlib.util.spec_from_file_location("rate_limiter_service", "d:\\SOLO\\api-gateway\\rate-limiter-service.py")
rate_limiter_service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rate_limiter_service)
TokenBucket = rate_limiter_service.TokenBucket

def test_single_thread():
    print('=' * 60)
    print('测试 1: 单线程令牌桶算法验证')
    print('=' * 60)
    print()
    
    bucket = TokenBucket(capacity=5, refill_rate=1, refill_interval=10000)
    print(f'初始状态: tokens={bucket.tokens}/{bucket.capacity}')
    print()
    
    print('连续消费 10 个令牌 (间隔 10ms):')
    for i in range(1, 11):
        result = bucket.try_consume(1)
        status = '✓ 通过' if result['allowed'] else '✗ 限流'
        print(f'  第 {i} 次: {status}, remaining={result["remainingTokens"]}')
        time.sleep(0.01)
    
    print()
    print(f'最终状态: tokens={bucket.tokens}/{bucket.capacity}')
    print()

def test_multi_thread():
    print('=' * 60)
    print('测试 2: 多线程并发验证')
    print('=' * 60)
    print()
    
    bucket = TokenBucket(capacity=10, refill_rate=1, refill_interval=10000)
    results = []
    lock = threading.Lock()
    
    def consumer(thread_id):
        for i in range(3):
            result = bucket.try_consume(1)
            with lock:
                results.append((thread_id, i, result['allowed'], result['remainingTokens']))
            time.sleep(0.01)
    
    threads = []
    for i in range(5):
        t = threading.Thread(target=consumer, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    results.sort(key=lambda x: x[1] * 10 + x[0])
    
    allowed_count = sum(1 for r in results if r[2])
    blocked_count = sum(1 for r in results if not r[2])
    
    print('并发消费结果 (15次请求，容量10):')
    for thread_id, req_num, allowed, remaining in results:
        status = '✓ 通过' if allowed else '✗ 限流'
        print(f'  线程{thread_id} 请求{req_num+1}: {status}, remaining={remaining}')
    
    print()
    print(f'总计: 通过 {allowed_count} 个, 限流 {blocked_count} 个')
    print(f'期望: 通过 10 个, 限流 5 个')
    
    if allowed_count == 10 and blocked_count == 5:
        print('✓✓✓ 多线程并发正常！ ✓✓✓')
    else:
        print('✗✗✗ 多线程并发异常！ ✗✗✗')
    print()
    print(f'最终状态: tokens={bucket.tokens}/{bucket.capacity}')
    print()

if __name__ == '__main__':
    test_single_thread()
    test_multi_thread()
    print('=' * 60)
    print('所有测试完成')
    print('=' * 60)
