#!/usr/bin/env bash
# First-time setup on Ubuntu 24.04. Idempotent. Run with sudo from the repo root:
#   sudo deploy/bootstrap.sh [new_username]
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Hay chay bang sudo: sudo deploy/bootstrap.sh [ten_user_moi]" >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
NEW_USER="${1:-}"
export DEBIAN_FRONTEND=noninteractive
COMPOSE="docker compose -f deploy/docker-compose.yml --env-file .env"

echo "==> 1. Goi he thong, ufw, fail2ban, unattended-upgrades"
apt-get update -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades openssl cron

if [ -n "$NEW_USER" ] && ! id "$NEW_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$NEW_USER"
  usermod -aG sudo "$NEW_USER"
  if [ -f /root/.ssh/authorized_keys ]; then
    install -d -m 700 -o "$NEW_USER" -g "$NEW_USER" "/home/$NEW_USER/.ssh"
    install -m 600 -o "$NEW_USER" -g "$NEW_USER" /root/.ssh/authorized_keys \
      "/home/$NEW_USER/.ssh/authorized_keys"
  fi
  echo "Da tao user $NEW_USER (hay dat mat khau: sudo passwd $NEW_USER)"
fi

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Disable root password login (key-based root login stays possible).
install -d /etc/ssh/sshd_config.d
printf 'PermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/10-bestone-root.conf
systemctl reload ssh || systemctl reload sshd || true

systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades || true

echo "==> 2. Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  . /etc/os-release
  ARCH="$(dpkg --print-architecture)"
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin
fi
systemctl enable --now docker
if [ -n "$NEW_USER" ]; then usermod -aG docker "$NEW_USER"; fi
OWNER="${SUDO_USER:-${NEW_USER:-root}}"
if [ "$OWNER" != "root" ]; then usermod -aG docker "$OWNER"; fi

echo "==> 3. File .env"
cd "$REPO"
[ -f .env ] || cp .env.example .env
fill_if_empty() {
  # $1 = variable name; sets a random value only when currently empty.
  local current value
  current="$(grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' || true)"
  if [ -z "$current" ]; then
    value="$(openssl rand -hex 32)"
    if grep -qE "^$1=" .env; then
      sed -i "s|^$1=.*|$1=$value|" .env
    else
      printf '%s=%s\n' "$1" "$value" >> .env
    fi
  fi
}
fill_if_empty POSTGRES_PASSWORD
fill_if_empty SESSION_SECRET_KEY
chmod 600 .env
chown "$OWNER:$OWNER" .env
if ! grep -qE '^APP_DOMAIN=.+' .env; then
  echo "CANH BAO: APP_DOMAIN trong .env dang trong. Dien ten mien (nano .env) roi chay lai script." >&2
  exit 1
fi

echo "==> 4. Khoi dong he thong"
$COMPOSE up -d --build
$COMPOSE exec -T app python -m app.knowledge.ingest

echo "==> 5. Mui gio Viet Nam va cron backup hang ngay 02:00"
timedatectl set-timezone Asia/Ho_Chi_Minh || true
mkdir -p "$REPO/backups/weekly"
chown -R "$OWNER:$OWNER" "$REPO/backups"
chmod +x "$REPO/deploy/backup.sh"
CRON_LINE="0 2 * * * cd $REPO && deploy/backup.sh >> backups/backup.log 2>&1"
{ crontab -l 2>/dev/null | grep -vF "deploy/backup.sh" || true; echo "$CRON_LINE"; } | crontab -

DOMAIN="$(grep -E '^APP_DOMAIN=' .env | tail -n1 | cut -d= -f2- | tr -d '\r')"
S3_MISSING=""
for v in BACKUP_S3_ENDPOINT BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY; do
  if ! grep -qE "^$v=.+" .env; then S3_MISSING="$S3_MISSING $v"; fi
done
if [ -n "$S3_MISSING" ]; then
  echo
  echo "!!! CANH BAO QUAN TRONG: backup ngoai VPS CHUA duoc cau hinh."
  echo "!!! Con thieu trong .env:$S3_MISSING"
  echo "!!! Neu khong co, mat VPS la mat toan bo du lieu. Phai dien truoc khi dung that (xem buoc 0b)."
fi

cat <<MSG

Hoan tat. Cac buoc tiep theo (chay bang user $OWNER, KHONG dung sudo):
0. Dang xuat roi dang nhap lai SSH mot lan de user nhan quyen nhom docker.
0b. BAT BUOC: dien BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY
   (va TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID de nhan canh bao) trong .env (nano .env),
   roi chay thu: deploy/backup.sh  (phai bao "uploaded to S3").
1. Dien INITIAL_ADMIN_USERNAME va INITIAL_ADMIN_PASSWORD trong .env (nano .env), roi:
   $COMPOSE up -d app
   $COMPOSE exec app python -m app.cli.create_admin
2. XOA hai dong INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD khoi .env, roi nap lai cau hinh:
   $COMPOSE up -d app
3. Kiem tra: curl https://$DOMAIN/health  (mong doi {"status":"ok",...})
4. Dang nhap thu tai https://$DOMAIN/login, sau do tao tai khoan Ke toan trong dashboard.
5. Dang ky Webhook tren Meta va gui tin thu tu tai khoan tester.
MSG
