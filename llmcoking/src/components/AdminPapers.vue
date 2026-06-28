<template>
  <div class="admin-papers">
    <!-- 顶栏 -->
    <div class="ap-header">
      <div class="ap-title">
        <span class="ap-icon">📚</span>
        <h2>文献知识库管理</h2>
        <span class="ap-counter">
          {{ total }} 篇 · 已生成深度摘要 {{ totalWithSummary }} 篇
        </span>
      </div>
      <div class="ap-actions">
        <button class="btn btn-primary" @click="triggerUpload">
          <span>⬆️</span> 上传 PDF
        </button>
        <button class="btn btn-ghost" @click="refresh">
          <span>🔄</span> 刷新
        </button>
        <button class="btn btn-ghost" @click="$router.push('/Home/MainDia/new')">
          <span>←</span> 返回聊天
        </button>
      </div>
    </div>

    <!-- 上传任务进度条 -->
    <div v-if="jobs.length" class="ap-jobs">
      <div v-for="job in jobs" :key="job.job_id" class="job-card" :class="job.status">
        <div class="job-head">
          <span class="job-name">{{ job.filename || job.paper_id }}</span>
          <span class="job-status">{{ statusLabel(job.status) }}</span>
        </div>
        <div class="job-msg">{{ job.message }}</div>
      </div>
    </div>

    <!-- 隐藏的文件选择 -->
    <input
      ref="fileInput"
      type="file"
      accept=".pdf"
      multiple
      style="display:none"
      @change="onFileSelected"
    />

    <!-- 搜索过滤 -->
    <div class="ap-filter">
      <input
        v-model="filter"
        type="text"
        placeholder="搜索标题 / 作者 / 类别 ..."
        class="filter-input"
      />
      <select v-model="filterSummary" class="filter-select">
        <option value="all">全部</option>
        <option value="with">有深度摘要</option>
        <option value="without">无深度摘要</option>
      </select>
    </div>

    <!-- 表格 -->
    <div class="ap-table-wrap">
      <table class="ap-table">
        <thead>
          <tr>
            <th width="60">ID</th>
            <th>标题</th>
            <th width="180">作者</th>
            <th width="70">年份</th>
            <th width="120">类别</th>
            <th width="80">片段数</th>
            <th width="100">深度摘要</th>
            <th width="160">入库时间</th>
            <th width="200">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in filteredPapers" :key="p.id">
            <td class="cell-id">{{ p.id }}</td>
            <td class="cell-title" :title="p.title">{{ p.title || '(无标题)' }}</td>
            <td class="cell-authors" :title="p.authors">{{ shortenAuthors(p.authors) }}</td>
            <td>{{ p.year || '-' }}</td>
            <td>
              <span class="badge-cat">{{ p.category || 'uncategorized' }}</span>
            </td>
            <td class="text-right">{{ p.chunk_count || 0 }}</td>
            <td>
              <span v-if="p.has_deep_summary" class="badge-ok">✓ 已生成</span>
              <span v-else class="badge-no">未生成</span>
            </td>
            <td class="cell-date">{{ formatDate(p.ingested_at) }}</td>
            <td class="cell-actions">
              <a
                class="op-link"
                :href="apiUrlWithToken('/papers/' + p.id + '/pdf')"
                target="_blank"
                title="查看 PDF"
              >🔍 PDF</a>
              <button class="op-link" @click="rebuildSummary(p)">🔄 重抽</button>
              <button class="op-link danger" @click="deletePaper(p)">🗑 删除</button>
            </td>
          </tr>
          <tr v-if="!filteredPapers.length">
            <td colspan="9" class="empty-row">没有符合条件的文献</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { apiFetch, apiUrlWithToken } from '../api'

export default {
  name: 'AdminPapers',
  data () {
    return {
      papers: [],
      total: 0,
      totalWithSummary: 0,
      jobs: [], // 进行中的任务列表
      filter: '',
      filterSummary: 'all',
      pollingTimer: null
    }
  },
  computed: {
    filteredPapers () {
      const q = this.filter.trim().toLowerCase()
      return this.papers.filter(p => {
        if (this.filterSummary === 'with' && !p.has_deep_summary) return false
        if (this.filterSummary === 'without' && p.has_deep_summary) return false
        if (!q) return true
        return (
          (p.title || '').toLowerCase().includes(q) ||
          (p.authors || '').toLowerCase().includes(q) ||
          (p.category || '').toLowerCase().includes(q)
        )
      })
    }
  },
  mounted () {
    this.refresh()
    // 每 5 秒轮询一次进度
    this.pollingTimer = setInterval(this.pollJobs, 5000)
  },
  beforeDestroy () {
    if (this.pollingTimer) clearInterval(this.pollingTimer)
  },
  methods: {
    apiUrlWithToken,
    async refresh () {
      try {
        const r = await apiFetch('/admin/papers/list?limit=1000')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = await r.json()
        this.papers = data.items || []
        this.total = data.total
        this.totalWithSummary = data.total_with_summary
      } catch (e) {
        this.$message && this.$message.error('加载文献列表失败: ' + e.message)
      }
    },
    triggerUpload () {
      if (this.$refs.fileInput) this.$refs.fileInput.click()
    },
    async onFileSelected (e) {
      const files = Array.from(e.target.files || [])
      e.target.value = ''
      for (const f of files) {
        await this.uploadOne(f)
      }
    },
    async uploadOne (file) {
      const form = new FormData()
      form.append('file', file)
      try {
        const r = await apiFetch('/admin/papers/upload', {
          method: 'POST',
          body: form
        })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = await r.json()
        this.jobs.unshift({
          job_id: data.job_id,
          filename: data.filename,
          status: 'queued',
          message: '已上传,正在排队'
        })
        this.$message && this.$message.success(`已上传 ${file.name}`)
      } catch (e) {
        this.$message && this.$message.error('上传失败: ' + e.message)
      }
    },
    async pollJobs () {
      const live = this.jobs.filter(j =>
        j.status !== 'done' && j.status !== 'error' && j.status !== 'done_no_summary'
      )
      if (!live.length) return
      for (const j of live) {
        try {
          const r = await apiFetch('/admin/papers/jobs/' + j.job_id)
          if (!r.ok) continue
          const data = await r.json()
          j.status = data.status
          j.message = data.message
          j.paper_id = data.paper_id
          j.title = data.title
        } catch (_) { /* ignore */ }
      }
      // 如有任务完成,刷新列表
      const justDone = live.filter(j => j.status === 'done' || j.status === 'done_no_summary')
      if (justDone.length) {
        this.refresh()
      }
    },
    statusLabel (s) {
      return ({
        queued: '⏳ 排队中',
        ingesting: '📥 解析中',
        summarizing: '🧠 生成摘要中',
        done: '✅ 完成',
        done_no_summary: '⚠️ 完成(摘要失败)',
        error: '❌ 失败'
      })[s] || s
    },
    shortenAuthors (a) {
      if (!a) return '-'
      if (a.length > 30) return a.slice(0, 28) + '…'
      return a
    },
    formatDate (s) {
      if (!s) return '-'
      try {
        const d = new Date(s.replace(' ', 'T'))
        return d.toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        })
      } catch (_) {
        return s
      }
    },
    async deletePaper (p) {
      if (!confirm(`确认删除 paper_id=${p.id} 《${p.title || ''}》? PDF 文件不会被删,但向量库 chunks 会清掉。`)) return
      try {
        const r = await apiFetch('/admin/papers/' + p.id, { method: 'DELETE' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = await r.json()
        this.$message && this.$message.success(`已删除 paper_id=${p.id} (清掉 ${data.chunks_deleted} chunks)`)
        this.refresh()
      } catch (e) {
        this.$message && this.$message.error('删除失败: ' + e.message)
      }
    },
    async rebuildSummary (p) {
      if (!confirm(`重新生成 paper_id=${p.id} 的深度摘要?需要 2-5 分钟,期间不影响查询。`)) return
      try {
        const r = await apiFetch('/admin/papers/' + p.id + '/rebuild', { method: 'POST' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = await r.json()
        this.jobs.unshift({
          job_id: data.job_id,
          filename: p.title || ('paper_' + p.id),
          paper_id: p.id,
          status: 'queued',
          message: '排队中'
        })
        this.$message && this.$message.success(`已触发重抽 paper_id=${p.id}`)
      } catch (e) {
        this.$message && this.$message.error('触发失败: ' + e.message)
      }
    }
  }
}
</script>

<style scoped>
.admin-papers {
  padding: 24px 32px;
  max-width: 1500px;
  margin: 0 auto;
  background: #f7f9fc;
  /* 父级 el-main 是 overflow:hidden,本页需自己撑满并内部滚动,否则内容超出无滚动条 */
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
  color: #1a3556;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.ap-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid #e0e7ef;
  margin-bottom: 20px;
}
.ap-title { display: flex; align-items: center; gap: 12px; }
.ap-icon { font-size: 24px; }
.ap-title h2 { margin: 0; font-size: 20px; font-weight: 700; }
.ap-counter {
  color: #6b7c93;
  font-size: 13px;
  margin-left: 12px;
}
.ap-actions { display: flex; gap: 10px; }

.btn {
  padding: 7px 16px;
  border: none;
  border-radius: 6px;
  font-size: 13.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-primary { background: #4a90e2; color: #fff; }
.btn-primary:hover { background: #3a7bcc; }
.btn-ghost { background: #fff; color: #4a90e2; border: 1px solid #4a90e2; }
.btn-ghost:hover { background: #eaf2fc; }

.ap-jobs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.job-card {
  background: #fff;
  border: 1px solid #d3dde9;
  border-left-width: 4px;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 13px;
}
.job-card.queued     { border-left-color: #999; }
.job-card.ingesting  { border-left-color: #4a90e2; }
.job-card.summarizing{ border-left-color: #7c4dff; }
.job-card.done       { border-left-color: #2ecc71; background: #ecf9f1; }
.job-card.done_no_summary { border-left-color: #f0ad4e; background: #fdf6e3; }
.job-card.error      { border-left-color: #e74c3c; background: #fdecea; }
.job-head { display: flex; justify-content: space-between; font-weight: 600; }
.job-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80%; }
.job-msg { color: #6b7c93; font-size: 12px; margin-top: 4px; }

.ap-filter { display: flex; gap: 12px; margin-bottom: 14px; }
.filter-input {
  flex: 1;
  padding: 7px 12px;
  border: 1px solid #d3dde9;
  border-radius: 6px;
  font-size: 13px;
}
.filter-select {
  padding: 7px 12px;
  border: 1px solid #d3dde9;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
}

.ap-table-wrap {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}
.ap-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ap-table th {
  background: #f0f5fa;
  text-align: left;
  padding: 10px 12px;
  font-weight: 600;
  border-bottom: 1px solid #e0e7ef;
  color: #1a3556;
  white-space: nowrap;
}
.ap-table td {
  padding: 9px 12px;
  border-bottom: 1px solid #f0f4f8;
  vertical-align: middle;
}
.ap-table tr:hover td { background: #f9fbfd; }
.cell-id { color: #999; font-family: monospace; }
.cell-title {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.cell-authors {
  color: #6b7c93;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-date { color: #6b7c93; font-size: 12px; }
.text-right { text-align: right; }

.badge-cat {
  display: inline-block;
  padding: 2px 8px;
  background: #eaf2fc;
  color: #4a90e2;
  border-radius: 10px;
  font-size: 11.5px;
}
.badge-ok {
  display: inline-block;
  padding: 2px 8px;
  background: #d4f4dd;
  color: #2ecc71;
  border-radius: 10px;
  font-size: 11.5px;
  font-weight: 600;
}
.badge-no {
  display: inline-block;
  padding: 2px 8px;
  background: #f5f5f5;
  color: #999;
  border-radius: 10px;
  font-size: 11.5px;
}

.cell-actions { display: flex; gap: 8px; }
.op-link {
  background: none;
  border: 1px solid transparent;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  text-decoration: none;
  color: #4a90e2;
}
.op-link:hover { background: #eaf2fc; }
.op-link.danger { color: #e74c3c; }
.op-link.danger:hover { background: #fdecea; }

.empty-row {
  text-align: center;
  padding: 40px 0 !important;
  color: #999;
}
</style>
