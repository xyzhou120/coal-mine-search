<template>
  <div class="search-page">
    <!-- 检索条件卡片 -->
    <el-card class="filter-card" shadow="never">
      <template #header>
        <span class="card-title">检索条件</span>
        <span class="card-subtitle">不填写筛选条件则在全库范围内检索</span>
      </template>

      <el-form :model="form" label-width="90px" @submit.prevent="handleSearch">
        <!-- 第一行：煤矿 + 清单 -->
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="煤矿">
              <el-select
                v-model="form.mine_code"
                placeholder="全部煤矿"
                clearable
                filterable
                style="width: 100%"
                @change="onMineChange"
              >
                <el-option
                  v-for="m in mines"
                  :key="m.mine_code"
                  :label="m.mine_name"
                  :value="m.mine_code"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="清单类型">
              <el-select
                v-model="form.file_name_id"
                placeholder="全部清单"
                clearable
                filterable
                :disabled="!form.mine_code"
                style="width: 100%"
              >
                <el-option
                  v-for="l in listTypes"
                  :key="l.file_name_id"
                  :label="l.file_name"
                  :value="l.file_name_id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="上报时间">
              <el-input
                v-model="form.report_time"
                placeholder="如：2025-01"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 第二行：检索问题 -->
        <el-form-item label="检索问题">
          <el-input
            v-model="form.query"
            type="textarea"
            :rows="3"
            placeholder="请输入检索问题，例如：2025年1月安全检查发现了哪些隐患？"
            resize="none"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!form.query.trim()"
            @click="handleSearch"
            size="large"
          >
            <el-icon><Search /></el-icon>
            开始检索
          </el-button>
          <el-button @click="handleReset" size="large">重置</el-button>
          <span v-if="result" class="doc-count">
            检索范围：{{ result.doc_count }} 份文档
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 检索结果 -->
    <div v-if="loading" class="result-loading">
      <el-skeleton :rows="8" animated />
    </div>

    <template v-else-if="result">
      <!-- 答案卡片 -->
      <el-card class="answer-card" shadow="never">
        <template #header>
          <div class="answer-header">
            <el-icon color="#409eff" size="18"><ChatDotRound /></el-icon>
            <span class="card-title">检索结果</span>
          </div>
        </template>
        <div class="answer-content" v-if="result.answer">
          <p
            v-for="(line, i) in answerLines"
            :key="i"
            class="answer-line"
            v-html="line || '&nbsp;'"
          />
        </div>
        <el-empty v-else description="未找到相关内容" />
      </el-card>

      <!-- 引用来源 -->
      <el-card
        v-if="result.citations?.length"
        class="citations-card"
        shadow="never"
      >
        <template #header>
          <span class="card-title">引用来源</span>
          <el-tag size="small" type="info" style="margin-left: 8px">
            {{ result.citations.length }} 处引用
          </el-tag>
        </template>
        <el-table :data="result.citations" stripe size="small">
          <el-table-column type="index" width="50" label="#" />
          <el-table-column prop="mine_name" label="煤矿" width="160" show-overflow-tooltip />
          <el-table-column prop="file_name" label="清单类型" width="200" show-overflow-tooltip />
          <el-table-column prop="attachment_name" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column prop="report_time" label="上报时间" width="110" />
          <el-table-column prop="page" label="页码" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.page" size="small">第 {{ row.page }} 页</el-tag>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 错误提示 -->
    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      class="mt-16"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { searchApi } from '@/api'
import { ElMessage } from 'element-plus'

const form = ref({ query: '', mine_code: '', file_name_id: '', report_time: '' })
const mines = ref([])
const listTypes = ref([])
const loading = ref(false)
const result = ref(null)
const errorMsg = ref('')

const answerLines = computed(() =>
  (result.value?.answer || '').split('\n')
)

onMounted(loadMines)

async function loadMines() {
  try {
    const res = await searchApi.getMines()
    mines.value = res.items || []
  } catch {}
}

async function onMineChange(mineCode) {
  form.value.file_name_id = ''
  listTypes.value = []
  if (!mineCode) return
  try {
    const res = await searchApi.getListTypes(mineCode)
    listTypes.value = res.items || []
  } catch {}
}

async function handleSearch() {
  if (!form.value.query.trim()) return
  loading.value = true
  result.value = null
  errorMsg.value = ''
  try {
    const payload = { query: form.value.query }
    if (form.value.mine_code) payload.mine_code = form.value.mine_code
    if (form.value.file_name_id) payload.file_name_id = form.value.file_name_id
    if (form.value.report_time) payload.report_time = form.value.report_time
    result.value = await searchApi.search(payload)
    if (result.value.error) errorMsg.value = result.value.error
  } catch (e) {
    errorMsg.value = e?.response?.data?.detail || '检索失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function handleReset() {
  form.value = { query: '', mine_code: '', file_name_id: '', report_time: '' }
  result.value = null
  errorMsg.value = ''
  listTypes.value = []
}
</script>

<style scoped>
.search-page { display: flex; flex-direction: column; gap: 16px; }

.filter-card :deep(.el-card__header) {
  display: flex; align-items: baseline; gap: 12px; padding: 16px 20px;
}
.card-title { font-size: 15px; font-weight: 600; color: #303133; }
.card-subtitle { font-size: 12px; color: #909399; }

.doc-count { margin-left: 16px; font-size: 13px; color: #909399; }

.result-loading { background: #fff; border-radius: 8px; padding: 24px; }

.answer-header { display: flex; align-items: center; gap: 8px; }
.answer-content { line-height: 1.9; color: #303133; }
.answer-line { margin: 0; padding: 1px 0; font-size: 14px; }

.citations-card :deep(.el-card__header) {
  display: flex; align-items: center; padding: 12px 20px;
}

.text-muted { color: #c0c4cc; }
.mt-16 { margin-top: 16px; }
</style>
