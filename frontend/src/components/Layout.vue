<template>
  <el-container class="layout">
    <!-- 侧边栏 -->
    <el-aside width="220px" class="aside">
      <div class="logo">
        <el-icon size="22" color="#409eff"><Files /></el-icon>
        <span>煤矿文档检索</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        background-color="#1a1a2e"
        text-color="#c0c4cc"
        active-text-color="#409eff"
      >
        <el-menu-item index="/search">
          <el-icon><Search /></el-icon>
          <span>文档检索</span>
        </el-menu-item>
        <el-sub-menu index="/import-group">
          <template #title>
            <el-icon><Upload /></el-icon>
            <span>文档导入</span>
          </template>
          <el-menu-item index="/import">
            <el-icon><UploadFilled /></el-icon>
            <span>上传 Excel</span>
          </el-menu-item>
          <el-menu-item index="/import/tasks">
            <el-icon><List /></el-icon>
            <span>导入任务</span>
          </el-menu-item>
          <el-menu-item index="/import/documents">
            <el-icon><Document /></el-icon>
            <span>文档列表</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <span class="page-title">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-tag
            :type="healthStatus === 'ok' ? 'success' : 'danger'"
            size="small"
            effect="light"
          >
            {{ healthStatus === 'ok' ? '服务正常' : '服务异常' }}
          </el-tag>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const healthStatus = ref('unknown')

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta?.title || '煤矿文档检索系统')

onMounted(async () => {
  try {
    const res = await axios.get('/health')
    healthStatus.value = res.data?.status || 'ok'
  } catch {
    healthStatus.value = 'error'
  }
})
</script>

<style scoped>
.layout { height: 100vh; }

.aside {
  background-color: #1a1a2e;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 20px 16px;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  border-bottom: 1px solid #2a2a4a;
  margin-bottom: 8px;
}

.el-menu { border-right: none; flex: 1; }

.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.main {
  background: #f5f7fa;
  padding: 24px;
  overflow-y: auto;
}
</style>
