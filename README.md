# Bot Điểm Danh Telegram

Bot Telegram để theo dõi thời gian nghỉ của nhân viên trong nhóm.

## Tính năng

- Theo dõi các hoạt động: Ra ngoài, Hút thuốc, Vệ sinh cá nhân (1), Vệ sinh cá nhân (2), Lấy cơm, Cất bát
- Tự động kiểm tra thời gian vi phạm
- Lưu thông tin vi phạm vào file Excel riêng cho từng nhóm
- Gửi báo cáo cho admin
- Hệ thống quản lý admin và superadmin

## Cài đặt

1. Cài đặt các thư viện cần thiết:
```bash
pip install -r requirements.txt
```

2. Tạo file `.env` với nội dung:
```
TELEGRAM_TOKEN=your_telegram_bot_token_here
INITIAL_SUPERADMIN_ID=your_telegram_user_id_here
```

Lưu ý:
- `TELEGRAM_TOKEN`: Token của bot được lấy từ BotFather
- `INITIAL_SUPERADMIN_ID`: ID của người dùng Telegram sẽ là superadmin đầu tiên
  - Để lấy ID Telegram, bạn có thể:
    1. Gửi tin nhắn cho @userinfobot
    2. Hoặc sử dụng @RawDataBot
    3. Hoặc thêm bot @getidsbot vào nhóm

3. Chạy bot:
```bash
python bot.py
```

## Cách sử dụng

### Thiết lập ban đầu
1. Thêm bot vào nhóm Telegram
2. Superadmin đầu tiên (đã cấu hình trong .env) sử dụng lệnh `/start` để cấu hình bot
3. Bot sẽ tự động thiết lập người có ID trong INITIAL_SUPERADMIN_ID làm superadmin

### Lệnh cho thành viên
- `/checkin`: Bắt đầu điểm danh và chọn hành động

### Lệnh cho Admin
- `/report`: Xem báo cáo hoạt động trong ngày
- `/listadmin`: Xem danh sách admin và superadmin
- `/listsuperadmin`: Xem danh sách superadmin

### Lệnh cho Superadmin
- `/addadmin [user_id]`: Thêm admin mới
- `/removeadmin [user_id]`: Xóa admin
- `/addsuperadmin [user_id]`: Thêm superadmin mới
- `/removesuperadmin [user_id]`: Xóa superadmin

## Thời gian cho phép

- 🚶 Ra ngoài: 5 phút/lần
- 🚬 Hút thuốc: 5 phút/lần
- 🚻 Vệ sinh cá nhân (1): 10 phút/lần
- 🚻 Vệ sinh cá nhân (2): 25 phút/lần
- 🍱 Lấy cơm: 10 phút/lần
- 🧹 Cất bát: 5 phút/lần

## Cấu trúc file Excel

Mỗi nhóm sẽ có một file Excel riêng với tên: `activities_group_{group_id}_{date}.xlsx`

Các cột trong file Excel:
- ID: ID của người dùng trên Telegram
- Tên: Tên đầy đủ của người dùng
- Hành động: Loại hoạt động đã chọn
- Thời gian bắt đầu: Thời điểm bắt đầu hoạt động
- Thời gian kết thúc: Thời điểm kết thúc hoạt động
- Tổng thời gian (phút): Số phút thực hiện hoạt động
- Vi phạm: "Có" hoặc "Không" tùy thuộc vào việc có vượt quá thời gian cho phép

## Phân quyền

### Superadmin
- Có toàn quyền quản lý admin và superadmin
- Có thể thêm/xóa admin và superadmin
- Có tất cả quyền của admin

### Admin
- Có thể xem báo cáo
- Có thể xem danh sách admin và superadmin
- Không thể thêm/xóa admin hoặc superadmin

## Lưu ý
- Mỗi nhóm có file Excel riêng biệt
- Không thể xóa superadmin cuối cùng
- Superadmin luôn là admin
- Bot chỉ hoạt động trong nhóm Telegram
- Cần cấu hình đúng ID superadmin trong file .env trước khi chạy bot 