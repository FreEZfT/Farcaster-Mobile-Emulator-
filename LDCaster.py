import subprocess
import random
import os
import threading
import time
import uiautomator2 as u2
import zipfile
import json
import shutil


# ==============================================================================
# КОНФИГУРАЦИЯ
# ==============================================================================

# 1. Укажите путь к ldconsole.exe. Если оставить None, скрипт попытается найти его сам.
LDPLAYER_PATH = r"C:\LDPlayer64\LDPlayer64\ldconsole.exe"
VMS_PATH = r"C:\LDPlayer64\LDPlayer64\vms"


# 3. Настройки "железа" эмулятора.
CPU_CORES = "2"
RAM_MB = "4096"  # 4 ГБ
RESOLUTION_WIDTH = "540"
RESOLUTION_HEIGHT = "960"
RESOLUTION_DPI = "240" # DPI

# 4. Укажите полные пути к двум APK-файлам, которые нужно установить.
# Пример: APK_PATHS = [r"C:\Users\Admin\Downloads\proxy.apk", r"C:\Users\Admin\Downloads\farcaster.apk"]
APK_PATHS = [
    r"C:\Users\Ruslan\Desktop\FarLD\Farcaster_2.0.5_APKPure.xapk",
    r"C:\Users\Ruslan\Desktop\FarLD\Super+Proxy_2.8.10_apkcombo.com.xapk"
]


# ==============================================================================

def get_ldplayer_path():
    """Автоматически находит путь к ldconsole.exe."""
    if LDPLAYER_PATH and os.path.exists(LDPLAYER_PATH):
        return LDPLAYER_PATH

    # Ищем в стандартных директориях
    for path in [os.path.join(os.environ["ProgramFiles"], "LDPlayer"),
                 os.path.join(os.environ.get("ProgramFiles(x86)", ""), "LDPlayer")]:
        if not os.path.exists(path):
            continue
        for folder_name in os.listdir(path):
            if folder_name.lower().startswith('ldplayer'):
                console_path = os.path.join(path, folder_name, "ldconsole.exe")
                if os.path.exists(console_path):
                    print(f"Найден ldconsole.exe: {console_path}")
                    return console_path
    raise FileNotFoundError("Не удалось найти ldconsole.exe. Пожалуйста, укажите путь в переменной LDPLAYER_PATH.")

def prepare_and_configure_emulator(ld_path, index):
    """
    Выполняет "холодную" настройку с надежным ожиданием файла конфигурации.
    """
    print(f"[Индекс {index}]: Начало 'холодной' подготовки эмулятора.")
    config_file_path = os.path.join(VMS_PATH, "config", f"leidian{index}.config")

    if not os.path.exists(config_file_path):
        print(f"[Индекс {index}]: Эмулятор не существует. Создание...")
        try:
            subprocess.run([ld_path, "create", "--index", str(index)], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"[{index}]: КРИТИЧЕСКАЯ ОШИБКА при выполнении 'create': {e.stderr}")
            return False

        # Более надежный цикл ожидания
        print(f"[{index}]: Ожидание появления файла конфигурации...")
        timeout = 45;
        start_time = time.time()
        while not os.path.exists(config_file_path):
            if time.time() - start_time > timeout:
                print(f"[{index}]: ОШИБКА: Файл конфигурации не появился за {timeout} секунд.")
                return False
            print(f"[{index}]: ...файл еще не создан, ждем...")
            time.sleep(2)
        print(f"[{index}]: Эмулятор и конфиг созданы.")

    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        config_data["basicSettings.adbDebug"] = 1
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        print(f"[Индекс {index}]: ADB принудительно включен.")
    except Exception as e:
        print(f"[{index}]: ОШИБКА при редактировании JSON: {e}")
        return False

    if not configure_emulator(ld_path, index):
        return False

    return True

def wait_for_emulator_boot(ld_path, index):
    """Ждет полной загрузки эмулятора с увеличенным таймаутом и выводом статуса."""
    print(f"[Индекс {index}]: Ожидание загрузки эмулятора...")

    timeout = 300
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            command = [ld_path, "adb", "--index", str(index), "--command", "shell getprop sys.boot_completed"]

            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=15)

            if "1" in result.stdout.strip():
                print(f"[Индекс {index}]: Эмулятор успешно загружен.")
                time.sleep(5)
                return True

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Ошибка или таймаут команды - это нормально на этапе загрузки.
            # Просто выводим статус и продолжаем ждать.
            elapsed_time = int(time.time() - start_time)
            print(f"[Индекс {index}]: ...ожидание... ({elapsed_time} сек / {timeout} сек)")
            pass

        time.sleep(5)

    print(f"[Индекс {index}]: ОШИБКА: Эмулятор не загрузился за {timeout} секунд.")
    return False

def get_emulator_serial(ld_path, index):
    """Получает серийный номер эмулятора по его индексу."""
    try:
        result = subprocess.run(
            [ld_path, "adb", "--index", str(index), "--command", "get-serialno"],
            capture_output=True, text=True, check=True
        )
        serial = result.stdout.strip()
        if "error" in serial or not serial:
            raise ValueError("Не удалось получить серийный номер.")
        print(f"[Индекс {index}]: Получен серийный номер: {serial}")
        return serial
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"[Индекс {index}]: ОШИБКА при получении серийного номера: {e}")
        return None

def install_xapk(serial, xapk_path):
    """
    Устанавливает Split APKs, используя самый надежный метод через Package Manager (pm).
    """
    if not os.path.exists(xapk_path):
        print(f"[{serial}]: ОШИБКА: Файл не найден {xapk_path}")
        return

    print(f"[{serial}]: Начало установки Split APKs из файла {os.path.basename(xapk_path)}...")
    temp_dir = os.path.join(os.getcwd(), "temp_xapk_install")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    remote_tmp_dir = "/data/local/tmp/split_apk_install"

    try:
        # 1. Распаковка
        with zipfile.ZipFile(xapk_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        print(f"[{serial}]: Архив успешно распакован.")

        # 2. НАДЕЖНО ищем базовый и конфигурационные APK через manifest.json
        all_apk_files = [f for f in os.listdir(temp_dir) if f.lower().endswith('.apk')]
        base_apk_name = None
        manifest_path = os.path.join(temp_dir, "manifest.json")

        if not os.path.exists(manifest_path):
            print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: manifest.json не найден. Невозможно определить базовый APK.")
            return

        with open(manifest_path, 'r') as f:
            manifest = json.load(f)

        # Ищем APK с id 'base'
        base_apk_name = next((split['file'] for split in manifest.get('split_apks', []) if split.get('id') == 'base'),
                             None)

        if not base_apk_name:
            print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось найти 'base' APK в manifest.json.")
            return

        base_apk_path = os.path.join(temp_dir, base_apk_name)
        split_apks_paths = [os.path.join(temp_dir, f) for f in all_apk_files if f != base_apk_name]
        print(f"[{serial}]: Базовый APK (из манифеста): '{base_apk_name}'.")

        # 3. Копируем ВСЕ .apk во временную папку на устройстве
        print(f"[{serial}]: Копирование всех APK на устройство...")
        subprocess.run(["adb", "-s", serial, "shell", "mkdir", "-p", remote_tmp_dir], check=True)

        # Сначала копируем базовый, потом остальные
        all_local_paths = [base_apk_path] + split_apks_paths
        for local_path in all_local_paths:
            remote_path = f"{remote_tmp_dir}/{os.path.basename(local_path)}"
            subprocess.run(["adb", "-s", serial, "push", local_path, remote_path], check=True, capture_output=True)

        print(f"[{serial}]: Все {len(all_local_paths)} APK скопированы на устройство.")

        # 4. Создаем сессию установки через pm install-create
        pm_create_cmd = ["adb", "-s", serial, "shell", "pm", "install-create", "-r", "-g"]
        create_output = subprocess.check_output(pm_create_cmd).decode("utf-8")
        session_id = create_output.split('[')[-1].split(']')[0]
        print(f"[{serial}]: Создана сессия установки PM с ID: {session_id}")

        # 5. Записываем каждый APK в сессию
        for i, local_path in enumerate(all_local_paths):
            apk_name = os.path.basename(local_path)
            remote_path = f"{remote_tmp_dir}/{apk_name}"
            size = os.path.getsize(local_path)

            # pm install-write -S <size> <session_id> <split_name> <remote_path>
            split_name = f"split_{i}_{apk_name}"  # Даем уникальное имя для каждого сплита
            pm_write_cmd = ["adb", "-s", serial, "shell", "pm", "install-write", "-S", str(size), session_id,
                            split_name, remote_path]
            subprocess.run(pm_write_cmd, check=True, capture_output=True)
            print(f"[{serial}]:   -> Файл '{apk_name}' записан в сессию.")

        # 6. Коммитим сессию
        pm_commit_cmd = ["adb", "-s", serial, "shell", "pm", "install-commit", session_id]
        print(f"[{serial}]: Отправка команды на завершение установки (commit)...")
        commit_output = subprocess.check_output(pm_commit_cmd, stderr=subprocess.STDOUT).decode("utf-8")

        if "Success" in commit_output:
            print(f"[{serial}]: УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!")
        else:
            print(f"[{serial}]: ОШИБКА: Завершение сессии не удалось. Ответ системы: {commit_output}")
            return

    except Exception as e:
        print(f"[{serial}]: ПРОИЗОШЛА КРИТИЧЕСКАЯ ОШИБКА во время установки: {e}")

    finally:
        subprocess.run(["adb", "-s", serial, "shell", "rm", "-rf", remote_tmp_dir], capture_output=True)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        print(f"[{serial}]: Временные файлы удалены.")

def install_apps_from_paths(serial, paths):
    """
    Устанавливает приложения, определяя тип файла (.apk или .xapk) по расширению.
    """
    if not serial:
        print("Пропуск установки из-за отсутствия серийного номера.")
        return

    for app_path in paths:
        if not os.path.exists(app_path):
            print(f"[{serial}]: ОШИБКА: Файл не найден {app_path}")
            continue

        # Определяем тип файла и вызываем нужный установщик
        if app_path.lower().endswith('.xapk'):
            install_xapk(serial, app_path)
        elif app_path.lower().endswith('.apk'):
            # Логика установки обычного APK
            print(f"[{serial}]: Установка APK {os.path.basename(app_path)}...")
            try:
                subprocess.run(
                    ["adb", "-s", serial, "install", "-r", app_path],
                    check=True, capture_output=True, text=True, timeout=120
                )
                print(f"[{serial}]: Установка {os.path.basename(app_path)} завершена.")
            except Exception as e:
                print(f"[{serial}]: ОШИБКА установки APK: {e}")
        else:
            print(f"[{serial}]: ВНИМАНИЕ: Неизвестный формат файла {app_path}. Пропуск.")

def configure_emulator(ld_path, index):
    """
    Применяет случайные и фиксированные настройки к эмулятору по его индексу.
    """

    print(f"[Индекс {index}]: Применение настроек (модель, IMEI, CPU, RAM, разрешение)...")
    manufacturers = {
        "Samsung": ["SM-G998U1", "SM-N986U", "SM-S908E"],
        "Google": ["Pixel 6 Pro", "Pixel 5", "Pixel 4a"],
        "Xiaomi": ["2201116SG", "M2102J20SG", "M2012K11AG"],
        "OnePlus": ["NE2213", "IN2023", "KB2005"]
    }
    manufacturer = random.choice(list(manufacturers.keys()))
    model = random.choice(manufacturers[manufacturer])

    # 1. Формируем строку для разрешения из переменных конфигурации
    resolution_str = f"{RESOLUTION_WIDTH},{RESOLUTION_HEIGHT},{RESOLUTION_DPI}"

    command = [
        ld_path, "modify", "--index", str(index),
        "--resolution", resolution_str,
        "--cpu", CPU_CORES,
        "--memory", RAM_MB,
        "--manufacturer", manufacturer,
        "--model", model,
        "--imei", "auto",
        "--root", "0"
    ]
    try:
        subprocess.run(command, check=True, capture_output=True)
        # Сообщение тоже можно дополнить
        print(f"[Индекс {index}]: Настройки применены. Модель: {manufacturer} {model}, Разрешение: {resolution_str}.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Индекс {index}]: ОШИБКА при настройке: {e.stderr}")
        return False

def load_proxies_from_file(filename="proxies.txt"):
    """
    Загружает список прокси из текстового файла.
    Возвращает список словарей [{'ip': ..., 'port': ..., 'user': ..., 'pass': ...}]
    """
    proxies = []
    if not os.path.exists(filename):
        print(f"ВНИМАНИЕ: Файл с прокси '{filename}' не найден.")
        return proxies

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(':')
            if len(parts) == 4:
                proxies.append({
                    'ip': parts[0],
                    'port': parts[1],
                    'user': parts[2],
                    'pass': parts[3]
                })
            else:
                print(f"ВНИМАНИЕ: Неверный формат строки в файле прокси: '{line}'")

    print(f"Загружено {len(proxies)} прокси из файла '{filename}'.")
    return proxies

def setup_super_proxy(serial, proxy_data):
    """
    Автоматизирует настройку прокси в Super Proxy, используя XPath и явный клик перед вводом.
    """
    print(f"[{serial}]: Начало полной настройки Super Proxy...")


    try:
        d = u2.connect(serial)
        app_package = "com.scheler.superproxy"


        # --- Шаг 1: Запуск приложения ---
        print(f"[{serial}]: Запуск приложения {app_package}...")
        d.app_start(app_package, stop=True)
        time.sleep(7)

        # --- Шаг 2: Добавление нового прокси ---
        print(f"[{serial}]: Нажатие на кнопку 'Add proxy'...")
        d(description="Add proxy").click()
        time.sleep(2)

        # --- Шаг 3: Выбор типа прокси HTTP ---
        print(f"[{serial}]: Открытие меню выбора типа прокси...")
        d(text="SOCKS5").click()
        time.sleep(1)
        print(f"[{serial}]: Выбор типа 'HTTP'...")
        d(description="HTTP").click()
        time.sleep(1)

        # --- ШАГ 4: Ввод IP и Порта с предварительным кликом ---
        print(f"[{serial}]: Ввод IP-адреса...")
        ip_field = d.xpath(
            '//*[@resource-id="android:id/content"]/android.widget.FrameLayout[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[2]/android.view.View[2]/android.widget.EditText[1]')
        ip_field.click()
        ip_field.set_text(proxy_data['ip'])

        print(f"[{serial}]: Ввод порта...")
        port_field = d.xpath(
            '//*[@resource-id="android:id/content"]/android.widget.FrameLayout[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[2]/android.view.View[3]')
        port_field.click()
        port_field.set_text(proxy_data['port'])
        time.sleep(1)

        # --- ШАГ 5: Настройка аутентификации ---
        print(f"[{serial}]: Открытие меню выбора аутентификации...")
        d(text="None").click()
        time.sleep(1)
        print(f"[{serial}]: Выбор 'Username/Password'...")
        d(description="Username/Password").click()
        time.sleep(1)

        # --- ШАГ 6: Прокрутка и ввод логина/пароля с предварительным кликом ---
        print(f"[{serial}]: Прокрутка вниз...")
        d.swipe_ext("up", scale=0.7)
        time.sleep(2)

        print(f"[{serial}]: Ввод имени пользователя...")
        user_field = d.xpath('//android.widget.ScrollView/android.view.View[5]/android.widget.EditText[1]')
        user_field.click()
        user_field.set_text(proxy_data['user'])

        print(f"[{serial}]: Ввод пароля...")
        pass_field = d.xpath('//android.widget.ScrollView/android.view.View[6]/android.widget.EditText[1]')
        pass_field.click()
        pass_field.set_text(proxy_data['pass'])
        time.sleep(1)

        # --- ШАГ 7: Сохранение прокси (используем XPath) ---
        print(f"[{serial}]: Нажатие на кнопку сохранения через XPath...")
        d.xpath(
            '//*[@resource-id="android:id/content"]/android.widget.FrameLayout[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.view.View[1]/android.widget.Button[2]').click()
        time.sleep(3)


        print(f"[{serial}]: Нажатие на кнопку 'Start'...")
        d(description="Start").click()

        time.sleep(1.5)

        print(f"[{serial}]: Ожидание системного окна VPN (до 10 секунд)...")

        # --- Попытка №1: Простой поиск по классу и индексу ---
        # Ищем вторую кнопку на экране. Это самый прямой способ.
        ok_button_selector = d(className="android.widget.Button", instance=1)

        if ok_button_selector.wait(timeout=10.0):
            print(f"[{serial}]: Кнопка найдена по className и index. Нажатие 'ОК'...")
            try:
                ok_button_selector.click()
            except u2.exceptions.UiObjectNotFoundError:
                print(f"[{serial}]: Окно исчезло перед кликом, считаем, что все в порядке.")
        else:
            # --- Попытка №2: Поиск в контексте системного пакета (если первая не удалась) ---
            print(f"[{serial}]: Простой поиск не удался. Пробуем найти в контексте пакета 'com.android.vpndialogs'...")

            vpn_dialog_package = "com.android.vpndialogs"
            # Ищем вторую кнопку, но только внутри этого пакета.
            # Также ищем текст "ОК" в верхнем регистре.
            ok_button_in_dialog = d(
                packageName=vpn_dialog_package,
                className="android.widget.Button",
                text="ОК"
            )

            if ok_button_in_dialog.wait(timeout=5.0):
                print(f"[{serial}]: Кнопка найдена в контексте пакета. Нажатие 'ОК'...")
                try:
                    ok_button_in_dialog.click()
                except u2.exceptions.UiObjectNotFoundError:
                    print(f"[{serial}]: Окно исчезло перед кликом, считаем, что все в порядке.")
            else:
                print(f"[{serial}]: Оба метода поиска не сработали. Системное окно не найдено. Продолжаем...")



        time.sleep(5)

        print(f"[{serial}]: Проверка статуса подключения...")
        if d(descriptionStartsWith="00:00:").exists:
            print(f"[{serial}]: УСПЕХ! Прокси запущен, таймер работает.")
        else:
            print(f"[{serial}]: ВНИМАНИЕ: Таймер не обнаружен. Попытка повторного запуска...")
            if d(description="Start").exists:
                d(description="Start").click()
                time.sleep(2)
                if d(resourceId="android:id/button1", text="OK").exists:
                    d(resourceId="android:id/button1", text="OK").click()

        print(f"[{serial}]: Сворачивание приложения Super Proxy...")
        d.press("home")

    except Exception as e:
        print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА в UI-автоматизации Super Proxy: {e}")
        if 'd' in locals() and d:
            screenshot_path = f"error_screenshot_{serial}.png"
            d.screenshot(screenshot_path)
            print(f"[{serial}]: Сделан скриншот ошибки: {screenshot_path}")
        return False



    return True

def check_and_revive_proxy(serial):
    """
    Проверяет наличие иконки прокси в строке состояния и перезапускает его в случае необходимости.
    Работает без открытия панели уведомлений.
    """
    print(f"[{serial}]: Проверка статуса прокси по иконке в строке состояния...")
    d = u2.connect(serial)


    proxy_icon_selector = d(description="Уведомление Super Proxy: Прокси сервер запущен")

    if proxy_icon_selector.exists(timeout=3):
        print(f"[{serial}]: Прокси активен (иконка найдена). Продолжаем.")
        return True
    else:
        print(f"[{serial}]: ВНИМАНИЕ: Прокси неактивен (иконка не найдена)! Попытка перезапуска...")

        app_package = "com.scheler.superproxy"
        # Запускаем Super Proxy
        d.app_start(app_package)
        time.sleep(4)

        # Ищем и нажимаем кнопку Start
        if d(description="Start").exists:
            d(description="Start").click()
            time.sleep(2)
            # Проверяем системное окно подтверждения
            if d(resourceId="android:id/button1", text="OK").exists:
                d(resourceId="android:id/button1", text="OK").click()

        # После попытки перезапуска сворачиваем приложение, чтобы не мешать Farcaster
        d.press("home")
        print(f"[{serial}]: Попытка перезапуска прокси завершена.")

        # Можно добавить повторную проверку иконки для 100% уверенности
        time.sleep(5)
        if proxy_icon_selector.exists(timeout=3):
            print(f"[{serial}]: Прокси успешно перезапущен!")
            return True
        else:
            print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось перезапустить прокси.")
            return False

def click_random_in_zone(d_obj, x1, y1, x2, y2):
    """
    Выполняет клик по случайным координатам внутри заданной прямоугольной зоны.
    (x1, y1) - левый верхний угол, (x2, y2) - правый нижний угол.
    """
    if not all(isinstance(i, int) for i in [x1, y1, x2, y2]):
        print("ОШИБКА: Координаты зоны должны быть целыми числами.")
        return

    random_x = random.randint(x1, x2)
    random_y = random.randint(y1, y2)

    print(f"Выполнение случайного клика в зоне по координатам ({random_x}, {random_y})...")
    d_obj.click(random_x, random_y)

def load_farcaster_phrases(filename="farcaster_phrase.txt"):
    """Загружает сид-фразы из файла."""
    if not os.path.exists(filename):
        print(f"ВНИМАНИЕ: Файл с сид-фразами '{filename}' не найден.")
        return []
    with open(filename, 'r') as f:
        # Читаем непустые строки
        phrases = [line.strip() for line in f if line.strip()]
    print(f"Загружено {len(phrases)} сид-фраз из файла '{filename}'.")
    return phrases

def save_private_key(seed_phrase, private_key, filename="privatkey.txt"):
    """Сохраняет результат в файл в формате seed:key."""
    try:
        with open(filename, 'a') as f:
            f.write(f"{seed_phrase}:{private_key}\n")
        print(f"Успешно сохранена пара в '{filename}'")
    except Exception as e:
        print(f"ОШИБКА записи в файл '{filename}': {e}")


def login_farcaster(serial, seed_phrase):
    """
    Выполняет полный цикл входа в аккаунт Farcaster и оставляет приложение на главном экране.
    Возвращает True в случае успеха и False в случае ошибки.
    """
    print(f"\n[{serial}]: Начало процесса входа в Farcaster с фразой: '{seed_phrase[:15]}...'")
    d = None
    try:
        d = u2.connect(serial)
        app_package = "com.farcaster.mobile"

        # --- Шаг 1: Запуск и вход ---
        print(f"[{serial}]: Запуск приложения и поиск кнопки 'Sign in'...")
        d.app_start(app_package, stop=True)
        sign_in_button = d(text="Sign in")
        if not sign_in_button.wait(timeout=30.0):
            d.app_start(app_package, stop=True)
            if not sign_in_button.wait(timeout=30.0):
                print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Кнопка 'Sign in' не найдена.")
                return False

        sign_in_button.click()
        time.sleep(2)
        d(text="Use recovery phrase").click()
        time.sleep(2)
        edit_text_field = d(className="android.widget.EditText")
        edit_text_field.click()
        edit_text_field.set_text(seed_phrase)
        time.sleep(1)
        d(description="Continue").click()

        # --- Шаг 2: Обработка необязательных экранов и ожидание главного ---

        # Проверка экрана "Collectible Casts"
        print(f"[{serial}]: Проверка наличия экрана 'Collectible Casts'...")
        collectible_casts_header = d(text="Collectible Casts")
        if collectible_casts_header.exists(timeout=5.0):
            print(f"[{serial}]: Экран 'Collectible Casts' обнаружен. Выполняем обход...")
            d.swipe_ext("up", scale=0.8)
            time.sleep(1)
            continue_button = d(description="Continue")
            if continue_button.exists(timeout=5.0):
                continue_button.click()
                print(f"[{serial}]: Кнопка 'Continue' нажата.")
            else:
                print(f"[{serial}]: ВНИМАНИЕ: Кнопка 'Continue' не найдена после прокрутки.")
        else:
            print(f"[{serial}]: Экран 'Collectible Casts' не обнаружен. Пропускаем.")

        # Финальное ожидание главного экрана
        print(f"[{serial}]: Ожидание главного экрана ('Home')...")
        if not d(text="Home").wait(timeout=60.0):
            print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось войти в аккаунт (элемент 'Home' не найден).")
            d.screenshot(f"error_login_farcaster_{serial}.png")
            return False

        time.sleep(1)
        print(f"[{serial}]: ✅ Вход в Farcaster выполнен успешно. Приложение на главном экране.")
        return True

    except Exception as e:
        print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА во время входа в Farcaster: {e}")
        if d: d.screenshot(f"error_farcaster_{serial}.png")
        return False


# def farcaster_save_private_key(serial, seed_phrase):
#     """
#     Выполняет "прогревочный" и "боевой" проходы для надежного копирования ключа.
#     """
#     print(f"[{serial}]: Начало работы с Farcaster для фразы: '{seed_phrase[:15]}...'")
#
#     d = None
#     try:
#         d = u2.connect(serial)
#         app_package = "com.farcaster.mobile"
#
#         # --- Шаг 1: Однократный вход в приложение ---
#         print(f"[{serial}]: Запуск Farcaster и первичный вход...")
#         d.app_start(app_package, stop=True)
#         sign_in_button = d(text="Sign in")
#         if not sign_in_button.wait(timeout=30.0):
#             d.app_start(app_package, stop=True)
#             if not sign_in_button.wait(timeout=30.0):
#                 print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Кнопка 'Sign in' не найдена.")
#                 return False
#
#         sign_in_button.click()
#         time.sleep(2)
#         d(text="Use recovery phrase").click()
#         time.sleep(2)
#         edit_text_field = d(className="android.widget.EditText")
#         edit_text_field.click()
#         edit_text_field.set_text(seed_phrase)
#         time.sleep(1)
#         d(description="Continue").click()
#
#         # --- Шаг 2: "Прогревочный" проход ---
#         print(f"\n[{serial}]: ================= НАЧАЛО ПРОГРЕВОЧНОГО ПРОХОДА ================= ")
#         time.sleep(1)
#         print(f"[{serial}]: Проверка наличия экрана 'Collectible Casts' (до 5 секунд)...")
#         collectible_casts_header = d(text="Collectible Casts")
#
#         # .exists(timeout=...) - идеальный способ для быстрой проверки
#         if collectible_casts_header.exists(timeout=5.0):
#             print(f"[{serial}]: Экран 'Collectible Casts' обнаружен. Выполняем обход...")
#             # Прокручиваем вниз, чтобы кнопка "Continue" стала видимой
#             d.swipe_ext("up", scale=0.8)
#             time.sleep(1)
#
#             continue_button = d(description="Continue")
#             if continue_button.exists(timeout=5.0):
#                 continue_button.click()
#                 print(f"[{serial}]: Кнопка 'Continue' нажата.")
#             else:
#                 print(f"[{serial}]: ВНИМАНИЕ: Кнопка 'Continue' не найдена после прокрутки.")
#         else:
#             print(f"[{serial}]: Экран 'Collectible Casts' не обнаружен. Пропускаем шаг.")
#
#         print(f"[{serial}]: Ожидание главного экрана ('Home')...")
#         if not d(text="Home").wait(timeout=60.0):
#             print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось войти в аккаунт.")
#             return False
#         time.sleep(1)
#
#
#         print(f"[{serial}]: Навигация в настройки для 'прогрева'...")
#         print(f"[{serial}]: Ожидание и нажатие на кнопку профиля...")
#         print(f"[{serial}]: Открытие боковой панели свайпом (до 3 попыток)...")
#
#         max_swipe_attempts = 3
#         panel_opened = False
#         settings_button = d(text="Settings")  # Заранее определяем селектор
#
#         for attempt in range(max_swipe_attempts):
#             # Проверяем, не видна ли кнопка "Settings" УЖЕ
#             if settings_button.exists(timeout=1.0):
#                 print(f"[{serial}]: Панель уже открыта.")
#                 panel_opened = True
#                 break  # Выходим из цикла, если панель уже открыта
#
#             # Если не видна, делаем свайп
#             print(f"[{serial}]: Попытка свайпа #{attempt + 1}...")
#             # d.swipe(x_start, y_start, x_end, y_end, duration)
#             # Сделаем жест чуть быстрее (0.2 секунды)
#             d.swipe(10, 480, 400, 480, 0.2)
#
#             # Ждем появления кнопки после свайпа
#             if settings_button.wait(timeout=3.0):
#                 print(f"[{serial}]: Панель успешно открыта.")
#                 panel_opened = True
#                 break  # Успех, выходим из цикла
#
#         # Финальная проверка
#         if not panel_opened:
#             print(
#                 f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось открыть боковую панель после {max_swipe_attempts} попыток.")
#             # Здесь можно либо вернуть False, либо дать скрипту упасть со следующей ошибкой
#             return False  # Надежнее всего завершить функцию с ошибкой
#
#         # Теперь, когда мы уверены, что панель открыта, нажимаем на кнопку
#         settings_button.click()
#         time.sleep(2)
#         d(text="Advanced").click()
#         time.sleep(2)
#         recovery_button = d(description="Show wallet recovery phrase")
#         if not recovery_button.wait(timeout=10.0): return False
#         recovery_button.click()
#         time.sleep(2)
#         d.xpath(
#             '//android.widget.ScrollView/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[6]/android.view.ViewGroup[1]/android.view.ViewGroup[1]').click()
#         time.sleep(1)
#         d(text="Continue").click()
#         time.sleep(2)
#         wallet_container_xpath = '//android.widget.ScrollView/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[1]'
#         if not d.xpath(wallet_container_xpath).wait(timeout=20.0): return False
#         print(f"[{serial}]: 'Прогревочный' проход завершен. Перезапуск приложения для 'боевого' прохода.")
#
#         # --- Шаг 3: "Боевой" проход ---
#         print(f"\n[{serial}]: ================= НАЧАЛО БОЕВОГО ПРОХОДА ================= ")
#         d.app_start(app_package, stop=True)
#
#         time.sleep(1)
#         print(f"[{serial}]: Проверка наличия экрана 'Collectible Casts' (до 5 секунд)...")
#         collectible_casts_header = d(text="Collectible Casts")
#
#         # .exists(timeout=...) - идеальный способ для быстрой проверки
#         if collectible_casts_header.exists(timeout=5.0):
#             print(f"[{serial}]: Экран 'Collectible Casts' обнаружен. Выполняем обход...")
#             # Прокручиваем вниз, чтобы кнопка "Continue" стала видимой
#             d.swipe_ext("up", scale=0.8)
#             time.sleep(1)
#
#             continue_button = d(description="Continue")
#             if continue_button.exists(timeout=5.0):
#                 continue_button.click()
#                 print(f"[{serial}]: Кнопка 'Continue' нажата.")
#             else:
#                 print(f"[{serial}]: ВНИМАНИЕ: Кнопка 'Continue' не найдена после прокрутки.")
#         else:
#             print(f"[{serial}]: Экран 'Collectible Casts' не обнаружен. Пропускаем шаг.")
#
#         print(f"[{serial}]: Ожидание главного экрана ('Home')...")
#         if not d(text="Home").wait(timeout=60.0):
#             print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуться на главный экран.")
#             return False
#
#         time.sleep(1)  # Пауза после нахождения Home
#         print(f"[{serial}]: Начинаем навигацию для копирования ключа...")
#         print(f"[{serial}]: Ожидание и нажатие на кнопку профиля...")
#         print(f"[{serial}]: Открытие боковой панели свайпом (до 3 попыток)...")
#
#         max_swipe_attempts = 3
#         panel_opened = False
#         settings_button = d(text="Settings")  # Заранее определяем селектор
#
#         for attempt in range(max_swipe_attempts):
#             # Проверяем, не видна ли кнопка "Settings" УЖЕ
#             if settings_button.exists(timeout=1.0):
#                 print(f"[{serial}]: Панель уже открыта.")
#                 panel_opened = True
#                 break  # Выходим из цикла, если панель уже открыта
#
#             # Если не видна, делаем свайп
#             print(f"[{serial}]: Попытка свайпа #{attempt + 1}...")
#             # d.swipe(x_start, y_start, x_end, y_end, duration)
#             # Сделаем жест чуть быстрее (0.2 секунды)
#             d.swipe(10, 480, 400, 480, 0.2)
#
#             # Ждем появления кнопки после свайпа
#             if settings_button.wait(timeout=3.0):
#                 print(f"[{serial}]: Панель успешно открыта.")
#                 panel_opened = True
#                 break  # Успех, выходим из цикла
#
#         # Финальная проверка
#         if not panel_opened:
#             print(
#                 f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось открыть боковую панель после {max_swipe_attempts} попыток.")
#             # Здесь можно либо вернуть False, либо дать скрипту упасть со следующей ошибкой
#             return False  # Надежнее всего завершить функцию с ошибкой
#
#         # Теперь, когда мы уверены, что панель открыта, нажимаем на кнопку
#         settings_button.click()
#         time.sleep(2)
#         d(text="Advanced").click()
#         time.sleep(2)
#         recovery_button = d(description="Show wallet recovery phrase")
#         if not recovery_button.wait(timeout=10.0): return False
#         recovery_button.click()
#         time.sleep(2)
#         d.xpath(
#             '//android.widget.ScrollView/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[1]/android.view.ViewGroup[6]/android.view.ViewGroup[1]/android.view.ViewGroup[1]').click()
#         time.sleep(1)
#         d(text="Continue").click()
#         time.sleep(2)
#         if not d.xpath(wallet_container_xpath).wait(timeout=20.0): return False
#
#         # Пауза и клик по Ethereum (с вашими новыми таймингами)
#         print(f"[{serial}]: Пауза 20 секунд для прогрузки кошельков...")
#         time.sleep(20)
#         ETHEREUM_ICON_ZONE = {"x1": 71, "y1": 216, "x2": 120, "y2": 267}
#         click_random_in_zone(d, ETHEREUM_ICON_ZONE["x1"], ETHEREUM_ICON_ZONE["y1"], ETHEREUM_ICON_ZONE["x2"],
#                              ETHEREUM_ICON_ZONE["y2"])
#         time.sleep(5)
#
#
#
#         # Клик по кнопке "Копировать"
#         COPY_KEY_ZONE = {"x1": 76, "y1": 814, "x2": 219, "y2": 848}
#         print(f"[{serial}]: Клик по зоне кнопки 'Копировать'...")
#         click_random_in_zone(d, COPY_KEY_ZONE["x1"], COPY_KEY_ZONE["y1"], COPY_KEY_ZONE["x2"], COPY_KEY_ZONE["y2"])
#         time.sleep(3)
#
#         print(f"[{serial}]: Начало процесса извлечения ключа через поиск...")
#
#         # 1. Нажимаем назад 3 раза
#         print(f"[{serial}]: Возвращение на главный экран...")
#         d.press("back")
#         time.sleep(1)
#         d.press("back")
#         time.sleep(1)
#         d.press("back")
#         time.sleep(1)
#
#         # 2. Нажимаем на "Bookmarks"
#         # Будем использовать text, так как это надежнее, чем длинный XPath
#         print(f"[{serial}]: Переход в 'Bookmarks'...")
#         d(text="Bookmarks").click()
#         time.sleep(2)
#
#         # 3. Нажимаем на иконку поиска
#         # Ваш длинный XPath указывает на 6-ю кнопку. Попробуем найти ее так.
#         # Это хрупко, но соответствует вашему XPath.
#         print(f"[{serial}]: Нажатие на иконку поиска...")
#         d(className="android.widget.Button", instance=5).click()  # instance=5 это 6-й по счету
#         time.sleep(2)
#
#         # 4. Находим поле поиска, вставляем и читаем
#         d(text=" Search").click()
#         time.sleep(1)
#         print(f"[{serial}]: Вставка и чтение ключа из поля поиска...")
#         search_field = d(className="android.widget.EditText")  # Предполагаем, что это единственное поле
#
#         # Долгое нажатие для вызова контекстного меню
#         search_field.long_click()
#         time.sleep(1)
#
#         # Ищем и нажимаем "Вставить"
#         if d(text="Paste").exists:
#             d(text="Paste").click()
#         elif d(text="Вставить").exists:
#             d(text="Вставить").click()
#         else:
#             print(f"[{serial}]: ВНИМАНИЕ: Не удалось найти кнопку 'Вставить'. Пробуем клик по координатам...")
#             # Координаты нужно будет подобрать, если текстовый поиск не сработает
#             d.click(150, 150)
#
#         time.sleep(1)
#
#         # Читаем текст, который был вставлен
#         private_key = search_field.get_text()
#
#         # 5. Проверяем и сохраняем
#         if private_key and len(private_key) > 60:
#             print(f"[{serial}]: УСПЕХ! Приватный ключ извлечен из поля поиска: {private_key[:10]}...")
#             # Используем вашу новую функцию сохранения privatekey:seedphrase
#             save_private_key(private_key, seed_phrase)
#         else:
#             print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось извлечь ключ. Содержимое поля: '{private_key}'")
#             return False  # Завершаем с ошибкой, если ключ не извлекся
#
#         # === КОНЕЦ НОВОГО БЛОКА ===
#
#         print(f"[{serial}]: Задача по сохранению ключа выполнена. Возвращаемся на главный экран...")
#         d.app_start(app_package, stop=True)
#
#         return True
#
#     except Exception as e:
#         print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА в работе с Farcaster: {e}")
#         if d: d.screenshot(f"error_farcaster_{serial}.png")
#         return False

def wallet_eth_swap(serial):
    """
    Выполняет полный цикл обмена ETH на USDC в Farcaster.
    """
    print(f"\n[{serial}]: --- Начало сценария wallet_eth_swap ---")
    d = None
    try:
        d = u2.connect(serial)
        app_package = "com.farcaster.mobile"

        # --- Шаг 1: Переход в кошелек ---
        print(f"[{serial}]: Переход в кошелек (кнопка instance=3)...")

        wallet_button = d(className="android.widget.Button", instance=3)
        if not wallet_button.wait(timeout=10.0):
            print(f"[{serial}]: ОШИБКА: Кнопка кошелька не найдена.")
            return False
        wallet_button.click()
        time.sleep(3)

        # --- Шаг 2: Выбор Ethereum и переход к обмену ---
        print(f"[{serial}]: Выбор 'Ethereum'...")
        eth_button = d(text="Ethereum")
        if not eth_button.wait(timeout=10.0):
            print(f"[{serial}]: ОШИБКА: Кнопка 'Ethereum' не найдена.")
            return False
        eth_button.click()
        time.sleep(2)

        print(f"[{serial}]: Нажатие на кнопку 'Sell'...")
        d(description="Sell").click()
        time.sleep(3)

        # --- Шаг 3: Вычисление и ввод суммы ETH ---
        print(f"[{serial}]: Поиск баланса ETH...")
        # Ищем элемент, у которого description содержит ", ETH"
        eth_balance_element = d(descriptionContains=", ETH")
        if not eth_balance_element.wait(timeout=10.0):
            print(f"[{serial}]: ОШИБКА: Элемент с балансом ETH не найден.")
            return False

        # Извлекаем и вычисляем сумму
        full_balance_str = eth_balance_element.info['contentDescription'].split(',')[0].replace(',', '.')
        eth_balance = float(full_balance_str)
        percentage = random.uniform(0.50, 0.85)
        amount_to_swap = round(eth_balance * percentage, 6)
        print(
            f"[{serial}]: Полный баланс: {eth_balance} ETH. Выбрано для обмена: {amount_to_swap} ETH ({percentage:.0%}).")

        # Находим поле для ввода и вводим сумму
        amount_input_field = d(className="android.widget.TextView", text="0")
        if not amount_input_field.wait(timeout=5.0):
            print(f"[{serial}]: ОШИБКА: Поле для ввода суммы не найдено.")
            return False

        amount_input_field.click()
        time.sleep(1)
        # d.set_text() эмулирует ввод, это должно сработать
        d.set_text(str(amount_to_swap).replace('.', ','))
        print(f"[{serial}]: Сумма для обмена введена.")
        time.sleep(2)

        # --- Шаг 4: Выбор токена для получения (USDC) с умным скроллингом ---

        target_networks = ["Base", "Solana", "Optimism", "Arbitrum", "Unichain", "Celo"]
        target_network = random.choice(target_networks)
        print(f"[{serial}]: Целевая сеть для поиска: '{target_network}'")

        # Цикл с попытками выбора сети
        max_select_attempts = 3
        selection_successful = False
        for attempt in range(max_select_attempts):
            print(f"[{serial}]: Попытка выбора сети #{attempt + 1}...")

            # Нажимаем "Select" в начале каждой попытки
            if not d(description="Select").exists:
                print(f"[{serial}]: ОШИБКА: Не могу найти кнопку 'Select' для начала выбора.")
                break
            d(description="Select").click()
            time.sleep(2)

            # Пытаемся найти сеть скроллингом
            scroll_view = d(className="android.widget.HorizontalScrollView")
            if scroll_view.scroll.to(description=target_network):
                print(f"[{serial}]: Сеть '{target_network}' найдена. Клик...")
                d(description=target_network).click()

                usdc_button = d(text="USD Coin")
                if not usdc_button.wait(timeout=15.0):
                    print(f"[{serial}]: ОШИБКА: 'USD Coin' не появился после выбора сети. Повторяем...")
                    d.press("back")
                    time.sleep(1)
                    continue

                usdc_button.click()
                print(f"[{serial}]: 'USD Coin' успешно выбран.")
                selection_successful = True
                break

            # Если мы здесь, значит, scroll.to() не нашел элемент. Проверяем, почему.
            elif d(textStartsWith="No results found for").exists(timeout=2.0):
                print(f"[{serial}]: Обнаружена ошибка 'No results'. Закрываем и повторяем.")

                d(className="android.view.ViewGroup", instance=0).click()
                time.sleep(2)
                continue
            else:
                print(
                    f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА: Не удалось найти сеть '{target_network}' и ошибки 'No results' тоже нет.")
                # Делаем скриншот для анализа
                d.screenshot(f"error_scroll_{serial}.png")
                break

        # Финальная проверка после цикла
        if not selection_successful:
            print(f"[{serial}]: Не удалось выбрать токен после {max_select_attempts} попыток. Прерывание сценария.")
            return False

        # --- Шаг 5: Завершение обмена ---
        print(f"[{serial}]: Прокрутка вниз для поиска кнопки 'Review'...")
        d.swipe_ext("up", scale=0.8)
        time.sleep(2)

        review_button = d(description="Review")
        if not review_button.wait(timeout=10.0):
            print(f"[{serial}]: ОШИБКА: Кнопка 'Review' не найдена.")
            return False
        review_button.click()
        print(f"[{serial}]: Кнопка 'Review' нажата.")

        swap_button = d(description="Swap")
        if not swap_button.wait(timeout=15.0):
            print(f"[{serial}]: ОШИБКА: Кнопка 'Swap' не найдена.")
            return False

        time.sleep(1)  # Пауза перед нажатием
        swap_button.click()
        print(f"[{serial}]: Кнопка 'Swap' нажата. Ожидание завершения транзакции...")

        # --- Шаг 6: Возврат в кошелек ---
        random_wait = random.randint(5, 10)
        time.sleep(random_wait)

        print(f"[{serial}]: Возврат в кошелек...")
        # Используем тот же селектор, что и в начале
        d(className="android.widget.Button", instance=3).click()

        print(f"[{serial}]: --- Сценарий wallet_eth_swap успешно завершен ---")
        return True

    except Exception as e:
        print(f"[{serial}]: КРИТИЧЕСКАЯ ОШИБКА в сценарии wallet_eth_swap: {e}")
        if d: d.screenshot(f"error_swap_{serial}.png")
        return False

def run_automation_for_emulator(index, all_proxies, all_phrases):
    """Полный цикл работы для одного эмулятора."""

    # --- Шаг 1: Получаем путь к LDPlayer. Это должно быть первым действием. ---
    ld_path = get_ldplayer_path()

    # --- Шаг 2: Полная подготовка и настройка эмулятора ---
    if not prepare_and_configure_emulator(ld_path, index):
        print(f"[Индекс {index}]: Критическая ошибка на этапе подготовки. Прерывание работы.")
        return

    # --- Шаг 3: Запуск и ожидание ---
    subprocess.run([ld_path, "launch", "--index", str(index)])
    if not wait_for_emulator_boot(ld_path, index):
        return

    # --- Шаг 4: Получение серийного номера (теперь ld_path существует) ---
    serial = get_emulator_serial(ld_path, index)

    # --- Шаг 5: Установка приложений ---
    install_apps_from_paths(serial, APK_PATHS)

    # --- Шаг 6: Управление телефоном ---
    if serial:
        print(f"[{serial}]: Эмулятор готов к UI-автоматизации.")

        if not all_proxies:
            print(f"[{serial}]: Список прокси пуст. Пропуск UI-автоматизации.")
        else:
            proxy_for_this_emulator = all_proxies[index % len(all_proxies)]
            print(f"[{serial}]: Назначен прокси: {proxy_for_this_emulator['ip']}")

            if setup_super_proxy(serial, proxy_for_this_emulator):
                # perform_farcaster_actions(serial)
                pass

        if not all_phrases:
            print(f"[{serial}]: Список сид-фраз пуст. Пропуск Farcaster.")
        else:
            # Назначаем эмулятору сид-фразу по его индексу
            phrase_for_this_emulator = all_phrases[index % len(all_phrases)]

            # Вызываем нашу новую главную функцию
            login_farcaster(serial, phrase_for_this_emulator)

    print(f"[Индекс {index}]: Работа завершена.")


if __name__ == "__main__":
    proxies = load_proxies_from_file()
    phrases = load_farcaster_phrases()
    ld_path = get_ldplayer_path()

    BATCH_SIZE = 5
    TOTAL = len(phrases)  # количество сид-фраз = количество эмуляторов
    ready_emulators = []

    for batch_start in range(0, TOTAL, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, TOTAL)
        current_indices = range(batch_start, batch_end)
        ready_emulators.clear()

        print(f"\n{'=' * 20} ЗАПУСК БАТЧА {batch_start}-{batch_end - 1} {'=' * 20}")

        # === 1. Запуск и подготовка эмуляторов ===
        for i in current_indices:
            config_path = os.path.join(VMS_PATH, "config", f"leidian{i}.config")
            if not os.path.exists(config_path):
                print(f"[Индекс {i}]: ❌ Конфиг не найден. Пропуск.")
                continue

            # Включаем ADB
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                cfg["basicSettings.adbDebug"] = 1
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=4)
                print(f"[Индекс {i}]: ADB включен.")
            except Exception as e:
                print(f"[Индекс {i}]: Ошибка правки конфига: {e}")

            # Применяем настройки
            if not configure_emulator(ld_path, i):
                print(f"[Индекс {i}]: ❌ Ошибка при настройке. Пропуск.")
                continue

            # Запуск
            subprocess.run([ld_path, "launch", "--index", str(i)])
            if not wait_for_emulator_boot(ld_path, i):
                print(f"[Индекс {i}]: ❌ Не загрузился. Пропуск.")
                continue

            serial = get_emulator_serial(ld_path, i)
            if not serial:
                print(f"[Индекс {i}]: ❌ Не получил serial. Пропуск.")
                continue

            install_apps_from_paths(serial, APK_PATHS)

            proxy_data = proxies[i % len(proxies)] if proxies else None
            phrase_data = phrases[i] if i < len(phrases) else None
            ready_emulators.append({"index": i, "serial": serial, "proxy": proxy_data, "phrase": phrase_data})

            print(f"--- ✅ Эмулятор [{serial}] готов ---")

        if not ready_emulators:
            print("\n❌ Нет готовых эмуляторов в этом батче. Пропуск.")
            continue


        # === 2. Параллельная UI-автоматизация ===
        def run_single_emulator_task(emulator_info):
            serial = emulator_info["serial"]
            proxy = emulator_info["proxy"]
            phrase = emulator_info["phrase"]

            print(f"[{serial}]: 🚀 Запуск UI-автоматизации...")
            if proxy and not setup_super_proxy(serial, proxy):
                print(f"[{serial}]: ⚠ Ошибка прокси.")
            if phrase and not login_farcaster(serial, phrase):
                print(f"[{serial}]: ⚠ Ошибка Farcaster.")
            print(f"[{serial}]: ✅ Завершено.")


        threads = []
        for info in ready_emulators:
            t = threading.Thread(target=run_single_emulator_task, args=(info,))
            threads.append(t)
            t.start()
            time.sleep(3)

        for t in threads:
            t.join()

        # === 3. Закрытие и удаление эмуляторов ===
        for info in ready_emulators:
            idx = info["index"]
            print(f"[Индекс {idx}]: Закрытие эмулятора...")
            subprocess.run([ld_path, "quit", "--index", str(idx)], check=False)
            print(f"[Индекс {idx}]: Удаление эмулятора...")
            subprocess.run([ld_path, "remove", "--index", str(idx)], check=False)

        print(f"\n✅ Батч {batch_start}-{batch_end - 1} завершён, переходим к следующему.")

    print("\n\n🎯 Все сид-фразы обработаны. Работа завершена.")


