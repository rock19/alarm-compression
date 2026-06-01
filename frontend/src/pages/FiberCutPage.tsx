import { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Button, Upload, Tag, Progress, DatePicker, Select, Space, Alert, Spin, message, Collapse, Table, Input, Drawer, Tabs } from 'antd';
import { ExperimentOutlined, SearchOutlined, AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, RobotOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useTaskProgress } from '../hooks/useTaskProgress';
import TopologyLinks from '../components/TopologyLinks';

// Shared alarm detail columns (10 fields, consistent across all tables)
const ALARM_COLUMNS = [
  { title: '网管', dataIndex: '网管', width: 100, sorter: (a:any,b:any)=>(a.网管||'').localeCompare(b.网管||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '网元', dataIndex: '网元', width: 140, sorter: (a:any,b:any)=>(a.网元||'').localeCompare(b.网元||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '告警对象', dataIndex: '告警对象', width: 120, sorter: (a:any,b:any)=>(a.告警对象||'').localeCompare(b.告警对象||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '级别', dataIndex: '告警级别', width: 60, sorter: (a:any,b:any)=>(a.告警级别||'').localeCompare(b.告警级别||''),
    render: (v:any) => <Tag color={(v||'').includes('紧急')?'red':(v||'').includes('主要')?'orange':'blue'} style={{fontSize:10}}>{v||''}</Tag> },
  { title: '告警名称', dataIndex: '告警名称', width: 150, sorter: (a:any,b:any)=>(a.告警名称||'').localeCompare(b.告警名称||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '告警类型', dataIndex: '告警类型', width: 80, sorter: (a:any,b:any)=>(a.告警类型||'').localeCompare(b.告警类型||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '告警描述', dataIndex: '告警描述', width: 130, sorter: (a:any,b:any)=>(a.告警描述||'').localeCompare(b.告警描述||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '发生时间', dataIndex: '发生时间', width: 130, sorter: (a:any,b:any)=>(a.发生时间||'').localeCompare(b.发生时间||''),
    render: (v:any) => <span style={{fontSize:10}}>{(v||'').toString().replace('T',' ')}</span> },
  { title: '关联业务', dataIndex: '关联业务', width: 80, sorter: (a:any,b:any)=>(a.关联业务||'').localeCompare(b.关联业务||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
  { title: '告警分析', dataIndex: '告警分析', width: 100, sorter: (a:any,b:any)=>(a.告警分析||'').localeCompare(b.告警分析||''),
    render: (v:any) => <div style={{wordBreak:'break-all',whiteSpace:'normal',fontSize:10}}>{v||''}</div> },
];

export default function FiberCutPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [fiberEvents, setFiberEvents] = useState<any[]>([]);
  const [unmatchedAlarms, setUnmatchedAlarms] = useState<any[]>([]);
  const [queryStart, setQueryStart] = useState('');
  const [queryEnd, setQueryEnd] = useState('');
  const [querySpec, setQuerySpec] = useState('3');
  const [filterText, setFilterText] = useState('');
  const specOpts = [{ label: '传输系统', value: '3' }, { label: 'GSM-R', value: '4' }, { label: '数据通信', value: '1' }, { label: '电源监控', value: '9' }, { label: '调度通信', value: '7' }];
  const [apiLoading, setApiLoading] = useState(false);

  const { prog: queryProg, trackTask } = useTaskProgress();

  const [cacheLoading, setCacheLoading] = useState(false);
  const [hitDrawerOpen, setHitDrawerOpen] = useState(false);
  const [missDrawerOpen, setMissDrawerOpen] = useState(false);

  // Auto-load cached fiber events on mount (instant from sim_data.json)
  useEffect(() => {
    (async () => {
      setCacheLoading(true);
      try {
        const cached = await api.fiberCutCached() as any;
        if (cached?.events?.length) {
          setFiberEvents(cached.events);
          if (cached.unmatched_alarms) setUnmatchedAlarms(cached.unmatched_alarms);
        }
      } catch {}
      setCacheLoading(false);
    })();
  }, []);

  const handleImport = async (type: 'file' | 'api-cur' | 'api-hist', file?: File) => {
    setLoading(true); setResult(null); setFiberEvents([]);
    try {
      if (type === 'file' && file) {
        // Validate file without storing (simulation only)
        const vr = await api.validateAlarms(file) as any;
        setResult(vr);
        // Run fiber cut detection on the validated work orders
        const fc = await api.analyzeFiberCuts(vr.work_orders || []) as any;
        setFiberEvents(fc.events || []);
      } else if (type === 'api-cur') {
        const r = await fetch(`http://localhost:8000/api/import-current-alarms?spec_id=${querySpec}&sim=1`, { method: 'POST' }).then(r => r.json());
        if (r.error) { message.error(r.error); setLoading(false); return; }
        const fc = await api.fiberCutDetect() as any;
        setFiberEvents(fc.events || []);
        if (fc.unmatched_alarms) setUnmatchedAlarms(fc.unmatched_alarms);
        try { const vr = await api.validateStore() as any; setResult(vr); }
        catch { setResult({ total_alarms: fc.total_alarms_scanned || 0 }); }
        message.success(`当前告警: ${r.loaded}条`);
      } else if (type === 'api-hist') {
        if (!queryStart || !queryEnd) { message.warning('请选择日期'); setLoading(false); return; }
        setApiLoading(true);
        const r = await fetch(`http://localhost:8000/api/query-alarms?start_date=${queryStart}&end_date=${queryEnd}&spec_id=${querySpec}&sim=1`, { method: 'POST' }).then(r => r.json());
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
              if (fc.unmatched_alarms) setUnmatchedAlarms(fc.unmatched_alarms);
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

  // Build set of alarm keys that are in fiber events (matched)
  const fiberAlarmKeys = new Set(
    fiberEvents.flatMap((ev: any) =>
      (ev.event_alarms || []).map((a: any) =>
        `${a.ne || ''}|${a.name || ''}|${a.first_time || a.time || ''}`
      )
    )
  );

  // Unmatched = all WO alarms minus fiber event alarms (same source as panel total)
  const allWoAlarms = (result?.work_orders || []).flatMap((wo: any) => wo.triggered_alarms || []);
  const unmatchedFiberDetails = allWoAlarms.filter((a: any) =>
    !fiberAlarmKeys.has(`${a.ne || ''}|${a.name || ''}|${a.first_time || a.time || ''}`)
  );

  const filteredUnmatched = unmatchedFiberDetails.filter((a: any) =>
    !filterText || (a.ne || '').includes(filterText) || (a.name || '').includes(filterText)
  );

  // Use actual unmatched count for drawer
  const actualUnmatchedCount = unmatchedFiberDetails.length;

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
          <Col span={4}><Card size="small" hoverable onClick={() => setHitDrawerOpen(true)} style={{cursor:'pointer'}}>
            <Statistic title="光缆中断告警" value={fiberAlarmCount} suffix={<CheckCircleOutlined style={{ color: '#52c41a' }} />} />
            <div style={{fontSize:10,color:'#1890ff',marginTop:-8}}>点击查看明细</div>
          </Card></Col>
          <Col span={4}><Card size="small" hoverable onClick={() => setMissDrawerOpen(true)} style={{cursor:'pointer'}}>
            <Statistic title="未命中光缆中断" value={unmatchedAlarms.length} suffix={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />} />
            <div style={{fontSize:10,color:'#1890ff',marginTop:-8}}>点击查看明细</div>
          </Card></Col>
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
              <TopologyLinks nes={evNes} alarms={evAlarms} neTypes={ev.alarm_ne_types} />
              <Table size="small" bordered pagination={{pageSize:20,showSizeChanger:true,pageSizeOptions:['20','50','100']}} scroll={{ x: 1000 }}
                dataSource={evAlarms.map((a: any, j: number) => ({ ...a, key: j }))}
                columns={ALARM_COLUMNS}
              />
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

      {/* Hit alarms Drawer */}
      <Drawer title="命中告警明细" open={hitDrawerOpen} onClose={() => setHitDrawerOpen(false)} width="90%">
        <Tabs items={[
          { key: 'fiber', label: `光纤告警 (${fiberEvents.reduce((s: number, ev: any) => s + (ev.fiber_alarms || []).length, 0)}条)`,
            children: <Table size="small" bordered pagination={{pageSize:20,showSizeChanger:true}} scroll={{x:1000}}
              dataSource={fiberEvents.flatMap((ev: any) => (ev.fiber_alarms || []).map((a: any, j: number) => ({...a, key: `${ev.title}_${j}`})))}
              columns={ALARM_COLUMNS}
            />
          },
          { key: 'deriv', label: `衍生告警 (${fiberEvents.reduce((s: number, ev: any) => s + (ev.derivative_alarms || []).length, 0)}条)`,
            children: <Table size="small" bordered pagination={{pageSize:20,showSizeChanger:true}} scroll={{x:1000}}
              dataSource={fiberEvents.flatMap((ev: any) => (ev.derivative_alarms || []).map((a: any, j: number) => ({...a, key: `${ev.title}_${j}`})))}
              columns={ALARM_COLUMNS}
            />
          },
        ]} />
      </Drawer>

      {/* Miss alarms Drawer */}
      <Drawer title={`未命中光缆中断的告警 (${unmatchedAlarms.length} 条)`} open={missDrawerOpen} onClose={() => setMissDrawerOpen(false)} width="90%">
        <Table size="small" bordered pagination={{pageSize:20,showSizeChanger:true}} scroll={{x:1000}}
          dataSource={unmatchedAlarms.map((a: any, j: number) => ({...a, key: j}))}
          columns={ALARM_COLUMNS}
        />
      </Drawer>
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
                  网管: a.网管, 网元: a.网元, 告警对象: a.告警对象, 告警级别: a.告警级别,
                  告警名称: a.告警名称, 告警类型: a.告警类型, 告警描述: a.告警描述,
                  发生时间: a.发生时间, 关联业务: a.关联业务, 告警分析: a.告警分析,
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
