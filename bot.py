import asyncio
import logging
import json
from datetime import datetime
try:
    import aiomysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("aiomysql не установлен. Будет использовано хранение в памяти.")
    print("Для установки: pip install aiomysql")

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, LabeledPrice, PreCheckoutQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота PROD HELPER
BOT_TOKEN = "7774438388:AAFqNtwBqzwRz55bwHbo5a7J7AcIrd2GoJ8"

# Стоимость подписки в звёздах
SUBSCRIPTION_PRICE = 1 #788

# Настройки базы данных MySQL
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': 'Bilibaben9518!',
    'db': 'leilagus',
    'autocommit': True
}

# Пул подключений к MySQL
mysql_pool = None

# Словари для хранения данных в памяти в случае отсутствия MySQL
memory_users = {}
memory_user_generations = {}
memory_user_subscriptions = {}
memory_user_actions = []

# Словарь со ставками специалистов
rates = {
    'Gaffer': {
        'base': 20000,
        'overtime_1': 4000,
        'overtime_2': 8000,
        'overtime_3': 16000
    },
    'Key Grip': {
        'base': 14000,
        'overtime_1': 3200,
        'overtime_2': 6400,
        'overtime_3': 12800
    },
    'Best Boy': {
        'base': 14000,
        'overtime_1': 3200,
        'overtime_2': 6400,
        'overtime_3': 12800
    },
    'Programmer': {
        'base': 15500,
        'overtime_1': 3200,
        'overtime_2': 6400,
        'overtime_3': 12800
    },
    'Осветитель': {
        'base': 12000,
        'overtime_1': 2600,
        'overtime_2': 5200,
        'overtime_3': 10400
    },
    'Grip': {
        'base': 12000,
        'overtime_1': 2600,
        'overtime_2': 5200,
        'overtime_3': 10400
    }
}

# Определение состояний пользователя через FSM
class UserStates(StatesGroup):
    choose_specialist = State()
    choose_rates = State()
    enter_time = State()
    enter_custom_rates = State()
    idle = State()
    check_subscription = State()

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Добавим функцию для сохранения информации о пользователе
async def save_user(user_id, username=None, first_name=None, last_name=None):
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Создадим таблицу пользователей, если её еще нет
                    await cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT PRIMARY KEY,
                            username VARCHAR(255),
                            first_name VARCHAR(255),
                            last_name VARCHAR(255),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    # Проверяем, существует ли запись для данного пользователя
                    await cursor.execute('SELECT user_id FROM users WHERE user_id = %s', (user_id,))
                    result = await cursor.fetchone()
                    
                    if result:
                        # Обновляем существующую запись
                        await cursor.execute('''
                            UPDATE users 
                            SET username = %s, first_name = %s, last_name = %s, last_activity = CURRENT_TIMESTAMP
                            WHERE user_id = %s
                        ''', (username, first_name, last_name, user_id))
                    else:
                        # Создаем новую запись
                        await cursor.execute('''
                            INSERT INTO users (user_id, username, first_name, last_name)
                            VALUES (%s, %s, %s, %s)
                        ''', (user_id, username, first_name, last_name))
        except Exception as e:
            logger.error(f"Ошибка при сохранении пользователя в БД: {e}")
            # Сохраняем в память если возникла ошибка с БД
            memory_users[user_id] = {
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'created_at': datetime.now(),
                'last_activity': datetime.now()
            }
    else:
        # Сохраняем в память
        memory_users[user_id] = {
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'created_at': datetime.now(),
            'last_activity': datetime.now()
        }

# Функция для логирования действий пользователя
async def log_user_action(user_id, action_type, action_data=None):
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Создаем таблицу для логирования действий пользователя, если она еще не существует
                    await cursor.execute('''
                        CREATE TABLE IF NOT EXISTS user_actions (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            action_type VARCHAR(255) NOT NULL,
                            action_data JSON,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX (user_id),
                            INDEX (action_type),
                            INDEX (timestamp)
                        )
                    ''')
                    
                    # Логируем действие
                    await cursor.execute(
                        'INSERT INTO user_actions (user_id, action_type, action_data) VALUES (%s, %s, %s)',
                        (user_id, action_type, action_data)
                    )
        except Exception as e:
            logger.error(f"Ошибка при логировании действия в БД: {e}")
            # Сохраняем в память если возникла ошибка с БД
            memory_user_actions.append({
                'user_id': user_id,
                'action_type': action_type,
                'action_data': action_data,
                'timestamp': datetime.now()
            })
    else:
        # Сохраняем в память
        memory_user_actions.append({
            'user_id': user_id,
            'action_type': action_type,
            'action_data': action_data,
            'timestamp': datetime.now()
        })

# Инициализация базы данных
async def init_db():
    global mysql_pool
    
    if not MYSQL_AVAILABLE:
        logger.warning("MySQL не доступен. Используется хранение в памяти.")
        return
    
    try:
        mysql_pool = await aiomysql.create_pool(**DB_CONFIG)
        
        async with mysql_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Создаем таблицу для хранения информации о пользователях
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        last_name VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Создаем таблицу для хранения информации о генерациях
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_generations (
                        user_id BIGINT PRIMARY KEY,
                        count INT NOT NULL DEFAULT 0
                    )
                ''')
                
                # Создаем таблицу для хранения информации о подписках
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_subscriptions (
                        user_id BIGINT PRIMARY KEY,
                        active BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP NULL
                    )
                ''')
                
                # Создаем таблицу для логирования действий пользователя
                await cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_actions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        action_type VARCHAR(255) NOT NULL,
                        action_data JSON,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX (user_id),
                        INDEX (action_type),
                        INDEX (timestamp)
                    )
                ''')
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        mysql_pool = None
        logger.warning("Используется хранение в памяти вместо MySQL")

# Функция для получения количества генераций пользователя
async def get_user_generations(user_id):
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute('SELECT count FROM user_generations WHERE user_id = %s', (user_id,))
                    result = await cursor.fetchone()
                    if result:
                        return result[0]
                    return 0
        except Exception as e:
            logger.error(f"Ошибка при получении генераций из БД: {e}")
            # Используем данные из памяти если возникла ошибка с БД
            return memory_user_generations.get(user_id, 0)
    else:
        # Используем данные из памяти
        return memory_user_generations.get(user_id, 0)

# Функция для увеличения счетчика генераций пользователя
async def increment_user_generations(user_id):
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Проверяем, существует ли запись для данного пользователя
                    await cursor.execute('SELECT count FROM user_generations WHERE user_id = %s', (user_id,))
                    result = await cursor.fetchone()
                    
                    if result:
                        # Обновляем существующую запись
                        await cursor.execute('UPDATE user_generations SET count = count + 1 WHERE user_id = %s', (user_id,))
                    else:
                        # Создаем новую запись
                        await cursor.execute('INSERT INTO user_generations (user_id, count) VALUES (%s, 1)', (user_id,))
        except Exception as e:
            logger.error(f"Ошибка при увеличении счетчика генераций в БД: {e}")
            # Увеличиваем в памяти если возникла ошибка с БД
            memory_user_generations[user_id] = memory_user_generations.get(user_id, 0) + 1
    else:
        # Увеличиваем в памяти
        memory_user_generations[user_id] = memory_user_generations.get(user_id, 0) + 1

# Функция для проверки подписки пользователя
async def check_subscription(user_id):
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Проверяем активность подписки и не истек ли срок её действия
                    await cursor.execute('''
                        SELECT active FROM user_subscriptions 
                        WHERE user_id = %s AND active = TRUE AND 
                        (expires_at IS NULL OR expires_at > NOW())
                    ''', (user_id,))
                    result = await cursor.fetchone()
                    
                    # Если срок подписки истек, деактивируем её
                    if not result:
                        await cursor.execute('''
                            UPDATE user_subscriptions 
                            SET active = FALSE 
                            WHERE user_id = %s AND active = TRUE AND expires_at <= NOW()
                        ''', (user_id,))
                    
                    return bool(result)
        except Exception as e:
            logger.error(f"Ошибка при проверке подписки в БД: {e}")
            # Проверяем в памяти если возникла ошибка с БД
            subscription = memory_user_subscriptions.get(user_id, {})
            if subscription.get('active') and 'expires_at' in subscription:
                # Проверяем срок действия подписки
                return subscription['expires_at'] > datetime.now()
            return subscription.get('active', False)
    else:
        # Проверяем в памяти
        subscription = memory_user_subscriptions.get(user_id, {})
        if subscription.get('active') and 'expires_at' in subscription:
            # Проверяем срок действия подписки
            return subscription['expires_at'] > datetime.now()
        return subscription.get('active', False)

# Функция для активации подписки пользователя
async def activate_subscription(user_id):
    # Устанавливаем срок действия подписки - 1 месяц от текущей даты
    expires_at = datetime.now().replace(microsecond=0) + datetime.timedelta(days=30)
    
    if MYSQL_AVAILABLE and mysql_pool:
        try:
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Проверяем, существует ли запись для данного пользователя
                    await cursor.execute('SELECT user_id FROM user_subscriptions WHERE user_id = %s', (user_id,))
                    result = await cursor.fetchone()
                    
                    if result:
                        # Обновляем существующую запись
                        await cursor.execute(
                            'UPDATE user_subscriptions SET active = TRUE, expires_at = %s WHERE user_id = %s', 
                            (expires_at, user_id)
                        )
                    else:
                        # Создаем новую запись
                        await cursor.execute(
                            'INSERT INTO user_subscriptions (user_id, active, expires_at) VALUES (%s, TRUE, %s)', 
                            (user_id, expires_at)
                        )
        except Exception as e:
            logger.error(f"Ошибка при активации подписки в БД: {e}")
            # Активируем в памяти если возникла ошибка с БД
            memory_user_subscriptions[user_id] = {
                'active': True, 
                'created_at': datetime.now(),
                'expires_at': expires_at
            }
    else:
        # Активируем в памяти
        memory_user_subscriptions[user_id] = {
            'active': True, 
            'created_at': datetime.now(),
            'expires_at': expires_at
        }

# Установка команд для меню
async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="reset", description="Сбросить текущий расчет"),
        BotCommand(command="info", description="Получить информацию о проекте"),
        BotCommand(command="help", description="Показать это сообщение"),
        BotCommand(command="faq", description="Часто задаваемые вопросы"),
        BotCommand(command="support", description="Связаться с поддержкой"),
        BotCommand(command="subscribe", description="Оформить подписку")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

# Создание инлайн-клавиатуры для выбора специалиста
def get_specialists_inline_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=specialist, callback_data=specialist)] for specialist in rates.keys()
    ])
    return keyboard

# Клавиатура для выбора ставок
def get_rates_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="По файлу профсоюза", callback_data="union_rates")],
        [InlineKeyboardButton(text="По своим ставкам", callback_data="custom_rates")]
    ])
    return keyboard

# Клавиатура с кнопкой "Назад"
def get_back_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)
    return keyboard

# Клавиатура с кнопкой "Начать сначала"
def get_restart_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Начать сначала")]], resize_keyboard=True)
    return keyboard

# Основное меню
def get_main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Сделать новый просчет🔄"), KeyboardButton(text="Моя подписка💳")],
        [KeyboardButton(text="FAQ🙋🏽"), KeyboardButton(text="Поддержка📞")]
    ], resize_keyboard=True)
    return keyboard

# Инлайн-клавиатура для подписки через Telegram Stars
def get_subscription_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оформить подписку ~ 1299₽/месяц", callback_data="buy_subscription")]
    ])
    return keyboard

# Обработчик команды /start с логированием
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Сохраняем информацию о пользователе в БД
    await save_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="command_start",
        action_data=None
    )
    
    await state.set_state(UserStates.choose_specialist)
    
    welcome_message = (
        "👋 Добро пожаловать! 🎬\n\n"
        "Я бот, который поможет вам рассчитать стоимость рабочей смены для различных технических специалистов в киноиндустрии.\n\n"
        "Я пока умею просчитывать только осветителей, но обещаю в скором времени добавить другие департаменты.\n\n"
        "<b>Мы используем актуальные ставки, утвержденные профсоюзом осветителей от <a href='https://clck.ru/3EX7yh'>1 марта 2024 года</a>.</b>\n\n"
        "Также вы можете вносить в формулу вашу собственную стоимость основной ставки и прогрессивных переработок департамента.\n\n"
        "Давайте начнем!\n\n"
        "Выберите тип просчета:"
    )
    
    # Отправка изображения с текстом
    photo = FSInputFile("start.jpg")
    await message.answer_photo(photo, caption=welcome_message, reply_markup=get_specialists_inline_keyboard(), parse_mode=ParseMode.HTML)

# Обработчик выбора специалиста с логированием
@router.callback_query(lambda call: call.data in rates.keys())
async def choose_specialist(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    specialist = callback.data
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="choose_specialist",
        action_data=json.dumps({"specialist": specialist})
    )
    
    await state.update_data(specialist=specialist)
    await state.set_state(UserStates.choose_rates)
    
    await callback.message.answer("Вы хотите просчитать стоимость по файлу профсоюза или по своим ставкам?", reply_markup=get_rates_keyboard())
    await callback.answer()

# Обработчик выбора ставок с логированием
@router.callback_query(lambda call: call.data in ["union_rates", "custom_rates"])
async def choose_rates(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    rate_type = callback.data
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="choose_rates",
        action_data=json.dumps({"rate_type": rate_type})
    )
    
    # Проверяем, был ли уже использован бесплатный расчет
    user_generations_count = await get_user_generations(user_id)
    
    if user_generations_count == 0:
        if callback.data == "union_rates":
            await state.set_state(UserStates.enter_time)
            photo = FSInputFile("dates.jpg")
            await callback.message.answer_photo(photo, caption="Введите дату и время съемок в формате: <b>10:00 23.01.24 - 11:00 24.01.24</b>\n\n<b>❗Пожалуйста, соблюдайте точный формат — даже одна лишняя точка или пробел собьёт расчет.</b>", reply_markup=get_back_keyboard(), parse_mode=ParseMode.HTML)
        elif callback.data == "custom_rates":
            await state.set_state(UserStates.enter_custom_rates)
            message_text = (
                "Мы учитываем, что не все работают по ставкам Профсоюза, в связи с чем вы можете внести в формулу просчета индивидуальные ставки.\n\n"
                "Для этого вам необходимо в следующем сообщении написать через запятую: <b>ставку за основную смену и стоимость часа каждого прогрессива.</b>\n\n"
            )
            photo = FSInputFile("price.jpg")
            await callback.message.answer_photo(photo, caption=message_text, reply_markup=get_back_keyboard())
    else:
        # Проверка подписки пользователя
        has_subscription = await check_subscription(user_id)
        if has_subscription:
            if callback.data == "union_rates":
                await state.set_state(UserStates.enter_time)
                photo = FSInputFile("dates.jpg")
                await callback.message.answer_photo(photo, caption="Введите дату и время съемок в формате: <b>10:00 23.01.24 - 11:00 24.01.24</b>\n\n<b>❗Пожалуйста, соблюдайте точный формат — даже одна лишняя точка или пробел собьёт расчет.</b>", reply_markup=get_back_keyboard(), parse_mode=ParseMode.HTML)
            elif callback.data == "custom_rates":
                await state.set_state(UserStates.enter_custom_rates)
                message_text = (
                    "Мы учитываем, что не все работают по ставкам Профсоюза, в связи с чем вы можете внести в формулу просчета индивидуальные ставки.\n\n"
                    "Для этого вам необходимо в следующем сообщении написать через запятую: <b>ставку за основную смену и стоимость часа каждого прогрессива.</b>\n\n"
                )
                photo = FSInputFile("price.jpg")
                await callback.message.answer_photo(photo, caption=message_text, reply_markup=get_back_keyboard())
        else:
            # Логируем попытку использовать платный функционал без подписки
            await log_user_action(
                user_id=user_id,
                action_type="subscription_required",
                action_data=json.dumps({"action": "choose_rates", "rate_type": rate_type})
            )
            
            await callback.message.answer(
                "Вы исчерпали бесплатные генерации. Для продолжения работы оформите подписку.", 
                reply_markup=get_subscription_keyboard()
            )
    await callback.answer()

# Обработчик ввода времени съемок с логированием
@router.message(UserStates.enter_time)
async def enter_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if message.text == "Назад":
        # Логируем действие
        await log_user_action(
            user_id=user_id,
            action_type="navigation",
            action_data=json.dumps({"button": "back", "from": "enter_time", "to": "choose_specialist"})
        )
        
        await state.set_state(UserStates.choose_specialist)
        await message.answer("Выберите специалиста:", reply_markup=get_specialists_inline_keyboard())
        return

    try:
        # Логируем ввод времени (но не само время для конфиденциальности)
        await log_user_action(
            user_id=user_id,
            action_type="enter_time",
            action_data=None
        )
        
        start_time, end_time = message.text.split(' - ')

        # Проверка наличия разделителей времени и даты
        if ':' not in start_time or ':' not in end_time:
            raise ValueError(
                "Отсутствует разделитель времени ':'. Пожалуйста, используйте формат: 10:00 23.01.24 - 11:00 24.01.24")

        if '.' not in start_time or '.' not in end_time:
            raise ValueError(
                "Отсутствует разделитель даты '.'. Пожалуйста, используйте формат: 10:00 23.01.24 - 11:00 24.01.24")

        if ' ' not in start_time or ' ' not in end_time:
            raise ValueError(
                "Отсутствует пробел между временем и датой. Пожалуйста, используйте формат: 10:00 23.01.24 - 11:00 24.01.24")

        start_time = datetime.strptime(start_time, '%H:%M %d.%m.%y')
        end_time = datetime.strptime(end_time, '%H:%M %d.%m.%y')
        duration = (end_time - start_time).total_seconds() / 3600

        if duration <= 0:
            raise ValueError("Неверный интервал времени. Время окончания должно быть позже времени начала.")

        await state.update_data(duration=duration)
        await check_and_calculate_cost(message, state)
        
    except ValueError as e:
        # Логируем ошибку
        error_message = str(e)
        await log_user_action(
            user_id=user_id,
            action_type="error",
            action_data=json.dumps({"error_type": "value_error", "message": error_message})
        )
        
        if "unconverted data remains" in error_message:
            error_message = "Неверный формат времени или даты. Пожалуйста, используйте формат: 10:00 23.01.24 - 11:00 24.01.24"
        await message.answer(f"Ошибка: {error_message}", reply_markup=get_back_keyboard())
    except IndexError:
        # Логируем ошибку
        await log_user_action(
            user_id=user_id,
            action_type="error",
            action_data=json.dumps({"error_type": "index_error", "message": "Неверный формат времени"})
        )
        
        await message.answer(
                         "Неверный формат времени. Пожалуйста, используйте формат: 10:00 23.01.24 - 11:00 24.01.24",
                         reply_markup=get_back_keyboard())

# Обработчик ввода пользовательских ставок
@router.message(UserStates.enter_custom_rates)
async def enter_custom_rates(message: Message, state: FSMContext):
    if message.text == "Назад":
        await state.set_state(UserStates.choose_specialist)
        await message.answer("Выберите специалиста:", reply_markup=get_specialists_inline_keyboard())
        return

    try:
        custom_rates = list(map(int, message.text.split(',')))
        if len(custom_rates) != 4:
            raise ValueError("Неверное количество ставок.")
        
        await state.update_data(custom_rates={
            'base': custom_rates[0],
            'overtime_1': custom_rates[1],
            'overtime_2': custom_rates[2],
            'overtime_3': custom_rates[3]
        })
        
        await state.set_state(UserStates.enter_time)
        photo = FSInputFile("dates.jpg")
        await message.answer_photo(photo, caption="Введите дату и время съемок в формате: <b>10:00 23.01.24 - 11:00 24.01.24</b>\n\n<b>❗Пожалуйста, соблюдайте точный формат — даже одна лишняя точка или пробел собьёт расчет.</b>", reply_markup=get_back_keyboard(), parse_mode=ParseMode.HTML)
    except (ValueError, IndexError):
        await message.answer("Неверный формат ставок. Пожалуйста, введите ставки через запятую в формате: 20000, 2000, 3000, 3000", reply_markup=get_back_keyboard())

# Проверка и расчет стоимости с логированием
async def check_and_calculate_cost(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем, был ли уже использован бесплатный расчет
    user_generations_count = await get_user_generations(user_id)
    
    if user_generations_count == 0:
        await calculate_cost(message, state)
        await increment_user_generations(user_id)
    else:
        # Проверка подписки пользователя
        has_subscription = await check_subscription(user_id)
        if has_subscription:
            await calculate_cost(message, state)
        else:
            await message.answer(
                "Вы исчерпали бесплатные генерации. Для продолжения работы оформите подписку.", 
                reply_markup=get_subscription_keyboard()
            )

# Расчет стоимости с логированием
async def calculate_cost(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    specialist = user_data['specialist']
    duration = user_data['duration']
    
    # Логируем расчет стоимости
    log_data = {
        "specialist": specialist,
        "duration": duration,
        "custom_rates": "custom_rates" in user_data
    }
    await log_user_action(
        user_id=user_id,
        action_type="calculate_cost",
        action_data=json.dumps(log_data)
    )
    
    if 'custom_rates' in user_data:
        rate = user_data['custom_rates']
    else:
        rate = rates[specialist]

    base_cost = rate['base']
    overtime_1_cost = 0
    overtime_2_cost = 0
    overtime_3_cost = 0

    if duration <= 10:
        total_cost = base_cost
    else:
        overtime = duration - 10
        if overtime <= 8:
            overtime_1_cost = overtime * rate['overtime_1']
        elif overtime <= 14:
            overtime_1_cost = 8 * rate['overtime_1']
            overtime_2_cost = (overtime - 8) * rate['overtime_2']
        else:
            overtime_1_cost = 8 * rate['overtime_1']
            overtime_2_cost = 6 * rate['overtime_2']
            overtime_3_cost = (overtime - 14) * rate['overtime_3']

        total_cost = base_cost + overtime_1_cost + overtime_2_cost + overtime_3_cost

    result_message = (
        f"<b>Длительность смены: {int(duration)} часов</b>\n"
        f"Смена 10 часов: <b>{int(base_cost):,} ₽</b>".replace(',', ' ') + "\n"
        f"Первый прогрессив: <b>{int(overtime_1_cost):,} ₽</b>".replace(',', ' ') + "\n"
        f"Второй прогрессив: <b>{int(overtime_2_cost):,} ₽</b>".replace(',', ' ') + "\n"
        f"Третий прогрессив: <b>{int(overtime_3_cost):,} ₽</b>".replace(',', ' ') + "\n"
        f"<b>ОБЩИЙ ИТОГ: {int(total_cost):,} ₽</b>".replace(',', ' ')
    )
    
    await message.answer(result_message, reply_markup=get_main_menu_keyboard())
    await state.set_state(UserStates.idle)
    
    # Дополнительное сообщение для Gaffer
    if specialist == 'Gaffer':
        photo = FSInputFile("3.jpg")
        await message.answer_photo(photo)

# Обработчик кнопки "Сделать новый просчет🔄" с логированием
@router.message(F.text == "Сделать новый просчет🔄")
async def new_calculation(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="new_calculation",
        action_data=None
    )
    
    await state.set_state(UserStates.choose_specialist)
    await message.answer("Выберите специалиста из списка:", reply_markup=get_specialists_inline_keyboard())

# Обработчик кнопки "Моя подписка💳" с логированием
@router.message(F.text == "Моя подписка💳")
async def subscription(message: Message):
    user_id = message.from_user.id
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="check_subscription",
        action_data=None
    )
    
    has_subscription = await check_subscription(user_id)
    if has_subscription:
        await message.answer("У вас есть активная подписка. Вы можете делать неограниченное количество расчетов.")
    else:
        await message.answer("У вас нет активной подписки. Для неограниченного доступа оформите подписку.", 
                           reply_markup=get_subscription_keyboard())

# Обработчик кнопки "Начать сначала"
@router.message(F.text == "Начать сначала")
async def restart(message: Message, state: FSMContext):
    await state.set_state(UserStates.choose_specialist)
    await message.answer("Пожалуйста, выберите специалиста из списка:", reply_markup=get_specialists_inline_keyboard())

# Обработчик выбора подписки с логированием
@router.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Логируем действие
    await log_user_action(
        user_id=user_id,
        action_type="buy_subscription_attempt",
        action_data=None
    )
    
    try:
        # Отправляем запрос на создание счета
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Подписка на бота",
            description="Ежемесячная подписка для неограниченного доступа к расчетам",
            payload="subscription_payload",
            provider_token="",  # Здесь должен быть ваш провайдер-токен
            currency="XTR",
            prices=[LabeledPrice(label="Подписка на 1 месяц", amount=SUBSCRIPTION_PRICE)],
            protect_content=True
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при создании счета: {e}")
        await callback.message.answer(f"Произошла ошибка при создании счета: {e}")
        await callback.answer()

# Обработчик предварительной проверки платежа
@router.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    # Здесь можно добавить дополнительную логику проверки перед подтверждением платежа
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Обработчик успешного платежа
@router.message(F.content_type == "successful_payment")
async def successful_payment_handler(message: Message):
    payment_info = message.successful_payment
    user_id = message.from_user.id
    
    # Активируем подписку для пользователя
    await activate_subscription(user_id)
    
    await message.answer(
        "Спасибо за оплату! Ваша подписка активирована. Теперь вы можете делать неограниченное количество расчетов."
    )

# Команда для оформления подписки
@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    user_id = message.from_user.id
    has_subscription = await check_subscription(user_id)
    if has_subscription:
        await message.answer("У вас уже есть активная подписка. Вы можете делать неограниченное количество расчетов.")
        else:
        await message.answer("Для оформления подписки нажмите на кнопку ниже:", 
                           reply_markup=get_subscription_keyboard())

# Команда /reset
@router.message(Command("reset"))
async def reset(message: Message, state: FSMContext):
    await state.set_state(UserStates.choose_specialist)
    await message.answer("Расчет сброшен. Выберите специалиста:", reply_markup=get_specialists_inline_keyboard())

# Команда /info
@router.message(Command("info"))
async def info(message: Message):
    await message.answer("""Этот бот предназначен для быстрого расчета стоимости и часов рабочих смен различных технических специалистов киноиндустрии

На данный момент реализованы расчеты для осветителей с учетом прогрессивных переработок согласно стандартам профсоюза от 1 марта 2024 года""")

# Команда /help
@router.message(Command("help"))
async def display_help(message: Message):
    help_message = (
        "Доступные команды:\n"
        "/start - Начать работу с ботом\n"
        "/reset - Сбросить текущий расчет\n"
        "/info - Получить информацию о проекте\n"
        "/help - Показать это сообщение\n"
        "/subscribe - Оформить подписку"
    )
    await message.answer(help_message)

# Обработчик кнопки "FAQ🙋🏽"
@router.message(F.text == "FAQ🙋🏽")
async def faq(message: Message):
    faq_message = (
        "🔍 Часто задаваемые вопросы:\n\n"
        "1. Как рассчитываются ставки?\n"
        "Ставки рассчитываются на основе данных профсоюза осветителей от 1 марта 2024 года. Вы можете уточнить детали по ссылке: <a href='https://clck.ru/3EX7yh'>1 марта 2024 года</a>.\n\n"
        "2. Что такое прогрессивные переработки?\n"
        "Прогрессивные переработки — это дополнительные часы работы после 10 часов смены. Они оплачиваются по повышенным ставкам.\n\n"
        "3. Как оформить подписку?\n"
        "Чтобы оформить подписку, перейдите в раздел 'Моя подписка💳' или используйте команду /subscribe.\n\n"
        "4. Как сбросить текущий расчет?\n"
        "Для сброса текущего расчета используйте команду /reset.\n\n"
        "5. Как связаться с поддержкой?\n"
        "Для связи с поддержкой используйте команду /support или перейдите в раздел 'Поддержка📞'.\n\n"
        "6. Как использовать бота?\n"
        "Просто следуйте инструкциям в боте. Выберите специалиста, введите время съемок, и бот рассчитает стоимость смены.\n\n"
        "7. Какие специалисты доступны для расчета?\n"
        "В настоящее время доступны расчеты для осветителей. Скоро будут добавлены другие технические специалисты.\n\n"
        "8. Как узнать больше о проекте?\n"
        "Для получения дополнительной информации используйте команду /info."
    )
    await message.answer(faq_message, disable_web_page_preview=True)

# Обработчик кнопки "Поддержка📞"
@router.message(F.text == "Поддержка📞")
async def support(message: Message):
    support_message = (
        "Для связи с поддержкой, пожалуйста, напишите нам в Telegram:\n\n"
        "👉 <a href='https://t.me/producer_help_support'>https://t.me/producer_help_support</a>\n\n"
        "Мы постараемся ответить как можно скорее!"
    )
    await message.answer(support_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# Команда /faq
@router.message(Command("faq"))
async def faq_command(message: Message):
    await faq(message)

# Команда /support
@router.message(Command("support"))
async def support_command(message: Message):
    await support(message)

# Основная точка входа
async def main():
    # Инициализация базы данных
    await init_db()
    
    # Установка команд бота
    await set_bot_commands()

# Запуск бота
    await dp.start_polling(bot)

# Закрытие соединения с базой данных при завершении работы бота
async def on_shutdown():
    if mysql_pool:
        mysql_pool.close()
        await mysql_pool.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(on_shutdown())
        else:
            asyncio.run(on_shutdown()) 