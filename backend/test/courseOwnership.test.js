const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { before, after, test } = require('node:test');
const bcrypt = require('bcryptjs');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pbl-course-owner-'));
process.env.DB_PATH = path.join(dir, 'test.db');
process.env.UPLOAD_PATH = path.join(dir, 'uploads');
process.env.NODE_ENV = 'test';
process.env.JWT_SECRET = 'ownership-test';
const app = require('../app');
const db = require('../config/database');
const { canManageCourse } = require('../policies/coursePolicy');
let server, base;
const tokens = {};
async function api(url, method = 'GET', data, token = tokens.mentor_a) {
  const multipart = data instanceof FormData;
  const res = await fetch(base + '/api' + url, { method,
    headers: { ...(multipart ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(data === undefined ? {} : { body: multipart ? data : JSON.stringify(data) }),
  });
  return { status: res.status, body: await res.json() };
}
before(async () => {
  for (const [index, [username, role]] of [['admin','admin'], ['mentor_a','academic_mentor'], ['mentor_b','academic_mentor'], ['teacher','teacher'], ['student','student']].entries()) {
    db.prepare('INSERT INTO users (id,username,real_name,password_hash,role) VALUES (?,?,?,?,?)').run(index+1,username,username,bcrypt.hashSync('user123',4),role);
  }
  for (const [id, owner] of [[1,2],[2,3],[3,1]]) {
    db.prepare("INSERT INTO courses (id,title,grade_level,difficulty,created_by) VALUES (?,?,'primary','basic',?)").run(id,`课程${id}`,owner);
    db.prepare('INSERT INTO lessons (id,course_id,title) VALUES (?,?,?)').run(id,id,`课时${id}`);
    db.prepare('INSERT INTO course_replays (id,course_id,title,video_path,created_by) VALUES (?,?,?,?,?)').run(id,id,`回放${id}`,path.join(dir,`replay-${id}.mp4`),owner);
    fs.writeFileSync(path.join(dir,`replay-${id}.mp4`),'original');
  }
  server = app.listen(0,'127.0.0.1'); await new Promise(r=>server.once('listening',r));
  base = `http://127.0.0.1:${server.address().port}`;
  for (const username of ['admin','mentor_a','mentor_b','teacher','student']) tokens[username]=(await api('/auth/login','POST',{username,password:'user123'},null)).body.token;
});
after(async () => { await new Promise(r=>server.close(r)); db.close(); fs.rmSync(dir,{recursive:true,force:true}); });

test('课程管理策略拒绝非导师创建者、空课程；管理员和课程创建导师允许', () => {
  assert.equal(canManageCourse({id:2,role:'academic_mentor'},{created_by:2}),true);
  assert.equal(canManageCourse({id:3,role:'academic_mentor'},{created_by:2}),false);
  assert.equal(canManageCourse({id:2,role:'teacher'},{created_by:2}),false);
  assert.equal(canManageCourse({id:1,role:'admin'},{created_by:2}),true);
  assert.equal(canManageCourse({id:1,role:'admin'},null),false);
});

test('导师无法跨课程修改、删除、排课、加任务、管理回放或导入学生，数据库及文件不变', async () => {
  const tables = ['courses','lessons','tasks','resources','course_replays','enrollments'];
  const snapshot = () => tables.map(t=>db.prepare(`SELECT * FROM ${t} ORDER BY id`).all());
  const before = snapshot();
  for (const id of [2,3]) {
    for (const [url,method,data,status] of [
      [`/courses/${id}`,'PUT',{title:'越权修改'},403],
      [`/courses/${id}`,'DELETE',undefined,403],
      [`/courses/${id}/lessons`,'POST',{title:'越权课时'},403],
      [`/courses/lessons/${id}/tasks`,'POST',{title:'越权任务'},403],
      [`/courses/replays/${id}`,'PUT',{title:'越权回放'},404],
      [`/courses/replays/${id}`,'DELETE',undefined,404],
      [`/courses/${id}/enroll`,'POST',{student_ids:[5]},403],
      [`/courses/${id}/enroll/candidates`,'GET',undefined,403],
    ]) assert.equal((await api(url,method,data)).status,status,`${method} ${url}`);
    for (const kind of ['resources','replays']) {
      const form = new FormData(); form.append('title','越权上传'); form.append('file',new Blob(['test'],{type:kind==='resources'?'application/pdf':'video/mp4'}),kind==='resources'?'test.pdf':'test.mp4');
      assert.equal((await api(`/courses/${id}/${kind}`,'POST',form)).status,403);
    }
    assert.equal(fs.readFileSync(path.join(dir,`replay-${id}.mp4`),'utf8'),'original');
  }
  assert.deepEqual(snapshot(),before);
  const uploads = path.join(dir,'uploads');
  const files = fs.existsSync(uploads) ? fs.readdirSync(uploads,{recursive:true}).filter(p=>fs.statSync(path.join(uploads,p)).isFile()) : [];
  assert.deepEqual(files,[]);
});

test('课程列表与详情返回逐课程管理标志，其他导师草稿详情不可访问', async () => {
  const list = await api('/courses');
  assert.deepEqual(list.body.courses.filter(c=>c.can_manage).map(c=>c.id),[1]);
  assert.equal((await api('/courses/1')).body.course.can_enroll,true);
  const other = await api('/courses/2');
  assert.equal(other.status,403);
  assert.ok((await api('/courses','GET',undefined,tokens.admin)).body.courses.every(c=>c.can_manage));
});

test('本人课程及管理员跨课程管理仍可用，候选学生保留全平台查询能力', async () => {
  for (const [id,token] of [[1,tokens.mentor_a],[2,tokens.mentor_b],[3,tokens.admin]]) {
    assert.equal((await api(`/courses/${id}`,'PUT',{title:'合法编辑'},token)).status,200);
    assert.equal((await api(`/courses/${id}/lessons`,'POST',{title:'合法课时'},token)).status,200);
    assert.equal((await api(`/courses/lessons/${id}/tasks`,'POST',{title:'合法任务'},token)).status,200);
    assert.equal((await api(`/courses/replays/${id}`,'PUT',{title:'合法回放'},token)).status,200);
    assert.equal((await api(`/courses/${id}/enroll/candidates`,'GET',undefined,token)).status,200);
    assert.equal((await api(`/courses/${id}/enroll`,'POST',{student_ids:[5]},token)).status,200);
  }
  assert.equal((await api('/courses/2','PUT',{title:'管理员修改他人课程'},tokens.admin)).status,200);
  assert.equal(db.prepare('SELECT COUNT(*) c FROM enrollments').get().c,3);
});
