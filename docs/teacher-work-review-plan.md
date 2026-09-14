# 教师负责学生作品查看与批改计划

## 问题与验收

学生提交作品后，负责教师无法查看待批改或需修改的作品，也无法进入作品详情批改。

- 教师在工作台可看到自己负责学生、且关联报名的最近作品及状态，并可进入详情。
- 教师在作品管理页可查看上述范围内的全部版本与状态。
- 教师可批改该范围内待批改作品；非负责学生、无报名关联的遗留作品仍返回 `403`。
- 列表、详情、下载与批改复用同一 `workPolicy` 归属规则，API 不返回 `file_path`。

## 设计决策

本批次将“分属自己的学生”优先定义为 `users.teacher_id = 当前教师 ID`。为兼容历史未分配学生（`teacher_id` 为空），其关联报名作品可由本校教师处理；一旦明确分配，便只认负责教师。作品还必须有关联报名与课程；不改变管理员全量权限、执行导师的课程归属权限，亦不扩大教师对已明确分属其他教师的学生或遗留无报名数据的访问范围。

## 变更与验证

- `backend/helpers/workPolicy.js`：增加教师负责学生的查看/批改策略。
- `backend/controllers/workController.js`、`backend/routes/works.js`：让列表、详情、下载、批改采用该策略。
- `backend/controllers/dashboardController.js`、`frontend/src/pages/dashboard/Index.jsx`、`frontend/src/pages/works/*.jsx`：提供工作台与作品管理入口、状态和批改操作。
- `backend/test/workPolicy.test.js`：覆盖允许范围与越权 `403`。
- `README.md`：同步角色权限与作品规则。

预定提交：

1. `feat(works): 支持教师批改负责学生作品`
2. `test(works): 覆盖教师作品查看与批改权限`
3. `docs(readme): 补充教师作品批改说明`

验证：`cd backend && npm test`、`cd frontend && npm run lint`、`cd frontend && npm run build`。
