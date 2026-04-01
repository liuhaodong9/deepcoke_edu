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
        <div class="hero-badge">AI-Powered Coking Intelligence</div>
        <h1 class="hero-title">Deep<span class="title-accent">Coke</span></h1>
        <p class="hero-subtitle">智能焦化决策平台</p>
        <p class="hero-desc">融合配煤优化、数字孪生、知识图谱与智能对话<br/>为焦化全流程提供 AI 驱动的决策支持</p>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-value">8</span>
            <span class="stat-label">预测模型</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">6017</span>
            <span class="stat-label">知识文档</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-value">24/7</span>
            <span class="stat-label">本地部署</span>
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
            <span class="card-status">{{ product.status }}</span>
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
          开始智能对话
        </button>
        <p class="cta-hint">输入您的焦化问题，DeepCoke 将自动调用合适的工具为您解答</p>
      </section>

      <!-- 示例问题 -->
      <section class="capabilities-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          您可以这样问
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
      products: [
        {
          id: 'blend',
          icon: 'el-icon-s-operation',
          title: '智能配煤',
          desc: '基于煤质指标与焦炭质量模型，AI 自动推算最优配煤方案，降低成本、稳定焦炭质量。',
          gradient: 'linear-gradient(135deg, #1a3a5c 0%, #2a6496 100%)',
          tags: ['配方优化', '成本控制', '质量预测'],
          status: '已上线'
        },
        {
          id: 'twin',
          icon: 'el-icon-monitor',
          title: '数字孪生',
          desc: '基于 UE5 构建的焦炉三维温度场可视化系统，实时监控炼焦过程工况与温度分布。',
          gradient: 'linear-gradient(135deg, #ff8a00 0%, #e06b10 100%)',
          tags: ['三维可视化', '温度场', '实时监控'],
          status: '开发中'
        },
        {
          id: 'chat',
          icon: 'el-icon-microphone',
          title: '智能对话',
          desc: '支持文字与语音交互，理解焦化领域专业问题，调用多种工具综合回答。',
          gradient: 'linear-gradient(135deg, #149efa 0%, #0d6efd 100%)',
          tags: ['语音识别', '多轮对话', '工具调度'],
          status: '已上线'
        },
        {
          id: 'knowledge',
          icon: 'el-icon-notebook-2',
          title: '知识图谱',
          desc: '基于焦化文献构建的专业知识库，回答附带文献来源引用，确保可溯源。',
          gradient: 'linear-gradient(135deg, #1a5c3a 0%, #28a06a 100%)',
          tags: ['文献检索', '知识问答', '来源引用'],
          status: '已上线'
        }
      ],
      examples: [
        '这批煤灰分12%、挥发分28%，如何配煤？',
        '焦炉温度场异常，可能的原因有哪些？',
        '配煤中肥煤比例过高会怎样？',
        '查看当前焦炉实时温度分布',
        '关于捣固焦工艺的文献有哪些？',
        '如何降低焦炭灰分同时保证强度？'
      ]
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
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
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
  background: rgba(5, 10, 20, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid @border-subtle;
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
  color: @text-secondary;
  font-size: 13px;
}

.logout-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid @border-subtle;
  color: @text-secondary;
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
  max-width: 1060px;
  margin: 0 auto;
  padding: 110px 32px 40px;
}

/* Hero 区域 */
.hero-section {
  text-align: center;
  padding: 48px 0 32px;
}

.hero-badge {
  display: inline-block;
  padding: 5px 16px;
  font-size: 12px;
  font-family: 'Fira Code', monospace;
  color: @primary;
  background: rgba(20, 158, 250, 0.08);
  border: 1px solid rgba(20, 158, 250, 0.2);
  border-radius: 20px;
  margin-bottom: 24px;
  letter-spacing: 0.5px;
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
  background: @bg-card;
  border: 1px solid @border-subtle;
  border-radius: 16px;
  padding: 24px 20px;
  transition: all 0.25s ease;
  cursor: pointer;

  &:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.15);
    transform: translateY(-4px);
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
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
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
  font-family: 'Fira Code', monospace;
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
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.06);
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
  box-shadow: 0 4px 24px rgba(20, 158, 250, 0.25);

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(20, 158, 250, 0.35);
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
    background: rgba(255, 255, 255, 0.06);
    color: @text-primary;
    border-color: rgba(255, 255, 255, 0.15);

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
