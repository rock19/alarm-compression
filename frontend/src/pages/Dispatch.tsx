import { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Button, Upload, Tag, Progress, Descriptions, Alert, Spin, message, Collapse, Table, Typography, Space, Input, DatePicker, Select } from 'antd';
const { Panel } = Collapse;
import { ExperimentOutlined, AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, RobotOutlined, SearchOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';
import { useTaskProgress } from '../hooks/useTaskProgress';

interface UnmatchedDetail {
  alarm_name: string;
  ne_name: string;
  display_name: string;
  alarm_time: string;
  severity: string;
  isolation?: string;
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
    scenario_name: string; convergence_alarm: string; priority: string; category?: string;
    triggered_alarms: { name: string; ne: string; time: string; severity: string }[];
    matched_rule_count: number; max_lift?: number; recommendation: string;
  }[];
  coverage_rate: number;
  compression_rate?: number;
}

function TopologyLinks({ nes, alarms }: { nes: string[]; alarms?: any[] }) {
  const [links, setLinks] = useState<any[] | null>(null);
  const [fullNes, setFullNes] = useState<string[]>(nes);

  useEffect(() => {
    if (nes.length === 0) return;
    api.getNENeighbors(nes.slice(0, 200)).then((r: any) => {
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
              // Build tree from topology: pick first alarmed NE as root
              const rootNe = neOrder.find(n => alarmedNes.has(n)) || neOrder[0];
              const visited = new Set<string>();
              const buildTree = (ne: string, depth: number): any => {
                if (visited.has(ne)) return null;
                visited.add(ne);
                const info = neInfo[ne];
                const hasAlarm = alarmedNes.has(ne);
                const children: any[] = [];
                (adj[ne] || []).forEach(peer => {
                  const child = buildTree(peer, depth + 1);
                  if (child) children.push(child);
                });
                // Add NEs without topology as leaves
                return {
                  name: ne,
                  children: children.length > 0 ? children : undefined,
                  itemStyle: { color: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderColor: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderWidth: 2 },
                  alarmDetails: info?.alarmDetails || [],
                  hasAlarm, _info: info,
                };
              };
              const treeData = buildTree(rootNe, 0);
              // Add any remaining unvisited NEs as additional roots
              const extraRoots: any[] = [];
              neOrder.forEach(n => {
                if (!visited.has(n)) {
                  const info = neInfo[n];
                  const hasAlarm = alarmedNes.has(n);
                  extraRoots.push({
                    name: n,
                    itemStyle: { color: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderColor: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderWidth: 2 },
                    alarmDetails: info?.alarmDetails || [],
                    hasAlarm, _info: info,
                  });
                }
              });

              return {
                tooltip: {
                  formatter: (p: any) => {
                    const d = p.data; let h = `<b>${d.name}</b>`;
                    if (d.hasAlarm) h += `<br/>级别: ${d._info?.severity || '-'}`;
                    if (d.alarmDetails?.length) {
                      d.alarmDetails.forEach((a: any) => {
                        const desc = a.alarm_desc ? `, ${a.alarm_desc}` : '';
                        const obj = a.alarm_object ? `<br/>  ${a.alarm_object}` : '';
                        h += `<br/><br/>• <b>${a.name || ''}</b>${obj}`;
                        if (desc) h += `<br/>  ${desc}`;
                        h += `<br/>  ${(a.first_time||'').replace('T',' ').slice(0,16)}`;
                        if (a.last_time) h += ` ~ ${(a.last_time||'').replace('T',' ').slice(0,16)}`;
                      });
                    } else { h += '<br/>✓ 无告警'; }
                    return h;
                  },
                },
                series: [{
                  type: 'tree',
                  data: treeData ? [treeData, ...extraRoots] : extraRoots,
                  top: '2%', left: '3%', bottom: '2%', right: '8%',
                  symbol: 'circle',
                  symbolSize: 12,
                  roam: true,
                  expandAndCollapse: true,
                  initialTreeDepth: -1,
                  orient: 'LR',
                  layout: 'orthogonal',
                  edgeShape: 'curve',
                  nodeWidth: 20,
                  nodeHeight: 20,
                  label: {
                    position: 'bottom', verticalAlign: 'top', align: 'center',
                    fontSize: 10, distance: 6,
                    formatter: (p: any) => {
                      const n = p.name.length > 18 ? p.name.slice(0,18)+'...' : p.name;
                      const d = p.data; const cnt = d.alarmDetails?.length || 0;
                      const label = cnt > 0 ? `${n}(${cnt})` : n;
                      if (!d.hasAlarm) return `{ne|${label}}\n{ok|✓无告警}`;
                      let r = `{ne|${label}}`;
                      (d.alarmDetails || []).slice(0, 3).forEach((a: any) => {
                        const obj = a.alarm_object ? `${a.alarm_object} - ` : '';
                        const desc = a.alarm_desc ? `, ${a.alarm_desc}` : '';
                        let t = `${obj}${a.name||''}${desc}`;
                        if (t.length > 22) t = t.slice(0,22)+'...';
                        const sev = a.severity || '';
                        const style = sev.includes('紧急') ? 'urg' : sev.includes('主要') ? 'maj' : sev.includes('次要') ? 'min' : 'tip';
                        r += `\n{${style}|${t}}`;
                      });
                      if (cnt > 3) r += `\n{more|...+${cnt-3}条}`;
                      return r;
                    },
                    rich: {
                      ne: { fontSize: 11, color: '#333', lineHeight: 18, fontWeight: 'bold' },
                      urg: { fontSize: 9, color: '#cf1322', lineHeight: 14 },
                      maj: { fontSize: 9, color: '#d46b08', lineHeight: 14 },
                      min: { fontSize: 9, color: '#d4b106', lineHeight: 14 },
                      tip: { fontSize: 9, color: '#096dd9', lineHeight: 14 },
                      ok: { fontSize: 9, color: '#52c41a', lineHeight: 14 },
                      more: { fontSize: 8, color: '#999', lineHeight: 12 },
                    },
                  },
                  leaves: { label: { position: 'bottom', align: 'center', distance: 6 }},
                  lineStyle: { color: '#b0b0b0', width: 1.5, curveness: 0.5 },
                  emphasis: { focus: 'descendant', lineStyle: { color: '#333', width: 2.5 } },
                }],
              };
            })()} style={{ height: Math.max(380, fullNes.length * 14) }} />
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

function FiberCutAnalysis({ workOrders }: { workOrders: any[] }) {
  const [events, setEvents] = useState<any[] | null>(null);
  useEffect(() => {
    if (workOrders.length === 0) return;
    api.analyzeFiberCuts(workOrders).then((r: any) => {
      if (r.events?.length > 0) setEvents(r.events);
    }).catch(() => {});
  }, [workOrders]);

  if (!events || events.length === 0) return null;

  return (
    <Card title={<><AlertOutlined /> 光缆中断检测 ({events.length} 处疑似断点)</>}
      size="small" style={{ marginBottom: 16, borderLeft: '4px solid #cf1322' }}>
      {events.map((ev: any, i: number) => {
        const evAlarms = ev.event_alarms || [];
        const evNes = [...new Set(evAlarms.map((a: any) => a.ne))] as string[];
        return (
        <Card key={i} size="small" style={{ marginBottom: 8 }}
          title={<>
            <Tag color="red">紧急</Tag>
            <span style={{ fontWeight: 700 }}>{ev.title}</span>
            <Tag>压缩比 {ev.compression_ratio}</Tag>
            <Tag color="orange">{ev.affected_ne_count}站 {evAlarms.length}条告警</Tag>
          </>}>
          <p style={{ fontSize: 13, color: '#cf1322', fontWeight: 600 }}>
            断点: {ev.cut_segment} | 受影响: {ev.affected_nes?.join(' → ')}
          </p>
          <TopologyLinks nes={evNes} alarms={evAlarms} />
          <Collapse size="small" ghost items={[{ key: 'detail', label: `告警明细 (${evAlarms.length} 条)`,
            children: (
              <Table size="small" bordered pagination={false}
                dataSource={evAlarms.map((a: any, j: number) => ({ ...a, key: j }))}
                columns={[
                  { title: '网元', dataIndex: 'ne', width: 180, ellipsis: true },
                  { title: '告警名称', dataIndex: 'name', width: 180, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v}</div> },
                  { title: '级别', dataIndex: 'severity', width: 80,
                    render: (v: string) => <Tag color={v?.includes('紧急')?'red':v?.includes('主要')?'orange':'blue'} style={{fontSize:10}}>{v}</Tag> },
                  { title: '发生时间', dataIndex: 'first_time', width: 145, render: (v: string) => <span style={{fontSize:10}}>{(v||'').replace('T',' ')}</span> },
                ]}
              />
            ),
          }]} />
          <div style={{ marginTop: 8 }}><FiberCutGuidanceButton ev={ev} /></div>
        </Card>
      );})}
    </Card>
  );
}

function FiberCutGuidanceButton({ ev }: { ev: any }) {
  const [guidance, setGuidance] = useState<string | null>(null);
  const [gLoading, setGLoading] = useState(false);
  if (!ev.event_alarms?.length) return null;
  return (
    <div>
      <Button size="small" icon={<RobotOutlined />} loading={gLoading}
        onClick={async () => {
          setGLoading(true); setGuidance(null);
          try {
            const r = await fetch('http://localhost:8000/api/fiber-cut-guidance', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ title: ev.title, cut_segment: ev.cut_segment,
                affected_nes: ev.affected_nes, alarm_count: ev.alarm_count,
                sample_alarms: (ev.event_alarms || []).slice(0, 10).map((a: any) => ({
                  ne: a.ne, name: a.name, severity: a.severity, first_time: a.first_time,
                })),
              }),
            }).then(r => r.json());
            setGuidance(r.guidance);
          } catch (e: any) { message.error(e.message); }
          setGLoading(false);
        }}>AI分析</Button>
      {guidance && <Alert type="info" message={guidance} style={{ marginTop: 6, fontSize: 12, whiteSpace: 'pre-line' }} />}
    </div>
  );
}

function WorkOrderCard({ wo }: { wo: any }) {
  const shortName = wo.scenario_name.replace(/.*事件(\d+).*/, '事件$1').replace(/.*\(\d+网元\).*/, (m: string) => m);
  return (
    <Card size="small" style={{ marginBottom: 6, marginLeft: 16 }}
      title={<>
        <Tag color={wo.priority === '紧急' ? 'red' : wo.priority === '重要' ? 'orange' : 'blue'}>{wo.priority}</Tag>
        {wo.scenario_name.includes('事件') ? shortName : wo.scenario_name}
        <Tag>{wo.triggered_alarms.length}条告警</Tag>
        {wo.scenario_name.includes('网元') && <Tag color="green">{wo.scenario_name.match(/\((\d+)网元\)/)?.[1] || ''}网元</Tag>}
      </>}>
      <Descriptions size="small" column={4}>
        <Descriptions.Item label="收敛告警">{wo.convergence_alarm}</Descriptions.Item>
        <Descriptions.Item label="触发告警数">{wo.triggered_alarms.length}</Descriptions.Item>
        <Descriptions.Item label="命中规则">{wo.matched_rule_count}条</Descriptions.Item>
        <Descriptions.Item label="最大提升度">{wo.max_lift?.toFixed(1) || '-'}</Descriptions.Item>
      </Descriptions>
      <Collapse size="small" ghost items={[{ key: 'detail', label: `触发告警明细 (${wo.triggered_alarms.length} 条)`,
        children: (
          <Table size="small" bordered pagination={false}
            dataSource={wo.triggered_alarms.map((a: any, j: number) => ({ ...a, key: j }))}
            columns={[
              { title: '网管', dataIndex: 'network_manager', width: 100 },
              { title: '网元', dataIndex: 'ne', width: 140 },
              { title: '告警对象', dataIndex: 'alarm_object', width: 180, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
              { title: '告警名称', dataIndex: 'name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
              { title: '告警类型', dataIndex: 'alarm_type', width: 80 },
              { title: '告警描述', dataIndex: 'alarm_desc', width: 140, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
              { title: '级别', dataIndex: 'severity', width: 80,
                render: (v: string) => <Tag color={v.includes('紧急') ? 'red' : v.includes('主要') ? 'orange' : 'blue'}>{v}</Tag> },
              { title: '首次发生', dataIndex: 'first_time', width: 145, render: (v: string) => (v || '').replace('T', ' ') },
              { title: '最后发生', dataIndex: 'last_time', width: 145, render: (v: string) => (v || '').replace('T', ' ') },
            ]}
          />
        ),
      }]} />
      {(() => { const nesArr: string[] = []; const seen = new Set<string>(); wo.triggered_alarms.forEach((a: any) => { if (!seen.has(a.ne)) { seen.add(a.ne); nesArr.push(a.ne); } }); return <TopologyLinks nes={nesArr} alarms={wo.triggered_alarms} />; })()}
      <Alert type="warning" message={wo.recommendation} style={{ marginTop: 8, fontSize: 12 }} />
      <div style={{ marginTop: 8 }}><GuidanceButton wo={wo} /></div>
    </Card>
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
  const [apiCurLoading, setApiCurLoading] = useState(false);
  const [apiHistLoading, setApiHistLoading] = useState(false);
  const [apiCurProgress, setApiCurProgress] = useState({ progress: 0, status: '', loaded: 0 });
  const { prog: histProg, trackTask: trackHistTask, onDone: onHistDone } = useTaskProgress();
  const [apiHistProgress, setApiHistProgress] = useState({ progress: 0, status: '', loaded: 0, page: 0, total_pages: 0 });
  const [woFilter, setWoFilter] = useState('');
  const [queryStart, setQueryStart] = useState('');
  const [queryEnd, setQueryEnd] = useState('');
  const [querySpec, setQuerySpec] = useState('3');
  const specOptions = [
    { label: '传输系统', value: '3' }, { label: 'GSM-R', value: '4' },
    { label: '数据通信', value: '1' }, { label: '电源及环境监控', value: '9' },
    { label: '调度通信', value: '7' },
  ];

  const filteredOrders = valResult
    ? (woFilter
        ? valResult.work_orders.filter(wo =>
            wo.triggered_alarms.some((a: any) =>
              (a.name || '').includes(woFilter) || (a.alarm_desc || '').includes(woFilter)))
        : valResult.work_orders)
    : [];

  // Group work orders: category → scenario → events
  const categoryGroups = (() => {
    const cats: Record<string, Record<string, any[]>> = {};
    filteredOrders.forEach(wo => {
      const cat = wo.category || '其他故障';
      const base = wo.scenario_name
        .replace(/ \(事件\d+\)/, '')
        .replace(/ \(\d+网元\)/, '')
        .replace(/ \(网元非直连.*/, '')
        .replace(/ \(网元互联.*/, '');
      if (!cats[cat]) cats[cat] = {};
      (cats[cat][base] = cats[cat][base] || []).push(wo);
    });
    return Object.entries(cats);
  })();

  return (
    <div>
      <Alert
        type="info" showIcon
        message="模拟派单 — 上传当前告警，匹配规则，生成工单"
        description="先确认已在告警概览中上传历史告警并运行 FP-Growth。当前告警中同专业/网管/网元/告警对象/告警名称/告警类型/告警描述的视为同一条去重。"
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[12, 8]} style={{ marginBottom: 16 }}>
        <Col span={7}>
          <Card size="small" title="文件导入">
            <Row gutter={8}><Col span={12}>
              <Upload accept=".xlsx" showUploadList={false}
                beforeUpload={(f) => { setLoading(true); setValResult(null);
                  api.validateAlarms(f).then((r: any) => { setValResult(r); setLoading(false); message.success(`完成: ${r.work_orders.length}工单`); }).catch((e: any) => { message.error(e.message); setLoading(false); });
                  return false; }}>
                <Button style={{ width: '100%' }} size="small" icon={<ExperimentOutlined />} loading={loading}>当前</Button>
              </Upload></Col><Col span={12}>
              <Upload accept=".xlsx" showUploadList={false}
                beforeUpload={(f) => { setLoading(true); setValResult(null);
                  api.validateAlarms(f).then((r: any) => { setValResult(r); setLoading(false); }).catch((e: any) => { message.error(e.message); setLoading(false); });
                  return false; }}>
                <Button style={{ width: '100%' }} size="small" icon={<ExperimentOutlined />} loading={loading}>历史</Button>
              </Upload></Col>
            </Row>
          </Card>
        </Col>
        <Col span={7}>
          <Card size="small" title="API — 当前告警">
            <Space.Compact style={{ width: '100%' }}>
              <Select size="small" value={querySpec} onChange={setQuerySpec} style={{ width: 'calc(100% - 60px)' }}
                options={specOptions} />
              <Button icon={<SearchOutlined />} size="small" loading={apiCurLoading}
                onClick={async () => { setApiCurLoading(true); setValResult(null);
                  setApiCurProgress({ progress: 10, status: '查询中...', loaded: 0 });
                  try {
                    const r = await fetch(`http://localhost:8000/api/import-current-alarms?spec_id=${querySpec}`, { method: 'POST' }).then(r => r.json());
                    if (r.error) { message.error(r.error); setApiCurLoading(false); return; }
                    setApiCurProgress({ progress: 70, status: '派单分析中...', loaded: r.loaded });
                    const vr = await api.validateStore() as any; setValResult(vr); setApiCurLoading(false);
                    setApiCurProgress({ progress: 100, status: '完成', loaded: r.loaded });
                    message.success(`当前: ${r.loaded}条 → ${vr.work_orders.length}工单`);
                  } catch (e: any) { message.error(e.message); setApiCurLoading(false); }
                }}>导入</Button>
            </Space.Compact>
            {apiCurLoading && <Progress percent={apiCurProgress.progress} size="small"
              format={() => `${apiCurProgress.status} ${apiCurProgress.loaded}条`} style={{ marginTop: 2 }} />}
          </Card>
        </Col>
        <Col span={10}>
          <Card size="small" title="API — 历史告警">
            <Space.Compact style={{ width: '100%' }}>
              <DatePicker size="small" placeholder="起始日期" onChange={(d: any) => setQueryStart(d?.format('YYYY-MM-DD') || '')}
                style={{ width: '25%' }} />
              <DatePicker size="small" placeholder="结束日期" onChange={(d: any) => setQueryEnd(d?.format('YYYY-MM-DD') || '')}
                style={{ width: '25%' }} />
              <Select size="small" value={querySpec} onChange={setQuerySpec} style={{ width: '30%' }}
                options={specOptions} />
              <Button icon={<SearchOutlined />} size="small" loading={apiHistLoading} style={{ width: '20%' }}
                onClick={async () => { if (!queryStart || !queryEnd) { message.warning('请选择日期'); return; }
                  setApiHistLoading(true); setValResult(null);
                  setApiHistProgress({ progress: 5, status: '查询中...', loaded: 0, page: 0, total_pages: 0 });
                  try {
                    const r = await fetch(`http://localhost:8000/api/query-alarms?start_date=${queryStart}&end_date=${queryEnd}&spec_id=${querySpec}`, { method: 'POST' }).then(r => r.json());
                    if (r.error) { message.error(r.error); setApiHistLoading(false); return; }
                    if (r.task_id) {
                      trackHistTask(r.task_id);
                      // Wait for completion, then run validate
                      const checkDone = setInterval(async () => {
                        const pr = await fetch(`http://localhost:8000/api/query-progress/${r.task_id}`).then(r => r.json());
                        setApiHistProgress({ progress: pr.progress || 0, status: pr.status || '', loaded: pr.loaded || 0, page: pr.page || 0, total_pages: pr.total_pages || 0 });
                        if (pr.status === 'done') {
                          clearInterval(checkDone);
                          setApiHistProgress({ progress: 85, status: '派单分析中...', loaded: pr.loaded || 0, page: 0, total_pages: 0 });
                          try {
                            const vr = await api.validateStore() as any; setValResult(vr);
                            setApiHistProgress({ progress: 100, status: '完成', loaded: pr.loaded || 0, page: 0, total_pages: 0 });
                            message.success(`历史: ${pr.loaded || 0}条 → ${vr.work_orders.length}工单`);
                          } catch (ve: any) { message.error(ve.message); }
                          setApiHistLoading(false);
                        } else if (pr.status === 'failed') {
                          clearInterval(checkDone);
                          message.error((pr as any).error || '查询失败');
                          setApiHistLoading(false);
                        }
                      }, 500);
                    } else {
                      setApiHistLoading(false);
                    }
                  } catch (e: any) { message.error(e.message); setApiHistLoading(false); }
                }}>导入</Button>
            </Space.Compact>
            {apiHistLoading && <Progress percent={histProg.progress > 0 ? histProg.progress : apiHistProgress.progress} size="small"
              format={() => {
                // Use hook progress during query phase, local progress during post-processing
                if (histProg.progress > 0 && histProg.progress < 100) {
                  let label = histProg.status;
                  if (histProg.page > 0 && histProg.total_pages > 0) label += ` (第${histProg.page}/${histProg.total_pages}页)`;
                  if (histProg.loaded > 0) label += ` ${histProg.loaded}条`;
                  return label;
                }
                return `${apiHistProgress.status} ${apiHistProgress.loaded}条`;
              }} style={{ marginTop: 2 }} />}
          </Card>
        </Col>
      </Row>

      {valResult && (
            <Row gutter={[12, 8]} style={{ marginBottom: 16 }}>
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
            </Row>
          )}

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

          <Card title={<><AlertOutlined /> 诊断场景与工单 ({filteredOrders.length}/{valResult.work_orders.length} 条)</>} size="small" style={{ marginBottom: 16 }}
            extra={
              <Input
                prefix={<SearchOutlined />}
                placeholder="筛选告警名称..."
                size="small"
                style={{ width: 220 }}
                value={woFilter}
                onChange={e => setWoFilter(e.target.value)}
                allowClear
              />
            }
          >
            {filteredOrders.length === 0
              ? <p style={{ color: '#999' }}>无已触发诊断场景</p>
              : <Collapse size="small" defaultActiveKey={categoryGroups.slice(0, 2).map(([c]) => c)}>
                  {categoryGroups.map(([category, scenarios]) => {
                    const catAlarms = Object.values(scenarios).flat().reduce((s: number, wo: any) => s + wo.triggered_alarms.length, 0);
                    const catOrders = Object.values(scenarios).flat().length;
                    return (
                      <Panel key={category}
                        header={<>
                          <Tag color="purple">{category}</Tag>
                          <span>{Object.keys(scenarios).length}个场景, {catOrders}个工单, {catAlarms}条告警</span>
                        </>}>
                        <Collapse size="small" ghost defaultActiveKey={Object.keys(scenarios).slice(0, 2)}>
                          {Object.entries(scenarios).map(([scenario, orders]) => {
                            const prio = orders.some((w: any) => w.priority === '紧急') ? '紧急'
                              : orders.some((w: any) => w.priority === '重要') ? '重要' : '普通';
                            const scAlarms = orders.reduce((s: number, wo: any) => s + wo.triggered_alarms.length, 0);
                            const scNes = new Set(orders.flatMap((wo: any) => wo.triggered_alarms.map((a: any) => a.ne))).size;
                            return (
                              <Panel key={scenario}
                                header={<>
                                  <Tag color={prio === '紧急' ? 'red' : prio === '重要' ? 'orange' : 'blue'}>{prio}</Tag>
                                  <span style={{ fontWeight: 600 }}>{scenario}</span>
                                  <Tag>{orders.length}个事件</Tag><Tag>{scAlarms}条告警</Tag><Tag>{scNes}个网元</Tag>
                                </>}>
                                {orders.map((wo: any) => (
                                  <WorkOrderCard key={wo.scenario_name + wo.priority + wo.triggered_alarms.length} wo={wo} />
                                ))}
                              </Panel>
                            );
                          })}
                        </Collapse>
                      </Panel>
                    );
                  })}
                </Collapse>
            }
          </Card>

          <FiberCutAnalysis workOrders={valResult.work_orders} />

          {valResult.unmatched_alarms > 0 && (() => {
            const details = valResult.unmatched_details || [];
            const nmFilters = [...new Set(details.map((a: any) => a.network_manager).filter(Boolean))].map(v => ({ text: v, value: v }));
            const neFilters = [...new Set(details.map((a: any) => a.ne_name).filter(Boolean))].slice(0, 50).map(v => ({ text: v, value: v }));
            const sevFilters = [...new Set(details.map((a: any) => a.severity).filter(Boolean))].map(v => ({ text: v, value: v }));
            const isolCount = details.filter((a: any) => a.isolation?.includes('孤立')).length;
            const couldCount = details.filter((a: any) => a.isolation?.includes('可共现')).length;
            return (
            <Card title={<span>未命中规则的告警 ({valResult.unmatched_alarms} 条: <Tag color="orange">孤立事件 {isolCount}</Tag> <Tag color="blue">可共现 {couldCount}</Tag>)</span>} size="small">
              <Table
                size="small"
                bordered
                pagination={{ pageSize: 15, showTotal: (t: number) => `共 ${t} 条` }}
                dataSource={details.map((a, j) => ({ ...a, key: j }))}
                columns={[
                  { title: '网管', dataIndex: 'network_manager', width: 100, filters: nmFilters, onFilter: (v: any, r: any) => r.network_manager === v },
                  { title: '网元', dataIndex: 'ne_name', width: 140, filters: neFilters, onFilter: (v: any, r: any) => r.ne_name === v },
                  { title: '告警对象', dataIndex: 'alarm_object', width: 180, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '告警名称', dataIndex: 'display_name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '告警类型', dataIndex: 'alarm_type', width: 80 },
                  { title: '告警描述', dataIndex: 'alarm_desc', width: 140, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal'}}>{v}</div> },
                  { title: '级别', dataIndex: 'severity', width: 80, filters: sevFilters, onFilter: (v: any, r: any) => r.severity === v,
                    render: (v: string) => <Tag color={v.includes('紧急') ? 'red' : v.includes('主要') ? 'orange' : 'blue'}>{v}</Tag> },
                  { title: '分类', dataIndex: 'isolation', width: 130,
                    render: (v: string) => v?.includes('孤立')
                      ? <Tag color="orange">孤立事件</Tag>
                      : v?.includes('可共现') ? <Tag color="blue">可共现</Tag> : null },
                  { title: '首次发生', dataIndex: 'first_time', width: 145,
                    render: (v: string) => (v || '').replace('T', ' ') },
                  { title: '最后发生', dataIndex: 'last_time', width: 145,
                    render: (v: string) => (v || '').replace('T', ' ') },
                ]}
              />
            </Card>
          )})()}
        </>
      )}
    </div>
  );
}
