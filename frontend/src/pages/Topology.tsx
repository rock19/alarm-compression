import { useEffect, useState } from 'react';
import { Card, Spin, Empty, message, Upload, Button, Space, Tag } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

interface GraphData {
  nodes: { id: string; name: string; type: string }[];
  edges: { source: string; target: string; type: string; weight?: number; style: string; link_type?: string }[];
}

const buildGraphOption = (data: GraphData) => ({
  title: { text: '网元告警关联拓扑', left: 'center' },
  legend: {
    data: ['物理网元', '网元', '告警'],
    bottom: 0,
  },
  tooltip: {
    trigger: 'item' as const,
    formatter: (p: any) => {
      if (p.dataType === 'edge') {
        const ed = p.data.data;
        const srcName = ed.source?.replace?.('alarm:', '') || ed.source;
        const tgtName = ed.target?.replace?.('alarm:', '') || ed.target;
        if (ed.type === 'physical') {
          return `<b>物理链路</b><br/>${srcName} ↔ ${tgtName}<br/>链路类型: ${ed.link_type || '-'}`;
        }
        return `<b>告警关联</b><br/>${srcName} → ${tgtName}<br/>提升度: ${(ed.weight || 0).toFixed(2)}`;
      }
      const nd = p.data.data || p.data;
      const typeMap: Record<string, string> = { physical: '物理网元', ne: '网元', alarm: '告警' };
      return `<b>${nd.name || p.name}</b><br/>类型: ${typeMap[nd.type] || nd.type || '-'}`;
    },
  },
  series: [{
    type: 'graph',
    layout: 'force',
    roam: true,
    draggable: true,
    force: { repulsion: 300, edgeLength: [150, 300] },
    data: data.nodes.map(n => ({
      name: n.id,
      value: n.name,
      symbolSize: n.type === 'alarm' ? 20 : n.type === 'ne' ? 35 : 30,
      category: n.type === 'physical' ? 0 : n.type === 'ne' ? 1 : 2,
      itemStyle: { color: n.type === 'physical' ? '#5470c6' : n.type === 'ne' ? '#91cc75' : '#ee6666' },
      data: n,
    })),
    categories: [{ name: '物理网元' }, { name: '网元' }, { name: '告警' }],
    edges: data.edges.map(e => ({
      source: e.source,
      target: e.target,
      lineStyle: {
        type: e.style as 'dashed' | 'solid',
        width: Math.min(6, Math.max(1, 1 + Math.log10((e.weight || 1) + 1) * 3)),
        color: e.type === 'physical' ? '#5470c6' : '#ee6666',
      },
      data: e,
    })),
    label: {
      show: true,
      fontSize: 10,
      overflow: 'truncate',
      width: 100,
      formatter: (p: any) => {
        const v = p.data?.value || p.value || p.name || '';
        return v.length > 12 ? v.slice(0, 12) + '...' : v;
      },
    },
  }],
});

export default function Topology() {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getTopology()
      .then(g => { setGraph(g as GraphData); setLoading(false); })
      .catch(e => { message.error(e.message); setLoading(false); });
  }, []);

  const handleUploadTopology = async (file: File) => {
    const text = await file.text();
    try {
      const links = JSON.parse(text);
      await api.uploadTopology(links);
      message.success(`已上传 ${links.length} 条物理链路`);
      const g = await api.getTopology() as GraphData;
      setGraph(g);
    } catch (e: any) { message.error('JSON 解析失败: ' + e.message); }
    return false;
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 100 }} />;
  if (!graph || graph.nodes.length === 0) return <Empty description="无拓扑数据，请先运行FP-Growth" />;

  return (
    <Card
      title="拓扑视图"
      extra={
        <Space>
          <Tag color="blue">虚线 = 物理链路</Tag>
          <Tag color="red">实线 = 告警关联</Tag>
          <Upload accept=".json" showUploadList={false} beforeUpload={handleUploadTopology}>
            <Button icon={<UploadOutlined />} size="small">上传物理拓扑</Button>
          </Upload>
        </Space>
      }
    >
      <ReactECharts option={buildGraphOption(graph)} style={{ height: 650 }} />
    </Card>
  );
}
