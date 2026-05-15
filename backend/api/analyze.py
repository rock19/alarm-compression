import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AnalyzeRuleRequest(BaseModel):
    antecedent: list[str]
    consequent: list[str]
    support: float
    confidence: float
    lift: float
    data_explain: str
    biz_interpret: str


class AnalyzeRuleResponse(BaseModel):
    analysis: str
    prompt: str


def build_prompt(req: AnalyzeRuleRequest) -> str:
    ant = "、".join(req.antecedent)
    con = "、".join(req.consequent)
    return f"""你是一名通信网络告警分析专家。请根据以下关联规则挖掘结果，给出专业分析，字数在500字以内。

【规则数据】
- 前件（触发条件）：{ant}
- 后件（推断结果）：{con}
- 支持度：{req.support:.4f}
- 置信度：{req.confidence:.4f}
- 提升度：{req.lift:.2f}

【算法解释】
{req.data_explain}

【业务初步解析】
{req.biz_interpret}

请从以下角度分析：
1. 该规则在通信网络运维中的实际意义
2. 前件和后件之间可能的因果关系或共现根因
3. 对该规则的告警压缩和运维建议
要求：字数在200字左右，语言专业、简洁。"""


def call_llm(prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 ANTHROPIC_AUTH_TOKEN 环境变量")

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    try:
        from anthropic import Anthropic
        from anthropic.types import TextBlock

        client = Anthropic(api_key=api_key, base_url=base_url)
        model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

        message = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in message.content:
            if isinstance(block, TextBlock):
                return block.text
        # Fallback: try to extract text from any block that has a 'text' attribute
        for block in message.content:
            if hasattr(block, 'text') and not str(type(block)).endswith("ThinkingBlock'>"):
                return getattr(block, 'text')
        return "大模型返回了思考内容但未生成文本回复，请重试。"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM调用失败: {str(e)}")


@router.post("/analyze-rule", response_model=AnalyzeRuleResponse)
async def analyze_rule(req: AnalyzeRuleRequest):
    prompt = build_prompt(req)
    analysis = call_llm(prompt)
    return AnalyzeRuleResponse(analysis=analysis, prompt=prompt)
