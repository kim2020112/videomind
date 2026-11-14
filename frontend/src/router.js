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
  { path: '/bloggers', name: 'bloggers', component: RouteSurface },
  { path: '/bloggers/:id', name: 'blogger-detail', component: RouteSurface },
]

export function scrollBehavior(to, _from, savedPosition) {
  if (to.name === 'blogger-detail') return false
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
