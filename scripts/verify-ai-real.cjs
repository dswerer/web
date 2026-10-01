// 在隔离测试库中复用已有加密配置，最多发送三次真实请求。
// 源数据库只读；外发内容全部为合成课程资料，不使用真实学生数据。
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const assert = require('node:assert/strict');
const backend = path.resolve(__dirname, '../backend');
const requireBackend = createRequire(path.join(backend, 'package.json'));
const Database = requireBackend('better-sqlite3');
const bcrypt = requireBackend('bcryptjs');
requireBackend('dotenv').config({ path: path.join(backend, '.env') });
const outputIndex = process.argv.indexOf('--output');
const output = outputIndex >= 0 ? path.resolve(process.argv[outputIndex + 1]) : path.resolve('ai-real-evidence.json');
const sourcePath = path.resolve(backend, process.env.DB_PATH || 'database/pbl_platform.db');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pbl-ai-real-'));
const evidence = { date: new Intl.DateTimeFormat('sv-SE', { timeZone:'Asia/Shanghai', dateStyle:'short', timeStyle:'medium' }).format(new Date()),
  environment: '本机隔离测试服务；源配置只读；非部署环境验收', mock: false, realRequestsLimit: 3,
  syntheticDataOnly: true, cases: [] };
if (process.argv.includes('--unrelated-only') || process.argv.includes('--retrieval-only')) evidence.realRequestsLimit = 1;
let server, db;

async function main() {
  const source = new Database(sourcePath, { readonly:true, fileMustExist:true });
  let config;
  try { config = source.prepare('SELECT * FROM ai_settings WHERE id=1').get(); }
  finally { source.close(); }
  if (!config?.enabled || !config.api_key_encrypted || !/^[a-f0-9]{64}$/i.test(process.env.AI_CONFIG_SECRET || '')) {
    throw Object.assign(new Error('需先在后端配置并启用真实 AI 服务'), { code:'AI_CONFIG_MISSING' });
  }
  evidence.model = config.model;
  const originalFetch = global.fetch;
  global.fetch = async (url, options) => {
    const response = await originalFetch(url, options);
    if (String(url).startsWith(config.base_url + '/')) {
      try {
        const payload = await response.clone().json();
        let parsed;
        try { parsed = JSON.parse(payload?.choices?.[0]?.message?.content); } catch { /* shape only */ }
        evidence.lastProviderShape = { httpStatus:response.status, finishReason:payload?.choices?.[0]?.finish_reason,
          parsedScope:parsed?.scope, answerType:typeof parsed?.answer, parsedType:typeof parsed,
          fields:parsed && typeof parsed === 'object' ? Object.keys(parsed) : [] };
      } catch { /* 不打印供应商原始错误体 */ }
    }
    return response;
  };
  // 所有写操作都限定到本次临时目录。
  process.env.DB_PATH = path.join(temporary, 'test.db');
  process.env.UPLOAD_PATH = path.join(temporary, 'uploads');
  process.env.FEEDBACK_UPLOAD_PATH = path.join(temporary, 'feedback');
  process.env.NODE_ENV = 'test';
  process.env.JWT_SECRET = 'isolated-real-ai-test-only';
  process.env.LOGIN_RATE_LIMIT_IP = '1000';
  process.env.AI_TIMEOUT_MS = '30000';
  const app = requireBackend('./app');
  db = requireBackend('./config/database');
  const columns = Object.keys(config);
  assert.ok(columns.every(column => /^[a-z_]+$/.test(column)));
  db.prepare(`INSERT OR REPLACE INTO ai_settings (${columns.join(',')}) VALUES (${columns.map(() => '?').join(',')})`).run(...columns.map(column => config[column]));
  const users = [[1,'admin'],[2,'academic_mentor'],[3,'student'],[4,'teacher'],[5,'media'],[6,'student']];
  for (const [id,role] of users) db.prepare('INSERT INTO users (id,username,real_name,role,password_hash) VALUES (?,?,?,?,?)')
    .run(id,`synthetic${id}`,`测试角色${id}`,role,bcrypt.hashSync('Synthetic!1234',4));
  db.prepare("INSERT INTO courses (id,title,description,grade_level,difficulty,status,created_by) VALUES (1,'合成滑翔实验课','通过测量观察滑翔距离变化。','primary','basic','published',2),(2,'隔离对照课程','这是无权检索的课程内容。','primary','basic','published',1)").run();
  db.prepare('INSERT INTO enrollments (student_id,course_id) VALUES (3,1)').run();
  db.prepare("INSERT INTO lessons (id,course_id,title,status,sort_order) VALUES (1,1,'滑翔测量','completed',1)").run();
  db.prepare("INSERT INTO tasks (id,lesson_id,title,description,status) VALUES (1,1,'测量滑翔距离','测量三次滑翔距离，记录后比较平均值。','active')").run();
  const file = path.join(temporary,'uploads','synthetic.txt');
  fs.mkdirSync(path.dirname(file),{recursive:true});
  fs.writeFileSync(file,'实验讲义规定：滑翔测量起点高度为1.37米。记录三次滑翔距离，以米为单位计算平均值。');
  const resource = db.prepare("INSERT INTO resources (course_id,resource_type,title,file_path,file_size,upload_by) VALUES (1,'courseware','合成实验讲义',?,?,2)").run(file,fs.statSync(file).size);
  const documents = requireBackend('./services/aiDocumentService');
  documents.registerResource(Number(resource.lastInsertRowid));
  await documents.processResource(Number(resource.lastInsertRowid));
  assert.equal(db.prepare('SELECT status FROM ai_documents WHERE resource_id=?').get(resource.lastInsertRowid).status,'ready');
  server = app.listen(0,'127.0.0.1');
  await new Promise(resolve => server.once('listening',resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const sessions={};
  const api=async(url,method='GET',body,token)=>{
    const response=await fetch(`${base}/api${url}`,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},
      ...(body===undefined?{}:{body:JSON.stringify(body)})});
    return {status:response.status,body:await response.json()};
  };
  for(const [id] of users) {
    const login=await api('/auth/login','POST',{username:`synthetic${id}`,password:'Synthetic!1234'});
    assert.equal(login.status,200);sessions[id]=login.body.token;
  }
  const check=async(name,run)=>{
    try {const detail=await run();evidence.cases.push({name,passed:true,...detail});console.log(`${name}: PASS`);}
    catch(err){evidence.cases.push({name,passed:false,code:err.code||'ASSERTION_FAILED',status:err.status,
      assertion:err.code==='ERR_ASSERTION'?{operator:err.operator,actual:err.actual,expected:String(err.expected)}:undefined});console.log(`${name}: FAIL (${err.code||'ASSERTION_FAILED'})`);}
  };
  await check('五角色可见范围与跨课程拒绝',async()=>{
    for(const id of [1,2,3]) assert.equal((await api('/dashboard/ai/courses','GET',undefined,sessions[id])).status,200);
    for(const id of [4,5,6]) assert.equal((await api('/dashboard/ai/ask','POST',{course_id:1,question:'任务是什么？'},sessions[id])).status,403);
    assert.equal((await api('/dashboard/ai/ask','POST',{course_id:2,question:'课程内容'},sessions[3])).status,403);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM ai_usage').get().n,0);
    return {providerRequests:0};
  });
  for(const item of [
    {name:'真实服务根据课程任务回答',question:'本课程的必交任务名称是什么？',match:/测量滑翔距离/,scope:'core'},
    {name:'真实服务检索上传讲义并引用',question:'实验讲义规定的滑翔测量起点高度是多少？',match:/1[.．]37/,scope:'core',resource:true},
    {name:'真实服务拒绝无关提问',question:'今天娱乐新闻有哪些？',scope:'unrelated'},
  ].filter(item=>(!process.argv.includes('--unrelated-only')||item.scope==='unrelated')&&(!process.argv.includes('--retrieval-only')||item.resource))) await check(item.name,async()=>{
    const response=await api('/dashboard/ai/ask','POST',{course_id:1,question:item.question},sessions[3]);
    evidence.lastSyntheticResponse = { case:item.name, httpStatus:response.status, answer:response.body.answer,
      scope:response.body.scope, sources:response.body.sources, origin:response.body.origin };
    if(response.status!==200) throw Object.assign(new Error('真实服务请求失败'),{code:response.body.code,status:response.status});
    assert.equal(response.body.origin,'provider');
    assert.equal(response.body.scope,item.scope);
    if(item.match) assert.match(response.body.answer,item.match);
    if(item.resource) assert.ok(response.body.sources.some(source=>source.type==='resource'));
    if(item.scope==='unrelated') assert.equal(response.body.answer,requireBackend('./services/aiAnswerService').REFUSAL);
    const usage=db.prepare('SELECT * FROM ai_usage WHERE id=?').get(response.body.request_id);
    assert.equal(usage.status,'succeeded');assert.ok(usage.total_tokens>0);assert.ok(usage.provider_request_id);
    return {httpStatus:response.status,scope:response.body.scope,answer:response.body.answer,sources:response.body.sources,
      requestId:response.body.request_id,providerRequestId:usage.provider_request_id,tokens:usage.total_tokens,durationMs:usage.duration_ms};
  });
  evidence.requests=db.prepare('SELECT model,status,error_code,provider_request_id,total_tokens,duration_ms FROM ai_usage ORDER BY created_at,id').all();
  evidence.totalTokens=evidence.requests.reduce((total,row)=>total+(row.total_tokens||0),0);
  evidence.allPassed=evidence.cases.every(item=>item.passed);
  if(!evidence.allPassed) process.exitCode=1;
}

main().catch(err=>{
  evidence.allPassed=false;evidence.setupFailure={code:err.code||'SETUP_FAILED'};
  console.error(`真实 AI 验证未完成: ${err.code||'SETUP_FAILED'}`);process.exitCode=1;
}).finally(async()=>{
  if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  if(db) db.close();
  // 只清理本脚本用 mkdtemp 创建的目录。
  fs.rmSync(temporary,{recursive:true,force:true});
  fs.writeFileSync(output,JSON.stringify(evidence,null,2)+'\n');
  console.log(`证据已写入: ${output}`);
});
