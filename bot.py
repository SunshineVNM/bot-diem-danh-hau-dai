import os
import logging
from datetime import datetime, timedelta, time
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ChatMemberHandler
from dotenv import load_dotenv
import asyncio
from telegram.ext import JobQueue
import telegram.error
import pytz
import json

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Constants
TIME_LIMITS = {
    '🚶 Ra Ngoài': 5,
    '🚬 Hút Thuốc': 5,
    '🚻 Vệ Sinh 1': 10,
    '🚻 Vệ Sinh 2': 15,
    '🍚 Lấy Cơm': 10,
    '🍽️ Cất Bát': 5
}

# Store user states
user_states = {}
# Store group settings
group_settings = {}
# Store countdown tasks
countdown_tasks = {}

activity_keyboard = ReplyKeyboardMarkup(
    [
        [
            KeyboardButton("🍚 Lấy Cơm", request_contact=False, request_location=False),
            KeyboardButton("🚬 Hút Thuốc", request_contact=False, request_location=False),
            KeyboardButton("🚻 Vệ Sinh 1", request_contact=False, request_location=False)
        ],
        [
            KeyboardButton("🚻 Vệ Sinh 2", request_contact=False, request_location=False),
            KeyboardButton("🍽️ Cất Bát", request_contact=False, request_location=False),
            KeyboardButton("🚶 Ra Ngoài", request_contact=False, request_location=False)
        ],
        [
            KeyboardButton("🔙 Quay về", request_contact=False, request_location=False)
        ]
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Chọn hoạt động của bạn",
    selective=True,
    is_persistent=True
)

def create_keyboard():
    keyboard = [
        [InlineKeyboardButton("🍱 Ăn Cơm", callback_data="🍱 Lấy cơm"),
         InlineKeyboardButton("🚶 Ra Ngoài", callback_data="🚶 Ra ngoài"),
         InlineKeyboardButton("🚬 Hút Thuốc", callback_data="🚬 Hút thuốc")],
        [InlineKeyboardButton("🚻 Vệ Sinh-1", callback_data="🚻 Vệ sinh (1)"),
         InlineKeyboardButton("🚻 Vệ Sinh-2", callback_data="🚻 Vệ sinh (2)")],
        [InlineKeyboardButton("🧹 Cất Bát", callback_data="🧹 Cất bát")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_excel_filename(group_id):
    """Generate Excel filename for a specific group."""
    # Tạo thư mục reports nếu chưa tồn tại
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    # Tạo tên file với đường dẫn đầy đủ
    utc_plus_7 = pytz.timezone('Asia/Bangkok')
    now = datetime.now(utc_plus_7)
    filename = f'activities_group_{group_id}_{now.strftime("%Y%m%d")}.xlsx'
    full_path = os.path.join(reports_dir, filename)
    
    logging.info(f"Excel file will be saved to: {full_path}")
    return full_path

def is_superadmin(user_id, chat_id):
    """Check if user is superadmin in the group or là ID trong .env."""
    initial_superadmin_id = int(os.getenv('INITIAL_SUPERADMIN_ID', '0'))
    if user_id == initial_superadmin_id:
        return True
    if chat_id not in group_settings:
        return False
    return user_id in group_settings[chat_id].get('superadmin_ids', [])

def is_admin(user_id, chat_id):
    """Check if user is admin in the group."""
    if chat_id not in group_settings:
        return False
    return user_id in group_settings[chat_id]['admin_ids']

def save_group_settings():
    """Save group settings to JSON file."""
    with open('group_settings.json', 'w', encoding='utf-8') as f:
        # Convert datetime objects to strings
        settings_to_save = {}
        for group_id, settings in group_settings.items():
            settings_to_save[str(group_id)] = settings
        json.dump(settings_to_save, f, ensure_ascii=False, indent=4)

def load_group_settings():
    """Load group settings from JSON file."""
    try:
        with open('group_settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            # Convert string keys back to integers
            return {int(k): v for k, v in settings.items()}
    except FileNotFoundError:
        return {}

def save_user_states():
    """Save user states to JSON file."""
    try:
        with open('user_states.json', 'w', encoding='utf-8') as f:
            # Convert datetime objects to strings
            states_to_save = {}
            for user_id, state in user_states.items():
                states_to_save[str(user_id)] = state.copy()  # Create a copy to avoid modifying original
                if 'start_time' in state and isinstance(state['start_time'], datetime):
                    states_to_save[str(user_id)]['start_time'] = state['start_time'].isoformat()
                if 'activities' in state:
                    for activity in states_to_save[str(user_id)]['activities']:
                        if 'start_time' in activity and isinstance(activity['start_time'], datetime):
                            activity['start_time'] = activity['start_time'].isoformat()
                        if 'end_time' in activity and isinstance(activity['end_time'], datetime):
                            activity['end_time'] = activity['end_time'].isoformat()
            json.dump(states_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error saving user states: {e}")
        logging.error(f"User states content: {user_states}")

def load_user_states():
    """Load user states from JSON file."""
    try:
        with open('user_states.json', 'r', encoding='utf-8') as f:
            states = json.load(f)
            # Convert string keys back to integers and parse datetime
            loaded_states = {}
            for k, v in states.items():
                loaded_states[int(k)] = v.copy()  # Create a copy to avoid modifying original
                if 'start_time' in v and isinstance(v['start_time'], str):
                    loaded_states[int(k)]['start_time'] = datetime.fromisoformat(v['start_time'])
                if 'activities' in v:
                    for activity in loaded_states[int(k)]['activities']:
                        if 'start_time' in activity and isinstance(activity['start_time'], str):
                            activity['start_time'] = datetime.fromisoformat(activity['start_time'])
                        if 'end_time' in activity and isinstance(activity['end_time'], str):
                            activity['end_time'] = datetime.fromisoformat(activity['end_time'])
            return loaded_states
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.error(f"Error loading user states: {e}")
        return {}

# Load settings when bot starts
group_settings = load_group_settings()
user_states = load_user_states()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    if update.effective_chat.type == 'private':
        await update.message.reply_text(
            '🤖 Bot này chỉ hoạt động trong nhóm.\n'
            'Quy trình cấu hình:\n'
            '1. Thêm bot vào nhóm\n'
            '2. Superadmin (đã cấu hình trong .env) sử dụng lệnh /start để cấu hình bot\n'
            '3. Sau khi cấu hình, các thành viên có thể sử dụng các nút bấm để thực hiện hành động'
        )
        return

    user_id = update.effective_user.id
    initial_superadmin_id = int(os.getenv('INITIAL_SUPERADMIN_ID', '0'))
    
    if user_id != initial_superadmin_id:
        await update.message.reply_text('❌ Chỉ superadmin được cấu hình mới có thể sử dụng lệnh này.')
        return

    group_id = update.effective_chat.id
    group_settings[group_id] = {
        'is_setup': True,
        'admin_ids': [user_id],
        'superadmin_ids': [user_id],
        'group_name': update.effective_chat.title,
        'report_group_id': -1002560630146  # Kênh mặc định để nhận báo cáo
    }
    
    # Save settings after modification
    save_group_settings()
    
    await update.message.reply_text(
        f'✅ Bot đã được cấu hình cho nhóm {update.effective_chat.title}.\n'
        'Các thành viên có thể sử dụng các nút bấm để thực hiện hành động.\n\n'
        'Các lệnh quản lý admin (chỉ superadmin):\n'
        '/addadmin - Thêm admin mới\n'
        '/removeadmin - Xóa admin\n'
        '/listadmin - Xem danh sách admin\n'
        '/setreportgroup - Cấu hình nhóm nhận báo cáo (mặc định: kênh -1002560630146)',
        reply_markup=activity_keyboard
    )

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new admin to the group."""
    if not is_superadmin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ superadmin mới có thể sử dụng lệnh này.')
        return

    if not context.args:
        await update.message.reply_text('❌ Vui lòng nhập ID của người dùng cần thêm làm admin.')
        return

    try:
        new_admin_id = int(context.args[0])
        group_id = update.effective_chat.id
        
        if new_admin_id in group_settings[group_id]['admin_ids']:
            await update.message.reply_text('❌ Người này đã là admin.')
            return

        group_settings[group_id]['admin_ids'].append(new_admin_id)
        save_group_settings()  # Save after modification
        await update.message.reply_text(f'✅ Đã thêm admin mới với ID: {new_admin_id}')
    except ValueError:
        await update.message.reply_text('❌ ID không hợp lệ. Vui lòng nhập số.')

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an admin from the group."""
    if not is_superadmin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ superadmin mới có thể sử dụng lệnh này.')
        return

    if not context.args:
        await update.message.reply_text('❌ Vui lòng nhập ID của admin cần xóa.')
        return

    try:
        admin_id = int(context.args[0])
        group_id = update.effective_chat.id
        
        if admin_id not in group_settings[group_id]['admin_ids']:
            await update.message.reply_text('❌ Không tìm thấy admin này.')
            return

        if admin_id in group_settings[group_id]['superadmin_ids']:
            await update.message.reply_text('❌ Không thể xóa superadmin khỏi danh sách admin.')
            return

        group_settings[group_id]['admin_ids'].remove(admin_id)
        save_group_settings()  # Save after modification
        await update.message.reply_text(f'✅ Đã xóa admin với ID: {admin_id}')
    except ValueError:
        await update.message.reply_text('❌ ID không hợp lệ. Vui lòng nhập số.')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins in the group."""
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ admin mới có thể sử dụng lệnh này.')
        return

    group_id = update.effective_chat.id
    admin_list = group_settings[group_id]['admin_ids']
    superadmin_list = group_settings[group_id]['superadmin_ids']
    
    admin_text = "👥 Danh sách admin:\n"
    for admin_id in admin_list:
        try:
            chat_member = await context.bot.get_chat_member(group_id, admin_id)
            role = "👑 Superadmin" if admin_id in superadmin_list else "👤 Admin"
            admin_text += f"- {chat_member.user.full_name} (ID: {admin_id}) - {role}\n"
        except:
            role = "👑 Superadmin" if admin_id in superadmin_list else "👤 Admin"
            admin_text += f"- ID: {admin_id} - {role}\n"
    
    await update.message.reply_text(admin_text)

async def add_superadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new superadmin to the group."""
    if not is_superadmin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ superadmin mới có thể sử dụng lệnh này.')
        return

    if not context.args:
        await update.message.reply_text('❌ Vui lòng nhập ID của người dùng cần thêm làm superadmin.')
        return

    try:
        new_superadmin_id = int(context.args[0])
        group_id = update.effective_chat.id
        
        if new_superadmin_id in group_settings[group_id]['superadmin_ids']:
            await update.message.reply_text('❌ Người này đã là superadmin.')
            return

        # Thêm vào cả danh sách admin và superadmin
        group_settings[group_id]['admin_ids'].append(new_superadmin_id)
        group_settings[group_id]['superadmin_ids'].append(new_superadmin_id)
        save_group_settings()  # Save after modification
        await update.message.reply_text(f'✅ Đã thêm superadmin mới với ID: {new_superadmin_id}')
    except ValueError:
        await update.message.reply_text('❌ ID không hợp lệ. Vui lòng nhập số.')

async def remove_superadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a superadmin from the group."""
    if not is_superadmin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ superadmin mới có thể sử dụng lệnh này.')
        return

    if not context.args:
        await update.message.reply_text('❌ Vui lòng nhập ID của superadmin cần xóa.')
        return

    try:
        superadmin_id = int(context.args[0])
        group_id = update.effective_chat.id
        
        if superadmin_id not in group_settings[group_id]['superadmin_ids']:
            await update.message.reply_text('❌ Không tìm thấy superadmin này.')
            return

        if len(group_settings[group_id]['superadmin_ids']) <= 1:
            await update.message.reply_text('❌ Không thể xóa superadmin cuối cùng.')
            return

        # Xóa khỏi cả danh sách admin và superadmin
        group_settings[group_id]['admin_ids'].remove(superadmin_id)
        group_settings[group_id]['superadmin_ids'].remove(superadmin_id)
        save_group_settings()  # Save after modification
        await update.message.reply_text(f'✅ Đã xóa superadmin với ID: {superadmin_id}')
    except ValueError:
        await update.message.reply_text('❌ ID không hợp lệ. Vui lòng nhập số.')

async def list_superadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all superadmins in the group."""
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ admin mới có thể sử dụng lệnh này.')
        return

    group_id = update.effective_chat.id
    superadmin_list = group_settings[group_id]['superadmin_ids']
    
    admin_text = "👑 Danh sách superadmin:\n"
    for superadmin_id in superadmin_list:
        try:
            chat_member = await context.bot.get_chat_member(group_id, superadmin_id)
            admin_text += f"- {chat_member.user.full_name} (ID: {superadmin_id})\n"
        except:
            admin_text += f"- ID: {superadmin_id}\n"
    
    await update.message.reply_text(admin_text)

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle check-in command."""
    if update.effective_chat.type == 'private':
        await update.message.reply_text('❌ Lệnh này chỉ hoạt động trong nhóm.')
        return

    group_id = update.effective_chat.id
    if group_id not in group_settings or not group_settings[group_id]['is_setup']:
        await update.message.reply_text('❌ Bot chưa được cấu hình cho nhóm này. Vui lòng liên hệ admin.')
        return

    user_id = update.effective_user.id
    if user_id not in user_states or user_states[user_id]['status'] != 'active':
        await update.message.reply_text('❌ Bạn chưa có hoạt động nào đang diễn ra.')
        return

    # Tạo bàn phím chỉ với nút quay về cho hoạt động hiện tại
    reply_keyboard = [["🔙 Quay về"]]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f'Vui lòng nhấn nút bên dưới để kết thúc hoạt động {user_states[user_id]["action"]}:',
        reply_markup=reply_markup
    )

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle check-out command."""
    if update.effective_chat.type == 'private':
        await update.message.reply_text('❌ Lệnh này chỉ hoạt động trong nhóm.')
        return

    user_id = update.effective_user.id
    if user_id in user_states and user_states[user_id]['status'] == 'active':
        await update.message.reply_text(
            f'⚠️ Bạn đang trong trạng thái {user_states[user_id]["action"]}.\n'
        )
        return

    await update.message.reply_text(
        f'👋 Xin chào {update.effective_user.full_name}!\n'
        'Vui lòng chọn hành động của bạn:',
        reply_markup=activity_keyboard
    )

async def update_countdown(user_id, chat_id, message_id, action, time_limit, context):
    """Update countdown timer."""
    if user_id not in user_states:
        return
    
    start_time = user_states[user_id]['start_time']
    end_time = start_time + timedelta(minutes=time_limit)
    now = get_current_time()
    
    # Tính thời gian còn lại
    remaining = (end_time - now).total_seconds()
    
    # Chờ đến khi còn 1 phút
    if remaining > 60:
        await asyncio.sleep(remaining - 60)
        # Kiểm tra lại trạng thái
        if user_id not in user_states or user_states[user_id]['status'] != 'active':
            return
        await safe_send_message(
            context.bot, 
            chat_id, 
            text=f"⚠️⏳ CẢNH BÁO: Hoạt động {action} còn 1 phút nữa sẽ hết thời gian cho phép!", 
            reply_to_message_id=message_id
        )
        remaining = 60
    
    # Chờ đến khi còn 20 giây
    if remaining > 20:
        await asyncio.sleep(remaining - 20)
        # Kiểm tra lại trạng thái
        if user_id not in user_states or user_states[user_id]['status'] != 'active':
            return
        await safe_send_message(
            context.bot, 
            chat_id, 
            text=f'🚨 CẢNH BÁO KHẨN CẤP: Hoạt động {action} chỉ còn 20 giây nữa!\nẤn quay về ngay lập tức!', 
            reply_to_message_id=message_id
        )
        remaining = 20
    
    # Chờ đến hết giờ
    await asyncio.sleep(remaining)
    # Kiểm tra lại trạng thái
    if user_id in user_states and user_states[user_id]['status'] == 'active':
        try:
            end_time = get_current_time()
            duration = (end_time - start_time).total_seconds()
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            record_activity(
                chat_id, user_id, user_states[user_id].get('user_name', 'Unknown'),
                action, start_time, end_time, duration / 60
            )
            await safe_send_message(
                context.bot, 
                chat_id, 
                text=f'⛔ VI PHẠM THỜI GIAN!\nHành động: {action}\nThời gian cho phép: {time_limit} phút\nThời gian thực tế: {minutes:02d}:{seconds:02d}\nĐã ghi nhận vi phạm vào báo cáo.', 
                reply_to_message_id=message_id
            )
            del user_states[user_id]
            if user_id in countdown_tasks:
                del countdown_tasks[user_id]
        except Exception as e:
            logging.error(f"Error handling time violation: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    current_time = datetime.now()
    
    if user_id in user_states and user_states[user_id]['status'] == 'active':
        # User is returning
        if action != user_states[user_id]['action']:
            await query.edit_message_text(
                f'❌ Vui lòng chọn đúng hành động {user_states[user_id]["action"]} để kết thúc.'
            )
            return

        # Hủy task đếm ngược nếu có
        if user_id in countdown_tasks:
            countdown_tasks[user_id].cancel()
            del countdown_tasks[user_id]

        start_time = user_states[user_id]['start_time']
        time_diff = current_time - start_time
        duration = time_diff.total_seconds() / 60
        
        if duration > TIME_LIMITS[user_states[user_id]['action']]:
            # Violation occurred
            minutes = int(duration)
            seconds = int((duration - minutes) * 60)
            await query.edit_message_text(
                f'⚠️ Vi phạm thời gian!\n'
                f'Hành động: {user_states[user_id]["action"]}\n'
                f'Thời gian cho phép: {TIME_LIMITS[user_states[user_id]["action"]]} phút\n'
                f'Thời gian thực tế: {minutes:02d}:{seconds:02d}'
            )
        else:
            minutes = int(duration)
            seconds = int((duration - minutes) * 60)
            await query.edit_message_text(
                f'✅🎉 Hoàn thành!\n'
                f'Hành động: {user_states[user_id]["action"]}\n'
                f'Thời gian: {minutes:02d}:{seconds:02d}'
            )
        
        # Record the activity
        group_id = query.message.chat_id
        record_activity(group_id, user_id, query.from_user.full_name, user_states[user_id]['action'], 
                       start_time, current_time, duration)
        
        # Clear user state
        del user_states[user_id]
    else:
        # User is starting new activity
        user_states[user_id] = {
            'action': action,
            'start_time': current_time,
            'status': 'active',
            'user_name': query.from_user.full_name  # Lưu tên người dùng
        }
        
        # Tạo bàn phím reply chỉ với nút Quay về
        reply_keyboard = [["🔙 Quay về"]]
        reply_markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        message = await query.edit_message_text(
            f'⏱️ Bạn đã bắt đầu: {action}\n'
            f'Thời gian cho phép: {TIME_LIMITS[action]} phút\n'
            f'Còn lại: {TIME_LIMITS[action]:02d}:00'
        )
        
        # Gửi bàn phím reply
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Nhấn 'Quay về' khi bạn đã quay lại.",
            reply_markup=reply_markup
        )
        
        # Bắt đầu task đếm ngược
        countdown_tasks[user_id] = asyncio.create_task(
            update_countdown(
                user_id=user_id,
                chat_id=message.chat_id,
                message_id=message.message_id,
                action=action,
                time_limit=TIME_LIMITS[action],
                context=context
            )
        )

async def handle_activity_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle activity button presses from ReplyKeyboardMarkup."""
    user_id = update.effective_user.id
    action = update.message.text
    
    # Xử lý nút Quay về
    if action == "🔙 Quay về":
        if user_id in user_states and user_states[user_id]['status'] == 'active':
            # Hủy task đếm ngược nếu có
            if user_id in countdown_tasks:
                countdown_tasks[user_id].cancel()
                del countdown_tasks[user_id]
            
            # Xử lý kết thúc hoạt động
            start_time = user_states[user_id]['start_time']
            end_time = get_current_time()
            duration = (end_time - start_time).total_seconds() / 60
            current_action = user_states[user_id]['action']
            group_id = update.effective_chat.id
            
            # Khởi tạo user_states nếu chưa tồn tại
            if user_id not in user_states:
                user_states[user_id] = {
                    'group_id': group_id,
                    'activities': [],
                    'status': 'inactive'
                }
            elif 'activities' not in user_states[user_id]:
                user_states[user_id]['activities'] = []
            
            # Lưu hoạt động hiện tại
            current_activity = {
                'date': datetime.now().strftime("%Y%m%d"),
                'username': update.effective_user.full_name,
                'full_name': update.effective_user.full_name,
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'status': 'completed'
            }
            user_states[user_id]['activities'].append(current_activity)
            
            # Lưu user_states vào file
            save_user_states()
            
            # Ghi log hoạt động vào Excel
            success = record_activity(
                group_id, user_id, update.effective_user.full_name,
                current_action, start_time, end_time, duration
            )
            
            # Tính toán tổng thời gian và số lần hoạt động trong ngày
            current_date = datetime.now().strftime("%Y%m%d")
            total_duration = 0
            activity_count = 0
            
            # Debug log
            logging.info(f"=== Thống kê hoạt động ===")
            logging.info(f"User ID: {user_id}")
            logging.info(f"Current date: {current_date}")
            logging.info(f"Activities count: {len(user_states[user_id]['activities'])}")
            
            # Tính toán thống kê
            for activity in user_states[user_id]['activities']:
                if activity['date'] == current_date:
                    total_duration += activity['duration']
                    activity_count += 1
                    logging.info(f"Activity: {activity}")
            
            logging.info(f"Total duration: {total_duration}")
            logging.info(f"Activity count: {activity_count}")
            logging.info("=== Kết thúc thống kê ===")
            
            # Thông báo kết quả
            if duration > TIME_LIMITS[current_action]:
                await update.message.reply_text(
                    f'⚠️ Vi phạm thời gian!\n'
                    f'Hành động: {current_action}\n'
                    f'Thời gian cho phép: {TIME_LIMITS[current_action]} phút\n'
                    f'Thời gian thực tế: {duration:.1f} phút\n'
                    f'{"✅ Đã ghi nhận vào báo cáo" if success else "❌ Lỗi khi ghi báo cáo"}\n\n'
                    f'📊 Thống kê ngày hôm nay:\n'
                    f'• Tổng thời gian hoạt động: {total_duration:.1f} phút\n'
                    f'• Số lần hoạt động: {activity_count}',
                    reply_markup=activity_keyboard
                )
            else:
                await update.message.reply_text(
                    f'✅🎉 Hoàn thành!\n'
                    f'Hành động: {current_action}\n'
                    f'Thời gian: {duration:.1f} phút\n'
                    f'{"✅ Đã ghi nhận vào báo cáo" if success else "❌ Lỗi khi ghi báo cáo"}\n\n'
                    f'📊 Thống kê ngày hôm nay:\n'
                    f'• Tổng thời gian hoạt động: {total_duration:.1f} phút\n'
                    f'• Số lần hoạt động: {activity_count}',
                    reply_markup=activity_keyboard
                )
            
            # Xóa trạng thái active của user nhưng giữ lại lịch sử hoạt động
            user_states[user_id]['status'] = 'inactive'
            if 'start_time' in user_states[user_id]:
                del user_states[user_id]['start_time']
            if 'action' in user_states[user_id]:
                del user_states[user_id]['action']
            
            # Lưu lại trạng thái mới
            save_user_states()
        else:
            await update.message.reply_text(
                '❌ Bạn không có hoạt động nào đang diễn ra.',
                reply_markup=activity_keyboard
            )
        return

    # Kiểm tra nếu user đang trong trạng thái active
    if user_id in user_states and user_states[user_id]['status'] == 'active':
        await update.message.reply_text(
            f'⚠️ Bạn đang trong trạng thái {user_states[user_id]["action"]}.\n'
            'Vui lòng nhấn "🔙 Quay về" trước khi chọn hoạt động mới.',
            reply_markup=activity_keyboard
        )
        return

    # Kiểm tra nếu action là một trong các hoạt động được định nghĩa
    if action in TIME_LIMITS:
        current_time = get_current_time()
        user_states[user_id] = {
            'action': action,
            'start_time': current_time,
            'status': 'active',
            'user_name': update.effective_user.full_name,
            'message_id': update.message.message_id  # Lưu message_id của tin nhắn bắt đầu
        }
        
        message = await update.message.reply_text(
            f'⏱️ Bạn đã bắt đầu: {action}\n'
            f'Thời gian cho phép: {TIME_LIMITS[action]} phút\n'
            f'Còn lại: {TIME_LIMITS[action]:02d}:00',
            reply_markup=activity_keyboard
        )
        
        # Bắt đầu task đếm ngược
        countdown_tasks[user_id] = asyncio.create_task(
            update_countdown(
                user_id=user_id,
                chat_id=message.chat_id,
                message_id=user_states[user_id]['message_id'],  # Sử dụng message_id của tin nhắn bắt đầu
                action=action,
                time_limit=TIME_LIMITS[action],
                context=context
            )
        )
    else:
        # Nếu không phải là một hoạt động hợp lệ
        await update.message.reply_text(
            '❌ Vui lòng chọn một hoạt động từ bàn phím.',
            reply_markup=activity_keyboard
        )

async def handle_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when user clicks the return button."""
    user_id = update.effective_user.id
    if user_id in user_states and user_states[user_id]['status'] == 'active':
        action = user_states[user_id]['action']
        start_time = user_states[user_id]['start_time']
        end_time = get_current_time()  # Sử dụng get_current_time() thay vì datetime.now()
        duration = (end_time - start_time).total_seconds() / 60

        # Hủy task đếm ngược nếu có
        if user_id in countdown_tasks:
            countdown_tasks[user_id].cancel()
            del countdown_tasks[user_id]

        # Ghi log hoạt động
        group_id = update.effective_chat.id
        record_activity(
            group_id, user_id, update.effective_user.full_name,
            action, start_time, end_time, duration
        )

        # Thông báo kết quả
        if duration > TIME_LIMITS[action]:
            await update.message.reply_text(
                f'⚠️ Vi phạm thời gian!\n'
                f'Hành động: {action}\n'
                f'Thời gian cho phép: {TIME_LIMITS[action]} phút\n'
                f'Thời gian thực tế: {duration:.1f} phút',
                reply_markup=activity_keyboard
            )
        else:
            await update.message.reply_text(
                f'✅🎉 Hoàn thành!\n'
                f'Hành động: {action}\n'
                f'Thời gian: {duration:.1f} phút',
                reply_markup=activity_keyboard
            )

        # Xóa trạng thái user sau khi đã xử lý xong
        if user_id in user_states:
            del user_states[user_id]
    else:
        # Nếu không có trạng thái active, thông báo cho người dùng
        await update.message.reply_text(
            '❌ Bạn không có hoạt động nào đang diễn ra.',
            reply_markup=activity_keyboard
        )

def record_activity(group_id, user_id, user_name, action, start_time, end_time, duration):
    """Record activity in Excel file."""
    success = False
    try:
        filename = get_group_excel_filename(group_id)
        logging.info(f"=== Bắt đầu ghi hoạt động ===")
        logging.info(f"Group ID: {group_id}")
        logging.info(f"User ID: {user_id}")
        logging.info(f"User Name: {user_name}")
        logging.info(f"Action: {action}")
        logging.info(f"Start Time: {start_time}")
        logging.info(f"End Time: {end_time}")
        logging.info(f"Duration: {duration} phút")
        logging.info(f"Excel File: {filename}")
        
        # Convert to timezone-naive datetime for Excel
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.replace(tzinfo=None)
        
        # Lưu hoạt động vào user_states
        if user_id not in user_states:
            user_states[user_id] = {
                'group_id': group_id,
                'activities': []
            }
        
        user_states[user_id]['activities'].append({
            'date': datetime.now().strftime("%Y%m%d"),
            'username': user_name,
            'full_name': user_name,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'status': 'completed'
        })
        
        # Lưu user_states vào file
        save_user_states()
        
        data = {
            'ID': user_id,
            'Tên': user_name,
            'Hành động': action,
            'Thời gian bắt đầu': start_time,
            'Thời gian kết thúc': end_time,
            'Tổng thời gian (phút)': duration,
            'Vi phạm': 'Có' if duration > TIME_LIMITS[action] else 'Không'
        }
        
        df = pd.DataFrame([data])
        logging.info(f"DataFrame created with {len(df)} rows")
        
        # Tạo thư mục nếu chưa tồn tại
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        logging.info(f"Directory created/checked: {os.path.dirname(filename)}")
        
        # Kiểm tra file có tồn tại không
        if os.path.exists(filename):
            try:
                logging.info(f"Reading existing Excel file: {filename}")
                existing_df = pd.read_excel(filename)
                logging.info(f"Existing file has {len(existing_df)} rows")
                df = pd.concat([existing_df, df], ignore_index=True)
                logging.info(f"Combined DataFrame has {len(df)} rows")
            except Exception as e:
                logging.error(f"Error reading existing Excel file: {e}")
                logging.info("Creating new Excel file")
        
        # Ghi file Excel
        try:
            logging.info(f"Writing to Excel file: {filename}")
            with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Sheet1')
                
                # Lấy workbook và worksheet
                workbook = writer.book
                worksheet = writer.sheets['Sheet1']
                
                # Tạo format cho vi phạm (màu đỏ)
                red_format = workbook.add_format({'font_color': 'red'})
                
                # Áp dụng format cho cột Vi phạm
                for row_num, value in enumerate(df['Vi phạm'], start=1):
                    if value == 'Có':
                        worksheet.write(row_num, df.columns.get_loc('Vi phạm'), value, red_format)
                    else:
                        worksheet.write(row_num, df.columns.get_loc('Vi phạm'), value)
                        
            logging.info(f"Successfully wrote to Excel file: {filename}")
            logging.info(f"File size: {os.path.getsize(filename)} bytes")
            success = True
        except Exception as e:
            logging.error(f"Error writing to Excel file: {e}")
            # Thử ghi file tạm
            temp_filename = f"{filename}.temp"
            try:
                logging.info(f"Attempting to write to temp file: {temp_filename}")
                df.to_excel(temp_filename, index=False)
                if os.path.exists(filename):
                    os.remove(filename)
                os.rename(temp_filename, filename)
                logging.info(f"Successfully wrote to temp file and renamed: {filename}")
                logging.info(f"Final file size: {os.path.getsize(filename)} bytes")
                success = True
            except Exception as e2:
                logging.error(f"Error writing to temp file: {e2}")
                
    except Exception as e:
        logging.error(f"Error in record_activity: {e}")
        # Ghi log chi tiết lỗi
        logging.error(f"Group ID: {group_id}")
        logging.error(f"User ID: {user_id}")
        logging.error(f"Action: {action}")
        logging.error(f"Start time: {start_time}")
        logging.error(f"End time: {end_time}")
        logging.error(f"Duration: {duration}")
    finally:
        logging.info("=== Kết thúc ghi hoạt động ===")
        return success

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send daily report."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Log thông tin cơ bản
    logging.info(f"Report command called by user {user_id} in chat {chat_id}")
    
    # Kiểm tra xem đây có phải là nhóm không
    if update.effective_chat.type == 'private':
        logging.warning(f"Command used in private chat {chat_id}")
        await update.message.reply_text('❌ Lệnh này chỉ hoạt động trong nhóm.')
        return
    
    # Cho phép cả admin và superadmin dùng lệnh
    if not (is_admin(user_id, chat_id) or is_superadmin(user_id, chat_id)):
        logging.warning(f"User {user_id} is not admin/superadmin in chat {chat_id}")
        await update.message.reply_text('❌ Chỉ admin hoặc superadmin mới có thể sử dụng lệnh này.')
        return

    # Lấy tên file Excel thực tế
    current_date = datetime.now().strftime("%Y%m%d")
    filename = f'activities_group_{chat_id}_{current_date}.xlsx'
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports', filename)
    logging.info(f"Looking for report file: {full_path}")
    
    # Kiểm tra xem file có tồn tại không
    if not os.path.exists(full_path):
        logging.warning(f"Report file does not exist: {full_path}")
        await update.message.reply_text('📊 Chưa có dữ liệu hoạt động nào trong ngày.')
        return
        
    if filename.startswith('~$'):
        logging.warning(f"Report file is a temporary file: {full_path}")
        await update.message.reply_text('📊 Chưa có dữ liệu hoạt động nào trong ngày.')
        return

    # Log thông tin file
    file_size = os.path.getsize(full_path)
    logging.info(f"Report file exists, size: {file_size} bytes")

    group_name = group_settings[chat_id]['group_name']
    try:
        logging.info(f"Sending report for group {group_name}")
        # Mở file trong chế độ binary
        with open(full_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f'📊 Báo cáo hoạt động ngày hôm nay - Nhóm {group_name}'
            )
        logging.info("Report sent successfully")
    except Exception as e:
        logging.error(f"Error sending report: {e}")
        logging.error(f"Error type: {type(e)}")
        logging.error(f"Error details: {str(e)}")
        await update.message.reply_text('❌ Có lỗi xảy ra khi gửi báo cáo. Vui lòng thử lại sau.')

async def send_daily_reports(context: ContextTypes.DEFAULT_TYPE):
    """Send daily reports to all admins in all groups."""
    try:
        current_date = datetime.now().strftime("%Y%m%d")
        logging.info(f"Starting daily report sending for date: {current_date}")
        
        for group_id, settings in group_settings.items():
            try:
                if not settings['is_setup']:
                    logging.info(f"Group {group_id} is not setup, skipping")
                    continue
                    
                filename = f'activities_group_{group_id}_{current_date}.xlsx'
                full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports', filename)
                logging.info(f"Checking for report file: {full_path}")
                
                if not os.path.exists(full_path):
                    logging.warning(f"Report file not found: {full_path}")
                    continue
                    
                group_name = settings['group_name']
                admin_ids = settings['admin_ids']
                report_group_id = settings.get('report_group_id')
                
                # Gửi báo cáo vào nhóm được chỉ định
                if report_group_id:
                    try:
                        logging.info(f"Sending report to report group {report_group_id}")
                        # Mở file trong chế độ binary
                        with open(full_path, 'rb') as f:
                            await context.bot.send_message(
                                chat_id=report_group_id,
                                text=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}\n'
                                     f'Thời gian gửi: {datetime.now().strftime("%H:%M:%S")}'
                            )
                            await context.bot.send_document(
                                chat_id=report_group_id,
                                document=f,
                                filename=filename,
                                caption=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}'
                            )
                        logging.info(f"Successfully sent report to report group {report_group_id}")
                    except Exception as e:
                        logging.error(f"Error sending report to report group {report_group_id}: {e}")
                        logging.error(f"Error type: {type(e)}")
                        logging.error(f"Error details: {str(e)}")
                
                # Gửi báo cáo riêng cho từng admin
                for admin_id in admin_ids:
                    try:
                        logging.info(f"Sending report to admin {admin_id}")
                        # Mở file trong chế độ binary
                        with open(full_path, 'rb') as f:
                            # Gửi thông báo trước
                            await context.bot.send_message(
                                chat_id=admin_id,
                                text=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}\n'
                                     f'Vui lòng đợi trong giây lát...'
                            )
                            
                            # Gửi file Excel
                            await context.bot.send_document(
                                chat_id=admin_id,
                                document=f,
                                filename=filename,
                                caption=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}\n'
                                       f'Thời gian gửi: {datetime.now().strftime("%H:%M:%S")}'
                            )
                        logging.info(f"Successfully sent report to admin {admin_id}")
                    except Exception as e:
                        logging.error(f"Error sending report to admin {admin_id}: {e}")
                        logging.error(f"Error type: {type(e)}")
                        logging.error(f"Error details: {str(e)}")
                        continue
                        
            except Exception as e:
                logging.error(f"Error processing group {group_id}: {e}")
                logging.error(f"Error type: {type(e)}")
                logging.error(f"Error details: {str(e)}")
                continue
                
    except Exception as e:
        logging.error(f"Error in send_daily_reports: {e}")
        logging.error(f"Error type: {type(e)}")
        logging.error(f"Error details: {str(e)}")

async def send_daily_reports_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to send daily reports."""
    try:
        current_date = datetime.now().strftime("%Y%m%d")
        logging.info(f"Starting daily report generation for date: {current_date}")
        logging.info(f"Current timezone: {datetime.now().astimezone().tzinfo}")
        logging.info(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Kiểm tra thư mục reports
        reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
        if not os.path.exists(reports_dir):
            logging.info(f"Creating reports directory: {reports_dir}")
            os.makedirs(reports_dir)
        
        for group_id, settings in group_settings.items():
            try:
                logging.info(f"Processing group {group_id}: {settings}")
                if not settings['is_setup']:
                    logging.info(f"Group {group_id} is not setup, skipping")
                    continue
                    
                group_name = settings['group_name']
                report_group_id = settings.get('report_group_id')
                
                if not report_group_id:
                    logging.warning(f"No report group configured for {group_name}")
                    continue
                    
                logging.info(f"Generating report for group {group_name} (ID: {group_id})")
                logging.info(f"Report will be sent to group {report_group_id}")
                
                filename = f'activities_group_{group_id}_{current_date}.xlsx'
                full_path = os.path.join(reports_dir, filename)
                
                # Tạo DataFrame từ dữ liệu hoạt động
                activities = []
                for user_id, user_data in user_states.items():
                    if user_data['group_id'] == group_id:
                        for activity in user_data['activities']:
                            if activity['date'] == current_date:
                                activities.append({
                                    'user_id': user_id,
                                    'username': activity['username'],
                                    'full_name': activity['full_name'],
                                    'start_time': activity['start_time'],
                                    'end_time': activity['end_time'],
                                    'duration': activity['duration'],
                                    'status': activity['status']
                                })
                
                if not activities:
                    logging.info(f"No activities found for group {group_name}")
                    continue
                
                logging.info(f"Found {len(activities)} activities for group {group_name}")
                
                # Tạo DataFrame
                df = pd.DataFrame(activities)
                
                # Tính toán tổng thời gian và số lần hoạt động cho mỗi user
                user_stats = df.groupby(['user_id', 'username', 'full_name']).agg({
                    'duration': 'sum',  # Tổng thời gian
                    'start_time': 'count'  # Số lần hoạt động
                }).reset_index()
                
                user_stats.columns = ['user_id', 'username', 'full_name', 'total_duration', 'activity_count']
                
                # Sắp xếp theo tổng thời gian giảm dần
                user_stats = user_stats.sort_values('total_duration', ascending=False)
                
                # Tạo file Excel
                with pd.ExcelWriter(full_path, engine='openpyxl') as writer:
                    # Sheet chi tiết hoạt động
                    df.to_excel(writer, sheet_name='Chi tiết hoạt động', index=False)
                    
                    # Sheet thống kê theo user
                    user_stats.to_excel(writer, sheet_name='Thống kê theo user', index=False)
                    
                    # Định dạng cột thời gian
                    for sheet in writer.sheets.values():
                        for col in ['start_time', 'end_time']:
                            if col in sheet.columns:
                                for cell in sheet[col]:
                                    if cell.value:
                                        cell.number_format = 'hh:mm:ss'
                
                logging.info(f"Generated report file: {full_path}")
                
                # Gửi báo cáo đến nhóm được chỉ định
                try:
                    with open(full_path, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=report_group_id,
                            document=f,
                            filename=filename,
                            caption=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}'
                        )
                    logging.info(f"Report sent successfully to group {report_group_id}")
                except Exception as e:
                    logging.error(f"Error sending report to group {report_group_id}: {e}")
                
            except Exception as e:
                logging.error(f"Error generating report for group {group_id}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"Error in send_daily_reports_job: {e}")
        logging.error(f"Error type: {type(e)}")
        logging.error(f"Error details: {str(e)}")

async def safe_send_message(bot, chat_id, text, reply_to_message_id=None):
    while True:
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to_message_id)
            break
        except telegram.error.RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception as ex:
            logging.error(f"Error sending message: {ex}")
            break

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        await update.message.reply_text(
            f"👋 Chào mừng {member.full_name}!\n"
            "Vui lòng chọn hoạt động của bạn:",
            reply_markup=activity_keyboard
        )

async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member.new_chat_member.status == "member":
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id=chat_id,
            text="🤖 Bot đã sẵn sàng!\nVui lòng chọn hoạt động của bạn:",
            reply_markup=activity_keyboard
        )
        # Gửi bàn phím cho tất cả thành viên
        await send_keyboard_to_all_members(chat_id, context)

async def send_keyboard_to_all_members(chat_id, context):
    """Gửi bàn phím cho tất cả thành viên trong nhóm."""
    try:
        # Lấy danh sách thành viên trong nhóm
        chat_members = await context.bot.get_chat_administrators(chat_id)
        for member in chat_members:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="🤖 Chọn hoạt động của bạn:",
                    reply_markup=activity_keyboard
                )
                break  # Chỉ gửi một lần trong nhóm
            except Exception as e:
                logging.error(f"Error sending keyboard to member {member.user.id}: {e}")
    except Exception as e:
        logging.error(f"Error getting chat members: {e}")

async def show_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Chọn hoạt động của bạn:",
        reply_markup=activity_keyboard
    )

def get_current_time():
    """Get current time in UTC+7."""
    utc_plus_7 = pytz.timezone('Asia/Bangkok')
    return datetime.now(utc_plus_7)

async def check_time_violations(context: ContextTypes.DEFAULT_TYPE):
    """Check for time violations."""
    now = get_current_time()
    for user_id, state in list(user_states.items()):
        if state['status'] == 'active':
            start_time = state['start_time']
            action = state['action']
            time_limit = TIME_LIMITS[action]
            duration = (now - start_time).total_seconds() / 60
            
            if duration > time_limit:
                try:
                    chat_id = state['chat_id']
                    user_name = state.get('user_name', 'Unknown')
                    record_activity(chat_id, user_id, user_name, action, start_time, now, duration)
                    await safe_send_message(
                        context.bot, chat_id,
                        f'⛔ VI PHẠM THỜI GIAN!\n'
                        f'Hành động: {action}\n'
                        f'Thời gian cho phép: {time_limit} phút\n'
                        f'Thời gian thực tế: {duration:.1f} phút\n'
                        f'Đã ghi nhận vi phạm vào báo cáo.'
                    )
                    del user_states[user_id]
                except Exception as e:
                    logging.error(f"Error handling time violation: {e}")

async def set_report_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the group that will receive daily reports."""
    if not is_superadmin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text('❌ Chỉ superadmin mới có thể sử dụng lệnh này.')
        return

    group_id = update.effective_chat.id
    
    # Kiểm tra xem nhóm đã được cấu hình chưa
    if group_id not in group_settings:
        await update.message.reply_text('❌ Nhóm này chưa được cấu hình. Vui lòng sử dụng lệnh /start trước.')
        return

    # Nếu không có tham số, sử dụng ID của nhóm hiện tại
    if not context.args:
        report_group_id = group_id
    else:
        try:
            report_group_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text('❌ ID không hợp lệ. Vui lòng nhập số.')
            return

    # Cập nhật cấu hình
    group_settings[group_id]['report_group_id'] = report_group_id
    save_group_settings()
    
    if report_group_id == group_id:
        await update.message.reply_text(f'✅ Đã cấu hình nhóm hiện tại ({group_id}) làm nhóm nhận báo cáo.')
    else:
        await update.message.reply_text(f'✅ Đã cấu hình nhóm nhận báo cáo với ID: {report_group_id}')

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("listadmin", list_admins))
    application.add_handler(CommandHandler("keyboard", show_keyboard))
    application.add_handler(CommandHandler("setreportgroup", set_report_group))
    
    # Handler cho thành viên mới và bot được thêm vào nhóm
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(ChatMemberHandler(bot_added_to_group, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER))
    
    # Thêm handler cho các nút hoạt động (đặt sau các handler khác)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_activity_button))

    # Lên lịch gửi báo cáo lúc 23:59 mỗi ngày (UTC+7)
    utc_plus_7 = pytz.timezone('Asia/Bangkok')
    report_time = time(hour=23, minute=59, second=0, tzinfo=utc_plus_7)
    application.job_queue.run_daily(
        send_daily_reports_job,
        time=report_time
    )

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 