// DeepCoke 前端统一 API 封装
// 设计:
// - baseURL 走相对路径: 开发环境靠 vue.config.js 的 devServer.proxy 转发，生产由 nginx 反代
// - 自动从 sessionStorage 读 token，加 Authorization: Bearer <token>
// - 401 自动清 token 并跳 /login，避免每个页面写一遍
// - 暴露 apiFetch(path, opts)：跟原生 fetch 同接口；和 apiUrl(path)：拼绝对 URL 给 <iframe src>/<a href> 用

const TOKEN_KEY = 'token'

// 让 apiBaseUrl 能在调试时切换；默认空字符串 = 相对路径
export const API_BASE = ''

export function getToken () {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) || ''
  } catch (e) {
    return ''
  }
}

export function setToken (token) {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token)
    else window.sessionStorage.removeItem(TOKEN_KEY)
  } catch (e) {}
}

export function clearAuth () {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY)
    window.sessionStorage.removeItem('username')
    window.sessionStorage.removeItem('nickname')
  } catch (e) {}
}

function _redirectToLogin () {
  // 避免重复跳转（已经在登录页就不跳）
  if (window.location.hash.indexOf('Login') >= 0 || window.location.pathname.indexOf('Login') >= 0) return
  // 用 hash 路由跳：项目用 vue-router history/hash 都兼容
  try {
    window.location.replace('/')
  } catch (e) {}
}

// 拼 URL：path 以 / 开头时直接拼，否则当前文件夹相对
export function apiUrl (path) {
  if (!path) return API_BASE || '/'
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  if (!path.startsWith('/')) path = '/' + path
  return API_BASE + path
}

// 给 <iframe>/<a href> 用：把 token 塞 query，因为 iframe/a 不能加 header
export function apiUrlWithToken (path) {
  const url = apiUrl(path)
  const token = getToken()
  if (!token) return url
  const sep = url.indexOf('?') >= 0 ? '&' : '?'
  return url + sep + 'token=' + encodeURIComponent(token)
}

// 主接口：跟 fetch 同签名
export async function apiFetch (path, opts = {}) {
  const url = apiUrl(path)
  const headers = new Headers(opts.headers || {})
  const token = getToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', 'Bearer ' + token)
  }
  // JSON body 时默认 Content-Type（除非已 set）
  if (
    opts.body &&
    typeof opts.body === 'string' &&
    !headers.has('Content-Type') &&
    opts.body.trim().startsWith('{')
  ) {
    headers.set('Content-Type', 'application/json')
  }
  const finalOpts = { ...opts, headers }
  const res = await fetch(url, finalOpts)
  if (res.status === 401) {
    clearAuth()
    _redirectToLogin()
  }
  return res
}
