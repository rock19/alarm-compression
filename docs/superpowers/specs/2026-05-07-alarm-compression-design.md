# 铁路通信承载网告警压缩 — 设计方案

## 概述

针对铁路通信承载网（5G-R）综合网管导出的历史告警数据，使用 FP-Growth 算法对同网元、同时段内发生的告警进行关联规则挖掘，实现告警压缩。并提供 Web 仪表盘对挖掘结果进行可视化展示和交互分析。

**数据来源**：华为设备历史告警 Excel（33 列、约 2.6 万条、51 网元、220 种告警类型，时间跨度约 2.5 个月）

---

## 架构

```
React Frontend (TypeScript + ECharts)
       │  HTTP REST
FastAPI Backend (Python)
       │
┌──────┴──────────────────────────────┐
│  Service Layer                       │
│  data_loader │ preprocessor          │
│  fpgrowth_engine │ topology_builder  │
└─────────────────────────────────────┘
```

- **前端**：React + TypeScript + ECharts，四个仪表盘页面
- **后端**：FastAPI REST API，JSON 通信，核心算法封装为独立 service 模块

---

## 数据预处理流水线

1. **格式校验与清洗**：检查 33 列完整性，时间格式解析，空值处理
2. **时间窗口分组**：按 `网元` 分组，在组内按可配置时间窗口（time_window_seconds）切片
3. **事务编码**：每个时间窗口内同一网元产生的告警名称集合 → 一条事务，告警名称映射为整数 ID
4. **过滤**：支持按告警级别、铁路线、时间范围在预处理阶段过滤

---

## FP-Growth 算法与分层挖掘

使用 `mlxtend.fpgrowth` 实现。

### 分层策略

1. **第一轮**：全量数据挖掘，min_support、min_confidence 可配置
2. **高频过滤**：过滤掉包含高频告警的项集（阈值 threshold_ratio 可配置，如 0.2），高频告警定义：在事务中出现频率超过阈值的告警名称
3. **第二轮**：对过滤后数据重新挖掘

### 输出

- 频繁项集：项集内容、支持度、涉及网元数、涉及时间窗口数
- 关联规则：前件 → 后件、置信度、提升度、规则出现时段分布
- 两轮结果并列，前端可切换查看

### 可配置参数

| 参数 | 说明 |
|------|------|
| time_window_seconds | 时间窗口大小（秒） |
| min_support | 最小支持度 |
| min_confidence | 最小置信度 |
| threshold_ratio | 高频过滤阈值 |

---

## 后端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload` | POST | 上传 Excel，返回数据摘要 |
| `/api/fpgrowth` | POST | 执行 FP-Growth 计算 |
| `/api/rules` | GET | 获取关联规则（分页、搜索、排序） |
| `/api/transactions` | GET | 获取规则对应的原始告警明细 |
| `/api/stats` | GET | 告警概览统计 |
| `/api/topology` | GET | 网元拓扑数据 |

---

## 前端仪表盘

### 页面 1：告警概览

- 指标卡（告警总数、网元数、告警类型数）
- 告警级别分布饼图
- 告警频次 Top 20 柱状图
- 时间范围选择器 + 铁路线筛选
- 网元告警热力图

### 页面 2：关联规则

- 参数面板（支持度、置信度、时间窗口滑块）
- 规则表（前件 → 后件 | 支持度 | 置信度 | 提升度）
- 切换标签：全量挖掘 / 分层挖掘
- 点击规则展开告警明细
- 规则搜索、排序

### 页面 3：时序分析

- 告警类型/网元时间趋势折线图
- 告警并发量曲线
- 标注关联规则命中时段

### 页面 4：拓扑视图

- 力导向图，节点 = 网元，边 = 关联强度
- 物理拓扑连线（虚线）叠加逻辑关联连线（实线，粗细 = 强度）
- 点击节点高亮关联告警

---

## 项目结构

```
alarm-compression/
├── backend/
│   ├── main.py
│   ├── api/
│   │   ├── upload.py
│   │   ├── fpgrowth.py
│   │   ├── rules.py
│   │   ├── transactions.py
│   │   ├── stats.py
│   │   └── topology.py
│   ├── services/
│   │   ├── data_loader.py
│   │   ├── preprocessor.py
│   │   ├── fpgrowth_engine.py
│   │   └── topology_builder.py
│   ├── schemas/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Rules.tsx
│   │   │   ├── Timeline.tsx
│   │   │   └── Topology.tsx
│   │   ├── components/
│   │   ├── api/
│   │   └── App.tsx
│   └── package.json
└── docs/
    └── superpowers/specs/
```

---

## 错误处理

- 上传校验：仅 .xlsx、必填列缺失 → 400
- 计算超时：FP-Growth 60s 超时 → 504
- 空结果：给定参数无频繁项集 → 200 + 空列表 + 提示降低阈值
- 前端：API 错误 toast 提示，加载态骨架屏

## 不在范围内

- 实时告警接入
- 用户认证/权限
- 多厂家告警适配（当前仅华为格式）
- 告警自动处置/派单
