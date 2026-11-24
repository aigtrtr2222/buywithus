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
      ? `<button class="btn is-joined" data-join="${p.id}" type="button">🧺 ${p.isLeader ? '내 모집글' : '수다방'}</button>`
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

/* ---------- 4. 참여 모달 : 참여하면 수다방 입장 ---------- */
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
  const $kakao = document.getElementById('kakaoLink');
  $kakao.hidden = !(p.mine && p.kakao);
  $kakao.href = p.mine && p.kakao ? p.kakao : '#';
  leaveBtn.textContent = p.isLeader ? '모집글 삭제' : '참여 취소';
}

function openJoin() {
  fillJoin();
  noShow.checked = false;
  joinBtn.disabled = true;
  joinDialog.showModal();
}

noShow.addEventListener('change', () => { joinBtn.disabled = !noShow.checked; });
document.getElementById('openRoomBtn').addEventListener('click', () => {
  joinDialog.close();
  Chat.open(current.id);
});

joinBtn.addEventListener('click', async () => {
  if (isClosed(current)) return toast('이미 마감된 공구예요');
  joinBtn.disabled = true;
  try {
    current = upsert(await api(`/api/posts/${current.id}/join`, { method: 'POST' }));
    fillJoin();
    render();
    toast('참여 완료! 수다방이 열렸어요 🎉');
    Chat.refresh();
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
    Chat.forget(p.id);
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

  for (const name of ['title', 'leader', 'item', 'price', 'max', 'place', 'area', 'meet', 'deadline']) {
    if (!String(fd[name] || '').trim()) return fail(name, '빈 칸을 채워주세요');
  }
  if (fd.kakao.trim() && !/^https:\/\/open\.kakao\.com\//.test(fd.kakao.trim())) return fail('kakao', '오픈카카오톡 링크는 https://open.kakao.com/... 형식이어야 해요 (비워둬도 돼요)');
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
  toast('모집글이 올라갔어요 🧺 수다방도 열렸어요');
  Chat.refresh();
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


/* ---------- 6. 공구 수다방 : 모집글마다 참여자끼리만 쓰는 채팅 ---------- */
const Chat = (() => {
  const $chat = document.getElementById('chat');
  const $fab = document.getElementById('chatFab');
  const $bag = document.getElementById('chatBag');
  const $back = document.getElementById('chatBack');
  const $title = document.getElementById('chatTitle');
  const $sub = document.getElementById('chatSub');
  const $members = document.getElementById('chatMembers');
  const $rooms = document.getElementById('chatRooms');
  const $list = document.getElementById('chatList');
  const $form = document.getElementById('chatForm');
  const $input = document.getElementById('chatInput');
  const $badge = document.getElementById('chatBadge');
  const $send = $form.querySelector('.chat__send');

  let rooms = [];
  let room = null;        // 지금 열려 있는 방 id
  let lastId = 0;         // 열린 방에서 받은 마지막 메시지 id
  let lastAuthor = null;  // 같은 사람이 연달아 말하면 프로필 생략
  let busy = false;
  const isOpen = () => !$bag.hidden;
  const fmtTime = (t) => new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false }).format(t);

  // 방마다 어디까지 읽었는지 (이 브라우저에만 저장)
  let read = {};
  try { read = JSON.parse(localStorage.getItem('bwu_read') || '{}') || {}; } catch {}
  const markRead = (id, msgId) => {
    if ((read[id] || 0) >= msgId) return;
    read[id] = msgId;
    try { localStorage.setItem('bwu_read', JSON.stringify(read)); } catch {}
  };
  const isUnread = (r) => r.last && !r.last.mine && r.last.id > (read[r.id] || 0) && r.id !== room;

  function paintBadge() {
    const n = rooms.filter(isUnread).length;
    $badge.hidden = n === 0;
    $badge.textContent = n;
    $chat.hidden = rooms.length === 0 && !isOpen();
  }

  /* ----- 방 목록 ----- */
  function paintRooms() {
    if (!rooms.length) {
      $rooms.innerHTML = '<li class="chat__empty">아직 참여한 공구가 없어요.<br>공구에 참여하면 여기서 같이 사는 사람들과 이야기해요 🧺</li>';
      return;
    }
    $rooms.innerHTML = rooms.map((r) => {
      const last = r.last
        ? (r.last.kind === 'sys' ? r.last.text : `${r.last.mine ? '나' : r.last.name}: ${r.last.text}`)
        : '아직 대화가 없어요';
      return `
        <li><button class="room" type="button" data-room="${r.id}">
          <span class="room__ico" aria-hidden="true">${CATS[r.cat]?.emoji || '🧺'}</span>
          <span class="room__main">
            <span class="room__title">${r.isLeader ? '👑 ' : ''}${esc(r.title)}</span>
            <span class="room__last">${esc(last)}</span>
          </span>
          <span class="room__meta">
            <span>${r.joined}/${r.max}명</span>
            ${isUnread(r) ? '<span class="room__dot" aria-label="새 메시지"></span>' : ''}
          </span>
        </button></li>`;
    }).join('');
  }

  async function refresh() {
    try {
      rooms = (await api('/api/rooms')).rooms;
    } catch (err) {
      return console.warn('수다방 목록을 불러오지 못했어요', err);
    }
    // 처음 보는 방의 입장·개설 안내는 '새 메시지'로 치지 않음 (내가 방금 만들거나 들어간 방)
    rooms.forEach((r) => { if (!(r.id in read) && r.last?.kind === 'sys') markRead(r.id, r.last.id); });
    if (room && !rooms.some((r) => r.id === room)) {   // 방이 사라짐 (삭제·나감)
      showList();
      toast('수다방이 닫혔어요');
    }
    if (!room) paintRooms();
    paintBadge();
  }

  function showList() {
    room = null;
    $title.textContent = '내 공구 수다방';
    $sub.textContent = '참여한 공구 사람들끼리만 보여요';
    $back.hidden = true;
    $members.hidden = true;
    $list.hidden = true;
    $form.hidden = true;
    $rooms.hidden = false;
    paintRooms();
    paintBadge();
  }

  /* ----- 방 안 ----- */
  function paintMembers(members) {
    const me = members.find((m) => m.me);
    if (me) $sub.innerHTML = `나는 ${esc(me.emoji)} <b>${esc(me.name)}</b> · ${members.length}명`;
    $members.innerHTML = members.map((m) => `
      <li class="${m.me ? 'is-me' : ''}" title="${esc(m.name)}">
        <span class="ava" aria-hidden="true">${esc(m.emoji)}</span>${esc(m.name)}${m.leader ? '<span class="msg__crown" aria-label="리더">👑</span>' : ''}
      </li>`).join('');
  }

  function append(msgs) {
    const fresh = msgs.filter((m) => m.id > lastId);
    if (!fresh.length) return;
    const nearBottom = $list.scrollHeight - $list.scrollTop - $list.clientHeight < 80;
    $list.insertAdjacentHTML('beforeend', fresh.map((m) => {
      lastId = Math.max(lastId, m.id);
      if (m.kind === 'sys') {
        lastAuthor = null;
        return `<li class="msg-sys">${esc(m.text)}</li>`;
      }
      const author = `${m.name}|${m.mine}`;
      const cont = author === lastAuthor;
      lastAuthor = author;
      return `
        <li class="msg ${m.mine ? 'is-mine' : ''} ${cont ? 'is-cont' : ''}">
          <span class="msg__ava" aria-hidden="true">${esc(m.emoji)}</span>
          <div class="msg__body">
            <span class="msg__name">${esc(m.name)}${m.leader ? '<span class="msg__crown" aria-label="리더">👑</span>' : ''}</span>
            <p class="msg__bubble">${esc(m.text)}</p>
            <time class="msg__time">${fmtTime(m.ts)}</time>
          </div>
        </li>`;
    }).join(''));
    if (nearBottom || fresh.some((m) => m.mine)) $list.scrollTop = $list.scrollHeight;
    markRead(room, lastId);
  }

  async function pollRoom() {
    if (!room || busy) return;
    busy = true;
    const id = room;
    try {
      const data = await api(`/api/posts/${id}/chat?after=${lastId}`);
      if (id !== room) return;
      paintMembers(data.members);
      append(data.messages);
    } catch (err) {
      if (id === room) { toast(err.message); showList(); refresh(); }
    } finally {
      busy = false;
    }
  }

  async function enter(id) {
    let r = rooms.find((x) => x.id === id);
    if (!r) { await refresh(); r = rooms.find((x) => x.id === id); }
    if (!r) return toast('참여한 공구의 수다방만 열 수 있어요');
    room = id;
    lastId = 0;
    lastAuthor = null;
    $title.textContent = r.title;
    $sub.textContent = '불러오는 중…';
    $back.hidden = false;
    $rooms.hidden = true;
    $members.hidden = false;
    $members.innerHTML = '';
    $list.hidden = false;
    $list.innerHTML = '';
    $form.hidden = false;
    await pollRoom();
    $list.scrollTop = $list.scrollHeight;
    paintBadge();
    if (matchMedia('(hover: hover)').matches) $input.focus();
  }

  function setOpen(open) {
    $bag.hidden = !open;
    $fab.setAttribute('aria-expanded', String(open));
    if (!open) { room = null; paintBadge(); $fab.focus(); }
  }

  async function open(id) {
    $chat.hidden = false;
    setOpen(true);
    if (id) await enter(id);
    else if (rooms.length === 1) await enter(rooms[0].id);   // 방이 하나면 바로 입장
    else { showList(); refresh(); }
  }

  $fab.addEventListener('click', () => (isOpen() ? setOpen(false) : open()));
  document.getElementById('chatClose').addEventListener('click', () => setOpen(false));
  $back.addEventListener('click', () => { showList(); refresh(); });
  $bag.addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); });
  $rooms.addEventListener('click', (e) => {
    const b = e.target.closest('[data-room]');
    if (b) enter(+b.dataset.room);
  });

  $form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = $input.value.trim();
    if (!text || !room) return;
    $send.disabled = true;
    try {
      const id = room;
      const m = await api(`/api/posts/${id}/chat`, { method: 'POST', body: JSON.stringify({ text }) });
      $input.value = '';
      await pollRoom();   // 그사이 다른 사람 메시지 먼저 붙이고
      if (id === room) append([m]);
    } catch (err) {
      toast(err.message);
    } finally {
      $send.disabled = false;
      $input.focus();
    }
  });

  // 방이 열려 있으면 3초마다, 아니면 15초마다 방 목록(새 메시지 표시) 확인
  let tick = 0;
  setInterval(() => {
    tick += 1;
    if (document.hidden) return;
    if (room && isOpen()) pollRoom();
    else if (tick % 5 === 0) refresh();
  }, 3000);
  refresh();

  return {
    open,
    refresh,
    forget(id) {
      delete read[id];
      try { localStorage.setItem('bwu_read', JSON.stringify(read)); } catch {}
      if (room === id) showList();
      refresh();
    },
  };
})();

load();
