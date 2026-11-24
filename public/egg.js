/* =========================================================
   🥚 이스터에그 : 바구니 합치기
   장바구니를 열 때 10% 확률로 등장. 같은 과일·채소끼리 닿으면 한 단계 큰 것으로 합쳐짐.
   물리 엔진: Matter.js 0.20.0 (MIT, vendor/ 에 포함)
   ========================================================= */
(() => {
  const TIERS = [
    { e: '🫐', n: '블루베리', r: 15, c: '#C9CDF2' },
    { e: '🍒', n: '체리',     r: 20, c: '#F6C6CC' },
    { e: '🍓', n: '딸기',     r: 26, c: '#F9CFCB' },
    { e: '🍋', n: '레몬',     r: 32, c: '#FBEBA8' },
    { e: '🧅', n: '양파',     r: 38, c: '#F1DCC7' },
    { e: '🍅', n: '토마토',   r: 45, c: '#F7C3B4' },
    { e: '🍎', n: '사과',     r: 52, c: '#F5BDBD' },
    { e: '🥦', n: '브로콜리', r: 60, c: '#D2E6BE' },
    { e: '🍍', n: '파인애플', r: 68, c: '#F6E2A6' },
    { e: '🥬', n: '배추',     r: 77, c: '#DDEFC9' },
    { e: '🎃', n: '호박',     r: 88, c: '#F8D2A6' },
  ];
  const W = 360, H = 540, DANGER_Y = 92, DROP_Y = 46, WALL = 60;
  const SPAWN_MAX = 4;            // 처음 떨어뜨릴 수 있는 건 레몬까지
  const COOLDOWN = 450;
  const FONT = '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';

  let built = false, dlg, cv, ctx, $score, $best, $next, $over, $overScore;
  let engine, raf = 0, last = 0, acc = 0;
  let aimX = W / 2, cur = 0, next = 0, canDrop = true, score = 0, best = 0, over = false;
  let dangerMs = 0, pops = [], pending = [], noMerge = false;

  const rand = () => Math.floor(Math.random() * SPAWN_MAX);
  try { best = +localStorage.getItem('bwu_egg_best') || 0; } catch {}

  function build() {
    built = true;
    dlg = document.createElement('dialog');
    dlg.className = 'modal egg';
    dlg.id = 'eggDialog';
    dlg.innerHTML = `
      <div class="modal__box egg__box">
        <button class="modal__x" type="button" data-egg-close aria-label="닫기">×</button>
        <p class="egg__tag">🥚 EASTER EGG 발견!</p>
        <h3>바구니 합치기</h3>
        <p class="egg__desc">장바구니를 열 때 <b>10% 확률</b>로만 나타나는 숨은 게임이에요.
          같은 과일·채소끼리 닿으면 한 단계 큰 걸로 합쳐져요. <b>🎃 호박</b>까지 키워보세요!</p>
        <div class="egg__hud">
          <span>점수 <b id="eggScore">0</b></span>
          <span>최고 <b id="eggBest">0</b></span>
          <span class="egg__next">다음 <b id="eggNext"></b></span>
        </div>
        <div class="egg__stage">
          <canvas width="${W}" height="${H}" aria-label="게임 화면: 좌우로 움직여 위치를 정하고 눌러서 떨어뜨리기"></canvas>
          <div class="egg__over" hidden>
            <p>바구니가 넘쳤어요! 🧺</p>
            <strong id="eggOverScore">0</strong>
            <button class="btn btn--primary btn--sm" type="button" data-egg-restart>다시 하기</button>
          </div>
        </div>
        <ol class="egg__ladder" aria-label="합쳐지는 순서">${TIERS.map((t) => `<li title="${t.n}">${t.e}</li>`).join('')}</ol>
        <p class="egg__help">PC: 마우스로 위치 → 클릭 · ← → 이동, 스페이스 떨어뜨리기 &nbsp;|&nbsp; 폰: 손가락으로 끌고 떼면 떨어져요</p>
        <div class="egg__actions">
          <button class="btn btn--ghost btn--sm" type="button" data-egg-restart>처음부터</button>
          <button class="btn btn--primary btn--sm" type="button" data-egg-close>사이트 구경하러 가기</button>
        </div>
      </div>`;
    document.body.appendChild(dlg);
    cv = dlg.querySelector('canvas');
    ctx = cv.getContext('2d');
    $score = dlg.querySelector('#eggScore');
    $best = dlg.querySelector('#eggBest');
    $next = dlg.querySelector('#eggNext');
    $over = dlg.querySelector('.egg__over');
    $overScore = dlg.querySelector('#eggOverScore');

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    dlg.querySelectorAll('[data-egg-close]').forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.querySelectorAll('[data-egg-restart]').forEach((b) => b.addEventListener('click', reset));
    dlg.addEventListener('close', stop);

    const toX = (e) => {
      const rect = cv.getBoundingClientRect();
      return ((e.clientX - rect.left) / rect.width) * W;
    };
    cv.addEventListener('pointermove', (e) => { aimX = toX(e); });
    cv.addEventListener('pointerdown', (e) => { aimX = toX(e); cv.setPointerCapture(e.pointerId); });
    cv.addEventListener('pointerup', (e) => { aimX = toX(e); drop(); });
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') { aimX -= 14; e.preventDefault(); }
      else if (e.key === 'ArrowRight') { aimX += 14; e.preventDefault(); }
      else if ((e.key === ' ' || e.key === 'Enter') && e.target.tagName !== 'BUTTON') { drop(); e.preventDefault(); }
    });
  }

  function makeEngine() {
    const { Engine, Bodies, Composite, Events } = Matter;
    engine = Engine.create({ gravity: { x: 0, y: 1.1 } });
    const wall = { isStatic: true, friction: 0.3, restitution: 0.1, label: 'wall' };
    Composite.add(engine.world, [
      Bodies.rectangle(W / 2, H + WALL / 2, W + WALL * 2, WALL, wall),
      Bodies.rectangle(-WALL / 2, H / 2, WALL, H * 3, wall),
      Bodies.rectangle(W + WALL / 2, H / 2, WALL, H * 3, wall),
    ]);
    const onHit = (ev) => {
      for (const { bodyA: a, bodyB: b } of ev.pairs) {
        if (a.label !== 'p' || b.label !== 'p' || a.tier !== b.tier) continue;
        if (noMerge || a.merging || b.merging) continue;
        a.merging = b.merging = true;
        pending.push([a, b]);
      }
    };
    Events.on(engine, 'collisionStart', onHit);
    Events.on(engine, 'collisionActive', onHit);
  }

  function spawn(tier, x, y, born = performance.now()) {
    const t = TIERS[tier];
    const body = Matter.Bodies.circle(x, y, t.r, {
      label: 'p', restitution: 0.12, friction: 0.35, frictionStatic: 0.6, density: 0.0012,
    });
    body.tier = tier;
    body.born = born;
    Matter.Composite.add(engine.world, body);
    return body;
  }

  function mergePending() {
    const { Composite } = Matter;
    for (const [a, b] of pending) {
      const x = (a.position.x + b.position.x) / 2;
      const y = (a.position.y + b.position.y) / 2;
      Composite.remove(engine.world, [a, b]);
      const t = a.tier;
      if (t + 1 < TIERS.length) {
        spawn(t + 1, x, y, 0);
        addScore((t + 1) * (t + 2));
      } else {
        addScore(500);   // 🎃 + 🎃 → 사라지며 보너스
      }
      pops.push({ x, y, r: TIERS[Math.min(t + 1, TIERS.length - 1)].r, life: 1, e: TIERS[Math.min(t + 1, TIERS.length - 1)].e });
    }
    pending = [];
  }

  function addScore(n) {
    score += n;
    $score.textContent = score;
    if (score > best) {
      best = score;
      $best.textContent = best;
      try { localStorage.setItem('bwu_egg_best', best); } catch {}
    }
  }

  function clampAim() {
    const r = TIERS[cur].r;
    aimX = Math.max(r + 2, Math.min(W - r - 2, aimX));
  }

  function drop() {
    if (!canDrop || over) return;
    clampAim();
    spawn(cur, aimX, DROP_Y);
    cur = next;
    next = rand();
    $next.textContent = TIERS[next].e;
    canDrop = false;
    setTimeout(() => { canDrop = true; }, COOLDOWN);
  }

  function checkOver(dt) {
    const now = performance.now();
    const high = Matter.Composite.allBodies(engine.world).some((b) =>
      b.label === 'p' && b.born !== undefined && now - b.born > 1200 &&
      b.position.y - TIERS[b.tier].r < DANGER_Y && Math.abs(b.velocity.y) < 0.6);
    dangerMs = high ? dangerMs + dt : 0;
    if (dangerMs > 1800) {
      over = true;
      $overScore.textContent = `${score}점`;
      $over.hidden = false;
      $over.querySelector('button').focus();
    }
  }

  function drawFruit(x, y, r, tier, angle = 0, alpha = 1) {
    const t = TIERS[tier];
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = t.c;
    ctx.fill();
    ctx.font = `${Math.round(r * 1.45)}px ${FONT}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(t.e, 0, r * 0.08);
    ctx.restore();
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    // 종이봉투 속
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#F3E6CB');
    g.addColorStop(1, '#E3C894');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = 'rgba(120,84,40,.08)';
    for (let x = 12; x < W; x += 24) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + 6, H); ctx.stroke(); }

    // 넘침 선
    ctx.setLineDash([8, 6]);
    ctx.strokeStyle = dangerMs > 0 ? 'rgba(200,87,58,.9)' : 'rgba(200,87,58,.35)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, DANGER_Y); ctx.lineTo(W, DANGER_Y); ctx.stroke();
    ctx.setLineDash([]);

    // 조준선 + 들고 있는 것
    if (!over) {
      clampAim();
      ctx.strokeStyle = 'rgba(94,107,59,.35)';
      ctx.setLineDash([3, 7]);
      ctx.beginPath(); ctx.moveTo(aimX, DROP_Y); ctx.lineTo(aimX, H); ctx.stroke();
      ctx.setLineDash([]);
      drawFruit(aimX, DROP_Y, TIERS[cur].r, cur, 0, canDrop ? 1 : 0.45);
    }

    for (const b of Matter.Composite.allBodies(engine.world)) {
      if (b.label === 'p') drawFruit(b.position.x, b.position.y, TIERS[b.tier].r, b.tier, b.angle);
    }

    // 합쳐질 때 반짝
    pops = pops.filter((p) => (p.life -= 0.05) > 0);
    for (const p of pops) {
      ctx.save();
      ctx.globalAlpha = p.life;
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r + (1 - p.life) * 26, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  function loop(t) {
    raf = requestAnimationFrame(loop);
    const dt = Math.min(50, t - (last || t));
    last = t;
    if (!over) {
      acc += dt;
      while (acc >= 1000 / 60) {
        Matter.Engine.update(engine, 1000 / 60);
        if (pending.length) mergePending();
        acc -= 1000 / 60;
      }
      checkOver(dt);
    }
    draw();
  }

  function reset() {
    if (engine) Matter.Engine.clear(engine);
    makeEngine();
    score = 0; over = false; dangerMs = 0; pops = []; pending = []; canDrop = true; noMerge = false;
    cur = rand(); next = rand(); aimX = W / 2;
    $score.textContent = 0;
    $best.textContent = best;
    $next.textContent = TIERS[next].e;
    $over.hidden = true;
    cv.focus?.();
  }

  function stop() {
    cancelAnimationFrame(raf);
    raf = 0;
  }

  function start() {
    if (!built) build();
    reset();
    if (!dlg.open) dlg.showModal();
    last = 0; acc = 0;
    if (!raf) raf = requestAnimationFrame(loop);
  }

  // _fill: 테스트용 — 합치기를 끄고 과일을 잔뜩 부어 넘침(게임 오버) 확인. '처음부터'로 원상복구
  window.BWUEgg = {
    start,
    _fill() {
      noMerge = true;
      let i = 0;
      const t = setInterval(() => {
        if (over || i >= 45) return clearInterval(t);
        spawn(i % 8, 40 + ((i * 97) % 280), DROP_Y);
        i += 1;
      }, 110);
    },
  };
})();
