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
          DeepCoke
          <span class="edition-badge">Edu</span>
        </div>
      </div>
      <div class="header-right">
        <!-- 已登录：显示用户名 + 退出 -->
        <template v-if="isLoggedIn">
          <span class="user-name">{{ userName }}</span>
          <button class="logout-btn" @click="logout">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
            退出
          </button>
        </template>
        <!-- 未登录：显示登录按钮 -->
        <button v-else class="login-btn" @click="goLogin">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
            <polyline points="10 17 15 12 10 7"/>
            <line x1="15" y1="12" x2="3" y2="12"/>
          </svg>
          登录
        </button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="landing-main">
      <!-- Hero 区域 -->
      <section class="hero-section">
        <div class="hero-badge">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: -1px;">
            <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
            <path d="M6 12v5c0 1 4 3 6 3s6-2 6-3v-5"/>
          </svg>
          高校教学专用版
        </div>
        <h1 class="hero-title">Deep<span class="title-accent">Coke</span></h1>
        <p class="hero-subtitle">焦化工艺智能教学实训平台</p>
        <p class="hero-desc">面向高校冶金、化工、材料等专业<br/>通过 AI 对话式交互学习配煤优化、焦炭质量预测与焦化工艺知识</p>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-value">8</span>
            <span class="stat-label">机器学习模型</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">6017</span>
            <span class="stat-label">专业文献库</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">100%</span>
            <span class="stat-label">离线可用</span>
          </div>
        </div>
      </section>

      <!-- 四大产品卡片 - Bento Grid -->
      <section class="products-section">
        <div
          class="product-card"
          v-for="product in products"
          :key="product.id"
          :class="'card-' + product.id"
        >
          <div class="card-header">
            <div class="card-icon-wrapper" :style="{ background: product.gradient }">
              <i :class="product.icon" class="card-icon"></i>
            </div>
            <span class="card-status" :class="{ 'card-status-dev': product.status === '开发中' }">{{ product.status }}</span>
          </div>
          <h3 class="card-title">{{ product.title }}</h3>
          <p class="card-desc">{{ product.desc }}</p>
          <div class="card-tags">
            <span class="tag" v-for="tag in product.tags" :key="tag">{{ tag }}</span>
          </div>
        </div>
      </section>

      <!-- CTA 按钮 -->
      <section class="cta-section">
        <button class="cta-button" @click="enterChat">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          开始学习对话
        </button>
        <p class="cta-hint">向 AI 助教提问焦化专业问题，系统将自动检索文献、调用模型为你解答</p>
      </section>

      <!-- 示例问题 -->
      <section class="capabilities-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          试着问这些问题
        </h2>
        <div class="examples-grid">
          <div class="example-item" v-for="(example, idx) in examples" :key="idx" @click="enterChatWithQuestion(example)">
            <svg class="example-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="5" y1="12" x2="19" y2="12"/>
              <polyline points="12 5 19 12 12 19"/>
            </svg>
            <span>{{ example }}</span>
          </div>
        </div>
      </section>
    </main>

    <!-- 底部 -->
    <footer class="landing-footer">
      <img class="footer-logo" src="../assets/imgs/CompanyLogo.png" alt="Logo" />
      <span class="footer-text">苏州龙泰氢一能源科技有限公司 · 高校教学版</span>
    </footer>
  </div>
</template>

<script>
export default {
  name: 'LandingPage',
  data () {
    return {
      products: [
        {
          id: 'blend',
          icon: 'el-icon-s-operation',
          title: '配煤优化实训',
          desc: '输入煤质指标，AI 自动演示多目标优化配煤过程，帮助学生理解配煤原理与成本控制逻辑。',
          gradient: 'linear-gradient(135deg, #1a3a5c 0%, #2a6496 100%)',
          tags: ['交互式学习', '优化算法', '成本分析'],
          status: '可体验'
        },
        {
          id: 'twin',
          icon: 'el-icon-monitor',
          title: '焦炉数字孪生',
          desc: '基于 UE5 的三维焦炉温度场模拟，学生可直观观察炼焦过程中的热工状态变化。',
          gradient: 'linear-gradient(135deg, #ff8a00 0%, #e06b10 100%)',
          tags: ['三维仿真', '温度场', '过程可视化'],
          status: '开发中'
        },
        {
          id: 'chat',
          icon: 'el-icon-microphone',
          title: 'AI 答疑助手',
          desc: '支持文字与语音提问，覆盖配煤、炼焦、煤化学等知识点，即时获得专业解答。',
          gradient: 'linear-gradient(135deg, #149efa 0%, #0d6efd 100%)',
          tags: ['智能问答', '语音交互', '即时反馈'],
          status: '可体验'
        },
        {
          id: 'knowledge',
          icon: 'el-icon-notebook-2',
          title: '专业文献库',
          desc: '收录 6000+ 篇焦化领域文献，AI 自动检索并引用原文出处，辅助学生文献调研与论文写作。',
          gradient: 'linear-gradient(135deg, #1a5c3a 0%, #28a06a 100%)',
          tags: ['文献检索', 'RAG 问答', '来源溯源'],
          status: '可体验'
        }
      ],
      examples: [
        '配煤中肥煤比例过高会对焦炭质量产生什么影响？',
        '什么是焦炭的CRI和CSR指标？它们的关系是什么？',
        '灰分12%、挥发分28%的煤，帮我设计一个配煤方案',
        '焦炉温度场不均匀的原因和调节方法有哪些？',
        '捣固焦与顶装焦工艺的区别是什么？',
        '如何通过调整配煤比降低焦炭灰分同时保证强度？'
      ]
    }
  },
  computed: {
    isLoggedIn () {
      return !!window.sessionStorage.getItem('token')
    },
    userName () {
      return window.sessionStorage.getItem('nickname') || window.sessionStorage.getItem('username') || ''
    }
  },
  methods: {
    enterChat () {
      this.$router.push({ name: 'MainDia', params: { sessionId: 'new' } })
    },
    enterChatWithQuestion (question) {
      this.$router.push({
        name: 'MainDia',
        params: { sessionId: 'new' },
        query: { q: question }
      })
    },
    goLogin () {
      this.$router.push('/login')
    },
    logout () {
      window.sessionStorage.removeItem('token')
      window.sessionStorage.removeItem('username')
      window.sessionStorage.removeItem('nickname')
      this.$router.go(0)
    }
  }
}
</script>

<style lang="less" scoped>
@primary: #149efa;
@accent: #ff8a00;
@bg-deep: #E8E8ED;
@bg-card: rgba(0, 0, 0, 0.02);
@border-subtle: #D5D5DA;
@text-primary: #1E293B;
@text-secondary: #64748B;
@text-muted: #94A3B8;

.landing-container {
  min-height: 100vh;
  background: @bg-deep;
  position: relative;
  overflow-x: hidden;
  color: @text-primary;
}

/* 网格背景 */
.grid-bg {
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  z-index: 0;
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
  background: rgba(20, 158, 250, 0.06);
  top: -100px;
  right: -100px;
}

.orb-2 {
  width: 400px;
  height: 400px;
  background: rgba(255, 138, 0, 0.04);
  bottom: -50px;
  left: -100px;
}

/* 顶部导航 — Apple 风格全宽薄条 */
.landing-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  height: 44px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  background: rgba(246, 246, 248, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.08);
}

.header-left {
  display: flex;
  align-items: center;
}

.header-logo {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 15px;
  font-weight: 700;
  color: @text-primary;
  display: flex;
  align-items: center;
  gap: 7px;
}

.logo-icon {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: linear-gradient(135deg, @accent, @primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;

  svg {
    width: 12px;
    height: 12px;
  }
}

.edition-badge {
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 10px;
  font-weight: 600;
  color: @primary;
  background: rgba(20, 158, 250, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  margin-left: 2px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-name {
  color: @text-muted;
  font-size: 12px;
}

.logout-btn,
.login-btn {
  background: transparent;
  border: none;
  color: @text-muted;
  font-size: 12px;
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
  transition: color 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;

  &:hover {
    color: @text-primary;
  }
}

/* 主内容 */
.landing-main {
  position: relative;
  z-index: 1;
  max-width: 1060px;
  margin: 0 auto;
  padding: 80px 32px 40px;
}

/* Hero 区域 */
.hero-section {
  text-align: center;
  padding: 48px 0 32px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 16px;
  font-size: 12px;
  color: @primary;
  background: rgba(20, 158, 250, 0.08);
  border: 1px solid rgba(20, 158, 250, 0.2);
  border-radius: 20px;
  margin-bottom: 24px;
  letter-spacing: 1px;
  font-weight: 500;
}

.hero-title {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 68px;
  font-weight: 900;
  color: @text-primary;
  margin: 0 0 8px;
  letter-spacing: 3px;
}

.title-accent {
  background: linear-gradient(90deg, @accent, @primary);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 24px;
  color: @text-secondary;
  font-weight: 300;
  margin: 0 0 16px;
  letter-spacing: 6px;
}

.hero-desc {
  font-size: 15px;
  color: @text-muted;
  line-height: 1.8;
  margin: 0 auto;
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

/* 产品卡片 - Bento Grid */
.products-section {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  padding: 32px 0;
}

.product-card {
  background: #F0F0F3;
  border: 1px solid #D5D5DA;
  border-radius: 16px;
  padding: 24px 20px;
  transition: all 0.25s ease;
  cursor: pointer;

  &:hover {
    border-color: #C5C5CC;
    transform: translateY(-4px);
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.08);
  }
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.card-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-icon {
  font-size: 22px;
  color: #fff;
}

.card-status {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(20, 158, 250, 0.08);
  color: @primary;
  font-family: 'Fira Code', monospace;
}

.card-status-dev {
  background: rgba(255, 138, 0, 0.08);
  color: @accent;
}

.card-title {
  font-size: 16px;
  color: @text-primary;
  margin: 0 0 8px;
  font-weight: 600;
}

.card-desc {
  font-size: 13px;
  color: @text-secondary;
  line-height: 1.7;
  margin: 0 0 14px;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: 11px;
  font-family: 'Fira Code', monospace;
  color: @text-muted;
  background: rgba(0, 0, 0, 0.03);
  border: 1px solid #D5D5DA;
  padding: 2px 8px;
  border-radius: 4px;
}

/* CTA 按钮 */
.cta-section {
  text-align: center;
  padding: 16px 0 36px;
}

.cta-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 40px;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, @accent, @primary);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: 0 4px 24px rgba(20, 158, 250, 0.15);

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(20, 158, 250, 0.25);
  }

  &:active {
    transform: translateY(0);
  }
}

.cta-hint {
  margin-top: 14px;
  font-size: 13px;
  color: @text-muted;
}

/* 示例问题 */
.capabilities-section {
  padding: 16px 0 48px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 16px;
  color: @text-secondary;
  font-weight: 400;
  margin: 0 0 20px;

  svg {
    opacity: 0.5;
  }
}

.examples-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.example-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 18px;
  background: @bg-card;
  border: 1px solid @border-subtle;
  border-radius: 10px;
  color: @text-secondary;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    background: rgba(0, 0, 0, 0.04);
    color: @text-primary;
    border-color: #C5C5CC;

    .example-arrow {
      color: @accent;
      transform: translateX(2px);
    }
  }
}

.example-arrow {
  color: @text-muted;
  flex-shrink: 0;
  transition: all 0.2s;
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
  color: @text-muted;
}

/* 响应式 */
@media (max-width: 900px) {
  .products-section {
    grid-template-columns: repeat(2, 1fr);
  }
  .hero-title {
    font-size: 48px;
  }
}

@media (max-width: 600px) {
  .products-section {
    grid-template-columns: 1fr;
  }
  .examples-grid {
    grid-template-columns: 1fr;
  }
  .hero-stats {
    flex-direction: column;
    gap: 16px;
  }
  .stat-divider {
    width: 32px;
    height: 1px;
  }
}
</style>
