<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ page: Number, pageSize: Number, total: Number, busy: Boolean })
const emit = defineEmits(['page', 'size'])
const jump = ref('')
const count = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const numbers = computed(() => [...new Set([1, props.page - 1, props.page, props.page + 1, count.value])].filter(n => n > 0 && n <= count.value))
function go() {
  const n = Number(jump.value)
  if (Number.isInteger(n) && n >= 1) { emit('page', Math.min(n, count.value)); jump.value = '' }
}
</script>
<template>
  <nav class="list-pagination" aria-label="视频列表分页">
    <span class="page-total">共 {{ total }} 个 · {{ page }}/{{ count }} 页</span>
    <label>每页 <select :value="pageSize" :disabled="busy" @change="emit('size', Number($event.target.value))"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></label>
    <div class="page-buttons"><button :disabled="busy || page <= 1" @click="emit('page', page - 1)" aria-label="上一页">上一页</button>
      <button v-for="n in numbers" :key="n" class="page-number" :class="{ adjacent: n !== page && n !== 1 && n !== count }" :disabled="busy" :aria-current="page === n ? 'page' : undefined" @click="emit('page', n)">{{ n }}</button>
      <button :disabled="busy || page >= count" @click="emit('page', page + 1)" aria-label="下一页">下一页</button></div>
    <form @submit.prevent="go"><label>跳至 <input v-model="jump" type="number" min="1" :max="count" aria-label="跳转页码" /></label><button :disabled="busy">跳转</button></form>
  </nav>
</template>
<style scoped>
.list-pagination { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding:16px 0; color:var(--text-secondary); font-size:13px; scroll-margin-top:100px; }
.page-buttons, form { display:flex; gap:6px; align-items:center; }
button, select, input { min-height:44px; border:1px solid var(--border); border-radius:8px; background:var(--bg-secondary); color:var(--text-primary); padding:0 12px; font:inherit; }
button { min-width:44px; } button, select { cursor:pointer; } button[aria-current] { border-color:var(--accent-blue); color:var(--accent-blue); background:var(--bg-tertiary); }
button:hover:not(:disabled) { border-color:var(--accent-blue); } button:disabled { opacity:.45; cursor:default; } input { width:64px; } :focus-visible { outline:2px solid var(--accent-blue); outline-offset:2px; }
@media(max-width:600px) { .list-pagination { gap:8px; } .page-total { flex:1; } .page-number.adjacent { display:none; } .page-buttons { width:100%; justify-content:space-between; } button { padding:0 10px; } }
</style>
