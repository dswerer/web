import { useCallback, useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Descriptions, List, Result, Space, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { taskAPI } from '../../api';
import { useAuth } from '../../store/AuthContext';

const statusText = { pending: '待完成', in_progress: '进行中', submitted: '已提交', completed: '已完结' };

export default function TaskDetail() {
  const { id } = useParams(); const navigate = useNavigate(); const { user } = useAuth(); const [data, setData] = useState(null); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(() => {
    setLoading(true);
    setError('');
    setData(null);
    taskAPI.detail(id)
      .then(setData)
      .catch((err) => setError(err?.response?.data?.error || '任务不存在，或当前身份无权查看。'))
      .finally(() => setLoading(false));
  }, [id]);
  // 路由参数变化时需立即清空上一任务，避免短暂展示无权访问的旧数据。
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);
  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />;
  if (!data) return <Result status="404" title="无法打开任务" subTitle={error} extra={<Space><Button onClick={() => navigate('/tasks')}>返回任务列表</Button><Button type="primary" onClick={load}>重新加载</Button></Space>} />;
  const { task, works } = data;
  if (user?.role === 'student') return <Navigate to={`/courses/${task.course_id}/lessons/${task.lesson_id}/learn`} replace />;
  return <div><Space style={{ marginBottom: 16 }}><Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/tasks')}>返回任务</Button><Typography.Title level={4} style={{ margin: 0 }}>{task.title}</Typography.Title></Space>
    <Card><Descriptions column={1} bordered><Descriptions.Item label="所属课程">{task.course_title}</Descriptions.Item><Descriptions.Item label="探究阶段">{task.lesson_title}</Descriptions.Item><Descriptions.Item label="任务状态"><Tag>{statusText[task.status]}</Tag></Descriptions.Item><Descriptions.Item label="截止时间">{task.deadline || '未设置'}</Descriptions.Item><Descriptions.Item label="任务目标与指引">{task.description || '暂无说明'}</Descriptions.Item></Descriptions>
      {user?.role === 'student' && <Button type="primary" style={{ marginTop: 16 }} onClick={() => navigate(`/courses/${task.course_id}/lessons/${task.lesson_id}/learn`)}>进入课后学习</Button>}
    </Card>
    {user?.role === 'student' && <Card title="我的提交与反馈" style={{ marginTop: 16 }}><List dataSource={works} locale={{ emptyText: '尚未提交成果' }} renderItem={(work) => <List.Item><List.Item.Meta title={`${work.title} · 第 ${work.version || 1} 版`} description={work.description || '附件成果'} /><Space><Tag color={work.review_status === 'approved' ? 'green' : work.review_status === 'rejected' ? 'red' : 'orange'}>{work.review_status === 'approved' ? '已通过' : work.review_status === 'rejected' ? '需修改' : '待评审'}</Tag>{work.review_comment && <Typography.Text>{work.review_comment}</Typography.Text>}</Space></List.Item>} /></Card>}
  </div>;
}
