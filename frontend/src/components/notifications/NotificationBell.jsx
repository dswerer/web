import { useState } from 'react';
import { Badge, Button, Divider, Empty, Flex, Popover, Spin, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { notificationAPI } from '../../api';
import useNotifications from '../../hooks/useNotifications';
import NotificationItem from './NotificationItem';
import { useAuth } from '../../store/AuthContext';
import { canRoleAccessPath } from '../../utils/roleNavigation';

const { Text } = Typography;

export default function NotificationBell() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { unreadCount, reduceUnread } = useNotifications();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);

  const loadRecent = async () => {
    setLoading(true);
    try {
      const response = await notificationAPI.recent(8);
      setItems(response.data.items);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenChange = (nextOpen) => {
    setOpen(nextOpen);
    if (nextOpen) loadRecent();
  };

  const handleClick = async (notification) => {
    if (!notification.is_read) {
      await notificationAPI.markRead(notification.id);
      reduceUnread();
    }
    setOpen(false);
    const detailPath = `/notifications/${notification.id}`;
    navigate(canRoleAccessPath(user?.role, notification.action_url) ? notification.action_url : detailPath);
  };

  const content = (
    <div style={{ width: 360, maxWidth: '80vw' }}>
      <Flex justify="space-between" align="center" style={{ padding: '4px 12px' }}>
        <Text strong>最近通知</Text>
        <Button type="link" size="small" onClick={() => { setOpen(false); navigate('/notifications'); }}>
          查看全部
        </Button>
      </Flex>
      <Divider style={{ margin: '4px 0 0' }} />
      <div style={{ maxHeight: 440, overflowY: 'auto' }}>
        {loading ? (
          <Flex justify="center" style={{ padding: 32 }}><Spin /></Flex>
        ) : items.length ? (
          items.map((item) => (
            <NotificationItem key={item.id} notification={item} compact onClick={handleClick} />
          ))
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
        )}
      </div>
    </div>
  );

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={handleOpenChange}
      content={content}
      styles={{ body: { padding: 0 } }}
    >
      <Badge count={unreadCount} overflowCount={99} size="small">
        <Button type="text" shape="circle" aria-label="通知" icon={<BellOutlined />} />
      </Badge>
    </Popover>
  );
}
