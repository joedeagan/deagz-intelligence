// JARVIS HUD Orb — Movie-accurate concentric rings with DEAGZ branding

class JarvisOrb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = "idle";
    this.time = 0;
    this.audioLevel = 0;
    this.targetAudioLevel = 0;

    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.animate();
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = window.innerWidth * dpr;
    this.canvas.height = window.innerHeight * dpr;
    this.canvas.style.width = window.innerWidth + "px";
    this.canvas.style.height = window.innerHeight + "px";
    this.ctx.scale(dpr, dpr);
    this.w = window.innerWidth;
    this.h = window.innerHeight;
    this.cx = this.w / 2;
    this.cy = this.h / 2;
    this.baseR = Math.min(this.w, this.h) * 0.28;
  }

  setState(s) { this.state = s; }
  setAudioLevel(l) { this.targetAudioLevel = l; }

  animate() {
    this.time += 0.016;
    this.audioLevel += (this.targetAudioLevel - this.audioLevel) * 0.12;
    this.ctx.clearRect(0, 0, this.w, this.h);

    this.drawBackground();
    this.drawOuterRing();
    this.drawTickMarks();
    this.drawMiddleRings();
    this.drawSegmentedRing();
    this.drawInnerDetailRing();
    this.drawCoreGlow();
    this.drawCenterText();
    this.drawCornerHUD();

    requestAnimationFrame(() => this.animate());
  }

  // Dark blue gradient background with grid
  drawBackground() {
    // Radial gradient
    const g = this.ctx.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, this.baseR * 3);
    g.addColorStop(0, "rgba(8, 30, 55, 1)");
    g.addColorStop(0.5, "rgba(4, 15, 30, 1)");
    g.addColorStop(1, "rgba(2, 8, 18, 1)");
    this.ctx.fillStyle = g;
    this.ctx.fillRect(0, 0, this.w, this.h);

    // Subtle grid
    this.ctx.strokeStyle = "rgba(0, 80, 140, 0.06)";
    this.ctx.lineWidth = 0.5;
    const step = 40;
    for (let x = 0; x < this.w; x += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(x, 0);
      this.ctx.lineTo(x, this.h);
      this.ctx.stroke();
    }
    for (let y = 0; y < this.h; y += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(this.w, y);
      this.ctx.stroke();
    }
  }

  // Outermost thick ring with glow
  drawOuterRing() {
    const ctx = this.ctx;
    const speak = this.state === "speaking" ? this.audioLevel * 0.06 : 0;
    const r = this.baseR * (1.15 + speak);

    // Glow behind ring
    ctx.beginPath();
    ctx.arc(this.cx, this.cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0, 160, 240, 0.08)";
    ctx.lineWidth = 12;
    ctx.stroke();

    // Main ring
    ctx.beginPath();
    ctx.arc(this.cx, this.cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0, 170, 255, 0.25)";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Second outer ring
    ctx.beginPath();
    ctx.arc(this.cx, this.cy, r * 1.04, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0, 150, 230, 0.12)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Tick marks around the outer ring like a compass/gauge
  drawTickMarks() {
    const ctx = this.ctx;
    const r = this.baseR * 1.15;
    const thinkSpeed = this.state === "thinking" ? 2 : 0;
    const rotation = this.time * (0.05 + thinkSpeed * 0.1);

    ctx.save();
    ctx.translate(this.cx, this.cy);
    ctx.rotate(rotation);

    for (let i = 0; i < 360; i += 2) {
      const angle = (i / 180) * Math.PI;
      const isMajor = i % 10 === 0;
      const isMid = i % 5 === 0;
      const inner = isMajor ? r * 0.92 : isMid ? r * 0.95 : r * 0.97;
      const outer = r;

      ctx.beginPath();
      ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
      ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
      ctx.strokeStyle = isMajor ? "rgba(0, 200, 255, 0.4)" :
                        isMid ? "rgba(0, 180, 255, 0.2)" :
                        "rgba(0, 160, 255, 0.08)";
      ctx.lineWidth = isMajor ? 1.5 : 0.5;
      ctx.stroke();
    }

    // Cardinal markers (N, E, S, W style notches)
    for (let i = 0; i < 4; i++) {
      const a = (i / 4) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r * 0.88, Math.sin(a) * r * 0.88);
      ctx.lineTo(Math.cos(a) * r * 1.02, Math.sin(a) * r * 1.02);
      ctx.strokeStyle = "rgba(0, 220, 255, 0.6)";
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }

    ctx.restore();
  }

  // Middle concentric rings — the signature look
  drawMiddleRings() {
    const ctx = this.ctx;
    const isListening = this.state === "listening";
    const listen = isListening ? 1.08 : 1;
    const speak = this.state === "speaking" ? 1 + this.audioLevel * 0.04 : 1;

    // Listening pulse effect — rings breathe in and out
    const listenPulse = isListening ? Math.sin(this.time * 3) * 0.03 : 0;

    const rings = [
      { r: 0.88, w: 1.5, a: 0.2 },
      { r: 0.78, w: 1, a: 0.15 },
      { r: 0.68, w: 1, a: 0.12 },
      { r: 0.58, w: 0.8, a: 0.1 },
    ];

    rings.forEach((ring, i) => {
      const pOffset = isListening ? Math.sin(this.time * 3 + i * 0.8) * 0.03 : 0;
      const radius = this.baseR * (ring.r + pOffset) * listen * speak;

      ctx.beginPath();
      ctx.arc(this.cx, this.cy, radius, 0, Math.PI * 2);

      if (isListening) {
        // Brighter cyan when listening
        const bright = ring.a * 2.5;
        ctx.strokeStyle = `rgba(0, 220, 255, ${bright})`;
        ctx.lineWidth = ring.w * 1.8;
      } else {
        ctx.strokeStyle = `rgba(0, 180, 255, ${ring.a})`;
        ctx.lineWidth = ring.w;
      }
      ctx.stroke();
    });
  }

  // Segmented rotating ring — the iconic spinning element
  drawSegmentedRing() {
    const ctx = this.ctx;
    const thinkSpeed = this.state === "thinking" ? 4 : 1;
    const r = this.baseR * 0.83;

    ctx.save();
    ctx.translate(this.cx, this.cy);

    // Outer segmented ring — rotates clockwise
    ctx.rotate(this.time * 0.3 * thinkSpeed);
    const segments = 24;
    const gap = 0.03;
    for (let i = 0; i < segments; i++) {
      const start = (i / segments) * Math.PI * 2 + gap;
      const end = ((i + 1) / segments) * Math.PI * 2 - gap;
      const bright = (i % 3 === 0);

      ctx.beginPath();
      ctx.arc(0, 0, r, start, end);
      ctx.strokeStyle = bright ? "rgba(0, 200, 255, 0.35)" : "rgba(0, 160, 255, 0.12)";
      ctx.lineWidth = bright ? 3 : 2;
      ctx.stroke();
    }

    ctx.restore();

    // Inner segmented ring — rotates counter-clockwise
    ctx.save();
    ctx.translate(this.cx, this.cy);
    ctx.rotate(-this.time * 0.2 * thinkSpeed);

    const innerSegs = 36;
    const innerR = this.baseR * 0.72;
    for (let i = 0; i < innerSegs; i++) {
      const start = (i / innerSegs) * Math.PI * 2 + 0.02;
      const end = ((i + 1) / innerSegs) * Math.PI * 2 - 0.02;

      ctx.beginPath();
      ctx.arc(0, 0, innerR, start, end);
      ctx.strokeStyle = (i % 4 === 0) ? "rgba(0, 200, 255, 0.25)" : "rgba(0, 150, 255, 0.08)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    ctx.restore();
  }

  // Inner detail ring with data-like markings
  drawInnerDetailRing() {
    const ctx = this.ctx;
    const r = this.baseR * 0.5;

    ctx.save();
    ctx.translate(this.cx, this.cy);
    ctx.rotate(this.time * 0.15);

    // Dashed circle
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.setLineDash([4, 6]);
    ctx.strokeStyle = "rgba(0, 180, 255, 0.15)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);

    // Small notches
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r * 0.9, Math.sin(a) * r * 0.9);
      ctx.lineTo(Math.cos(a) * r * 1.1, Math.sin(a) * r * 1.1);
      ctx.strokeStyle = "rgba(0, 200, 255, 0.2)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    ctx.restore();

    // Innermost solid ring
    ctx.beginPath();
    ctx.arc(this.cx, this.cy, this.baseR * 0.42, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(0, 170, 255, 0.12)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Glowing core center
  drawCoreGlow() {
    const isListening = this.state === "listening";
    const breathe = Math.sin(this.time * 1.2) * 0.03;
    const speak = this.state === "speaking" ? this.audioLevel * 0.15 : 0;
    const listen = isListening ? 0.15 + Math.sin(this.time * 4) * 0.08 : 0;
    const r = this.baseR * (0.38 + breathe + speak + listen);

    // Wide glow — much brighter when listening
    const g1 = this.ctx.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, r * 2.5);
    if (isListening) {
      g1.addColorStop(0, "rgba(40, 220, 255, 0.45)");
      g1.addColorStop(0.5, "rgba(20, 150, 255, 0.15)");
      g1.addColorStop(1, "rgba(0,0,0,0)");
    } else {
      g1.addColorStop(0, "rgba(40, 170, 255, 0.2)");
      g1.addColorStop(0.5, "rgba(20, 100, 220, 0.05)");
      g1.addColorStop(1, "rgba(0,0,0,0)");
    }
    this.ctx.fillStyle = g1;
    this.ctx.beginPath();
    this.ctx.arc(this.cx, this.cy, r * 2.5, 0, Math.PI * 2);
    this.ctx.fill();

    // Core bright center — much brighter when listening
    const g2 = this.ctx.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, r);
    if (isListening) {
      const pulse = 0.7 + Math.sin(this.time * 5) * 0.2;
      g2.addColorStop(0, `rgba(220, 250, 255, ${pulse})`);
      g2.addColorStop(0.3, "rgba(80, 210, 255, 0.5)");
      g2.addColorStop(0.7, "rgba(30, 150, 255, 0.2)");
      g2.addColorStop(1, "rgba(0,0,0,0)");
    } else {
      g2.addColorStop(0, "rgba(180, 230, 255, 0.6)");
      g2.addColorStop(0.3, "rgba(60, 180, 255, 0.3)");
      g2.addColorStop(0.7, "rgba(20, 120, 255, 0.1)");
      g2.addColorStop(1, "rgba(0,0,0,0)");
    }
    this.ctx.fillStyle = g2;
    this.ctx.beginPath();
    this.ctx.arc(this.cx, this.cy, r, 0, Math.PI * 2);
    this.ctx.fill();

    // Listening indicator — pulsing outer ring
    if (isListening) {
      const pulseR = this.baseR * (1.2 + Math.sin(this.time * 3) * 0.05);
      const pulseAlpha = 0.15 + Math.sin(this.time * 3) * 0.1;
      this.ctx.beginPath();
      this.ctx.arc(this.cx, this.cy, pulseR, 0, Math.PI * 2);
      this.ctx.strokeStyle = `rgba(0, 255, 255, ${pulseAlpha})`;
      this.ctx.lineWidth = 3;
      this.ctx.stroke();
    }
  }

  // Center text — "D.E.A.G.Z" in the style of "J.A.R.V.I.S."
  drawCenterText() {
    const ctx = this.ctx;
    const pulse = Math.sin(this.time * 2) * 0.05;
    const alpha = 0.85 + pulse;

    // Main title
    ctx.font = `500 ${this.baseR * 0.15}px 'Orbitron', sans-serif`;
    ctx.letterSpacing = `${this.baseR * 0.02}px`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    // Text glow
    ctx.shadowColor = "rgba(0, 180, 255, 0.8)";
    ctx.shadowBlur = 20;
    ctx.fillStyle = `rgba(180, 230, 255, ${alpha})`;
    ctx.fillText("D . E . A . G . Z", this.cx, this.cy);

    // Second pass for crispness
    ctx.shadowBlur = 0;
    ctx.fillStyle = `rgba(200, 240, 255, ${alpha * 0.9})`;
    ctx.fillText("D . E . A . G . Z", this.cx, this.cy);

    // Subtitle
    ctx.font = `300 ${this.baseR * 0.05}px 'Rajdhani', sans-serif`;
    ctx.fillStyle = `rgba(0, 180, 255, ${alpha * 0.4})`;
    ctx.fillText("PERSONAL INTELLIGENCE SYSTEM", this.cx, this.cy + this.baseR * 0.14);

    // Thin lines flanking the text
    const lineW = this.baseR * 0.3;
    const lineY = this.cy + this.baseR * 0.06;
    ctx.beginPath();
    ctx.moveTo(this.cx - lineW, lineY);
    ctx.lineTo(this.cx - this.baseR * 0.08, lineY);
    ctx.strokeStyle = `rgba(0, 180, 255, 0.3)`;
    ctx.lineWidth = 0.5;
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(this.cx + this.baseR * 0.08, lineY);
    ctx.lineTo(this.cx + lineW, lineY);
    ctx.stroke();
  }

  // Corner HUD elements
  drawCornerHUD() {
    const ctx = this.ctx;
    ctx.font = "9px monospace";
    const a = 0.2 + Math.sin(this.time) * 0.05;

    // Top-left
    ctx.fillStyle = `rgba(0, 180, 255, ${a})`;
    ctx.textAlign = "left";
    ctx.fillText("SYS.STATUS: NOMINAL", 20, this.h - 40);
    ctx.fillText("CONN: SECURE", 20, this.h - 26);

    // Top-right
    ctx.textAlign = "right";
    ctx.fillText("TOOLS: 20 ACTIVE", this.w - 20, this.h - 40);
    ctx.fillText("AI.ENGINE: CLAUDE", this.w - 20, this.h - 26);

    // Scanning line indicator
    if (this.state === "thinking") {
      const scanX = this.cx + Math.sin(this.time * 5) * this.baseR;
      ctx.beginPath();
      ctx.moveTo(scanX, this.cy - this.baseR * 1.2);
      ctx.lineTo(scanX, this.cy + this.baseR * 1.2);
      ctx.strokeStyle = "rgba(0, 255, 200, 0.15)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
}
