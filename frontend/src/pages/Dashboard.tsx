import { useEffect, useState } from 'react';
import { Row, Col, Card, Statistic, Spin, message, Alert } from 'antd';
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

  const handleUpload = async (f: File) => {
    setLoading(true);
    try {
      await api.upload(f);
      const s = await api.getStats() as StatsData;
      setStats(s);
      message.success(`已加载 ${s.total_alarms} 条告警记录`);
    } catch (e: any) {
      message.error(e.message);
    }
    setLoading(false);
  };

  if (!stats) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 100 }}>
        <Alert
          type="info"
          message="请上传告警数据文件"
          description={<input type="file" accept=".xlsx" onChange={e => {
            const f = e.target.files?.[0];
            if (f) handleUpload(f);
          }} />}
          style={{ maxWidth: 500, margin: '0 auto' }}
        />
      </div>
    );
  }

  const severityPieOption = {
    title: { text: '告警级别分布', left: 'center' },
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      data: Object.entries(stats.severity_distribution).map(([k, v]) => ({ name: k, value: v })),
      label: { formatter: '{b}: {c}' },
    }],
  };

  const barOption = {
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
  };

  const neBarOption = {
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
  };

  return (
    <Spin spinning={loading}>
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
    </Spin>
  );
}
