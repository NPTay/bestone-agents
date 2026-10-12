# Quay lại phiên bản trước (rollback)

Mọi lệnh chạy trên VPS, trong thư mục repo (ví dụ `cd ~/bestone-agents`).
Đặt tên ngắn cho lệnh compose:

```bash
DC="docker compose -f deploy/docker-compose.yml --env-file .env"
```

## 1. Xem các phiên bản có thể quay lại

```bash
git fetch --tags
git tag --list --sort=-creatordate | head -20
git log --oneline -20
```

## 2. Khôi phục DB từ bản backup trên VPS (làm TRƯỚC khi dựng lại bản cũ)

Chỉ cần khi bản cũ có schema khác bản hiện tại. Nếu không, bỏ qua sang bước 3.
Cảnh báo: lệnh này ghi đè dữ liệu hiện tại. Dừng app trước (db vẫn chạy).

```bash
ls -lt backups/ backups/weekly/
$DC stop app
set -a; . ./.env; set +a
$DC exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < backups/bestone-YYYYmmdd-HHMM.dump
```

Nếu mất cả VPS hoặc thư mục `backups/`, tải bản dump từ S3 về trước (mục 4).

## 3. Quay lại mã nguồn cũ và dựng lại

Lưu ý: nếu bạn đã khôi phục DB cũ ở bước 2 thì PHẢI dựng đúng bản mã tương ứng;
nếu dựng bản mã cũ khi DB còn schema mới, `app` có thể lỗi và khởi động lại liên tục
cho đến khi khôi phục DB.

```bash
git checkout <tag-hoac-commit>
$DC up -d --build
$DC logs --tail=50 app
curl -s https://<ten-mien>/health
```

Migration Alembic chạy tự động khi `app` khởi động.
Quay về bản mới nhất: `git checkout main && git pull && $DC up -d --build`.

## 4. Tải backup từ S3

Đặt lifecycle rule (giữ bản theo thời hạn mong muốn) trên bucket phía nhà cung cấp,
vì `backup.sh` chỉ upload và không xóa bản cũ trên S3.

```bash
set -a; . ./.env; set +a
export AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
S3OPTS="-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION=us-east-1 -e AWS_REQUEST_CHECKSUM_CALCULATION=when_required -e AWS_RESPONSE_CHECKSUM_VALIDATION=when_required"
docker run --rm $S3OPTS amazon/aws-cli s3 ls "s3://$BACKUP_S3_BUCKET/" --endpoint-url "$BACKUP_S3_ENDPOINT"
mkdir -p backups
docker run --rm $S3OPTS -v "$PWD/backups:/backups" amazon/aws-cli s3 cp "s3://$BACKUP_S3_BUCKET/bestone-YYYYmmdd-HHMM.dump" /backups/ --endpoint-url "$BACKUP_S3_ENDPOINT"
```

Sau đó làm bước 2 với file vừa tải về, rồi bước 3. Trên VPS mới: chạy
`sudo deploy/bootstrap.sh` trước.

## 5. Thử khôi phục vào DB tạm (mỗi tháng một lần)

```bash
set -a; . ./.env; set +a
$DC exec -T db createdb -U "$POSTGRES_USER" restore_test
$DC exec -T db pg_restore -U "$POSTGRES_USER" -d restore_test --no-owner < backups/bestone-YYYYmmdd-HHMM.dump
$DC exec -T db psql -U "$POSTGRES_USER" -d restore_test -c "select count(*) from users;"
$DC exec -T db dropdb -U "$POSTGRES_USER" restore_test
```

## Ghi chú bảo mật (hoãn sang giai đoạn sau)

Ở Phase 0, `POSTGRES_USER=bestone_app` là chủ DB và theo image Postgres chính thức
cũng là superuser. Cần tách thành role ứng dụng không phải superuser (theo `docs/04`
"Bảo vệ DB") ở giai đoạn sau.
