import { useEffect, useState } from 'react';
import { Button, Card, Descriptions, Space, Spin, Typography, message } from 'antd';
import { ArrowLeftOutlined, DeleteOutlined, LinkOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useNavigate, useParams } from 'react-router-dom';
import { notificationAPI } from '../../api';
import { notificationCategories } from '../../constants/notification';
import NotificationLevelTag from '../../components/notifications/NotificationLevelTag';
import useNotifications from '../../hooks/useNotifications';
import { useAuth } from '../../store/AuthContext';
import { canRoleAccessPath } from '../../utils/roleNavigation';

const { Title, Paragraph } = Typography;

export default function NotificationDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { refreshUnread } = useNotifications();
  const [notification, setNotification] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    let active = true;
    notificationAPI.detail(id).then((response) => {
      if (!active) return;
      setNotification(response.data.notification);
      refreshUnread().catch(() => {});
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [id, refreshUnread]);

  const toggleRead = async () => {
    setActionLoading(true);
    try {
      if (notification.is_read) await notificationAPI.markUnread(id);
      else await notificationAPI.markRead(id);
      setNotification((current) => ({ ...current, is_read: current.is_read ? 0 : 1 }));
      await refreshUnread();
      message.success(notification.is_read ? '已标记为未读' : '已标记为已读');
    } finally {
      setActionLoading(false);
    }
  };

  const hide = async () => {
    setActionLoading(true);
    try {
      await notificationAPI.hide(id);
      await refreshUnread();
      message.success('通知已隐藏');
      navigate('/notifications');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!notification) return <Card>通知不存在或无权访问。</Card>;

  const category = notificationCategories[notification.category]?.label || notification.category;

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/notifications')}>返回</Button>
        <Title level={4} style={{ margin: 0 }}>{notification.title}</Title>
      </Space>
      <Card>
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="分类">{category}</Descriptions.Item>
          <Descriptions.Item label="级别"><NotificationLevelTag level={notification.level} /></Descriptions.Item>
          <Descriptions.Item label="发布时间">
            {dayjs(notification.published_at || notification.received_at).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
          <Descriptions.Item label="阅读状态">{notification.is_read ? '已读' : '未读'}</Descriptions.Item>
        </Descriptions>
        <Paragraph style={{ whiteSpace: 'pre-wrap', margin: '24px 0' }}>{notification.content}</Paragraph>
        <Space>
          {notification.action_url && canRoleAccessPath(user?.role, notification.action_url) && (
            <Button type="primary" icon={<LinkOutlined />} onClick={() => navigate(notification.action_url)}>
              查看相关内容
            </Button>
          )}
          <Button loading={actionLoading} onClick={toggleRead}>
            标记为{notification.is_read ? '未读' : '已读'}
          </Button>
          <Button danger icon={<DeleteOutlined />} loading={actionLoading} onClick={hide}>隐藏</Button>
        </Space>
      </Card>
    </div>
  );
}
