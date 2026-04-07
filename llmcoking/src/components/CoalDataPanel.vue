<template>
  <div class="data-panel">
    <!-- 上方：煤仓库列表 -->
    <div class="coal-table-section">
      <div class="section-header">
        <span class="section-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          </svg>
          煤仓库列表
        </span>
        <button class="refresh-btn" @click="fetchCoalData(currentPage)" title="刷新">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
        </button>
      </div>
      <div class="table-wrapper">
        <el-table
          :data="coalData"
          size="mini"
          stripe
          border
          height="100%"
          :header-cell-style="{ background: '#E8E8ED', color: '#334155', fontSize: '12px', padding: '6px 0' }"
          :cell-style="{ fontSize: '12px', padding: '4px 0' }"
        >
          <el-table-column prop="coal_name" label="煤样名称" min-width="90" show-overflow-tooltip />
          <el-table-column prop="coal_type" label="煤种" min-width="65" show-overflow-tooltip />
          <el-table-column prop="coal_price" label="价格" min-width="55" align="right" />
          <el-table-column prop="coal_mad" label="Mad%" min-width="52" align="right" />
          <el-table-column prop="coal_ad" label="Ad%" min-width="48" align="right" />
          <el-table-column prop="coal_vdaf" label="Vdaf%" min-width="52" align="right" />
          <el-table-column prop="coal_std" label="St,d%" min-width="50" align="right" />
          <el-table-column prop="G" label="G" min-width="40" align="right" />
          <el-table-column prop="X" label="X" min-width="38" align="right" />
          <el-table-column prop="Y" label="Y" min-width="38" align="right" />
        </el-table>
      </div>
      <div class="pagination-wrapper">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page.sync="currentPage"
          @current-change="fetchCoalData"
          small
        />
      </div>
    </div>

    <!-- 下方：数字孪生视频 -->
    <div class="video-section">
      <div class="section-header">
        <span class="section-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          数字孪生
        </span>
      </div>
      <div class="video-wrapper">
        <video controls autoplay loop muted preload="metadata" class="twin-video">
          <source src="/static/数字孪生视频.mp4" type="video/mp4" />
        </video>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'CoalDataPanel',
  data () {
    return {
      coalData: [],
      total: 0,
      currentPage: 1,
      pageSize: 10,
      apiBaseUrl: 'http://127.0.0.1:8000'
    }
  },
  methods: {
    async fetchCoalData (page) {
      try {
        const res = await fetch(`${this.apiBaseUrl}/all_coals_page/?page=${page}&page_size=${this.pageSize}`)
        const json = await res.json()
        this.coalData = json.data || []
        this.total = json.total || 0
      } catch (e) {
        console.error('加载煤样数据失败:', e)
      }
    }
  },
  mounted () {
    this.fetchCoalData(1)
  }
}
</script>

<style lang="less" scoped>
.data-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #F0F0F3;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px 8px;
  flex-shrink: 0;
}

.section-title {
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  font-weight: 600;
  color: #1E293B;
  display: flex;
  align-items: center;
  gap: 6px;

  svg {
    color: #64748B;
  }
}

.refresh-btn {
  width: 28px;
  height: 28px;
  border: 1px solid #D5D5DA;
  border-radius: 6px;
  background: #E8E8ED;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    color: #1E293B;
    border-color: #C5C5CC;
  }
}

/* 煤仓表格区域 */
.coal-table-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid #D5D5DA;
}

.table-wrapper {
  flex: 1;
  min-height: 0;
  padding: 0 14px;
}

.pagination-wrapper {
  padding: 8px 14px;
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}

/* 视频区域 */
.video-section {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.video-wrapper {
  flex: 1;
  padding: 0 14px 14px;
  min-height: 0;
}

.twin-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: 8px;
  background: #000;
}
</style>
