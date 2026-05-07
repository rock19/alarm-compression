import { useEffect, useState } from 'react';
import {
  Card, Table, InputNumber, Button, Space, Tag, Tabs,
  Input, message, Spin, Empty, Row, Col,
} from 'antd';
import { SearchOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { api } from '../api/client';

interface Rule {
  antecedent: string[];
  consequent: string[];
  support: number;
  confidence: number;
  lift: number;
}

export default function Rules() {
  const [params, setParams] = useState({
    time_window_seconds: 300, min_support: 0.01, min_confidence: 0.5, threshold_ratio: 0.2,
  });
  const [rules, setRules] = useState<Rule[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [computed, setComputed] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [activeRound, setActiveRound] = useState('all');

  const fetchRules = async () => {
    setLoading(true);
    try {
      const res = await api.getRules({ round: activeRound, page, page_size: 20, search, sort_by: 'lift', sort_order: 'desc' }) as { rules: Rule[]; total: number };
      setRules(res.rules);
      setTotal(res.total);
    } catch (e: any) { message.error(e.message); }
    setLoading(false);
  };

  const runFpgrowth = async () => {
    setLoading(true);
    try {
      await api.runFpgrowth(params);
      setComputed(true);
      message.success('FP-Growth 计算完成');
      fetchRules();
    } catch (e: any) { message.error(e.message); }
    setLoading(false);
  };

  useEffect(() => { if (computed) fetchRules(); }, [page, activeRound, search]);

  const columns = [
    {
      title: '前件', dataIndex: 'antecedent',
      render: (v: string[]) => v.map((s, i) => <Tag key={i} color="blue">{s}</Tag>),
    },
    {
      title: '后件', dataIndex: 'consequent',
      render: (v: string[]) => v.map((s, i) => <Tag key={i} color="orange">{s}</Tag>),
    },
    {
      title: '支持度', dataIndex: 'support', width: 90,
      render: (v: number) => v.toFixed(4),
      sorter: (a: Rule, b: Rule) => a.support - b.support,
    },
    {
      title: '置信度', dataIndex: 'confidence', width: 90,
      render: (v: number) => v.toFixed(4),
      sorter: (a: Rule, b: Rule) => a.confidence - b.confidence,
    },
    {
      title: '提升度', dataIndex: 'lift', width: 90,
      render: (v: number) => (
        <span style={{ color: v > 2 ? '#cf1322' : '#333', fontWeight: v > 2 ? 700 : 400 }}>
          {v.toFixed(2)}
        </span>
      ),
      sorter: (a: Rule, b: Rule) => a.lift - b.lift,
    },
  ];

  return (
    <div>
      <Card title="算法参数" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col span={6}>
            <span>时间窗口(秒): </span>
            <InputNumber min={10} max={3600} value={params.time_window_seconds}
              onChange={v => setParams(p => ({ ...p, time_window_seconds: v || 300 }))} />
          </Col>
          <Col span={6}>
            <span>最小支持度: </span>
            <InputNumber min={0.001} max={1} step={0.01} value={params.min_support}
              onChange={v => setParams(p => ({ ...p, min_support: v || 0.01 }))} />
          </Col>
          <Col span={6}>
            <span>最小置信度: </span>
            <InputNumber min={0.1} max={1} step={0.1} value={params.min_confidence}
              onChange={v => setParams(p => ({ ...p, min_confidence: v || 0.5 }))} />
          </Col>
          <Col span={6}>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={runFpgrowth} loading={loading}>
              运行 FP-Growth
            </Button>
          </Col>
        </Row>
      </Card>

      <Card title="关联规则">
        <Space style={{ marginBottom: 16 }}>
          <Tabs activeKey={activeRound} onChange={setActiveRound}
            items={[
              { key: 'all', label: '全部' },
              { key: 'full', label: '全量挖掘' },
              { key: 'filtered', label: '分层挖掘(去高频)' },
            ]}
          />
          <Input prefix={<SearchOutlined />} placeholder="搜索告警名称..."
            value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            style={{ width: 300 }} />
        </Space>

        <Table
          columns={columns}
          dataSource={rules.map((r, i) => ({ ...r, key: i }))}
          loading={loading}
          locale={{ emptyText: computed ? <Empty description="当前参数下无关联规则" /> : <Empty description="请先运行FP-Growth" /> }}
          pagination={{
            current: page, pageSize: 20, total,
            onChange: (p) => setPage(p),
            showTotal: (t) => `共 ${t} 条规则`,
          }}
          size="small"
        />
      </Card>
    </div>
  );
}
