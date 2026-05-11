import { useEffect, useState } from 'react';
import {
  Card, Table, InputNumber, Button, Space, Tag, Tabs,
  Input, message, Spin, Empty, Row, Col, Collapse, Typography, Divider,
} from 'antd';
import { LoadingOutlined } from '@ant-design/icons';
import { SearchOutlined, PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { api } from '../api/client';

const { Text, Paragraph } = Typography;

interface Rule {
  antecedent: string[];
  consequent: string[];
  support: number;
  confidence: number;
  lift: number;
}

function explainRule(r: Rule) {
  const ant = r.antecedent.join('、');
  const con = r.consequent.join('、');
  const sPct = (r.support * 100).toFixed(2);
  const cPct = (r.confidence * 100).toFixed(2);

  const dataExplain = [
    `支持度 ${r.support.toFixed(4)}：在所有 ${Math.round(r.antecedent.length + r.consequent.length)} 个告警构成的事务中，"${ant}" 与 "${con}" 同时出现的比例为 ${sPct}%。`,
    `置信度 ${r.confidence.toFixed(4)}：当 "${ant}" 出现时，${cPct}% 的情况下 "${con}" 也会出现。`,
    `提升度 ${r.lift.toFixed(2)}：${r.lift > 1 ? `${r.lift > 3 ? '远' : ''}大于 1` : '小于等于 1'}，说明前件的出现${r.lift > 1 ? '显著提升了' : r.lift < 1 ? '反而降低了' : '对'}后件的发生概率${r.lift > 1 ? '' : '无正向影响'}。`,
  ].join('\n');

  let bizInterpret: string;
  if (r.lift > 3 && r.confidence > 0.7) {
    bizInterpret = `强关联规则。${ant} 发生后，${con} 几乎必然伴随出现，建议将二者纳入同一告警压缩策略，或排查是否存在共同的根因（如网络设备故障、链路中断等）。`;
  } else if (r.lift > 1.5 && r.confidence > 0.5) {
    bizInterpret = `中等关联规则。${ant} 与 ${con} 存在较明显的伴随关系，可考虑在告警聚合时将二者归为一组，减少重复派单。`;
  } else if (r.lift > 1) {
    bizInterpret = `弱关联规则。${ant} 对 ${con} 有一定提示作用，但置信度有限，不建议作为强制压缩依据，可作为参考辅助判断。`;
  } else {
    bizInterpret = `无显著正向关联。${ant} 的出现并未提升 ${con} 的发生概率，该规则可能由随机共现产生，建议忽略或调整参数重新挖掘。`;
  }

  return { dataExplain, bizInterpret };
}

function AiAnalysis({ record, dataExplain, bizInterpret, index }: {
  record: Rule;
  dataExplain: string;
  bizInterpret: string;
  index: number;
}) {
  const [aiResult, setAiResult] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiPrompt, setAiPrompt] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setAiLoading(true);
    setAiResult(null);
    setAiPrompt(null);
    try {
      const res = await api.analyzeRule({
        antecedent: record.antecedent,
        consequent: record.consequent,
        support: record.support,
        confidence: record.confidence,
        lift: record.lift,
        data_explain: dataExplain,
        biz_interpret: bizInterpret,
      }) as { analysis: string; prompt: string };
      setAiResult(res.analysis);
      setAiPrompt(res.prompt);
    } catch (e: any) {
      message.error(e.message);
    }
    setAiLoading(false);
  };

  return (
    <Card
      size="small"
      title="🤖 AI 分析"
      style={{ background: '#f9f0ff' }}
      extra={
        <Button
          type="primary"
          size="small"
          icon={aiLoading ? <LoadingOutlined /> : undefined}
          loading={aiLoading}
          onClick={handleAnalyze}
        >
          调用大模型分析
        </Button>
      }
    >
      {aiResult ? (
        <Row gutter={[16, 0]}>
          <Col span={16}>
            <Paragraph style={{ margin: 0, fontSize: 13, whiteSpace: 'pre-line', lineHeight: 1.8 }}>
              {aiResult}
            </Paragraph>
          </Col>
          <Col span={8}>
            <Collapse size="small" ghost
              items={[{
                key: 'prompt',
                label: <Text type="secondary" style={{ fontSize: 12 }}>查看提示词</Text>,
                children: (
                  <Paragraph style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto', background: '#fff', padding: 8, borderRadius: 4 }}>
                    {aiPrompt}
                  </Paragraph>
                ),
              }]}
            />
          </Col>
        </Row>
      ) : (
        <Text type="secondary" style={{ fontSize: 13 }}>
          点击按钮，将规则数据、算法解释和业务解析发送给大模型，获取约 200 字的专业分析。
        </Text>
      )}
    </Card>
  );
}

export default function Rules() {
  const [params, setParams] = useState({
    time_window_seconds: 300, min_support: 0.01, min_confidence: 1.0, threshold_ratio: 0.2,
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

      <Collapse style={{ marginBottom: 16 }}
        items={[
          {
            key: 'explain',
            label: <><InfoCircleOutlined style={{ marginRight: 8 }} />支持度、置信度、提升度及关联规则算法解释</>,
          children: (
            <div style={{ padding: '8px 0' }}>
              <Paragraph style={{ marginBottom: 12 }}>
                <Text strong>算法原理</Text> — 关联规则挖掘基于 <Text code>FP-Growth</Text>（频繁模式增长）算法。先将告警按网元和时间窗口（滑动窗口）分组为“事务”，再从事务中提取频繁项集（高频共现的告警组合），最后从频繁项集中生成关联规则（A → B 形式）。
              </Paragraph>
              <Row gutter={[16, 12]}>
                <Col span={12}>
                  <Card size="small" title={<Text strong>支持度 Support</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0 }}>
                      公式：<Text code>support(A→B) = count(A∪B) / 总事务数</Text><br />
                      含义：前件和后件<Text strong>同时出现</Text>的事务数占总事务的比例。值越高，说明该组合在历史数据中越频繁，统计意义越可靠。通常设置最小支持度阈值过滤偶发组合。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title={<Text strong>置信度 Confidence</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0 }}>
                      公式：<Text code>confidence(A→B) = count(A∪B) / count(A)</Text><br />
                      含义：在前件 A 出现的<Text strong>前提下</Text>，后件 B 也出现的条件概率。值越高，说明前件对后件的预测能力越强。通常设置最小置信度阈值保证规则的推导可靠性。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title={<Text strong>提升度 Lift</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0 }}>
                      公式：<Text code>lift(A→B) = confidence(A→B) / support(B)</Text><br />
                      含义：衡量前件 A 的出现是否<Text strong>提升</Text>了后件 B 的发生概率。
                      <Text type="success">Lift &gt; 1</Text> 为正相关（A 提升了 B 的概率），
                      <Text type="danger">Lift &lt; 1</Text> 为负相关（A 降低了 B 的概率），
                      <Text>Lift ≈ 1</Text> 表示 A 和 B 相互独立。提升度越高，规则的业务价值越大。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" title={<Text strong>关联规则评估</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0 }}>
                      一条有效的关联规则通常需要<Text strong>三重验证</Text>：
                      <br />① 支持度达标 — 组合不是偶发事件
                      <br />② 置信度达标 — 前件确实能推导后件
                      <br />③ 提升度 &gt; 1 — 排除因后件本身高发导致的虚假高置信度
                      <br />三项指标互相制衡，避免单一指标造成的误判。
                    </Paragraph>
                  </Card>
                </Col>
              </Row>
            </div>
          ),
        },
        {
          key: 'rounds-explain',
          label: <><InfoCircleOutlined style={{ marginRight: 8 }} />全部、全量挖掘、分层挖掘的区别与意义</>,
          children: (
            <div style={{ padding: '8px 0' }}>
              <Paragraph style={{ marginBottom: 12 }}>
                <Text strong>两轮挖掘策略</Text> — FP-Growth 算法执行<Text strong>两轮</Text>关联规则挖掘，通过分层设计兼顾宏观覆盖率与微观可执行性。
              </Paragraph>
              <Row gutter={[16, 12]}>
                <Col span={8}>
                  <Card size="small" title={<Text strong>全量挖掘（Round 1）</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                      <Text>直接对所有事务运行 FP-Growth，不做任何过滤。</Text><br /><br />
                      <Text strong>特点</Text>：规则数量多、覆盖广，能完整呈现告警生态的全貌，但结果易被高频泛在告警（如 <Text code>License即将过期</Text>、<Text code>HTTP客户端链接故障</Text>）主导——这些告警几乎在所有网元中频繁出现，会与大量其他告警产生关联，<Text type="danger">淹没真正有业务价值的特定故障链</Text>。<br /><br />
                      <Text strong>适用场景</Text>：宏观掌握网络整体告警模式，了解哪些告警在全网范围内高频共现。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" title={<Text strong>分层挖掘（Round 2）</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                      <Text>先用 <Text code>threshold_ratio</Text>（默认 20%）过滤高频告警，再从剩余事务中运行 FP-Growth。</Text><br /><br />
                      <Text strong>过滤逻辑</Text>：当某个告警名称出现在<Text strong>超过 threshold_ratio 比例的事务</Text>中时，该告警被从第二轮事务中移除。例如 threshold_ratio=0.2 表示出现在 20% 以上事务中的告警被视为"背景噪声"。<br /><br />
                      <Text strong>特点</Text>：规则数量少但更聚焦，<Text type="success">去除了泛在告警的干扰，暴露出被掩盖的特定故障链</Text>（如特定设备的板卡级故障组合）。<br /><br />
                      <Text strong>适用场景</Text>：定位特定根因，制定可执行的告警压缩策略。
                    </Paragraph>
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" title={<Text strong>全部视图</Text>}>
                    <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                      <Text>将全量挖掘和分层挖掘的结果<Text strong>合并展示</Text>，提供完整的规则列表。</Text><br /><br />
                      <Text strong>查看建议</Text>：
                      <br />• 管理层 / 报表场景 → 看<Text strong>全量挖掘</Text>，关注告警全景
                      <br />• 运维排障场景 → 看<Text strong>分层挖掘</Text>，聚焦特定故障链
                      <br />• 全局搜索/导出场景 → 看<Text strong>全部</Text>，不遗漏任何规则
                      <br /><br />
                      <Text strong>核心区别总结</Text>：
                      <br />两轮挖掘不是优劣关系，而是<Text type="success">互补关系</Text>。全量挖掘提供广度（不能漏），分层挖掘提供精度（不能杂）。若分层挖掘产出的规则数仍很大，可降低 threshold_ratio 提高过滤强度；若分层挖掘无结果，可增大 threshold_ratio 或放宽支持度。
                    </Paragraph>
                  </Card>
                </Col>
              </Row>
            </div>
          ),
        },
      ]}
      />

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
          expandable={{
            expandedRowRender: (record: Rule, index: number) => {
              const { dataExplain, bizInterpret } = explainRule(record);
              return (
                <div style={{ padding: '8px 24px', background: '#fafafa', borderRadius: 4 }}>
                  <Row gutter={[16, 8]}>
                    <Col span={12}>
                      <Card size="small" title="数据算法解释" style={{ background: '#f0f5ff' }}>
                        <Paragraph style={{ margin: 0, whiteSpace: 'pre-line', fontSize: 13 }}>
                          {dataExplain}
                        </Paragraph>
                      </Card>
                    </Col>
                    <Col span={12}>
                      <Card size="small" title="业务解析" style={{ background: '#fff7e6' }}>
                        <Paragraph style={{ margin: 0, fontSize: 13 }}>
                          {bizInterpret}
                        </Paragraph>
                      </Card>
                    </Col>
                  </Row>
                  <Divider style={{ margin: '12px 0' }} />
                  <Row>
                    <Col span={24}>
                      <AiAnalysis record={record} dataExplain={dataExplain} bizInterpret={bizInterpret} index={index} />
                    </Col>
                  </Row>
                </div>
              );
            },
            rowExpandable: () => true,
          }}
        />
      </Card>
    </div>
  );
}
