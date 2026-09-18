# 评审席位抽签服务

基于 **commit-reveal** 方案的评审席位分配服务：创建抽签时服务端生成秘密种子并仅公开其
SHA-256 承诺；执行时结合调用方提供的 nonce，按权重**无放回**抽出席位并固化顺序；抽签结束
后揭示种子，任何人都可重放算法独立校验承诺、nonce 与结果的一致性。

技术栈：FastAPI + SQLite + Docker。

## 快速开始

```bash
docker compose up --build
```

服务启动后访问：

- API 文档（Swagger UI）：http://localhost:8000/docs
- OpenAPI 规范：http://localhost:8000/openapi.json

## 抽签流程

```
创建(提交候选人/席位/权重) ──► 返回 SHA-256 承诺（种子保密）
        │
执行(提交 nonce) ──► 按权重无放回抽样，固化席位顺序，仅可执行一次
        │
揭示 ──► 公开秘密种子
        │
校验 ──► 重放算法，核对承诺 / nonce / 结果
```

### 1. 创建抽签

```bash
curl -X POST http://localhost:8000/lotteries \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "2026 年度评审席位",
    "seat_count": 2,
    "candidates": [
      {"name": "甲", "weight": 1},
      {"name": "乙", "weight": 2},
      {"name": "丙", "weight": 3},
      {"name": "丁", "weight": 4}
    ]
  }'
```

响应中包含 `id` 与 `commitment`（`SHA-256(seed)`），**不包含种子**。

### 2. 执行抽签

```bash
curl -X POST http://localhost:8000/lotteries/{id}/execute \
  -H 'Content-Type: application/json' \
  -d '{"nonce": "panel-2026-09-18"}'
```

返回固定位次的当选名单 `result`。同一抽签仅可执行一次（重复执行返回 409）。

### 3. 揭示种子

```bash
curl -X POST http://localhost:8000/lotteries/{id}/reveal
```

### 4. 校验

```bash
# 使用服务端已揭示的种子校验
curl -X POST http://localhost:8000/lotteries/{id}/verify

# 或外部方凭 (seed, nonce) 独立校验
curl -X POST http://localhost:8000/lotteries/{id}/verify \
  -H 'Content-Type: application/json' \
  -d '{"seed": "<已揭示的种子>", "nonce": "panel-2026-09-18"}'
```

响应示例：

```json
{
  "valid": true,
  "checks": {"commitment": true, "nonce": true, "result": true},
  "expected_result": ["丙", "丁"],
  "recorded_result": ["丙", "丁"]
}
```

## 公平性设计

- **承诺**：创建时生成 256 位随机种子，仅公开 `SHA-256(seed)`。服务端无法在承诺后更换种子，
  调用方也无法预知种子。
- **执行**：以 `SHA-256(seed:nonce)` 派生确定性随机源。nonce 由调用方在执行时提供，
  双方都无法单独操纵结果。
- **抽样算法**：Efraimidis–Spirakis 加权无放回抽样——为每位候选人计算
  `key = u^(1/weight)`（`u` 为均匀随机数），按 key 降序排列，前 N 名获得席位，
  排名即固化的席位顺序。候选人被选中的概率严格正比于权重。
- **可校验**：相同 `(seed, nonce, candidates, seat_count)` 必然重放出相同结果，
  校验接口逐项核对承诺、nonce 与结果。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/lotteries` | 创建抽签，返回承诺 |
| GET | `/lotteries` | 列出全部抽签 |
| GET | `/lotteries/{id}` | 查询详情（揭示后含种子） |
| POST | `/lotteries/{id}/execute` | 提交 nonce 并执行 |
| POST | `/lotteries/{id}/reveal` | 揭示种子 |
| POST | `/lotteries/{id}/verify` | 重放校验 |

状态机：`pending` → `executed` → `revealed`，非法流转返回 409。

## 本地开发与测试

```bash
pip install -r requirements.txt pytest httpx
uvicorn app.main:app --reload          # 开发模式启动
pytest tests/                          # 运行测试
```

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_PATH` | `./lottery.db`（容器内 `/data/lottery.db`） | SQLite 数据库路径 |

Compose 通过命名卷 `lottery-data` 持久化抽签记录，容器重建后数据不丢失。
