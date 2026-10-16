<template>
  <div class="import-page">
    <el-row :gutter="20">
      <!-- 上传区域 -->
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">上传 Excel 文件</span>
          </template>

          <el-upload
            ref="uploadRef"
            class="upload-area"
            drag
            action=""
            :auto-upload="false"
            :on-change="onFileChange"
            :before-remove="() => false"
            accept=".xlsx,.xls"
            :limit="1"
          >
            <el-icon size="48" color="#c0c4cc"><UploadFilled /></el-icon>
            <div class="upload-text">
              <p>拖拽 Excel 文件到此处，或 <em>点击选择</em></p>
              <p class="upload-hint">支持 .xlsx / .xls 格式</p>
            </div>
          </el-upload>

          <div v-if="selectedFile" class="selected-file">
            <el-icon color="#409eff"><Document /></el-icon>
            <span>{{ selectedFile.name }}</span>
            <el-tag size="small" type="info">
              {{ formatSize(selectedFile.size) }}
            </el-tag>
            <el-button
              link type="danger" size="small"
              @click="clearFile"
            >移除</el-button>
          </div>

          <div class="upload-actions">
            <el-button
              type="primary"
              size="large"
              :loading="uploading"
              :disabled="!selectedFile"
              @click="handleUpload"
            >
              <el-icon><Upload /></el-icon>
              开始导入
            </el-button>
          </div>

          <!-- 上传进度 -->
          <el-progress
            v-if="uploadProgress > 0 && uploadProgress < 100"
            :percentage="uploadProgress"
            style="margin-top: 16px"
          />
        </el-card>
      </el-col>

      <!-- 说明 -->
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">Excel 格式说明</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="mine_code" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 煤矿编码
            </el-descriptions-item>
            <el-descriptions-item label="mine_name" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 煤矿名称
            </el-descriptions-item>
            <el-descriptions-item label="file_name_id" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 清单类型ID
            </el-descriptions-item>
            <el-descriptions-item label="file_name" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 清单类型名称
            </el-descriptions-item>
            <el-descriptions-item label="attachment_id" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 附件唯一ID
            </el-descriptions-item>
            <el-descriptions-item label="attachment_name" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> 附件文件名
            </el-descriptions-item>
            <el-descriptions-item label="attachment_link" label-class-name="desc-label">
              <el-tag type="danger" size="small">必填</el-tag> MinIO HTTPS 地址
            </el-descriptions-item>
            <el-descriptions-item label="report_time" label-class-name="desc-label">
              <el-tag type="info" size="small">选填</el-tag> 上报时间
            </el-descriptions-item>
            <el-descriptions-item label="update_rate" label-class-name="desc-label">
              <el-tag type="info" size="small">选填</el-tag> 更新频率数值
            </el-descriptions-item>
            <el-descriptions-item label="cycle" label-class-name="desc-label">
              <el-tag type="info" size="small">选填</el-tag> 上报周期枚举
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <!-- 上传结果 -->
    <el-card v-if="uploadResult" shadow="never" class="result-card">
      <template #header>
        <span class="card-title">导入结果</span>
      </template>
      <el-descriptions :column="4" border>
        <el-descriptions-item label="任务ID">
          <el-text truncated style="max-width: 200px">{{ uploadResult.task_id }}</el-text>
        </el-descriptions-item>
        <el-descriptions-item label="总行数">{{ uploadResult.total_rows }}</el-descriptions-item>
        <el-descriptions-item label="有效记录">
          <el-text type="success">{{ uploadResult.valid_count }}</el-text>
        </el-descriptions-item>
        <el-descriptions-item label="新增文件">
          <el-text type="primary">{{ uploadResult.new_count }}</el-text>
        </el-descriptions-item>
        <el-descriptions-item label="跳过（已存在）">{{ uploadResult.skip_count }}</el-descriptions-item>
        <el-descriptions-item label="无效行">
          <el-text :type="uploadResult.invalid_rows?.length ? 'danger' : 'info'">
            {{ uploadResult.invalid_rows?.length || 0 }}
          </el-text>
        </el-descriptions-item>
      </el-descriptions>

      <div v-if="uploadResult.invalid_rows?.length" class="invalid-rows">
        <p class="invalid-title">
          <el-icon color="#f56c6c"><Warning /></el-icon>
          无效行详情（最多展示10条）
        </p>
        <el-table :data="uploadResult.invalid_rows" size="small" border>
          <el-table-column prop="row" label="行号" width="70" />
          <el-table-column prop="attachment_id" label="attachment_id" width="160" show-overflow-tooltip />
          <el-table-column prop="reason" label="原因" />
        </el-table>
      </div>

      <div class="result-actions">
        <el-button type="primary" @click="$router.push('/import/tasks')">
          查看导入进度
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importApi } from '@/api'

const uploadRef = ref()
const selectedFile = ref(null)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadResult = ref(null)

function onFileChange(file) {
  selectedFile.value = file.raw
}

function clearFile() {
  selectedFile.value = null
  uploadProgress.value = 0
  uploadRef.value?.clearFiles()
}

async function handleUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  uploadProgress.value = 0
  uploadResult.value = null
  try {
    const fd = new FormData()
    fd.append('file', selectedFile.value)
    const res = await importApi.upload(fd, e => {
      uploadProgress.value = Math.round((e.loaded / e.total) * 100)
    })
    uploadResult.value = res
    ElMessage.success('文件上传成功，后台正在处理')
    clearFile()
  } catch {
    ElMessage.error('上传失败，请检查文件格式')
  } finally {
    uploading.value = false
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / 1024 / 1024).toFixed(1) + 'MB'
}
</script>

<style scoped>
.import-page { display: flex; flex-direction: column; gap: 16px; }
.card-title { font-size: 15px; font-weight: 600; color: #303133; }

.upload-area { width: 100%; }
.upload-text p { margin: 6px 0; color: #606266; font-size: 14px; }
.upload-text em { color: #409eff; font-style: normal; }
.upload-hint { color: #909399; font-size: 12px; }

.selected-file {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; background: #f5f7fa;
  border-radius: 6px; margin-top: 12px; font-size: 13px;
}
.selected-file span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.upload-actions { margin-top: 20px; display: flex; justify-content: center; }

.result-card { margin-top: 4px; }
.invalid-rows { margin-top: 16px; }
.invalid-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: #f56c6c; margin-bottom: 8px;
}
.result-actions { margin-top: 16px; display: flex; justify-content: flex-end; }

:deep(.desc-label) { font-family: monospace; font-size: 12px; color: #606266; }
</style>
