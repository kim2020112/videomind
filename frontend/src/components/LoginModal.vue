<script setup>
import { ref } from 'vue'
import { useAuth } from '../composables/useAuth.js'
import BaseDialog from './BaseDialog.vue'

const { login, register, loading } = useAuth()
const emit = defineEmits(['close', 'authenticated'])
defineProps({ visible: Boolean })

const mode = ref('login')
const username = ref('')
const password = ref('')
const error = ref('')
const fieldErrors = ref({ username: '', password: '' })

function validate() {
  const usernameValue = username.value.trim()
  const nextErrors = {
    username: usernameValue ? (usernameValue.length < 2 ? '用户名至少需要 2 个字符' : '') : '请输入用户名',
    password: password.value ? (password.value.length < 4 ? '密码至少需要 4 个字符' : '') : '请输入密码',
  }
  fieldErrors.value = nextErrors
  return !nextErrors.username && !nextErrors.password
}

async function handleSubmit() {
  error.value = ''
  if (!validate()) return

  try {
    if (mode.value === 'login') {
      await login(username.value.trim(), password.value)
    } else {
      await register(username.value.trim(), password.value)
    }
    emit('authenticated')
    emit('close')
    username.value = ''
    password.value = ''
    fieldErrors.value = { username: '', password: '' }
  } catch (submitError) {
    error.value = submitError.message || '登录失败，请稍后重试'
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
  fieldErrors.value = { username: '', password: '' }
}
</script>

<template>
  <BaseDialog
    :visible="visible"
    title-id="login-dialog-title"
    :close-label="mode === 'login' ? '关闭登录弹窗' : '关闭注册弹窗'"
    initial-focus="#login-username"
    @close="emit('close')"
  >
    <h2 id="login-dialog-title" class="modal-title">{{ mode === 'login' ? '登录' : '注册' }}</h2>
    <p class="modal-desc">{{ mode === 'login' ? '登录后继续当前学习任务，并查看个人历史与统计' : '创建账号，开始记录你的学习旅程' }}</p>

    <form class="modal-form" novalidate @submit.prevent="handleSubmit">
      <div class="form-group">
        <label for="login-username">用户名</label>
        <input
          id="login-username"
          v-model="username"
          name="username"
          type="text"
          placeholder="至少 2 个字符"
          autocomplete="username"
          spellcheck="false"
          :aria-invalid="Boolean(fieldErrors.username)"
          :aria-describedby="fieldErrors.username ? 'login-username-error' : undefined"
          @input="fieldErrors.username = ''"
        />
        <p v-if="fieldErrors.username" id="login-username-error" class="field-error">{{ fieldErrors.username }}</p>
      </div>

      <div class="form-group">
        <label for="login-password">密码</label>
        <input
          id="login-password"
          v-model="password"
          name="password"
          type="password"
          placeholder="至少 4 个字符"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          :aria-invalid="Boolean(fieldErrors.password)"
          :aria-describedby="fieldErrors.password ? 'login-password-error' : undefined"
          @input="fieldErrors.password = ''"
        />
        <p v-if="fieldErrors.password" id="login-password-error" class="field-error">{{ fieldErrors.password }}</p>
      </div>

      <p v-if="error" class="form-error" role="alert" aria-live="polite">{{ error }}</p>

      <button type="submit" class="form-submit" :disabled="loading">
        {{ loading ? '请稍候…' : (mode === 'login' ? '登录' : '注册') }}
      </button>
    </form>

    <p class="modal-switch">
      {{ mode === 'login' ? '没有账号？' : '已有账号？' }}
      <button type="button" class="mode-switch-button" @click="switchMode">{{ mode === 'login' ? '立即注册' : '去登录' }}</button>
    </p>
  </BaseDialog>
</template>

<style scoped>
.modal-title {
  margin: 0 3rem 0.5rem 0;
  color: #f1f5f9;
  font-size: 1.25rem;
  font-weight: 700;
}

.modal-desc {
  margin: 0 0 1.5rem;
  color: var(--text-secondary);
  font-size: 0.8125rem;
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
  color: #cbd5e1;
  font-size: 0.8125rem;
  font-weight: 600;
}

.form-group input {
  min-height: 44px;
  padding: 0.625rem 0.875rem;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  color: #f1f5f9;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.form-group input:focus-visible {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
}

.form-group input::placeholder {
  color: var(--text-muted);
}

.field-error {
  margin: 0;
  color: #fca5a5;
  font-size: 0.75rem;
  line-height: 1.4;
}

.form-error {
  margin: 0;
  padding: 0.5rem 0.75rem;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.1);
  color: #fca5a5;
  font-size: 0.8125rem;
}

.form-submit {
  min-height: 44px;
  margin-top: 0.25rem;
  padding: 0.625rem;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  color: white;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}

.form-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.form-submit:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.modal-switch {
  margin: 1rem 0 0;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  text-align: center;
}

.mode-switch-button {
  min-height: 44px;
  padding: 0.25rem 0.375rem;
  border: 0;
  background: transparent;
  color: #60a5fa;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.mode-switch-button:hover {
  color: #93c5fd;
  text-decoration: underline;
}
</style>
