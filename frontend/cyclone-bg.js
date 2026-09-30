/* CYCLOPS background: a procedural, satellite-style tropical cyclone that rotates
   counter-clockwise (Northern Hemisphere) and drifts slowly north-west, as a Bay of Bengal
   cyclone approaching the Odisha coast would. Rendered at low resolution and scaled up
   (clouds are soft, so this costs a few ms per frame). Honours prefers-reduced-motion,
   pauses when the tab is hidden, and exposes window.cycloneBg for scenario intensity. */
(function () {
  "use strict";
  const canvas = document.getElementById("bg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const low = document.createElement("canvas");
  const lctx = low.getContext("2d");

  // ---------- tileable fbm value noise (256 x 256) ----------
  const N = 256;
  function makeNoise(seed) {
    let s = seed >>> 0;
    const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
    const out = new Float32Array(N * N);
    let amp = 1, total = 0;
    for (let oct = 0; oct < 5; oct++) {
      const cells = 4 << oct;
      const g = new Float32Array(cells * cells);
      for (let i = 0; i < g.length; i++) g[i] = rnd();
      const step = N / cells;
      for (let y = 0; y < N; y++) {
        const gy = y / step, y0 = Math.floor(gy), fy = gy - y0;
        const sy = fy * fy * (3 - 2 * fy);
        const ya = (y0 % cells) * cells, yb = ((y0 + 1) % cells) * cells;
        for (let x = 0; x < N; x++) {
          const gx = x / step, x0 = Math.floor(gx), fx = gx - x0;
          const sx = fx * fx * (3 - 2 * fx);
          const xa = x0 % cells, xb = (x0 + 1) % cells;
          const a = g[ya + xa] + (g[ya + xb] - g[ya + xa]) * sx;
          const b = g[yb + xa] + (g[yb + xb] - g[yb + xa]) * sx;
          out[y * N + x] += (a + (b - a) * sy) * amp;
        }
      }
      total += amp;
      amp *= 0.52;
    }
    for (let i = 0; i < out.length; i++) out[i] /= total;
    return out;
  }
  const NOISE = makeNoise(20190503);
  const NOISE2 = makeNoise(1999);

  function sample(tex, u, v) {
    u = ((u % N) + N) % N; v = ((v % N) + N) % N;
    const x0 = u | 0, y0 = v | 0, fx = u - x0, fy = v - y0;
    const x1 = (x0 + 1) & 255, y1 = (y0 + 1) & 255;
    const a = tex[y0 * N + x0], b = tex[y0 * N + x1], c = tex[y1 * N + x0], d = tex[y1 * N + x1];
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  }

  // ---------- state ----------
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  let intensity = 1.0, targetIntensity = 1.0;
  let paused = reduce;
  let t = 0, last = 0, acc = 1, cost = 8, targetFps = 30, img = null, W = 0, H = 0;
  const TRACK_SECONDS = 420; // one full drift across the screen
  const ocean = [13, 38, 54], oceanDeep = [8, 26, 39], cloud = [236, 243, 247];

  function resize() {
    const w = window.innerWidth, h = window.innerHeight;
    canvas.width = Math.round(w * Math.min(1.5, window.devicePixelRatio || 1));
    canvas.height = Math.round(h * Math.min(1.5, window.devicePixelRatio || 1));
    W = 260; H = Math.max(140, Math.round(W * h / w));
    low.width = W; low.height = H;
    img = lctx.createImageData(W, H);
  }

  function frame(now) {
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    if (!paused) t += dt;
    intensity += (targetIntensity - intensity) * Math.min(1, dt * 0.8);
    acc += dt;
    if (acc >= 1 / targetFps) {
      acc = 0;
      const s0 = performance.now();
      render();
      cost = cost * 0.9 + (performance.now() - s0) * 0.1;
      targetFps = cost > 22 ? 12 : cost > 12 ? 20 : 30; // back off on slow devices
    }
    if (!paused) requestAnimationFrame(frame);
  }

  function render() {
    const d = img.data;
    const m = Math.min(W, H);
    // slow NW drift from lower-right towards upper-left, then fade and restart
    const phase = (t % TRACK_SECONDS) / TRACK_SECONDS;
    const cx = W * (0.78 - 0.42 * phase);
    const cy = H * (0.80 - 0.50 * phase);
    const fade = Math.min(1, phase / 0.04, (1 - phase) / 0.04);
    const R = m * 0.62 * (0.85 + 0.15 * intensity);
    const eye = m * (0.030 - 0.006 * (intensity - 1));
    const omega = 0.10 * (0.8 + 0.4 * intensity);   // rad/s, counter-clockwise
    const arms = 2, wind = 1.9;                      // integer band count keeps the field continuous
    const inflow = t * 6;                            // texture drifts inward along the bands
    let p = 0;
    for (let y = 0; y < H; y++) {
      const dy = cy - y; // y up
      for (let x = 0; x < W; x++) {
        const dx = x - cx;
        const r = Math.sqrt(dx * dx + dy * dy) + 0.001;
        const bgc = sample(NOISE2, x * 0.9 + t * 1.5, y * 0.9 + t * 0.4);
        const deep = Math.min(1, (x + y) / (W + H) * 1.2);
        const oc0 = ocean[0] + (oceanDeep[0] - ocean[0]) * deep;
        const oc1 = ocean[1] + (oceanDeep[1] - ocean[1]) * deep;
        const oc2 = ocean[2] + (oceanDeep[2] - ocean[2]) * deep;
        if (r > R * 2.2) {                       // far field: only scattered convection
          const a0 = Math.min(1, Math.max(0, bgc - 0.56) * 1.6) * 0.8;
          d[p++] = oc0 + (cloud[0] - oc0) * a0; d[p++] = oc1 + (cloud[1] - oc1) * a0;
          d[p++] = oc2 + (cloud[2] - oc2) * a0; d[p++] = 255;
          continue;
        }
        const th = Math.atan2(dy, dx);
        const lr = Math.log(r / eye + 1);
        const spiral = th + wind * lr - omega * t;       // NH: outward bands turn clockwise
        const u = (spiral / (Math.PI * 2)) * 256 * 2;
        const v = lr * 70 + inflow;
        const n = 0.55 * sample(NOISE, u, v) + 0.45 * sample(NOISE, u * 3.1 + 37, v * 2.7 + 91);
        const band = 0.5 + 0.5 * Math.cos(arms * spiral + n * 2.4);
        const rn = r / R;
        const env = Math.exp(-Math.pow(rn * 1.15, 1.6));             // storm extent
        const cdo = Math.exp(-Math.pow(r / (R * 0.28), 2));          // central dense overcast
        const eyeCut = 0.12 + 0.88 / (1 + Math.exp(-(r - eye * 1.2) / (eye * 0.22)));
        const wall = Math.exp(-Math.pow((r - eye * 1.7) / (eye * 0.6), 2)) * 0.35;
        let dens = env * (cdo * (0.6 + 0.6 * n) + (1 - cdo) * Math.pow(band, 2.2) * (0.2 + 1.5 * n * n)) * intensity;
        dens = dens * eyeCut + wall * eyeCut;
        // scattered background convection, drifting west
        const bg = Math.min(1, Math.max(0, bgc - 0.56) * 1.6) * 0.8;
        dens = Math.min(1, dens * fade + bg * (1 - env * 0.6));
        const shade = 0.45 + 0.55 * n; // texture in cloud tops
        const a = Math.min(1, dens * (0.5 + 0.6 * shade));
        d[p++] = oc0 + (cloud[0] - oc0) * a;
        d[p++] = oc1 + (cloud[1] - oc1) * a;
        d[p++] = oc2 + (cloud[2] - oc2) * a;
        d[p++] = 255;
      }
    }
    lctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(low, 0, 0, canvas.width, canvas.height);
    // chart graticule: faint lat/lon lines, a nod to the synoptic chart
    ctx.strokeStyle = "rgba(255,255,255,0.06)";
    ctx.lineWidth = 1;
    const gs = Math.round(canvas.width / 12);
    ctx.beginPath();
    for (let gx = gs; gx < canvas.width; gx += gs) { ctx.moveTo(gx + 0.5, 0); ctx.lineTo(gx + 0.5, canvas.height); }
    for (let gy = gs; gy < canvas.height; gy += gs) { ctx.moveTo(0, gy + 0.5); ctx.lineTo(canvas.width, gy + 0.5); }
    ctx.stroke();
  }

  function start() { if (!paused) { last = 0; requestAnimationFrame(frame); } }

  resize();
  t = 60; // start with the storm already on screen
  render();
  start();
  window.addEventListener("resize", () => { resize(); render(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) paused = true;
    else if (!reduce && !window.cycloneBg.userPaused) { paused = false; start(); }
  });

  window.cycloneBg = {
    userPaused: reduce,
    setIntensity(v) { targetIntensity = v; if (paused) { intensity = v; render(); } },
    toggle() {
      this.userPaused = !this.userPaused;
      paused = this.userPaused;
      if (!paused) start();
      return !paused;
    },
    get running() { return !paused; },
  };
})();
