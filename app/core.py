"""抽签核心算法：承诺生成与按权重无放回抽样。

采用 commit-reveal 方案：
1. 创建抽签时服务端生成秘密种子，仅公开其 SHA-256 承诺；
2. 执行时以 SHA-256(seed:nonce) 派生确定性随机源；
3. 使用 Efraimidis-Spirakis 算法（key = u^(1/w)）按权重无放回抽样，
   按 key 降序排名，前 N 名即席位，排名顺序固化。
"""

import hashlib
import random
import secrets
from typing import Sequence


def generate_seed() -> str:
    """生成 256 位秘密种子（hex 编码）。"""
    return secrets.token_hex(32)


def commitment_for(seed: str) -> str:
    """计算种子的 SHA-256 承诺。"""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _derive_rng_seed(seed: str, nonce: str) -> int:
    """由秘密种子与调用方 nonce 派生确定性随机源种子。"""
    digest = hashlib.sha256(f"{seed}:{nonce}".encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


def draw(candidates: Sequence[dict], seat_count: int, seed: str, nonce: str) -> list[str]:
    """按权重无放回抽样，返回固定位次的候选人名单。

    candidates: [{"name": str, "weight": float}, ...]，顺序即提交顺序。
    同一 (seed, nonce, candidates, seat_count) 输入必然得到同一输出，可重放校验。
    """
    rng = random.Random(_derive_rng_seed(seed, nonce))
    keyed = []
    for c in candidates:
        # rng.random() ∈ [0,1)，取 1-u 得到 (0,1]，保证 key > 0
        u = 1.0 - rng.random()
        key = u ** (1.0 / c["weight"])
        keyed.append((key, c["name"]))
    keyed.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in keyed[:seat_count]]
