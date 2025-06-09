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
    '🍽️ Cất Bát': 5,
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

def get_group_excel_filename(group_id):
    """Generate Excel filename for a specific group."""
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    
    utc_plus_7 = pytz.timezone('Asia/Bangkok')
    now = datetime.now(utc_plus_7)
    filename = f'activities_group_{group_id}_{now.strftime("%Y%m%d")}.xlsx'
    full_path = os.path.join(reports_dir, filename)
    
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
        settings_to_save = {}
        for group_id, settings in group_settings.items():
            settings_to_save[str(group_id)] = settings
        json.dump(settings_to_save, f, ensure_ascii=False, indent=4)

def load_group_settings():
    """Load group settings from JSON file."""
    try:
        with open('group_settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            return {int(k): v for k, v in settings.items()}
    except FileNotFoundError:
        return {}

def save_user_states():
    """Save user states to JSON file."""
    try:
        with open('user_states.json', 'w', encoding='utf-8') as f:
            states_to_save = {}
            for user_id, state in user_states.items():
                states_to_save[str(user_id)] = state.copy()
                if 'start_time' in state and isinstance(state['start_time'], datetime):
                    states_to_save[str(user_id)]['start_time'] = state['start_time'].isoformat()
                if 'activities' in state:
                    for activity in states_to_save[str(user_id)]['activities']:
                        if 'start_time' in activity and isinstance(activity['start_time'], datetime):
                            activity['start_time'] = activity['start_time'].isoformat()
                        if 'end_time' in activity and isinstance(activity['end_time'], datetime):
                            activity['end_time'] = activity['end_time'].isoformat()
                        if 'duration' in activity:
                            if isinstance(activity['duration'], str):
                                try:
                                    activity['duration'] = float(activity['duration'])
                                except ValueError:
                                    activity['duration'] = 0.0
            json.dump(states_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error saving user states: {e}")

def load_user_states():
    """Load user states from JSON file."""
    try:
        with open('user_states.json', 'r', encoding='utf-8') as f:
            states = json.load(f)
            loaded_states = {}
            for k, v in states.items():
                loaded_states[int(k)] = {
                    'start_time': None,
                    'activities': [],
                    'action': None,
                    'status': 'inactive'
                }
                
                if 'start_time' in v and isinstance(v['start_time'], str):
                    loaded_states[int(k)]['start_time'] = datetime.fromisoformat(v['start_time'])
                if 'activities' in v:
                    loaded_states[int(k)]['activities'] = v['activities']
                    for activity in loaded_states[int(k)]['activities']:
                        if 'start_time' in activity and isinstance(activity['start_time'], str):
                            activity['start_time'] = datetime.fromisoformat(activity['start_time'])
                        if 'end_time' in activity and isinstance(activity['end_time'], str):
                            activity['end_time'] = datetime.fromisoformat(activity['end_time'])
                        if 'duration' in activity:
                            if isinstance(activity['duration'], str):
                                try:
                                    activity['duration'] = float(activity['duration'])
                                except ValueError:
                                    activity['duration'] = 0.0
                if 'action' in v:
                    loaded_states[int(k)]['action'] = v['action']
                if 'status' in v:
                    loaded_states[int(k)]['status'] = v['status']
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
        'report_group_id': -1002560630146
    }
    
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
        save_group_settings()
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
        save_group_settings()
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

async def handle_activity_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle activity button press."""
    user_id = update.effective_user.id
    
    if user_id not in user_states:
        user_states[user_id] = {
            'start_time': None,
            'activities': [],
            'action': None,
            'status': 'inactive'
        }
    
    if update.message and update.message.text:
        current_action = update.message.text
        if current_action == "🔙 Quay về":
            if user_states[user_id]['start_time'] is not None:
                if user_id in countdown_tasks:
                    countdown_tasks[user_id].cancel()
                    del countdown_tasks[user_id]

                start_time = user_states[user_id]['start_time']
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds() / 60
                
                is_violation = duration > TIME_LIMITS.get(user_states[user_id]['action'], float('inf'))
                status = 'violation' if is_violation else 'completed'
                
                current_activity = {
                    'date': end_time.strftime("%Y%m%d"),
                    'username': update.effective_user.full_name,
                    'full_name': update.effective_user.full_name,
                    'start_time': start_time,
                    'end_time': end_time,
                    'duration': duration,
                    'status': status,
                    'action': user_states[user_id].get('action', 'Unknown'),
                    'violation_duration': duration - TIME_LIMITS.get(user_states[user_id]['action'], 0) if is_violation else 0
                }
                
                user_states[user_id]['activities'].append(current_activity)
                
                current_date = end_time.strftime("%Y%m%d")
                total_duration = 0
                activity_count = 0
                violation_count = 0
                
                today_activities = []
                for activity in user_states[user_id]['activities']:
                    activity_start_time = activity['start_time']
                    if isinstance(activity_start_time, str):
                        try:
                            activity_start_time = datetime.fromisoformat(activity_start_time)
                        except ValueError:
                            continue
                    
                    if activity_start_time.strftime("%Y%m%d") == current_date:
                        today_activities.append(activity)
                        if activity['status'] == 'violation':
                            violation_count += 1
                
                for activity in today_activities:
                    activity_duration = activity['duration']
                    if isinstance(activity_duration, str):
                        try:
                            activity_duration = float(activity_duration)
                        except ValueError:
                            continue
                    total_duration += activity_duration
                    activity_count += 1
                
                success = record_activity(
                    update.effective_chat.id,
                    user_id,
                    update.effective_user.full_name,
                    current_activity['action'],
                    start_time,
                    end_time,
                    duration
                )
                
                user_states[user_id]['start_time'] = None
                user_states[user_id]['action'] = None
                user_states[user_id]['status'] = 'inactive'
                
                duration_minutes = int(duration)
                duration_seconds = int((duration - duration_minutes) * 60)
                duration_str = f"{duration_minutes:02d}:{duration_seconds:02d}"
                
                is_violation = duration > TIME_LIMITS.get(current_activity['action'], float('inf'))
                status_icon = "❌" if is_violation else "✅"
                status_text = "VI PHẠM" if is_violation else "HỢP LỆ"
                
                result_message = (
                    f"📊 KẾT QUẢ HOẠT ĐỘNG\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 Hoạt động: {current_activity['action']}\n"
                    f"⏱️ Thời gian bắt đầu: {start_time.strftime('%H:%M:%S')}\n"
                    f"⏱️ Thời gian kết thúc: {end_time.strftime('%H:%M:%S')}\n"
                    f"⏱️ Thời gian hoạt động: {duration_str}\n"
                    f"📅 Ngày: {start_time.strftime('%d/%m/%Y')}\n"
                    f"📈 Tổng thời gian hôm nay: {total_duration:.2f} phút\n"
                    f"🔢 Số lần hoạt động: {activity_count}\n"
                    f"⚠️ Số lần vi phạm: {violation_count}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{status_icon} Trạng thái: {status_text}\n"
                )
                
                if is_violation:
                    result_message += f"⚠️ Vượt quá thời gian cho phép ({TIME_LIMITS[current_activity['action']]} phút)"
                
                await update.message.reply_text(result_message, reply_markup=activity_keyboard)
                save_user_states()
            else:
                await update.message.reply_text(
                    '❌ Bạn không có hoạt động nào đang diễn ra.',
                    reply_markup=activity_keyboard
                )
            return
            
        if current_action in TIME_LIMITS:
            if user_states[user_id]['start_time'] is not None:
                await update.message.reply_text(
                    f'⚠️ Bạn đang trong hoạt động khác.\n'
                    'Vui lòng nhấn "🔙 Quay về" trước khi bắt đầu hoạt động mới.',
                    reply_markup=activity_keyboard
                )
                return
            
            current_time = datetime.now()
            user_states[user_id]['start_time'] = current_time
            user_states[user_id]['action'] = current_action
            user_states[user_id]['status'] = 'active'
            
            message = await update.message.reply_text(
                f"Bạn đã bắt đầu hoạt động {current_action}.\n"
                f"Thời gian bắt đầu: {current_time.strftime('%H:%M:%S')}\n"
                f"Thời gian cho phép: {TIME_LIMITS[current_action]} phút",
                reply_markup=activity_keyboard
            )
            
            countdown_tasks[user_id] = asyncio.create_task(
                update_countdown(
                    user_id=user_id,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    action=current_action,
                    time_limit=TIME_LIMITS[current_action],
                    context=context
                )
            )
            save_user_states()

def record_activity(group_id, user_id, user_name, action, start_time, end_time, duration):
    """Record activity in Excel file."""
    success = False
    try:
        filename = get_group_excel_filename(group_id)
        
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.replace(tzinfo=None)
        
        is_violation = duration > TIME_LIMITS.get(action, float('inf'))
        violation_status = 'Có' if is_violation else 'Không'
        violation_duration = duration - TIME_LIMITS.get(action, 0) if is_violation else 0
        
        data = {
            'ID Nhóm': group_id,
            'ID': user_id,
            'Tên': user_name,
            'Hành động': action,
            'Thời gian bắt đầu': start_time,
            'Thời gian kết thúc': end_time,
            'Tổng thời gian (phút)': duration,
            'Thời gian cho phép (phút)': TIME_LIMITS.get(action, 0),
            'Vi phạm': violation_status,
            'Thời gian vi phạm (phút)': violation_duration
        }
        
        df = pd.DataFrame([data])
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        if os.path.exists(filename):
            try:
                existing_df = pd.read_excel(filename)
                existing_df = existing_df[existing_df['ID Nhóm'] == group_id]
                df = pd.concat([existing_df, df], ignore_index=True)
            except Exception as e:
                logging.error(f"Error reading existing Excel file: {e}")
        
        try:
            with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Sheet1')
                
                workbook = writer.book
                worksheet = writer.sheets['Sheet1']
                
                red_format = workbook.add_format({'font_color': 'red'})
                
                for row_num, (violation, violation_dur) in enumerate(zip(df['Vi phạm'], df['Thời gian vi phạm (phút)']), start=1):
                    if violation == 'Có':
                        worksheet.write(row_num, df.columns.get_loc('Vi phạm'), violation, red_format)
                        worksheet.write(row_num, df.columns.get_loc('Thời gian vi phạm (phút)'), violation_dur, red_format)
                    else:
                        worksheet.write(row_num, df.columns.get_loc('Vi phạm'), violation)
                        worksheet.write(row_num, df.columns.get_loc('Thời gian vi phạm (phút)'), violation_dur)
                        
            success = True
        except Exception as e:
            logging.error(f"Error writing to Excel file: {e}")
            temp_filename = f"{filename}.temp"
            try:
                df.to_excel(temp_filename, index=False)
                if os.path.exists(filename):
                    os.remove(filename)
                os.rename(temp_filename, filename)
                success = True
            except Exception as e2:
                logging.error(f"Error writing to temp file: {e2}")
                
    except Exception as e:
        logging.error(f"Error in record_activity: {e}")
        logging.error(f"Group ID: {group_id}, User ID: {user_id}, Action: {action}")
    return success

async def update_countdown(user_id, chat_id, message_id, action, time_limit, context):
    """Update countdown timer."""
    try:
        if user_id not in user_states:
            return
        
        start_time = user_states[user_id]['start_time']
        end_time = start_time + timedelta(minutes=time_limit)
        now = datetime.now()
        
        remaining = (end_time - now).total_seconds()
        
        if remaining > 60:
            wait_time = remaining - 60
            await asyncio.sleep(wait_time)
            
            if user_id not in user_states or user_states[user_id]['status'] != 'active':
                return
                
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️⏳ CẢNH BÁO: Hoạt động {action} còn 1 phút nữa sẽ hết thời gian cho phép!",
                reply_to_message_id=message_id
            )
            remaining = 60
        
        if remaining > 20:
            wait_time = remaining - 20
            await asyncio.sleep(wait_time)
            
            if user_id not in user_states or user_states[user_id]['status'] != 'active':
                return
                
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'🚨 CẢNH BÁO KHẨN CẤP: Hoạt động {action} chỉ còn 20 giây nữa!\nẤn quay về ngay lập tức!',
                reply_to_message_id=message_id
            )
            remaining = 20
        
        await asyncio.sleep(remaining)
        
        if user_id in user_states and user_states[user_id]['status'] == 'active':
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'⏰ ĐÃ HẾT THỜI GIAN CHO PHÉP!\nHoạt động: {action}\nThời gian cho phép: {time_limit} phút\nVui lòng ấn nút "Quay về" để kết thúc hoạt động.',
                reply_to_message_id=message_id
            )
            
    except Exception as e:
        logging.error(f"Error in update_countdown: {e}")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send daily report."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text('❌ Lệnh này chỉ hoạt động trong nhóm.')
        return
    
    if not (is_admin(user_id, chat_id) or is_superadmin(user_id, chat_id)):
        await update.message.reply_text('❌ Chỉ admin hoặc superadmin mới có thể sử dụng lệnh này.')
        return

    current_date = datetime.now().strftime("%Y%m%d")
    filename = f'activities_group_{chat_id}_{current_date}.xlsx'
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports', filename)
    
    if not os.path.exists(full_path):
        await update.message.reply_text('📊 Chưa có dữ liệu hoạt động nào trong ngày.')
        return
        
    if filename.startswith('~$'):
        await update.message.reply_text('📊 Chưa có dữ liệu hoạt động nào trong ngày.')
        return

    group_name = group_settings[chat_id]['group_name']
    try:
        with open(full_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f'📊 Báo cáo hoạt động ngày hôm nay - Nhóm {group_name}'
            )
    except Exception as e:
        logging.error(f"Error sending report: {e}")
        await update.message.reply_text('❌ Có lỗi xảy ra khi gửi báo cáo. Vui lòng thử lại sau.')

async def send_daily_reports_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to send daily reports."""
    try:
        current_date = datetime.now().strftime("%Y%m%d")
        
        for group_id, settings in group_settings.items():
            try:
                if not settings['is_setup']:
                    continue
                    
                group_name = settings['group_name']
                report_group_id = settings.get('report_group_id')
                
                if not report_group_id:
                    continue
                
                filename = f'activities_group_{group_id}_{current_date}.xlsx'
                full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports', filename)
                
                if not os.path.exists(full_path):
                    continue
                    
                if filename.startswith('~$'):
                    continue
                
                try:
                    with open(full_path, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=report_group_id,
                            document=f,
                            filename=filename,
                            caption=f'📊 Báo cáo hoạt động ngày {current_date} - Nhóm {group_name}'
                        )
                except Exception as e:
                    logging.error(f"Error sending report to group {group_name}: {e}")
                
            except Exception as e:
                logging.error(f"Error processing group {group_id}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"Error in send_daily_reports_job: {e}")

def main():
    """Start the bot."""
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("listadmin", list_admins))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_activity_button))

    # Lên lịch gửi báo cáo lúc 23:59 mỗi ngày (UTC+7)
    utc_plus_7 = pytz.timezone('Asia/Bangkok')
    report_time = time(hour=22, minute=18, second=0, tzinfo=utc_plus_7)
    
    application.job_queue.run_daily(
        send_daily_reports_job,
        time=report_time,
        name='daily_report',
        days=(0, 1, 2, 3, 4, 5, 6),
        job_kwargs={
            'misfire_grace_time': 300,
            'replace_existing': True
        }
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 