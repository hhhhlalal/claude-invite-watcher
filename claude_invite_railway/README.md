# Claude Invite Watcher — Railway

Hướng dẫn triển khai đầy đủ: [README ở gốc repo](../README.md).

Nếu deploy từ repo hiện tại, để Railway Root Directory trống hoặc `/` để sử dụng Dockerfile ở gốc. Thư mục này vẫn có Dockerfile riêng nếu bạn đã đặt Root Directory là `/claude_invite_railway`.

Chạy `export_login.bat` tại đây để xuất phiên X. Không upload file `X_STORAGE_STATE_B64.txt` lên GitHub hoặc gửi vào chat.

Từ gốc repo, chạy test bằng:

```bash
python -m unittest discover -s claude_invite_railway -v
```

Xem mục Test trong README gốc để chạy thêm Chromium/Docker.
