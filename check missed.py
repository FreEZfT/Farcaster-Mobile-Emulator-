file_seed = "farcaster_phrase.txt"    # формат: seedphrase
file_pk = "privatkey.txt"            # формат: privatekey:seedphrase
file_missed = "missed.txt"            # результат

# Читаем сид-фразы из первого файла
with open(file_seed, "r", encoding="utf-8") as f:
    seeds_list = [line.strip() for line in f if line.strip()]

# Читаем сид-фразы из второго файла (после двоеточия)
with open(file_pk, "r", encoding="utf-8") as f:
    pk_seeds_list = []
    for line in f:
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            _, seed = line.split(":", 1)
            pk_seeds_list.append(seed.strip())

# Превращаем во множество для быстрого поиска
pk_seeds_set = set(pk_seeds_list)

# Находим сид-фразы, которых нет во втором файле
missed_phrases = [seed for seed in seeds_list if seed not in pk_seeds_set]

# Записываем результат
with open(file_missed, "w", encoding="utf-8") as f:
    for phrase in missed_phrases:
        f.write(phrase + "\n")

print(f"Готово! Найдено {len(missed_phrases)} пропущенных сид-фраз. Результат в {file_missed}")