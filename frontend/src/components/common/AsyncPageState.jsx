import { Button, Empty, Result, Skeleton } from 'antd';

export default function AsyncPageState({ loading, error, empty = false, onRetry, emptyText = '暂无数据', children }) {
  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (error) return <Result status="error" title="内容加载失败" subTitle={error} extra={<Button type="primary" onClick={onRetry}>重新加载</Button>} />;
  if (empty) return <Empty description={emptyText} />;
  return children;
}
