// 短期管理规则：管理员管理全部课程，执行导师仅管理自己创建的课程。
function canManageCourse(user, course) {
  return !!user && !!course && (user.role === 'admin' ||
    (user.role === 'academic_mentor' && course.created_by === user.id));
}
module.exports = { canManageCourse };
