# 第 6 题：滑动窗口限流怎么实现

题目要求明确：按 userId 限流，任意连续 windowSeconds 秒内最多 limit 次，必须是滑动窗口，并且不活跃用户的数据需要清理。

## 单机实现

单机最直接的做法是给每个用户维护一个时间戳队列。

```python
class SlidingWindowLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._logs = {}
        self._last_seen = {}

    def allow(self, user_id):
        now = time.monotonic()
        cutoff = now - self.window

        log = self._logs.setdefault(user_id, deque())
        while log and log[0] <= cutoff:
            log.popleft()

        self._last_seen[user_id] = now
        if len(log) >= self.limit:
            return False
        log.append(now)
        return True
```

每次请求先把窗口外的旧时间戳弹出，再检查队列长度。

几个需要注意的点：

时间用 monotonic，不用 time.time()。系统时间被 NTP 回拨时，窗口判断会整体出错。

需要加锁。单机可以用一把全局锁，也可以按用户分片加锁。不加锁时，判断长度和追加这两个操作之间会被其他线程插入，并发量大时无法正确限流。

## 不活跃用户的清理

两个机制同时使用。

惰性清理：用户下次访问时顺便弹出过期时间戳，这个没有额外成本。

后台扫描：定时任务遍历，把长时间未访问的用户整个删除。

```python
def cleanup(self, now):
    expired = [u for u, t in self._last_seen.items()
               if now - t > self.window * 2]
    for user_id in expired:
        self._logs.pop(user_id, None)
        self._last_seen.pop(user_id, None)
```

为什么两个都需要：

只有惰性清理时，一批只访问一次的新用户数据会一直留在内存里，因为没有后续访问触发清理。

只有后台扫描时，扫描周期内的内存占用仍然存在。

两者结合，内存有上界，请求路径上也不会增加负担。

## 复杂度

单次 allow 的时间取决于弹出多少个过期时间戳，均摊为 O(1)，因为每个时间戳只进队出队一次。

空间上每个活跃用户最多 limit 个时间戳。

后台清理扫描一遍是 O(用户数)。

## 四种限流器的适用场景

固定窗口实现最简单，但窗口交界处可能放过双倍流量。例如一分钟限 100 次，用户在 0:59 发起 100 次，1:00 再发起 100 次，实际两秒内通过了 200 次。适合要求不高的粗粒度保护。

滑动窗口最精确，任意连续窗口都能卡住。代价是内存随请求量增长。适合按用户计算的精确配额，例如登录、下单。

令牌桶允许突发。桶里预存令牌，使用时扣减，用完后等待补充。适合允许短时突发的接口，例如上传。

漏桶以恒定速率输出，不允许突发。适合保护下游固定处理能力的场景，例如调用第三方老接口。

题目要求任意连续 N 秒最多 M 次，固定窗口不满足，令牌桶也不满足，只能使用滑动窗口。

## Redis 集群版

单机方案在多机环境下不成立，因为每台机器各存各的。计数需要放到 Redis。

### key 设计

```
rl:{userId}    ZSET    member 是请求唯一 ID，score 是毫秒时间戳
```

使用 ZSET 而不是 LIST，是因为需要按时间范围删除。ZREMRANGEBYSCORE 一条命令就能删除所有过期记录，比在 LIST 上逐个弹出高效得多。

### 原子操作

三步必须一起完成，中间不能被其他请求插入，所以用 Lua。

```lua
-- KEYS[1] = rl:{userId}
-- ARGV[1] = 当前毫秒, ARGV[2] = 窗口毫秒数, ARGV[3] = limit, ARGV[4] = 请求唯一 ID
redis.call("ZREMRANGEBYSCORE", KEYS[1], 0, ARGV[1] - ARGV[2])
local count = redis.call("ZCARD", KEYS[1])
if count >= tonumber(ARGV[3]) then
    return 0
end
redis.call("ZADD", KEYS[1], ARGV[1], ARGV[4])
redis.call("PEXPIRE", KEYS[1], tonumber(ARGV[2]) * 2)
return 1
```

删除过期记录、统计数量、写入新记录在一个脚本里完成。Lua 是单线程执行的，不存在竞争。

### 需要注意的地方

时间源最好使用 Redis 服务端的，或者保证所有客户端 NTP 对齐。多机时间相差几十毫秒，窗口边界就会偏移。

member 必须唯一。同一毫秒的两个请求如果 member 相同，ZADD 会覆盖，等于少算一次。使用 UUID 或"时间戳-序列号"。

TTL 一定要设置。即使后续没有请求，key 也会自动过期，这是清理冷用户的最后保障。

热点用户会集中打到单个 key。用户量大且集中时，可以按用户再分片，总量取各分片之和。代价是需要在同一个脚本中读取多个 key，复杂度上升。

多机部署时，同一用户的多个分片 key 必须落在同一节点。Redis Cluster 使用 {userId} 这种 hash tag 可以保证这一点。

## 小结

单机使用 deque 记录时间戳，惰性清理加后台扫描控制内存。集群使用 ZSET 加 Lua 保证原子性，TTL 兜底冷用户，时间统一从 Redis 端获取。
