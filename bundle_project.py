import os

# Обновленные настройки исключений (добавлен .venv)
EXCLUDE_DIRS = {'.venv', 'venv', 'env', '.env', '.git', '.idea', '__pycache__', 'build', 'dist'}
EXCLUDE_FILES = {'bundle_project.py', 'gemini_context.txt', 'bundle_project.bat', 'bundle.bat'}
ALLOWED_EXTENSIONS = {'.py', '.md', '.txt', '.json', '.ini'}
OUTPUT_FILENAME = 'gemini_context.txt'


def generate_tree(startpath):
    """Генерирует текстовое дерево структуры проекта."""
    tree_lines = []
    for root, dirs, files in os.walk(startpath):
        # Отсекаем ненужные папки, чтобы не идти вглубь
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        level = root.replace(startpath, '').count(os.sep)
        indent = ' ' * 4 * level
        basename = os.path.basename(root)
        if basename:
            tree_lines.append(f"{indent}{basename}/")
        else:
            tree_lines.append("./")

        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if f not in EXCLUDE_FILES and any(f.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                tree_lines.append(f"{subindent}{f}")
    return '\n'.join(tree_lines)


def main():
    current_dir = os.getcwd()
    print(f"[INFO] Сканирование директории: {current_dir}")

    # Проверяем наличие файла состояния, если его нет — создаем шаблон
    state_file = 'project_state.md'
    if not os.path.exists(state_file):
        with open(state_file, 'w', encoding='utf-8') as sf:
            sf.write(
                "# Текущее состояние проекта\n\n## Архитектура и Технологии\n- Python, PyQt5, Modbus\n\n## Текущий план\n- Настройка отображения случайных данных в таблице\n- Исправление прокрутки колесиком\n- Удаление лишнего столбца К1\n\n## Исправленные баги\n- Фикс AttributeError 'NoneType' object has no attribute 'deleteLater' в memory_viewer.py\n")
        print(f"[INFO] Создан дефолтный шаблон файла состояния: {state_file}")

    try:
        with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as outfile:
            # Заголовок контекста
            outfile.write("# ==========================================================\n")
            outfile.write("# АВТОМАТИЧЕСКИЙ КОНТЕКСТ ПРОЕКТА ДЛЯ GEMINI NOTEBOOK\n")
            outfile.write("# ==========================================================\n\n")

            # Дерево проекта
            outfile.write("# СТРУКТУРА ПРОЕКТА\n")
            outfile.write("```\n")
            outfile.write(generate_tree(current_dir))
            outfile.write("\n```\n\n")

            # Содержимое файлов
            for root, dirs, files in os.walk(current_dir):
                # Еще раз отсекаем папки при чтении файлов
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for file in files:
                    if file in EXCLUDE_FILES or file == OUTPUT_FILENAME:
                        continue
                    if not any(file.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                        continue

                    rel_path = os.path.relpath(os.path.join(root, file), current_dir)
                    outfile.write("# ==========================================================\n")
                    outfile.write(f"# ФАЙЛ: {rel_path}\n")
                    outfile.write("# ==========================================================\n\n")

                    ext = os.path.splitext(file)[1]
                    lang = ext.replace('.', '') if ext != '.md' else 'markdown'
                    if lang == 'py': lang = 'python'

                    outfile.write(f"```{lang}\n")
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
                    except Exception as e:
                        outfile.write(f"[Ошибка чтения файла: {e}]\n")
                    outfile.write("\n```\n\n")

        print(f"[SUCCESS] Файл {OUTPUT_FILENAME} успешно сгенерирован!")
    except Exception as e:
        print(f"[ERROR] Ошибка при записи итогового файла: {e}")


if __name__ == '__main__':
    main()