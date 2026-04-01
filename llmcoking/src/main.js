import Vue from 'vue'
import App from './App.vue'
import router from './router'
import './plugins/element.js'
import VueParticles from 'vue-particles'
import 'element-ui/lib/theme-chalk/index.css' // Element UI 样式文件
import 'core-js/actual/array/at'
import 'core-js/actual/string/at'

// ==================== 引入 axios 并挂载到 Vue 原型 ====================
import axios from 'axios'
const http = axios.create({
  baseURL: 'http://127.0.0.1:8000/', // FastAPI 后端地址（注意结尾有 /）
  timeout: 15000 // 请求超时时间（毫秒）
})
Vue.prototype.$http = http
// =====================================================================

Vue.config.productionTip = false

Vue.use(VueParticles)

new Vue({
  router, // 路由配置
  render: h => h(App) // 渲染入口组件 App.vue
}).$mount('#app') // 挂载到 #app 元素
