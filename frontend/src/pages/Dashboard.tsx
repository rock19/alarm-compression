import { useEffect, useState, useRef } from 'react';
import { Row, Col, Card, Statistic, Spin, message, Empty, DatePicker, Select, Button, Progress, Table, Tag } from 'antd';
import { AlertOutlined, NodeIndexOutlined, TagsOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

interface StatsData {
  total_alarms: number;
  total_nes: number;
  total_alarm_types: number;
  severity_distribution: Record<string, number>;
  top_alarm_names: { name: string; count: number }[];
  top_network_elements: { name: string; count: number }[];
  railway_distribution: Record<string, number>;
  time_range: { min: string; max: string };
}

export default function Dashboard() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialCheck, setInitialCheck] = useState(true);
  const [queryStart, setQueryStart] = useState<string>('');
  const [queryEnd, setQueryEnd] = useState<string>('');
  const [querySpec, setQuerySpec] = useState<string>('3');
  const [queryLoading, setQueryLoading] = useState(false);
  const [specOptions, setSpecOptions] = useState([
    { label: '传输系统', value: '3' }, { label: 'GSM-R', value: '4' },
    { label: '数据通信', value: '1' }, { label: '电源及环境监控', value: '9' },
    { label: '调度通信', value: '7' }, { label: '铁塔漏缆', value: '17' },
  ]);

  const [prog, setProg] = useState({ progress: 0, status: '', loaded: 0, page: 0, total_pages: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/alarm-specs')
      .then(r => r.json()).then(d => {
        if (d.specs?.length) setSpecOptions(d.specs.map((s: any) => ({ label: s.name, value: s.id })));
      }).catch(() => {});
  }, []);

  // On mount, check if backend already has data
  useEffect(() => {
    api.getStats()
      .then((s) => {
        if (s && (s as StatsData).total_alarms > 0) {
          setStats(s as StatsData);
        }
      })
      .catch(() => {})
      .finally(() => setInitialCheck(false));
  }, []);

  const [uploadInfo, setUploadInfo] = useState<{ raw: number; filtered: number; total: number } | null>(null);

  const handleApiQuery = async () => {
    if (!queryStart || !queryEnd) { message.warning('请选择起止日期'); return; }
    setQueryLoading(true);
    setProg({ progress: 0, status: '正在提交查询...', loaded: 0, page: 0, total_pages: 0 });
    try {
      const resp = await fetch(
        `http://localhost:8000/api/query-alarms?start_date=${queryStart}&end_date=${queryEnd}&spec_id=${querySpec}`,
        { method: 'POST' }
      );
      const r = await resp.json();
      if (r.error) { message.error(r.error); setQueryLoading(false); return; }
      if (!r.task_id) { setQueryLoading(false); return; }

      // Poll progress and completion
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const pr = await fetch(`http://localhost:8000/api/query-progress/${r.task_id}`).then(r => r.json());
          setProg({
            progress: pr.progress || 0,
            status: pr.status || '',
            loaded: pr.loaded || 0,
            page: pr.page || 0,
            total_pages: pr.total_pages || 0,
          });
          if (pr.status === 'done') {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            try {
              const s = await api.getStats() as StatsData;
              setStats(s);
            } catch {}
            setQueryLoading(false);
            message.success(`导入完成，获取 ${pr.loaded || 0} 条告警`);
          } else if (pr.status === 'failed') {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            message.error((pr as any).error || '查询失败');
            setQueryLoading(false);
          }
        } catch {}
      }, 500);
    } catch (e: any) {
      message.error(e.message);
      setQueryLoading(false);
    }
  };

  const handleUpload = async (files: FileList) => {
    setLoading(true);
    try {
      const result = await api.upload(files) as any;
      const s = await api.getStats() as StatsData;
      setStats(s);
      if (result.raw_total) {
        setUploadInfo({ raw: result.raw_total, filtered: result.filtered_count || 0, total: s.total_alarms });
      }
      const filterMsg = result.filtered_count ? `，过滤重复 ${result.filtered_count} 条` : '';
      message.success(`已加载 ${s.total_alarms} 条告警记录${filterMsg}`);
    } catch (e: any) {
      message.error(e.message);
    }
    setLoading(false);
  };

  if (initialCheck) {
    return <Spin style={{ display: 'block', marginTop: 100 }} />;
  }

  const severityPieOption = stats ? {
    title: { text: '告警级别分布', left: 'center', top: 0 },
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['40%', '70%'], top: 40,
      data: Object.entries(stats.severity_distribution).map(([k, v]) => ({ name: k, value: v })),
      label: { formatter: '{b}: {c}', fontSize: 11 },
    }],
  } : null;

  const barOption = stats ? {
    title: { text: '告警频次 Top 20', left: 'center' },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: stats.top_alarm_names.map(i => i.name).reverse(),
      axisLabel: { width: 150, overflow: 'truncate' },
    },
    series: [{ type: 'bar', data: stats.top_alarm_names.map(i => i.count).reverse() }],
    grid: { left: 180 },
  } : null;

  const neBarOption = stats ? {
    title: { text: '网元告警 Top 20', left: 'center' },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: stats.top_network_elements.map(i => i.name).reverse(),
      axisLabel: { width: 150, overflow: 'truncate' },
    },
    series: [{ type: 'bar', data: stats.top_network_elements.map(i => i.count).reverse() }],
    grid: { left: 180 },
  } : null;

  return (
    <Spin spinning={loading}>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row align="middle" gutter={16}>
          <Col flex="auto">
            {stats
              ? <span>导入 <b>{uploadInfo?.raw || stats.total_alarms}</b> 条，过滤重复 <b>{uploadInfo?.filtered || 0}</b> 条，保留 <b>{stats.total_alarms}</b> 条 | <b>{stats.total_nes}</b> 个网元，<b>{stats.total_alarm_types}</b> 种类型</span>
              : <span style={{ color: '#999' }}>暂无数据，请上传历史告警 Excel 文件</span>
            }
          </Col>
          <Col>
            <span style={{ fontSize: 12, marginRight: 8 }}>导入历史告警文件：</span>
            <input type="file" accept=".xlsx" multiple onChange={e => {
              const files = e.target.files;
              if (files && files.length > 0) {
                handleUpload(files);
              }
            }} />
          </Col>
        </Row>
        <Row style={{ marginTop: 8 }} align="middle" gutter={8}>
          <Col><span style={{ fontSize: 12 }}>或通过API查询：</span></Col>
          <Col><DatePicker size="small" placeholder="起始日期" onChange={(d) => setQueryStart(d?.format('YYYY-MM-DD') || '')} /></Col>
          <Col><DatePicker size="small" placeholder="结束日期" onChange={(d) => setQueryEnd(d?.format('YYYY-MM-DD') || '')} /></Col>
          <Col><Select size="small" value={querySpec} onChange={setQuerySpec} style={{ width: 140 }} options={specOptions} /></Col>
          <Col><Button size="small" type="primary" icon={<SearchOutlined />} loading={queryLoading} onClick={handleApiQuery}>导入</Button></Col>
        </Row>
        {(loading || queryLoading) && (
          <Row style={{ marginTop: 8 }}>
            <Col span={24}>
              <Progress percent={queryLoading ? prog.progress : undefined}
                status={queryLoading ? 'active' : undefined}
                format={() => {
                  if (!queryLoading) return '处理中...';
                  const p = prog;
                  let label = p.status || '准备中...';
                  // Only add page/loaded info if not already in status text
                  if (!label.includes('页') && p.page > 0 && p.total_pages > 0) label += ` (第${p.page}/${p.total_pages}页)`;
                  if (!label.includes('条') && p.loaded > 0) label += ` ${p.loaded}条`;
                  return label;
                }}
              />
            </Col>
          </Row>
        )}
      </Card>

      {!stats ? (
        <Empty description="上传历史告警数据后展示仪表盘" style={{ marginTop: 80 }} />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col span={8}><Card><Statistic title="告警总数" value={stats.total_alarms} prefix={<AlertOutlined />} /></Card></Col>
            <Col span={8}><Card><Statistic title="网元数量" value={stats.total_nes} prefix={<NodeIndexOutlined />} /></Card></Col>
            <Col span={8}><Card>
              <Statistic title="告警类型" value={stats.total_alarm_types} prefix={<TagsOutlined />} />
            </Card></Col>
          </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}><Card><ReactECharts option={severityPieOption} /></Card></Col>
        <Col span={12}><Card><ReactECharts option={barOption} /></Card></Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}><Card><ReactECharts option={neBarOption} /></Card></Col>
      </Row>

          <AlarmPreviewTable />
        </>
      )}
    </Spin>
  );
}

function AlarmPreviewTable() {
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`http://localhost:8000/api/alarm-preview?page=${page}&page_size=50`)
      .then(r => r.json()).then(d => { setData(d.rows || []); setTotal(d.total); setLoading(false); })
      .catch(() => setLoading(false));
  }, [page]);

  const handleExport = () => {
    window.open('http://localhost:8000/api/export-alarms?limit=50000', '_blank');
  };

  if (total === 0) return null;

  return (
    <Card
      title={<span>告警数据预览 (共 {total} 条)</span>}
      extra={<Button icon={<DownloadOutlined />} onClick={handleExport}>导出Excel</Button>}
      style={{ marginTop: 16 }}
    >
      <Table size="small" pagination={{ current: page, pageSize: 50, total, onChange: setPage }}
        loading={loading}
        dataSource={data.map((r, i) => ({ ...r, key: i }))}
        columns={[
          { title: '网管', dataIndex: 'network_manager', width: 110, ellipsis: true },
          { title: '网元', dataIndex: 'ne_name', width: 160, ellipsis: true },
          { title: '告警对象', dataIndex: 'alarm_object', width: 180, ellipsis: true },
          { title: '告警名称', dataIndex: 'alarm_name', width: 180, ellipsis: true },
          { title: '告警描述', dataIndex: 'alarm_desc', width: 150, ellipsis: true },
          { title: '级别', dataIndex: 'severity', width: 80,
            render: (v: string) => <Tag color={v?.includes('紧急') ? 'red' : v?.includes('主要') ? 'orange' : 'blue'}>{v}</Tag> },
          { title: '发生时间', dataIndex: 'occur_time', width: 160, render: (v: string) => (v||'').replace('T',' ') },
          { title: '铁路线', dataIndex: 'railway', width: 80 },
        ]}
      />
    </Card>
  );
}
