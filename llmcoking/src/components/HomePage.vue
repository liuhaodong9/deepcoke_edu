<template>
  <div class="app-layout">
    <!-- ===== 顶部导航栏 ===== -->
    <div class="top-nav">
      <div class="nav-left">
        <!-- Logo -->
        <div class="nav-logo" @click="goLanding">
          <span class="logo-dot"></span>
          <span class="logo-text">DeepCoke</span>
          <span class="edition-badge">Edu</span>
        </div>
        <!-- 导航菜单 -->
        <div class="nav-items">
          <div class="nav-item" @click="goLanding">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
            <span>首页</span>
          </div>
          <div class="nav-item active">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              <circle cx="12" cy="16" r="1"/>
            </svg>
            <span>DeepCoke智能体</span>
          </div>
          <div class="nav-item disabled">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="20" x2="18" y2="10"/>
              <line x1="12" y1="20" x2="12" y2="4"/>
              <line x1="6" y1="20" x2="6" y2="14"/>
            </svg>
            <span>焦炭质量预测</span>
          </div>
          <div class="nav-item disabled">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>配煤优化</span>
          </div>
          <div class="nav-item disabled">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <ellipse cx="12" cy="5" rx="9" ry="3"/>
              <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
              <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            </svg>
            <span>数据管理</span>
          </div>
        </div>
      </div>
      <div class="nav-right">
        <button class="nav-btn" @click="toggleLang">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span>{{ lang === 'zh' ? '中/EN' : 'EN/中' }}</span>
        </button>
        <div class="nav-user">
          <div class="user-avatar">{{ userName.charAt(0) }}</div>
          <span class="user-name-text">{{ userName }}</span>
        </div>
        <button class="nav-btn">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          <span>设置</span>
        </button>
        <button class="nav-btn">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          <span>消息提醒</span>
        </button>
        <button class="nav-btn" @click="logout">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          <span>退出</span>
        </button>
      </div>
    </div>

    <!-- ===== 内容区域 ===== -->
    <div class="content-area">
      <!-- 聊天历史浮层侧边栏 -->
      <transition name="slide-sidebar">
        <div v-if="sidebarVisible" class="chat-sidebar">
          <div class="sidebar-header">
            <span class="sidebar-title">历史对话</span>
            <button class="icon-btn" @click="sidebarVisible = false">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
          <button class="new-chat-btn" @click="startNewChat">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            <span>新对话</span>
          </button>
          <div class="chat-history">
            <div
              v-for="session in chatSessions"
              :key="session.session_id"
              class="chat-item"
              :class="{ active: sessionId === session.session_id }"
              @click="selectSession(session.session_id)"
            >
              <svg class="chat-item-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
              <span class="chat-title">{{ session.title }}</span>
              <el-dropdown trigger="click" @command="handleMenuCommand($event, session.session_id)">
                <span class="chat-menu-btn" @click.stop>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                    <circle cx="12" cy="5" r="1.5"/>
                    <circle cx="12" cy="12" r="1.5"/>
                    <circle cx="12" cy="19" r="1.5"/>
                  </svg>
                </span>
                <el-dropdown-menu slot="dropdown">
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete">删除</el-dropdown-item>
                </el-dropdown-menu>
              </el-dropdown>
            </div>
          </div>
        </div>
      </transition>

      <!-- 左侧：聊天面板 -->
      <div class="chat-panel">
        <div class="chat-panel-header">
          <button class="icon-btn" @click="sidebarVisible = !sidebarVisible" title="对话历史">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <span class="chat-panel-title">DeepCoke 智能体</span>
        </div>
        <router-view :sessionId="sessionId" :isCollapese="false" @update-sessions="fetchChatSessions"></router-view>
      </div>

      <!-- 右侧：数据面板 -->
      <div class="data-panel-container">
        <coal-data-panel />
      </div>
    </div>
  </div>
</template>

<script>
import CoalDataPanel from './CoalDataPanel.vue'

export default {
  components: { CoalDataPanel },
  data () {
    return {
      sidebarVisible: false,
      chatSessions: [],
      sessionId: '',
      userId: 'user123',
      apiBaseUrl: 'http://127.0.0.1:8000',
      lang: 'zh',
      userName: window.sessionStorage.getItem('nickname') || window.sessionStorage.getItem('username') || 'user'
    }
  },
  methods: {
    goLanding () {
      this.$router.push('/landing')
    },
    toggleLang () {
      this.lang = this.lang === 'zh' ? 'en' : 'zh'
    },
    logout () {
      window.sessionStorage.removeItem('token')
      window.sessionStorage.removeItem('username')
      window.sessionStorage.removeItem('nickname')
      this.$router.push('/login')
    },
    async startNewChat () {
      try {
        const response = await fetch(`${this.apiBaseUrl}/new_session/?user_id=${this.userId}`, {
          method: 'POST'
        })
        const data = await response.json()
        this.sessionId = data.session_id

        this.chatSessions.unshift({
          session_id: this.sessionId,
          title: '新对话'
        })

        if (this.$route.path !== `/Home/MainDia/${this.sessionId}`) {
          setTimeout(() => {
            this.$router.push({ path: `/Home/MainDia/${this.sessionId}` })
          }, 100)
        }
      } catch (error) {
        console.error('创建会话失败:', error)
      }
    },
    async selectSession (sessionId) {
      this.sessionId = sessionId
      if (this.$route.params.sessionId !== sessionId) {
        this.$router.push(`/Home/MainDia/${sessionId}`)
      }
    },
    async fetchChatSessions () {
      try {
        const response = await fetch(`${this.apiBaseUrl}/user_sessions/?user_id=${this.userId}`)
        const data = await response.json()
        if (!Array.isArray(data)) return

        this.chatSessions = data.map(session => ({
          session_id: session.session_id,
          title: session.title || `对话 ${session.session_id.slice(0, 6)}`
        }))
      } catch (error) {
        console.error('加载历史会话失败:', error)
      }
    },
    async handleMenuCommand (command, sessionId) {
      if (command === 'rename') {
        this.renameSession(sessionId)
      } else if (command === 'delete') {
        this.deleteSession(sessionId)
      }
    },
    async renameSession (sessionId) {
      const newTitle = prompt('请输入新的会话名称:')
      if (!newTitle) return

      try {
        const response = await fetch(`${this.apiBaseUrl}/rename_session/?session_id=${sessionId}&new_title=${encodeURIComponent(newTitle)}`, {
          method: 'PUT'
        })

        if (response.ok) {
          const session = this.chatSessions.find(s => s.session_id === sessionId)
          if (session) session.title = newTitle
        }
      } catch (error) {
        console.error('网络错误:', error)
      }
    },
    async deleteSession (sessionId) {
      if (!confirm('确定要删除这个会话吗？')) return

      try {
        const response = await fetch(`${this.apiBaseUrl}/delete_session/?session_id=${sessionId}`, {
          method: 'DELETE'
        })

        if (response.ok) {
          this.chatSessions = this.chatSessions.filter(s => s.session_id !== sessionId)

          if (this.sessionId === sessionId) {
            this.sessionId = this.chatSessions.length > 0 ? this.chatSessions[0].session_id : ''
          }
        }
      } catch (error) {
        console.error('网络错误:', error)
      }
    }
  },
  mounted () {
    this.fetchChatSessions()
  }
}
</script>

<style lang="less" scoped>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap');

@bg-main: #E8E8ED;
@bg-sidebar: #F0F0F3;
@border-color: #D5D5DA;
@hover-bg: #E0E0E5;
@accent: #149efa;
@accent-dim: rgba(20, 158, 250, 0.06);
@text-bright: #1E293B;
@text-secondary: #475569;
@text-muted: #94A3B8;

/* ===== 整体布局 ===== */
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: @bg-main;
}

/* ===== 顶部导航栏 ===== */
.top-nav {
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: @bg-sidebar;
  border-bottom: 1px solid @border-color;
  z-index: 200;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 24px;
}

.nav-logo {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex-shrink: 0;
}

.logo-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff8a00, #149efa);
  box-shadow: 0 0 8px rgba(20, 158, 250, 0.4);
}

.logo-text {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 16px;
  font-weight: 700;
  color: @text-bright;
}

.edition-badge {
  font-size: 10px;
  font-weight: 600;
  color: @accent;
  border: 1px solid fadeout(@accent, 60%);
  border-radius: 4px;
  padding: 1px 5px;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.nav-items {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: @text-secondary;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;

  &:hover {
    background: @hover-bg;
    color: @text-bright;
  }

  &.active {
    background: @accent;
    color: #FFFFFF;

    svg {
      stroke: #FFFFFF;
    }
  }

  &.disabled {
    color: @text-muted;
    cursor: default;
    opacity: 0.6;

    &:hover {
      background: transparent;
      color: @text-muted;
    }
  }
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.nav-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: @text-secondary;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;

  &:hover {
    background: @hover-bg;
    color: @text-bright;
  }
}

.nav-user {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
}

.user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: @accent;
  color: #FFFFFF;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name-text {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 12px;
  color: @text-secondary;
}

/* ===== 内容区域 ===== */
.content-area {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
}

/* ===== 聊天历史浮层侧边栏 ===== */
.chat-sidebar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 260px;
  background: @bg-sidebar;
  border-right: 1px solid @border-color;
  z-index: 150;
  display: flex;
  flex-direction: column;
  box-shadow: 4px 0 16px rgba(0, 0, 0, 0.08);
}

.slide-sidebar-enter-active,
.slide-sidebar-leave-active {
  transition: transform 0.2s ease;
}
.slide-sidebar-enter,
.slide-sidebar-leave-to {
  transform: translateX(-100%);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 12px 8px;
  flex-shrink: 0;
}

.sidebar-title {
  font-family: 'Fira Code', monospace;
  font-size: 13px;
  font-weight: 600;
  color: @text-bright;
}

.icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: @text-muted;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover {
    background: @hover-bg;
    color: @text-secondary;
  }
}

.new-chat-btn {
  margin: 4px 12px 8px;
  height: 36px;
  border: 1px solid @border-color;
  border-radius: 10px;
  background: @bg-main;
  color: @text-secondary;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover {
    background: @hover-bg;
    border-color: #C5C5CC;
    color: @text-bright;
  }
}

/* ===== 聊天历史列表 ===== */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #C5C5CC;
    border-radius: 4px;
  }
}

.chat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  margin: 1px 0;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;

  &:hover {
    background: @hover-bg;
  }

  &.active {
    background: @accent-dim;
    border: 1px solid fadeout(@accent, 80%);
  }
}

.chat-item-icon {
  color: @text-muted;
  flex-shrink: 0;
}

.chat-item.active .chat-item-icon {
  color: @accent;
}

.chat-title {
  flex: 1;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: #64748B;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.chat-item.active .chat-title {
  color: @text-bright;
}

.chat-menu-btn {
  opacity: 0;
  color: @text-muted;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.12s;
  cursor: pointer;
  flex-shrink: 0;
}

.chat-item:hover .chat-menu-btn {
  opacity: 1;
}

.chat-menu-btn:hover {
  color: @text-secondary;
  background: rgba(0, 0, 0, 0.04);
}

/* ===== 左侧聊天面板 ===== */
.chat-panel {
  flex: 0 0 50%;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-right: 1px solid @border-color;
}

.chat-panel-header {
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-bottom: 1px solid @border-color;
  background: @bg-sidebar;
}

.chat-panel-title {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: @text-bright;
}

/* ===== 右侧数据面板 ===== */
.data-panel-container {
  flex: 0 0 50%;
  display: flex;
  flex-direction: column;
  background: @bg-sidebar;
  border-left: 1px solid @border-color;
}
</style>
