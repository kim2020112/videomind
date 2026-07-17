export function formatModelLabel(model) {
  const name = String(model?.name || '').trim()
  const id = String(model?.model || '').trim()

  return !name || name === id ? id || name : `${name} · ${id}`
}
