import { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Button, Upload, Tag, Progress, Descriptions, Alert, Spin, message, Collapse, Table, Typography } from 'antd';
import { ExperimentOutlined, AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, RobotOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

interface UnmatchedDetail {
  alarm_name: string;
  ne_name: string;
  display_name: string;
  alarm_time: string;
  severity: string;
}

interface ValidateResult {
  total_alarms: number;
  matched_alarms: number;
  unmatched_alarms: number;
  unmatched_names: string[];
  unmatched_details?: UnmatchedDetail[];
  filtered_count?: number;
  filtered_professions?: string[];
  current_dedup_count?: number;
  work_orders: {
    scenario_name: string; convergence_alarm: string; priority: string;
    triggered_alarms: { name: string; ne: string; time: string; severity: string }[];
    matched_rule_count: number; recommendation: string;
  }[];
  coverage_rate: number;
  compression_rate?: number;
}

function TopologyLinks({ nes, alarms }: { nes: string[]; alarms?: any[] }) {
  const [links, setLinks] = useState<any[] | null>(null);
  const [fullNes, setFullNes] = useState<string[]>(nes);

  useEffect(() => {
    if (nes.length <= 1) return;
    api.getNENeighbors(nes.slice(0, 20)).then((r: any) => {
      if (r.links?.length > 0) {
        setLinks(r.links);
        const allNes = new Set(nes);
        r.links.forEach((l: any) => { allNes.add(l.source); allNes.add(l.target); });
        setFullNes([...allNes]);
      }
    }).catch(() => {});
  }, [nes.join(',')]);

  if (!links || links.length === 0) return null;

  // Map NE → alarm details
  const severityColor: Record<string, string> = { '紧急告警': '#cf1322', '主要告警': '#d46b08', '次要告警': '#d4b106', '提示告警': '#096dd9' };
  const neInfo: Record<string, { alarmDetails: any[]; severity: string; color: string }> = {};
  if (alarms) {
    alarms.forEach((a: any) => {
      const ne = a.ne;
      if (!neInfo[ne]) neInfo[ne] = { alarmDetails: [], severity: '', color: '#91cc75' };
      neInfo[ne].alarmDetails.push(a);
      const sevOrder = ['紧急告警', '主要告警', '次要告警', '提示告警'];
      const curIdx = sevOrder.indexOf(neInfo[ne].severity);
      const newIdx = sevOrder.indexOf(a.severity || '');
      if (newIdx >= 0 && (curIdx < 0 || newIdx < curIdx)) {
        neInfo[ne].severity = a.severity;
        neInfo[ne].color = severityColor[a.severity] || '#91cc75';
      }
    });
  }

  const alarmedNes = new Set(nes);
  const neSet = new Set(fullNes);
  const filteredLinks = links.filter((l: any) => neSet.has(l.source) && neSet.has(l.target));

  // Build adjacency and sort into chain
  const adj: Record<string, string[]> = {};
  filteredLinks.forEach((l: any) => {
    adj[l.source] = adj[l.source] || []; adj[l.source].push(l.target);
    adj[l.target] = adj[l.target] || []; adj[l.target].push(l.source);
  });
  // Find endpoint (node with only 1 connection)
  let start = fullNes[0] || '';
  for (const ne of fullNes) {
    if ((adj[ne] || []).length === 1) { start = ne; break; }
  }
  const neOrder: string[] = [];
  const added = new Set<string>();
  const queue = [start];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    if (added.has(cur)) continue;
    added.add(cur); neOrder.push(cur);
    (adj[cur] || []).forEach(nb => { if (!added.has(nb)) queue.push(nb); });
  }
  fullNes.forEach(n => { if (!added.has(n)) neOrder.push(n); });

  return (
    <Collapse size="small" ghost style={{ marginTop: 4 }}
      items={[{
        key: 'topo',
        label: <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          网元物理拓扑 ({filteredLinks.length} 条链路, {fullNes.length} 个网元)
          <span style={{ marginLeft: 8 }}>
            <Tag color="red" style={{fontSize:10}}>紧急</Tag>
            <Tag color="orange" style={{fontSize:10}}>主要</Tag>
            <Tag color="gold" style={{fontSize:10}}>次要</Tag>
            <Tag color="blue" style={{fontSize:10}}>提示</Tag>
            <Tag color="green" style={{fontSize:10}}>无告警</Tag>
          </span>
        </Typography.Text>,
        children: (
          <>
            <ReactECharts option={(() => {
              const nodes = neOrder.map((ne, idx) => {
                const info = neInfo[ne];
                const hasAlarm = alarmedNes.has(ne);
                return {
                  name: ne, x: idx * 180 + 60, y: 150, fixed: true,
                  symbolSize: hasAlarm ? 30 : 22,
                  itemStyle: { color: hasAlarm ? (info?.color || '#d46b08') : '#91cc75' },
                  alarmDetails: info?.alarmDetails || [],
                  hasAlarm, _info: info,
                };
              });
              const edges = filteredLinks.map((l: any) => ({ source: l.source, target: l.target }));
              return {
                tooltip: {
                  formatter: (p: any) => {
                    if (p.dataType === 'edge') return `${p.data.source} ↔ ${p.data.target}`;
                    const d = p.data; let h = `<b>${d.name}</b>`;
                    if (d.alarmDetails?.length) {
                      d.alarmDetails.forEach((a: any) => {
                        const desc = a.alarm_desc ? `, ${a.alarm_desc}` : '';
                        h += `<br/>• ${a.name || ''}${desc}`;
                        h += `<br/>  首次:${(a.first_time||'').replace('T',' ').slice(0,16)}`;
                      });
                    } else { h += '<br/>✓ 无告警'; }
                    return h;
                  },
                },
                series: [{
                  type: 'graph', layout: 'none', roam: true,
                  data: nodes, edges,
                  symbolSize: 30,
                  label: {
                    show: true, fontSize: 10, distance: 14, position: 'bottom',
                    formatter: (p: any) => {
                      const n = p.name.length > 16 ? p.name.slice(0,16)+'...' : p.name;
                      const d = p.data; const cnt = d.alarmDetails?.length || 0;
                      const label = cnt > 0 ? `${n}(${cnt})` : n;
                      if (!d.hasAlarm) return `{ne|${label}}\n{ok|✓无告警}`;
                      let r = `{ne|${label}}`;
                      d.alarmDetails?.slice(0,3).forEach((a: any) => {
                        const desc = a.alarm_desc ? `, ${a.alarm_desc}` : '';
                        let t = `${a.name||''}${desc}`;
                        if (t.length > 25) t = t.slice(0,25)+'...';
                        r += `\n{a|${t}}`;
                      });
                      if ((d.alarmDetails?.length||0) > 3) r += `\n{more|...+${d.alarmDetails.length-3}条}`;
                      return r;
                    },
                    rich: {
                      ne: { fontSize: 10, color: '#333', lineHeight: 16, fontWeight: 'bold' },
                      a: { fontSize: 9, color: '#cf1322', lineHeight: 13 },
                      ok: { fontSize: 9, color: '#52c41a', lineHeight: 13 },
                      more: { fontSize: 8, color: '#999', lineHeight: 11 },
                    },
                  },
                  lineStyle: { color: '#5470c6', width: 2, curveness: 0 },
                }],
              };
            })()} style={{ height: 280 }} />
            <Collapse size="small" ghost
              items={[{
                key: 'link-table',
                label: <Typography.Text type="secondary" style={{ fontSize: 11 }}>链路端口明细 ({filteredLinks.length} 条)</Typography.Text>,
                children: (
                  <Table size="small" pagination={false}
                    dataSource={filteredLinks.map((l: any, i: number) => ({ ...l, key: i }))}
                    columns={[
                      { title: 'A端', dataIndex: 'source', width: 160, ellipsis: true },
                      { title: 'A端端口', dataIndex: 'source_port', width: 180, ellipsis: true, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v}</div> },
                      { title: 'Z端', dataIndex: 'target', width: 160, ellipsis: true },
                      { title: 'Z端端口', dataIndex: 'target_port', width: 180, ellipsis: true, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v}</div> },
                    ]}
                  />
                ),
              }]}
            />
          </>
        ),
      }]}
    />
  );
}

function GuidanceButton({ wo }: { wo: any }) {
  const [guidance, setGuidance] = useState<string | null>(null);
  const [gLoading, setGLoading] = useState(false);

  const handleGuidance = async () => {
    setGLoading(true);
    setGuidance(null);
    try {
      const res = await api.workOrderGuidance({
        scenario_name: wo.scenario_name,
        convergence_alarm: wo.convergence_alarm,
        priority: wo.priority,
        triggered_alarms: wo.triggered_alarms,
        matched_rule_count: wo.matched_rule_count,
        avg_lift: 0,
      }) as any;
      setGuidance(res.guidance);
    } catch (e: any) {
      message.error(e.message);
    }
    setGLoading(false);
  };

  return (
    <div>
      <Button
        type="dashed"
        size="small"
        icon={<RobotOutlined />}
        loading={gLoading}
        onClick={handleGuidance}
      >
        {guidance ? '重新生成运维指导' : 'AI 生成运维指导'}
      </Button>
      {guidance && (
        <div style={{
          marginTop: 8, padding: 12, background: '#f6ffed',
          borderLeft: '4px solid #52c41a', borderRadius: 4,
          fontSize: 13, lineHeight: 2, whiteSpace: 'pre-line',
        }}>
          {guidance}
        </div>
      )}
    </div>
  );
}

export default function Dispatch() {
  const [valResult, setValResult] = useState<ValidateResult | null>(null);
  const [loading, setLoading] = useState(false);

  return (
    <div>
      <Alert
        type="info" showIcon
        message="模拟派单 — 上传当前告警，匹配规则，生成工单"
        description="先确认已在告警概览中上传历史告警并运行 FP-Growth。当前告警中同专业/网管/网元/告警对象/告警名称/告警类型/告警描述的视为同一条去重。"
        style={{ marginBottom: 16 }}
      />

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col span={8}>
            <Upload
              accept=".xlsx"
              showUploadList={false}
              beforeUpload={(f) => {
                setLoading(true);
                setValResult(null);
                api.validateAlarms(f)
                  .then((r: any) => {
                    setValResult(r);
                    setLoading(false);
                    message.success(`派单完成，覆盖率 ${r.coverage_rate}%，压缩率 ${r.compression_rate || 0}%，生成 ${r.work_orders.length} 张工单`);
                  })
                  .catch((e: any) => { message.error(e.message); setLoading(false); });
                return false;
              }}
            >
              <Button type="primary" icon={<ExperimentOutlined />} loading={loading} size="large">
                上传当前告警，一键模拟派单
              </Button>
            </Upload>
          </Col>

          {valResult && (
            <>
              <Col span={4}>
                <Statistic title="告警总数" value={valResult.total_alarms}
                suffix={valResult.current_dedup_count ? <span style={{fontSize:12,color:'#fa8c16'}}>去重{valResult.current_dedup_count}</span> : undefined} />
              </Col>
              <Col span={4}>
                <Statistic title="命中" value={valResult.matched_alarms}
                  suffix={<CheckCircleOutlined style={{ color: '#52c41a' }} />} />
              </Col>
              <Col span={4}>
                <Statistic title="未命中" value={valResult.unmatched_alarms}
                  suffix={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />} />
              </Col>
              <Col span={4}>
                <Progress type="circle" percent={valResult.coverage_rate} size={70}
                  status={valResult.coverage_rate > 70 ? 'success' : valResult.coverage_rate > 40 ? 'active' : 'exception'} />
              </Col>
            </>
          )}
        </Row>
      </Card>

      {loading && <Spin style={{ display: 'block', marginTop: 40 }} />}

      {valResult && (
        <>
          <Alert
            type="success" showIcon
            message={`告警压缩: ${valResult.total_alarms} 条 → ${valResult.matched_alarms} 条命中规则 → ${valResult.work_orders.length} 张工单（平均 ${(valResult.matched_alarms / Math.max(1, valResult.work_orders.length)).toFixed(1)} 条/张）+ ${valResult.unmatched_alarms} 条未命中（保持原样）= 共 ${valResult.unmatched_alarms + valResult.work_orders.length} 条输出，压缩率 ${valResult.compression_rate || 0}%`}
            style={{ marginBottom: 16 }}
          />
          {valResult.filtered_count && valResult.filtered_count > 0 ? (
            <Alert
              type="warning" showIcon
              message={`已过滤 ${valResult.filtered_count} 条告警（${valResult.filtered_professions?.length || 0} 个无规则专业），去重 ${valResult.current_dedup_count || 0} 条相同告警`}
              description={valResult.filtered_professions?.join('、') || ''}
              style={{ marginBottom: 16 }}
            />
          ) : null}

          <Card title={<><AlertOutlined /> 工单列表 ({valResult.work_orders.length} 条)</>} size="small" style={{ marginBottom: 16 }}>
            {valResult.work_orders.length === 0 ? (
              <p style={{ color: '#999' }}>无已触发诊断场景 — 当前告警全部不在已有规则覆盖范围内</p>
            ) : (
              valResult.work_orders.map((wo, i) => (
                <Card key={i} size="small" style={{ marginBottom: 8 }}
                  title={<>
                    <Tag color={wo.priority === '紧急' ? 'red' : wo.priority === '重要' ? 'orange' : 'blue'}>{wo.priority}</Tag>
                    {wo.scenario_name}
                  </>}
                >
                  <Descriptions size="small" column={3}>
                    <Descriptions.Item label="收敛告警">{wo.convergence_alarm}</Descriptions.Item>
                    <Descriptions.Item label="触发告警数">{wo.triggered_alarms.length}</Descriptions.Item>
                    <Descriptions.Item label="命中规则">{wo.matched_rule_count}条</Descriptions.Item>
                  </Descriptions>
                  <Collapse
                    size="small"
                    ghost
                    items={[{
                      key: 'detail',
                      label: `触发告警明细 (${wo.triggered_alarms.length} 条)`,
                      children: (
                        <Table
                          size="small"
                          bordered
                          pagination={false}
                          dataSource={wo.triggered_alarms.map((a, j) => ({ ...a, key: j }))}
                          columns={[
                            { title: '网管', dataIndex: 'network_manager', width: 100 },
                            { title: '网元', dataIndex: 'ne', width: 140 },
                            { title: '告警对象', dataIndex: 'alarm_object', width: 180, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                            { title: '告警名称', dataIndex: 'name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                            { title: '告警类型', dataIndex: 'alarm_type', width: 80 },
                            { title: '告警描述', dataIndex: 'alarm_desc', width: 140, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                            { title: '级别', dataIndex: 'severity', width: 80,
                              render: (v: string) => <Tag color={v.includes('紧急') ? 'red' : v.includes('主要') ? 'orange' : 'blue'}>{v}</Tag> },
                            { title: '首次发生', dataIndex: 'first_time', width: 145,
                              render: (v: string) => (v || '').replace('T', ' ') },
                            { title: '最后发生', dataIndex: 'last_time', width: 145,
                              render: (v: string) => (v || '').replace('T', ' ') },
                          ]}
                        />
                      ),
                    }]}
                  />
                  <TopologyLinks
                    nes={[...new Set(wo.triggered_alarms.map((a: any) => a.ne))]}
                    alarms={wo.triggered_alarms}
                  />
                  <Alert type="warning" message={wo.recommendation} style={{ marginTop: 8, fontSize: 12 }} />
                  <div style={{ marginTop: 8 }}>
                    <GuidanceButton wo={wo as any} />
                  </div>
                </Card>
              ))
            )}
          </Card>

          {valResult.unmatched_alarms > 0 && (
            <Card title={`未命中规则的告警 (${valResult.unmatched_alarms} 条 / ${valResult.unmatched_names.length} 种)`} size="small">
              <Table
                size="small"
                bordered
                pagination={{ pageSize: 15, showTotal: (t: number) => `共 ${t} 条` }}
                dataSource={(valResult.unmatched_details || []).map((a, j) => ({ ...a, key: j }))}
                columns={[
                  { title: '网管', dataIndex: 'network_manager', width: 100 },
                  { title: '网元', dataIndex: 'ne_name', width: 140 },
                  { title: '告警对象', dataIndex: 'alarm_object', width: 180, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '告警名称', dataIndex: 'display_name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '告警类型', dataIndex: 'alarm_type', width: 80 },
                  { title: '告警描述', dataIndex: 'alarm_desc', width: 140, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '级别', dataIndex: 'severity', width: 80,
                    render: (v: string) => <Tag color={v.includes('紧急') ? 'red' : v.includes('主要') ? 'orange' : 'blue'}>{v}</Tag> },
                  { title: '首次发生', dataIndex: 'first_time', width: 145,
                    render: (v: string) => (v || '').replace('T', ' ') },
                  { title: '最后发生', dataIndex: 'last_time', width: 145,
                    render: (v: string) => (v || '').replace('T', ' ') },
                ]}
              />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
