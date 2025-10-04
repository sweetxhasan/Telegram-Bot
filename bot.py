import os
import json
import requests
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import random
import tempfile

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "8493342513:AAFdmE1KeeKfdzu5O7jIYTNAPAcXvafHN0I"
SCRAPINGBEE_API_URL = "https://app.scrapingbee.com/api/v1/"

# Data storage files
ADMIN_FILE = "admin_data.json"
API_KEYS_FILE = "api_keys.json"
REQUESTS_FILE = "requests_data.json"
USERS_FILE = "users_data.json"
API_REQUESTS_FILE = "api_requests_data.json"

class BotDataManager:
    def __init__(self):
        self.load_all_data()
        
    def load_all_data(self):
        # Load or initialize all data files
        self.admin_data = self.load_json(ADMIN_FILE, {"admin_id": None})
        self.api_keys = self.load_json(API_KEYS_FILE, {"keys": [], "next_id": 1})
        self.requests_data = self.load_json(REQUESTS_FILE, {
            "total_requests": 0, 
            "today_requests": 0, 
            "last_reset": str(date.today())
        })
        self.users_data = self.load_json(USERS_FILE, {"users": {}})
        self.api_requests = self.load_json(API_REQUESTS_FILE, {"requests": [], "next_id": 1})

    def load_json(self, filename, default_data):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default_data

    def save_json(self, data, filename):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            return False

    def save_admin_data(self):
        return self.save_json(self.admin_data, ADMIN_FILE)

    def save_api_keys(self):
        return self.save_json(self.api_keys, API_KEYS_FILE)

    def save_requests_data(self):
        return self.save_json(self.requests_data, REQUESTS_FILE)

    def save_users_data(self):
        return self.save_json(self.users_data, USERS_FILE)

    def save_api_requests(self):
        return self.save_json(self.api_requests, API_REQUESTS_FILE)

    def reset_daily_requests_if_needed(self):
        today = str(date.today())
        if self.requests_data.get("last_reset") != today:
            self.requests_data["today_requests"] = 0
            self.requests_data["last_reset"] = today
            self.save_requests_data()

    def increment_requests(self):
        self.reset_daily_requests_if_needed()
        self.requests_data["total_requests"] += 1
        self.requests_data["today_requests"] += 1
        self.save_requests_data()

    def add_api_key(self, api_key):
        # Find the maximum existing ID
        existing_ids = [key["id"] for key in self.api_keys["keys"]]
        new_id = max(existing_ids) + 1 if existing_ids else 1
        
        key_data = {
            "id": new_id,
            "key": api_key.strip(),
            "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.api_keys["keys"].append(key_data)
        self.save_api_keys()
        return new_id

    def delete_api_key(self, api_id):
        self.api_keys["keys"] = [key for key in self.api_keys["keys"] if key["id"] != api_id]
        self.save_api_keys()

    def get_random_api_key(self):
        if not self.api_keys["keys"]:
            return None
        return random.choice(self.api_keys["keys"])["key"]

    def add_or_update_user(self, user_id, user_name):
        user_id_str = str(user_id)
        if user_id_str not in self.users_data["users"]:
            self.users_data["users"][user_id_str] = {
                "name": user_name,
                "join_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "api_requests_count": 0
            }
        else:
            # Update user name if changed
            self.users_data["users"][user_id_str]["name"] = user_name
        self.save_users_data()

    def increment_user_requests(self, user_id):
        user_id_str = str(user_id)
        if user_id_str in self.users_data["users"]:
            self.users_data["users"][user_id_str]["api_requests_count"] += 1
            self.save_users_data()

    def get_users_count(self):
        return len(self.users_data["users"])

    def add_api_request(self, user_id, user_name, url, status, response_code=None, error_msg=None):
        request_data = {
            "id": self.api_requests["next_id"],
            "user_id": user_id,
            "user_name": user_name,
            "url": url,
            "status": status,
            "response_code": response_code,
            "error_msg": error_msg,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.api_requests["requests"].insert(0, request_data)
        self.api_requests["next_id"] += 1
        
        # Keep only last 100 requests
        if len(self.api_requests["requests"]) > 100:
            self.api_requests["requests"] = self.api_requests["requests"][:100]
        
        self.save_api_requests()
        return request_data["id"]

# Initialize data manager
data_manager = BotDataManager()

# User states for conversation handling
USER_STATES = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    # Set first user as admin
    if data_manager.admin_data.get("admin_id") is None:
        data_manager.admin_data["admin_id"] = user_id
        data_manager.save_admin_data()
        await update.message.reply_text("🎉 You are now the admin!")
    
    # Add/update user data
    data_manager.add_or_update_user(user_id, user_name)
    
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    welcome_text = "🤖 **HTML Secure Code Downloader**"
    
    keyboard = []
    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin_dashboard")])
    
    keyboard.append([InlineKeyboardButton("🚀 Start Code Download", callback_data="start_download")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    if data == "start_download":
        USER_STATES[user_id] = "waiting_for_url"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Enter website URL:", reply_markup=reply_markup)
    
    elif data == "admin_dashboard" and is_admin:
        await show_admin_dashboard(query)
    
    elif data == "add_api_key" and is_admin:
        USER_STATES[user_id] = "waiting_for_api_key"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Enter your API key:", reply_markup=reply_markup)
    
    elif data == "api_key_list" and is_admin:
        await show_api_key_list(query)
    
    elif data == "delete_api_key" and is_admin:
        USER_STATES[user_id] = "waiting_for_api_id"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Enter API ID to delete:", reply_markup=reply_markup)
    
    elif data == "user_list" and is_admin:
        await show_user_list(query)
    
    elif data == "api_requests_list" and is_admin:
        await show_api_requests_list(query)
    
    elif data == "back_to_main":
        await show_main_menu(update, context)
    
    elif data == "back_to_dashboard" and is_admin:
        await show_admin_dashboard(query)
    
    elif data == "new_download":
        USER_STATES[user_id] = "waiting_for_url"
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Enter website URL:", reply_markup=reply_markup)
    
    elif data == "cancel_operation":
        USER_STATES.pop(user_id, None)
        if is_admin:
            await show_admin_dashboard(query)
        else:
            await show_main_menu(update, context)

async def show_admin_dashboard(query):
    data_manager.reset_daily_requests_if_needed()
    
    total_requests = data_manager.requests_data["total_requests"]
    today_requests = data_manager.requests_data["today_requests"]
    api_key_count = len(data_manager.api_keys["keys"])
    users_count = data_manager.get_users_count()
    
    dashboard_text = (
        "👑 **Admin Dashboard**\n\n"
        f"📊 API Keys: `{api_key_count}`\n"
        f"📈 Total Requests: `{total_requests}`\n"
        f"📅 Today's Requests: `{today_requests}`\n"
        f"👥 Users: `{users_count}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add API Key", callback_data="add_api_key")],
        [InlineKeyboardButton("📋 API Key List", callback_data="api_key_list")],
        [InlineKeyboardButton("🗑️ Delete API Key", callback_data="delete_api_key")],
        [InlineKeyboardButton("👥 User List", callback_data="user_list")],
        [InlineKeyboardButton("📋 API Requests", callback_data="api_requests_list")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(dashboard_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_api_key_list(query):
    api_keys = data_manager.api_keys["keys"]
    
    if not api_keys:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ No API Keys", reply_markup=reply_markup)
        return
    
    key_list_text = "📋 **API Keys:**\n\n"
    for key_data in api_keys:
        masked_key = key_data["key"][:8] + "..." + key_data["key"][-4:]
        key_list_text += f"#`{key_data['id']}` - `{masked_key}` - {key_data['added_date']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(key_list_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_user_list(query):
    users = data_manager.users_data["users"]
    
    if not users:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ No Users", reply_markup=reply_markup)
        return
    
    user_list_text = "👥 **Users:**\n\n"
    for user_id, user_data in list(users.items())[:20]:
        user_list_text += f"#`{user_id}` - {user_data['name']} - Requests: {user_data['api_requests_count']} - {user_data['join_date']}\n"
    
    if len(users) > 20:
        user_list_text += f"\n... and {len(users) - 20} more"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(user_list_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_api_requests_list(query):
    requests = data_manager.api_requests["requests"]
    
    if not requests:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ No Requests", reply_markup=reply_markup)
        return
    
    requests_text = "📋 **API Requests:**\n\n"
    for req in requests[:15]:
        status_emoji = "✅" if req["status"] == "success" else "❌"
        short_url = req['url'][:30] + "..." if len(req['url']) > 30 else req['url']
        error_info = f" - {req['error_msg']}" if req.get('error_msg') else ""
        requests_text += f"#{req['id']} {status_emoji} - {short_url} - {req['user_name']} - {req['date'][:16]}{error_info}\n"
    
    if len(requests) > 15:
        requests_text += f"\n... and {len(requests) - 15} more"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(requests_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    if user_id not in USER_STATES:
        await show_main_menu(update, context)
        return
    
    state = USER_STATES[user_id]
    
    if state == "waiting_for_url":
        await handle_url_input(update, context, message_text)
    elif state == "waiting_for_api_key":
        await handle_api_key_input(update, context, message_text)
    elif state == "waiting_for_api_id":
        await handle_api_id_input(update, context, message_text)

async def handle_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    
    # Validate and clean URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Remove any extra spaces or quotes
    url = url.strip().strip('"').strip("'")
    
    processing_msg = await update.message.reply_text("⏳ Fetching HTML code...")
    
    try:
        # Get random API key
        api_key = data_manager.get_random_api_key()
        if not api_key:
            await processing_msg.edit_text("❌ No API keys available. Please add API keys first.")
            USER_STATES.pop(user_id, None)
            await show_main_menu(update, context)
            return
        
        # Prepare API request with proper parameters
        params = {
            'api_key': api_key,
            'url': url,
            'premium_proxy': 'false',
            'render_js': 'false',
            'timeout': '30000'
        }
        
        # Make request to ScrapingBee API with proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(
            SCRAPINGBEE_API_URL, 
            params=params, 
            headers=headers,
            timeout=30
        )
        
        # Check if response is valid HTML
        if response.status_code == 200 and response.text:
            # Check if response is actually HTML and not an error page
            if any(tag in response.text.lower() for tag in ['<html', '<!doctype', '<body']):
                data_manager.increment_requests()
                data_manager.increment_user_requests(user_id)
                
                html_content = response.text
                
                # Create unique filename
                domain = url.split('//')[-1].split('/')[0].replace('.', '-')
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{domain}-hasan-tool-{timestamp}.html"
                
                # Log successful API request
                data_manager.add_api_request(user_id, user_name, url, "success", response.status_code)
                
                # Create temporary file and send
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.html', delete=False) as temp_file:
                    temp_file.write(html_content)
                    temp_file_path = temp_file.name
                
                try:
                    # Send HTML file
                    with open(temp_file_path, 'rb') as file:
                        await update.message.reply_document(
                            document=file,
                            filename=filename,
                            caption=f"✅ Successfully downloaded: `{url}`"
                        )
                    
                    # Show options
                    keyboard = [
                        [InlineKeyboardButton("🔄 New Download", callback_data="new_download")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text("Choose:", reply_markup=reply_markup)
                    
                finally:
                    # Clean up temporary file
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass
                
            else:
                # Response doesn't contain HTML tags - likely an API error
                error_msg = "API returned non-HTML content"
                data_manager.add_api_request(user_id, user_name, url, "failed", response.status_code, error_msg)
                await processing_msg.edit_text("❌ Error: API returned invalid content")
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Choose:", reply_markup=reply_markup)
                
        else:
            # API request failed
            error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
            data_manager.add_api_request(user_id, user_name, url, "failed", response.status_code, error_msg)
            await processing_msg.edit_text(f"❌ Error: {error_msg}")
            
            keyboard = [
                [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Choose:", reply_markup=reply_markup)
            
    except requests.exceptions.Timeout:
        error_msg = "Request timeout"
        data_manager.add_api_request(user_id, user_name, url, "failed", None, error_msg)
        await processing_msg.edit_text("❌ Error: Request timeout")
        
        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose:", reply_markup=reply_markup)
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Request error: {str(e)}"
        data_manager.add_api_request(user_id, user_name, url, "failed", None, error_msg)
        await processing_msg.edit_text(f"❌ Error: {str(e)}")
        
        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose:", reply_markup=reply_markup)
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        data_manager.add_api_request(user_id, user_name, url, "failed", None, error_msg)
        await processing_msg.edit_text(f"❌ Error: {str(e)}")
        
        keyboard = [
            [InlineKeyboardButton("🔄 Try Again", callback_data="new_download")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose:", reply_markup=reply_markup)
    
    finally:
        USER_STATES.pop(user_id, None)

async def handle_api_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE, api_key: str):
    user_id = update.effective_user.id
    
    if len(api_key) < 10:
        await update.message.reply_text("❌ Invalid API key")
        return
    
    new_id = data_manager.add_api_key(api_key)
    
    await update.message.reply_text(f"✅ API Key added! ID: `{new_id}`")
    
    USER_STATES.pop(user_id, None)
    await show_admin_dashboard_from_message(update)

async def handle_api_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE, api_id: str):
    user_id = update.effective_user.id
    
    try:
        api_id_int = int(api_id)
        existing_ids = [key["id"] for key in data_manager.api_keys["keys"]]
        
        if api_id_int not in existing_ids:
            await update.message.reply_text("❌ API ID not found")
            return
        
        data_manager.delete_api_key(api_id_int)
        await update.message.reply_text(f"✅ API Key deleted! ID: `{api_id_int}`")
        
    except ValueError:
        await update.message.reply_text("❌ Enter valid ID")
    
    finally:
        USER_STATES.pop(user_id, None)
        await show_admin_dashboard_from_message(update)

async def show_admin_dashboard_from_message(update: Update):
    user_id = update.effective_user.id
    is_admin = data_manager.admin_data.get("admin_id") == user_id
    
    if not is_admin:
        await show_main_menu(update, None)
        return
    
    data_manager.reset_daily_requests_if_needed()
    
    total_requests = data_manager.requests_data["total_requests"]
    today_requests = data_manager.requests_data["today_requests"]
    api_key_count = len(data_manager.api_keys["keys"])
    users_count = data_manager.get_users_count()
    
    dashboard_text = (
        "👑 **Admin Dashboard**\n\n"
        f"📊 API Keys: `{api_key_count}`\n"
        f"📈 Total Requests: `{total_requests}`\n"
        f"📅 Today's Requests: `{today_requests}`\n"
        f"👥 Users: `{users_count}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Add API Key", callback_data="add_api_key")],
        [InlineKeyboardButton("📋 API Key List", callback_data="api_key_list")],
        [InlineKeyboardButton("🗑️ Delete API Key", callback_data="delete_api_key")],
        [InlineKeyboardButton("👥 User List", callback_data="user_list")],
        [InlineKeyboardButton("📋 API Requests", callback_data="api_requests_list")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(dashboard_text, reply_markup=reply_markup, parse_mode='Markdown')

def main():
    try:
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Start the bot - Railway compatible
        port = int(os.environ.get('PORT', 8443))
        print(f"🤖 Bot is running on port {port}...")
        
        # Use webhook for production
        if "RAILWAY_STATIC_URL" in os.environ:
            # Railway specific webhook setup
            webhook_url = f"{os.environ['RAILWAY_STATIC_URL']}/{BOT_TOKEN}"
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=BOT_TOKEN,
                webhook_url=webhook_url
            )
        else:
            # Local polling for development
            application.run_polling()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()