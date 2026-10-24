/**
 * 单元测试运行在 node 环境（不引入 jsdom，避免额外体积）。
 * 这里给 stores 里用到的最小浏览器 API 打桩：主题、localStorage、计时器无关的部分。
 */

class MemoryStorage {
  constructor() {
    this.map = new Map()
  }

  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null
  }

  setItem(key, value) {
    this.map.set(key, String(value))
  }

  removeItem(key) {
    this.map.delete(key)
  }

  clear() {
    this.map.clear()
  }
}

const storage = new MemoryStorage()

Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true })
Object.defineProperty(globalThis, 'sessionStorage', { value: new MemoryStorage(), configurable: true })

if (!globalThis.document) {
  const element = () => ({
    dataset: {},
    style: {},
    setAttribute() {},
    getAttribute() {
      return null
    },
    appendChild() {},
    removeChild() {},
  })
  globalThis.document = {
    documentElement: element(),
    body: element(),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => element(),
    addEventListener() {},
    removeEventListener() {},
  }
}

if (!globalThis.window) {
  globalThis.window = {
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
    innerWidth: 1440,
    innerHeight: 900,
    devicePixelRatio: 1,
  }
}
