import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.store import store
from services.diagnostic_tree_builder import build_diagnostic_trees
from schemas.schemas import DiagnosticTreeResponse

router = APIRouter()


class DiagnoseScenarioRequest(BaseModel):
    scenario_name: str
    convergence_alarm: str
    symptoms: list[dict]    # [{name, trigger_alarms: [str], rule_count, avg_lift}]
    rule_count: int
    avg_lift: float
    top_rules: list[dict]   # top 10 rules with full metrics


class DiagnoseScenarioResponse(BaseModel):
    diagnosis: str
    prompt: str


def _build_diagnose_prompt(req: DiagnoseScenarioRequest) -> str:
    symptoms_text = ""
    for s in req.symptoms[:10]:
        triggers = "、".join(s.get("trigger_alarms", [])[:5])
        symptoms_text += (
            f"- 中间症状「{s['name']}」：触发告警包括 {triggers}，"
            f"关联 {s.get('rule_count', 0)} 条规则，"
            f"平均提升度 {s.get('avg_lift', 0):.2f}\n"
        )

    rules_text = ""
    for r in req.top_rules[:10]:
        ants = "、".join(r.get("antecedent_names", []))
        cons = "、".join(r.get("consequent_names", []))
        rules_text += (
            f"- {ants} → {cons} "
            f"(支持度={r.get('support', 0):.4f}, 置信度={r.get('confidence', 0):.4f}, "
            f"提升度={r.get('lift', 0):.2f}, 时序置信度={r.get('temporal_confidence', 0):.4f})\n"
        )

    return f"""你是一名铁路通信网络告警分析专家。请根据以下诊断树场景的数据，给出专业诊断报告，字数在 500 字以内。

【场景信息】
- 收敛告警（根因假设）：{req.convergence_alarm}
- 场景规则总数：{req.rule_count}
- 场景平均提升度：{req.avg_lift:.2f}

【症状分支与触发条件】
{symptoms_text}

【Top 10 规则详情】
{rules_text}

请从以下角度分析：
1. 该收敛告警作为根因的合理性 —— 从症状覆盖面和时序方向评估
2. 关键故障链路 —— 哪些症状-触发组合的置信度和提升度最高，指示了什么
3. 诊断建议 —— 实操排查步骤和优先检查点
4. 规则质量评价 —— 该场景的关联规则是否可靠，时序置信度是否支持因果推断

要求：专业、简洁、面向通信运维人员。直接给出诊断结论，不要客套话。"""


def _call_llm(prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 ANTHROPIC_AUTH_TOKEN 环境变量")

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    try:
        from anthropic import Anthropic
        from anthropic.types import TextBlock

        client = Anthropic(api_key=api_key, base_url=base_url)
        model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5")
        model = model if model else "claude-haiku-4-5"

        message = client.messages.create(
            model=model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "disabled"},
        )
        for block in message.content:
            if isinstance(block, TextBlock):
                return block.text
        for block in message.content:
            if hasattr(block, 'text') and 'ThinkingBlock' not in str(type(block)):
                return getattr(block, 'text')
        return "大模型未返回文本内容，请重试。"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM调用失败: {str(e)}")


@router.get("/diagnostic-trees", response_model=DiagnosticTreeResponse)
async def get_diagnostic_trees(network_manager: str = "all"):
    if network_manager and network_manager != "all":
        result = store.get_result(network_manager)
    else:
        result = store.get_result()
    if not result:
        raise HTTPException(status_code=400, detail="请先运行FP-Growth计算")

    # Return cached trees if available
    cached = store.get_diagnostic_trees()
    if cached:
        return DiagnosticTreeResponse(
            scenarios=cached,
            total_rules_analyzed=sum(s.get("rule_count", 0) for s in cached),
            cached=True,
        )

    all_rules = result["round1"]["rules"] + result["round2"]["rules"]

    seen: dict[tuple, dict] = {}
    for r in all_rules:
        key = (tuple(r["antecedent"]), tuple(r["consequent"]))
        if key not in seen or r["lift"] > seen[key]["lift"]:
            seen[key] = r
    unique_rules = list(seen.values())

    if not unique_rules:
        return DiagnosticTreeResponse(scenarios=[], total_rules_analyzed=0)

    scenarios = build_diagnostic_trees(unique_rules)
    store.set_diagnostic_trees(scenarios)

    # Build alarm name → description mapping
    alarms = store.get_alarms()
    name_to_desc: dict[str, str] = {}
    alarm_to_nes: dict[str, set[str]] = {}
    for a in alarms:
        ne = a.get("网元", "")
        name = a.get("告警名称", "")
        desc = a.get("告警描述", "")
        if ne and name:
            alarm_to_nes.setdefault(name, set()).add(ne)
            # Also index by display name for later lookup
            display = f"{name}({desc})" if desc and desc != name and len(desc) >= 2 else name
            alarm_to_nes.setdefault(display, set()).add(ne)
        if name and desc and name not in name_to_desc:
            name_to_desc[name] = desc

    # Alarm categorization
    CATEGORY_RULES = [
        ("物理光口故障", ["LOS", "信号丢失", "光物理", "接收线路侧信号", "光模块", "光功率", "光口"]),
        ("SDH远端缺陷", ["RDI", "远端接收失效", "远端缺陷"]),
        ("帧同步异常", ["LOF", "帧丢失", "帧失步", "定帧", "OOF"]),
        ("LCAS虚级联故障", ["LCAS", "虚级联", "VCAT", "VCG"]),
        ("时钟同步异常", ["时钟", "SYNC", "定时"]),
        ("2M/PDH线路故障", ["2M", "PDH", "E1", "AIS", "T_ALOS"]),
        ("以太网端口故障", ["以太", "ETH", "网口", "VCG(EOS)"]),
        ("通道层故障", ["VC12", "VC4", "VC3", "TU", "通道", "AU4", "指针丢失", "踪迹", "UNEQ", "SLM"]),
        ("复用段故障", ["复用段", "MS_", "MS ", "B2"]),
        ("再生段故障", ["再生段", "RS_", "RS ", "B1"]),
        ("性能越限", ["越限", "误码越限", "PM", "UAS", "ES", "SES", "BBE"]),
        ("OPU/客户侧故障", ["OPU", "客户信号", "ODU"]),
    ]

    def get_category(alarm_name: str) -> str:
        desc = name_to_desc.get(alarm_name, alarm_name)
        combined = f"{alarm_name} {desc}"
        for cat, keywords in CATEGORY_RULES:
            for kw in keywords:
                if kw in combined:
                    return cat
        return "其他故障"

    def get_display_name(alarm_name: str) -> str:
        """Return human-readable name: description if available, else alarm name."""
        desc = name_to_desc.get(alarm_name, "")
        if desc and desc != alarm_name and len(desc) >= 2:
            return f"{alarm_name}({desc})"
        return alarm_name

    # Enrich scenarios with readable names and categories
    for s in scenarios:
        # Rename scenario
        raw_name = s["scenario_name"]
        s["scenario_name"] = get_display_name(raw_name)
        s["convergence_alarm"] = get_display_name(raw_name)

        # Add category
        s["category"] = get_category(raw_name)

        # Recursively rename tree nodes
        def rename_node(node: dict):
            node["name"] = get_display_name(node["name"])
            node["category"] = get_category(node["name"])
            for child in node.get("children", []):
                rename_node(child)
        rename_node(s["root"])

        # Rename rules' alarm names
        for r in s["rules"]:
            r["antecedent_names"] = [get_display_name(n) for n in r["antecedent_names"]]
            r["consequent_names"] = [get_display_name(n) for n in r["consequent_names"]]

    # Continue with related NEs enrichment (reuse alarm_to_nes from above)
    for s in scenarios:
        scenario_alarms: set[str] = set()
        for r in s["rules"]:
            scenario_alarms.update(r.get("antecedent_names", []))
            scenario_alarms.update(r.get("consequent_names", []))
        related = set()
        for alarm_name in scenario_alarms:
            if alarm_name in alarm_to_nes:
                related.update(alarm_to_nes[alarm_name])
        s["related_nes"] = sorted(related)[:50]  # limit to top 50 NEs

    return DiagnosticTreeResponse(
        scenarios=scenarios,
        total_rules_analyzed=len(unique_rules),
    )


@router.post("/diagnose-scenario", response_model=DiagnoseScenarioResponse)
async def diagnose_scenario(req: DiagnoseScenarioRequest):
    prompt = _build_diagnose_prompt(req)
    diagnosis = _call_llm(prompt)
    return DiagnoseScenarioResponse(diagnosis=diagnosis, prompt=prompt)


class WorkOrderGuidanceRequest(BaseModel):
    scenario_name: str
    convergence_alarm: str
    priority: str
    category: str = ""
    triggered_alarms: list[dict] = []
    matched_rule_count: int = 0
    avg_lift: float = 0


class WorkOrderGuidanceResponse(BaseModel):
    guidance: str


@router.post("/work-order-guidance", response_model=WorkOrderGuidanceResponse)
async def work_order_guidance(req: WorkOrderGuidanceRequest):
    alarms_text = ""
    for a in req.triggered_alarms[:20]:
        alarms_text += f"- {a.get('ne','')}: {a.get('name','')} [{a.get('severity','')}] {a.get('time','')}\n"

    prompt = f"""你是一名铁路通信网络运维专家。请根据以下工单信息，给出面向一线运维人员的实操指导，字数在 400 字以内。

【工单信息】
- 诊断场景：{req.scenario_name}
- 收敛告警：{req.convergence_alarm}
- 优先级：{req.priority}
- 故障分类：{req.category}
- 命中规则数：{req.matched_rule_count}
- 平均提升度：{req.avg_lift:.1f}

【触发告警列表】
{alarms_text}

请从以下角度给出指导：
1. 故障判断 —— 根据告警组合，最可能的故障类型和位置
2. 排查步骤 —— 按优先级列出 3-5 步实操动作（具体到设备、端口、命令）
3. 安全提醒 —— 是否需要申请天窗、是否需要备件、是否影响业务
4. 升级建议 —— 什么情况下需要升级到二线/厂家

要求：语言简洁、步骤可执行、面向一线通信工。不客套、不废话。"""

    guidance = _call_llm(prompt)
    return WorkOrderGuidanceResponse(guidance=guidance)
