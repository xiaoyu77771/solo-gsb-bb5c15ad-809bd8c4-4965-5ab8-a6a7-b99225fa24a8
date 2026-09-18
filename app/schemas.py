"""请求/响应数据模型。"""

from pydantic import BaseModel, Field, model_validator


class CandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="候选人名称")
    weight: float = Field(gt=0, description="权重，必须为正数")


class LotteryCreate(BaseModel):
    title: str = Field(default="评审席位抽签", max_length=200)
    seat_count: int = Field(gt=0, description="席位数量")
    candidates: list[CandidateIn] = Field(min_length=1, description="候选人及权重")

    @model_validator(mode="after")
    def check_candidates(self):
        if self.seat_count > len(self.candidates):
            raise ValueError("席位数不能大于候选人数")
        names = [c.name for c in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("候选人名称不能重复")
        return self


class ExecuteRequest(BaseModel):
    nonce: str = Field(min_length=1, max_length=256, description="调用方提供的随机 nonce")


class VerifyRequest(BaseModel):
    """校验请求。两者均可选：缺省时使用服务端已揭示/已记录的值。"""

    seed: str | None = Field(default=None, description="已揭示的种子")
    nonce: str | None = Field(default=None, description="执行时使用的 nonce")
