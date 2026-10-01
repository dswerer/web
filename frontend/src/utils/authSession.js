// 登录和改密共用，保存服务端新会话后才继续业务请求。
export function saveAuthSession(storage, session) {
  storage.setItem('token', session.token);
  storage.setItem('refresh_token', session.refresh_token);
  storage.setItem('user', JSON.stringify(session.user));
  return session.user;
}
