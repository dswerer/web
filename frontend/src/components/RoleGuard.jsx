import { Button, Result } from 'antd';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../store/AuthContext';
import { homeForRole } from '../utils/roleNavigation';

export function RoleHomeRedirect() {
  const { user } = useAuth();
  return <Navigate to={homeForRole(user?.role)} replace />;
}

export default function RoleGuard({ roles, children }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  if (!user || roles.includes(user.role)) return children;
  return <Result
    status="403"
    title="当前身份无法访问此页面"
    subTitle="该功能不属于你的工作范围，请从当前身份的工作台继续。"
    extra={<Button type="primary" onClick={() => navigate(homeForRole(user.role), { replace: true })}>返回工作台</Button>}
  />;
}
