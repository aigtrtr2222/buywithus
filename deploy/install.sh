#!/usr/bin/env bash
# Buy With Us 서버 설치/업데이트 (VODA가 돌고 있는 같은 VM에 나란히 올림)
# 사용: cd ~/buywithus && bash deploy/install.sh 내도메인.com
#  - 일반 SSH 계정으로 실행 (sudo 붙이지 말 것)
#  - 기존 Caddyfile(VODA 설정)은 백업 후 그대로 두고, 이 사이트 블록만 추가함
set -euo pipefail

if [[ "$EUID" -eq 0 ]]; then
  echo 'sudo 없이 일반 계정으로 실행하세요.' >&2; exit 1
fi
site="${1:-}"
if [[ ! "$site" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ || "$site" != *.* ]]; then
  echo '사용법: bash deploy/install.sh 내도메인.com  (소문자 도메인)' >&2; exit 1
fi

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$app_dir"
if [[ "$app_dir" =~ [[:space:]\%\"\\] ]]; then
  echo '공백/특수문자 없는 경로에 설치하세요 (예: ~/buywithus).' >&2; exit 1
fi
command -v caddy >/dev/null || { echo 'Caddy가 없습니다. VODA 서버인지 확인하세요.' >&2; exit 1; }
PORT=8001
if ss -ltn "sport = :$PORT" | grep -q LISTEN && ! systemctl is-active --quiet buywithus; then
  echo "포트 $PORT 를 다른 프로그램이 쓰고 있습니다." >&2; exit 1
fi

# 1) 파이썬 환경
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
mkdir -p data && chmod 700 data

sudo -v
server_user="$(id -un)"
stamp="$(date -u +%Y%m%dT%H%M%S)"

# 2) systemd 서비스
sudo tee /etc/systemd/system/buywithus.service >/dev/null <<EOF
[Unit]
Description=Buy With Us FastAPI website
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$server_user
WorkingDirectory=$app_dir
Environment=BWU_DATA_DIR=$app_dir/data
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$app_dir/.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port $PORT --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$app_dir/data

[Install]
WantedBy=multi-user.target
EOF

# 3) Caddy: 기존 설정 유지 + 이 도메인 블록만 추가 (이미 있으면 건드리지 않음)
sudo cp -p /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.backup-$stamp"
if sudo grep -qE "^${site//./\\.}[[:space:]]*\{" /etc/caddy/Caddyfile; then
  echo "Caddyfile에 $site 블록이 이미 있어 그대로 둡니다."
else
  printf '\n%s {\n    reverse_proxy 127.0.0.1:%s\n}\n' "$site" "$PORT" | sudo tee -a /etc/caddy/Caddyfile >/dev/null
fi
if ! sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo 'Caddy 설정 오류 → 백업으로 되돌립니다.' >&2
  sudo cp -p "/etc/caddy/Caddyfile.backup-$stamp" /etc/caddy/Caddyfile
  exit 1
fi

sudo systemctl daemon-reload
sudo systemctl enable buywithus.service >/dev/null
sudo systemctl restart buywithus.service
sudo systemctl reload caddy

for _ in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null \
  || { echo '서버 시작 실패: sudo journalctl -u buywithus -n 50' >&2; exit 1; }

echo
echo "완료! 서버 실행 중. Caddy가 HTTPS 인증서를 받는 데 1~2분 걸릴 수 있어요."
echo "확인: https://$site"
echo "(도메인 DNS의 A 레코드가 이 VM 외부 IP를 가리키고 있어야 인증서가 발급됩니다)"
