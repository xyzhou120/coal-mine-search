import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/components/Layout.vue'),
    redirect: '/search',
    children: [
      {
        path: '/search',
        name: 'Search',
        component: () => import('@/views/search/SearchView.vue'),
        meta: { title: '文档检索' }
      },
      {
        path: '/import',
        name: 'Import',
        component: () => import('@/views/import/ImportView.vue'),
        meta: { title: '文档导入' }
      },
      {
        path: '/import/tasks',
        name: 'ImportTasks',
        component: () => import('@/views/import/TaskListView.vue'),
        meta: { title: '导入任务' }
      },
      {
        path: '/import/documents',
        name: 'Documents',
        component: () => import('@/views/import/DocumentListView.vue'),
        meta: { title: '文档列表' }
      }
    ]
  }
]

export default createRouter({
  history: createWebHistory(),
  routes
})
