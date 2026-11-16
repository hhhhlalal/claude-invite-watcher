# Claude Invite Watcher

Theo dõi bài mới trên X chia sẻ link Claude `/duet-invite/`, `/invite/` hoặc nhắc lời mời dùng thử 7 ngày. Gửi thông báo qua ntfy, lưu lịch sử chống trùng, xem kết quả qua trang có mật khẩu. Không cần API X/AI. Không xác nhận được link còn lượt hoặc tài khoản đủ điều kiện nhận.

## Deploy Railway

Repo này giữ mã Python trong `claude_invite_railway/`, có **Dockerfile và railway.json ở gốc**. Railway có thể build trực tiếp từ repo.

1. New Project → GitHub Repository → chọn repo này, nhánh `main`.
2. Để **Root Directory trống hoặc `/`** để dùng Dockerfile ở gốc. Nếu trước đó đã đặt `/claude_invite_railway`, có thể giữ nguyên: thư mục con cũng có Dockerfile riêng. Xóa Start Command/Build Command tùy chỉnh cũ nếu có để dùng Dockerfile.
3. Gắn volume vào service với Mount Path **`/data`**. Chỉ chạy **1 replica**. Không dùng cron deployment hoặc chế độ ngủ/serverless.
4. Thêm các Variables:

| Variable | Nội dung |
| --- | --- |
| `DASHBOARD_PASSWORD` | Mật khẩu riêng ngẫu nhiên, tối thiểu 20 ký tự |
| `NTFY_TOPIC` | Topic riêng khó đoán đã đăng ký trong app ntfy |
| `X_STORAGE_STATE_B64` | Phiên X xuất theo hướng dẫn bên dưới |
| `DATA_DIR` | `/data` (đã mặc định) |
| `NTFY_SERVER` | Tùy chọn, mặc định `https://ntfy.sh` |
| `NTFY_TOKEN` | Tùy chọn nếu máy chủ ntfy dùng xác thực |

5. Deploy → Settings → Networking → Generate Domain. Dùng địa chỉ **HTTPS** được cấp. Không tự đặt PORT; Railway cấp biến này.
6. Mở domain, đăng nhập username **`admin`** và password ở trên. Xem `/status` sau một vòng quét. Chỉ khi quét thành công và điện thoại nhận được thông báo thật mới xác nhận hoàn tất triển khai.

Railway healthcheck `/health` chỉ phục vụ kiểm tra khởi động, không phải giám sát liên tục. App có watchdog riêng, thoát với lỗi nếu worker chết/treo quá hạn để chính sách ON_FAILURE khởi động lại (tối đa 10 lần). Thiếu phiên hoặc X từ chối truy cập được báo trong `/status`, không lặp restart liên tục.

## Xuất phiên X trên Windows

1. Cài Python 3.11+, tải mã nguồn repo rồi giải nén.
2. Mở thư mục `claude_invite_railway`, chạy **`export_login.bat`**.
3. Đăng nhập X trên cửa sổ Chromium mở ra. Sau khi vào Home, quay lại console nhấn Enter.
4. Copy nội dung `X_STORAGE_STATE_B64.txt` vào **Railway Variables**, sau đó redeploy.

File này là phiên đăng nhập, base64 không phải mã hóa. **Không gửi vào chat, GitHub hoặc ảnh chụp**. `.gitignore` giúp tránh commit nhầm khi dùng Git, không bảo vệ khi tự chọn upload trên web. Có thể xóa file cục bộ sau khi nạp. Phiên được làm mới sẽ lưu trong `/data/session-state.json` với quyền chỉ chủ file; không được phục vụ qua HTTP. Nếu thay biến phiên, seed mới thay thế phiên lưu cũ. Nếu X yêu cầu đăng nhập lại, xuất phiên mới và cập nhật biến.

## Trạng thái và thông báo

| Đường dẫn / trạng thái | Ý nghĩa |
| --- | --- |
| `/results` hoặc `/` | 500 kết quả gần nhất, F5 để cập nhật |
| `/status` | Trạng thái quét, lần thành công cuối, số thông báo chờ gửi |
| `/health` | Liveness: worker còn sống và chưa quá hạn; không bảo đảm X truy cập được |
| `/ready` | Có mật khẩu; 200 khi vòng trước hoàn tất tất cả truy vấn và không còn thông báo tồn; ngược lại 503 |
| `waiting_for_*` | Thiếu biến cấu hình tương ứng |
| `scanning` | Đang chạy một vòng |
| `waiting` | Tất cả truy vấn hoàn tất (có thể không có bài phù hợp) |
| `partial_failure` | Chỉ một phần truy vấn hoàn tất |
| `invalid_X_session` | Dữ liệu phiên sai/thiếu auth_token/hết hạn; xuất lại phiên |
| `X_unavailable_check_session` | Không hoàn tất truy vấn nào; xem last_error |
| `error_*` | Lỗi chu kỳ, xem logs; dữ liệu bí mật không được ghi trong thông báo lỗi |

Cài ntfy trên điện thoại, Subscribe topic `NTFY_TOPIC` và server tương ứng. Topic công khai trên ntfy.sh có thể được đọc bởi người biết tên; dùng topic khó đoán hoặc máy chủ có xác thực. Thông báo thất bại được giữ lại để thử tiếp, kể cả khi X lỗi. Một bài có nhiều link mới được gom một thông báo. Lỗi quét/phiên gửi cảnh báo ntfy, tối đa mỗi giờ nếu trạng thái không đổi.

Máy cá nhân có thể tắt sau khi triển khai. Máy chủ vẫn có thể bị X yêu cầu xác minh; tool không vượt CAPTCHA. Khi không thấy bài và cũng không có thông báo “No results”, tool báo không xác định thay vì giả định không có link mới. Không bảo đảm bao phủ mọi bài, thời gian thực, hoặc chạy đủ 30 ngày với $5 trial.

## Test

```bash
pip install -r claude_invite_railway/requirements.txt
python -m unittest discover -s claude_invite_railway -v
```

Mặc định bỏ qua 4 bài test Chromium. Chạy toàn bộ trong image khớp phiên bản Playwright:

```bash
docker build -t invite-watcher-test .
docker run --rm --init --network none -e RUN_BROWSER_TESTS=1 invite-watcher-test python -m unittest discover -s /app -v
```

GitHub Actions chạy unit/HTTP và build Docker + test Chromium trên trang mô phỏng, không dùng tài khoản X, không tốn API/ntfy thật. Đây không phải kiểm thử đăng nhập X hoặc kiểm tra Railway deployment thật. Mở tab Actions để xem kết quả của commit hiện tại.
