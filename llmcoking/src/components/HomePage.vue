<template>
    <el-container>
        <!--侧边栏-->
        <el-aside :style="{ width: isCollapese ? '0px' : '260px' }">
            <!-- 侧边栏完整内容 -->
            <div v-if="!isCollapese" class="sidebar-inner">
                <!-- 顶部：logo + 折叠 + 新对话 -->
                <div class="sidebar-top">
                    <div class="sidebar-header">
                        <div class="logo">
                            <span class="logo-dot"></span>
                            DeepResearch
                        </div>
                        <button class="icon-btn" @click="toggleCollapse" title="收起侧边栏">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="11 17 6 12 11 7"/>
                                <polyline points="18 17 13 12 18 7"/>
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
                </div>

                <!-- 历史对话记录 -->
                <div class="chat-history">
                    <div class="history-header">
                        <div class="history-label">历史对话</div>
                        <div class="history-actions">
                            <span v-if="!multiSelectMode" class="history-action-btn" title="新建文件夹" @click="createFolder">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                                    <line x1="12" y1="11" x2="12" y2="17"/>
                                    <line x1="9" y1="14" x2="15" y2="14"/>
                                </svg>
                            </span>
                            <span v-if="!multiSelectMode" class="history-action-btn" title="多选" @click="enterMultiSelect">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                    <rect x="3" y="3" width="7" height="7"/>
                                    <rect x="14" y="3" width="7" height="7"/>
                                    <rect x="3" y="14" width="7" height="7"/>
                                    <polyline points="14 17 17 20 22 14"/>
                                </svg>
                            </span>
                            <span v-if="multiSelectMode" class="history-action-btn text-action" @click="toggleSelectAll">
                                {{ isAllSelected ? '取消' : '全选' }}
                            </span>
                            <span v-if="multiSelectMode" class="history-action-btn text-action" @click="exitMultiSelect">退出</span>
                        </div>
                    </div>

                    <!-- 文件夹分组 -->
                    <div v-for="folder in folders" :key="'folder-' + folder.id" class="folder-group">
                        <div class="folder-header" @click="toggleFolder(folder.id)">
                            <svg class="folder-caret" :class="{ open: expandedFolderIds.includes(folder.id) }" viewBox="0 0 24 24" width="10" height="10" fill="currentColor">
                                <polygon points="6 4 18 12 6 20"/>
                            </svg>
                            <svg class="folder-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                            </svg>
                            <span class="folder-name">{{ folder.name }}</span>
                            <span class="folder-count">{{ sessionsByFolder[folder.id] ? sessionsByFolder[folder.id].length : 0 }}</span>
                            <el-dropdown trigger="click" @command="handleFolderMenuCommand($event, folder)">
                                <span class="chat-menu-btn folder-menu" @click.stop>
                                    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor">
                                        <circle cx="12" cy="5" r="1.5"/>
                                        <circle cx="12" cy="12" r="1.5"/>
                                        <circle cx="12" cy="19" r="1.5"/>
                                    </svg>
                                </span>
                                <el-dropdown-menu slot="dropdown">
                                    <el-dropdown-item command="rename">重命名</el-dropdown-item>
                                    <el-dropdown-item command="delete">删除文件夹</el-dropdown-item>
                                </el-dropdown-menu>
                            </el-dropdown>
                        </div>
                        <div v-if="expandedFolderIds.includes(folder.id)" class="folder-content">
                            <div
                              v-for="session in (sessionsByFolder[folder.id] || [])"
                              :key="session.session_id"
                              class="chat-item nested"
                              :class="{ active: sessionId === session.session_id, selected: selectedIds.includes(session.session_id) }"
                              @click="onSessionClick(session.session_id)"
                            >
                                <input v-if="multiSelectMode" type="checkbox" class="chat-checkbox" :checked="selectedIds.includes(session.session_id)" @click.stop="toggleSelect(session.session_id)" />
                                <svg v-else class="chat-item-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                                </svg>
                                <span class="chat-title">{{ session.title }}</span>
                                <el-dropdown v-if="!multiSelectMode" trigger="click" @command="handleMenuCommand($event, session.session_id)">
                                    <span class="chat-menu-btn" @click.stop>
                                        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                                            <circle cx="12" cy="5" r="1.5"/>
                                            <circle cx="12" cy="12" r="1.5"/>
                                            <circle cx="12" cy="19" r="1.5"/>
                                        </svg>
                                    </span>
                                    <el-dropdown-menu slot="dropdown">
                                        <el-dropdown-item command="rename">重命名</el-dropdown-item>
                                        <el-dropdown-item :command="'move:' + session.session_id">移动到…</el-dropdown-item>
                                        <el-dropdown-item command="delete">删除</el-dropdown-item>
                                    </el-dropdown-menu>
                                </el-dropdown>
                            </div>
                        </div>
                    </div>

                    <!-- 根目录会话 -->
                    <div v-if="folders.length > 0 && sessionsByFolder['root'] && sessionsByFolder['root'].length > 0" class="root-divider">未分组</div>
                    <div
                      v-for="session in (sessionsByFolder['root'] || [])"
                      :key="session.session_id"
                      class="chat-item"
                      :class="{ active: sessionId === session.session_id, selected: selectedIds.includes(session.session_id) }"
                      @click="onSessionClick(session.session_id)"
                    >
                        <input v-if="multiSelectMode" type="checkbox" class="chat-checkbox" :checked="selectedIds.includes(session.session_id)" @click.stop="toggleSelect(session.session_id)" />
                        <svg v-else class="chat-item-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                        </svg>
                        <span class="chat-title">{{ session.title }}</span>
                        <el-dropdown v-if="!multiSelectMode" trigger="click" @command="handleMenuCommand($event, session.session_id)">
                            <span class="chat-menu-btn" @click.stop>
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                                    <circle cx="12" cy="5" r="1.5"/>
                                    <circle cx="12" cy="12" r="1.5"/>
                                    <circle cx="12" cy="19" r="1.5"/>
                                </svg>
                            </span>
                            <el-dropdown-menu slot="dropdown">
                                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                                <el-dropdown-item :command="'move:' + session.session_id">移动到…</el-dropdown-item>
                                <el-dropdown-item command="delete">删除</el-dropdown-item>
                            </el-dropdown-menu>
                        </el-dropdown>
                    </div>
                </div>

                <!-- 多选模式底部操作条 -->
                <div v-if="multiSelectMode" class="multi-action-bar">
                    <div class="multi-action-count">已选 {{ selectedIds.length }} 项</div>
                    <div class="multi-action-buttons">
                        <el-dropdown trigger="click" placement="top-start" @command="onMoveCommand">
                            <button class="multi-btn" :disabled="selectedIds.length === 0">
                                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                                </svg>
                                移动
                            </button>
                            <el-dropdown-menu slot="dropdown">
                                <el-dropdown-item v-for="f in folders" :key="'mv-' + f.id" :command="'folder:' + f.id">{{ f.name }}</el-dropdown-item>
                                <el-dropdown-item command="folder:none" divided>移出文件夹</el-dropdown-item>
                                <el-dropdown-item command="folder:new" divided>+ 新建文件夹</el-dropdown-item>
                            </el-dropdown-menu>
                        </el-dropdown>
                        <button class="multi-btn danger" :disabled="selectedIds.length === 0" @click="batchDelete">
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                            </svg>
                            删除
                        </button>
                    </div>
                </div>

                <!-- 侧边栏底部 -->
                <div class="sidebar-bottom">
                    <button class="sidebar-bottom-btn" @click="$router.push('/Home/AdminPapers')" title="管理文献知识库(上传 PDF / 删除 / 重抽摘要)">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
                        </svg>
                        <span>知识库管理</span>
                    </button>
                    <button class="sidebar-bottom-btn" @click="goLanding">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                            <polyline points="9 22 9 12 15 12 15 22"/>
                        </svg>
                        <span>返回首页</span>
                    </button>
                </div>
            </div>
        </el-aside>

        <!--右侧内容主体区域-->
        <el-main>
            <!-- 顶栏 -->
            <div class="top-bar">
                <button v-if="isCollapese" class="icon-btn" @click="toggleCollapse" title="展开侧边栏">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="13 17 18 12 13 7"/>
                        <polyline points="6 17 11 12 6 7"/>
                    </svg>
                </button>
                <div class="top-bar-right">
                    <button class="voice-top-btn" @click="goVoiceChat">
                        <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                            <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/>
                        </svg>
                        <span>语音对话</span>
                    </button>
                </div>
            </div>
            <router-view :sessionId="sessionId" :isCollapese="isCollapese" @update-sessions="fetchChatSessions"></router-view>
        </el-main>
    </el-container>
</template>

<script>
import { apiFetch } from '../api'

export default {
  data () {
    return {
      isCollapese: false,
      chatSessions: [],
      folders: [],
      expandedFolderIds: [],
      sessionId: '',
      userId: 'user123',
      multiSelectMode: false,
      selectedIds: []
    }
  },
  computed: {
    sessionsByFolder () {
      const map = { root: [] }
      for (const f of this.folders) map[f.id] = []
      for (const s of this.chatSessions) {
        const k = s.folder_id != null && map[s.folder_id] ? s.folder_id : 'root'
        map[k].push(s)
      }
      return map
    },
    isAllSelected () {
      return this.chatSessions.length > 0 && this.selectedIds.length === this.chatSessions.length
    }
  },
  methods: {
    toggleCollapse () {
      this.isCollapese = !this.isCollapese
    },
    goLanding () {
      this.$router.push('/landing')
    },
    async startNewChat () {
      try {
        const response = await apiFetch(`/new_session/?user_id=${this.userId}`, {
          method: 'POST'
        })
        const data = await response.json()
        this.sessionId = data.session_id

        this.chatSessions.unshift({
          session_id: this.sessionId,
          title: '新对话',
          folder_id: null
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
    goVoiceChat () {
      this.$router.push('/Home/VoiceAgent')
    },
    onSessionClick (sessionId) {
      if (this.multiSelectMode) {
        this.toggleSelect(sessionId)
      } else {
        this.selectSession(sessionId)
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
        const response = await apiFetch(`/user_sessions/?user_id=${this.userId}`)
        const data = await response.json()
        if (!Array.isArray(data)) return

        this.chatSessions = data.map(session => ({
          session_id: session.session_id,
          title: session.title || `对话 ${session.session_id.slice(0, 6)}`,
          folder_id: session.folder_id != null ? session.folder_id : null
        }))
      } catch (error) {
        console.error('加载历史会话失败:', error)
      }
    },
    async fetchFolders () {
      try {
        const response = await apiFetch(`/folders/?user_id=${this.userId}`)
        const data = await response.json()
        if (Array.isArray(data)) {
          this.folders = data
          // 默认全部展开
          this.expandedFolderIds = data.map(f => f.id)
        }
      } catch (error) {
        console.error('加载文件夹失败:', error)
      }
    },
    toggleFolder (folderId) {
      const i = this.expandedFolderIds.indexOf(folderId)
      if (i >= 0) this.expandedFolderIds.splice(i, 1)
      else this.expandedFolderIds.push(folderId)
    },
    async createFolder () {
      const name = prompt('请输入文件夹名称:')
      if (!name || !name.trim()) return
      try {
        const res = await apiFetch('/folders/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: this.userId, name: name.trim() })
        })
        if (res.ok) {
          const folder = await res.json()
          this.folders.push(folder)
          this.expandedFolderIds.push(folder.id)
          return folder
        } else {
          alert('新建文件夹失败')
        }
      } catch (e) {
        console.error('网络错误:', e)
      }
    },
    async handleFolderMenuCommand (command, folder) {
      if (command === 'rename') {
        const newName = prompt('请输入新的文件夹名称:', folder.name)
        if (!newName || !newName.trim()) return
        try {
          const res = await apiFetch(`/folders/${folder.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName.trim() })
          })
          if (res.ok) {
            folder.name = newName.trim()
          }
        } catch (e) { console.error(e) }
      } else if (command === 'delete') {
        if (!confirm(`删除文件夹「${folder.name}」？里面的对话会回到「未分组」。`)) return
        try {
          const res = await apiFetch(`/folders/${folder.id}`, { method: 'DELETE' })
          if (res.ok) {
            this.folders = this.folders.filter(f => f.id !== folder.id)
            for (const s of this.chatSessions) {
              if (s.folder_id === folder.id) s.folder_id = null
            }
          }
        } catch (e) { console.error(e) }
      }
    },
    enterMultiSelect () {
      this.multiSelectMode = true
      this.selectedIds = []
    },
    exitMultiSelect () {
      this.multiSelectMode = false
      this.selectedIds = []
    },
    toggleSelect (sessionId) {
      const i = this.selectedIds.indexOf(sessionId)
      if (i >= 0) this.selectedIds.splice(i, 1)
      else this.selectedIds.push(sessionId)
    },
    toggleSelectAll () {
      if (this.isAllSelected) this.selectedIds = []
      else this.selectedIds = this.chatSessions.map(s => s.session_id)
    },
    async batchDelete () {
      if (this.selectedIds.length === 0) return
      if (!confirm(`确定要删除选中的 ${this.selectedIds.length} 个会话吗？此操作不可恢复。`)) return
      try {
        const res = await apiFetch('/sessions/batch_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_ids: this.selectedIds })
        })
        if (res.ok) {
          const deletedSet = new Set(this.selectedIds)
          this.chatSessions = this.chatSessions.filter(s => !deletedSet.has(s.session_id))
          if (deletedSet.has(this.sessionId)) {
            this.sessionId = this.chatSessions.length > 0 ? this.chatSessions[0].session_id : ''
            if (this.sessionId) this.$router.push(`/Home/MainDia/${this.sessionId}`)
          }
          this.exitMultiSelect()
        } else {
          alert('批量删除失败')
        }
      } catch (e) { console.error(e) }
    },
    async onMoveCommand (command) {
      // command 形如 "folder:5" / "folder:none" / "folder:new"
      const value = String(command).split(':')[1]
      let folderId = null
      if (value === 'new') {
        const folder = await this.createFolder()
        if (!folder) return
        folderId = folder.id
      } else if (value !== 'none') {
        folderId = parseInt(value, 10)
      }
      await this.moveSelected(folderId)
    },
    async moveSelected (folderId) {
      if (this.selectedIds.length === 0) return
      try {
        const res = await apiFetch('/sessions/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_ids: this.selectedIds, folder_id: folderId })
        })
        if (res.ok) {
          const movedSet = new Set(this.selectedIds)
          for (const s of this.chatSessions) {
            if (movedSet.has(s.session_id)) s.folder_id = folderId
          }
          if (folderId != null && !this.expandedFolderIds.includes(folderId)) {
            this.expandedFolderIds.push(folderId)
          }
          this.exitMultiSelect()
        }
      } catch (e) { console.error(e) }
    },
    async handleMenuCommand (command, sessionId) {
      if (command === 'rename') {
        this.renameSession(sessionId)
      } else if (command === 'delete') {
        this.deleteSession(sessionId)
      } else if (typeof command === 'string' && command.startsWith('move:')) {
        // 单条移动：临时把当前条放进 selectedIds，复用 moveSelected
        this.selectedIds = [sessionId]
        // 弹一个最小选择（这里简单实现：用 prompt 让用户选）
        const choices = this.folders.map((f, idx) => `${idx + 1}. ${f.name}`).join('\n')
        const tip = `输入要移动到的文件夹编号（0 = 移出文件夹）：\n0. （未分组）\n${choices}`
        const input = prompt(tip)
        if (input === null) { this.selectedIds = []; return }
        const idx = parseInt(input, 10)
        if (isNaN(idx) || idx < 0 || idx > this.folders.length) { this.selectedIds = []; return }
        const folderId = idx === 0 ? null : this.folders[idx - 1].id
        await this.moveSelected(folderId)
      }
    },
    async renameSession (sessionId) {
      const newTitle = prompt('请输入新的会话名称:')
      if (!newTitle) return

      try {
        const response = await apiFetch(`/rename_session/?session_id=${sessionId}&new_title=${encodeURIComponent(newTitle)}`, {
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
        const response = await apiFetch(`/delete_session/?session_id=${sessionId}`, {
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
    this.fetchFolders()
  }
}
</script>

<style lang="less" scoped>

/* ===== 布局 ===== */
.el-container {
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100vh;
}

/* ===== 侧边栏 ===== */
.el-aside {
  background: #0a0a0a;
  width: 260px;
  position: relative;
  height: 100vh;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 260px;
}

.sidebar-top {
  padding: 14px 12px;
  flex-shrink: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding: 2px 0;
}

.logo {
  font-family: 'Orbitron', 'Fira Code', monospace;
  font-size: 18px;
  font-weight: 700;
  color: #e0e0e0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ff8a00, #149efa);
  box-shadow: 0 0 8px rgba(20, 158, 250, 0.4);
}

/* ===== 通用图标按钮 ===== */
.icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #666;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #aaa;
}

/* ===== 新对话按钮 ===== */
.new-chat-btn {
  width: 100%;
  height: 38px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  color: #c0c0c0;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.new-chat-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.18);
  color: #e0e0e0;
}

/* ===== 历史记录 ===== */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px 6px;
}

.history-label {
  font-size: 11px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-family: 'Fira Code', monospace;
}

.history-actions {
  display: flex;
  gap: 4px;
  align-items: center;
}

.history-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 6px;
  color: #666;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s;
}

.history-action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #ccc;
}

.history-action-btn.text-action {
  font-family: inherit;
  letter-spacing: 0;
  text-transform: none;
}

/* ===== 文件夹 ===== */
.folder-group {
  margin: 2px 0;
}

.folder-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #888;
  transition: background 0.12s;
}

.folder-header:hover {
  background: rgba(255, 255, 255, 0.04);
}

.folder-caret {
  transition: transform 0.15s ease;
  color: #555;
  flex-shrink: 0;
}

.folder-caret.open {
  transform: rotate(90deg);
}

.folder-icon {
  color: #b89968;
  flex-shrink: 0;
}

.folder-name {
  flex: 1;
  font-size: 13px;
  color: #c0c0c0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.folder-count {
  font-size: 11px;
  color: #555;
  font-family: 'Fira Code', monospace;
}

.folder-menu {
  opacity: 0;
}

.folder-header:hover .folder-menu {
  opacity: 1;
}

.folder-content {
  padding-left: 10px;
}

.root-divider {
  font-size: 10px;
  color: #444;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 10px 12px 4px;
  font-family: 'Fira Code', monospace;
}

/* ===== 多选状态 ===== */
.chat-checkbox {
  width: 14px;
  height: 14px;
  margin: 0;
  cursor: pointer;
  accent-color: #149efa;
  flex-shrink: 0;
}

.chat-item.selected {
  background: rgba(20, 158, 250, 0.12);
  border: 1px solid rgba(20, 158, 250, 0.2);
}

.chat-item.nested {
  margin-left: 0;
}

/* ===== 底部多选操作条 ===== */
.multi-action-bar {
  flex-shrink: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
}

.multi-action-count {
  font-size: 11px;
  color: #888;
  margin-bottom: 8px;
  font-family: 'Fira Code', monospace;
}

.multi-action-buttons {
  display: flex;
  gap: 8px;
}

.multi-btn {
  flex: 1;
  height: 30px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  color: #c0c0c0;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.multi-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.18);
  color: #e0e0e0;
}

.multi-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.multi-btn.danger {
  color: #e57373;
  border-color: rgba(229, 115, 115, 0.18);
}

.multi-btn.danger:hover:not(:disabled) {
  background: rgba(229, 115, 115, 0.08);
  border-color: rgba(229, 115, 115, 0.35);
  color: #ff8a80;
}

.chat-history::-webkit-scrollbar {
  width: 4px;
}

.chat-history::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
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
}

.chat-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.chat-item.active {
  background: rgba(20, 158, 250, 0.08);
  border: 1px solid rgba(20, 158, 250, 0.12);
}

.chat-item-icon {
  color: #555;
  flex-shrink: 0;
}

.chat-item.active .chat-item-icon {
  color: #149efa;
}

.chat-title {
  flex: 1;
  font-size: 13px;
  color: #999;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.chat-item.active .chat-title {
  color: #d0d0d0;
}

.chat-menu-btn {
  opacity: 0;
  color: #666;
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
  color: #aaa;
  background: rgba(255, 255, 255, 0.08);
}

/* ===== 侧边栏底部 ===== */
.sidebar-bottom {
  flex-shrink: 0;
  padding: 8px 12px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.sidebar-bottom-btn {
  width: 100%;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #666;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.sidebar-bottom-btn:hover {
  background: rgba(255, 255, 255, 0.04);
  color: #aaa;
}

/* ===== 右侧主体 ===== */
.el-main {
  background: #0f0f0f;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  padding: 0;
  position: relative;
}

/* ===== 顶栏 ===== */
.top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  z-index: 100;
}

.top-bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.voice-top-btn {
  height: 32px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  color: #888;
  font-size: 13px;
  padding: 0 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.voice-top-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ccc;
  border-color: rgba(255, 255, 255, 0.15);
}

.voice-top-btn svg {
  opacity: 0.6;
}

</style>
