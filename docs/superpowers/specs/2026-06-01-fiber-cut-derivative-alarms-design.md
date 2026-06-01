# 光缆中断衍生告警分离展示 — 设计文档

**日期**: 2026-06-01
**状态**: 已确认

## 背景

当前光缆中断检测已能识别两类告警：
- **光纤告警**：LOS/LOF/MS_AIS/R_LOS/R_LOF/信号丢失/帧丢失等
- **衍生告警**：RDI/AIS/误码/UAS/BBE/CSF/退服/告警指示等

但两类告警混在一起展示，无法区分哪些是直接光纤中断导致的，哪些是间接衍生影响。

## 设计目标

1. 光纤告警和衍生告警在拓扑图、事件卡片中**视觉区分**
2. 命中/未命中告警通过**统计面板链接**弹出查看（页签方式）
3. 以实际数据为准，不虚构不存在的数据

## 后端改动

### fiber_cut.py — `_build_fiber_events_from_window`

在事件 dict 中新增字段：

```python
{
    # 现有字段保持不变
    "event_alarms": [...],   # 保留：全部告警（向后兼容）

    # 新增
    "fiber_alarms": [        # 仅光纤类告警
        {"name": "STM1光物理接口 信号丢失(LOS)", "ne": "xxx", ...}
    ],
    "derivative_alarms": [   # 仅衍生类告警
        {"name": "AU4 告警指示信号(AIS)", "ne": "yyy", ...}
    ],
    "alarm_ne_types": {      # 每个网元的告警类型
        "710-达尔布特2.5G": "both",      # 同时有光纤+衍生
        "709-K26+700基站": "fiber",      # 仅有光纤
        "708-K21+080基站": "deriv",      # 仅有衍生
    }
}
```

分类逻辑：
- `_is_fiber_alarm(name)` → 归入 fiber_alarms
- `_is_derivative(name)` → 归入 derivative_alarms
- 两者都不是 → 仍保留在 event_alarms 中，但不在 fiber/derivative 分组里
- `alarm_ne_types`：遍历 event_alarms，对每个 NE 判断其告警类型

### 向后兼容

- `event_alarms` 保留不变，现有使用方不受影响
- 新增字段仅在 fiber-cut-detect 和 fiber-cut-analysis 端点返回
- 缓存的 sim_data.json 在重新检测后自动包含新字段

## 前端改动

### 统计面板（FiberCutPage）

`光缆中断告警 X` 和 `未命中光缆中断 Y` 改为可点击链接：

```tsx
// 点击"光缆中断告警"→ Drawer(命中告警)
<Button type="link" onClick={() => setHitDrawerOpen(true)}>
  光缆中断告警 {fiberAlarmCount}
</Button>

// 点击"未命中光缆中断"→ Drawer(未命中告警)
<Button type="link" onClick={() => setMissDrawerOpen(true)}>
  未命中光缆中断 {unmatchedFiberCount}
</Button>
```

### Drawer 1：命中告警（页签模式）

```
┌─────────────────────────────────────┐
│ 命中告警明细                    [X] │
├─────────────────────────────────────┤
│ [光纤告警 (N条)] [衍生告警 (M条)]   │  ← Tabs
├─────────────────────────────────────┤
│ 网管 │ 网元 │ 告警对象 │ 级别 │ ... │  ← Table
│ xxx  │ xxx  │ xxx     │ 紧急 │ ... │
└─────────────────────────────────────┘
```

两个页签各自展示表格（列：网管/网元/告警对象/级别/告警名称/告警类型/告警描述/发生时间/关联业务/告警分析）。

### Drawer 2：未命中告警

```
┌─────────────────────────────────────┐
│ 未命中光缆中断的告警 (Y条)      [X] │
├─────────────────────────────────────┤
│ 网元 │ 告警名称 │ 级别 │ 时间 │ ... │
└─────────────────────────────────────┘
```

展示所有不在任何光纤事件中的告警（即 `unmatchedFiberDetails`），帮助用户核对是否有漏判。

### 拓扑图（TopologyLinks 组件）

同一张 ECharts 树图，网元颜色根据 `alarm_ne_types`：

| 颜色 | 含义 |
|------|------|
| 🔴 红色 `#cf1322` | 仅有光纤告警 |
| 🟠 橙色 `#d46b08` | 光纤+衍生都有 |
| 🟡 黄色 `#d4b106` | 仅有衍生告警 |
| 🟢 绿色 `#91cc75` | 无告警（拓扑链上的中间节点） |

色标图例放在拓扑 Collapse 标签右侧：

```tsx
<Tag color="red">光纤</Tag>
<Tag color="orange">光纤+衍生</Tag>
<Tag color="gold">衍生</Tag>
<Tag color="green">无告警</Tag>
```

### 事件卡片（保持简洁）

事件卡片自身只保留：
- 标题、压缩比、网元/告警数量
- 断点信息（带时间范围）
- 拓扑图（三色+图例）
- 告警明细折叠区移除（改为通过统计面板链接查看）

## 数据流

```
fiber-cut-detect
  → _normalize_alarm() → 中英文字段
  → _split_into_time_windows()
  → _build_fiber_events_from_window()
      → 分类: fiber_alarms / derivative_alarms
      → 标记: alarm_ne_types = {ne: "fiber"|"deriv"|"both"}
      → 现有 event_alarms 保留
  → FiberCutResponse
      → events[] 包含新字段

前端 FiberCutPage
  → 统计面板点击 → Drawer(命中/未命中)
  → TopologyLinks 读 alarm_ne_types → 三色渲染
```

## 注意事项

1. **不虚构数据**：衍生告警数量由 `_is_derivative()` 实际匹配决定，为 0 时相关 UI 不展示
2. **alarm_ne_types 为空的向后兼容**：旧缓存无此字段时，TopologyLinks 回退到现有红/绿逻辑
3. **未命中告警**：来自 `unmatchedFiberDetails`（所有告警中不在任何事件里的）
4. **性能**：分类计算在检测时完成，不在前端实时处理
