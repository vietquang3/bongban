# 🏓 Bóng bàn – điện thoại là vợt

iPhone dán lên vợt → gửi cảm biến qua WiFi → game chạy trên laptop (Surface 3).

## 1. Build file IPA (không cần Mac)
1. Tạo repo mới trên GitHub, giải nén zip này rồi đẩy TOÀN BỘ lên (nhớ cả thư mục `.github`).
2. Vào tab **Actions** → workflow **Build IPA** → chờ ~3-5 phút (hoặc bấm *Run workflow*).
3. Mở lần chạy xong → mục **Artifacts** → tải `PingPongPaddle-ipa` → giải nén ra `PingPongPaddle.ipa`.

## 2. Cài IPA lên iPhone 7 Plus từ Windows
- Cài iTunes + iCloud bản từ apple.com (không dùng bản Microsoft Store), cài **Sideloadly**.
- Cắm iPhone, kéo `PingPongPaddle.ipa` vào Sideloadly, đăng nhập Apple ID miễn phí → Start.
- Trên iPhone: Cài đặt → Cài đặt chung → Quản lý VPN & thiết bị → Tin cậy.
- Bản cài bằng Apple ID miễn phí hết hạn sau 7 ngày, cài lại là được.

## 3. Chạy game trên laptop
```
cd python
run.bat          (hoặc: pip install pygame  &&  python pingpong_game.py)
```
Game hiển thị IP của laptop ở góc trên. Cho phép Python qua Windows Firewall (mạng riêng) nếu được hỏi.

## 4. Chơi
1. iPhone và laptop cùng một WiFi (hoặc laptop kết nối vào điểm phát WiFi của iPhone).
2. Mở app trên iPhone → nhập IP → BẮT ĐẦU → bấm "Cho phép" truy cập mạng nội bộ.
3. Dán điện thoại lên mặt vợt: **đỉnh máy hướng về đầu vợt**, màn hình quay ra ngoài.
4. Cầm vợt tư thế sẵn sàng → nhấn **SPACE** trên laptop để căn chỉnh.
5. Nghiêng/xoay cổ tay để di chuyển vợt trên màn hình; **vung mạnh** để đánh mạnh và sâu (nhưng dễ lỗi hơn).
   Giao bóng: đưa vợt vào quả bóng rồi vung. Điện thoại rung khi bạn chạm bóng.

Nếu vợt đi sai chiều: `I` đảo trái-phải, `O` đảo lên-xuống, `T` đổi trục, `[` `]` chỉnh độ nhạy.
Không có điện thoại vẫn test được bằng chuột (click = đập mạnh).

Lưu ý: cảm biến chỉ đo xoay và gia tốc, không đo vị trí tay, nên vợt trên màn hình di chuyển theo góc cổ tay.
