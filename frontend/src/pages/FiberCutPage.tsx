import { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Button, Upload, Tag, Progress, DatePicker, Select, Space, Alert, Spin, message, Collapse, Table, Input } from 'antd';
import { ExperimentOutlined, SearchOutlined, AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, RobotOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useTaskProgress } from '../hooks/useTaskProgress';
import TopologyLinks from '../components/TopologyLinks';

export default function FiberCutPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [fiberEvents, setFiberEvents] = useState<any[]>([]);
  const [queryStart, setQueryStart] = useState('');
  const [queryEnd, setQueryEnd] = useState('');
  const [querySpec, setQuerySpec] = useState('3');
  const [filterText, setFilterText] = useState('');
  const specOpts = [{ label: '传输系统', value: '3' }, { label: 'GSM-R', value: '4' }, { label: '数据通信', value: '1' }, { label: '电源监控', value: '9' }, { label: '调度通信', value: '7' }];
  const [apiLoading, setApiLoading] = useState(false);

  const { prog: queryProg, trackTask } = useTaskProgress();

  const [cacheLoading, setCacheLoading] = useState(false);

  // Auto-load cached fiber events on mount (fast), then fall back to detect
  useEffect(() => {
    (async () => {
      setCacheLoading(true);
      try {
        // Try cache first (instant if persisted)
        const cached = await api.fiberCutCached() as any;
        if (cached?.events?.length) {
          setFiberEvents(cached.events);
          try { const vr = await api.validateStore() as any; setResult(vr); }
          catch { setResult({ total_alarms: cached.total_alarms_scanned || 0 }); }
          setCacheLoading(false);
          return;
        }
      } catch {}
      // Fall back to full detection
      try {
        const fc = await api.fiberCutDetect() as any;
        if (fc.events?.length) {
          setFiberEvents(fc.events);
          try { const vr = await api.validateStore() as any; setResult(vr); }
          catch { setResult({ total_alarms: fc.total_alarms_scanned || 0 }); }
        }
      } catch {}
      setCacheLoading(false);
    })();
  }, []);

  const handleImport = async (type: 'file' | 'api-cur' | 'api-hist', file?: File) => {
    setLoading(true); setResult(null); setFiberEvents([]);
    try {
      if (type === 'file' && file) {
        // Upload to store first
        await api.upload([file]);
        // Detect fiber cuts from stored alarms
        const fc = await api.fiberCutDetect() as any;
        setFiberEvents(fc.events || []);
        // Get validation stats (may fail if no FP-Growth, that's ok for fiber detection)
        try { const vr = await api.validateStore() as any; setResult(vr); }
        catch { setResult({ total_alarms: fc.total_alarms_scanned || 0 }); }
      } else if (type === 'api-cur') {
        const r = await fetch(`http://localhost:8000/api/import-current-alarms?spec_id=${querySpec}`, { method: 'POST' }).then(r => r.json());
        if (r.error) { message.error(r.error); setLoading(false); return; }
        const fc = await api.fiberCutDetect() as any;
        setFiberEvents(fc.events || []);
        try { const vr = await api.validateStore() as any; setResult(vr); }
        catch { setResult({ total_alarms: fc.total_alarms_scanned || 0 }); }
        message.success(`当前告警: ${r.loaded}条`);
      } else if (type === 'api-hist') {
        if (!queryStart || !queryEnd) { message.warning('请选择日期'); setLoading(false); return; }
        setApiLoading(true);
        const r = await fetch(`http://localhost:8000/api/query-alarms?start_date=${queryStart}&end_date=${queryEnd}&spec_id=${querySpec}`, { method: 'POST' }).then(r => r.json());
        if (r.error) { message.error(r.error); setLoading(false); setApiLoading(false); return; }
        if (r.task_id) {
          trackTask(r.task_id);
          // Poll until done, then run fiber detection
          const poll = setInterval(async () => {
            const pr = await fetch(`http://localhost:8000/api/query-progress/${r.task_id}`).then(r => r.json());
            if (pr.status === 'done') {
              clearInterval(poll);
              const fc = await api.fiberCutDetect() as any;
              setFiberEvents(fc.events || []);
              try { const vr = await api.validateStore() as any; setResult(vr); }
              catch { setResult({ total_alarms: fc.total_alarms_scanned || 0 }); }
              setApiLoading(false);
              setLoading(false);
              message.success(`历史告警: ${pr.loaded || 0}条`);
            } else if (pr.status === 'failed') {
              clearInterval(poll);
              message.error((pr as any).error || '查询失败');
              setApiLoading(false);
              setLoading(false);
            }
          }, 500);
        } else {
          setApiLoading(false);
        }
      }
    } catch (e: any) { message.error(e.message); }
    setLoading(false);
  };

  // Fiber-cut-specific stats — all from fiberCutDetect response, not validateStore
  const fiberAlarmCount = fiberEvents.reduce((sum: number, ev: any) => sum + (ev.alarm_count || 0), 0);
  const totalAlarms = result?.total_alarms || 0;
  const unmatchedFiberCount = Math.max(0, totalAlarms - fiberAlarmCount);

  // Unique NEs + unique stations across all events
  const affectedNEs = new Set(fiberEvents.flatMap((ev: any) => ev.affected_nes || []));
  const affectedNECount = affectedNEs.size;
  const totalEventAlarms = fiberEvents.reduce((sum: number, ev: any) => sum + (ev.alarm_count || 0), 0);

  // Build alarm keys from fiber events to exclude from unmatched table
  const fiberAlarmKeys = new Set(
    fiberEvents.flatMap((ev: any) =>
      (ev.event_alarms || []).map((a: any) =>
        `${a.ne || ''}|${a.name || ''}|${a.first_time || a.time || ''}`
      )
    )
  );

  // Use work order alarms for unmatched table, excluding fiber event alarms
  const allWoAlarms = (result?.work_orders || []).flatMap((wo: any) => wo.triggered_alarms || []);
  const unmatchedFiberDetails = allWoAlarms.filter((a: any) =>
    !fiberAlarmKeys.has(`${a.ne || ''}|${a.name || ''}|${a.first_time || a.time || ''}`)
  );

  const filteredUnmatched = unmatchedFiberDetails.filter((a: any) =>
    !filterText || (a.ne || '').includes(filterText) || (a.name || '').includes(filterText)
  );

  return (
    <div>
      <Alert type="info" showIcon message="光缆中断检测 — 导入告警数据，自动识别光纤中断事件"
        style={{ marginBottom: 16 }} />

      {/* Import section - same as Dispatch */}
      <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small" title="文件导入">
            <Upload accept=".xlsx" showUploadList={false}
              beforeUpload={(f) => { handleImport('file', f); return false; }}>
              <Button block style={{ width: '100%' }} icon={<ExperimentOutlined />} loading={loading}>上传告警文件</Button>
            </Upload>
          </Card>
        </Col>
        <Col span={7}>
          <Card size="small" title="API — 当前告警">
            <Space.Compact style={{ width: '100%' }}>
              <Select size="small" value={querySpec} onChange={setQuerySpec} style={{ width: '60%' }} options={specOpts} />
              <Button icon={<SearchOutlined />} size="small" loading={loading} onClick={() => handleImport('api-cur')}
                style={{ width: '40%' }}>导入</Button>
            </Space.Compact>
          </Card>
        </Col>
        <Col span={11}>
          <Card size="small" title="API — 历史告警">
            <Space.Compact style={{ width: '100%' }}>
              <DatePicker size="small" placeholder="起始" style={{ width: '23%' }}
                onChange={(d: any) => setQueryStart(d?.format('YYYY-MM-DD') || '')} />
              <DatePicker size="small" placeholder="结束" style={{ width: '23%' }}
                onChange={(d: any) => setQueryEnd(d?.format('YYYY-MM-DD') || '')} />
              <Select size="small" value={querySpec} onChange={setQuerySpec} style={{ width: '25%' }} options={specOpts} />
              <Button icon={<SearchOutlined />} size="small" loading={loading} onClick={() => handleImport('api-hist')}
                style={{ width: '29%' }} disabled={!queryStart || !queryEnd}>导入</Button>
            </Space.Compact>
          </Card>
        </Col>
      </Row>

      {(loading || cacheLoading) && <Spin tip={cacheLoading ? '加载本地数据...' : undefined} style={{ display: 'block', marginTop: 40 }} />}

      {apiLoading && (
        <Row style={{ marginBottom: 16 }}>
          <Col span={24}>
            <Progress percent={queryProg.progress} status={queryProg.error ? 'exception' : 'active'}
              format={() => {
                let label = queryProg.status || '查询中...';
                if (queryProg.page > 0 && queryProg.total_pages > 0) label += ` (第${queryProg.page}/${queryProg.total_pages}页)`;
                if (queryProg.loaded > 0) label += ` ${queryProg.loaded}条`;
                return label;
              }}
            />
          </Col>
        </Row>
      )}

      {result && (
        <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
          <Col span={4}><Card size="small"><Statistic title="告警总数" value={totalAlarms} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="光缆中断告警" value={fiberAlarmCount} suffix={<CheckCircleOutlined style={{ color: '#52c41a' }} />} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="未命中光缆中断" value={unmatchedFiberCount} suffix={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="光缆事件" value={fiberEvents.length} suffix={<AlertOutlined style={{ color: '#cf1322' }} />} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="涉及网元" value={affectedNECount} /></Card></Col>
          <Col span={4}><Card size="small"><Progress type="circle" percent={result.total_alarms > 0 ? Math.round(fiberAlarmCount / result.total_alarms * 100) : 0} size={60}
            status={fiberAlarmCount / (result.total_alarms || 1) > 0.7 ? 'success' : fiberAlarmCount / (result.total_alarms || 1) > 0.4 ? 'active' : 'exception'} /></Card></Col>
        </Row>
      )}

      {/* Fiber cut events */}
      {fiberEvents.length > 0 && (
        <Card title={<><AlertOutlined /> 光缆中断检测 ({fiberEvents.length} 处疑似断点)</>}
          size="small" style={{ marginBottom: 16, borderLeft: '4px solid #cf1322' }}>
          {[...fiberEvents].sort((a, b) => (b.alarmed_ne_count || 0) - (a.alarmed_ne_count || 0)).map((ev: any, i: number) => {
            const evAlarms = ev.event_alarms || [];
            const evNes = [...new Set(evAlarms.map((a: any) => a.ne))] as string[];
            const isMulti = (ev.alarmed_ne_count || 0) >= 2;
            return (
            <Card key={i} size="small" style={{ marginBottom: 8 }}
              title={<><Tag color={isMulti ? 'red' : 'orange'}>{isMulti ? '多网元' : '单网元'}</Tag><span style={{ fontWeight: 700 }}>{ev.title}</span>
                <Tag>压缩比 {ev.compression_ratio}</Tag><Tag color="orange">{ev.affected_ne_count}站 {evAlarms.length}条</Tag></>}>
              <p style={{ fontSize: 13, color: '#cf1322', fontWeight: 600 }}>
                断点: {ev.cut_segment} | {ev.time_start && ev.time_end ? `${ev.time_start} ~ ${ev.time_end} | ` : ''}受影响: {ev.affected_nes?.join(' → ')}
              </p>
              <TopologyLinks nes={evNes} alarms={evAlarms} />
              <Collapse size="small" ghost items={[{ key: 'detail', label: `告警明细 (${evAlarms.length} 条)`,
                children: (
                  <Table size="small" bordered pagination={false}
                    dataSource={evAlarms.map((a: any, j: number) => ({ ...a, key: j }))}
                    columns={[
                      { title: '网元', dataIndex: 'ne', width: 160, ellipsis: true },
                      { title: '告警名称', dataIndex: 'name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v}</div> },
                      { title: '级别', dataIndex: 'severity', width: 70, render: (v: string) => <Tag color={v?.includes('紧急')?'red':v?.includes('主要')?'orange':'blue'} style={{fontSize:10}}>{v}</Tag> },
                      { title: '时间', dataIndex: 'first_time', width: 140, render: (v: string) => <span style={{fontSize:10}}>{(v||'').replace('T',' ')}</span> },
                    ]}
                  />),
              }]} />
              <FiberGuidance ev={ev} />
            </Card>
          );})}
        </Card>
      )}

      {/* Unmatched alarms */}
      {unmatchedFiberDetails.length > 0 && (
        <Card size="small" title={<span>未命中场景的告警 ({unmatchedFiberDetails.length} 条) <Tag color="orange">无法识别为光缆中断模式</Tag></span>}
          extra={<Input size="small" placeholder="筛选网元/告警..." value={filterText} onChange={e => setFilterText(e.target.value)}
            style={{ width: 200 }} allowClear />}>
          <Table size="small" bordered pagination={{ pageSize: 15 }}
            dataSource={filteredUnmatched.map((a: any, j: number) => ({ ...a, key: j }))}
            columns={[
              { title: '网元', dataIndex: 'ne', width: 140, ellipsis: true },
              { title: '告警名称', dataIndex: 'name', width: 160, render: (v: string) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v}</div> },
              { title: '级别', dataIndex: 'severity', width: 70, render: (v: string) => <Tag color={v?.includes('紧急')?'red':v?.includes('主要')?'orange':'blue'} style={{fontSize:10}}>{v}</Tag> },
              { title: '时间', dataIndex: 'first_time', width: 140, render: (v: string) => <span style={{fontSize:10}}>{(v||'').replace('T',' ')}</span> },
            ]}
          />
        </Card>
      )}
    </div>
  );
}

function FiberGuidance({ ev }: { ev: any }) {
  const [guidance, setGuidance] = useState<string | null>(null);
  const [gLoading, setGLoading] = useState(false);
  if (!ev.event_alarms?.length) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <Button size="small" icon={<RobotOutlined />} loading={gLoading}
        onClick={async () => {
          setGLoading(true); setGuidance(null);
          try {
            const r = await fetch('http://localhost:8000/api/fiber-cut-guidance', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ title: ev.title, cut_segment: ev.cut_segment,
                affected_nes: ev.affected_nes, alarm_count: ev.alarm_count,
                sample_alarms: (ev.event_alarms || []).slice(0, 200).map((a: any) => ({
                  ne: a.ne, name: a.name, severity: a.severity, first_time: a.first_time,
                })),
                topology_path: ev.topology_path || [],
                link_details: (ev.link_details || []).slice(0, 20),
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
