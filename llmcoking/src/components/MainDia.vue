<template>
  <div class="chat-wrapper">
    <!-- 聊天内容区域 -->
    <div class="chat-scroll" ref="chatScroll">
      <div class="chat-content">
        <!-- 欢迎区域（仅新会话且无消息时显示） -->
        <div v-if="messages.length <= 1 && sessionId === 'new'" class="welcome-area">
          <div class="welcome-logo">
            <img src="../assets/imgs/deepresearch_logo.png" alt="DR" />
          </div>
          <h2 class="welcome-title">有什么可以帮您？</h2>
          <div class="quick-actions">
            <div class="quick-item" v-for="(q, i) in quickQuestions" :key="i" @click="sendQuickQuestion(q.text)">
              <span class="quick-icon">{{ q.icon }}</span>
              <div class="quick-text">
                <span class="quick-main">{{ q.main }}</span>
                <span class="quick-sub">{{ q.sub }}</span>
              </div>
            </div>
          </div>
        </div>

        <div
          v-for="(message, index) in messages"
          :key="index"
          class="message-row"
          :class="message.type"
          :data-message-id="message.id"
          ref="lastMessage"
        >
          <!-- bot 头像 -->
          <div v-if="message.type === 'bot'" class="avatar bot-avatar">
            <img src="../assets/imgs/deepresearch_logo.png" alt="DR" />
          </div>

          <div class="message-bubble">
            <span v-if="message.text" v-html="renderMarkdown(message.text, message)"></span>
            <div v-else-if="message.type === 'bot'" class="loading-dots">
              <span></span><span></span><span></span>
            </div>
            <!-- 流式生成时的实时计时 + token 估算 -->
            <div v-if="message.streaming" class="gen-stats">
              <span class="gen-stats-dot"></span>
              <span class="gen-time">{{ formatElapsed(message.elapsedMs) }}</span>
              <span class="gen-sep">·</span>
              <span class="gen-tokens">~{{ message.tokens || 0 }} tokens</span>
            </div>
            <!-- 文献检索命中清单(literature_qa 路径才有):用 vis-network 渲染知识图谱 -->
            <div v-if="message.litqa" class="litqa-panel">
              <div class="litqa-panel-title">
                <span class="litqa-icon">📚</span>
                命中 {{ message.litqa.papers.length }} 篇 · 引用
                {{ message.litqa.papers.filter(p => p.cited).length }} 篇 · 取证
                {{ message.litqa.chunks.length }} 段
                <span class="litqa-hint">· 点节点查看 PDF</span>
              </div>
              <div v-if="activeConstraints(message)" class="litqa-constraints">
                <span class="litqa-constraints-icon">⛃</span>
                已按你的追问过滤：{{ activeConstraints(message) }}
              </div>
              <!-- 来源工具条:导出引用 -->
              <div
                v-if="message.litqa.papers && citedPapers(message.litqa.papers).length"
                class="litqa-toolbar"
              >
                <span class="litqa-toolbar-label">引用 {{ citedPapers(message.litqa.papers).length }} 篇</span>
                <button class="litqa-export-btn" @click="openFavDrawer">★ 我的收藏</button>
                <button class="litqa-export-btn" @click="exportCitations(message, 'bibtex')">⬇ BibTeX</button>
                <button class="litqa-export-btn" @click="exportCitations(message, 'ris')">⬇ RIS</button>
              </div>
              <!-- 来源面板:引用文献列表(类型徽章 + 年份/期刊,点击看 PDF) -->
              <div
                v-if="message.litqa.papers && message.litqa.papers.length"
                class="litqa-papers"
              >
                <div
                  v-for="p in citedPapers(message.litqa.papers)"
                  :key="p.paper_id"
                  class="litqa-paper"
                  @click="openPdfPreview(p, (message.litqa.chunks || []).find(c => c.paper_id === p.paper_id) || null)"
                >
                  <div class="litqa-paper-head">
                    <span v-if="p.ref_num" class="litqa-paper-ref">[{{ p.ref_num }}]</span>
                    <span class="litqa-doctype" :class="'dt-' + (p.doctype || 'research')">{{ doctypeLabel(p.doctype) }}</span>
                    <span class="litqa-paper-title">{{ p.title || ('Paper ' + p.paper_id) }}</span>
                    <span
                      class="litqa-fav"
                      :class="{ on: isFavorited(p.paper_id) }"
                      :title="isFavorited(p.paper_id) ? '取消收藏' : '收藏'"
                      @click.stop="toggleFavorite(p)"
                    >{{ isFavorited(p.paper_id) ? '★' : '☆' }}</span>
                  </div>
                  <div class="litqa-paper-meta">
                    <span v-if="p.year">{{ p.year }}</span>
                    <span v-if="p.journal" class="litqa-journal">{{ p.journal }}</span>
                    <span v-if="p.category" class="litqa-category">{{ p.category }}</span>
                  </div>
                  <div v-if="supportSents(message, p)" class="litqa-support">
                    <span class="litqa-support-label">支持的回答句</span>
                    <div
                      v-for="(s, si) in supportSents(message, p)"
                      :key="si"
                      class="litqa-support-sent"
                    >“{{ s }}”</div>
                  </div>
                  <div class="litqa-similar-bar">
                    <span class="litqa-similar-toggle" @click.stop="toggleSimilar(p.paper_id)">
                      🔗 相似论文 {{ similarOpen[p.paper_id] ? '▾' : '▸' }}
                    </span>
                    <span class="litqa-similar-toggle" @click.stop="startFocusRead(p)">📖 精读这篇</span>
                    <span class="litqa-similar-toggle" @click.stop="openNote(p)">📝 笔记</span>
                  </div>
                  <div v-if="similarOpen[p.paper_id]" class="litqa-similar-list" @click.stop>
                    <div v-if="!(similarCache[p.paper_id] || []).length" class="litqa-similar-empty">
                      {{ similarCache[p.paper_id] ? '暂无相似文献' : '加载中…' }}
                    </div>
                    <div
                      v-for="sp in (similarCache[p.paper_id] || [])"
                      :key="sp.paper_id"
                      class="litqa-similar-item"
                      @click.stop="openPdfPreview({ paper_id: sp.paper_id, title: sp.title }, null)"
                    >
                      <span class="litqa-similar-score">{{ Math.round(sp.score * 100) }}%</span>
                      <span class="litqa-similar-title">{{ sp.title || ('Paper ' + sp.paper_id) }}</span>
                      <span v-if="sp.year" class="litqa-similar-year">{{ sp.year }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div
                class="litqa-graph"
                :id="'litqa-graph-' + message.id"
                :ref="'litqaGraph_' + message.id"
              ></div>
              <!-- C⑨': 关键图表(从引用论文里按 query 选,点击跳 PDF 那页) -->
              <div
                v-if="message.litqa.figures && message.litqa.figures.length"
                class="litqa-figures"
              >
                <div class="litqa-figures-title">📈 相关图表 · 点击看原文</div>
                <div class="litqa-figures-grid">
                  <figure
                    v-for="(fig, fidx) in message.litqa.figures"
                    :key="fidx"
                    class="litqa-fig"
                    @click="openFigurePdf(message, fig)"
                  >
                    <img :src="figureUrl(fig)" :alt="fig.caption" loading="lazy" />
                    <figcaption>[{{ fig.ref }}] {{ fig.caption }}</figcaption>
                  </figure>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="input-area">
      <!-- 精读模式:锁定单篇提示条 -->
      <div v-if="focusPaper" class="focus-bar">
        📖 精读中：<span class="focus-title">{{ focusPaper.title }}</span>
        <span class="focus-exit" @click="exitFocusRead">退出精读 ✕</span>
      </div>
      <!-- 玻尔-A:回答模式选择器 -->
      <div class="mode-tabs">
        <button
          v-for="m in chatModes"
          :key="m.key"
          class="mode-tab"
          :class="{ active: chatMode === m.key }"
          :title="m.tip"
          @click="chatMode = m.key"
        >{{ m.label }}</button>
      </div>
      <div class="input-wrapper">
        <!-- 隐藏文件选择器 -->
        <input
          ref="filePicker"
          type="file"
          multiple
          style="display:none"
          @change="onFilesSelected"
        />

        <!-- 附件按钮 -->
        <button class="input-icon-btn" @click="openFilePicker" title="添加文件">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>

        <el-input
          ref="inputBox"
          v-model="newMessage"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="给 DeepResearch 发送消息..."
          @keydown.enter.native.prevent="sendMessage"
          class="input-box"
        ></el-input>

        <!-- 听写按钮 -->
        <button
          class="input-icon-btn"
          :class="{ active: isDictating }"
          @click="toggleDictation"
          title="语音输入"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
            <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/>
          </svg>
        </button>

        <!-- 发送按钮 -->
        <button class="send-btn" :class="{ 'has-text': newMessage.trim() }" @click="sendMessage">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
      <div class="input-footer">内容由 AI 生成，请仔细甄别</div>
    </div>

    <!-- PDF 预览抽屉(右侧滑入) -->
    <transition name="pdf-drawer">
      <div v-if="previewPaper" class="pdf-drawer-mask" @click.self="closePdfPreview">
        <div class="pdf-drawer">
          <div class="pdf-drawer-header">
            <div class="pdf-drawer-title-wrap">
              <div class="pdf-drawer-title">{{ previewPaper.title || '(无标题)' }}</div>
              <div class="pdf-drawer-meta">
                <span v-if="previewPaper.year">{{ previewPaper.year }}</span>
                <span v-if="previewPaper.journal">· {{ previewPaper.journal }}</span>
                <span v-if="previewPaper.authors && previewPaper.authors !== '[]'">· {{ previewPaper.authors }}</span>
              </div>
            </div>
            <a
              class="pdf-drawer-newtab"
              :href="apiUrlWithToken('/papers/' + previewPaper.paper_id + '/pdf')"
              target="_blank"
              title="新窗口打开"
            >↗</a>
            <button class="pdf-drawer-close" @click="closePdfPreview" title="关闭">×</button>
          </div>
          <!-- 点 [n] 时附带的引用片段:浅黄高亮显示 LLM 引用的那段 chunk 原文 -->
          <div v-if="previewChunk && previewChunk.text" class="pdf-drawer-chunk">
            <div class="pdf-drawer-chunk-head">
              📌 引用片段 [{{ previewChunk.ref }}]
              <span v-if="previewChunk.section"> · {{ previewChunk.section }}</span>
              <span v-if="previewChunk.score"> · 相似度 {{ Math.round(previewChunk.score * 100) }}%</span>
            </div>
            <div class="pdf-drawer-chunk-text">{{ previewChunk.text }}</div>
          </div>
          <iframe
            v-if="previewPdfBlobUrl && !previewPdfError"
            class="pdf-drawer-iframe"
            :src="pdfViewerSrc()"
            frameborder="0"
          ></iframe>
          <div v-else-if="previewPdfError" class="pdf-drawer-fallback">
            <div class="pdf-drawer-fallback-icon">📄</div>
            <div class="pdf-drawer-fallback-text">{{ previewPdfError }}</div>
          </div>
          <div v-else class="pdf-drawer-fallback">
            <div class="pdf-drawer-fallback-text">正在加载 PDF…</div>
          </div>
        </div>
      </div>
    </transition>

    <!-- ⑫ 我的收藏抽屉 -->
    <transition name="fav-fade">
      <div v-if="showFavDrawer" class="fav-mask" @click.self="showFavDrawer = false">
        <div class="fav-drawer">
          <div class="fav-drawer-head">
            <span>★ 我的收藏 ({{ favList.length }})</span>
            <span class="fav-close" @click="showFavDrawer = false">✕</span>
          </div>
          <div v-if="!favList.length" class="fav-empty">还没有收藏文献。点论文卡上的 ☆ 收藏。</div>
          <div v-else class="fav-list">
            <div v-for="f in favList" :key="f.paper_id" class="fav-item">
              <div class="fav-item-main" @click="openPdfPreview({ paper_id: f.paper_id, title: f.title }, null)">
                <div class="fav-item-title">{{ f.title || ('Paper ' + f.paper_id) }}</div>
                <div class="fav-item-meta">{{ f.authors || '' }}{{ f.year ? ' · ' + f.year : '' }}</div>
              </div>
              <span class="fav-item-del" title="取消收藏" @click="removeFavorite(f.paper_id)">✕</span>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 句子级证据链:点 [N] 弹的结构化证据卡 -->
    <div v-if="evidenceCard.show" class="ev-mask" @click="closeEvidenceCard">
      <div
        class="ev-card"
        :style="{ left: evidenceCard.x + 'px', top: evidenceCard.y + 'px' }"
        @click.stop
      >
        <span class="ev-close" @click="closeEvidenceCard">✕</span>
        <div v-if="evidenceCard.claim" class="ev-claim">{{ evidenceCard.claim }}</div>
        <div class="ev-row">
          <span class="ev-k">来源</span>
          <span class="ev-v">{{ evidenceCard.paper.title || ('Paper ' + evidenceCard.paper.paper_id) }}<em v-if="evidenceCard.paper.year"> ({{ evidenceCard.paper.year }})</em></span>
        </div>
        <div v-if="evidenceCard.v" class="ev-row">
          <span class="ev-k">证据类型</span>
          <span class="ev-v">{{ evidenceCard.v.evidence_type || '正文' }}</span>
        </div>
        <div v-if="evidenceCard.v && evidenceCard.v.page" class="ev-row">
          <span class="ev-k">页码</span>
          <span class="ev-v">第 {{ evidenceCard.v.page }} 页</span>
        </div>
        <div v-if="evidenceCard.v" class="ev-row">
          <span class="ev-k">置信度</span>
          <span
            class="ev-v ev-conf"
            :class="{ 'conf-high': evidenceCard.v.confidence === '高', 'conf-mid': evidenceCard.v.confidence === '中', 'conf-low': evidenceCard.v.confidence === '低' }"
          >{{ evidenceCard.v.confidence }}（{{ evidenceCard.v.score }}）</span>
        </div>
        <div v-else class="ev-row">
          <span class="ev-k">置信度</span><span class="ev-v">未核验</span>
        </div>
        <div v-if="evidenceCard.v && evidenceCard.v.snippet" class="ev-snippet">“{{ evidenceCard.v.snippet }}”</div>
        <button class="ev-pdf-btn" @click="evidenceViewPdf">查看 PDF 原文 →</button>
      </div>
    </div>

    <!-- ⑫ 论文笔记编辑弹框 -->
    <div v-if="noteEdit.show" class="ev-mask" @click.self="noteEdit.show = false">
      <div class="note-modal" @click.stop>
        <div class="note-head">
          <span>📝 {{ noteEdit.title }}</span>
          <span class="ev-close" @click="noteEdit.show = false">✕</span>
        </div>
        <textarea
          v-model="noteEdit.content"
          class="note-textarea"
          placeholder="记录你对这篇文献的笔记、要点、想法…（清空并保存即删除）"
        ></textarea>
        <button class="ev-pdf-btn" :disabled="noteEdit.saving" @click="saveNote">
          {{ noteEdit.saving ? '保存中…' : '保存笔记' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { marked } from 'marked'
import hljs from 'highlight.js'
import { apiFetch, apiUrl, apiUrlWithToken } from '../api'
import 'highlight.js/styles/github-dark.css'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { Network, DataSet } from 'vis-network/standalone'

// 简单 uid 生成器:用于给每条 bot 消息一个独立 id,vis-network 容器靠它定位
let __msgUid = 0
function nextMsgId () { return `m${Date.now()}_${++__msgUid}` }

export default {
  props: ['sessionId', 'isCollapese'],
  data () {
    return {
      messages: [],
      newMessage: '',
      // ⑫ 收藏:已收藏 paper_id 集合 + 抽屉
      favIds: [],
      favList: [],
      showFavDrawer: false,
      // 玻尔-A:回答模式
      chatMode: 'qa',
      chatModes: [
        { key: 'qa', label: '智能问答', tip: '默认:综合多篇文献生成回答' },
        { key: 'discovery', label: '找文献', tip: '只返回相关论文列表,不生成长文' },
        { key: 'review', label: '综述', tip: '结构化综述:背景/机制/方法/趋势' },
        { key: 'compare', label: '对比', tip: '逐篇横向对比表' },
        { key: 'trend', label: '趋势', tip: '按年份汇总研究演变脉络' }
      ],
      // 精读模式:锁定单篇(focus_paper_id 传后端,只检索这一篇)
      focusPaper: null,
      // ⑫ 论文笔记编辑弹框
      noteEdit: { show: false, paper_id: 0, title: '', content: '', saving: false },
      // 相似论文推荐(语义最近邻)
      similarCache: {},
      similarOpen: {},
      // 句子级证据链:点 [N] 弹的证据卡
      evidenceCard: { show: false, x: 0, y: 0, paper: null, v: null, claim: '', chunk: null },
      // baseURL 走相对路径（dev: vue.config.js proxy，prod: nginx 反代）
      // PDF iframe/直链用 apiUrlWithToken('/papers/X/pdf') 拼带 token 的 URL
      previewPaper: null,
      previewChunk: null,
      // PDF 预览 blob URL: 预 fetch 后存 blob,viewer.html?file= 拿 blob: URL 避开 ?token= 编码问题
      previewPdfBlobUrl: '',
      // PDF 加载错误信息: 服务器上 PDF 文件缺失时(404)给用户降级提示
      previewPdfError: '',
      isUserScrolling: false,
      localSessionId: '',
      attachments: [],
      isDictating: false,
      voiceMode: false,
      recognition: null,
      quickQuestions: [
        { icon: '⚗', main: '优化配煤方案', sub: '基于煤质指标自动推算', text: '帮我优化一个配煤方案' },
        { icon: '📊', main: '预测焦炭质量', sub: '灰分、硫分、强度预测', text: '预测这批煤的焦炭质量' },
        { icon: '📚', main: '查阅焦化文献', sub: '6000+ 篇专业知识库', text: '关于捣固焦工艺的文献有哪些？' },
        { icon: '🔧', main: '工艺问题诊断', sub: '温度场异常分析', text: '焦炉温度场异常，可能的原因有哪些？' }
      ]
    }
  },
  beforeDestroy () {
    const el = this.$refs.chatScroll
    if (el) el.removeEventListener('click', this.onChatClick)
    window.removeEventListener('keydown', this.onKeydown)
    // 销毁所有 vis-network 实例,避免内存泄漏
    if (this._litqaNets) {
      Object.values(this._litqaNets).forEach(n => { try { n.destroy() } catch (_) {} })
      this._litqaNets = {}
    }
  },
  methods: {
    // 暴露 api helper 给 template 用(:href="apiUrlWithToken(...)")
    apiUrlWithToken (url) {
      return apiUrlWithToken(url)
    },
    onChatClick (e) {
      const target = e.target
      if (!target || !target.closest) return

      // [N] 论文引用 → 弹 PDF 抽屉
      // 自动取该 paper 在 LITQA_META.chunks 里 score 最高的 chunk 做 PDF 高光
      // (LLM 只输出 [N], 不再写 [#N]; chunk 高光由前端自动选择)
      const a = target.closest('a.litqa-cite')
      if (a) {
        e.preventDefault()
        const paperId = parseInt(a.dataset.paperId, 10)
        if (!paperId) return
        const row = a.closest('.message-row')
        const messageId = row && row.dataset.messageId
        if (!messageId) return
        const message = this.messages.find(m => m.id === messageId)
        if (!message || !message.litqa) return
        const paper = (message.litqa.papers || []).find(p => p.paper_id === paperId)
        if (!paper) return
        // 句子级证据链:点 [N] 先弹结构化证据卡(结论/来源/类型/页码/置信度),卡里再「查看原文」
        const v = (message.litqaCiteVerify || {})[paper.ref_num] || null
        const claim = this._claimTextAround(a) || (v && v.sents && v.sents[0]) || ''
        const chunk = this.pickSupportingChunk(message, paperId, a)
        this.evidenceCard = {
          show: true,
          x: Math.min(e.clientX, window.innerWidth - 360),
          y: Math.min(e.clientY + 14, window.innerHeight - 300),
          paper,
          v,
          claim,
          chunk
        }
        return
      }

      // 定量字典表"📄 原文" → 用该条记录的 evidence_quote 在 PDF 里文本高亮
      // (自包含:paper_id / quote / title 全在 data-* 里,不依赖 message.litqa)
      const q = target.closest('a.quant-cite')
      if (q) {
        e.preventDefault()
        const paperId = parseInt(q.dataset.paperId, 10)
        if (!paperId) return
        const paper = { paper_id: paperId, title: q.dataset.title || '' }
        this.openPdfPreview(paper, { text: q.dataset.quote || '' })
      }
    },
    // ② 引用溯源:在该 paper 的 chunks 里挑最支撑"[N] 所在句子"的那段
    // (答案中文、chunk 英文 → 用句中的数字 + 英文术语做跨语言锚点;命中不到退回 top-1)
    citedPapers (papers) {
      // 来源列表:被引用的文献,按引用编号排序
      return (papers || [])
        .filter(p => p && p.cited !== false)
        .slice()
        .sort((a, b) => (a.ref_num || 999) - (b.ref_num || 999))
    },
    doctypeLabel (dt) {
      return { research: '实验研究', review: '综述', corrigendum: '勘误', editorial: '社论' }[dt] || '研究'
    },
    supportSents (message, p) {
      // ⑤ 该篇论文支撑的回答句(来自 citation verifier)
      const v = message.litqaCiteVerify && message.litqaCiteVerify[p.ref_num]
      return (v && v.sents && v.sents.length) ? v.sents : null
    },
    _citationKey (p, i) {
      // BibTeX key: 第一作者姓 + 年份,缺则 paperN
      const first = (p.authors || '').split(/[,;]/)[0].trim().split(/\s+/).pop() || ''
      const surname = first.replace(/[^A-Za-z一-龥]/g, '')
      return (surname ? surname.toLowerCase() : 'paper') + (p.year || (i + 1))
    },
    exportCitations (message, fmt) {
      // ⑫ 导出引用:从已引用文献生成 BibTeX/RIS(数据用 litqa.papers,无 journal/doi)
      const papers = this.citedPapers(message.litqa.papers)
      if (!papers.length) return
      let text = ''
      papers.forEach((p, i) => {
        const title = (p.title || `Paper ${p.paper_id}`).replace(/[{}]/g, '')
        const authors = p.authors || ''
        const year = p.year || ''
        if (fmt === 'bibtex') {
          text += `@article{${this._citationKey(p, i)},\n`
          text += `  title = {${title}},\n`
          if (authors) text += `  author = {${authors}},\n`
          if (year) text += `  year = {${year}},\n`
          text += '}\n\n'
        } else {
          text += 'TY  - JOUR\n'
          text += `TI  - ${title}\n`
          authors.split(/[,;]/).map(a => a.trim()).filter(Boolean).forEach(a => { text += `AU  - ${a}\n` })
          if (year) text += `PY  - ${year}\n`
          text += 'ER  - \n\n'
        }
      })
      const ext = fmt === 'bibtex' ? 'bib' : 'ris'
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `references.${ext}`
      a.click()
      URL.revokeObjectURL(url)
      this.$message && this.$message.success(`已导出 ${papers.length} 篇引用 (${ext})`)
    },
    _favUser () {
      return window.sessionStorage.getItem('username') || 'user123'
    },
    async loadFavorites () {
      // ⑫ 拉取当前用户收藏,填 favIds/favList
      try {
        const r = await apiFetch(`/favorites/?user_id=${encodeURIComponent(this._favUser())}`)
        if (!r.ok) return
        const list = await r.json()
        this.favList = list
        this.favIds = list.map(f => f.paper_id)
      } catch (e) { /* 静默:收藏不可用不影响主流程 */ }
    },
    isFavorited (pid) {
      return this.favIds.includes(pid)
    },
    async toggleFavorite (p) {
      const pid = p.paper_id
      if (this.isFavorited(pid)) {
        await this.removeFavorite(pid)
      } else {
        try {
          const r = await apiFetch('/favorites/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              user_id: this._favUser(),
              paper_id: pid,
              title: p.title || '',
              authors: p.authors || '',
              year: p.year || null
            })
          })
          if (r.ok) {
            if (!this.favIds.includes(pid)) this.favIds.push(pid)
            this.favList.unshift({ paper_id: pid, title: p.title, authors: p.authors, year: p.year })
            this.$message && this.$message.success('已收藏')
          }
        } catch (e) {
          this.$message && this.$message.error('收藏失败')
        }
      }
    },
    async removeFavorite (pid) {
      try {
        const r = await apiFetch(
          `/favorites/?user_id=${encodeURIComponent(this._favUser())}&paper_id=${pid}`,
          { method: 'DELETE' })
        if (r.ok) {
          this.favIds = this.favIds.filter(x => x !== pid)
          this.favList = this.favList.filter(f => f.paper_id !== pid)
        }
      } catch (e) { /* 忽略 */ }
    },
    openFavDrawer () {
      this.loadFavorites()
      this.showFavDrawer = true
    },
    closeEvidenceCard () {
      this.evidenceCard.show = false
    },
    evidenceViewPdf () {
      const c = this.evidenceCard
      if (c.paper) this.openPdfPreview(c.paper, c.chunk || { text: c.claim })
      this.closeEvidenceCard()
    },
    async openNote (p) {
      // ⑫ 打开笔记编辑:先拉已有内容
      this.noteEdit = { show: true, paper_id: p.paper_id, title: p.title || ('Paper ' + p.paper_id), content: '', saving: false }
      try {
        const r = await apiFetch(`/notes/?user_id=${encodeURIComponent(this._favUser())}&paper_id=${p.paper_id}`)
        if (r.ok) { const d = await r.json(); this.noteEdit.content = d.content || '' }
      } catch (e) { /* 静默 */ }
    },
    async saveNote () {
      this.noteEdit.saving = true
      try {
        const r = await apiFetch('/notes/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_id: this._favUser(),
            paper_id: this.noteEdit.paper_id,
            title: this.noteEdit.title,
            content: this.noteEdit.content
          })
        })
        if (r.ok) {
          this.$message && this.$message.success('笔记已保存')
          this.noteEdit.show = false
        }
      } catch (e) {
        this.$message && this.$message.error('保存失败')
      } finally {
        this.noteEdit.saving = false
      }
    },
    startFocusRead (p) {
      // 精读模式:锁定这一篇,之后的问题只检索它
      this.focusPaper = { paper_id: p.paper_id, title: p.title || ('Paper ' + p.paper_id) }
      this.$message && this.$message.success('已进入精读:' + this.focusPaper.title.slice(0, 30))
    },
    exitFocusRead () {
      this.focusPaper = null
    },
    async toggleSimilar (pid) {
      // 相似论文:展开时按需拉取语义最近邻
      this.$set(this.similarOpen, pid, !this.similarOpen[pid])
      if (this.similarOpen[pid] && this.similarCache[pid] === undefined) {
        try {
          const r = await apiFetch(`/papers/${pid}/similar?k=6`)
          const data = r.ok ? await r.json() : { similar: [] }
          this.$set(this.similarCache, pid, data.similar || [])
        } catch (e) {
          this.$set(this.similarCache, pid, [])
        }
      }
    },
    activeConstraints (message) {
      // ⑩ 多轮约束:把生效的过滤条件转成中文标签
      const c = message.litqa && message.litqa.constraints
      if (!c) return ''
      const parts = []
      if (c.year_after) parts.push(`${c.year_after} 年后`)
      if (c.exclude_doctypes && c.exclude_doctypes.includes('review')) parts.push('排除综述')
      return parts.join(' · ')
    },
    pickSupportingChunk (message, paperId, anchorEl) {
      const chunks = (message.litqa.chunks || []).filter(c => c.paper_id === paperId)
      if (chunks.length <= 1) return chunks[0] || null
      const tokens = this._anchorTokens(this._claimTextAround(anchorEl))
      if (!tokens.length) return chunks[0] // 无数字/术语可锚 → 退回 top-1(已按 score 降序)
      let best = chunks[0]
      let bestHits = -1
      for (const c of chunks) {
        const text = (c.text || '').toLowerCase()
        let hits = 0
        for (const t of tokens) if (text.includes(t)) hits++
        if (hits > bestHits) { bestHits = hits; best = c }
      }
      return bestHits > 0 ? best : chunks[0]
    },
    // 取锚点 [N] 前面那句话(回溯前驱文本节点到句末标点)
    _claimTextAround (anchorEl) {
      let text = ''
      let node = anchorEl.previousSibling
      let guard = 0
      while (node && text.length < 220 && guard < 40) {
        const t = node.textContent || ''
        if (/[。！？!?；;\n]/.test(t)) { text = t.split(/[。！？!?；;\n]/).pop() + text; break }
        text = t + text
        node = node.previousSibling
        guard++
      }
      return text
    },
    // 从中文 claim 抽跨语言锚点:数字(≥2 位)+ 英文/缩写术语(CSR/CRI/MPa…)
    _anchorTokens (claim) {
      const nums = claim.match(/\d+(?:\.\d+)?/g) || []
      const latin = (claim.match(/[A-Za-z][A-Za-z0-9-]{1,}/g) || []).map(s => s.toLowerCase())
      return Array.from(new Set([...nums, ...latin])).filter(t => t.length >= 2)
    },
    async openPdfPreview (paper, chunk = null) {
      this.previewPaper = paper
      this.previewChunk = chunk
      this.previewPdfError = ''
      // 预 fetch PDF 拿 blob URL,viewer 拿 blob: 协议 URL 不会被 ?token= 编码问题影响
      try {
        if (this.previewPdfBlobUrl) {
          URL.revokeObjectURL(this.previewPdfBlobUrl)
          this.previewPdfBlobUrl = ''
        }
        const resp = await fetch(apiUrlWithToken('/papers/' + paper.paper_id + '/pdf'))
        if (!resp.ok) {
          this.previewPdfError = resp.status === 404
            ? 'PDF 原文未同步到服务器(可参考下方引用片段与论文元数据)'
            : `PDF 加载失败(HTTP ${resp.status})`
          throw new Error('PDF fetch failed: ' + resp.status)
        }
        const blob = await resp.blob()
        this.previewPdfBlobUrl = URL.createObjectURL(blob)
      } catch (e) {
        if (!this.previewPdfError) this.previewPdfError = 'PDF 加载失败:' + e.message
        console.error('[pdf-preview] load failed:', e)
      }
    },
    // C⑨': 图片直链(鉴权豁免,不用 token)+ 点击跳 PDF 该页
    figureUrl (fig) {
      return apiUrl('/papers/' + fig.paper_id + '/figure?page=' + (fig.page || 0) +
        '&bbox=' + encodeURIComponent(fig.bbox || ''))
    },
    openFigurePdf (message, fig) {
      const paper = (message.litqa.papers || []).find(p => p.paper_id === fig.paper_id) ||
        { paper_id: fig.paper_id, title: fig.caption || '' }
      this.openPdfPreview(paper, { page: fig.page, text: fig.caption })
    },
    closePdfPreview () {
      this.previewPaper = null
      this.previewChunk = null
      this.previewPdfError = ''
      if (this.previewPdfBlobUrl) {
        URL.revokeObjectURL(this.previewPdfBlobUrl)
        this.previewPdfBlobUrl = ''
      }
    },
    pdfViewerSrc () {
      if (!this.previewPaper || !this.previewPdfBlobUrl) return ''
      const fileUrl = encodeURIComponent(this.previewPdfBlobUrl)
      let url = `/pdfjs/web/viewer.html?file=${fileUrl}`
      const hash = []
      // 优先用结构化 page 直接跳页(新 ingestion 才有,0-based → PDF.js 1-based)
      const pg = this.previewChunk && this.previewChunk.page
      if (pg !== undefined && pg !== null && pg >= 0) {
        hash.push('page=' + (pg + 1))
      }
      // 再叠加文本搜索做页内高亮(无 page 时它也负责滚动定位)
      if (this.previewChunk && this.previewChunk.text) {
        const snippet = this.extractSearchPhrase(this.previewChunk.text)
        if (snippet) {
          hash.push('search=' + encodeURIComponent(snippet), 'phrase=true', 'highlightAll=true')
        }
      }
      if (hash.length) url += '#' + hash.join('&')
      return url
    },
    extractSearchPhrase (text) {
      // 从 chunk 文本提取适合 PDF.js 搜索的代表短语:
      // 1) 跳 section heading
      // 2) 按句切分,跳过期刊元数据句(ISSN/DOI/URL/卷期/版权等头部信息)
      // 3) 取首个有意义的内容句的前 80-120 字
      if (!text) return ''
      let s = text.replace(/^\s+/, '')
      // 跳过常见 section heading
      s = s.replace(
        /^(Abstract|Introduction|Background|Materials\s+and\s+Methods?|Methods?|Methodology|Experimental(?:\s+Section)?|Results?(?:\s+and\s+Discussion)?|Discussion|Conclusion[s]?|References?|Preamble)\b[\s\n:.\-—]*/i,
        ''
      )
      // 清理换行/多空格
      s = s.replace(/\s+/g, ' ').trim()

      // 跳过期刊页眉/元数据句:含 ISSN/DOI/版权/URL/卷期/收稿等关键词的句子
      const metaRe = /\b(?:ISSN|DOI|doi:|©|Volume\b|Vol\.|Issue\b|Received\b|Accepted\b|Available\s+online|www\.|https?:\/\/|p\.\s*\d|pp\.\s*\d|All rights reserved)\b/i
      // 按 [. ! ?] + 空格切句
      const sentences = s.split(/(?<=[.!?])\s+/)
      // 保留:长度 ≥ 40(过滤短碎句)且不含 metadata 关键词
      const contentSentences = sentences.filter(
        sent => sent.length >= 40 && !metaRe.test(sent)
      )

      const phrase = contentSentences.join(' ').slice(0, 120).trim()
      if (phrase.length >= 50) return phrase

      // Fallback: 整段是 metadata(标题/作者/期刊头)时,用清理后 text 前 80 字保底,
      // 至少让 PDF.js 跳到论文头部 + 高亮标题,比完全无高光更直观。
      // (deep_summary [#N] 编号跟实际 chunk 偶尔不对齐时的兜底)
      return s.slice(0, 80).trim()
    },
    async mountLitqaGraph (message) {
      if (!message || !message.litqa) return
      if (!this._litqaNets) this._litqaNets = {}
      if (this._litqaNets[message.id]) return // 已经 mount 过这条消息的图

      // 等 DOM 渲染好
      await this.$nextTick()
      const container = document.getElementById('litqa-graph-' + message.id)
      if (!container) return

      // ── 客户端拼"检索链路"图(不再调 /paper_graph 那种 Neo4j 论文内容图)──
      // 4 层节点:Query(中心) → EnglishQuery / Keyword(中间) → Paper(外层)
      // 边语义:
      //   Query → EnglishQuery:翻译为
      //   Query → Keyword:含关键词
      //   EnglishQuery → Paper:per-query 召回(label=score)
      //   Keyword → Paper:paper.title 含该 keyword(虚线辅助边)
      const litqa = message.litqa
      const papers = litqa.papers || []
      if (papers.length === 0) return
      const question = litqa.question || '本次查询'
      const englishQueries = litqa.english_queries || []
      const keyConcepts = litqa.key_concepts || []
      const queryRecalls = litqa.query_recalls || []

      const truncate = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : (s || ''))

      // ── 节点 ──
      const nodeList = []
      nodeList.push({
        id: 'Q',
        label: truncate(question, 24),
        group: 'Query',
        title: question
      })
      englishQueries.forEach((q, i) => {
        const words = q.split(/\s+/).slice(0, 6).join(' ')
        nodeList.push({
          id: `EQ${i}`,
          label: truncate(words, 36),
          group: 'EnglishQuery',
          title: q
        })
      })
      keyConcepts.forEach((kw, i) => {
        nodeList.push({
          id: `KW${i}`,
          label: truncate(kw, 24),
          group: 'Keyword',
          title: kw
        })
      })
      papers.forEach(p => {
        const title = p.title || `Paper ${p.paper_id}`
        const yearTag = p.year ? `\n(${p.year})` : ''
        nodeList.push({
          id: `P${p.paper_id}`,
          label: truncate(title, 36) + yearTag,
          group: 'Paper',
          title,
          paper_id: p.paper_id,
          score: p.score
        })
      })

      // ── 边 ──
      const edgeList = []
      englishQueries.forEach((q, i) => {
        edgeList.push({ from: 'Q', to: `EQ${i}`, label: '翻译为', arrows: 'to' })
      })
      keyConcepts.forEach((kw, i) => {
        edgeList.push({ from: 'Q', to: `KW${i}`, label: '含关键词', arrows: 'to' })
      })
      // EnglishQuery → Paper:per-query 召回链
      const paperIdsSet = new Set(papers.map(p => p.paper_id))
      queryRecalls.forEach((qr, qIdx) => {
        let eqIdx = englishQueries.indexOf(qr.query)
        if (eqIdx === -1) eqIdx = qIdx
        if (eqIdx < 0 || eqIdx >= englishQueries.length) return
        (qr.papers || []).forEach(pp => {
          if (!paperIdsSet.has(pp.paper_id)) return
          const s = typeof pp.score === 'number' ? pp.score : 0.5
          edgeList.push({
            from: `EQ${eqIdx}`,
            to: `P${pp.paper_id}`,
            label: s.toFixed(2),
            arrows: 'to',
            value: s
          })
        })
      })
      // Keyword → Paper:substring 匹配 paper.title
      papers.forEach(p => {
        const titleLow = (p.title || '').toLowerCase()
        if (!titleLow) return
        keyConcepts.forEach((kw, i) => {
          if (!kw) return
          if (titleLow.includes(kw.toLowerCase())) {
            edgeList.push({
              from: `KW${i}`,
              to: `P${p.paper_id}`,
              arrows: 'to',
              dashes: true,
              color: { color: '#f6a3c8', highlight: '#ed64a6' },
              width: 1
            })
          }
        })
      })

      const nodes = new DataSet(nodeList)
      const edges = new DataSet(edgeList)
      const options = {
        autoResize: true,
        height: '360px',
        nodes: {
          shape: 'dot',
          size: 20,
          borderWidth: 2,
          font: {
            size: 12,
            face: 'Microsoft YaHei, Segoe UI, sans-serif',
            color: '#1a202c',
            strokeWidth: 0
          }
        },
        edges: {
          font: {
            size: 11,
            align: 'middle',
            color: '#4a5568',
            strokeWidth: 3,
            strokeColor: '#ffffff'
          },
          smooth: { type: 'continuous' },
          arrows: { to: { enabled: true, scaleFactor: 0.5 } },
          width: 1.2,
          color: { color: '#a0aec0', highlight: '#4a90e2' }
        },
        groups: {
          Query: {
            color: { background: '#718096', border: '#2d3748' },
            shape: 'diamond',
            size: 26,
            font: { color: '#ffffff' }
          },
          EnglishQuery: {
            color: { background: '#9f7aea', border: '#6b46c1' },
            shape: 'dot',
            size: 22,
            font: { color: '#ffffff' }
          },
          Keyword: {
            color: { background: '#ed64a6', border: '#b83280' },
            shape: 'dot',
            size: 18,
            font: { color: '#ffffff' }
          },
          Paper: {
            color: { background: '#4299e1', border: '#2b6cb0' },
            shape: 'dot',
            size: 22,
            font: { color: '#ffffff' }
          }
        },
        physics: {
          enabled: true,
          barnesHut: {
            gravitationalConstant: -7000,
            springLength: 140,
            springConstant: 0.04,
            damping: 0.3
          },
          stabilization: { iterations: 220, fit: true }
        },
        interaction: {
          hover: true,
          tooltipDelay: 200,
          dragNodes: true,
          zoomView: true
        }
      }

      const net = new Network(container, { nodes, edges }, options)
      this._litqaNets[message.id] = net

      // 点 Paper 节点 → 弹 PDF
      net.on('click', (params) => {
        if (params.nodes.length === 0) return
        const nid = params.nodes[0]
        const node = nodes.get(nid)
        if (node && node.group === 'Paper' && node.paper_id) {
          const paper = papers.find(p => p.paper_id === node.paper_id)
          if (paper) this.openPdfPreview(paper)
        }
      })
    },
    onKeydown (e) {
      if (e.key === 'Escape' && this.previewPaper) {
        this.closePdfPreview()
      }
    },
    renderMarkdown (text, message) {
      const detailsPlaceholders = []
      // 先保护整段 progress 块(避免内部 < > 被 marked 前的转义吞掉)。
      // 后端 _progress_html 固定以 </div>\n\n 收尾,non-greedy 配 \n\n 锚点能稳定匹配
      // 整个最外层 pipeline-progress div(中间嵌套的 </div> 不会被 \n\n 命中)
      let preprocessed = text.replace(/<div class="pipeline-progress">[\s\S]*?<\/div>\n\n/g, (match) => {
        const idx = detailsPlaceholders.length
        detailsPlaceholders.push(match)
        return `__DETAILS_PH_${idx}__`
      })
      preprocessed = preprocessed.replace(/<\/?(?:details|summary)[^>]*>/gi, (match) => {
        const idx = detailsPlaceholders.length
        detailsPlaceholders.push(match)
        return `__DETAILS_PH_${idx}__`
      })
      // 保护定量字典 HTML 表整块(含 a.quant-cite data-* 溯源链接),
      // 否则下面的 < > 转义会把表打成字面文本。表内无嵌套 table,non-greedy 安全。
      preprocessed = preprocessed.replace(/<table class="quant-table">[\s\S]*?<\/table>/gi, (match) => {
        const idx = detailsPlaceholders.length
        detailsPlaceholders.push(match)
        return `__DETAILS_PH_${idx}__`
      })

      preprocessed = preprocessed
        .replace(/\s*<br\s*\/?>\s*/gi, '\n\n')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')

      preprocessed = preprocessed.replace(/__DETAILS_PH_(\d+)__/g, (_, idx) => {
        return detailsPlaceholders[parseInt(idx)]
      })

      preprocessed = preprocessed
        .replace(/\$\$(.*?)\$\$/gs, (_, equation) => {
          return katex.renderToString(equation.trim(), {
            throwOnError: false,
            displayMode: true
          })
        })
        // 行内公式:用 [^\$\n]+? 允许公式内含空格(原 \S+? 不匹配 `$a, b, c$` 这种)
        // (^|[^\d]) 前置非数字,(?!\d) 后置非数字 — 避免误吃 `$100` 这种货币
        .replace(/(^|[^\d])\$([^$\n]+?)\$(?!\d)/g, (_, before, equation) => {
          return before + katex.renderToString(equation.trim(), {
            throwOnError: false,
            displayMode: false
          })
        })

      let html = marked(preprocessed, {
        breaks: true,
        gfm: true,
        highlight: function (code, lang) {
          const language = hljs.getLanguage(lang) ? lang : 'plaintext'
          return hljs.highlight(code, { language }).value
        }
      })

      // 文献引用 [n] → 可点击锚点(只在 litqa 消息上做),hover 时显示原句前段
      if (message && message.litqa && Array.isArray(message.litqa.chunks)) {
        // ref → paper_id 映射 + ref → hover preview(取 score 最高的 chunk text 前 200 字)
        // chunks 已按 score 降序,第一次遇到 ref 时设的就是最高分,后续跳过
        const refToPid = {}
        const refToPreview = {}
        for (const c of message.litqa.chunks) {
          if (!(c.ref in refToPid)) {
            refToPid[c.ref] = c.paper_id
            const txt = (c.text || '').trim().replace(/\s+/g, ' ')
            if (txt) {
              refToPreview[c.ref] = txt.slice(0, 200)
                .replace(/"/g, '&quot;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;') + (txt.length > 200 ? '…' : '')
            }
          }
        }
        // 兜底删除 [#M] 段落级标记(LLM 不应输出,后端 stream 已清洗,前端再保一道)
        html = html.replace(/\s*\[#\d+\]/g, '')
        // 字典引用映射(续 RAG 编号的 [6][7][8]…),点击用 quote 在 PDF 文本高亮
        const dictRefs = message.litqaDictRefs || {}
        const verify = message.litqaCiteVerify || {}
        // [N] 引用 → 链接:字典 ref 走 quant-cite(quote 高亮),RAG ref 走 litqa-cite(top chunk)
        // citation verifier 判"弱支持"的加 cite-weak(置灰 + ⚠ 提示,不删)
        html = html.replace(/\[(\d+)\](?!\()/g, (m, n) => {
          const ref = parseInt(n)
          const weak = verify[ref] && verify[ref].ok === false
          const wCls = weak ? ' cite-weak' : ''
          const wAttr = weak ? ' title="⚠ 该引用证据支持较弱,建议点开核对原文"' : ''
          const dr = dictRefs[ref]
          if (dr && dr.paper_id) {
            const q = (dr.quote || '').replace(/"/g, '&quot;')
            const t = (dr.title || '').replace(/"/g, '&quot;')
            return `<a class="quant-cite${wCls}" data-paper-id="${dr.paper_id}" data-quote="${q}" data-title="${t}"${wAttr} href="#">[${ref}]</a>`
          }
          const pid = refToPid[ref] || ''
          if (!pid) return m
          const preview = refToPreview[ref] || ''
          const previewAttr = preview ? ` data-preview="${preview}"` : ''
          return `<a class="litqa-cite${wCls}" data-ref="${ref}" data-paper-id="${pid}"${previewAttr}${wAttr} href="#">[${ref}]</a>`
        })
      }

      // ⑦ 实体高亮:焦化领域专业术语加底色(只高亮文本节点,不碰标签/属性)
      html = this._highlightEntities(html)
      return html
    },
    _highlightEntities (html) {
      // 术语表(英文缩写 + 中文实体);按长度降序避免子串误伤
      const terms = [
        'HRTEM', 'WAXS', 'SAXS', 'FTIR', 'XRD', 'Raman', 'XPS', 'NMR', 'TG-MS', 'LDI-TOF-MS',
        'CSR', 'CRI', 'OTI', '镜质组', '惰质组', '壳质组', '胶质层', '流动度',
        '乱层结构', '芳香层片', '微晶', '挥发分', '半焦', '炼焦煤', '热解', '碳化', '石墨化',
        '焦炭反应性', '反应后强度', '焦炭光学组织'
      ].sort((a, b) => b.length - a.length)
      const re = new RegExp('(' + terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g')
      // 按标签切分,只在标签外的文本片段上替换
      return html.split(/(<[^>]*>)/).map(seg => {
        if (seg.startsWith('<')) return seg
        return seg.replace(re, '<span class="entity-hl">$1</span>')
      }).join('')
    },
    scrollToBottom () {
      this.$nextTick(() => {
        const el = this.$refs.chatScroll
        if (el) el.scrollTop = el.scrollHeight
      })
    },
    formatElapsed (ms) {
      if (!ms || ms < 100) return '0.0s'
      if (ms < 60000) return (ms / 1000).toFixed(1) + 's'
      const s = Math.floor(ms / 1000)
      const min = Math.floor(s / 60)
      const sec = (s % 60).toString().padStart(2, '0')
      return `${min}m${sec}s`
    },
    openFilePicker () {
      if (this.$refs.filePicker) this.$refs.filePicker.click()
    },
    onFilesSelected (e) {
      const files = Array.from(e.target.files || [])
      if (!files.length) return
      this.attachments.push(...files)
      const names = files.map(f => f.name).join('、')
      this.$message && this.$message.success(`已选择 ${files.length} 个文件：${names}`)
      e.target.value = ''
    },
    toggleDictation () {
      if (this.isDictating) {
        if (this.recognition) this.recognition.stop()
        this.isDictating = false
        return
      }
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition
      if (!SR) {
        this.$message && this.$message.warning('当前浏览器不支持语音输入')
        return
      }
      this.recognition = new SR()
      this.recognition.lang = 'zh-CN'
      this.recognition.continuous = true
      this.recognition.interimResults = true

      this.recognition.onstart = () => { this.isDictating = true }
      this.recognition.onresult = (event) => {
        let txt = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          txt += event.results[i][0].transcript
        }
        if (txt) this.newMessage = (this.newMessage + ' ' + txt).trim()
      }
      this.recognition.onerror = () => { this.isDictating = false }
      this.recognition.onend = () => { this.isDictating = false }
      this.recognition.start()
    },
    toggleVoiceMode () {
      this.voiceMode = !this.voiceMode
      if (!this.voiceMode) window.speechSynthesis.cancel()
    },
    speak (text) {
      if (!this.voiceMode || !window.speechSynthesis) return
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'zh-CN'
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(u)
    },
    sendQuickQuestion (text) {
      this.newMessage = text
      this.sendMessage()
    },
    async sendMessage () {
      if (!this.newMessage.trim()) return
      const userText = this.newMessage
      this.newMessage = ''
      this.messages.push({ text: userText, type: 'user', id: nextMsgId() })

      const botMessage = {
        text: '',
        type: 'bot',
        id: nextMsgId(),
        streaming: true,
        startTime: Date.now(),
        elapsedMs: 0,
        tokens: 0
      }
      this.messages.push(botMessage)
      // 实时更新 elapsedMs(每 200ms 刷一次)
      const timerId = setInterval(() => {
        if (!botMessage.streaming) {
          clearInterval(timerId)
          return
        }
        botMessage.elapsedMs = Date.now() - botMessage.startTime
      }, 200)
      this.scrollToBottom()

      let sessionToUse = this.sessionId
      if (this.sessionId === 'new') {
        try {
          const response = await apiFetch('/new_session/?user_id=user123', { method: 'POST' })
          const data = await response.json()
          this.localSessionId = data.session_id
          this.$emit('update-sessions')
          sessionToUse = this.localSessionId
        } catch (error) {
          console.error('创建新会话失败:', error)
          return
        }
      }

      try {
        const focusQ = this.focusPaper ? `&focus_paper_id=${this.focusPaper.paper_id}` : ''
        const response = await apiFetch(
          `/chat/?session_id=${sessionToUse}&user_message=${encodeURIComponent(userText)}&mode=${this.chatMode}${focusQ}`,
          { method: 'POST' }
        )
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let botReply = ''
        let progressBlock = ''
        const LITQA_META_RE = /<!--LITQA_META:([\s\S]*?)-->\s*/
        const LITQA_DICT_RE = /<!--LITQA_DICT_REFS:([\s\S]*?)-->\s*/
        const LITQA_VERIFY_RE = /<!--LITQA_CITE_VERIFY:([\s\S]*?)-->\s*/

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          const chunk = decoder.decode(value, { stream: true })

          if (chunk.includes('<details open>') && chunk.includes('推理链路')) {
            progressBlock = chunk
            botMessage.text = progressBlock
          } else {
            botReply += chunk
            // 截获结构化文献元数据(literature_qa 路径才有)
            if (!botMessage.litqa) {
              const m = botReply.match(LITQA_META_RE)
              if (m) {
                try {
                  this.$set(botMessage, 'litqa', JSON.parse(m[1]))
                  // 文献元数据就绪 → DOM 渲染后挂载知识图谱
                  this.$nextTick(() => this.mountLitqaGraph(botMessage))
                } catch (e) {
                  console.warn('parse LITQA_META failed', e)
                }
                botReply = botReply.replace(LITQA_META_RE, '')
              }
            }
            // 截获字典引用映射(续 RAG 编号的 [N] → quant-cite 溯源)
            if (!botMessage.litqaDictRefs) {
              const md = botReply.match(LITQA_DICT_RE)
              if (md) {
                try {
                  this.$set(botMessage, 'litqaDictRefs', JSON.parse(md[1]))
                } catch (e) {
                  console.warn('parse LITQA_DICT_REFS failed', e)
                }
                botReply = botReply.replace(LITQA_DICT_RE, '')
              }
            }
            // 截获引用校验结果(弱支持的 [N] 渲染时标 ⚠)
            if (!botMessage.litqaCiteVerify) {
              const mv = botReply.match(LITQA_VERIFY_RE)
              if (mv) {
                try {
                  this.$set(botMessage, 'litqaCiteVerify', JSON.parse(mv[1]))
                } catch (e) {
                  console.warn('parse LITQA_CITE_VERIFY failed', e)
                }
                botReply = botReply.replace(LITQA_VERIFY_RE, '')
              }
            }
            botMessage.text = progressBlock + botReply
          }
          // token 粗估:中文 1 char ≈ 1.5 token,英文 1 char ≈ 0.25 token,取平均
          botMessage.tokens = Math.round(botReply.length * 1.2)
          botMessage.elapsedMs = Date.now() - botMessage.startTime
          this.$nextTick(() => this.scrollToBottom())
        }

        // 流式响应结束:停 spinner(把所有 pending progress-step 改成 done)+ 关闭计时
        botMessage.streaming = false
        botMessage.elapsedMs = Date.now() - botMessage.startTime
        botMessage.text = botMessage.text.replace(
          /<div class="progress-step pending">([^<]*)<\/div>/g,
          '<div class="progress-step done">✅ $1</div>'
        )

        if (this.voiceMode && botReply.trim()) this.speak(botReply)
      } catch (error) {
        console.error('发送消息失败:', error)
        this.streamReply(botMessage, '对不起，网络异常，请稍后再试。')
      }

      this.attachments = []
      this.scrollToBottom()
    },
    parseLitqaMarkers (msg, rawText) {
      // 从存档文本里解析并剥离 LITQA_* 标记(流式生成时实时做的那套,历史加载也要做一遍,
      // 否则标记泄漏成正文、[N] 引用无 litqa 映射点不动)。
      let text = rawText || ''
      const META = /<!--LITQA_META:([\s\S]*?)-->\s*/
      const DICT = /<!--LITQA_DICT_REFS:([\s\S]*?)-->\s*/
      const VERIFY = /<!--LITQA_CITE_VERIFY:([\s\S]*?)-->\s*/
      const mm = text.match(META)
      if (mm) {
        try { this.$set(msg, 'litqa', JSON.parse(mm[1])) } catch (e) { /* 损坏的元数据忽略 */ }
        text = text.replace(META, '')
      }
      const md = text.match(DICT)
      if (md) {
        try { this.$set(msg, 'litqaDictRefs', JSON.parse(md[1])) } catch (e) { /* 忽略 */ }
        text = text.replace(DICT, '')
      }
      const mv = text.match(VERIFY)
      if (mv) {
        try { this.$set(msg, 'litqaCiteVerify', JSON.parse(mv[1])) } catch (e) { /* 忽略 */ }
        text = text.replace(VERIFY, '')
      }
      // 兜底:删掉任何残留的 LITQA_* 注释,绝不让它泄漏成正文
      text = text.replace(/<!--LITQA_[\s\S]*?-->\s*/g, '')
      // 旧格式 thinking 块(markdown 引用 > 推理过程 … ---);新版已改 <details>,历史里的旧块剥掉
      text = text.replace(/(?:^|\n)>[^\n]*推理过程[\s\S]*?\n---\n+/g, '\n')
      // 历史对话已完成:把还在转圈的 pending 步骤转成 done(✅),保留对勾、只停转圈
      text = text.replace(
        /<div class="progress-step pending">([^<]*)<\/div>/g,
        '<div class="progress-step done">✅ $1</div>'
      )
      return text
    },
    async loadChatHistory () {
      if (!this.sessionId) return
      try {
        const response = await apiFetch(`/messages/?session_id=${this.sessionId}`)
        const data = await response.json()
        this.messages = data
          .filter(msg => msg.type !== 'user' || msg.text.trim() !== '')
          .map(msg => {
            const m = { text: msg.text, type: msg.type, id: nextMsgId() }
            if (msg.type === 'bot') m.text = this.parseLitqaMarkers(m, msg.text)
            return m
          })
        if (this.sessionId === 'new') {
          this.streamWelcomeMessage()
        }
        // 历史里有文献元数据的消息,DOM 渲染后补挂知识图谱
        this.$nextTick(() => {
          this.messages.forEach(m => { if (m.litqa) this.mountLitqaGraph(m) })
        })
        this.scrollToBottom()
      } catch (error) {
        console.error('加载聊天记录失败:', error)
      }
    },
    streamReply (botMessage, fullText) {
      let i = 0
      const interval = setInterval(() => {
        if (i < fullText.length) {
          botMessage.text += fullText[i]
          i++
        } else {
          clearInterval(interval)
        }
      }, 50)
    },
    streamWelcomeMessage () {
      const botMessage = { text: '', type: 'bot' }
      this.messages.push(botMessage)
      this.streamReply(botMessage, '您好！我是高校智慧化工软件平台 DeepResearch，有什么可以帮助你的？')
    }
  },
  watch: {
    sessionId () {
      this.loadChatHistory()
    },
    messages () {
      this.scrollToBottom()
    }
  },
  mounted () {
    // ⑫ 预加载收藏,让论文卡星标即时反映状态
    this.loadFavorites()
    // 文献引用 [n] 点击 → 高亮对应文献卡片(全局事件委托)
    this.$nextTick(() => {
      const el = this.$refs.chatScroll
      if (el) el.addEventListener('click', this.onChatClick)
    })
    // ESC 关闭 PDF 预览
    window.addEventListener('keydown', this.onKeydown)
    if (this.sessionId === 'new') {
      const botMessage = { text: '', type: 'bot', id: nextMsgId() }
      this.messages.push(botMessage)
      this.streamReply(botMessage, '您好！我是高校智慧化工软件平台 DeepResearch，有什么可以帮助你的？')
    } else {
      this.loadChatHistory()
    }
  }
}
</script>

<style scoped>
/* ─── Pipeline 进度条:用旋转 spinner 代替百分比/bar ─── */
/* 后端 _progress_html 仍然发 .progress-bar-wrap / .progress-pct 等元素,
   这里全部隐藏,只保留 .progress-step 文本。pending 状态用 CSS spinner
   替代静态 ⏳ emoji(后端 pending 不发 emoji,done 仍发 ✅)。 */
::v-deep .pipeline-progress {
  margin: 4px 0;
  padding: 6px 10px;
  background: #fafbfc;
  border-left: 3px solid #c7d3e0;
  border-radius: 4px;
  font-size: 13px;
  color: #5a6878;
}
::v-deep .pipeline-progress .progress-bar-wrap,
::v-deep .pipeline-progress .progress-bar-fill,
::v-deep .pipeline-progress .progress-pct,
::v-deep .pipeline-progress .progress-pct-done {
  display: none !important;
}
::v-deep .pipeline-progress .progress-step {
  display: flex;
  align-items: center;
  line-height: 1.6;
  padding: 1px 0;
}
::v-deep .pipeline-progress .progress-step.pending {
  color: #4a90e2;
}
::v-deep .pipeline-progress .progress-step.pending::before {
  content: '';
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-right: 8px;
  border: 2px solid #d0d7e2;
  border-top-color: #4a90e2;
  border-radius: 50%;
  animation: dc-spinner-rotate 0.8s linear infinite;
  flex-shrink: 0;
}
::v-deep .pipeline-progress .progress-step.done {
  color: #38a169;
}
@keyframes dc-spinner-rotate {
  to { transform: rotate(360deg); }
}

/* 生成过程的实时统计:时间 + token 估算 */
.gen-stats {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  margin-bottom: 6px;
  background: #eef4ff;
  border-radius: 12px;
  font-size: 12px;
  color: #4a5568;
  font-family: "JetBrains Mono", "SF Mono", Consolas, monospace;
  letter-spacing: 0.2px;
}
.gen-stats-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4a90e2;
  animation: dc-stats-pulse 1.2s ease-in-out infinite;
}
.gen-time {
  font-weight: 600;
  color: #2c5282;
}
.gen-sep {
  color: #a0aec0;
}
.gen-tokens {
  color: #5a6878;
}
@keyframes dc-stats-pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}

/* ─── 文献检索命中清单 (literature_qa) ─── */
/* emoji 字体 fallback: 让 📚📄✓⏳✅ 等正常显示而不是豆腐 */
.litqa-panel,
::v-deep .message-bubble {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
               "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji",
               sans-serif;
}
.litqa-panel {
  margin-top: 14px;
  padding: 12px 14px;
  background: #f6f9fc;
  border: 1px solid #e1ecf4;
  border-left: 3px solid #4a90e2;
  border-radius: 8px;
  font-size: 12.5px;
}
.litqa-panel-title {
  font-weight: 600;
  color: #2c5282;
  margin-bottom: 10px;
  font-size: 13px;
}
.litqa-icon {
  margin-right: 4px;
}
.litqa-hint {
  font-weight: 400;
  color: #718096;
  font-size: 12px;
  margin-left: 6px;
}
/* vis-network 知识图谱容器 */
.litqa-graph {
  width: 100%;
  height: 340px;
  background: #fdfdfe;
  border: 1px solid #e5edf5;
  border-radius: 6px;
  position: relative;
  overflow: hidden;
}
/* C⑨': 相关图表 */
.litqa-figures {
  margin-top: 12px;
}
.litqa-figures-title {
  font-weight: 600;
  color: #2c5282;
  font-size: 12.5px;
  margin-bottom: 8px;
}
.litqa-figures-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.litqa-fig {
  margin: 0;
  border: 1px solid #e1ecf4;
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}
.litqa-fig:hover {
  box-shadow: 0 4px 14px rgba(74, 144, 226, 0.25);
  transform: translateY(-2px);
}
.litqa-fig img {
  width: 100%;
  height: 130px;
  object-fit: contain;
  background: #fafcff;
  display: block;
}
.litqa-fig figcaption {
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.4;
  color: #4a5568;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.litqa-papers {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}
.litqa-paper {
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #e5edf5;
  border-radius: 6px;
  transition: border-color 0.18s, box-shadow 0.18s, background 0.4s;
  position: relative;
  cursor: pointer;
}
.litqa-paper-ref {
  flex-shrink: 0;
  font-weight: 700;
  color: #4a90e2;
  font-size: 12px;
}
.litqa-doctype {
  flex-shrink: 0;
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  line-height: 1.5;
  white-space: nowrap;
}
.litqa-doctype.dt-research {
  background: #e7f3ea;
  color: #2e7d44;
}
.litqa-doctype.dt-review {
  background: #eef0fb;
  color: #4a55c7;
}
.litqa-doctype.dt-corrigendum,
.litqa-doctype.dt-editorial {
  background: #fdecec;
  color: #c0392b;
}
.litqa-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 8px;
}
.litqa-toolbar-label {
  font-size: 12px;
  color: #8a96a6;
  margin-right: auto;
}
.litqa-export-btn {
  font-size: 11.5px;
  padding: 3px 10px;
  border: 1px solid #b6cce4;
  border-radius: 5px;
  background: #f0f7ff;
  color: #2f6fb3;
  cursor: pointer;
  transition: background 0.15s;
}
.litqa-export-btn:hover {
  background: #e0eefb;
}
.litqa-fav {
  flex-shrink: 0;
  cursor: pointer;
  font-size: 15px;
  color: #c2cdda;
  line-height: 1;
  transition: color 0.15s, transform 0.15s;
}
.litqa-fav:hover {
  transform: scale(1.2);
}
.litqa-fav.on {
  color: #f5b301;
}
/* ⑫ 收藏抽屉 */
.fav-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 3000;
  display: flex;
  justify-content: flex-end;
}
.fav-drawer {
  width: 380px;
  max-width: 86vw;
  height: 100%;
  background: #fff;
  box-shadow: -2px 0 16px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
}
.fav-drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  font-weight: 600;
  color: #1a3556;
  border-bottom: 1px solid #eef2f7;
}
.fav-close {
  cursor: pointer;
  color: #8a96a6;
  font-size: 16px;
}
.fav-empty {
  padding: 30px 18px;
  color: #8a96a6;
  font-size: 13px;
  text-align: center;
}
.fav-list {
  overflow-y: auto;
  padding: 8px 12px;
}
.fav-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid #f2f5f9;
}
.fav-item-main {
  flex: 1;
  cursor: pointer;
}
.fav-item-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a3556;
  line-height: 1.4;
}
.fav-item-main:hover .fav-item-title {
  color: #2f6fb3;
}
.fav-item-meta {
  font-size: 11.5px;
  color: #8a96a6;
  margin-top: 3px;
}
.fav-item-del {
  cursor: pointer;
  color: #c2cdda;
  font-size: 13px;
  flex-shrink: 0;
}
.fav-item-del:hover {
  color: #e05656;
}
/* 句子级证据链卡片 */
.ev-mask {
  position: fixed;
  inset: 0;
  z-index: 3200;
}
.ev-card {
  position: fixed;
  width: 340px;
  max-width: 88vw;
  background: #fff;
  border: 1px solid #dbe5f0;
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(20, 50, 90, 0.22);
  padding: 14px 16px 16px;
  font-size: 13px;
  color: #2a3a4d;
}
.ev-close {
  position: absolute;
  top: 8px;
  right: 10px;
  cursor: pointer;
  color: #9aa7b4;
  font-size: 14px;
}
.ev-claim {
  font-weight: 600;
  color: #16243a;
  line-height: 1.45;
  margin: 2px 18px 10px 0;
}
.ev-row {
  display: flex;
  gap: 8px;
  margin: 5px 0;
  line-height: 1.4;
}
.ev-k {
  flex-shrink: 0;
  width: 52px;
  color: #8a96a6;
  font-size: 12px;
}
.ev-v {
  flex: 1;
  color: #3a4d63;
}
.ev-conf {
  font-weight: 700;
}
.ev-conf.conf-high { color: #2e7d44; }
.ev-conf.conf-mid { color: #c77f12; }
.ev-conf.conf-low { color: #c0392b; }
.ev-snippet {
  margin: 8px 0 4px;
  padding: 7px 10px;
  background: #f4f8fc;
  border-left: 2px solid #b6d2ee;
  color: #44597a;
  font-size: 12px;
  line-height: 1.5;
  max-height: 96px;
  overflow-y: auto;
}
.ev-pdf-btn {
  margin-top: 10px;
  width: 100%;
  padding: 7px 0;
  border: none;
  border-radius: 6px;
  background: #2f6fb3;
  color: #fff;
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.15s;
}
.ev-pdf-btn:hover {
  background: #245a93;
}
.note-modal {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 460px;
  max-width: 90vw;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(20, 50, 90, 0.25);
  padding: 16px;
}
.note-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: #1a3556;
  margin-bottom: 10px;
  font-size: 13.5px;
}
.note-head > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 10px;
}
.note-textarea {
  width: 100%;
  height: 180px;
  box-sizing: border-box;
  border: 1px solid #d9e2ec;
  border-radius: 6px;
  padding: 10px;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
  color: #2a3a4d;
  margin-bottom: 12px;
}
.note-textarea:focus {
  outline: none;
  border-color: #4a90e2;
}
.fav-fade-enter-active,
.fav-fade-leave-active {
  transition: opacity 0.2s;
}
.fav-fade-enter,
.fav-fade-leave-to {
  opacity: 0;
}
.litqa-constraints {
  margin: 6px 0 8px;
  padding: 5px 10px;
  background: #eef6ee;
  border: 1px solid #cfe6cf;
  border-radius: 6px;
  font-size: 12px;
  color: #3a7d44;
}
.litqa-constraints-icon {
  margin-right: 4px;
}
.litqa-support {
  margin-top: 5px;
  padding-top: 5px;
  border-top: 1px dashed #e2eaf3;
}
.litqa-similar-bar {
  margin-top: 5px;
  display: flex;
  gap: 14px;
}
::v-deep .entity-hl {
  background: rgba(20, 158, 250, 0.14);
  border-radius: 3px;
  padding: 0 2px;
  color: #7ec1ff;
}
[data-theme="light"] ::v-deep .entity-hl {
  background: #e7f1fb;
  color: #2f6fb3;
}
.focus-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 6px 12px;
  background: #fff5e6;
  border: 1px solid #f0d0a0;
  border-radius: 6px;
  font-size: 12.5px;
  color: #a05a00;
}
.focus-title {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.focus-exit {
  cursor: pointer;
  color: #c77f12;
  flex-shrink: 0;
}
.focus-exit:hover {
  color: #a05a00;
}
[data-theme="light"] .focus-bar {
  background: #fff5e6;
}
.litqa-similar-toggle {
  font-size: 11.5px;
  color: #4a90e2;
  cursor: pointer;
  user-select: none;
}
.litqa-similar-toggle:hover {
  text-decoration: underline;
}
.litqa-similar-list {
  margin-top: 4px;
  padding-left: 6px;
  border-left: 2px solid #d6e4f2;
}
.litqa-similar-empty {
  font-size: 11.5px;
  color: #9aa7b4;
  padding: 3px 0;
}
.litqa-similar-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 0;
  cursor: pointer;
}
.litqa-similar-item:hover .litqa-similar-title {
  color: #2f6fb3;
}
.litqa-similar-score {
  flex-shrink: 0;
  font-size: 10.5px;
  font-weight: 600;
  color: #3a7d44;
}
.litqa-similar-title {
  flex: 1;
  font-size: 11.5px;
  color: #41597a;
  line-height: 1.35;
}
.litqa-similar-year {
  flex-shrink: 0;
  font-size: 10.5px;
  color: #9aa7b4;
}
.litqa-support-label {
  display: block;
  font-size: 10.5px;
  color: #8a96a6;
  margin-bottom: 2px;
}
.litqa-support-sent {
  font-size: 11.5px;
  color: #41597a;
  line-height: 1.45;
  padding-left: 7px;
  border-left: 2px solid #b6d2ee;
  margin-bottom: 3px;
}
.litqa-paper:hover {
  border-color: #b6cce4;
  box-shadow: 0 1px 5px rgba(74, 144, 226, 0.12);
}
.litqa-paper.cited {
  background: #f0f7ff;
  border-color: #b6d2ee;
}
.litqa-paper.cited::before {
  content: '✓';
  position: absolute;
  top: 6px;
  right: 8px;
  color: #4a90e2;
  font-weight: 700;
  font-size: 11px;
}
.litqa-paper.litqa-flash {
  background: #fff7d6;
  border-color: #f0c75e;
  box-shadow: 0 0 0 2px rgba(240, 199, 94, 0.4);
}
.litqa-paper-head {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 4px;
}
.litqa-paper-title {
  flex: 1;
  font-weight: 600;
  color: #1a3556;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.litqa-pdf-link {
  font-size: 14px;
  text-decoration: none;
  opacity: 0.55;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.15s;
  flex-shrink: 0;
}
.litqa-pdf-link:hover {
  opacity: 1;
  transform: scale(1.15);
}
.litqa-paper-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: #6b7c93;
  font-size: 11.5px;
  margin-bottom: 3px;
}
.litqa-journal {
  font-style: italic;
  color: #4a6585;
}
.litqa-category {
  color: #8a96a6;
}
.litqa-score {
  margin-left: auto;
  color: #4a90e2;
  font-weight: 500;
}
.litqa-paper-authors {
  color: #94a3b8;
  font-size: 11px;
  font-style: italic;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 正文里的引用 [n] */
:deep(a.litqa-cite) {
  color: #4a90e2;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.85em;
  padding: 1px 3px;
  border-radius: 3px;
  background: rgba(74, 144, 226, 0.08);
  margin: 0 1px;
  cursor: pointer;
  position: relative;
}
:deep(a.litqa-cite:hover) {
  background: rgba(74, 144, 226, 0.2);
}
/* citation verifier 判弱支持:置灰 + ⚠(仍可点核对) */
:deep(a.cite-weak) {
  opacity: 0.5;
}
:deep(a.cite-weak)::after {
  content: '⚠';
  font-size: 0.78em;
  margin-left: 1px;
}
/* hover 显示原句前 200 字 tooltip — 类 NotebookLM 风格 */
:deep(a.litqa-cite[data-preview]:hover::after) {
  content: attr(data-preview);
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: #1a3556;
  color: #fff;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.5;
  width: 360px;
  max-width: 360px;
  white-space: normal;
  z-index: 1000;
  box-shadow: 0 6px 18px rgba(0,0,0,0.25);
  pointer-events: none;
  text-align: left;
}
/* tooltip 小三角 */
:deep(a.litqa-cite[data-preview]:hover::before) {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: #1a3556;
  z-index: 1000;
  pointer-events: none;
}

/* deep_summary 里的 [#N] 引用 — 跟 [n] 区分:更柔和的紫色 chip */
:deep(a.summary-cite) {
  color: #7c4dff;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.82em;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(124, 77, 255, 0.1);
  border: 1px solid rgba(124, 77, 255, 0.2);
  margin: 0 1px;
  cursor: pointer;
  transition: background 0.15s, transform 0.15s;
}
:deep(a.summary-cite:hover) {
  background: rgba(124, 77, 255, 0.22);
  transform: translateY(-1px);
}

/* ─── PDF 预览抽屉(右侧滑入) ─── */
.pdf-drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 10000;
  display: flex;
  justify-content: flex-end;
}
.pdf-drawer {
  width: 70vw;
  max-width: 1200px;
  min-width: 600px;
  height: 100vh;
  background: #1a1a1a;
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.5);
}
.pdf-drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid #2a2a2a;
  background: #222;
}
.pdf-drawer-title-wrap {
  flex: 1;
  min-width: 0;
}
.pdf-drawer-title {
  color: #e8e8e8;
  font-size: 14.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pdf-drawer-meta {
  color: #888;
  font-size: 11.5px;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pdf-drawer-newtab,
.pdf-drawer-close {
  background: transparent;
  border: 1px solid #3a3a3a;
  color: #b0b0b0;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-radius: 6px;
  font-size: 16px;
  text-decoration: none;
  transition: all 0.15s;
  flex-shrink: 0;
}
.pdf-drawer-newtab:hover,
.pdf-drawer-close:hover {
  background: #2e2e2e;
  color: #fff;
  border-color: #4a90e2;
}
.pdf-drawer-close {
  font-size: 22px;
  line-height: 1;
}
.pdf-drawer-iframe {
  flex: 1;
  width: 100%;
  background: #fff;
}
/* 点 [n] 弹 PDF 时显示的引用片段高亮框 */
.pdf-drawer-chunk {
  margin: 10px 14px;
  padding: 10px 12px;
  background: #fff8d6;
  border-left: 4px solid #f6e05e;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.55;
  max-height: 180px;
  overflow-y: auto;
}
.pdf-drawer-chunk-head {
  font-weight: 600;
  color: #744210;
  margin-bottom: 6px;
  font-size: 12px;
}
.pdf-drawer-chunk-text {
  color: #1a202c;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 滑入动画 */
.pdf-drawer-enter-active,
.pdf-drawer-leave-active {
  transition: opacity 0.22s;
}
.pdf-drawer-enter-active .pdf-drawer,
.pdf-drawer-leave-active .pdf-drawer {
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}
.pdf-drawer-enter,
.pdf-drawer-leave-to {
  opacity: 0;
}
.pdf-drawer-enter .pdf-drawer,
.pdf-drawer-leave-to .pdf-drawer {
  transform: translateX(100%);
}

/* ===== 整体布局 ===== */
.chat-wrapper {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #0f0f0f;
}

/* ===== 消息滚动区 ===== */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding-top: 56px;
}

.chat-scroll::-webkit-scrollbar {
  width: 6px;
}

.chat-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.chat-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.12);
}

.chat-content {
  max-width: 740px;
  margin: 0 auto;
  padding: 16px 24px 24px;
}

/* ===== 欢迎区域 ===== */
.welcome-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0 40px;
}

.welcome-logo {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: linear-gradient(135deg, #ff8a00, #149efa);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.welcome-logo img {
  width: 36px;
  height: 36px;
  object-fit: contain;
  filter: brightness(10);
}

.welcome-title {
  font-size: 22px;
  color: #e0e0e0;
  font-weight: 500;
  margin: 0 0 28px;
}

.quick-actions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  width: 100%;
  max-width: 520px;
}

.quick-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.14);
}

.quick-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

.quick-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.quick-main {
  font-size: 13px;
  color: #d0d0d0;
  font-weight: 500;
}

.quick-sub {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}

/* ===== 消息行 ===== */
.message-row {
  display: flex;
  gap: 14px;
  margin: 20px 0;
  align-items: flex-start;
}

.message-row.user {
  flex-direction: row-reverse;
}

/* ===== 头像 ===== */
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

.bot-avatar {
  background: linear-gradient(135deg, #ff8a00, #149efa);
  display: flex;
  align-items: center;
  justify-content: center;
}

.bot-avatar img {
  width: 20px;
  height: 20px;
  object-fit: contain;
  filter: brightness(10);
}

/* ===== 消息气泡 ===== */
.message-bubble {
  max-width: 85%;
  font-size: 15px;
  line-height: 1.7;
  word-wrap: break-word;
  text-align: left;
}

.message-row.bot .message-bubble {
  color: #d4d4d4;
  padding: 0;
}

.message-row.user .message-bubble {
  background: #1a3a5c;
  color: #e0e0e0;
  padding: 12px 18px;
  border-radius: 18px 18px 4px 18px;
  border: 1px solid rgba(20, 158, 250, 0.15);
}

/* ===== Markdown 内容样式 ===== */
.message-bubble span { word-break: break-word; }

::v-deep .message-bubble h1 { font-size: 20px; font-weight: 600; color: #f0f0f0; margin: 16px 0 8px; }
::v-deep .message-bubble h2 { font-size: 18px; font-weight: 600; color: #f0f0f0; margin: 14px 0 6px; }
::v-deep .message-bubble h3 { font-size: 16px; font-weight: 600; color: #f0f0f0; margin: 12px 0 4px; }
::v-deep .message-bubble p { margin: 8px 0; }
::v-deep .message-bubble ul,
::v-deep .message-bubble ol { padding-left: 20px; margin: 8px 0; }
::v-deep .message-bubble code {
  background: rgba(255, 255, 255, 0.07);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Fira Code', monospace;
  color: #e8ab6a;
}
::v-deep .message-bubble pre {
  background: #0a0a0a;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  padding: 14px;
  margin: 10px 0;
  overflow-x: auto;
}
::v-deep .message-bubble pre code {
  background: transparent;
  padding: 0;
  color: #d4d4d4;
}
::v-deep .message-bubble a { color: #58a6ff; }
::v-deep .message-bubble table {
  border-collapse: collapse;
  margin: 10px 0;
  width: 100%;
}
::v-deep .message-bubble th,
::v-deep .message-bubble td {
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 12px;
  text-align: left;
}
::v-deep .message-bubble th {
  background: rgba(255, 255, 255, 0.04);
  color: #e0e0e0;
}

/* ===== 推理过程折叠块 ===== */
::v-deep .message-bubble details {
  background: rgba(20, 158, 250, 0.04);
  border: 1px solid rgba(20, 158, 250, 0.12);
  border-radius: 10px;
  padding: 10px 14px;
  margin: 8px 0 12px;
}
::v-deep .message-bubble details summary {
  cursor: pointer;
  color: #7eb8f7;
  font-size: 14px;
  user-select: none;
}
::v-deep .message-bubble details summary:hover {
  color: #58a6ff;
}
::v-deep .message-bubble details[open] summary {
  margin-bottom: 8px;
  border-bottom: 1px solid rgba(20, 158, 250, 0.1);
  padding-bottom: 6px;
}
::v-deep .message-bubble details p,
::v-deep .message-bubble details li {
  font-size: 13px;
  color: #9a9a9a;
}
::v-deep .message-bubble .deep-think-body {
  font-size: 13px;
  color: #9a9a9a;
  line-height: 1.65;
}
::v-deep .message-bubble .deep-think-body ul {
  margin: 4px 0;
}

/* ===== 加载动画 ===== */
.loading-dots {
  display: flex;
  gap: 5px;
  padding: 8px 0;
}

.loading-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #444;
  animation: dots 1.4s infinite ease-in-out;
}

.loading-dots span:nth-child(1) { animation-delay: 0s; }
.loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.loading-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dots {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* ===== 玻尔-A 回答模式选择器 ===== */
.mode-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  padding-left: 2px;
}
.mode-tab {
  font-size: 12.5px;
  padding: 4px 14px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: transparent;
  color: #9aa7b4;
  cursor: pointer;
  transition: all 0.15s;
}
.mode-tab:hover {
  color: #d4d4d4;
  border-color: rgba(255, 255, 255, 0.28);
}
.mode-tab.active {
  background: rgba(20, 158, 250, 0.16);
  border-color: #2f8fe0;
  color: #7ec1ff;
  font-weight: 600;
}
[data-theme="light"] .mode-tab {
  border-color: #d3deea;
  color: #6b7c93;
}
[data-theme="light"] .mode-tab:hover {
  color: #1a2b3c;
  border-color: #b6cce4;
}
[data-theme="light"] .mode-tab.active {
  background: #e7f1fb;
  border-color: #4a90e2;
  color: #2f6fb3;
}

/* ===== 输入区域 ===== */
.input-area {
  flex-shrink: 0;
  padding: 0 24px 16px;
  max-width: 740px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  background: #1a1a1a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  padding: 8px 8px 8px 4px;
  transition: border-color 0.2s;
}

.input-wrapper:focus-within {
  border-color: rgba(20, 158, 250, 0.3);
}

/* ===== 输入框 ===== */
.input-box {
  flex: 1;
  font-size: 15px;
}

::v-deep .el-textarea__inner {
  border: none !important;
  border-radius: 0 !important;
  padding: 6px 8px;
  box-shadow: none !important;
  resize: none;
  font-family: "Microsoft YaHei", -apple-system, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  background: transparent !important;
  color: #e0e0e0;
  /* 完全隐藏滚动条(箭头 + 滑块),保留鼠标滚轮/键盘滚动功能 */
  scrollbar-width: none;
  -ms-overflow-style: none;
}
::v-deep .el-textarea__inner::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none;
}
::v-deep .el-textarea__inner::-webkit-scrollbar-button,
::v-deep .el-textarea__inner::-webkit-scrollbar-thumb,
::v-deep .el-textarea__inner::-webkit-scrollbar-track,
::v-deep .el-textarea__inner::-webkit-scrollbar-track-piece,
::v-deep .el-textarea__inner::-webkit-scrollbar-corner {
  display: none !important;
  background: transparent !important;
}

::v-deep .el-textarea__inner::placeholder {
  color: #555;
}

::v-deep .el-textarea__inner:focus {
  border: none !important;
  box-shadow: none !important;
}

/* ===== 输入框内图标按钮 ===== */
.input-icon-btn {
  width: 34px;
  height: 34px;
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

.input-icon-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #aaa;
}

.input-icon-btn.active {
  color: #149efa;
  background: rgba(20, 158, 250, 0.12);
}

/* ===== 发送按钮 ===== */
.send-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: #2a2a2a;
  color: #555;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
  transition: all 0.2s;
  flex-shrink: 0;
}

.send-btn.has-text {
  background: linear-gradient(135deg, #ff8a00, #149efa);
  color: #fff;
  cursor: pointer;
}

.send-btn.has-text:hover {
  opacity: 0.9;
  transform: scale(1.05);
}

/* ===== 底部提示 ===== */
.input-footer {
  text-align: center;
  font-size: 12px;
  color: #444;
  padding-top: 8px;
}

/* ===== 白天(light)主题覆盖:深色对话区 → 浅色(litqa面板/gen-stats 本就是浅卡,两套都保留) ===== */
[data-theme="light"] .chat-wrapper {
  background: #f5f8fc;
}
[data-theme="light"] .welcome-title {
  color: #1a202c;
}
[data-theme="light"] .message-row.bot .message-bubble {
  color: #1a202c;
}
/* 白天:正文标题/粗体/引用块改深色,否则白底白字看不见 */
[data-theme="light"] .message-bubble ::v-deep h1,
[data-theme="light"] .message-bubble ::v-deep h2,
[data-theme="light"] .message-bubble ::v-deep h3,
[data-theme="light"] .message-bubble ::v-deep strong,
[data-theme="light"] .message-bubble ::v-deep b {
  color: #16243a;
}
[data-theme="light"] .message-bubble ::v-deep blockquote {
  color: #44546a;
  border-left-color: #ccd6e2;
}
[data-theme="light"] .message-row.user .message-bubble {
  background: #d6e9ff;
  color: #143a5c;
  border-color: rgba(20, 158, 250, 0.25);
}
[data-theme="light"] .input-wrapper {
  background: #ffffff;
  border-color: #d9e2ec;
}
[data-theme="light"] .input-box {
  color: #1a202c;
}
[data-theme="light"] .input-box::placeholder {
  color: #94a3b8;
}
[data-theme="light"] .input-footer {
  color: #94a3b8;
}
</style>
