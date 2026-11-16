# Claude Invite Watcher — Railway trial

Bản triển khai thử nghiệm. Chưa build Docker hoặc chạy tích hợp trên Railway/X thật. 5 test bộ lọc đạt; Python kiểm tra cú pháp đạt. Không bảo đảm IP máy chủ được X chấp nhận. Hết credit có thể ngừng dịch vụ. Xác minh độ ổn định trước khi mua gói.

## 1. Đưa mã nguồn lên GitHub
Tạo repository PRIVATE mới, ví dụ claude-invite-watcher. Upload nội dung thư mục này ở gốc repository (Dockerfile cùng cấp server.py), KHÔNG upload cả ZIP. Nên upload trước khi xuất phiên đăng nhập.
Không upload X_STORAGE_STATE_B64.txt, .venv, browser_profile, .env hoặc file dữ liệu. Gitignore không bảo vệ khi bạn tự chọn upload file trên web!

## 2. Railway
Ở New Project chọn GitHub Repository, kết nối GitHub và chọn repo vừa tạo. Docker Image là dành cho image đã publish, không phải ZIP/Dockerfile.
Nếu nút GitHub bị vô hiệu hóa, thử kết nối/xác minh GitHub trong tài khoản Railway; quyền Trial có thể khác nhau. Không mua gói chỉ để thử cho đến khi rõ giới hạn.
Thêm volume gắn vào service, mount path /data. Nếu Trial không cho gắn volume, có thể thử không volume nhưng lịch sử chống trùng mất khi redeploy/restart môi trường, gây báo lại.
Settings > Networking > Generate Domain. Dùng URL HTTPS được cấp; PORT do Railway cấp tự động. Chỉ dùng 1 replica. Tắt chế độ serverless/sleep nếu đang bật; worker phải tiếp tục chạy khi không ai mở trang.
Không dùng cron deployment. Service chạy liên tục, nghỉ 5 phút giữa các vòng; Chromium đóng sau mỗi vòng để giảm RAM. Gắn volume trước vòng quét đầu tiên.

## 3. Variables (bí mật)
DASHBOARD_PASSWORD: tự đặt chuỗi ngẫu nhiên tối thiểu 20 ký tự, không dùng lại mật khẩu X.
NTFY_TOPIC: tên topic riêng khó đoán, ví dụ tự tạo 32 ký tự ngẫu nhiên. Cài app ntfy trên điện thoại và Subscribe đúng topic, server https://ntfy.sh.
X_STORAGE_STATE_B64: nội dung file xuất ở bước 4.
DATA_DIR: /data (đã mặc định trong Docker).
Tùy chọn NTFY_SERVER và NTFY_TOKEN nếu dùng ntfy có xác thực.
Topic công khai có thể bị người biết tên đọc; không gửi phiên đăng nhập vào ntfy.

## 4. Xuất phiên X trên Windows
Cài Python 3.11+. Chạy export_login.bat, đăng nhập X trong Chromium được mở. Khi vào Home thành công, quay lại console nhấn Enter. File X_STORAGE_STATE_B64.txt chứa phiên đăng nhập (base64 KHÔNG phải mã hóa).
Chỉ copy nội dung vào biến bí mật X_STORAGE_STATE_B64 của Railway rồi Deploy/Redeploy. Không gửi vào chat, GitHub hoặc ảnh chụp. Sau khi nạp thành công có thể xóa file cục bộ.
Nếu cần đăng nhập lại: chạy lại export_login.bat, thay biến và redeploy. Máy cá nhân chỉ cần mở để thực hiện bước này, không cần mở liên tục.

## 5. Kiểm tra
Mở domain HTTPS, đăng nhập username admin và password DASHBOARD_PASSWORD.
/results: kết quả; F5 để cập nhật.
/status: trạng thái, last_cycle (Unix timestamp), successful_queries.
/health: kiểm tra tiến trình/thread còn chạy, KHÔNG xác nhận X đang truy cập được.
waiting_for_X_STORAGE_STATE_B64 / waiting_for_NTFY_TOPIC: thiếu biến.
scanning: đang quét.
waiting: vòng vừa rồi có ít nhất một truy vấn lấy được bài; chờ vòng mới.
X_unavailable_check_session: không lấy được bài ở cả hai truy vấn. Có thể không có kết quả, phiên hết hạn, bị giới hạn, trang đổi giao diện. Không tự khẳng định là không có invite.
error_*: lỗi chu kỳ; xem Railway logs. Không chia sẻ logs có link invite nếu không muốn lộ.
Thông báo ntfy chỉ gửi kết quả mới; xem /status để kiểm tra tình trạng quét. Chưa có cảnh báo lỗi qua ntfy trong bản này.

## Giới hạn
Chỉ đọc bài hiển thị từ tìm kiếm Latest, tối đa 3 lượt cuộn mỗi truy vấn, mặc định lọc 24 giờ gần nhất. Không đảm bảo tìm hết bài hoặc nhận link trước người khác. Link duet-invite được ghi nhận dù không ghi 7 ngày; hiệu lực/quota/điều kiện tài khoản chưa xác minh. X có thể không chấp nhận browser headless hoặc phiên đổi IP; tool không vượt CAPTCHA.
Dữ liệu chứa session chỉ nằm trong biến bí mật Railway; kết quả và SQLite trong /data. Không mở public database hoặc static serve toàn bộ thư mục /data.
Theo dõi RAM và credit trong Railway. $5 dùng thử không đồng nghĩa chắc chắn chạy đủ 30 ngày. Sau khi deploy cần xác nhận /status, bài mới và thông báo điện thoại thật; hiện bản ZIP chưa được triển khai vào tài khoản của bạn.
