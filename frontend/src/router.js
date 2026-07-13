import { defineComponent } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

const RouteSurface = defineComponent({
  name: 'RouteSurface',
  render: () => null,
})

export const routes = [
  { path: '/', name: 'home', component: RouteSurface },
  { path: '/workspace', name: 'workspace', component: RouteSurface },
  { path: '/history', name: 'history', component: RouteSurface },
  { path: '/history/:urlHash', name: 'history-detail', component: RouteSurface },
]

export function scrollBehavior(_to, _from, savedPosition) {
  return savedPosition || { left: 0, top: 0 }
}

export function createAppRouter(history = createWebHistory()) {
  return createRouter({
    history,
    routes,
    scrollBehavior,
  })
}

export const router = createAppRouter()
