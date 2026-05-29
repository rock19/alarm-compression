import { useEffect, useState } from 'react';
import { Collapse, Tag, Typography, Table, Switch } from 'antd';
import ReactECharts from 'echarts-for-react';
import { api } from '../api/client';

export default function TopologyLinks({ nes, alarms }: { nes: string[]; alarms?: any[] }) {
  const [links, setLinks] = useState<any[] | null>(null);
  const [fullNes, setFullNes] = useState<string[]>(nes);
  const [hideHealthy, setHideHealthy] = useState(false);

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

  const adj: Record<string, string[]> = {};
  filteredLinks.forEach((l: any) => {
    adj[l.source] = adj[l.source] || []; adj[l.source].push(l.target);
    adj[l.target] = adj[l.target] || []; adj[l.target].push(l.source);
  });
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

  // Adapt layout to node count to avoid overlap
  const nodeCount = fullNes.length;
  const isLarge = nodeCount > 30;
  const chartHeight = Math.max(400, nodeCount * (isLarge ? 18 : 24));

  // Pre-compute filtered view for "hide healthy" mode
  let displayNes = fullNes.length;
  let displayLinks = filteredLinks.length;
  let displayFilteredLinks = filteredLinks;
  let displayVisibleNes: Set<string> | null = null;
  if (hideHealthy) {
    const hasAlarmBelow = (ne: string, seen: Set<string>): boolean => {
      if (seen.has(ne)) return false;
      seen.add(ne);
      if (alarmedNes.has(ne)) return true;
      return (adj[ne] || []).some(p => hasAlarmBelow(p, seen));
    };
    const visibleSet = new Set<string>();
    const walk = (ne: string, seen: Set<string>) => {
      if (seen.has(ne)) return;
      seen.add(ne);
      if (alarmedNes.has(ne) || hasAlarmBelow(ne, new Set([...seen]))) {
        visibleSet.add(ne);
        (adj[ne] || []).forEach(p => walk(p, seen));
      }
    };
    neOrder.forEach(n => walk(n, new Set()));
    displayNes = visibleSet.size;
    displayVisibleNes = visibleSet;
    displayFilteredLinks = filteredLinks.filter(l => visibleSet.has(l.source) && visibleSet.has(l.target));
    displayLinks = displayFilteredLinks.length;
  }

  return (
    <Collapse size="small" ghost style={{ marginTop: 4 }}
      items={[{
        key: 'topo',
        label: <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          网元物理拓扑 ({displayLinks} 条链路, {displayNes} 个网元{hideHealthy ? ', 已隐藏无告警' : ''})
          <span style={{ marginLeft: 8 }}>
            <Tag color="red" style={{fontSize:10}}>紧急</Tag>
            <Tag color="orange" style={{fontSize:10}}>主要</Tag>
            <Tag color="gold" style={{fontSize:10}}>次要</Tag>
            <Tag color="blue" style={{fontSize:10}}>提示</Tag>
            <Tag color="green" style={{fontSize:10}}>无告警</Tag>
          </span>
          <span style={{ marginLeft: 12 }}>
            <Switch size="small" checked={hideHealthy} onChange={setHideHealthy}
              checkedChildren="仅告警" unCheckedChildren="全部" />
          </span>
        </Typography.Text>,
        children: (
          <>
            <ReactECharts option={(() => {
              const rootNe = neOrder.find(n => alarmedNes.has(n)) || neOrder[0];
              const visited = new Set<string>();

              const buildTree = (ne: string, depth: number): any => {
                if (visited.has(ne)) return null;
                if (hideHealthy && displayVisibleNes && !displayVisibleNes.has(ne)) return null;
                visited.add(ne);
                const info = neInfo[ne];
                const hasAlarm = alarmedNes.has(ne);
                const children: any[] = [];
                (adj[ne] || []).forEach(peer => {
                  const child = buildTree(peer, depth + 1);
                  if (child) children.push(child);
                });
                return {
                  name: ne,
                  children: children.length > 0 ? children : undefined,
                  itemStyle: { color: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderColor: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderWidth: isLarge ? 1 : 2 },
                  alarmDetails: info?.alarmDetails || [],
                  hasAlarm, _info: info,
                };
              };
              const treeData = buildTree(rootNe, 0);
              const extraRoots: any[] = [];
              neOrder.forEach(n => {
                if (!visited.has(n)) {
                  const info = neInfo[n];
                  const hasAlarm = alarmedNes.has(n);
                  extraRoots.push({
                    name: n,
                    itemStyle: { color: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderColor: hasAlarm ? (info?.color || '#d46b08') : '#91cc75', borderWidth: isLarge ? 1 : 2 },
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
                  top: 10, left: 10, bottom: 10, right: 40,
                  symbol: 'circle',
                  symbolSize: isLarge ? 8 : 12,
                  roam: true,
                  expandAndCollapse: true,
                  initialTreeDepth: -1,
                  orient: 'LR',
                  layout: 'orthogonal',
                  edgeShape: 'curve',
                  label: {
                    position: 'bottom', verticalAlign: 'top', align: 'center',
                    fontSize: isLarge ? 8 : 10, distance: isLarge ? 3 : 6,
                    formatter: (p: any) => {
                      const maxLen = isLarge ? 12 : 18;
                      const n = p.name.length > maxLen ? p.name.slice(0,maxLen)+'...' : p.name;
                      const d = p.data; const cnt = d.alarmDetails?.length || 0;
                      const label = cnt > 0 ? `${n}(${cnt})` : n;
                      if (!d.hasAlarm) return isLarge ? `{ne|${label}}` : `{ne|${label}}\n{ok|✓无告警}`;
                      if (isLarge) return `{ne|${label}}`;
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
            })()} style={{ height: chartHeight }} />
            <Collapse size="small" ghost
              items={[{
                key: 'link-table',
                label: <Typography.Text type="secondary" style={{ fontSize: 11 }}>链路端口明细 ({displayLinks} 条)</Typography.Text>,
                children: (
                  <Table size="small" pagination={false}
                    dataSource={displayFilteredLinks.map((l: any, i: number) => ({ ...l, key: i }))}
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
