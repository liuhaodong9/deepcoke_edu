import Vue from 'vue'
import VueRouter from 'vue-router'
import LoginPage from '@/components/LoginPage.vue'
import LandingPage from '@/components/LandingPage.vue'
import HomePage from '@/components/HomePage.vue'
import MainDia from '@/components/MainDia.vue'
import VoiceAgent from '@/components/VoiceAgent.vue'
// 导入全局样式表
import '../assets/css/global.css'

Vue.use(VueRouter)

const router = new VueRouter({
  mode: 'hash', // 使用 hash 模式
  routes: [
    { path: '/', redirect: '/landing' }, // 根路径重定向到产品主页
    { path: '/login', name: 'Login', component: LoginPage }, // 登录页面路由
    { path: '/landing', name: 'Landing', component: LandingPage }, // 产品主页
    {
      path: '/Home',
      name: 'Home',
      component: HomePage, // Home 页面
      redirect: '/Home/MainDia/new', // 默认跳转到 MainDia 页面
      children: [
        {
          path: 'MainDia/:sessionId', // 子路由 MainDia，使用 sessionId 作为路由参数
          name: 'MainDia',
          component: MainDia, // MainDia 页面组件
          props: true // 允许将 sessionId 作为 prop 传递到组件中
        },
        {
          path: 'VoiceAgent',
          name: 'VoiceAgent',
          component: VoiceAgent
        }
      ]
    }
  ]
})

export default router
