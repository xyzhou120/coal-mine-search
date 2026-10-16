<template>
  <div class="doc-list-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">文档列表</span>
          <el-button :icon="Refresh" circle @click="loadDocs" :loading="loading" />
        </div>
      </template>

      <!-- 筛选条件 -->
      <el-form :model="filters" inline class="filter-bar">
        <el-form-item label="煤矿编码">
          <el-input v-model="filters.mine_code" placeholder="输入煤矿编码" clearable style="width: 150px" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px">
            <el-option label="待处理" value="pending" />
            <el-option label="下载中" value="downloading" />
            <el-option label="处理中" value="processing" />
            <el-option label="建索引中" value="indexing" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleFilter">查询</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- 统计 -->
      <div class="stats-row">
        <el-tag v-for="(count, status) in stats" :key="status"
          :type="statusType(status)" effect="light" style="margin-right: 8px">
          {{ statusLabel(status) }}: {{ count }}
        </el-tag>
      </div>

      <el-table :data="docs" v-loading="loading" stripe size="small">
        <el-table-column prop="mine_name" label="煤矿" width="140" show-overflow-tooltip />
        <el-table-column prop="file_name" label="清单类型" width="180" show-overflow-tooltip />
        <el-table-column prop="attachment_name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="report_time" label="上报时间" width="100" />
        <el-table-column prop="frequency_label" label="频率" width="80" />
        <el-table-column prop="file_type" label="类型" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="fileTypeColor(row.file_type)">
              {{ row.file_type?.toUpperCase() || '—' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="page_count" label="页数" width="70" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error_msg" label="错误信息" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error_msg" class="error-text">{{ row.error_msg }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'failed' || row.status === 'completed'"
              link type="primary" size="small"
              @click="handleReindex(row.attachment_id)"
            >重建索引</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="loadDocs"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { importApi } from '@/api'

const docs = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const stats = ref({})
const filters = ref({ mine_code: '', status: '' })

onMounted(loadDocs)

async function loadDocs() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filters.value.mine_code) params.mine_code = filters.value.mine_code
    if (filters.value.status) params.status = filters.value.status
    const res = await importApi.getDocuments(params)
    docs.value = res.items || []
    total.value = res.total || 0
    // 加载状态统计（不加筛选条件）
    loadStats()
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const res = await importApi.getDocuments({ page: 1, page_size: 1 })
    // 从 realtime_stats 字段获取
    if (res.realtime_stats) stats.value = res.realtime_stats
  } catch {}
}

function handleFilter() { page.value = 1; loadDocs() }
function resetFilter() { filters.value = { mine_code: '', status: '' }; page.value = 1; loadDocs() }

async function handleReindex(attachmentId) {
  await importApi.reindexDocument(attachmentId)
  ElMessage.success('已触发重建索引')
  loadDocs()
}

const STATUS_MAP = {
  pending: ['info', '待处理'],
  downloading: ['', '下载中'],
  processing: ['', '处理中'],
  indexing: ['warning', '建索引'],
  completed: ['success', '已完成'],
  failed: ['danger', '失败'],
}
function statusType(s) { return STATUS_MAP[s]?.[0] ?? 'info' }
function statusLabel(s) { return STATUS_MAP[s]?.[1] ?? s }
function fileTypeColor(t) {
  return { pdf: 'danger', word: 'primary', excel: 'success' }[t] ?? 'info'
}
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; }
.filter-bar { margin-bottom: 8px; }
.stats-row { margin-bottom: 12px; }
.error-text { color: #f56c6c; font-size: 12px; }
.text-muted { color: #c0c4cc; }
.pagination { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
