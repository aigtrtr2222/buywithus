/* =========================================================
   나 혼자 안산다 | Buy With Us — 프론트 동작 (서버 API 연결)
   ========================================================= */

/* ---------- 1. 인트로 : 바구니 호버 → 재료 튀어나옴 → 메인 등장 ---------- */
(() => {
  const intro = document.getElementById('intro');
  const basket = document.getElementById('basket');
  const skip = document.getElementById('introSkip');
  let opened = false;

  function finish() {
    intro.remove();
    document.body.classList.remove('is-locked');
  }

  function open(fast = false) {
    if (opened) return;
    opened = true;
    if (fast) {
      document.body.classList.add('is-revealed');
      intro.classList.add('is-leaving');
      setTimeout(finish, 800);
      return;
    }
    intro.classList.add('is-open');                       // 재료 튀어나옴
    setTimeout(() => intro.classList.add('is-leaving'), 950);        // 인트로 배경 걷힘
    setTimeout(() => document.body.classList.add('is-revealed'), 1050); // 메인 다가옴
    setTimeout(finish, 1900);
  }

  basket.addEventListener('mouseenter', () => open());
  basket.addEventListener('click', () => open());        // 모바일 탭 / 키보드 Enter
  skip.addEventListener('click', () => open(true));
  // 스크롤 휠로도 열리게
  window.addEventListener('wheel', () => open(), { once: true, passive: true });
})();

/* ---------- 2. 헤더 그림자 + 스크롤 등장 + 숫자 카운트 ---------- */
(() => {
  const header = document.querySelector('.header');
  addEventListener('scroll', () => {
    header.classList.toggle('is-scrolled', scrollY > 10);
  }, { passive: true });

  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add('is-in');
      e.target.querySelectorAll('.count').forEach(countUp);
      io.unobserve(e.target);
    });
  }, { threshold: 0.2 });
  document.querySelectorAll('.reveal').forEach((el) => io.observe(el));

  function countUp(el) {
    const to = +el.dataset.to;
    const start = performance.now();
    const dur = 1200;
    (function tick(now) {
      const t = Math.min((now - start) / dur, 1);
      el.textContent = Math.round(to * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick);
    })(start);
  }
})();

/* ---------- 3. 게시판 ---------- */
const CATS = {
  veg:   { label: '채소',       emoji: '🥬' },
  fruit: { label: '과일',       emoji: '🍎' },
  meat:  { label: '정육·수산',  emoji: '🥩' },
  dairy: { label: '계란·유제품', emoji: '🥚' },
  daily: { label: '생필품',     emoji: '🧻' },
};
const AVATARS = ['🧅', '🥕', '🍅', '🥖', '🥦', '🍋', '🥔'];

const H = 3600 * 1000;

/* ---------- 서버 API ---------- */
// 로그인 없이 이 브라우저를 구분하는 무작위 값 (작성자·참여자 확인용)
const TOKEN = (() => {
  const make = () => {
    const a = new Uint8Array(24);
    crypto.getRandomValues(a);
    return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
  };
  try {
    let t = localStorage.getItem('bwu_token');
    if (!t || !/^[A-Za-z0-9_-]{32,128}$/.test(t)) { t = make(); localStorage.setItem('bwu_token', t); }
    return t;
  } catch { return make(); }
})();

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'X-BWU-Token': TOKEN, ...(opts.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof data.error === 'string' ? data.error
      : Array.isArray(data.detail) ? '입력값을 다시 확인해주세요' : '잠시 후 다시 시도해주세요';
    throw new Error(msg);
  }
  return data;
}

let posts = [];
let loaded = false;
let filter = { cat: 'all', q: '', sort: 'deadline' };

const $cards = document.getElementById('cards');
const $empty = document.getElementById('empty');

async function load() {
  try {
    const data = await api('/api/posts');
    posts = data.posts;
    loaded = true;
    if (current) current = posts.find((p) => p.id === current.id) || current;
    render();
  } catch (err) {
    if (!loaded) { $cards.innerHTML = ''; $empty.hidden = false; }
    console.warn('목록을 불러오지 못했어요', err);
  }
}
const upsert = (p) => {
  const i = posts.findIndex((x) => x.id === p.id);
  if (i >= 0) posts[i] = p; else posts.unshift(p);
  return p;
};

const won = (n) => n.toLocaleString('ko-KR');
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDate = (t) => new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(t);

function remaining(t) {
  const diff = t - Date.now();
  if (diff <= 0) return { text: '모집 마감', urgent: false, closed: true };
  const m = Math.floor(diff / 60000);
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
  const text = d > 0 ? `마감 ${d}일 ${h}시간 전` : h > 0 ? `마감 ${h}시간 ${mm}분 전` : `마감 ${mm}분 전`;
  return { text, urgent: diff < 3 * H, closed: false };
}

const perPerson = (p) => Math.ceil(p.price / p.max / 10) * 10;
const isClosed = (p) => p.joined >= p.max || p.deadline <= Date.now();

function render() {
  let list = posts.filter((p) =>
    CATS[p.cat] &&
    (filter.cat === 'all' || p.cat === filter.cat) &&
    (`${p.title} ${p.item} ${p.place} ${p.area}`.toLowerCase().includes(filter.q.toLowerCase()))
  );
  list.sort((a, b) => {
    if (isClosed(a) !== isClosed(b)) return isClosed(a) ? 1 : -1; // 마감된 건 뒤로
    if (filter.sort === 'new') return b.created - a.created;
    if (filter.sort === 'cheap') return perPerson(a) - perPerson(b);
    return a.deadline - b.deadline;
  });

  $empty.hidden = list.length > 0;
  $cards.innerHTML = list.map((p, i) => {
    const r = remaining(p.deadline);
    const closed = isClosed(p);
    const mine = p.mine;
    const pct = Math.round((p.joined / p.max) * 100);
    const btn = mine
      ? `<button class="btn is-joined" data-join="${p.id}" type="button">💬 ${p.isLeader ? '내 모집글' : '오픈채팅'}</button>`
      : closed
        ? `<button class="btn btn--ghost" type="button" disabled>${p.joined >= p.max ? '인원 마감' : '모집 마감'}</button>`
        : `<button class="btn btn--primary" data-join="${p.id}" type="button">참여하기</button>`;

    return `
      <article class="card ${closed && !mine ? 'is-closed' : ''}" data-cat="${p.cat}" style="--i:${i}">
        <div class="card__top">
          <span class="tag">${CATS[p.cat].emoji} ${CATS[p.cat].label}</span>
          <span class="deadline ${r.urgent ? 'is-urgent' : ''}" data-deadline="${p.deadline}">${p.joined >= p.max ? '인원 마감' : r.text}</span>
        </div>
        <h3 class="card__title">${esc(p.title)}</h3>
        <p class="card__item">${esc(p.item)}</p>
        <dl class="card__meta">
          <div><dt>📍</dt><dd>${esc(p.place)}</dd></div>
          <div><dt>🕒</dt><dd>${fmtDate(p.meet)} 만남</dd></div>
        </dl>
        <div class="price">
          <span>총 ${won(p.price)}원 ÷ ${p.max}명</span>
          <strong>${won(perPerson(p))}<small>원/인</small></strong>
        </div>
        <div class="progress">
          <div class="progress__label"><span>모집 현황</span><span><b>${p.joined}</b> / ${p.max}명</span></div>
          <div class="progress__bar"><div class="progress__fill" style="width:${pct}%"></div></div>
        </div>
        <div class="card__foot">
          <span class="leader"><span class="leader__avatar">${AVATARS[p.id % AVATARS.length]}</span><span>리더 <b>${esc(p.leader)}</b></span></span>
          ${btn}
        </div>
      </article>`;
  }).join('');
}

// 마감 카운트다운 1분마다 갱신
setInterval(() => {
  document.querySelectorAll('[data-deadline]').forEach((el) => {
    if (el.textContent === '인원 마감') return;
    const r = remaining(+el.dataset.deadline);
    el.textContent = r.text;
    el.classList.toggle('is-urgent', r.urgent);
    if (r.closed) render();
  });
}, 60000);

// 다른 사람이 올린 글·참여 현황: 30초마다, 그리고 탭으로 돌아올 때 새로고침
setInterval(() => { if (!document.hidden) load(); }, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });

// 필터 / 검색 / 정렬
document.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    document.querySelector('.chip.is-active')?.classList.remove('is-active');
    chip.classList.add('is-active');
    filter.cat = chip.dataset.cat;
    render();
  });
});
document.getElementById('search').addEventListener('input', (e) => { filter.q = e.target.value.trim(); render(); });
document.getElementById('sort').addEventListener('change', (e) => { filter.sort = e.target.value; render(); });

/* ---------- 4. 참여 모달 : 참여하면 오픈채팅 링크 공개 ---------- */
const joinDialog = document.getElementById('joinDialog');
const noShow = document.getElementById('noShowCheck');
const joinBtn = document.getElementById('joinBtn');
const leaveBtn = document.getElementById('leaveBtn');
let current = null;

$cards.addEventListener('click', (e) => {
  const b = e.target.closest('[data-join]');
  if (!b) return;
  current = posts.find((p) => p.id === +b.dataset.join);
  if (current) openJoin();
});

function fillJoin() {
  const p = current;
  document.getElementById('joinCat').textContent = `${CATS[p.cat].emoji} ${CATS[p.cat].label}`;
  document.getElementById('joinTitle').textContent = p.title;
  document.getElementById('joinInfo').innerHTML = `
    <div><dt>물품</dt><dd>${esc(p.item)}</dd></div>
    <div><dt>장소</dt><dd>${esc(p.place)}</dd></div>
    <div><dt>만날 시간</dt><dd>${fmtDate(p.meet)}</dd></div>
    <div><dt>1인 금액</dt><dd>${won(perPerson(p))}원</dd></div>
    <div><dt>모집</dt><dd>${p.joined} / ${p.max}명 · ${remaining(p.deadline).text}</dd></div>
    ${p.memo ? `<div><dt>메모</dt><dd>${esc(p.memo)}</dd></div>` : ''}`;
  document.getElementById('joinConfirm').hidden = p.mine;
  document.getElementById('joinDone').hidden = !p.mine;
  document.getElementById('kakaoLink').href = p.mine && p.kakao ? p.kakao : '#';
  leaveBtn.textContent = p.isLeader ? '모집글 삭제' : '참여 취소';
}

function openJoin() {
  fillJoin();
  noShow.checked = false;
  joinBtn.disabled = true;
  joinDialog.showModal();
}

noShow.addEventListener('change', () => { joinBtn.disabled = !noShow.checked; });

joinBtn.addEventListener('click', async () => {
  if (isClosed(current)) return toast('이미 마감된 공구예요');
  joinBtn.disabled = true;
  try {
    current = upsert(await api(`/api/posts/${current.id}/join`, { method: 'POST' }));
    fillJoin();
    render();
    toast('참여 완료! 오픈채팅 링크가 열렸어요 🎉');
  } catch (err) {
    toast(err.message);
    joinBtn.disabled = !noShow.checked;
    load();
  }
});

leaveBtn.addEventListener('click', async () => {
  const p = current;
  try {
    if (p.isLeader) {
      if (!confirm('모집글을 삭제할까요? 참여한 사람들에게도 사라져요.')) return;
      await api(`/api/posts/${p.id}`, { method: 'DELETE' });
      posts = posts.filter((x) => x.id !== p.id);
      toast('모집글을 삭제했어요');
    } else {
      upsert(await api(`/api/posts/${p.id}/join`, { method: 'DELETE' }));
      toast('참여를 취소했어요');
    }
    joinDialog.close();
    render();
  } catch (err) {
    toast(err.message);
  }
});

/* ---------- 5. 글쓰기 모달 ---------- */
const writeDialog = document.getElementById('writeDialog');
const form = document.getElementById('writeForm');
const formError = document.getElementById('formError');

const toLocalInput = (t) => {
  const d = new Date(t - new Date().getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
};

document.querySelectorAll('[data-open-write]').forEach((b) =>
  b.addEventListener('click', () => {
    form.reset();
    formError.textContent = '';
    try { form.leader.value = localStorage.getItem('bwu_nick') || ''; } catch {}
    form.meet.value = toLocalInput(Date.now() + 26 * H);
    form.deadline.value = toLocalInput(Date.now() + 20 * H);
    writeDialog.showModal();
  })
);
writeDialog.querySelector('[data-close]').addEventListener('click', () => writeDialog.close());
[joinDialog, writeDialog].forEach((d) =>
  d.addEventListener('click', (e) => { if (e.target === d) d.close(); }) // 바깥 클릭 닫기
);

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  form.querySelectorAll('.field').forEach((f) => f.classList.remove('is-invalid'));
  const fd = Object.fromEntries(new FormData(form));
  const fail = (name, msg) => {
    form[name].closest('.field').classList.add('is-invalid');
    form[name].focus();
    formError.textContent = msg;
  };

  for (const name of ['title', 'leader', 'item', 'price', 'max', 'place', 'area', 'meet', 'deadline', 'kakao']) {
    if (!String(fd[name] || '').trim()) return fail(name, '빈 칸을 채워주세요');
  }
  if (!/^https:\/\/open\.kakao\.com\//.test(fd.kakao.trim())) return fail('kakao', '오픈카카오톡 링크(https://open.kakao.com/...)를 넣어주세요');
  const price = Math.round(+fd.price);
  const max = Math.round(+fd.max);
  if (!(price >= 0 && price <= 10000000)) return fail('price', '총 가격은 0원 ~ 1,000만 원 사이로 적어주세요');
  if (!(max >= 2 && max <= 10)) return fail('max', '인원은 2~10명으로 정해주세요');
  const meet = new Date(fd.meet).getTime();
  const deadline = new Date(fd.deadline).getTime();
  if (deadline <= Date.now()) return fail('deadline', '모집 마감 시간은 지금 이후여야 해요');
  if (meet <= deadline) return fail('meet', '만날 시간은 모집 마감 이후여야 해요');

  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  formError.textContent = '';
  try {
    upsert(await api('/api/posts', {
      method: 'POST',
      body: JSON.stringify({
        cat: fd.cat, title: fd.title.trim(), leader: fd.leader.trim(), item: fd.item.trim(),
        price, max, place: fd.place.trim(), area: fd.area.trim(),
        meet, deadline, kakao: fd.kakao.trim(), memo: (fd.memo || '').trim(),
      }),
    }));
    try { localStorage.setItem('bwu_nick', fd.leader.trim()); } catch {}
  } catch (err) {
    formError.textContent = err.message;
    return;
  } finally {
    submit.disabled = false;
  }
  writeDialog.close();
  filter = { ...filter, cat: 'all', q: '' };
  document.getElementById('search').value = '';
  document.querySelector('.chip.is-active')?.classList.remove('is-active');
  document.querySelector('.chip[data-cat="all"]').classList.add('is-active');
  render();
  document.getElementById('board').scrollIntoView();
  toast('모집글이 올라갔어요 🧺');
});

/* ---------- toast ---------- */
let toastTimer;
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('is-show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('is-show'), 2200);
}

load();
