from pydantic import BaseModel, Field
from typing import Optional


class FPGrowthRequest(BaseModel):
    time_window_seconds: int = Field(default=300, ge=10, le=3600, description="时间窗口大小(秒)")
    min_support: float = Field(default=0.01, gt=0, le=1.0, description="最小支持度")
    min_confidence: float = Field(default=0.5, gt=0, le=1.0, description="最小置信度")
    threshold_ratio: float = Field(default=0.2, gt=0, le=1.0, description="高频过滤阈值")
    severity_levels: Optional[list[str]] = None
    railway_lines: Optional[list[str]] = None
    network_managers: Optional[list[str]] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None


class RulesQuery(BaseModel):
    round: str = Field(default="all", pattern="^(all|full|filtered)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    search: Optional[str] = None
    sort_by: str = Field(default="lift", pattern="^(lift|confidence|support)$")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")
    min_lift: Optional[float] = Field(default=None, ge=0)


class TransactionQuery(BaseModel):
    rule_index: int = Field(ge=0)
    round: str = Field(default="all", pattern="^(all|full|filtered)$")


class UploadResponse(BaseModel):
    total_records: int
    raw_total: int = 0
    filtered_count: int = 0
    dedup_removed: int = 0
    file_stats: list[dict] = []
    unique_ne: int
    unique_alarm_names: int
    time_min: Optional[str] = None
    time_max: Optional[str] = None
    railway_lines: list[str]
    network_managers: list[str] = []
    severity_levels: list[str]
    sample_alarm_names: list[str]


class FrequentItemsetOut(BaseModel):
    items: list[str]
    support: float


class AssociationRuleOut(BaseModel):
    antecedent: list[str]
    consequent: list[str]
    support: float
    confidence: float
    lift: float
    temporal_confidence: float = 0.0
    temporal_lift: float = 0.0
    directional_support: float = 0.0


class FPGrowthResponse(BaseModel):
    round1: dict = Field(default_factory=dict)
    round2: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)


class RulesResponse(BaseModel):
    rules: list[AssociationRuleOut]
    total: int
    page: int
    page_size: int


class StatsResponse(BaseModel):
    total_alarms: int
    total_nes: int
    total_alarm_types: int
    severity_distribution: dict[str, int]
    top_alarm_names: list[dict]
    top_network_elements: list[dict]
    railway_distribution: dict[str, int]
    network_managers: list[str] = []
    time_range: dict
    time_series: list[dict] = []
    alarm_time_series: dict[str, list[dict]] = {}


class TopologyResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class DiagnosticTreeNode(BaseModel):
    name: str
    children: list["DiagnosticTreeNode"] = []
    metric_value: float | None = None
    node_type: str = "intermediate"
    rule_count: int = 1
    category: str = "其他故障"


class ScenarioRuleSummary(BaseModel):
    antecedent_names: list[str]
    consequent_names: list[str]
    support: float
    confidence: float
    lift: float
    temporal_confidence: float = 0.0
    temporal_lift: float = 0.0


class Scenario(BaseModel):
    scenario_name: str
    convergence_alarm: str
    root: DiagnosticTreeNode
    rule_count: int
    avg_lift: float
    rules: list[ScenarioRuleSummary]
    related_nes: list[str] = []
    category: str = "其他故障"


class DiagnosticTreeResponse(BaseModel):
    scenarios: list[Scenario]
    total_rules_analyzed: int
