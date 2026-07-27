import "@testing-library/jest-dom/vitest";

// jsdom 未实现 matchMedia,AntD 组件启动时会用到;补一个惰性桩。
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}
