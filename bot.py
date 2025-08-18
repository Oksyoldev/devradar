import os
import asyncio
import re
import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, Chat
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    ContextTypes,
    ConversationHandler
)
from dotenv import load_dotenv
from db import posts_col, users_col, channels_col
from filters import text_matches_filters, normalize

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = []
try:
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    if admin_ids_str:
        ADMIN_IDS = [int(id_str.strip()) for id_str in admin_ids_str.split(",") if id_str.strip()]
except Exception as e:
    print(f"Ошибка при загрузке ADMIN_IDS: {e}")

print(f"Загружены ID администраторов: {ADMIN_IDS}")

if not ADMIN_IDS:
    print("ADMIN_IDS не найдены в .env файле!")

ASK_COUNT, ASK_WORDS = range(2)
MANAGE_FILTERS, DELETE_FILTER = range(2, 4)
ADD_CHANNEL_INPUT = 5
CONFIRM_CHANNEL = 6
MAX_FILTERS = 10
ADD_CHANNEL = 5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я — бот DevRadar, твой помощник в поиске работы в IT-сфере.\n"
        "Я отслеживаю десятки каналов с вакансиями и присылаю тебе только те предложения, "
        "которые соответствуют твоим критериям.\n\n"
        "✨ <b>Основные возможности:</b>\n"
        "• Добавление персональных фильтров для поиска вакансий\n"
        "• Уведомления о новых подходящих вакансиях\n"
        "• Управление своими фильтрами\n"
        "• Просмотр отслеживаемых каналов\n\n"
        "🚀 <b>Чтобы начать:</b>\n"
        "1. Добавь фильтры командой /add_filter\n"
        "2. Настрой уведомления\n"
        "3. Получай релевантные вакансии!\n\n"
        "📌 <b>Основные команды:</b>\n"
        "/add_filter - добавить фильтр для поиска\n"
        "/manage - управление фильтрами\n"
        "/channels - список отслеживаемых каналов\n"
        "/help - помощь и инструкции\n\n"
        "Начни с команды /add_filter чтобы создать свой первый фильтр!"
    )
    
    await update.message.reply_text(
        welcome_message,
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def add_filter_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await users_col.find_one({"user_id": user_id})
    
    if user_data and len(user_data.get("filters_list", [])) >= MAX_FILTERS:
        await update.message.reply_text(
            "Достигнут лимит в 10 фильтров. Удалите старые фильтры командой /manage",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    keyboard = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        ["10"]
    ]
    await update.message.reply_text(
        "🔍 Давайте создадим новый фильтр!\n"
        "Сколько ключевых слов должно быть в фильтре? (1-10)\n\n"
        "<i>Пример: для фильтра \"Python удалённая работа\" нужно выбрать 3 слова</i>",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, 
            one_time_keyboard=True, 
            resize_keyboard=True
        ),
        parse_mode='HTML'
    )
    return ASK_COUNT

async def ask_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        count = int(update.message.text)
        if count < 1 or count > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, выберите число от 1 до 10:")
        return ASK_COUNT
    
    context.user_data["count"] = count
    
    word_text = "слово" if count == 1 else "слова"
    await update.message.reply_text(
        f"Введите {count} {word_text} для фильтра через запятую:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_WORDS

async def save_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = context.user_data.get("count")
    
    if not count:
        await update.message.reply_text("Ошибка! Начните снова командой /start")
        return ConversationHandler.END
    
    words = [w.strip() for w in update.message.text.split(",")]
    
    if len(words) != count:
        await update.message.reply_text(
            f"Ошибка! Нужно ввести {count} слов. Попробуйте еще раз:"
        )
        return ASK_WORDS
    
    new_filter = [[word] for word in words]
    
    await users_col.update_one(
        {"user_id": user_id},
        {"$push": {"filters_list": {"$each": [new_filter], "$slice": -MAX_FILTERS}}},
        upsert=True
    )
    
    user_data = await users_col.find_one({"user_id": user_id})
    filter_count = len(user_data.get("filters_list", []))
    
    await update.message.reply_text(
        f"✅ Фильтр добавлен! Всего фильтров: {filter_count}/{MAX_FILTERS}\n"
        "Используйте /manage для управления фильтрами"
    )
    
    return ConversationHandler.END

async def manage_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        user_data = await users_col.find_one({"user_id": user_id})
        
        if not user_data or not user_data.get("filters_list"):
            await update.message.reply_text("У вас нет сохраненных фильтров.")
            return ConversationHandler.END
        
        filters = user_data["filters_list"]
        response = ["📋 Ваши фильтры:"]
        
        for i, f in enumerate(filters, 1):
            words = [group[0] for group in f]
            response.append(f"{i}. {', '.join(words)}")
        
        response.append("\nОтправьте номер фильтра для удаления или /cancel для отмены")
        await update.message.reply_text("\n".join(response))
        
        return DELETE_FILTER
    except Exception as e:
        print(f"Ошибка в manage_filters: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при обработке команды. Попробуйте позже.")
        return ConversationHandler.END

async def delete_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    try:
        filter_num = int(update.message.text)
        if filter_num < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите номер фильтра:")
        return DELETE_FILTER
    
    user_data = await users_col.find_one({"user_id": user_id})
    if not user_data or not user_data.get("filters_list"):
        await update.message.reply_text("Фильтры не найдены")
        return ConversationHandler.END
    
    filters = user_data["filters_list"]
    if filter_num > len(filters):
        await update.message.reply_text("Неверный номер фильтра")
        return DELETE_FILTER
    
    del filters[filter_num-1]
    
    await users_col.update_one(
        {"user_id": user_id},
        {"$set": {"filters_list": filters}}
    )
    
    await update.message.reply_text(f"Фильтр #{filter_num} удален!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        channel_post = update.channel_post
        if not channel_post or not channel_post.text:
            return

        chat = channel_post.chat
        channel_id = chat.id
        channel_username = f"@{chat.username}" if chat.username else None
        channel_title = chat.title

        channel_in_db = await channels_col.find_one({
            "$or": [
                {"channel_id": channel_id},
                {"channel_username": channel_username},
                {"channel_title": channel_title}
            ]
        })
        
        if not channel_in_db:
            print(f"Пост из неподдерживаемого канала: {channel_title} (ID: {channel_id}, {channel_username})")
            return

        text = channel_post.text
        message_id = channel_post.message_id

        exists = await posts_col.find_one({"channel_id": channel_id, "message_id": message_id})
        if exists:
            return

        await posts_col.insert_one({
            "channel_id": channel_id,
            "channel_username": channel_username,
            "channel_title": channel_title,
            "message_id": message_id,
            "text": text,
            "processed_at": datetime.datetime.utcnow()
        })

        if channel_username:
            username = channel_username.lstrip('@')
            post_link = f"https://t.me/{username}/{message_id}"
        else:
            channel_id_num = str(channel_id).replace('-100', '')
            post_link = f"https://t.me/c/{channel_id_num}/{message_id}"

        async for user in users_col.find({}):
            if "filters_list" not in user:
                continue
                
            for user_filter in user["filters_list"]:
                try:
                    if text_matches_filters(text, user_filter):
                        try:
                            await context.bot.forward_message(
                                chat_id=user["user_id"],
                                from_chat_id=channel_id,
                                message_id=message_id
                            )
                        except Exception as e:
                            print(f"Не удалось переслать сообщение пользователю {user['user_id']}: {e}")
                            highlighted_text = text
                            for group in user_filter:
                                for word in group:
                                    for variant in normalize(word):
                                        if variant.lower() in text.lower():
                                            pattern = re.compile(re.escape(variant), re.IGNORECASE)
                                            highlighted_text = pattern.sub(f'<b>{variant}</b>', highlighted_text)
                            
                            await context.bot.send_message(
                                chat_id=user["user_id"],
                                text=(f"🔔 <b>Новый пост в канале {channel_title}</b>\n\n"
                                      f"{highlighted_text}\n\n"
                                      f"<a href='{post_link}'>Ссылка на пост</a>"),
                                parse_mode='HTML',
                                disable_web_page_preview=True
                            )
                        break
                except Exception as e:
                    print(f"Ошибка при обработке фильтра для пользователя {user['user_id']}: {e}")
                    continue
                    
    except Exception as e:
        print(f"Критическая ошибка в handle_channel_post: {e}")

async def list_tracked_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = []
    async for channel in channels_col.find({}):
        channel_title = channel.get("channel_title", "Без названия")
        channel_id = channel.get("channel_id", "N/A")
        username = channel.get("channel_username")
        added_date = channel.get("added_at", datetime.datetime.utcnow())
        
        formatted_date = added_date.strftime("%d.%m.%Y")
        
        if username:
            clean_username = username.lstrip('@')
            channel_str = (
                f"• <a href='https://t.me/{clean_username}'>{channel_title}</a> "
                f"(@{clean_username})\n"
                f"<i>Добавлен: {formatted_date}</i>"
            )
        else:
            if f"ID: {channel_id}" in channel_title:
                display_text = channel_title
            else:
                display_text = f"{channel_title} (ID: {channel_id})"
                
            channel_str = (
                f"• {display_text}\n"
                f"<i>Добавлен: {formatted_date}</i>"
            )
        
        channels.append(channel_str)
    
    if channels:
        response = (
            f"📢 <b>Каналы, отслеживаемые ботом:</b>\n\n" +
            "\n\n".join(channels) +
            f"\n\nВсего каналов: <b>{len(channels)}</b>"
        )
    else:
        response = "ℹ️ Нет отслеживаемых каналов"
    
    await update.message.reply_text(response, parse_mode='HTML', disable_web_page_preview=True)


async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Введите ссылку на канал, юзернейм (@username) или ID канала:\n"
        "Примеры:\n"
        "- https://t.me/jobjobjob7\n"
        "- @jobjobjob7\n"
        "- -1001234567890"
    )
    return ADD_CHANNEL

async def process_channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    channel_identifier = None
    
    if user_input.startswith("https://t.me/"):
        channel_identifier = user_input.split("/")[-1]
    elif user_input.startswith("@"):
        channel_identifier = user_input
    elif user_input.startswith("-100"):
        try:
            channel_id = int(user_input)
            channel_identifier = channel_id
        except ValueError:
            await update.message.reply_text("Неверный формат ID канала. Попробуйте еще раз:")
            return ADD_CHANNEL
    else:
        if user_input.isdigit() or (user_input.startswith('-') and user_input[1:].isdigit()):
            try:
                channel_identifier = int(user_input)
            except ValueError:
                await update.message.reply_text("Неверный формат ID канала. Попробуйте еще раз:")
                return ADD_CHANNEL
        else:
            channel_identifier = f"@{user_input}" if not user_input.startswith("@") else user_input
    
    context.user_data["channel_identifier"] = channel_identifier
    
    try:
        await asyncio.sleep(3)
        
        try:
            chat = await context.bot.get_chat(chat_id=channel_identifier)
        except Exception as e:
            print(f"Ошибка при получении чата: {e}")
            if isinstance(channel_identifier, int):
                try:
                    await context.bot.get_chat_member(chat_id=channel_identifier, user_id=context.bot.id)
                except Exception as e:
                    await update.message.reply_text(
                        "Бот не добавлен в канал! "
                        "Добавьте бота как администратора с правом 'Размещать сообщения' и повторите попытку."
                    )
                    return ConversationHandler.END
                chat = await context.bot.get_chat(chat_id=channel_identifier)
            else:
                raise e
        
        if chat.type != Chat.CHANNEL:
            await update.message.reply_text("Это не канал! Попробуйте другой идентификатор:")
            return ADD_CHANNEL
        
        channel_info = {
            "id": chat.id,
            "username": f"@{chat.username}" if chat.username else None,
            "title": chat.title
        }
        
        context.user_data["channel_info"] = channel_info
        
        await update.message.reply_text(
            f"Найден канал: {chat.title}\n"
            f"ID: {chat.id}\n"
            f"Username: @{chat.username or 'отсутствует'}\n\n"
            "Отправьте 'да' для подтверждения добавления или 'нет' для отмены:"
        )
        return CONFIRM_CHANNEL
    
    except Exception as e:
        print(f"Общая ошибка: {e}")
        if isinstance(channel_identifier, int) or (isinstance(channel_identifier, str) and channel_identifier.replace('-', '').isdigit()):
            channel_id = int(channel_identifier) if isinstance(channel_identifier, str) else channel_identifier
            
            try:
                chat = await context.bot.get_chat(chat_id=channel_id)
                channel_title = chat.title
            except:
                channel_title = f"Канал ID: {channel_id}"
            
            context.user_data["channel_info"] = {
                "id": channel_id,
                "username": None,
                "title": channel_title
            }
            
            await update.message.reply_text(
                f"Не удалось полностью проверить канал, но ID получен.\n"
                f"Название: {channel_title}\n\n"
                "Отправьте 'да' для подтверждения добавления или 'нет' для отмены:"
            )
            return CONFIRM_CHANNEL
        else:
            await update.message.reply_text(
                f"Ошибка при получении информации о канале: {e}\n"
                "Убедитесь, что:\n"
                "1. Канал существует\n"
                "2. Бот добавлен как администратор\n"
                "3. У бота есть право 'Размещать сообщения'\n\n"
                "Попробуйте еще раз:"
            )
            return ADD_CHANNEL

async def check_bot_admin(context, chat_id):
    try:
        members = await context.bot.get_chat_administrators(chat_id)
        for member in members:
            if member.user.id == context.bot.id:
                return True
        return False
    except Exception as e:
        print(f"Ошибка проверки прав: {e}")
        return False

async def force_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /force_add_channel <ID канала>")
        return
    
    try:
        channel_id = int(context.args[0])
        
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            channel_title = chat.title
            channel_username = f"@{chat.username}" if chat.username else None
        except:
            channel_title = f"Канал ID: {channel_id}"
            channel_username = None
        
        existing = await channels_col.find_one({"channel_id": channel_id})
        if existing:
            await update.message.reply_text("ℹ️ Этот канал уже добавлен.")
            return
        
        await channels_col.insert_one({
            "channel_id": channel_id,
            "channel_username": channel_username,
            "channel_title": channel_title,
            "added_by": user_id,
            "added_at": datetime.datetime.utcnow()
        })
        
        await update.message.reply_text(f"Канал добавлен! Название: {channel_title}")
    except ValueError:
        await update.message.reply_text("Неверный формат ID канала. Должен быть числом.")

async def confirm_channel_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.lower()
    channel_info = context.user_data.get("channel_info")
    
    if not channel_info:
        await update.message.reply_text("Ошибка! Начните заново командой /add_channel")
        return ConversationHandler.END
    
    if response == "да":
        existing_channel = await channels_col.find_one({
            "$or": [
                {"channel_id": channel_info["id"]},
                {"channel_username": channel_info["username"]}
            ]
        })
        
        if existing_channel:
            await update.message.reply_text("Этот канал уже добавлен в систему.")
            return ConversationHandler.END
        
        await channels_col.insert_one({
            "channel_id": channel_info["id"],
            "channel_username": channel_info["username"],
            "channel_title": channel_info["title"],
            "added_by": update.effective_user.id,
            "added_at": datetime.datetime.utcnow()
    })
        
        await update.message.reply_text(
            f"Канал успешно добавлен!\n"
            f"Название: {channel_info['title']}\n"
            f"ID: {channel_info['id']}\n"
            f"Username: {channel_info['username'] or 'отсутствует'}"
        )
    else:
        await update.message.reply_text("Добавление канала отменено.")
    
    return ConversationHandler.END

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    channels = []
    async for channel in channels_col.find({}):
        channels.append(
            f"📢 {channel.get('channel_title', 'Без названия')}\n"
            f"ID: {channel['channel_id']}\n"
            f"Username: {channel.get('channel_username', 'отсутствует')}\n"
            f"Добавлен: {channel.get('added_at', 'неизвестно')}"
        )

    if not channels:
        await update.message.reply_text("ℹ️ Нет добавленных каналов.")
        return

    response = "📢 <b>Добавленные каналы:</b>\n\n" + "\n\n".join(channels)
    await update.message.reply_text(response, parse_mode='HTML')

async def delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /delete_channel <ID канала>")
        return

    try:
        channel_id = int(context.args[0])
        result = await channels_col.delete_one({"channel_id": channel_id})
        if result.deleted_count > 0:
            await update.message.reply_text(f"Канал с ID {channel_id} удален.")
        else:
            await update.message.reply_text(f"Канал с ID {channel_id} не найден.")
    except ValueError:
        await update.message.reply_text("Неверный формат ID канала. Должен быть числом.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 <b>Помощь по использованию бота DevRadar</b>\n\n"
        "🔍 <b>Как это работает?</b>\n"
        "1. Вы добавляете фильтры с ключевыми словами (например: Python, удалённо, junior)\n"
        "2. Бот отслеживает новые посты в каналах с вакансиями\n"
        "3. Когда находится вакансия, соответствующая вашему фильтру, вы получаете уведомление\n\n"
        "📌 <b>Основные команды:</b>\n"
        "/start - начать работу с ботом\n"
        "/add_filter - добавить новый фильтр\n"
        "/manage - управление вашими фильтрами\n"
        "/channels - список отслеживаемых каналов\n\n"
        "⚙️ <b>Ограничения:</b>\n"
        "• Максимум 10 фильтров\n"
        "• В каждом фильтре от 1 до 10 слов\n\n"
        "💡 <b>Советы:</b>\n"
        "• Используйте конкретные ключевые слова\n"
        "• Разделяйте слова запятыми при добавлении фильтра\n"
        "• Комбинируйте технологии и условия работы\n\n"
        "Если у вас остались вопросы, обратитесь к администратору: @oksyol | @tozhest"
    )
    
    await update.message.reply_text(help_text, parse_mode='HTML')

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    add_filter_conv = ConversationHandler(
        entry_points=[CommandHandler("add_filter", add_filter_start)],
        states={
            ASK_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_words)],
            ASK_WORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_filter)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={
            ConversationHandler.END: ConversationHandler.END
        }
    )
    
    manage_conv = ConversationHandler(
        entry_points=[CommandHandler("manage", manage_filters)],
        states={
            DELETE_FILTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_filter)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    add_channel_conv = ConversationHandler(
        entry_points=[CommandHandler("add_channel", add_channel_command)],
        states={
            ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_channel_input)],  # Исправлено состояние
            CONFIRM_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_channel_addition)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_filter_conv)
    app.add_handler(CommandHandler("channels", list_tracked_channels))
    app.add_handler(manage_conv)
    app.add_handler(CommandHandler("list_channels", list_channels))
    app.add_handler(CommandHandler("delete_channel", delete_channel))
    app.add_handler(CommandHandler("force_add_channel", force_add_channel))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(add_channel_conv)
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_channel_post))
    
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    import platform
    import asyncio
    import datetime
    
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    main()