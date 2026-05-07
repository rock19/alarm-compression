import { useEffect, useState } from 'react';
import { Card, Spin, Empty, message, Select } from 'antd';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

interface TimePoint { time: string; count: number; }
interface StatsData {
  total_alarms: number;
  time_range: { min: string; max: string };
  top_alarm_names: { name: string; count: number }[];
  time_series: TimePoint[];
  alarm_time_series: Record<string, TimePoint[]>;
}

export default function Timeline() {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedAlarm, setSelectedAlarm] = useState<string | null>(null);

  useEffect(() => {
    api.getStats()
      .then(s => { setStats(s as StatsData); setLoading(false); })
      .catch(e => { message.error(e.message); setLoading(false); });
  }, []);

  if (loading) return <Spin style={{ display: 'block', marginTop: 100 }} />;
  if (!stats) return <Empty description="请先上传数据" />;

  const overallData = stats.time_series.map(p => [p.time, p.count] as [string, number]);

  const overallOption = {
    title: { text: '全量告警时间分布（按小时聚合）', left: 'center' },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'time', name: '时间' },
    yAxis: { type: 'value', name: '告警数量' },
    dataZoom: [{ type: 'slider', start: 0, end: 100 }],
    series: [{
      type: 'line', smooth: true, name: '告警数',
      data: overallData,
      markLine: { silent: true, data: [{ type: 'average', name: '均值' }] },
    }],
  };

  const alarmNameList = selectedAlarm
    ? [selectedAlarm]
    : stats.top_alarm_names.slice(0, 10).map(a => a.name);

  const selectedOption = {
    title: { text: selectedAlarm ? `${selectedAlarm} 趋势` : 'Top 10 告警类型趋势', left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', bottom: 0 },
    xAxis: { type: 'time', name: '时间' },
    yAxis: { type: 'value', name: '告警数量' },
    dataZoom: [{ type: 'slider', start: 0, end: 100 }],
    series: alarmNameList.map(name => ({
      type: 'line' as const, smooth: true, name,
      data: (stats.alarm_time_series[name] || []).map(p => [p.time, p.count] as [string, number]),
    })),
  };

  return (
    <div>
      <Card title="全量告警时间分布" style={{ marginBottom: 16 }}>
        <ReactECharts option={overallOption} style={{ height: 400 }} />
      </Card>
      <Card title="分告警类型趋势">
        <Select
          style={{ width: 400, marginBottom: 16 }}
          placeholder="选择告警类型查看趋势（不选则显示 Top 10）"
          allowClear showSearch
          options={stats.top_alarm_names.map(a => ({ label: `${a.name} (${a.count})`, value: a.name }))}
          onChange={setSelectedAlarm}
        />
        <ReactECharts option={selectedOption} style={{ height: 400 }} />
      </Card>
    </div>
  );
}
