# 나 혼자 안산다 | Buy With Us

동네 자취생 식재료 공동구매(1/N) 모집 게시판. FastAPI + SQLite, VODA와 같은 Google Cloud VM에서 Caddy(HTTPS) 뒤에 돌아감.

## 구조

```
public/            화면 (index.html, style.css, script.js, assets/)
server.py          API + 정적 파일 서빙, DB는 data/buywithus.sqlite3
deploy/install.sh  서버 설치/업데이트 (systemd 'buywithus', 포트 8001, Caddy 블록 추가)
tests/             test_api.py (pytest), browser_check.py (실제 Chrome)
```

## 동작 방식

- 로그인 없음. 브라우저마다 무작위 토큰을 localStorage에 만들어 작성자/참여자를 구분 (서버엔 해시만 저장).
- **공구 수다방**: 모집글마다 참여자끼리만 쓰는 채팅방 (오른쪽 아래 종이봉투). 참여 안 한 사람은 API에서도 403.
  - 닉네임은 방마다 랜덤 "형용사 + 야채/과일", 같은 방 안에서는 야채·과일이 안 겹침. 리더는 👑.
  - 입장·퇴장 안내 자동, 방마다 최근 300개 보관, 만남 후 3일까지 열림. 글 삭제 시 방도 삭제.
- 오픈채팅 링크는 **선택**이며 넣으면 참여한 사람에게만 서버가 내려줌.
- 인원 초과 참여 방지(DB 잠금), 작성자만 글 삭제, 리더는 참여 취소 불가.
- 만남 시간 하루 지난 글은 목록에서 숨김. IP당 글 5개/시간, 참여 30회/시간 제한.
- 다른 브라우저/기기에서 접속하면 다른 사람으로 인식됨 (브라우저 데이터 지우면 내 글 삭제 권한도 사라짐).

## 내 컴퓨터에서 실행

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn server:app --port 8001
# http://127.0.0.1:8001
```

테스트: `.venv\Scripts\python -m pip install pytest httpx playwright` 후 `.venv\Scripts\python -m pytest tests` / `.venv\Scripts\python tests\browser_check.py`

## 서버 배포 (처음 한 번)

1. 도메인 DNS 설정에서 **A 레코드**를 VM 외부 IP로 지정 (`@`, 필요하면 `www`도).
   외부 IP 확인: Cloud Shell에서 `gcloud compute instances list`
2. 코드를 VM의 `~/buywithus`로 올림 (GitHub 저장소에서 `git clone`, 또는 zip 업로드 후 압축 해제)
3. VM에서:
   ```bash
   cd ~/buywithus && bash deploy/install.sh 내도메인.com
   ```

## 업데이트

```bash
cd ~/buywithus && git pull --ff-only && sudo systemctl restart buywithus
```

## 주의

- VODA의 `deploy/enable-server.sh`는 Caddyfile을 **통째로 덮어씀**. 그걸 다시 돌리면 이 사이트 블록이 사라지니, 그 후엔 `bash deploy/install.sh 내도메인.com`을 한 번 더 실행.
- DB 백업: `cp ~/buywithus/data/buywithus.sqlite3 ~/bwu-backup-$(date +%F).sqlite3`
- 로그: `sudo journalctl -u buywithus -n 50`
