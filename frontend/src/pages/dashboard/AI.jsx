import { useState, useEffect, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Alert, Card, Input, Button, Select, Typography, Grid, Tag, Spin, message } from 'antd';
import { SendOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { aiAPI, courseAPI } from '../../api';
import { useAuth } from '../../store/AuthContext';

const { Title, Text } = Typography;

export default function AIAssistant() {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const [courses, setCourses] = useState([]);
  const [courseId, setCourseId] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [question, setQuestion] = useState('');
  const [chat, setChat] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const chatEndRef = useRef(null);
  const sequenceRef = useRef(0);
  const screens = Grid.useBreakpoint();

  useEffect(() => {
    let active = true;
    sequenceRef.current += 1;
    setChat([]);
    setCourseId(null);
    setLoading(false);
    setEnabled(false);
    setLoadError('');
    aiAPI.getCourses().then((res) => {
      if (!active) return;
      setCourses(res.courses || []);
      setEnabled(Boolean(res.enabled));
      const requested = Number(params.get('course_id'));
      if (res.courses?.some((course) => course.id === requested)) setCourseId(requested);
    }).catch(() => { if (active) setLoadError('无法加载可提问课程，请刷新页面重试。'); });
    return () => { active = false; sequenceRef.current += 1; };
  }, [params]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chat]);

  const downloadSource = async (source) => {
    try {
      const blob = await courseAPI.downloadResource(source.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = source.title || '课程资料';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch { message.error('下载资料失败'); }
  };

  const handleAsk = async () => {
    const value = question.trim();
    if (!value || loading) return;
    if (!courseId) { message.warning('请先选择一门课程'); return; }
    setLoading(true);
    const sequence = ++sequenceRef.current;
    setQuestion('');
    setChat((prev) => [...prev, { role: 'user', content: value }]);
    try {
      const res = await aiAPI.ask(value, courseId);
      if (sequence !== sequenceRef.current) return;
      setChat((prev) => [...prev, { role: 'ai', content: res.answer, sources: res.sources || [], courseId,
        origin: res.origin, requestId: res.request_id }]);
    } catch (err) {
      if (sequence !== sequenceRef.current) return;
      setChat((prev) => [...prev, { role: 'ai', error: true,
        content: err?.response?.data?.error || '未能取得 AI 回复，请稍后重试。' }]);
    } finally { if (sequence === sequenceRef.current) setLoading(false); }
  };

  return (
    <div style={{ maxWidth: 850, margin: '0 auto' }}>
      <Title level={4}>🤖 灵境小智</Title>
      <Text type="secondary">请选择课程，询问课程知识、任务或相关专业问题。课程规定以实际资料为准。</Text>
      {loadError && <Alert type="error" showIcon message={loadError} style={{ marginTop: 12 }} />}
      {!enabled && <Alert type="info" showIcon message="灵境小智暂未启用，请联系管理员。" style={{ marginTop: 12 }} />}
      {user?.role === 'admin' && <div style={{ marginTop: 8 }}><Link to="/dashboard/ai/settings">管理员 AI 配置</Link></div>}
      <Card style={{ marginTop: 16, height: 440, overflow: 'auto' }}>
        {chat.length === 0 && <div style={{ textAlign: 'center', color: '#999', marginTop: 120 }}>
          <RobotOutlined style={{ fontSize: 48 }} />
          <p>你好！选好课程后，就可以开始提问。</p>
        </div>}
        {chat.map((item, i) => <div key={i} style={{ marginBottom: 18, display: 'flex', gap: 8, justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start' }}>
          {item.role === 'ai' && <RobotOutlined style={{ fontSize: 20, color: '#1a73e8' }} />}
          <div style={{ maxWidth: screens.sm ? '78%' : '90%', minWidth: 0, overflowWrap: 'anywhere', padding: '8px 14px', borderRadius: 12, background: item.role === 'user' ? '#1a73e8' : '#f0f2f5', color: item.role === 'user' ? '#fff' : '#333', whiteSpace: 'pre-wrap' }}>
            {item.role === 'ai' && <div style={{ marginBottom: 6 }}><Tag color={item.error ? 'orange' : 'blue'}>
              {item.error ? '服务提示' : item.origin === 'provider' ? 'AI 服务回复' : '规则或回退回复'}
            </Tag></div>}
            {item.content}
            {item.sources?.length > 0 && <div style={{ marginTop: 12, borderTop: '1px solid #d9d9d9', paddingTop: 8 }}>
              <Text strong>参考资料</Text>
              {item.sources.map((source) => <div key={source.ref}>
                <Text type="secondary">[{source.ref}] {source.title} · {source.locator} </Text>
                {source.type === 'resource' ? <Button type="link" size="small" onClick={() => downloadSource(source)}>下载</Button>
                  : source.type === 'task' ? <Link to={`/tasks/${source.id}`}>查看</Link>
                    : <Link to={`/courses/${item.courseId}`}>查看课程</Link>}
              </div>)}
            </div>}
          </div>
          {item.role === 'user' && <UserOutlined style={{ fontSize: 20, color: '#1a73e8' }} />}
        </div>)}
        {loading && <Spin />}
        <div ref={chatEndRef} />
      </Card>
      <div style={{ display: 'flex', flexDirection: screens.sm ? 'row' : 'column', gap: 8, width: '100%', marginTop: 12 }}>
        <Select style={{ width: screens.sm ? 230 : '100%', flexShrink: 0 }} placeholder="选择课程（必选）" value={courseId} disabled={loading}
          onChange={(id) => { setCourseId(id); setChat([]); }}
          options={courses.map((course) => ({ label: course.title, value: course.id }))} />
        <Input placeholder="输入与当前课程相关的问题" maxLength={1000} value={question}
          disabled={!enabled || !courseId || loading} onChange={(event) => setQuestion(event.target.value)}
          onPressEnter={(event) => { if (!event.nativeEvent.isComposing) handleAsk(); }} />
        <Button type="primary" icon={<SendOutlined />} onClick={handleAsk} loading={loading} disabled={!enabled || !courseId}>发送</Button>
      </div>
    </div>
  );
}
