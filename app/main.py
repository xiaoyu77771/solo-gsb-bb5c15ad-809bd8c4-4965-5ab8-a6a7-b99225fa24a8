"""评审席位分配抽签服务 API。"""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException

from . import core, db
from .schemas import ExecuteRequest, LotteryCreate, VerifyRequest


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="评审席位抽签服务",
    description="基于 commit-reveal 的权重抽签：创建时公布种子承诺，执行时结合 nonce "
    "按权重无放回选出席位，揭示后可重放校验。",
    version="1.0.0",
    lifespan=lifespan,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_lottery(lottery_id: str) -> dict[str, Any]:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM lotteries WHERE id = ?", (lottery_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="抽签记录不存在")
    return dict(row)


def _public_view(lottery: dict[str, Any], reveal_seed: bool = False) -> dict[str, Any]:
    """序列化输出：除非已揭示，否则不泄露种子。"""
    view = {
        "id": lottery["id"],
        "title": lottery["title"],
        "seat_count": lottery["seat_count"],
        "candidates": json.loads(lottery["candidates"]),
        "commitment": lottery["commitment"],
        "nonce": lottery["nonce"],
        "status": lottery["status"],
        "result": json.loads(lottery["result"]) if lottery["result"] else None,
        "created_at": lottery["created_at"],
        "executed_at": lottery["executed_at"],
        "revealed_at": lottery["revealed_at"],
    }
    if reveal_seed or lottery["status"] == "revealed":
        view["seed"] = lottery["seed"]
    return view


@app.post("/lotteries", status_code=201, summary="创建抽签")
def create_lottery(payload: LotteryCreate):
    """提交候选人、席位数与权重。服务端生成秘密种子，仅返回其 SHA-256 承诺。"""
    lottery_id = uuid.uuid4().hex
    seed = core.generate_seed()
    commitment = core.commitment_for(seed)
    candidates = [c.model_dump() for c in payload.candidates]
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO lotteries (id, title, seat_count, candidates, seed, commitment,
                                   status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                lottery_id,
                payload.title,
                payload.seat_count,
                json.dumps(candidates, ensure_ascii=False),
                seed,
                commitment,
                _utcnow(),
            ),
        )
    return _public_view(_get_lottery(lottery_id))


@app.get("/lotteries", summary="列出全部抽签")
def list_lotteries():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM lotteries ORDER BY created_at DESC").fetchall()
    return [_public_view(dict(r)) for r in rows]


@app.get("/lotteries/{lottery_id}", summary="查询抽签详情")
def get_lottery(lottery_id: str):
    return _public_view(_get_lottery(lottery_id))


@app.post("/lotteries/{lottery_id}/execute", summary="执行抽签")
def execute_lottery(lottery_id: str, payload: ExecuteRequest):
    """结合调用方 nonce 按权重无放回抽出席位并固化顺序。仅可执行一次。"""
    lottery = _get_lottery(lottery_id)
    if lottery["status"] != "pending":
        raise HTTPException(status_code=409, detail="该抽签已执行，不能重复执行")

    candidates = json.loads(lottery["candidates"])
    result = core.draw(candidates, lottery["seat_count"], lottery["seed"], payload.nonce)

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE lotteries SET nonce = ?, result = ?, status = 'executed', "
            "executed_at = ? WHERE id = ?",
            (payload.nonce, json.dumps(result, ensure_ascii=False), _utcnow(), lottery_id),
        )
    return _public_view(_get_lottery(lottery_id))


@app.post("/lotteries/{lottery_id}/reveal", summary="揭示种子")
def reveal_lottery(lottery_id: str):
    """抽签执行后揭示秘密种子，供公众独立校验。"""
    lottery = _get_lottery(lottery_id)
    if lottery["status"] == "pending":
        raise HTTPException(status_code=409, detail="抽签尚未执行，不能揭示种子")
    if lottery["status"] == "executed":
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE lotteries SET status = 'revealed', revealed_at = ? WHERE id = ?",
                (_utcnow(), lottery_id),
            )
        lottery = _get_lottery(lottery_id)
    return _public_view(lottery, reveal_seed=True)


@app.post("/lotteries/{lottery_id}/verify", summary="校验抽签")
def verify_lottery(lottery_id: str, payload: VerifyRequest | None = None):
    """重放算法，校验承诺、nonce 与结果是否一致。

    种子未在请求中给出时，要求抽签已揭示并使用服务端记录的种子。
    """
    lottery = _get_lottery(lottery_id)
    if lottery["status"] == "pending":
        raise HTTPException(status_code=409, detail="抽签尚未执行，无法校验")

    payload = payload or VerifyRequest()
    seed = payload.seed if payload.seed is not None else lottery["seed"]
    nonce = payload.nonce if payload.nonce is not None else lottery["nonce"]

    if payload.seed is None and lottery["status"] != "revealed":
        raise HTTPException(status_code=409, detail="种子尚未揭示，请在请求中提供种子")

    checks = {
        "commitment": core.commitment_for(seed) == lottery["commitment"],
        "nonce": nonce == lottery["nonce"],
    }
    expected_result = None
    if checks["commitment"] and checks["nonce"]:
        candidates = json.loads(lottery["candidates"])
        expected_result = core.draw(candidates, lottery["seat_count"], seed, nonce)
        checks["result"] = expected_result == json.loads(lottery["result"])
    else:
        checks["result"] = False

    return {
        "id": lottery_id,
        "valid": all(checks.values()),
        "checks": checks,
        "expected_result": expected_result,
        "recorded_result": json.loads(lottery["result"]),
    }
