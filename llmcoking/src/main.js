import Vue from 'vue'
import App from './App.vue'
import router from './router'
import './plugins/element.js'
import VueParticles from 'vue-particles'
import 'element-ui/lib/theme-chalk/index.css' // Element UI 样式文件
import 'core-js/actual/array/at'
import 'core-js/actual/string/at'

// ==================== 引入 axios 并挂载到 Vue 原型 ====================
// baseURL 走相对路径：dev 靠 vue.config.js 的 devServer.proxy 转发，prod 由 nginx 反代
import axios from 'axios'
import { getToken, clearAuth, API_BASE } from './api'
const http = axios.create({
  baseURL: API_BASE || '/', // 相对路径
  timeout: 30000
})
// 请求拦截：自动加 Authorization header
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = 'Bearer ' + token
  return config
})
// 响应拦截：401 清 token + 回登录页
http.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err && err.response && err.response.status === 401) {
      clearAuth()
      try { window.location.replace('/') } catch (e) {}
    }
    return Promise.reject(err)
  }
)
Vue.prototype.$http = http
// =====================================================================

Vue.config.productionTip = false

Vue.use(VueParticles)

new Vue({
  router, // 路由配置
  render: h => h(App) // 渲染入口组件 App.vue
}).$mount('#app') // 挂载到 #app 元素
