import { useEffect, useRef, useState, useMemo } from 'react';
import { Card, Select, Table, Tag, Spin, Empty, message, Row, Col, Statistic, Space, Input, Alert, Badge, Button, Collapse, Typography, Divider } from 'antd';
import { ApartmentOutlined, ClusterOutlined, SearchOutlined, AimOutlined, CloseOutlined, ExperimentOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

interface DTreeNode {
  name: string;
  children: DTreeNode[];
  metric_value: number | null;
  node_type: 'root' | 'consequent' | 'antecedent';
  rule_count: number;
}

interface ScenarioRule {
  antecedent_names: string[];
  consequent_names: string[];
  support: number;
  confidence: number;
  lift: number;
  temporal_confidence: number;
  temporal_lift: number;
}

interface Scenario {
  scenario_name: string;
  convergence_alarm: string;
  root: DTreeNode;
  rule_count: number;
  avg_lift: number;
  rules: ScenarioRule[];
  related_nes?: string[];
  category?: string;
}

interface TopoLink {
  source: string;
  target: string;
  source_port: string;
  target_port: string;
  ems_name: string;
}

const nodeColors: Record<string, string> = {
  root: '#cf1322',
  consequent: '#d46b08',
  antecedent: '#1677ff',
};

const nodeLabels: Record<string, string> = {
  root: '收敛告警（根因）',
  consequent: '中间症状',
  antecedent: '前置触发',
};

function applyNodeStyle(node: DTreeNode, selectedName: string, depth: number = 0): any {
  if (!node || depth > 3) return null;
  const isSelected = selectedName && node.name === selectedName;
  const kids = (node.children || []).map(c => applyNodeStyle(c, selectedName, depth + 1)).filter(Boolean);
  return {
    name: node.name,
    node_type: node.node_type,
    metric_value: node.metric_value,
    rule_count: node.rule_count,
    itemStyle: {
      color: nodeColors[node.node_type] || '#999',
      borderColor: isSelected ? '#000' : '#fff',
      borderWidth: isSelected ? 3 : 1,
      shadowBlur: isSelected ? 12 : 0,
      shadowColor: isSelected ? 'rgba(0,0,0,0.3)' : 'transparent',
    },
    symbolSize: node.node_type === 'root' ? 24 : node.node_type === 'consequent' ? 15 : 10,
    children: kids,
  };
}

function buildTreeOption(scenario: Scenario, selectedName: string) {
  const styledRoot = applyNodeStyle(scenario.root, selectedName);

  return {
    tooltip: {
      trigger: 'item' as const,
      enterable: true,
      extraCssText: 'max-width:340px;white-space:normal;',
      formatter: (params: any) => {
        const d = params.data;
        if (!d) return '';
        const color = nodeColors[d.node_type] || '#333';
        let html = `<div style="font-size:13px;line-height:1.8">`;
        html += `<b style="font-size:14px;color:${color}">${d.name}</b><br/>`;
        html += `<span style="color:#999">类型:</span> <span style="color:${color};font-weight:bold">${nodeLabels[d.node_type] || d.node_type}</span><br/>`;
        if (d.metric_value != null) html += `<span style="color:#999">关联强度:</span> ${d.metric_value.toFixed(4)}<br/>`;
        html += `<span style="color:#999">关联规则数:</span> ${d.rule_count}<br/>`;
        if (d.node_type !== 'root' && d.children?.length > 0) {
          html += `<span style="color:#999">子节点:</span> ${d.children.length} 个<br/>`;
        }
        if (d.category) html += `<span style="color:#999">分类:</span> <span style="color:#722ed1">${d.category}</span><br/>`;
        html += `<br/><span style="color:#1677ff;font-size:12px">点击筛选规则列表</span>`;
        html += `</div>`;
        return html;
      },
    },
    series: [{
      type: 'tree' as const,
      data: [styledRoot],
      top: '2%',
      left: '2%',
      bottom: '2%',
      right: '20%',
      roam: true,
      expandAndCollapse: true,
      initialTreeDepth: 1,
      orient: 'LR',
      layout: 'orthogonal',
      edgeShape: 'curve',
      edgeForkPosition: '60%',
      symbol: 'circle',
      symbolSize: 10,
      label: {
        position: 'left',
        verticalAlign: 'middle',
        align: 'right',
        fontSize: 11,
        overflow: 'truncate',
        width: 140,
        distance: 8,
        color: '#333',
      },
      leaves: {
        label: {
          position: 'right',
          verticalAlign: 'middle',
          align: 'left',
          distance: 8,
          color: '#1677ff',
        },
      },
      lineStyle: { color: '#d9d9d9', width: 1.5, curveness: 0.6 },
      emphasis: {
        focus: 'descendant',
        lineStyle: { color: '#555', width: 3 },
        itemStyle: { shadowBlur: 15, shadowColor: 'rgba(0,0,0,0.3)' },
      },
    }],
  };
}

export default function DiagnosticTree() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [totalRules, setTotalRules] = useState(0);
  const [activeAlarm, setActiveAlarm] = useState<string>('');
  const [searchText, setSearchText] = useState('');
  const activeAlarmRef = useRef('');
  const [diagResult, setDiagResult] = useState<string | null>(null);
  const [diagPrompt, setDiagPrompt] = useState<string | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [topoLinks, setTopoLinks] = useState<TopoLink[]>([]);
  const [topoLoading, setTopoLoading] = useState(false);

  useEffect(() => {
    api.getDiagnosticTrees()
      .then((res: any) => {
        setScenarios(res.scenarios || []);
        setTotalRules(res.total_rules_analyzed || 0);
        setLoading(false);
      })
      .catch((e: any) => { message.error(e.message); setLoading(false); });
  }, []);

  const current = scenarios[selectedIdx] || scenarios[0];

  const onChartEvents = useMemo(() => ({
    click: (params: any) => {
      if (params.data && params.data.name) {
        const name = params.data.name;
        if (activeAlarmRef.current === name) {
          activeAlarmRef.current = '';
          setActiveAlarm('');
          setSearchText('');
        } else {
          activeAlarmRef.current = name;
          setActiveAlarm(name);
        }
      }
    },
  }), []);

  const handleScenarioChange = (v: number) => {
    setSelectedIdx(v);
    setActiveAlarm('');
    setSearchText('');
    setDiagResult(null);
  };

  // Fetch physical topology for current scenario's NEs
  useEffect(() => {
    if (!current || !current.related_nes || current.related_nes.length === 0) {
      setTopoLinks([]);
      return;
    }
    setTopoLoading(true);
    const nes = current.related_nes.slice(0, 10); // limit to first 10 NEs
    api.getNENeighbors(nes)
      .then((res: any) => {
        setTopoLinks(res.links || []);
        setTopoLoading(false);
      })
      .catch(() => { setTopoLoading(false); });
  }, [current]);

  const handleClearFilter = () => {
    setActiveAlarm('');
    setSearchText('');
  };

  const handleDiagnose = async () => {
    if (!current) return;
    setDiagLoading(true);
    setDiagResult(null);
    setDiagPrompt(null);
    try {
      const symptoms = (current.root.children || []).map((c: any) => ({
        name: c.name,
        trigger_alarms: (c.children || []).map((a: any) => a.name),
        rule_count: c.rule_count,
        avg_lift: c.metric_value || 0,
      }));
      const topRules = [...current.rules]
        .sort((a, b) => b.lift - a.lift)
        .slice(0, 10)
        .map(r => ({
          antecedent_names: r.antecedent_names,
          consequent_names: r.consequent_names,
          support: r.support,
          confidence: r.confidence,
          lift: r.lift,
          temporal_confidence: r.temporal_confidence,
          temporal_lift: r.temporal_lift,
        }));

      const res = await api.diagnoseScenario({
        scenario_name: current.scenario_name,
        convergence_alarm: current.convergence_alarm,
        symptoms,
        rule_count: current.rule_count,
        avg_lift: current.avg_lift,
        top_rules: topRules,
      }) as { diagnosis: string; prompt: string };
      setDiagResult(res.diagnosis);
      setDiagPrompt(res.prompt);
      message.success('AI 诊断报告生成完成');
    } catch (e: any) {
      message.error(e.message);
    }
    setDiagLoading(false);
  };

  const treeOption = useMemo(() => {
    if (!current || !current.root) return {};
    try {
      return buildTreeOption(current, activeAlarm);
    } catch (e) {
      console.error('buildTreeOption error:', e);
      return {};
    }
  }, [current, activeAlarm]);

  const filteredRules = useMemo(() => {
    if (!current) return [];
    let rules = current.rules || [];
    if (activeAlarm) {
      rules = rules.filter(r =>
        r.antecedent_names.some(n => n === activeAlarm) ||
        r.consequent_names.some(n => n === activeAlarm)
      );
    }
    if (searchText) {
      rules = rules.filter(r =>
        r.antecedent_names.some(n => n.includes(searchText)) ||
        r.consequent_names.some(n => n.includes(searchText))
      );
    }
    return rules;
  }, [current, activeAlarm, searchText]);

  if (loading) return <Spin style={{ display: 'block', marginTop: 100 }} />;
  if (!scenarios.length || !current || !current.root)
    return <Empty description="无诊断树数据，请先运行FP-Growth" />;

  const tableColumns = [
    {
      title: '前件告警', dataIndex: 'antecedent_names',
      render: (v: string[]) => v.map((s, i) => (
        <Tag key={i} color={s === activeAlarm ? 'red' : 'blue'}>{s}</Tag>
      )),
    },
    {
      title: '后件告警', dataIndex: 'consequent_names',
      render: (v: string[]) => v.map((s, i) => (
        <Tag key={i} color={s === activeAlarm ? 'red' : 'orange'}>{s}</Tag>
      )),
    },
    { title: '支持度', dataIndex: 'support', width: 80, render: (v: number) => v.toFixed(4) },
    { title: '置信度', dataIndex: 'confidence', width: 80, render: (v: number) => v.toFixed(4) },
    { title: '提升度', dataIndex: 'lift', width: 75, render: (v: number) => v.toFixed(2),
      sorter: (a: ScenarioRule, b: ScenarioRule) => a.lift - b.lift, defaultSortOrder: 'descend' as const },
    { title: '时序置信度', dataIndex: 'temporal_confidence', width: 95, render: (v: number) => v.toFixed(4) },
    { title: '时序提升度', dataIndex: 'temporal_lift', width: 95, render: (v: number) => v.toFixed(2) },
  ];

  const colLabels: Record<string, string> = {'root': '收', 'consequent': '症', 'antecedent': '触'};

  return (
    <div>
      <Alert
        type="info" showIcon closable
        message="操作说明"
        description="① 下拉选择场景 → ② 点击红色根节点旁的 + 展开症状分支 → ③ 点击任意节点，表格自动筛选该告警的关联规则 → ④ 再次点击同一节点取消筛选"
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="诊断场景" value={scenarios.length} prefix={<ApartmentOutlined />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="故障分类" value={[...new Set(scenarios.map(s => s.category || '其他'))].length} prefix={<ApartmentOutlined />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="规则总数" value={activeAlarm ? filteredRules.length : totalRules} prefix={<ClusterOutlined />} />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="选择场景">
            <Select
              value={selectedIdx}
              onChange={handleScenarioChange}
              style={{ width: '100%' }}
              options={
                [...new Set(scenarios.map(s => s.category || '其他'))].map(cat => ({
                  label: cat,
                  options: scenarios
                    .map((s, i) => ({ s, i }))
                    .filter(({ s }) => (s.category || '其他') === cat)
                    .map(({ s, i }) => ({
                      label: `${s.scenario_name} (${s.rule_count}条)`,
                      value: i,
                    })),
                }))
              }
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={18}>
          <Card
            title={
              <Space size="small">
                {current.category && <Tag color="purple">{current.category}</Tag>}
                <Badge color={nodeColors.root} text="收敛告警" />
                <Badge color={nodeColors.consequent} text="中间症状" />
                <Badge color={nodeColors.antecedent} text="前置触发" />
                {activeAlarm && (
                  <Tag closable onClose={handleClearFilter} color="red">
                    已选中: {activeAlarm}
                  </Tag>
                )}
              </Space>
            }
            extra={
              <Input
                prefix={<SearchOutlined />}
                placeholder="搜索告警名..."
                size="small"
                style={{ width: 190 }}
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                allowClear
              />
            }
          >
            <ReactECharts
              option={treeOption}
              style={{ height: 540 }}
              opts={{ renderer: 'canvas' }}
              onEvents={onChartEvents}
              notMerge={true}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card
            title={activeAlarm ? `"${activeAlarm}" 相关规则` : '规则概览'}
            size="small"
            style={{ marginBottom: 16 }}
            extra={activeAlarm ? <a onClick={handleClearFilter}>清除</a> : null}
          >
            {activeAlarm ? (
              <div style={{ fontSize: 13 }}>
                <p>已在 <b>{current.rules.length}</b> 条规则中筛选出 <b style={{ color: '#cf1322' }}>{filteredRules.length}</b> 条。</p>
                <Table
                  columns={tableColumns.slice(0, 3)}
                  dataSource={filteredRules.slice(0, 8).map((r, i) => ({ ...r, key: i }))}
                  size="small"
                  pagination={false}
                  scroll={{ y: 340 }}
                />
              </div>
            ) : (
              <div style={{ fontSize: 13 }}>
                <p style={{ color: '#999' }}>
                  点击树图中的<Badge color={nodeColors.root} text="红色" />（根因）、
                  <Badge color={nodeColors.consequent} text="黄色" />（症状）、
                  <Badge color={nodeColors.antecedent} text="蓝色" />（触发）节点，
                  筛选关联规则。
                </p>
                <p style={{ color: '#999' }}>该场景含 <b>{current.rules.length}</b> 条规则。</p>
                <p style={{ color: '#999' }}>根因告警: <Tag color="red">{current.convergence_alarm}</Tag></p>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <Space>
            <ExperimentOutlined />
            <span>AI 诊断报告</span>
            {diagResult && <Tag color="purple">已生成</Tag>}
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={diagLoading}
            onClick={handleDiagnose}
          >
            生成诊断报告
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        {diagResult ? (
          <Row gutter={[16, 0]}>
            <Col span={16}>
              <div style={{ fontSize: 14, lineHeight: 2, whiteSpace: 'pre-line', background: '#fafafa', padding: 16, borderRadius: 6, borderLeft: '4px solid #722ed1' }}>
                {diagResult}
              </div>
            </Col>
            <Col span={8}>
              <Collapse size="small" ghost
                items={[{
                  key: 'prompt',
                  label: <Typography.Text type="secondary" style={{ fontSize: 12 }}>查看提示词</Typography.Text>,
                  children: (
                    <Typography.Paragraph style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 400, overflow: 'auto', background: '#fff', padding: 8, borderRadius: 4 }}>
                      {diagPrompt}
                    </Typography.Paragraph>
                  ),
                }]}
              />
            </Col>
          </Row>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            点击按钮，将当前场景的收敛告警、症状分支、触发条件及 Top 10 关联规则发送给大模型，生成专业诊断报告。
          </Typography.Text>
        )}
      </Card>

      <Card
        title={
          <Space>
            <ApartmentOutlined />
            <span>物理拓扑对端</span>
            {current.related_nes && (
              <Tag>{current.related_nes.length} 个网元</Tag>
            )}
            {topoLinks.length > 0 && <Tag color="green">{topoLinks.length} 条链路</Tag>}
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        {topoLinks.length > 0 ? (
          <Table
            dataSource={topoLinks.map((l, i) => ({ ...l, key: i }))}
            columns={[
              { title: 'A端设备', dataIndex: 'source', ellipsis: true },
              { title: 'A端端口', dataIndex: 'source_port', ellipsis: true, width: 200 },
              { title: 'Z端设备', dataIndex: 'target', ellipsis: true },
              { title: 'Z端端口', dataIndex: 'target_port', ellipsis: true, width: 200 },
              { title: '网管', dataIndex: 'ems_name', width: 100 },
            ]}
            size="small"
            pagination={false}
            scroll={{ y: 250 }}
          />
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {topoLoading
              ? '正在查询物理拓扑对端...'
              : current.related_nes && current.related_nes.length > 0
                ? '物理拓扑对端未查询到数据（外部API无返回），可手动上传拓扑JSON。'
                : '当前场景未关联网元数据。运行FP-Growth后会自动提取相关网元。'}
          </Typography.Text>
        )}
      </Card>

      <Card
        title={
          <Space>
            <span>规则列表</span>
            {activeAlarm && (
              <Tag color="red" closable onClose={handleClearFilter}>
                筛选: {activeAlarm}（{filteredRules.length} 条）
              </Tag>
            )}
          </Space>
        }
      >
        <Table
          columns={tableColumns}
          dataSource={filteredRules.map((r, i) => ({ ...r, key: i }))}
          size="small"
          pagination={{
            pageSize: 15,
            showTotal: (t: number) => `共 ${t} 条${activeAlarm ? '（已筛选）' : ''}`,
          }}
        />
      </Card>
    </div>
  );
}
