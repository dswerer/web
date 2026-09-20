import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Input, Space, Table, Tag } from 'antd';
import { observerAPI } from '../../api';
import PageContainer from '../../components/common/PageContainer';
import AsyncPageState from '../../components/common/AsyncPageState';

export default function ObserverStudentList() {
  const navigate = useNavigate(); const [search, setSearch] = useState(''); const [data, setData] = useState({ items: [], pagination: {} }); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = async (page = 1) => { setLoading(true); setError(''); try { setData(await observerAPI.students({ page, page_size: 20, search })); } catch (err) { setError(err?.response?.data?.error || '无法加载负责学生'); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  const columns = [{ title: '学生', render: (_, r) => <Space direction="vertical" size={0}><strong>{r.real_name}</strong><span>{r.username}</span></Space> }, { title: '学校 / 班级', render: (_, r) => `${r.school_name || '-'} / ${r.class_name || '-'}` }, { title: '近30天完成', dataIndex: 'completed_30d' }, { title: '学习中课时', dataIndex: 'pending_lessons' }, { title: '关注项', dataIndex: 'risk_tags', render: (tags) => tags.map((tag) => <Tag color="orange" key={tag}>{tag}</Tag>) }, { title: '操作', render: (_, r) => <Button type="link" onClick={() => navigate(`/observer/students/${r.id}`)}>查看学情</Button> }];
  return <PageContainer title="负责学生" description="列表范围仅包含由管理员明确分配给你的学生。" extra={<Input.Search style={{ width: 320, maxWidth: '100%' }} value={search} onChange={(e) => setSearch(e.target.value)} onSearch={() => load()} placeholder="姓名或账号" allowClear />}><Card className="content-card"><AsyncPageState loading={loading} error={error} onRetry={() => load()} empty={!data.items.length} emptyText="暂无明确分配的学生"><Table rowKey="id" columns={columns} dataSource={data.items} scroll={{ x: 800 }} pagination={{ current: data.pagination.page, total: data.pagination.total, pageSize: 20, onChange: load }} /></AsyncPageState></Card></PageContainer>;
}
