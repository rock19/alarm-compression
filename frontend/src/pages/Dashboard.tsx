import { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Spin, message, Empty } from 'antd';
import { AlertOutlined, NodeIndexOutlined, TagsOutlined } from '@ant-design/icons';
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

  const handleUpload = async (files: FileList) => {
    setLoading(true);
    try {
      const result = await api.upload(files) as any;
      const s = await api.getStats() as StatsData;
      setStats(s);
      message.success(`已加载 ${s.total_alarms} 条告警记录`);
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
              ? <span>已加载 <b>{stats.total_alarms}</b> 条告警，<b>{stats.total_nes}</b> 个网元，<b>{stats.total_alarm_types}</b> 种类型</span>
              : <span style={{ color: '#999' }}>暂无数据，请上传历史告警 Excel 文件</span>
            }
          </Col>
          <Col>
            <input type="file" accept=".xlsx" multiple onChange={e => {
              const files = e.target.files;
              if (files && files.length > 0) {
                handleUpload(files);
              }
            }} />
          </Col>
        </Row>
      </Card>

      {!stats ? (
        <Empty description="上传历史告警数据后展示仪表盘" style={{ marginTop: 80 }} />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col span={8}><Card><Statistic title="告警总数" value={stats.total_alarms} prefix={<AlertOutlined />} /></Card></Col>
            <Col span={8}><Card><Statistic title="网元数量" value={stats.total_nes} prefix={<NodeIndexOutlined />} /></Card></Col>
            <Col span={8}><Card><Statistic title="告警类型" value={stats.total_alarm_types} prefix={<TagsOutlined />} /></Card></Col>
          </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={12}><Card><ReactECharts option={severityPieOption} /></Card></Col>
        <Col span={12}><Card><ReactECharts option={barOption} /></Card></Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}><Card><ReactECharts option={neBarOption} /></Card></Col>
      </Row>

        </>
      )}
    </Spin>
  );
}
