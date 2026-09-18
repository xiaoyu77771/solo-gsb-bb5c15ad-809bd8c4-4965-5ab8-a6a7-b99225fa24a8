"""端到端流程测试：创建 → 执行 → 揭示 → 校验。"""

import os
import tempfile

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    with TestClient(app) as c:
        yield c


def _create(client):
    resp = client.post(
        "/lotteries",
        json={
            "title": "2026 年度评审席位",
            "seat_count": 2,
            "candidates": [
                {"name": "甲", "weight": 1.0},
                {"name": "乙", "weight": 2.0},
                {"name": "丙", "weight": 3.0},
                {"name": "丁", "weight": 4.0},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_full_commit_reveal_flow(client):
    lottery = _create(client)
    lid = lottery["id"]

    # 创建后只暴露承诺，不暴露种子
    assert lottery["status"] == "pending"
    assert "seed" not in lottery
    assert len(lottery["commitment"]) == 64

    # 执行抽签
    resp = client.post(f"/lotteries/{lid}/execute", json={"nonce": "review-2026-09"})
    assert resp.status_code == 200
    executed = resp.json()
    assert executed["status"] == "executed"
    assert len(executed["result"]) == 2
    assert len(set(executed["result"])) == 2  # 无放回
    assert "seed" not in executed

    # 不能重复执行
    resp = client.post(f"/lotteries/{lid}/execute", json={"nonce": "again"})
    assert resp.status_code == 409

    # 揭示种子
    resp = client.post(f"/lotteries/{lid}/reveal")
    assert resp.status_code == 200
    seed = resp.json()["seed"]

    # 校验通过
    resp = client.post(f"/lotteries/{lid}/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["checks"] == {"commitment": True, "nonce": True, "result": True}

    # 外部方可凭 (seed, nonce) 独立校验
    resp = client.post(
        f"/lotteries/{lid}/verify", json={"seed": seed, "nonce": "review-2026-09"}
    )
    assert resp.json()["valid"] is True

    # 篡改 nonce 或种子则校验失败
    resp = client.post(
        f"/lotteries/{lid}/verify", json={"seed": seed, "nonce": "forged"}
    )
    assert resp.json()["valid"] is False
    resp = client.post(f"/lotteries/{lid}/verify", json={"seed": "0" * 64})
    assert resp.json()["valid"] is False


def test_execute_is_deterministic(client):
    """同一 seed+nonce 重放结果一致（通过 verify 的 expected_result 体现）。"""
    lottery = _create(client)
    lid = lottery["id"]
    client.post(f"/lotteries/{lid}/execute", json={"nonce": "n1"})
    client.post(f"/lotteries/{lid}/reveal")
    body = client.post(f"/lotteries/{lid}/verify").json()
    assert body["expected_result"] == body["recorded_result"]


def test_validation(client):
    # 席位多于候选人
    resp = client.post(
        "/lotteries",
        json={
            "seat_count": 3,
            "candidates": [{"name": "甲", "weight": 1}, {"name": "乙", "weight": 1}],
        },
    )
    assert resp.status_code == 422
    # 权重非正
    resp = client.post(
        "/lotteries",
        json={"seat_count": 1, "candidates": [{"name": "甲", "weight": 0}]},
    )
    assert resp.status_code == 422
    # 候选人重名
    resp = client.post(
        "/lotteries",
        json={
            "seat_count": 1,
            "candidates": [{"name": "甲", "weight": 1}, {"name": "甲", "weight": 2}],
        },
    )
    assert resp.status_code == 422


def test_state_transitions(client):
    lottery = _create(client)
    lid = lottery["id"]
    # 未执行不能揭示 / 校验
    assert client.post(f"/lotteries/{lid}/reveal").status_code == 409
    assert client.post(f"/lotteries/{lid}/verify").status_code == 409
    # 不存在
    assert client.get("/lotteries/nonexistent").status_code == 404
