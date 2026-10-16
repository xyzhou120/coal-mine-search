import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api',
  timeout: 120000, // 检索可能需要较长时间
})

request.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    ElMessage.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    return Promise.reject(err)
  }
)

// ── 导入相关 ──────────────────────────────────────────────
export const importApi = {
  /** 上传 Excel 文件 */
  upload(formData, onProgress) {
    return request.post('/import/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    })
  },

  /** 获取任务列表 */
  getTasks(page = 1, pageSize = 20) {
    return request.get('/import/tasks', { params: { page, page_size: pageSize } })
  },

  /** 获取单个任务详情 */
  getTask(taskId) {
    return request.get(`/import/tasks/${taskId}`)
  },

  /** 重试失败文件 */
  retryTask(taskId) {
    return request.post(`/import/tasks/${taskId}/retry`)
  },

  /** 获取文档列表 */
  getDocuments(params) {
    return request.get('/import/documents', { params })
  },

  /** 重新索引单个文件 */
  reindexDocument(attachmentId) {
    return request.post(`/import/documents/${attachmentId}/reindex`)
  },
}

// ── 检索相关 ──────────────────────────────────────────────
export const searchApi = {
  /** 执行检索 */
  search(payload) {
    return request.post('/search', payload)
  },

  /** 获取已索引煤矿列表 */
  getMines() {
    return request.get('/search/mines')
  },

  /** 获取指定煤矿的清单类型 */
  getListTypes(mineCode) {
    return request.get(`/search/mines/${mineCode}/list-types`)
  },
}

// ── 系统 ──────────────────────────────────────────────────
export const systemApi = {
  health() {
    return request.get('/health'.replace('/api', ''))
  },
}
