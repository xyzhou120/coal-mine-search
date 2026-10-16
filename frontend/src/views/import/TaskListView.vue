<template>
  <div class="task-list-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">导入任务列表</span>
          <el-button :icon="Refresh" circle @click="loadTasks" :loading="loading" />
        </div>
      </template>

      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column prop="file_name" label="Excel 文件名" min-width="200" show-overflow-tooltip />
        <el-table-column label="进度" min-width="220">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="calcProgress(row)"
                :status="progressStatus(row)"
                :stroke-width="8"
              />
              <div class="progress-labels">
                <span class="label-completed">完成 {{ row.completed_count }}</span>
                <span class="label-failed" v-if="row.failed_count > 0">失败 {{ row.failed_count }}</span>
                <span class="label-total">/ 共 {{ row.total_count }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.failed_count > 0"
              link type="warning" size="small"
              @click="handleRetry(row.task_id)"
            >重试失败</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @change="loadTasks"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { importApi } from '@/api'
import dayjs from 'dayjs'

const tasks = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
let timer = null

onMounted(() => {
  loadTasks()
  // 每10秒自动刷新
  timer = setInterval(loadTasks, 10000)
})
onUnmounted(() => clearInterval(timer))

async function loadTasks() {
  loading.value = true
  try {
    const res = await importApi.getTasks(page.value, pageSize.value)
    tasks.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function handleRetry(taskId) {
  await importApi.retryTask(taskId)
  ElMessage.success('已触发重试')
  loadTasks()
}

function calcProgress(row) {
  if (!row.total_count) return 0
  return Math.round(((row.completed_count + row.failed_count + row.skipped_count) / row.total_count) * 100)
}

function progressStatus(row) {
  if (row.status === 'completed') return 'success'
  if (row.status === 'failed') return 'exception'
  if (row.failed_count > 0 && row.status === 'partial') return 'warning'
  return ''
}

const STATUS_MAP = {
  created: ['info', '已创建'],
  parsing: ['', '解析中'],
  processing: ['', '处理中'],
  completed: ['success', '已完成'],
  partial: ['warning', '部分完成'],
  failed: ['danger', '失败'],
}

function statusType(s) { return STATUS_MAP[s]?.[0] ?? 'info' }
function statusLabel(s) { return STATUS_MAP[s]?.[1] ?? s }
function fmtTime(t) { return t ? dayjs(t).format('MM-DD HH:mm:ss') : '—' }
</script>

<style scoped>
.card-header { display: flex; align-items: center; justify-content: space-between; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; }
.progress-cell { display: flex; flex-direction: column; gap: 4px; }
.progress-labels { display: flex; gap: 8px; font-size: 12px; }
.label-completed { color: #67c23a; }
.label-failed { color: #f56c6c; }
.label-total { color: #909399; }
.pagination { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
