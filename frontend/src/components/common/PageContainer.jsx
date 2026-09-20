import { Typography } from 'antd';

export default function PageContainer({ title, description, extra, children }) {
  return <main className="page-container">
    {(title || description || extra) && <div className="page-heading" style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'start' }}>
      <div><Typography.Title level={2}>{title}</Typography.Title>{description && <Typography.Text type="secondary">{description}</Typography.Text>}</div>
      {extra}
    </div>}
    {children}
  </main>;
}
