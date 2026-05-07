import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { Layout, Menu } from 'antd';
import { DashboardOutlined, LinkOutlined, LineChartOutlined, ApartmentOutlined } from '@ant-design/icons';
import Dashboard from './pages/Dashboard';
import Rules from './pages/Rules';
import Timeline from './pages/Timeline';
import Topology from './pages/Topology';

const { Sider, Content } = Layout;

function App() {
  return (
    <BrowserRouter>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider width={200} theme="dark">
          <div style={{ color: '#fff', padding: '16px', fontSize: 16, fontWeight: 700, textAlign: 'center' }}>
            告警压缩分析
          </div>
          <Menu theme="dark" mode="inline" defaultSelectedKeys={['dashboard']}>
            <Menu.Item key="dashboard" icon={<DashboardOutlined />}>
              <NavLink to="/">告警概览</NavLink>
            </Menu.Item>
            <Menu.Item key="rules" icon={<LinkOutlined />}>
              <NavLink to="/rules">关联规则</NavLink>
            </Menu.Item>
            <Menu.Item key="timeline" icon={<LineChartOutlined />}>
              <NavLink to="/timeline">时序分析</NavLink>
            </Menu.Item>
            <Menu.Item key="topology" icon={<ApartmentOutlined />}>
              <NavLink to="/topology">拓扑视图</NavLink>
            </Menu.Item>
          </Menu>
        </Sider>
        <Content style={{ padding: 24, background: '#f5f5f5' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/topology" element={<Topology />} />
          </Routes>
        </Content>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
