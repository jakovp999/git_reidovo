import os
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Регистрируем оригинальные системные папки TIA Portal V15.1
TIA_PATHS = [
    r"C:\Program Files\Siemens\Automation\Portal V15_1\Bin",
    r"C:\Program Files\Siemens\Automation\Portal V15_1\Bin\PublicAPI",
    r"C:\Program Files\Siemens\Automation\Portal V15_1\PublicAPI\V15.1"
]
for path in TIA_PATHS:
    if os.path.exists(path):
        os.add_dll_directory(path)

# Импортируем официально установленный в систему модуль Сименса
try:
    import siemens_tia_scripting as ts
except ImportError:
    print("❌ Критическая ошибка: модуль siemens_tia_scripting не инициализирован.")
    sys.exit(1)

# Автоматически определяем пути на основе расположения скрипта
current_dir = os.path.dirname(os.path.abspath(__file__))
SCL_FILE_PATH = os.path.join(current_dir, "data_type_symap.scl")
PROJECT_NAME = "reidovo"

class TIAHotReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_modified = 0

    def on_modified(self, event):
        if os.path.normpath(event.src_path) == os.path.normpath(SCL_FILE_PATH):
            current_time = time.time()
            if current_time - self.last_modified < 1.0:
                return
            self.last_modified = current_time
            time.sleep(0.3)  # Пауза, чтобы редактор освободил файл перед чтением
            self.execute_import()

    def execute_import(self):
        print(f"\n[{time.strftime('%H:%M:%S')}] Файл изменен! Запуск Hot-Reload...")
        try:
            # Подключаемся к запущенному экземпляру TIA Portal V15.1
            portal = ts.attach_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface, version="15.1")
            project = portal.get_project()
            
            # Получаем список ПЛК в проекте
            plcs = project.get_plcs()
            if not plcs:
                print("❌ Ошибка: В проекте 'reidovo' не обнаружено ни одного ПЛК.")
                return
            
            plc = plcs[0]  # Извлекаем первый ПЛК
            
            # ==============================================================================
            # УМНЫЙ ПОИСК ИСТОЧНИКОВ ДЛЯ S7-300 (Обход вложенных элементов процессора)
            # ==============================================================================
            external_sources_list = None
            
            # Сначала проверяем верхний уровень ПЛК
            try:
                external_sources_list = plc.get_external_sources()
            except:
                pass
                
            # Если на верхнем уровне пусто или вызвало ошибку, пробиваем скрытые DeviceItems процессора
            if not external_sources_list:
                # Если у объекта plc есть дочерние элементы (или у его родительской станции)
                items_source = plc
                if hasattr(plc, 'device_items'):
                    items = plc.device_items() if callable(plc.device_items) else plc.device_items
                else:
                    # Пробуем подняться к станции и взять её модули
                    parent = plc.parent() if callable(plc.parent) else plc.parent
                    items = parent.device_items() if (parent and hasattr(parent, 'device_items')) else []
                
                for item in items:
                    if hasattr(item, 'get_external_sources'):
                        try:
                            res = item.get_external_sources()
                            # Проверяем, что это список и он доступен
                            if res is not None:
                                external_sources_list = res
                                break
                        except:
                            pass

            if external_sources_list is None:
                print("❌ Ошибка: Не удалось обнаружить папку 'External source files' для S7-300.")
                return
            
            file_name = os.path.basename(SCL_FILE_PATH)
            source_pure_name = os.path.splitext(file_name)[0]
            
            # 1. БЕЗОПАСНО УДАЛЯЕМ СТАРЫЙ ИСТОЧНИК (Чтобы избежать дубликатов на уровне CPU)
            for src in list(external_sources_list):
                try:
                    if str(src.get_name()) == str(source_pure_name):
                        src.delete()
                        print(f"🗑️ Старый источник '{file_name}' удален из дерева проекта.")
                except:
                    pass
            
            # 2. ИМПОРТИРУЕМ ОБНОВЛЕННЫЙ ФАЙЛ С ДИСКА
            print(f"📥 Загрузка файла '{file_name}' в External source files...")
            external_sources_list.append(SCL_FILE_PATH)
            
            # Даем TIA Portal время физически обновить базу данных проекта
            time.sleep(0.5)
            
            # 3. НАХОДИМ СВЕЖИЙ ОБЪЕКТ
            new_source = None
            for src in external_sources_list:
                if str(src.get_name()) == str(source_pure_name):
                    new_source = src
                    break
            
            # Если по имени не нашло, берем самый последний элемент списка в качестве подстраховки
            if new_source is None and len(external_sources_list) > 0:
                new_source = external_sources_list[-1]
                
            if new_source is None:
                print("❌ Ошибка: Файл загружен, но не зафиксирован в списке источников CPU.")
                return
                
            print(f"📦 Файл '{new_source.get_name()}' успешно зафиксирован в дереве процессора.")
                
            # 4. ЗАПУСКАЕМ ГЕНЕРАЦИЮ БЛОКОВ UDT (СТРАНИЦА 10 ВАШЕЙ ДОКУМЕНТАЦИИ СИМЕНСА)
            print("⚡ Компиляция SCL и генерация UDT блоков...")
            new_source.block_gen()
            
            print(f"✅ Успех! Структуры UDT успешно сгенерированы/обновлены в папке 'PLC data types'.")
            
        except Exception as e:
            print(f"❌ Ошибка автоматизации Siemens: {e}")

if __name__ == "__main__":
    if not os.path.exists(SCL_FILE_PATH):
        print(f"Ошибка: Файл {SCL_FILE_PATH} не найден!")
        sys.exit(1)

    print("========================================================")
    print("  TIA Portal V15.1 Python Hot-Reload Service запущен")
    print("========================================================")
    print(f"Слежу за файлом: {SCL_FILE_PATH}")
    print("Ожидаю изменений (Ctrl+S во внешнем редакторе)... Нажмите Ctrl+C для выхода.\n")
    
    event_handler = TIAHotReloadHandler()
    observer = Observer()
    observer.schedule(event_handler, path=current_dir, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
