#!/usr/bin/env bash
# 백엔드를 리눅스 서버(Azure for Students B1s, 나중에 AWS EC2 등)에 올린다. 맥에서 실행한다.
#
#   infra/server/deploy.sh azureuser@<서버 공인 IP>       # 처음·업데이트 모두 같은 명령 (Oracle은 ubuntu@)
#
# 하는 일
#   1) (처음만) 서버에 Docker·cloudflared 설치
#   2) backend/ 코드와 backend/.env를 서버 /opt/meetingfee 로 복사 (data/·캐시·실험 파일은 안 보냄)
#   3) Docker 이미지를 서버에서 빌드하고 컨테이너 실행 (데이터는 영구 볼륨 meetingfee-data)
#   4) Cloudflare 터널 'meetingfee'를 서버에서 서비스로 실행 → api.jnuai-meetingfee.com 이 서버를 가리킴
# 맥에서 돌던 터널은 끈다(둘 다 켜져 있으면 요청이 나뉘어 간다).
set -euo pipefail
HOST="${1:?사용법: deploy.sh ubuntu@<서버 IP>}"
KEY="${KEY:-$HOME/.ssh/meetingfee_oci}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TUNNEL_ID="$(/opt/homebrew/bin/cloudflared tunnel list -o json 2>/dev/null | python3 -c 'import json,sys;print(next(t["id"] for t in json.load(sys.stdin) if t["name"]=="meetingfee"))')"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new $HOST"

echo "▶ 1) 서버 준비 (Docker·cloudflared)"
$SSH 'bash -s' <<'REMOTE'
set -e
if ! command -v docker >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq docker.io rsync
  sudo usermod -aG docker "$USER"
fi
if ! command -v cloudflared >/dev/null; then
  arch=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb"
  sudo dpkg -i /tmp/cloudflared.deb
fi
sudo mkdir -p /opt/meetingfee /etc/cloudflared && sudo chown "$USER" /opt/meetingfee
# 메모리 1GB 서버(Azure B1s 등): 스왑 2GB를 잡아 Docker 빌드·HWP 미리보기에서 메모리가 모자라지 않게 한다
if [ "$(free -m | awk '/Mem:/{print $2}')" -lt 2000 ] && ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
REMOTE

echo "▶ 2) 코드·설정 복사"
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .venv --exclude data --exclude cache --exclude experiments --exclude samples --exclude tests --exclude '__pycache__' \
  "$ROOT/backend/" "$HOST:/opt/meetingfee/backend/"
scp -q -i "$KEY" "$HOME/.cloudflared/$TUNNEL_ID.json" "$HOST:/tmp/tunnel.json"

echo "▶ 3) 이미지 빌드·컨테이너 실행"
$SSH "bash -s" <<REMOTE
set -e
cd /opt/meetingfee/backend
sudo docker build -q -t meetingfee-backend .
sudo docker rm -f meetingfee >/dev/null 2>&1 || true
sudo docker run -d --name meetingfee --restart unless-stopped -p 127.0.0.1:8000:8000 \
  --env-file .env -e DEV_ENDPOINTS=false -v meetingfee-data:/app/data meetingfee-backend
sleep 5 && curl -fsS http://127.0.0.1:8000/api/health && echo
REMOTE

echo "▶ 4) 터널을 서버에서 실행"
$SSH "bash -s" <<REMOTE
set -e
sudo mv /tmp/tunnel.json /etc/cloudflared/$TUNNEL_ID.json
sudo tee /etc/cloudflared/config.yml >/dev/null <<CFG
tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: api.jnuai-meetingfee.com
    service: http://127.0.0.1:8000
  - service: http_status:404
CFG
sudo cloudflared service install >/dev/null 2>&1 || sudo systemctl restart cloudflared
sudo systemctl enable --now cloudflared >/dev/null
REMOTE
pkill -f "cloudflared tunnel run" || true
sleep 5
curl -fsS https://api.jnuai-meetingfee.com/api/health && echo "  ← 서버 경유 완료"
