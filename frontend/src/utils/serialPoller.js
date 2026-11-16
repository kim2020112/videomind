// Schedule from completion so a slow request never overlaps the next tick.
export function createSerialPoller(interval = 3000) {
  let timer = null
  let generation = 0
  function stop() {
    generation += 1
    clearTimeout(timer)
    timer = null
  }
  function start(run) {
    stop()
    const ticket = generation
    const current = () => ticket === generation
    let failures = 0
    const tick = async () => {
      try {
        const result = await run(current)
        if (!current()) return
        if (result === false) { stop(); return }
        failures = result === null ? failures + 1 : 0
      } catch {
        failures += 1
      } finally {
        if (current()) timer = setTimeout(tick, Math.min(30000, interval * 2 ** Math.min(failures, 4)))
      }
    }
    timer = setTimeout(tick, interval)
  }
  return { start, stop }
}
