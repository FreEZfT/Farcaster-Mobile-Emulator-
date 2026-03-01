import subprocess
import os
import time

# Импортируем нужные функции из нашего основного файла
from LDCaster import (get_ldplayer_path, wait_for_emulator_boot, install_apps_from_paths, get_emulator_serial,
                  prepare_and_configure_emulator,  configure_emulator, APK_PATHS, load_proxies_from_file,
                  setup_super_proxy, load_farcaster_phrases, login_farcaster, wallet_eth_swap)

# --- КОНФИГУРАЦИЯ ДЛЯ РАЗРАБОТКИ ---
# Мы будем работать только с первым эмулятором (индекс 0)
EMULATOR_INDEX = 0


def development_setup():
    """Подготавливает один эмулятор для разработки и оставляет его работать."""
    print("--- ЗАПУСК В РЕЖИМЕ РАЗРАБОТКИ ---")
    ld_path = get_ldplayer_path()

    # --- Шаг 1: ПОЛНАЯ ПОДГОТОВКА И НАСТРОЙКА ---
    if not prepare_and_configure_emulator(ld_path, EMULATOR_INDEX):
        print(f"[Индекс {EMULATOR_INDEX}]: Критическая ошибка на этапе подготовки. Выход.")
        return

    # --- Запуск и ожидание ---
    print(f"[Индекс {EMULATOR_INDEX}]: Запуск эмулятора...")
    subprocess.run([ld_path, "launch", "--index", str(EMULATOR_INDEX)])

    if not wait_for_emulator_boot(ld_path, EMULATOR_INDEX):
        return

    serial = get_emulator_serial(ld_path, EMULATOR_INDEX)
    install_apps_from_paths(serial, APK_PATHS)

    print("\n[ПАУЗА] Ожидание 5 секунд, чтобы иконки приложений успели появиться...")
    time.sleep(5)

    print("\n" + "=" * 50)
    print(f"Эмулятор [{serial}] готов для разработки.")
    print("Теперь вы можете открыть НОВЫЙ терминал и запустить 'python -m weditor'")
    print("Чтобы остановить этот скрипт и закрыть эмулятор, нажмите Ctrl+C в этой консоли.")
    print("="*50 + "\n")

    # --- ТЕСТОВЫЙ ЗАПУСК UI-АВТОМАТИЗАЦИИ ---
    if serial:
        # Загружаем прокси из файла
        proxies = load_proxies_from_file()
        if proxies:
            # Берем первый прокси из списка для теста
            proxy_to_test = proxies[0]
            print(f"Тестируем настройку прокси: {proxy_to_test['ip']}")

            # Вызываем нашу главную функцию
            setup_super_proxy(serial, proxy_to_test)

            print("\nТестовый сценарий для Super Proxy завершен.")
        else:
            print("Файл с прокси пуст, UI-тест не может быть выполнен.")

        phrases = load_farcaster_phrases()
        if phrases:
            phrase_to_test = phrases[0]  # Берем первую фразу для теста
            print(f"\nТестируем сценарий Farcaster с фразой: '{phrase_to_test[:15]}...'")

            # Вызываем нашу новую функцию
            login_farcaster(serial, phrase_to_test)
            time.sleep(1)


            print("\nТестовый сценарий для Farcaster завершен.")
        else:
            print("Файл с сид-фразами пуст, тест Farcaster не может быть выполнен.")

    try:
        # Этот цикл просто не дает скрипту завершиться
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # При нажатии Ctrl+C мы выходим и закрываем эмулятор
        print("\nЗавершение работы... Закрытие эмулятора.")
        subprocess.run([ld_path, "quit", "--index", str(EMULATOR_INDEX)])
        print("Эмулятор закрыт.")


if __name__ == "__main__":
    development_setup()