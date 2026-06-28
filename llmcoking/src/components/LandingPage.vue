<template>
  <div class="landing-container">
    <!-- 动态网格背景 -->
    <div class="grid-bg"></div>
    <div class="glow-orb orb-1"></div>
    <div class="glow-orb orb-2"></div>

    <!-- 顶部导航 -->
    <header class="landing-header">
      <div class="header-left">
        <div class="header-logo">
          <span class="logo-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
          </span>
          DeepResearch
        </div>
      </div>
      <div class="header-right">
        <span class="user-name">{{ userName }}</span>
        <button class="logout-btn" @click="logout">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          退出
        </button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="landing-main">
      <!-- Hero 区域 -->
      <section class="hero-section">
        <div class="hero-badge">智慧化工AI 智能体</div>
        <h1 class="hero-title">Deep<span class="title-accent">Research</span></h1>
        <p class="hero-subtitle">高校智慧化工软件平台</p>
        <p class="hero-desc">融合化工专业知识库、实验安全规则与数字孪生模拟软件，构建面向教学、实验管理和模拟仿真的一体化 AI 智能体。</p>
      </section>

      <!-- 两大支柱板块 -->
      <section
        class="section-block"
        v-for="section in sections"
        :key="section.id"
      >
        <div class="tiles" :class="section.grid">
          <article
            class="tile"
            v-for="card in section.cards"
            :key="card.id"
            :class="['tile-' + card.id, { disabled: !card.ready }]"
            :style="tileStyle(card)"
            @click="onCardClick(card)"
          >
            <span class="tile-overlay"></span>
            <i v-if="!card.image" :class="card.icon" class="tile-watermark"></i>
            <span class="tile-status" :class="{ 'status-soon': !card.ready }">{{ card.status }}</span>
            <header class="tile-body">
              <span class="tile-tag">{{ card.tags[0] }}</span>
              <h3 class="tile-title">{{ card.title }}</h3>
              <p class="tile-desc">{{ card.desc }}</p>
              <span class="tile-cta">{{ card.url ? '点击进入系统 →' : (card.ready ? '开始使用 →' : '敬请期待') }}</span>
            </header>
          </article>
        </div>
      </section>
    </main>

    <!-- 底部 -->
    <footer class="landing-footer">
      <img class="footer-logo" src="../assets/imgs/CompanyLogo.png" alt="Logo" />
      <span class="footer-text">苏州龙泰氢一能源科技有限公司</span>
    </footer>
  </div>
</template>

<script>
export default {
  name: 'LandingPage',
  data () {
    return {
      userName: window.sessionStorage.getItem('nickname') || window.sessionStorage.getItem('username') || 'user',
      sections: [
        {
          id: 'all',
          grid: 'tiles-uni',
          cards: [
            {
              id: 'twin',
              icon: 'el-icon-monitor',
              title: '模拟仿真',
              desc: '焦炉三维温度场与炼焦工艺过程的数字仿真，实时监控工况、温度场、煤床压力与焦化时间预测。',
              gradient: 'linear-gradient(135deg, rgba(6,182,212,0.5) 0%, rgba(8,145,178,0.5) 100%)',
              image: require('@/assets/imgs/DTbackground.jpg'),
              tags: ['三维可视化', '温度场', '工艺仿真'],
              status: '可用',
              ready: true,
              url: 'http://1.116.164.66/#/login'
            },
            {
              id: 'research',
              icon: 'el-icon-notebook-2',
              title: '科研写作',
              desc: '论文写作的可溯源、可引用、可信赖资料支持，回答附文献来源。',
              gradient: 'linear-gradient(135deg, rgba(26,92,58,0.5) 0%, rgba(40,160,106,0.5) 100%)',
              image: require('@/assets/imgs/writing.png'),
              tags: ['文献检索', '溯源引用', '多篇整合'],
              status: '可用',
              ready: true
            },
            {
              id: 'student',
              icon: 'el-icon-reading',
              title: '学科知识',
              desc: '课本、课件、历年试题汇成系统化复习路径；掌握学生高频疑问、章节难点与学习进度。',
              gradient: 'linear-gradient(135deg, rgba(20,158,250,0.5) 0%, rgba(13,110,253,0.5) 100%)',
              image: require('@/assets/imgs/knowledge.png'),
              tags: ['课程资料', '历年试题', '学情分析'],
              status: '建设中',
              ready: false
            },
            {
              id: 'lab',
              icon: 'el-icon-warning-outline',
              title: '实验安全',
              desc: '实验流程、安全规范、关键操作点实时提醒记录。',
              gradient: 'linear-gradient(135deg, rgba(225,29,72,0.5) 0%, rgba(244,63,94,0.5) 100%)',
              image: require('@/assets/imgs/lab.png'),
              tags: ['实验流程', '安全规范', '操作提醒'],
              status: '建设中',
              ready: false
            }
          ]
        }
      ]
    }
  },
  methods: {
    tileStyle (card) {
      // 有封面图用图，没有则用渐变色块
      return card.image
        ? { backgroundImage: 'url(' + card.image + ')' }
        : { backgroundImage: card.gradient }
    },
    onCardClick (card) {
      if (!card.ready) {
        if (this.$message) this.$message({ message: '该功能正在建设中，敬请期待 🚧', type: 'info' })
        else window.alert('该功能正在建设中，敬请期待')
        return
      }
      if (card.url) { window.open(card.url, '_blank'); return }
      this.enterChat()
    },
    enterChat () {
      this.$router.push({ name: 'MainDia', params: { sessionId: 'new' } })
    },
    logout () {
      window.sessionStorage.removeItem('token')
      this.$router.push('/login')
    }
  }
}
</script>

<style lang="less" scoped>
@primary: #149efa;
@accent: #ff8a00;
@bg-deep: #050a14;
@bg-card: rgba(255, 255, 255, 0.03);
@border-subtle: rgba(255, 255, 255, 0.08);
@text-primary: #f0f2f5;
@text-secondary: rgba(255, 255, 255, 0.55);
@text-muted: rgba(255, 255, 255, 0.35);

.landing-container {
  min-height: 100vh;
  /* 最底层:深蓝色大背景,铺满整屏 */
  background: linear-gradient(180deg, #16386b 0%, #0e2547 52%, #0a1a33 100%);
  background-attachment: fixed;
  position: relative;
  overflow-x: hidden;
  color: @text-primary;
}

/* 网格已移除 */
.grid-bg {
  display: none;
}

/* 光晕装饰 */
.glow-orb {
  position: fixed;
  border-radius: 50%;
  filter: blur(120px);
  z-index: 0;
  pointer-events: none;
}

.orb-1 {
  width: 500px;
  height: 500px;
  background: rgba(20, 158, 250, 0.08);
  top: -100px;
  right: -100px;
}

.orb-2 {
  width: 400px;
  height: 400px;
  background: rgba(255, 138, 0, 0.06);
  bottom: -50px;
  left: -100px;
}

/* 顶部导航 */
.landing-header {
  position: fixed;
  top: 16px;
  left: 24px;
  right: 24px;
  z-index: 100;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: transparent;
  border-radius: 14px;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-logo {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 20px;
  font-weight: bold;
  color: @text-primary;
  display: flex;
  align-items: center;
  gap: 10px;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8);
}

.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, @accent, @primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-name {
  color: #fff;
  font-size: 13px;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.7);
}

.logout-btn {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #fff;
  font-size: 13px;
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;

  &:hover {
    background: rgba(255, 255, 255, 0.1);
    color: @text-primary;
    border-color: rgba(255, 255, 255, 0.2);
  }
}

/* 主内容 */
.landing-main {
  position: relative;
  z-index: 1;
  width: 100%;
  padding: 0;
}

/* Hero 区域:background1 只占上半(横幅),底部渐隐进天蓝色 */
.hero-section {
  position: relative;
  text-align: center;
  padding: 130px 32px 84px;
  min-height: 52vh;
  background: url('../assets/imgs/background1.png') center / cover no-repeat;
}

.hero-section::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  background: linear-gradient(180deg, rgba(10, 24, 44, 0.3) 0%, rgba(10, 24, 44, 0.18) 45%, #16386b 100%);
}

.hero-section > * {
  position: relative;
  z-index: 1;
}

.hero-badge {
  display: inline-block;
  padding: 5px 16px;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: #fff;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 20px;
  margin-bottom: 24px;
  letter-spacing: 0.5px;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.6);
}

.hero-title {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 68px;
  font-weight: 900;
  color: @text-primary;
  margin: 0 0 8px;
  letter-spacing: 3px;
  text-shadow: 0 2px 20px rgba(0, 0, 0, 0.55);
}

.title-accent {
  background: linear-gradient(90deg, #ffe14a 0%, #ff8a00 32%, #ff4d6d 66%, #d94fd9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 24px;
  color: #fff;
  font-weight: 300;
  margin: 0 0 16px;
  letter-spacing: 6px;
  text-shadow: 0 2px 14px rgba(0, 0, 0, 0.65);
}

.hero-desc {
  font-size: 15px;
  color: #fff;
  line-height: 1.9;
  margin: 0 auto;
  max-width: 620px;
  text-shadow: 0 1px 12px rgba(0, 0, 0, 0.7);
}

.hero-stats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 32px;
  margin-top: 36px;
  padding: 20px 40px;
  background: @bg-card;
  border: 1px solid @border-subtle;
  border-radius: 14px;
  display: inline-flex;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-value {
  font-family: 'Fira Code', monospace;
  font-size: 24px;
  font-weight: 700;
  color: @text-primary;
}

.stat-label {
  font-size: 12px;
  color: @text-muted;
}

.stat-divider {
  width: 1px;
  height: 32px;
  background: @border-subtle;
}

/* 板块 */
.section-block {
  padding: 22px 0 0;
}

.block-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 0 32px 16px;
  padding-left: 12px;
  border-left: 3px solid @accent;
}

.block-name {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
  text-shadow: 0 2px 10px rgba(0, 0, 0, 0.7);
}

.block-desc {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.78);
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.7);
}

/* 等大图块网格(数字仿真与四端平级,差不多大) */
.tiles {
  display: grid;
}

.tiles-uni {
  grid-template-columns: repeat(2, 1fr);
  grid-auto-rows: 300px;
}

.tile {
  position: relative;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
  cursor: pointer;
  height: 100%;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  outline: 1px solid rgba(5, 10, 20, 0.6);
  transition: transform 0.3s ease;
}

/* 半透明压暗叠层:背景半透(rgba)透出深蓝 + 此层整体压暗 = 透明偏暗的玻璃质感 */
.tile-overlay {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: linear-gradient(to top, rgba(4, 9, 18, 0.9) 0%, rgba(4, 9, 18, 0.64) 55%, rgba(4, 9, 18, 0.55) 100%);
  transition: background 0.35s ease;
}

.tile:not(.disabled):hover .tile-overlay {
  background: linear-gradient(to top, rgba(4, 9, 18, 0.82) 0%, rgba(4, 9, 18, 0.4) 60%, rgba(4, 9, 18, 0.28) 100%);
}

/* 无图块的图标水印 */
.tile-watermark {
  position: absolute;
  right: -14px;
  top: 6px;
  z-index: 1;
  font-size: 130px;
  color: rgba(255, 255, 255, 0.08);
  pointer-events: none;
}

/* 状态角标 */
.tile-status {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 3;
  font-size: 11px;
  font-family: 'Fira Code', monospace;
  padding: 3px 10px;
  border-radius: 6px;
  background: rgba(34, 197, 94, 0.16);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.35);
  backdrop-filter: blur(4px);

  &.status-soon {
    background: rgba(255, 138, 0, 0.16);
    color: @accent;
    border-color: rgba(255, 138, 0, 0.4);
  }
}

/* 图块文字区(压在底部) */
.tile-body {
  position: relative;
  z-index: 2;
  width: 100%;
  padding: 28px 30px;
}

.tile-tag {
  display: inline-block;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: #67e8f9;
  letter-spacing: 1px;
  margin-bottom: 10px;
}

.tile-title {
  font-size: 46px;
  font-weight: 800;
  color: #fff;
  margin: 0 0 12px;
  letter-spacing: 1px;
  line-height: 1.1;
  text-shadow: 0 2px 16px rgba(0, 0, 0, 0.5);
}

.tile-desc {
  font-size: 13.5px;
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.65;
  margin: 0 0 14px;
  max-width: 92%;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tile-cta {
  display: inline-block;
  font-size: 13px;
  font-weight: 600;
  font-family: 'Fira Code', monospace;
  color: @accent;
  opacity: 0;
  transform: translateY(6px);
  transition: all 0.3s ease;
}

.tile:not(.disabled):hover .tile-cta {
  opacity: 1;
  transform: translateY(0);
}

.tile.disabled {
  cursor: not-allowed;
  filter: grayscale(0.35) brightness(0.85);

  .tile-cta {
    color: @text-muted;
    opacity: 0.8;
    transform: none;
  }
}

/* 底部 */
.landing-footer {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0 28px;
  border-top: 1px solid @border-subtle;
}

.footer-logo {
  width: 120px;
  height: auto;
  margin-bottom: 6px;
  opacity: 0.5;
}

.footer-text {
  font-size: 12px;
  color: #fff;
}

/* 响应式 */
@media (max-width: 980px) {
  .hero-title {
    font-size: 48px;
  }
}

@media (max-width: 600px) {
  .tiles-uni {
    grid-template-columns: 1fr;
    grid-auto-rows: 200px;
  }
  .tile-title {
    font-size: 19px;
  }
}
</style>
