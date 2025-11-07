from __future__ import annotations
import tkinter as tk
from tkinter import ttk, font, filedialog, messagebox, simpledialog
import os
import json
import keyword
import re
import sys
import ast
import html
import traceback

# Спрячем консоль на Windows при запуске через python.exe
if sys.platform == "win32":
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
            try:
                ctypes.windll.kernel32.FreeConsole()
            except Exception:
                pass
    except Exception:
        pass

APP_NAME = "Fly Create Pro"

# Базовые темы (можно расширять/замещать библиотеками .dl)
THEMES = {
    "Светлая": {
        "background": "#ffffff",
        "foreground": "#000000",
        "cursor": "#000000",
        "selectbackground": "#2f2f2f",
        "selectforeground": "#ffffff",
        "linenumber_bg": "#f0f0f0",
        "tab_bg": "#f5f5f5",
        "tag": {
            "keyword": {"foreground": "#0000ff"},
            "string": {"foreground": "#a31515"},
            "comment": {"foreground": "#008000"},
            "number": {"foreground": "#098658"},
            "builtin": {"foreground": "#795e26"},
        },
    },
    "Тёмная": {
        "background": "#1e1e1e",
        "foreground": "#d4d4d4",
        "cursor": "#ffffff",
        "selectbackground": "#dbeeff",
        "selectforeground": "#000000",
        "linenumber_bg": "#2b2b2b",
        "tab_bg": "#2a2a2a",
        "tag": {
            "keyword": {"foreground": "#569cd6"},
            "string": {"foreground": "#ce9178"},
            "comment": {"foreground": "#6a9955"},
            "number": {"foreground": "#b5cea8"},
            "builtin": {"foreground": "#dcdcaa"},
        },
    },
}

PY_KEYWORDS = set(keyword.kwlist)
PY_BUILTINS = set(dir(__builtins__))

# Регэкспы для подсветки
RE_COMMENT = re.compile(r"#.*")
RE_STRING = re.compile(r"('''.*?'''|\"\"\".*?\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", re.DOTALL)
RE_NUMBER = re.compile(r"\b\d+(\.\d+)?\b")
RE_WORD = re.compile(r"\b[A-Za-z_]\w*\b")

# Папка для библиотек (рядом с editor.py)
LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")

def find_brace_block(text: str, start_index: int) -> tuple[int, int]:
    n = len(text)
    i = start_index
    if i >= n or text[i] != "{":
        return -1, -1
    depth = 0
    in_single = False
    in_double = False
    escape = False
    while i < n:
        ch = text[i]
        if escape:
            escape = False
        elif ch == "\\":
            escape = True
        elif in_single:
            if ch == "'" and not escape:
                in_single = False
        elif in_double:
            if ch == '"' and not escape:
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return start_index, i + 1
        i += 1
    return -1, -1


def extract_fields_from_text(raw: str) -> dict:
    fields = {}
    for key in ("name", "creator", "value", "code", "type"):
        m = re.search(r"\b" + re.escape(key) + r"\s*:\s*\{", raw, flags=re.IGNORECASE)
        if not m:
            continue
        brace_start = raw.find("{", m.start())
        s, e = find_brace_block(raw, brace_start)
        if s == -1:
            continue
        inner = raw[s + 1:e - 1].strip()
        fields[key] = inner
    if "code" in fields:
        code_text = fields["code"]
        try:
            parsed = json.loads("{" + code_text + "}") if (code_text.strip().startswith('"') or ":" in code_text) else code_text
            fields["code"] = parsed
        except Exception:
            try:
                parsed = ast.literal_eval("{" + code_text + "}") if ":" in code_text else code_text
                fields["code"] = parsed
            except Exception:
                fields["code"] = code_text
    for k in ("name", "creator", "value", "type"):
        if k in fields:
            v = fields[k].strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            fields[k] = v
    return fields


def smart_save_dl(obj: dict, dest_path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# -------------------------
# PluginManager (интегрирован)
# -------------------------
class DataLibrary:
    def __init__(self, path: str, raw: dict):
        self.path = path
        self.raw = raw
        self.type = raw.get("type")
        self.name = raw.get("name")
        self.creator = raw.get("creator")
        self.value = raw.get("value")
        self.code = raw.get("code")


class PluginManager:
    """
    Интегрированный менеджер библиотек .dl.
    Загружает библиотеки из папки libs/ (не создаёт и не записывает встроенные файлы).
    Позволяет применять тему, включать бинды (insert-only), открывать вкладки.
    """
    def __init__(self, app, menu: tk.Menu, libs_dir: str = LIBS_DIR):
        self.app = app
        self.menu = menu
        self.libs_dir = libs_dir
        self.libs: list[DataLibrary] = []
        self.binds: dict[str, dict] = {}
        # Создаём только папку, не записываем никаких примеров
        os.makedirs(self.libs_dir, exist_ok=True)
        self._load_all()
        self._build_menu()

    def _load_all(self):
        self.libs.clear()
        for fname in sorted(os.listdir(self.libs_dir)):
            if not fname.lower().endswith(".dl"):
                continue
            path = os.path.join(self.libs_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if not all(k in raw for k in ("type", "name", "creator", "value", "code")):
                    continue
                dl = DataLibrary(path, raw)
                self.libs.append(dl)
                if dl.type == "theme":
                    self._register_theme(dl)
                elif dl.type == "bind":
                    self._register_bind(dl)
                elif dl.type == "tabs":
                    self._register_tabs(dl)
            except Exception:
                traceback.print_exc()
                continue

    def _build_menu(self):
        try:
            self.menu.delete(0, "end")
        except Exception:
            pass
        self.menu.add_command(label="Установить .dl из файла...", command=self.install_dl_from_file)
        self.menu.add_command(label="Импорт .dl из текста (.txt)...", command=self.import_dl_from_text_file)
        self.menu.add_command(label="Создать новую .dl (форма)...", command=self.create_dl_via_form)
        self.menu.add_separator()
        if not self.libs:
            self.menu.add_command(label="Нет установленных библиотек", state="disabled")
            self.menu.add_separator()
            self.menu.add_command(label="Открыть папку с библиотеками...", command=lambda: self._open_libs_folder())
            return
        for dl in self.libs:
            sub = tk.Menu(self.menu, tearoff=False)
            self.menu.add_cascade(label=dl.name, menu=sub)
            sub.add_command(label=f"Инфо (создатель: {dl.creator})", command=lambda d=dl: self._show_info(d))
            if dl.type == "theme":
                sub.add_command(label="Установить тему", command=lambda d=dl: self.apply_theme_from_dl(d))
            if dl.type == "bind":
                sub.add_command(label="Включить биндинг", command=lambda d=dl: self.enable_bind(d))
                sub.add_command(label="Отключить биндинг", command=lambda d=dl: self.disable_bind(d))
            if dl.type == "tabs":
                tabs = dl.code.get("tabs") if isinstance(dl.code, dict) else None
                if isinstance(tabs, list):
                    for t in tabs:
                        title = t.get("title", "Без названия")
                        sub.add_command(label=f"Открыть вкладку: {title}", command=lambda t=t: self.app.new_tab(content=t.get("content", "")))
            sub.add_separator()
            sub.add_command(label="Показать raw .dl", command=lambda d=dl: self._show_raw(d))
        self.menu.add_separator()
        self.menu.add_command(label="Открыть папку с библиотеками...", command=lambda: self._open_libs_folder())

    def _show_info(self, dl: DataLibrary):
        txt = f"Имя: {dl.name}\nСоздатель: {dl.creator}\nТип: {dl.type}\nФайл: {dl.path}"
        messagebox.showinfo("Информация о библиотеке", txt)

    def _show_raw(self, dl: DataLibrary):
        try:
            with open(dl.path, "r", encoding="utf-8") as f:
                txt = f.read()
        except Exception as e:
            txt = f"Не удалось прочитать файл: {e}"
        RawViewer(self.app, txt)

    def apply_theme_from_dl(self, dl: DataLibrary):
        code = dl.code
        if isinstance(code, dict):
            prefer = None
            for candidate in ("Светлая", "Light", "Default"):
                if candidate in code:
                    prefer = candidate
                    break
            if prefer is None:
                prefer = next(iter(code.keys()))
            theme_data = code[prefer] if isinstance(code.get(prefer), dict) else code
            THEMES[dl.name] = theme_data
            try:
                self.app.apply_theme(dl.name)
            except Exception:
                pass
        else:
            THEMES[dl.name] = code
            try:
                self.app.apply_theme(dl.name)
            except Exception:
                pass

    def _register_theme(self, dl: DataLibrary):
        try:
            code = dl.code
            if isinstance(code, dict):
                simple_keys = {"background", "foreground", "cursor"}
                if simple_keys.issubset(set(code.keys())):
                    THEMES[dl.name] = code
                else:
                    for branch, val in code.items():
                        THEMES[f"{dl.name} - {branch}"] = val
            else:
                THEMES[dl.name] = code
        except Exception:
            pass

    def _combo_to_tk(self, combo_str: str) -> str | None:
        if not combo_str:
            return None
        parts = [p.strip() for p in combo_str.split("+") if p.strip()]
        mods = []
        key = None
        for p in parts:
            lp = p.lower()
            if lp in ("ctrl", "control"):
                mods.append("Control")
            elif lp in ("alt",):
                mods.append("Alt")
            elif lp in ("shift",):
                mods.append("Shift")
            elif lp in ("win", "meta", "super"):
                mods.append("Mod4")
            else:
                key = p
        if not key:
            return None
        if len(key) == 1:
            key = key.lower()
        return "<" + "-".join(mods + [key]) + ">"

    def _register_bind(self, dl: DataLibrary):
        try:
            code = dl.code or {}
            combo = code.get("combo")
            action = code.get("action")
            if not combo or not action:
                return
            tk_combo = self._combo_to_tk(combo)
            if not tk_combo:
                return
            if action != "insert":
                return
            text = code.get("text", "")
            def handler(event, _text=text):
                try:
                    tab = self.app.current_editor_tab()
                    if not tab:
                        return "break"
                    tab.text.insert("insert", _text)
                except Exception:
                    pass
                return "break"
            entry = {"dl": dl, "tk": tk_combo, "handler": handler, "enabled": False}
            self.binds[dl.name] = entry
            self.enable_bind(dl)
        except Exception:
            pass

    def enable_bind(self, dl: DataLibrary):
        info = self.binds.get(dl.name)
        if not info:
            return
        if info.get("enabled"):
            return
        self.app.bind_all(info["tk"], info["handler"])
        info["enabled"] = True
        messagebox.showinfo("Бинд включён", f"Бинд из '{dl.name}' включён (комбинация {dl.code.get('combo')}).")

    def disable_bind(self, dl: DataLibrary):
        info = self.binds.get(dl.name)
        if not info or not info.get("enabled"):
            return
        try:
            self.app.unbind_all(info["tk"])
        except Exception:
            pass
        info["enabled"] = False
        messagebox.showinfo("Бинд отключён", f"Бинд из '{dl.name}' отключён.")

    def _register_tabs(self, dl: DataLibrary):
        pass

    def install_dl_from_file(self):
        path = filedialog.askopenfilename(filetypes=[("Data library", "*.dl"), ("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not all(k in raw for k in ("type", "name", "creator", "value", "code")):
                messagebox.showerror("Ошибка", "Файл не соответствует формату .dl (необходимы поля type,name,creator,value,code).")
                return
            dest = os.path.join(self.libs_dir, os.path.basename(path))
            if os.path.abspath(path) != os.path.abspath(dest):
                smart_save_dl(raw, dest)
            self._load_all()
            self._build_menu()
            messagebox.showinfo("Установлено", "Библиотека установлена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось установить .dl: {e}")

    def import_dl_from_text_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt;*.dl;*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл: {e}")
            return
        fields = extract_fields_from_text(txt)
        if not fields:
            messagebox.showerror("Ошибка", "Не удалось распознать поля в тексте.")
            return
        dl_obj = {}
        ttype = fields.get("type") or fields.get("value") or "theme"
        dl_obj["type"] = ttype
        dl_obj["name"] = fields.get("name") or "ImportedLib"
        dl_obj["creator"] = fields.get("creator") or "unknown"
        dl_obj["value"] = fields.get("value") or ttype
        dl_obj["code"] = fields.get("code") or {}
        PreviewAndSaveDialog(self.app, json.dumps(dl_obj, ensure_ascii=False, indent=2), lambda dest: self._save_imported(dl_obj, dest))

    def _save_imported(self, dl_obj: dict, dest_filename: str | None):
        if not dest_filename:
            return
        dest = os.path.join(self.libs_dir, dest_filename if dest_filename.lower().endswith(".dl") else dest_filename + ".dl")
        ok = smart_save_dl(dl_obj, dest)
        if ok:
            messagebox.showinfo("Сохранено", f"Библиотека сохранена в {dest}")
            self._load_all()
            self._build_menu()
        else:
            messagebox.showerror("Ошибка", "Не удалось сохранить .dl")

    def create_dl_via_form(self):
        FormCreateDL(self.app, on_save=lambda obj, fname: self._save_imported(obj, fname))

    def _open_libs_folder(self):
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(['explorer', os.path.normpath(self.libs_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(['open', self.libs_dir])
            else:
                subprocess.Popen(['xdg-open', self.libs_dir])
        except Exception:
            messagebox.showinfo("Папка библиотек", f"Путь: {self.libs_dir}")


# -------------------------
# Несколько простых диалогов/утилит UI
# -------------------------
class RawViewer(tk.Toplevel):
    def __init__(self, master, text: str):
        super().__init__(master)
        self.title("Raw .dl / preview")
        self.geometry("700x400")
        txt = tk.Text(self, wrap="none")
        txt.insert("1.0", text)
        txt.config(state="normal")
        txt.pack(fill=tk.BOTH, expand=True)
        btn = ttk.Button(self, text="Закрыть", command=self.destroy)
        btn.pack(pady=4)


class PreviewAndSaveDialog(tk.Toplevel):
    def __init__(self, master, preview_text: str, on_save):
        super().__init__(master)
        self.title("Предпросмотр .dl")
        self.on_save = on_save
        self.geometry("700x450")
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Предпросмотр .dl (JSON):").pack(anchor="w")
        self.txt = tk.Text(frm, height=18, wrap="none")
        self.txt.pack(fill=tk.BOTH, expand=True)
        self.txt.insert("1.0", preview_text)
        bottom = ttk.Frame(frm)
        bottom.pack(fill=tk.X, pady=6)
        ttk.Label(bottom, text="Имя файла для сохранения (без пути):").pack(side=tk.LEFT)
        self.filename = ttk.Entry(bottom, width=30)
        suggested = "imported_" + str(abs(hash(preview_text)))[:6] + ".dl"
        self.filename.insert(0, suggested)
        self.filename.pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Сохранить", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="Отмена", command=self.destroy).pack(side=tk.RIGHT, padx=6)

    def _save(self):
        fname = self.filename.get().strip()
        if not fname:
            messagebox.showerror("Ошибка", "Введите имя файла")
            return
        self.on_save(fname)
        self.destroy()


class FormCreateDL(tk.Toplevel):
    def __init__(self, master, on_save):
        super().__init__(master)
        self.title("Создать .dl — форма")
        self.on_save = on_save
        self.geometry("700x500")
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Тип библиотеки:").grid(row=0, column=0, sticky="w")
        self.type_var = tk.StringVar(value="theme")
        ttk.Combobox(frm, textvariable=self.type_var, values=["theme", "bind", "tabs"], state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text="Имя:").grid(row=1, column=0, sticky="w")
        self.name_e = ttk.Entry(frm, width=40); self.name_e.grid(row=1, column=1, sticky="w")
        ttk.Label(frm, text="Создатель:").grid(row=2, column=0, sticky="w")
        self.creator_e = ttk.Entry(frm, width=40); self.creator_e.grid(row=2, column=1, sticky="w")
        ttk.Label(frm, text="Value (повторяет тип):").grid(row=3, column=0, sticky="w")
        self.value_e = ttk.Entry(frm, width=40); self.value_e.grid(row=3, column=1, sticky="w")
        ttk.Label(frm, text="Code (JSON). Пример для темы — объект с ключами 'Светлая'/'Тёмная' и значениями темы.").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8,0))
        self.code_t = tk.Text(frm, height=15, wrap="none")
        self.code_t.grid(row=5, column=0, columnspan=2, sticky="nsew")
        frm.grid_rowconfigure(5, weight=1)
        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=8)
        ttk.Button(btns, text="Сохранить .dl", command=self._on_save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side=tk.RIGHT)

    def _on_save(self):
        ttype = self.type_var.get()
        name = self.name_e.get().strip() or "user_lib"
        creator = self.creator_e.get().strip() or "unknown"
        value = self.value_e.get().strip() or ttype
        code_txt = self.code_t.get("1.0", tk.END).strip()
        try:
            try:
                code_obj = json.loads(code_txt)
            except Exception:
                code_obj = ast.literal_eval(code_txt)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось разобрать код (code) как JSON/Python literal:\n{e}")
            return
        obj = {"type": ttype, "name": name, "creator": creator, "value": value, "code": code_obj}
        suggested = name.replace(" ", "_") + ".dl"
        self.on_save(obj, suggested)
        self.destroy()


# -------------------------
# Основной редактор (с уже встроенным плагином)
# -------------------------
class EditorTab:
    def __init__(self, text_widget, filepath=None, font_obj=None, wrap=False):
        self.text = text_widget
        self.filepath = filepath
        self.font = font_obj
        self.wrap = wrap
        self._text_changed = False
        self.syntax = "python" if filepath and filepath.endswith(".py") else None
        self._highlight_after_id = None


class TextEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1000x700")
        self.minsize(600, 320)
        self.notebook = None
        self.tabs: dict = {}
        self.current_theme = "Светлая"
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.default_font = font.Font(family="Consolas" if "Consolas" in font.families() else "Courier", size=12)
        self._setup_ui()
        self._bind_shortcuts()
        # Plugin manager integrated
        self.plugins_menu = tk.Menu(self.menubar, tearoff=False)
        self.menubar.add_cascade(label="Библиотеки", menu=self.plugins_menu)
        self.plugin_manager = PluginManager(self, self.plugins_menu, libs_dir=LIBS_DIR)
        # create first tab
        self.new_tab()

    def _setup_ui(self):
        menubar = tk.Menu(self)
        self.menubar = menubar
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Новый", accelerator="Ctrl+N", command=self.new_tab)
        file_menu.add_command(label="Открыть...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Сохранить", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Сохранить как...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Закрыть вкладку", accelerator="Ctrl+W", command=self.close_current_tab)
        file_menu.add_command(label="Выход", accelerator="Alt+F4", command=self.on_close)
        menubar.add_cascade(label="Файл", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Отменить", accelerator="Ctrl+Z", command=self.edit_undo)
        edit_menu.add_command(label="Повторить", accelerator="Ctrl+Y", command=self.edit_redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Вырезать", accelerator="Ctrl+X", command=lambda: self._cur_text_event("<<Cut>>"))
        edit_menu.add_command(label="Копировать", accelerator="Ctrl+C", command=lambda: self._cur_text_event("<<Copy>>"))
        edit_menu.add_command(label="Вставить", accelerator="Ctrl+V", command=lambda: self._cur_text_event("<<Paste>>"))
        edit_menu.add_command(label="Выделить всё", accelerator="Ctrl+A", command=self.select_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Найти/Заменить...", accelerator="Ctrl+F", command=self.open_find_replace)
        menubar.add_cascade(label="Правка", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        self.wrap_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(label="Перенос по словам", variable=self.wrap_var, command=self._toggle_wrap_global)
        view_menu.add_command(label="Выбрать шрифт...", command=self.choose_font)
        theme_menu = tk.Menu(view_menu, tearoff=False)
        for theme in THEMES.keys():
            theme_menu.add_command(label=theme, command=lambda t=theme: self.apply_theme(t))
        view_menu.add_cascade(label="Тема", menu=theme_menu)
        menubar.add_cascade(label="Вид", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=help_menu)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._on_tab_changed())

        self.statusbar = ttk.Label(self, text="", anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    # --- Вкладки / Текстовые поля ---
    def new_tab(self, filepath=None, content=None):
        frame = ttk.Frame(self.notebook)
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        text = tk.Text(frame, wrap="none", undo=True, yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set, padx=6, pady=6)
        # Явно разрешаем редактирование (вдруг что-то поставило DISABLED раньше)
        text.config(state="normal", takefocus=True)
        v_scroll.config(command=text.yview); h_scroll.config(command=text.xview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y); h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        text.configure(font=self.default_font)
        for tag in ("keyword", "string", "comment", "number", "builtin"):
            text.tag_configure(tag)
        text.bind("<<Modified>>", lambda e, t=text: self._on_text_modified(t))
        text.bind("<KeyRelease>", lambda e, t=text: self._on_key_release(t))
        text.bind("<ButtonRelease-1>", lambda e, t=text: self._update_statusbar(t))
        text.bind("<Control-a>", lambda e: self.select_all() or "break")
        if content:
            text.insert("1.0", content)
        title = os.path.basename(filepath) if filepath else "Безымянный"
        self.notebook.add(frame, text=title)
        self.notebook.select(frame)
        tab = EditorTab(text_widget=text, filepath=filepath, font_obj=self.default_font, wrap=False)
        if filepath and filepath.endswith(".py"):
            tab.syntax = "python"
        self.tabs[frame] = tab
        # Применяем тему и затем явно даём фокус тексту (чтобы можно было печатать сразу)
        self._apply_theme_to_text(tab)
        try:
            text.edit_reset(); text.edit_modified(False)
        except Exception:
            pass
        # Фокус и состояние normal — чтобы пользователь мог печатать
        try:
            text.focus_set()
            text.config(state="normal")
        except Exception:
            pass
        self._update_title(); self._update_statusbar(text)
        return frame

    def _current_frame(self):
        sel = self.notebook.select()
        if not sel:
            return None
        return self.nametowidget(sel)

    def current_editor_tab(self):
        frame = self._current_frame()
        if not frame:
            return None
        return self.tabs.get(frame)

    def close_current_tab(self):
        frame = self._current_frame()
        if not frame:
            return
        tab = self.tabs.get(frame)
        if tab and tab._text_changed:
            ans = messagebox.askyesnocancel("Несохранённые изменения", "Сохранить изменения вкладки?")
            if ans is None:
                return
            if ans:
                ok = self.save_file()
                if not ok:
                    return
        self.notebook.forget(frame)
        del self.tabs[frame]
        if not self.notebook.tabs():
            self.new_tab()
        else:
            self._update_title(); self._update_statusbar_for_current()

    # --- Файлы ---
    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("Все файлы", "*.*"), ("Текстовые", "*.txt;*.py;*.md;*.json;*.csv")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="cp1251", errors="replace") as f:
                data = f.read()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")
            return
        frame = self.new_tab(filepath=path, content=data)
        self.notebook.tab(frame, text=os.path.basename(path))
        tab = self.tabs[frame]
        tab.filepath = path; tab.syntax = "python" if path.endswith(".py") else None
        tab.text.edit_reset(); tab._text_changed = False
        self._apply_syntax_highlight(tab)

    def save_file(self):
        tab = self.current_editor_tab()
        if not tab:
            return False
        if tab.filepath:
            return self._write(tab, tab.filepath)
        else:
            return self.save_file_as()

    def save_file_as(self):
        tab = self.current_editor_tab()
        if not tab:
            return False
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt;*.py;*.md;*.json;*.csv"), ("All files", "*.*")])
        if not path:
            return False
        ok = self._write(tab, path)
        if ok:
            frame = self._current_frame()
            self.notebook.tab(frame, text=os.path.basename(path))
            tab.filepath = path
            tab.syntax = "python" if path.endswith(".py") else None
            self._apply_syntax_highlight(tab)
        return ok

    def _write(self, tab: EditorTab, path: str):
        try:
            text = tab.text.get("1.0", tk.END)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.rstrip("\n"))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")
            return False
        tab.filepath = path; tab._text_changed = False
        try: tab.text.edit_modified(False)
        except Exception: pass
        self._update_title(); self._update_statusbar_for_current()
        return True

    # --- Редактирование ---
    def edit_undo(self):
        tab = self.current_editor_tab(); 
        if not tab: return
        try: tab.text.edit_undo()
        except Exception: pass

    def edit_redo(self):
        tab = self.current_editor_tab();
        if not tab: return
        try: tab.text.edit_redo()
        except Exception: pass

    def _cur_text_event(self, name):
        tab = self.current_editor_tab()
        if not tab: return
        tab.text.event_generate(name)

    def select_all(self):
        tab = self.current_editor_tab()
        if not tab: return
        try:
            tab.text.tag_add("sel", "1.0", "end-1c")
            tab.text.mark_set("insert", "1.0")
            tab.text.see("insert")
        except tk.TclError:
            pass

    def open_find_replace(self):
        tab = self.current_editor_tab()
        if not tab: return
        FindReplaceDialog(self, tab.text)

    # --- Перенос слов и шрифт ---
    def _toggle_wrap_global(self):
        for f, tab in self.tabs.items():
            tab.wrap = self.wrap_var.get()
            tab.text.config(wrap="word" if tab.wrap else "none")
        self._update_statusbar_for_current()

    def toggle_wrap(self):
        tab = self.current_editor_tab()
        if not tab: return
        tab.wrap = not tab.wrap
        tab.text.config(wrap="word" if tab.wrap else "none")
        self.wrap_var.set(tab.wrap)
        self._update_statusbar_for_current()

    def choose_font(self):
        tab = self.current_editor_tab()
        if not tab: return
        FontDialog(self, tab.font, self._apply_font_to_current)

    def _apply_font_to_current(self, new_font):
        tab = self.current_editor_tab()
        if not tab: return
        tab.font = new_font; tab.text.configure(font=new_font)

    # --- Тема ---
    def apply_theme(self, theme_name):
        if theme_name not in THEMES:
            messagebox.showwarning("Тема не найдена", f"Тема '{theme_name}' не зарегистрирована.")
            return
        self.current_theme = theme_name
        theme = THEMES[theme_name]
        try:
            self.style.configure("TFrame", background=theme["background"])
            self.style.configure("TLabel", background=theme["background"], foreground=theme["foreground"])
            self.style.configure("TNotebook", background=theme["background"])
            self.style.configure("TNotebook.Tab", background=theme.get("tab_bg", theme["background"]), foreground=theme["foreground"])
            self.style.map("TNotebook.Tab",
                           background=[("selected", theme.get("tab_bg", theme["background"]))],
                           foreground=[("selected", theme["foreground"])])
        except Exception:
            pass
        for frame, tab in self.tabs.items():
            try:
                frame.configure(style="TFrame")
            except Exception:
                try:
                    frame.configure(background=theme["background"])
                except Exception:
                    pass
            self._apply_theme_to_text(tab)
        try:
            self.statusbar.config(background=theme.get("linenumber_bg", theme["background"]), foreground=theme["foreground"])
        except Exception:
            pass
        try:
            self.configure(background=theme["background"])
        except Exception:
            pass

    def _apply_theme_to_text(self, tab: EditorTab):
        theme = THEMES[self.current_theme]
        t = tab.text
        # Явно ставим состояние normal перед применением цветов, чтобы не было "недоступного" текста
        try:
            t.config(state="normal")
        except Exception:
            pass
        t.config(background=theme["background"],
                 foreground=theme["foreground"],
                 insertbackground=theme["cursor"],
                 selectbackground=theme["selectbackground"],
                 selectforeground=theme.get("selectforeground", theme["foreground"]))
        tags = theme.get("tag", {})
        for tagname, attrs in tags.items():
            t.tag_configure(tagname, **attrs)
        try:
            t.tag_configure("sel", background=theme["selectbackground"], foreground=theme.get("selectforeground", theme["foreground"]))
        except Exception:
            pass

    # --- Подсветка Python ---
    def _on_key_release(self, text_widget):
        frame = self._frame_for_text(text_widget)
        if not frame: return
        tab = self.tabs.get(frame)
        if not tab: return
        if tab._highlight_after_id:
            try: text_widget.after_cancel(tab._highlight_after_id)
            except Exception: pass
        tab._highlight_after_id = text_widget.after(180, lambda: self._apply_syntax_highlight(tab))
        self._update_statusbar(text_widget)

    def _apply_syntax_highlight(self, tab: EditorTab):
        text = tab.text
        if tab.syntax != "python":
            for tag in ("keyword", "string", "comment", "number", "builtin"):
                text.tag_remove(tag, "1.0", tk.END)
            return
        content = text.get("1.0", tk.END)
        for tag in ("keyword", "string", "comment", "number", "builtin"):
            text.tag_remove(tag, "1.0", tk.END)
        for m in RE_COMMENT.finditer(content):
            text.tag_add("comment", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in RE_STRING.finditer(content):
            text.tag_add("string", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in RE_NUMBER.finditer(content):
            text.tag_add("number", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in RE_WORD.finditer(content):
            word = m.group(0)
            start = f"1.0+{m.start()}c"; end = f"1.0+{m.end()}c"
            if word in PY_KEYWORDS:
                text.tag_add("keyword", start, end)
            elif word in PY_BUILTINS:
                text.tag_add("builtin", start, end)

    # --- Изменение текста / статусбар ---
    def _on_text_modified(self, text_widget):
        try:
            if text_widget.edit_modified():
                frame = self._frame_for_text(text_widget)
                if not frame: return
                tab = self.tabs.get(frame)
                if tab: tab._text_changed = True
                self._update_title(); self._update_statusbar(text_widget)
                text_widget.edit_modified(False)
        except Exception:
            pass

    def _frame_for_text(self, text_widget):
        parent = text_widget.master
        while parent and parent not in self.tabs:
            parent = parent.master
        return parent if parent in self.tabs else None

    def _on_tab_changed(self):
        # при переключении вкладки явно ставим фокус в текст, делаем state normal
        frame = self._current_frame()
        tab = self.tabs.get(frame) if frame else None
        if tab:
            try:
                tab.text.config(state="normal")
                tab.text.focus_set()
            except Exception:
                pass
        self._update_title(); self._update_statusbar_for_current()

    def _update_title(self):
        tab = self.current_editor_tab()
        name = os.path.basename(tab.filepath) if tab and tab.filepath else "Безымянный"
        dirty = "*" if tab and tab._text_changed else ""
        self.title(f"{name}{dirty} — {APP_NAME}")

    def _update_statusbar(self, text_widget):
        try:
            idx = text_widget.index(tk.INSERT)
            ln, col = idx.split("."); col = int(col) + 1; ln = int(ln)
            tab = self.current_editor_tab()
            filename = os.path.basename(tab.filepath) if tab and tab.filepath else "Безымянный"
            dirty = "*" if tab and tab._text_changed else ""
            wrap_state = "WRAP" if tab and tab.wrap else "NOWRAP"
            self.statusbar.config(text=f"{filename}{dirty} | Ln {ln}, Col {col} | {wrap_state}")
        except Exception:
            pass

    def _update_statusbar_for_current(self):
        tab = self.current_editor_tab()
        if not tab:
            self.statusbar.config(text=""); return
        self._update_statusbar(tab.text)

    def _about(self):
        messagebox.showinfo("О программе", f"{APP_NAME}\nРедактор с поддержкой .dl библиотек, Создатель-Никита Попов 9Е.")

    # --- Сочетания клавиш ---
    def _bind_shortcuts(self):
        self.bind_all("<Control-n>", lambda e: self.new_tab())
        self.bind_all("<Control-o>", lambda e: self.open_file())
        self.bind_all("<Control-s>", lambda e: self.save_file())
        self.bind_all("<Control-S>", lambda e: self.save_file_as())
        self.bind_all("<Control-w>", lambda e: self.close_current_tab())
        self.bind_all("<Control-z>", lambda e: self.edit_undo())
        self.bind_all("<Control-y>", lambda e: self.edit_redo())
        self.bind_all("<Control-f>", lambda e: self.open_find_replace())
        self.bind_all("<Control-a>", lambda e: self.select_all() or "break")
        self.bind_all("<Control-KeyPress>", self._control_keypress)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _control_keypress(self, event):
        try:
            ks = (event.keysym or "").lower()
            if ks in ("a", "ф"):
                self.select_all(); return "break"
        except Exception:
            pass
        return None

    def on_close(self):
        for frame, tab in list(self.tabs.items()):
            if tab._text_changed:
                self.notebook.select(frame)
                ans = messagebox.askyesnocancel("Несохранённые изменения", f"Вкладка '{os.path.basename(tab.filepath) if tab.filepath else 'Безымянный'}' содержит несохранённые изменения. Сохранить?")
                if ans is None:
                    return
                if ans:
                    ok = self.save_file()
                    if not ok:
                        return
        self.destroy()


# -------------------------
# Find/Replace, FontDialog (минимальные)
# -------------------------
class FindReplaceDialog(tk.Toplevel):
    def __init__(self, master, text_widget):
        super().__init__(master)
        self.title("Найти / Заменить")
        self.transient(master)
        self.resizable(False, False)
        self.text = text_widget
        self._last_search = None
        self._build_ui()
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Найти:").grid(column=0, row=0, sticky=tk.W)
        self.find_entry = ttk.Entry(frm, width=30); self.find_entry.grid(column=1, row=0, columnspan=2, sticky=tk.W, pady=2)
        ttk.Label(frm, text="Заменить:").grid(column=0, row=1, sticky=tk.W)
        self.replace_entry = ttk.Entry(frm, width=30); self.replace_entry.grid(column=1, row=1, columnspan=2, sticky=tk.W, pady=2)
        self.match_case = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Чувствительно к регистру", variable=self.match_case).grid(column=0, row=2, sticky=tk.W, pady=2)
        btn_find = ttk.Button(frm, text="Найти далее", command=self.find_next)
        btn_replace = ttk.Button(frm, text="Заменить", command=self.replace_one)
        btn_replace_all = ttk.Button(frm, text="Заменить всё", command=self.replace_all)
        btn_close = ttk.Button(frm, text="Закрыть", command=self.close)
        btn_find.grid(column=0, row=3, padx=3, pady=6); btn_replace.grid(column=1, row=3, padx=3, pady=6)
        btn_replace_all.grid(column=2, row=3, padx=3, pady=6); btn_close.grid(column=3, row=3, padx=3, pady=6)
        self.bind("<Return>", lambda e: self.find_next()); self.find_entry.focus_set()

    def find_next(self):
        needle = self.find_entry.get(); 
        if not needle: return
        start = self.text.index(tk.INSERT)
        opts = {} 
        if not self.match_case.get(): opts["nocase"] = 1
        pos = self.text.search(needle, start, tk.END, **opts)
        if not pos:
            pos = self.text.search(needle, "1.0", start, **opts)
        if pos:
            end = f"{pos}+{len(needle)}c"
            self.text.tag_remove("find_highlight", "1.0", tk.END)
            self.text.tag_add("find_highlight", pos, end)
            self.text.tag_configure("find_highlight", background="yellow")
            self.text.mark_set(tk.INSERT, end); self.text.see(pos)
            self._last_search = (needle, pos)
        else:
            messagebox.showinfo("Найти", "Не найдено")

    def replace_one(self):
        if not self._last_search:
            self.find_next(); return
        needle, pos = self._last_search; current = self.find_entry.get()
        if needle != current:
            self.find_next(); return
        start = pos; end = f"{start}+{len(needle)}c"; replacement = self.replace_entry.get()
        self.text.delete(start, end); self.text.insert(start, replacement)
        self.text.tag_remove("find_highlight", "1.0", tk.END)
        new_pos = f"{start}+{len(replacement)}c"; self.text.mark_set(tk.INSERT, new_pos)
        self._last_search = None

    def replace_all(self):
        needle = self.find_entry.get(); 
        if not needle: return
        replacement = self.replace_entry.get(); count = 0; idx = "1.0"; opts = {}
        if not self.match_case.get(): opts["nocase"] = 1
        while True:
            pos = self.text.search(needle, idx, tk.END, **opts)
            if not pos: break
            end = f"{pos}+{len(needle)}c"; self.text.delete(pos, end); self.text.insert(pos, replacement)
            idx = f"{pos}+{len(replacement)}c"; count += 1
        messagebox.showinfo("Заменить всё", f"Заменено {count} вхождений."); self.text.tag_remove("find_highlight", "1.0", tk.END)

    def close(self):
        self.text.tag_remove("find_highlight", "1.0", tk.END); self.grab_release(); self.destroy()


class FontDialog(tk.Toplevel):
    def __init__(self, master, current_font, callback):
        super().__init__(master)
        self.title("Выбрать шрифт")
        self.transient(master); self.resizable(False, False)
        self.callback = callback; self.current_font = current_font
        self.result_font = font.Font(font=current_font)
        self._build_ui(); self.grab_set(); self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10); frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Семейство:").grid(row=0, column=0, sticky=tk.W)
        families = sorted(font.families()); self.family_var = tk.StringVar(value=self.result_font.actual().get("family"))
        fam_combo = ttk.Combobox(frm, values=families, textvariable=self.family_var, width=30); fam_combo.grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(frm, text="Размер:").grid(row=1, column=0, sticky=tk.W); size_var = tk.IntVar(value=self.result_font.actual().get("size"))
        self.size_spin = ttk.Spinbox(frm, from_=6, to=72, textvariable=size_var, width=5); self.size_spin.grid(row=1, column=1, sticky=tk.W, pady=2)
        self.bold_var = tk.BooleanVar(value=bool(self.result_font.actual().get("weight") == "bold"))
        self.italic_var = tk.BooleanVar(value=bool(self.result_font.actual().get("slant") == "italic"))
        ttk.Checkbutton(frm, text="Полужирный", variable=self.bold_var).grid(row=2, column=0, sticky=tk.W)
        ttk.Checkbutton(frm, text="Курсив", variable=self.italic_var).grid(row=2, column=1, sticky=tk.W)
        btn_apply = ttk.Button(frm, text="Применить", command=self.apply); btn_ok = ttk.Button(frm, text="OK", command=self.ok); btn_cancel = ttk.Button(frm, text="Отмена", command=self.close)
        btn_apply.grid(row=3, column=0, pady=8); btn_ok.grid(row=3, column=1, pady=8); btn_cancel.grid(row=3, column=2, pady=8)

    def apply(self):
        fam = self.family_var.get()
        try: size = int(self.size_spin.get())
        except Exception: size = self.result_font.actual().get("size")
        weight = "bold" if self.bold_var.get() else "normal"; slant = "italic" if self.italic_var.get() else "roman"
        newf = font.Font(family=fam, size=size, weight=weight, slant=slant)
        self.result_font = newf; self.callback(newf)

    def ok(self): self.apply(); self.close()
    def close(self): self.grab_release(); self.destroy()


# -------------------------
# Запуск приложения
# -------------------------
def main():
    app = TextEditor()
    app.mainloop()

if __name__ == "__main__":
    main()