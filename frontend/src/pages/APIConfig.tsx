import { useEffect, useState } from 'react';
import { Card, Form, Input, Button, message, Spin, Divider, Alert, Space } from 'antd';
import { SaveOutlined, SettingOutlined, KeyOutlined, SearchOutlined } from '@ant-design/icons';

interface ConfigData {
  username: string;
  password: string;
  base_url: string;
  port: string;
  token: string;
  page_size: number;
}

export default function APIConfig() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ type: 'success' | 'error'; title: string; msg: string } | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    fetch('http://localhost:8000/api/api-config')
      .then(r => r.json())
      .then(d => { form.setFieldsValue(d); setLoading(false); })
      .catch(() => { message.error('加载配置失败'); setLoading(false); });
  }, [form]);

  const runTest = async (endpoint: string, label: string) => {
    setTesting(true); setTestResult(null);
    const values = form.getFieldsValue();
    try {
      const resp = await fetch(`http://localhost:8000/api/api-config/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      const r = await resp.json();
      if (r.ok) {
        if (r.token && endpoint === 'test-login') {
          form.setFieldsValue({ token: r.token });
          message.success('Token已自动填入并保存到配置');
        }
        setTestResult({ type: 'success', title: `${label}成功`,
          msg: r.token ? `Token: ${r.token.substring(0, 50)}...` : (r.msg || `共 ${r.total} 条，${r.sample}`) });
      } else {
        setTestResult({ type: 'error', title: `${label}失败`, msg: r.msg || '未知错误' });
      }
    } catch (e: any) { setTestResult({ type: 'error', title: '请求失败', msg: e.message }); }
    setTesting(false);
  };

  const handleSave = async (values: ConfigData) => {
    setSaving(true);
    try {
      const resp = await fetch('http://localhost:8000/api/api-config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      if (resp.ok) message.success('配置已保存');
      else message.error('保存失败');
    } catch { message.error('保存失败'); }
    setSaving(false);
  };

  if (loading) return <Spin style={{ display: 'block', marginTop: 100 }} />;

  return (
    <div>
      <Card title={<><SettingOutlined /> 数据接口配置</>} style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical" onFinish={handleSave}
          initialValues={{ username: 'test', password: 'Enovell@123',
            base_url: 'http://172.17.3.165', port: '10000', token: '', page_size: 100 }}>
          <Divider plain>登录信息</Divider>
          <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
            <Input placeholder="登录用户名" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true }]}>
            <Input.Password placeholder="登录密码" />
          </Form.Item>
          <Form.Item label="Token（可选，直接填入则跳过登录）" name="token">
            <Input.TextArea rows={3} placeholder="JWT token，填入后优先使用，留空则用账号密码获取" />
          </Form.Item>

          <Divider plain>连接信息</Divider>
          <Form.Item label="服务地址" name="base_url" rules={[{ required: true }]}>
            <Input placeholder="http://172.17.3.165" />
          </Form.Item>
          <Form.Item label="端口" name="port" rules={[{ required: true }]}>
            <Input placeholder="10000" />
          </Form.Item>
          <Divider plain>查询参数</Divider>
          <Form.Item label="每页最大行数（10-100）" name="page_size" rules={[{ required: true }]}>
            <Input type="number" min={10} max={100} placeholder="100" />
          </Form.Item>
          <Space>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} htmlType="submit" size="large">
              保存配置
            </Button>
            <Button icon={<KeyOutlined />} loading={testing} onClick={() => runTest('test-login', '登录测试')}>
              测试登录获取Token
            </Button>
            <Button icon={<SearchOutlined />} loading={testing} onClick={() => runTest('test-query', '查询测试')}>
              测试获取历史告警
            </Button>
          </Space>
          {testResult && (
            <Alert style={{ marginTop: 16 }}
              type={testResult.type === 'success' ? 'success' : 'error'}
              message={testResult.title}
              description={<div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{testResult.msg}</div>}
              showIcon closable onClose={() => setTestResult(null)}
            />
          )}
        </Form>
      </Card>
    </div>
  );
}
