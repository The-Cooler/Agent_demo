# 第 7 题：硬件推流做 ASR，云端怎么接

这题需要按设备的实际使用流程来设计：开机、鉴权、建连、唤醒、推音频、说完一句、收结果、播报。每一步都要有明确的接口。

## 一、设备鉴权

设备出厂时写入三个值：deviceId、sn、secret。云端保存 deviceId 对应的 sn 和 secret 哈希。

设备鉴权请求：

```
POST /v1/device/auth
{ deviceId, sn, timestamp, nonce, signature }

signature = HMAC-SHA256(secret, deviceId + sn + timestamp + nonce)
```

云端校验四步：

deviceId 和 sn 必须与库中记录一致。

时间戳与服务器时间偏差不超过五分钟，防止重放。

nonce 在窗口内未被使用。用 Redis 的 SETNX 记录，五分钟后自动过期。

重算签名，一致才放行。

校验通过后签发短期 token，是一个 JWT，绑定 deviceId 和 sn，一小时有效。设备建立长连接时使用这个 token，不需要每次重新签名。token 过期后重新走一次完整鉴权。

### 一轮说话的标识

我使用这个格式：

```
turn_id = deviceId:sessionSeq:turnSeq
```

sessionSeq 是这次设备会话的序号，从开机到关机算一次。turnSeq 是本次会话中第几轮说话。

不使用 UUID 的原因是：设备重启后 UUID 可能重复，而且断线重连时服务端需要根据 ID 找回之前那一轮的状态。deviceId 加序号天然唯一，也能反查。

## 二、音频上传

### 帧格式

```
POST /v1/voice/{turn_id}/chunk
{
  "turn_id": "...",
  "seq": 42,
  "timestamp_ms": 1320,
  "codec": "opus",
  "sample_rate": 16000,
  "channels": 1,
  "is_last": false,
  "payload": "base64..."
}
```

seq 从 0 开始递增，后续去重和排序都依赖它。

is_last 表示设备认为已经说完。但云端不能完全依赖设备判断，需要自己做端点检测，见第 9 题。

编码建议 opus，16k 采样、单声道，带宽小，兼容性好，ASR 厂商普遍支持。

### 乱序、重复、丢包

重复帧处理最简单：按 seq 判断，已处理过的直接丢弃，回一个 ack。

乱序处理：服务端记录 expected_seq。收到的帧大于 expected 时先放入缓冲区等待。超过五帧仍未等到缺失帧，按丢包处理。

少量丢包交给 ASR 的纠错能力处理。连续丢包过多时标记本轮质量差，让 ASR 跳过或重采样。

整段丢失的极端情况会一直等不到 is_last。这时依靠 maxUtteranceMs 强制结束，不能一直等待。

服务端每收到一帧返回一个轻量 ack，只带 seq，设备据此判断哪些帧需要重传。

## 三、断网重连

### 服务端保存状态

```
voice:turn:{turn_id}   Hash  状态、最后收到的 seq、ASR 进度、创建时间
voice:audio:{turn_id}  List  已收到的音频帧，带 TTL
```

### 重连流程

设备使用 token 重新建连，先发送：

```json
{"type": "resume", "turn_id": "...", "last_acked_seq": 42}
```

服务端查询 voice:turn。

如果仍在进行且未超时，返回 `{"type":"resume_ok","from_seq":43}`，设备从 43 继续发送。

如果已结束或超时，返回 `{"type":"turn_expired"}`，设备重新开启一轮。

### 重传范围

设备已发送但未收到 ack 的帧，需要重传。

服务端已 ack 且已送入 ASR 的帧，不重传。

服务端已收到但设备认为未发送成功的帧，按 seq 去重，不再送入 ASR。

已经产生的 ASR 中间结果，不重放。

最关键的一条：对话服务只能收到一次最终文本。

保证方式是使用 turn_id 去重。提交对话服务前先 SETNX dialog:{turn_id}，抢到的才提交，没抢到的跳过。

## 四、并发约束

同一设备不能同时运行两轮 ASR，麦克风只有一个，同时运行在逻辑上就不成立。

```
SETNX voice:active:{deviceId} {turn_id} EX 60
```

获取成功则建立新的一轮。

获取失败说明已有进行中的轮次，返回 409，并把当前 turn_id 告知设备。

设备收到 409 后可以等待，也可以主动发送 cancel 打断旧轮次再开启新的。用户重新唤醒属于后者。

本轮结束时删除 voice:active。

## A. 数据结构

| 存储内容 | 结构 | 关键操作 | 复杂度 |
|---|---|---|---|
| 进行中的轮次 | Redis Hash | 读状态、更新 last_seq | O(1) |
| 音频帧缓冲 | Redis List 或本地内存 | 追加、按序读取 | 追加 O(1)，整体读取 O(N) |
| 去重 seq | Set 或 Bitmap | 判断、写入 | O(1) |
| 活跃轮次锁 | String，SETNX | 获取、释放 | O(1) |
| 乱序缓冲 | 有序字典 | 插入、按序取出 | O(log K)，K 为缓冲窗口大小 |

内存估算：16k opus 大约每秒 4KB，一轮 30 秒约 120KB。一千台设备同时说话约 120MB。因此音频缓冲必须有 TTL 和上限，超限时丢弃最早的帧，同时标记质量下降。

## B. 从首帧到最终文本的服务端流程

```
1. 收到第一帧
   - 校验 token，确认本轮属于该设备
   - SETNX voice:active 获取锁，失败返回 409
   - 创建 voice:turn 记录，状态置为监听

2. 持续收帧
   - 按 seq 去重排序，写入音频缓冲
   - 返回 ack
   - 送入流式 ASR，获取中间结果
   - 端点检测：连续静音达到阈值，或超过最大时长，结束本轮

3. 本轮结束
   - 提交最后一帧给 ASR，获取最终文本
   - SETNX dialog:{turn_id} 去重
   - 提交给对话服务（第 3 题的流式接口）
   - 对话服务返回播报内容
   - 通过 WebSocket 下发设备，状态转为播报中

4. 播报结束
   - 释放 voice:active
   - 状态转为空闲，或自动重新监听（策略见第 9 题）
   - 写审计日志，清理音频缓冲
```

## 小结

设备用 HMAC 签名鉴权，获取短期 token 建立长连接。一轮说话用 turn_id 标识。音频按 seq 去重排序，断线后根据 ack 位置续传，最终文本只识别一次。同一设备用 SETNX 保证同时只有一轮在运行。
