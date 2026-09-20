import { Outlet, Navigate, useLocation } from 'react-router-dom';
import { Layout, Spin } from 'antd';
import { useAuth } from '../store/AuthContext';
import Sidebar from './Sidebar';
import HeaderBar from './Header';

const { Content } = Layout;

export default function AppLayout() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // 强制修改密码：管理员重置密码后，未改密前禁止访问其他页面
  if (user?.force_reset_password && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sidebar />
      <Layout>
        <HeaderBar />
        <Content style={{ background: '#f5f7fa', minHeight: 360 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
