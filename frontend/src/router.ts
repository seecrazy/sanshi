import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from './store/auth'

const routes = [
  { path: '/login', component: () => import('./pages/Login.vue') },
  { path: '/apply', component: () => import('./pages/Apply.vue') },
  { path: '/', component: () => import('./pages/consumer/Home.vue') },
  { path: '/shop/:id', component: () => import('./pages/consumer/ShopDetail.vue') },
  { path: '/orders', component: () => import('./pages/consumer/MyOrders.vue') },
  { path: '/orders/:id/track', component: () => import('./pages/consumer/OrderTrack.vue') },
  { path: '/merchant/board', component: () => import('./pages/merchant/OrderBoard.vue') },
  { path: '/merchant/goods', component: () => import('./pages/merchant/GoodsManage.vue') },
  { path: '/merchant/settings', component: () => import('./pages/merchant/Settings.vue') },
  { path: '/rider/pool', component: () => import('./pages/rider/TaskPool.vue') },
  { path: '/gov/issues', component: () => import('./pages/governance/IssueList.vue') },
  { path: '/gov/issues/:id', component: () => import('./pages/governance/IssueDetail.vue') },
  { path: '/gov/jury', component: () => import('./pages/governance/JuryTasks.vue') },
  { path: '/gov/decisions', component: () => import('./pages/governance/DecisionFeed.vue') },
  { path: '/admin', component: () => import('./pages/admin/Dashboard.vue') },
]

export const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuth()
  if (to.path !== '/login' && !auth.isLogin) return '/login'
  return true
})
