// Vue CLI 配置
// 生产: nginx 反代 / 到 dist 静态文件，/login /chat 等到 8000 文本后端
// 开发: vue-cli-service serve 用 devServer.proxy 把后端路径转发到 127.0.0.1:8000
const { defineConfig } = require('@vue/cli-service')

// 文本后端接口前缀清单（生产 nginx + 开发 devServer.proxy 共用）
const BACKEND_PATHS = [
  '/login', '/register', '/logout',
  '/chat', '/new_session', '/user_sessions', '/messages',
  '/sessions', '/folders',
  '/rename_session', '/delete_session',
  '/face', '/all_coals_page',
  '/papers', '/chunk', '/paper_graph'
]

const proxyConfig = {}
for (const p of BACKEND_PATHS) {
  proxyConfig[p] = {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
    ws: false
  }
}

module.exports = defineConfig({
  publicPath: '/',
  transpileDependencies: true,
  devServer: {
    proxy: proxyConfig
  }
})
