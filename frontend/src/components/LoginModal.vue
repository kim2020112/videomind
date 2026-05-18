<script setup>
import { ref } from 'vue'
import { useAuth } from '../composables/useAuth.js'

const { login, register, loading } = useAuth()

const emit = defineEmits(['close'])
const props = defineProps({ visible: Boolean })

const mode = ref('login') // 'login' | 'register'
const username = ref('')
const password = ref('')
const error = ref('')

async function handleSubmit() {
  error.value = ''
  try {
    if (mode.value === 'login') {
      await login(username.value, password.value)
    } else {
      await register(username.value, password.value)
    }
    emit('close')
    username.value = ''
    password.value = ''
  } catch (e) {
    error.value = e.message
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-card">
        <button class="modal-close" @click="$emit('close')">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </button>

        <h2 class="modal-title">{{ mode === 'login' ? '登录' : '注册' }}</h2>
        <p class="modal-desc">{{ mode === 'login' ? '登录后可查看个人学习历史和统计数据' : '创建账号，开始记录你的学习旅程' }}</p>

        <form @submit.prevent="handleSubmit" class="modal-form">
          <div class="form-group">
            <label>用户名</label>
            <input v-model="username" type="text" placeholder="至少 2 个字符" autocomplete="username" />
          </div>
          <div class="form-group">
            <label>密码</label>
            <input v-model="password" type="password" placeholder="至少 4 个字符" autocomplete="current-password" />
          </div>

          <p v-if="error" class="form-error">{{ error }}</p>

          <button type="submit" class="form-submit" :disabled="loading">
            {{ loading ? '请稍候...' : (mode === 'login' ? '登录' : '注册') }}
          </button>
        </form>

        <p class="modal-switch">
          {{ mode === 'login' ? '没有账号？' : '已有账号？' }}
          <a href="#" @click.prevent="switchMode">{{ mode === 'login' ? '立即注册' : '去登录' }}</a>
        </p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  position: relative;
  width: 100%;
  max-width: 380px;
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 2rem;
  margin: 1rem;
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s;
}
.modal-close:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.modal-close svg { width: 18px; height: 18px; }

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 0.5rem;
}

.modal-desc {
  font-size: 0.8125rem;
  color: #94a3b8;
  margin: 0 0 1.5rem;
  line-height: 1.5;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-group label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #cbd5e1;
}

.form-group input {
  padding: 0.625rem 0.875rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  color: #f1f5f9;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.15s;
}

.form-group input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.form-group input::placeholder {
  color: #64748b;
}

.form-error {
  font-size: 0.8125rem;
  color: #fca5a5;
  margin: 0;
  padding: 0.5rem 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
}

.form-submit {
  padding: 0.625rem;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  margin-top: 0.25rem;
}
.form-submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.form-submit:disabled { opacity: 0.5; cursor: not-allowed; }

.modal-switch {
  text-align: center;
  font-size: 0.8125rem;
  color: #94a3b8;
  margin: 1rem 0 0;
}
.modal-switch a {
  color: #60a5fa;
  text-decoration: none;
  font-weight: 600;
}
.modal-switch a:hover { text-decoration: underline; }
</style>
