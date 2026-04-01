// babel.config.js
module.exports = {
  presets: [
    // 给 @babel/preset-env 传参（由 vue/cli 的 preset 透传）
    ['@vue/cli-plugin-babel/preset', {
      useBuiltIns: 'entry', // 按需引入 polyfill（基于入口）
      corejs: { version: 3, proposals: true } // 使用 core-js@3，并包含提案
    }]
  ],
  plugins: [
    '@babel/plugin-transform-class-static-block'
  ]
}
