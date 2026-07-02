import sys
import os
import json
import random
import winreg
import time
from datetime import datetime, time as dt_time

# 【核心修复1】获取打包后的 exe 所在真实目录（用于持久化保存 json 存档）
if hasattr(sys, 'frozen'):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

# 智能识别系统路径，确保解压后的图片和动图能被完美加载
if hasattr(sys, '_MEIPASS'):
    os.chdir(sys._MEIPASS)
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 存档文件绝对路径化，确保牢牢扎根在 exe 旁边，不受临时目录清空的影响
DATA_FILE = os.path.join(EXE_DIR, "pet_data.json")

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QMenu, qApp, 
                             QSystemTrayIcon, QAction, QDialog, QVBoxLayout, 
                             QHBoxLayout, QSlider, QPushButton, QListWidget, 
                             QListWidgetItem, QDesktopWidget, QLineEdit, QCheckBox, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt5.QtGui import QPixmap, QIcon, QMovie

try:
    from pynput import mouse, keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

# 引入 Windows 底层 API
try:
    import ctypes
    import ctypes.wintypes
    HAS_CTYPES = True
    
    # 定义获取系统空闲时间的结构体（性能优化核心）
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
except ImportError:
    HAS_CTYPES = False

class Communicate(QObject):
    trigger_action = pyqtSignal(str) 

# --- 通用可拖拽弹窗基类 ---
class DraggableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drag_position = None
        self.is_dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self.is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            self.is_dragging = True
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            event.accept()

# --- 自定义待办条目组件 ---
class TodoItemWidget(QWidget):
    def __init__(self, text, parent_list_widget, dialog_parent):
        super().__init__()
        self.parent_list_widget = parent_list_widget
        self.dialog_parent = dialog_parent
        
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 2, 5, 2)
        
        self.checkbox = QCheckBox(text)
        self.checkbox.setStyleSheet("""
            QCheckBox { font-family: 'Microsoft YaHei'; font-size: 14px; font-weight: bold; color: #FFA500; }
            QCheckBox::indicator { width: 20px; height: 20px; }
            QCheckBox::indicator:unchecked { image: url(assets/checkbox_empty.png); }
            QCheckBox::indicator:checked { image: url(assets/checkbox_checked.png); }
        """)
        self.checkbox.stateChanged.connect(self.on_state_changed)
        
        self.del_btn = QPushButton()
        self.del_btn.setObjectName("deleteBtn")
        self.del_btn.setFixedSize(17, 22)
        self.del_btn.setStyleSheet("""
            QPushButton#deleteBtn { border-image: url(assets/delete_icon.png); background: transparent; border: none; }
        """)
        self.del_btn.clicked.connect(self.delete_item)
        
        layout.addWidget(self.checkbox)
        layout.addStretch()
        layout.addWidget(self.del_btn)
        self.setLayout(layout)
        
    def on_state_changed(self, state):
        self.dialog_parent.sync_to_pet_data()
        if state == Qt.Checked:
            self.dialog_parent.parent_pet.trigger_like("飒飒飒")
            
    def delete_item(self):
        for i in range(self.parent_list_widget.count()):
            item = self.parent_list_widget.item(i)
            if self.parent_list_widget.itemWidget(item) == self:
                self.parent_list_widget.takeItem(i)
                break
        self.dialog_parent.sync_to_pet_data()

# --- 视效控制面板 ---
class SettingsDialog(DraggableDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_pet = parent
        self.setFixedSize(342, 250)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("bgFrame")
        self.bg_frame.setStyleSheet("""
            QFrame#bgFrame { border-image: url(assets/panel_bg.png); }
            QLabel { font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 16px; color: #FFA500; background: transparent; }
            QPushButton#closeBtn { border-image: url(assets/close_btn.png); background: transparent; border: none; }
            QSlider::groove:horizontal { border-image: url(assets/slider_track.png); height: 8px; }
            QSlider::handle:horizontal { image: url(assets/slider_handle.png); width: 18px; height: 18px; margin: -5px 0; }
        """)
        main_layout.addWidget(self.bg_frame)

        frame_layout = QVBoxLayout(self.bg_frame)
        frame_layout.setContentsMargins(40, 30, 40, 30)
        
        top_layout = QHBoxLayout()
        self.title_label = QLabel("视效控制")
        self.title_label.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 18px; font-weight: bold; color: #FFA500; background: transparent;")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(20, 22)
        self.close_btn.clicked.connect(self.hide)
        top_layout.addWidget(self.close_btn)
        frame_layout.addLayout(top_layout)
        
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("透明度:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(self.parent_pet.data.get("opacity", 1.0) * 100))
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("大  小:"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(100, 400)
        self.size_slider.setValue(self.parent_pet.data.get("scale", 200))
        self.size_slider.valueChanged.connect(self.change_size)
        size_layout.addWidget(self.size_slider)

        frame_layout.addLayout(opacity_layout)
        frame_layout.addLayout(size_layout)

    def change_opacity(self, value):
        opacity = value / 100.0
        self.parent_pet.setWindowOpacity(opacity)
        self.parent_pet.data["opacity"] = opacity
        self.parent_pet.save_data()

    def change_size(self, value):
        self.parent_pet.data["scale"] = value
        self.parent_pet.preload_all_images()
        self.parent_pet.update_size()
        self.parent_pet.save_data()

# --- 待办清单面板 ---
class TodoListDialog(DraggableDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_pet = parent
        self.setFixedSize(342, 250)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("bgFrame")
        self.bg_frame.setStyleSheet("""
            QFrame#bgFrame { border-image: url(assets/panel_bg.png); }
            QListWidget { background: transparent; border: none; }
            QPushButton#closeBtn { border-image: url(assets/close_btn.png); background: transparent; border: none; }
            QLineEdit { border-image: url(assets/input_bg.png); background: transparent; padding: 2px 8px; font-family: 'Microsoft YaHei'; font-weight: bold; color: #FFA500; border: none; }
            QPushButton#actionBtn { border-image: url(assets/btn_normal.png); background: transparent; font-family: 'Microsoft YaHei'; font-weight: bold; color: #FFA500; border: none; }
            QPushButton#actionBtn:pressed { border-image: url(assets/btn_pressed.png); }
        """)
        main_layout.addWidget(self.bg_frame)

        frame_layout = QVBoxLayout(self.bg_frame)
        frame_layout.setContentsMargins(40, 30, 40, 30)

        top_layout = QHBoxLayout()
        self.title_label = QLabel("待办清单")
        self.title_label.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 18px; font-weight: bold; color: #FFA500; background: transparent;")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(20, 22)
        self.close_btn.clicked.connect(self.hide)
        top_layout.addWidget(self.close_btn)
        frame_layout.addLayout(top_layout)

        self.list_widget = QListWidget()
        frame_layout.addWidget(self.list_widget)
        
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setFixedHeight(28)
        self.input_field.setPlaceholderText("新任务...")
        
        self.add_btn = QPushButton("添加")
        self.add_btn.setObjectName("actionBtn")
        self.add_btn.setFixedSize(60, 30)
        self.add_btn.clicked.connect(self.add_task)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.add_btn)
        frame_layout.addLayout(input_layout)
        
        self.load_todos()

    def load_todos(self):
        todos = self.parent_pet.data.get("todos", [])
        for task in todos:
            self.add_task_item(task)

    def add_task_item(self, text):
        item = QListWidgetItem(self.list_widget)
        widget = TodoItemWidget(text, self.list_widget, self)
        item.setSizeHint(widget.sizeHint())
        self.list_widget.setItemWidget(item, widget)

    def add_task(self):
        text = self.input_field.text().strip()
        if text:
            self.add_task_item(text)
            self.input_field.clear()
            self.sync_to_pet_data()

    def sync_to_pet_data(self):
        todos = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget and not widget.checkbox.isChecked():
                todos.append(widget.checkbox.text())
        self.parent_pet.data["todos"] = todos
        self.parent_pet.save_data()

# --- 专注计时面板 ---
class FocusTimerDialog(DraggableDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_pet = parent
        self.setFixedSize(342, 250)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.remaining_seconds = 25 * 60
        self.is_running = False
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_frame = QFrame(self)
        self.bg_frame.setObjectName("bgFrame")
        self.bg_frame.setStyleSheet("""
            QFrame#bgFrame { border-image: url(assets/panel_bg.png); }
            QLineEdit#timeInput { font-family: 'Microsoft YaHei'; font-size: 38px; font-weight: bold; color: #FFA500; background: transparent; border: none; }
            QPushButton#closeBtn { border-image: url(assets/close_btn.png); background: transparent; border: none; }
            QPushButton#playBtn { border-image: url(assets/timer_play.png); background: transparent; border: none; }
            QPushButton#pauseBtn { border-image: url(assets/timer_pause.png); background: transparent; border: none; }
            QPushButton#stopBtn { border-image: url(assets/timer_stop.png); background: transparent; border: none; }
        """)
        main_layout.addWidget(self.bg_frame)

        frame_layout = QVBoxLayout(self.bg_frame)
        frame_layout.setContentsMargins(40, 35, 40, 35)

        top_layout = QHBoxLayout()
        self.title_label = QLabel("专注计时")
        self.title_label.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 18px; font-weight: bold; color: #FFA500; background: transparent;")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(20, 22)
        self.close_btn.clicked.connect(self.hide)
        top_layout.addWidget(self.close_btn)
        frame_layout.addLayout(top_layout)

        self.time_input = QLineEdit("25:00")
        self.time_input.setObjectName("timeInput")
        self.time_input.setAlignment(Qt.AlignCenter)
        frame_layout.addWidget(self.time_input)

        frame_layout.addSpacing(10)

        ctrl_layout = QHBoxLayout()
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("playBtn")
        self.play_btn.setFixedSize(32, 33)
        self.play_btn.clicked.connect(self.start_timer)
        
        self.pause_btn = QPushButton()
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.setFixedSize(32, 33)
        self.pause_btn.clicked.connect(self.pause_timer)
        self.pause_btn.hide()
        
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setFixedSize(32, 33)
        self.stop_btn.clicked.connect(self.stop_timer)
        
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.play_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addSpacing(15)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addStretch()
        frame_layout.addLayout(ctrl_layout)

    def parse_time(self):
        text = self.time_input.text().strip()
        parts = text.split(':')
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:
                return int(parts[0]) * 60 
        except ValueError:
            pass
        return 25 * 60

    def format_time(self, seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        else:
            return f"{m:02d}:{s:02d}"

    def start_timer(self):
        if not self.is_running:
            self.remaining_seconds = self.parse_time()
            self.time_input.setText(self.format_time(self.remaining_seconds))
            self.time_input.setReadOnly(True)
            self.timer.start(1000)
            self.is_running = True
            self.play_btn.hide()
            self.pause_btn.show()

    def pause_timer(self):
        if self.is_running:
            self.timer.stop()
            self.is_running = False
            self.time_input.setReadOnly(False)
            self.pause_btn.hide()
            self.play_btn.show()

    def stop_timer(self):
        self.timer.stop()
        self.is_running = False
        self.time_input.setReadOnly(False)
        self.remaining_seconds = 25 * 60
        self.time_input.setText("25:00")
        self.pause_btn.hide()
        self.play_btn.show()

    def update_timer(self):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.time_input.setText(self.format_time(self.remaining_seconds))
        else:
            self.stop_timer()
            self.parent_pet.show_dialogue("专注时间到了！")

# --- 桌宠主窗体 ---
class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        self.drag_position = None
        self.is_dragging = False
        self.current_state = "stand"
        
        self.load_data()
        
        self.raw_clicks = self.data.get("click_count", 0)
        self.last_milestone = self.raw_clicks // 100
        self.last_input_time = time.time()
        self.last_blink_time = time.time()
        
        self.pixmap_cache = {}
        self.movie_cache = {}
        self.current_movie = None
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(self.data.get("opacity", 1.0))

        self.image_label = QLabel(self)
        self.bubble_label = QLabel(self)
        self.bubble_label.setWordWrap(True) 
        
        self.counter_label = QLabel(self)
        self.counter_label.setAlignment(Qt.AlignCenter)
        self.bubble_label.setAlignment(Qt.AlignCenter)
        self.counter_label.setText(f"{self.raw_clicks:08d}")

        self.dialogues = [
            "那就全对", 
            "那就错了", 
            "张呈，我爱你", 
            "张先生，\n小心鳄鱼", 
            "我六岁那年\n你为什么不来", 
            "就由我雷公公顶上", 
            "马上将老婆孩子\n送至国外", 
            "等我回来，\n我就娶你", 
            "可是妈妈——\n我爱吃周黑鸭", 
            "你以为你真的能\n走出这家孤儿院吗", 
            "SUV才是大汽车", 
            "雷龙哪有我\n雷淞抓得好啊", 
            "会走进监狱", 
            "不是张呈，\n你家着急用钱呢", 
            "我觉得，也不能\n什么事儿都怪老天爷吧", 
            "那也是一条好狗", 
            "匍匐准备", 
            "小张小张\n来三楼一趟"
        ]

        self.todo_dialog = None
        self.timer_dialog = None
        self.settings_dialog = None

        self.dialogue_timer = QTimer(self)
        self.dialogue_timer.setSingleShot(True)
        self.dialogue_timer.timeout.connect(self.bubble_label.hide)

        self.state_timer = QTimer(self)
        self.state_timer.setSingleShot(True)
        self.state_timer.timeout.connect(self.check_sit_or_stand)

        self.preload_all_images()
        self.update_size()
        self.init_tray()
        
        self.c = Communicate()
        self.c.trigger_action.connect(self.handle_input_action) 
        
        self.init_timers()
        if HAS_PYNPUT:
            self.start_global_hooks()
            
        self.show()
        
        QTimer.singleShot(500, lambda: self.show_dialogue("天王老子来了"))

    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            
            today_str = str(datetime.now().date())
            if self.data.get("last_date") != today_str:
                self.data["last_date"] = today_str
                self.data["click_count"] = 0
        else:
            self.data = {
                "last_date": str(datetime.now().date()),
                "click_count": 0,
                "opacity": 1.0,
                "scale": 200,
                "autostart": False,
                "todos": []
            }
            self.set_autostart(False)

    def save_data(self):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def set_autostart(self, enable):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "LeiSongranPet"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                exe_path = sys.executable if hasattr(sys, 'frozen') else os.path.abspath(sys.argv[0])
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            self.data["autostart"] = enable
            self.save_data()
        except Exception:
            pass

    def preload_all_images(self):
        target_width = self.data.get("scale", 200)
        self.pixmap_cache.clear()
        self.movie_cache.clear()
        
        states = ["stand", "blink", "drag", "grab", "eat", "love", "like", "praise", "cute", "angry", "sleep", "sit", "edge"]
        for state in states:
            gif_path = f'assets/{state}.gif'
            png_path = f'assets/{state}.png'
            jpg_path = f'assets/{state}.jpg'
            
            if os.path.exists(gif_path):
                movie = QMovie(gif_path)
                self.movie_cache[state] = movie
            else:
                if os.path.exists(png_path):
                    original_pixmap = QPixmap(png_path)
                elif os.path.exists(jpg_path):
                    original_pixmap = QPixmap(jpg_path)
                else:
                    original_pixmap = QPixmap('assets/stand.png')
                    
                if not original_pixmap.isNull():
                    self.pixmap_cache[state] = original_pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)

    def update_size(self):
        target_width = self.data.get("scale", 200)
        
        if self.current_state in self.movie_cache:
            if self.current_movie:
                self.current_movie.stop()
            self.current_movie = self.movie_cache[self.current_state]
            self.current_movie.setScaledSize(QSize(target_width, target_width))
            self.image_label.setMovie(self.current_movie)
            self.current_movie.start()
            self.pet_width = target_width
            self.pet_height = target_width
        else:
            if self.current_movie:
                self.current_movie.stop()
                self.image_label.setMovie(None)
                self.current_movie = None
                
            pixmap = self.pixmap_cache.get(self.current_state)
            if not pixmap:
                pixmap = QPixmap(target_width, target_width)
                pixmap.fill(Qt.transparent)
                
            self.image_label.setPixmap(pixmap)
            self.pet_width = pixmap.width()
            self.pet_height = pixmap.height()
        
        scale_factor = target_width / 200.0
        dynamic_bubble_font = max(10, int(11 * scale_factor))
        dynamic_counter_font = max(10, int(12 * scale_factor))
        
        self.bubble_label.setStyleSheet(f"""
            background-color: transparent; 
            border-image: url(assets/speech_bubble.png);
            font-family: 'STHupo', '华文琥珀', 'Microsoft YaHei'; font-size: {dynamic_bubble_font}px; font-weight: normal; color: #FFA500;
            padding: 4px 10px 10px 10px;
        """)
        self.counter_label.setStyleSheet(f"""
            background-color: transparent;
            border-image: url(assets/counter_bg.png);
            font-family: 'Consolas'; font-size: {dynamic_counter_font}px; font-weight: bold; color: #FFA500;
            padding: 1px;
        """)
        
        bubble_width = int(self.pet_width * 0.9)
        bubble_height = int(bubble_width / 2.05)
        
        counter_width = int(self.pet_width * 0.4)
        counter_height = int(counter_width / 3.49)
        
        image_y = int(bubble_height * 0.7) 
        
        counter_x = (self.pet_width - counter_width) // 2
        counter_y = image_y + int(self.pet_height * 0.70)
        
        bubble_x = (self.pet_width - bubble_width) // 2
        bubble_y = int(bubble_height * 0.1)

        total_height = max(image_y + self.pet_height, counter_y + counter_height) + 10
        self.resize(self.pet_width, total_height)
        
        self.bubble_label.setGeometry(bubble_x, bubble_y, bubble_width, bubble_height)
        self.image_label.setGeometry(0, image_y, self.pet_width, self.pet_height)
        self.counter_label.setGeometry(counter_x, counter_y, counter_width, counter_height)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('assets/tray_icon.png')) 
        tray_menu = QMenu()
        show_action = QAction("呼唤雷淞然", self)
        show_action.triggered.connect(self.showNormal)
        tray_menu.addAction(show_action)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(qApp.quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def init_timers(self):
        self.logic_timer = QTimer(self)
        self.logic_timer.timeout.connect(self.check_status)
        self.logic_timer.start(2000)
        
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.do_blink)
        self.blink_timer.start(random.randint(6000, 9000))
        
        self.ui_sync_timer = QTimer(self)
        self.ui_sync_timer.timeout.connect(self.sync_ui_state)
        self.ui_sync_timer.start(500)

    def sync_ui_state(self):
        if self.raw_clicks != self.data["click_count"]:
            self.data["click_count"] = self.raw_clicks
            self.counter_label.setText(f"{self.raw_clicks:08d}")
            self.save_data()
            
            current_milestone = self.raw_clicks // 100
            if current_milestone > self.last_milestone and current_milestone > 0:
                self.last_milestone = current_milestone
                self.handle_input_action("love")

    def has_incomplete_tasks(self):
        if self.todo_dialog and self.todo_dialog.list_widget:
            count = self.todo_dialog.list_widget.count()
            if count == 0:
                return False
            for i in range(count):
                item = self.todo_dialog.list_widget.item(i)
                widget = self.todo_dialog.list_widget.itemWidget(item)
                if widget and not widget.checkbox.isChecked():
                    return True
            return False
        else:
            return len(self.data.get("todos", [])) > 0

    def get_idle_time(self):
        if HAS_CTYPES:
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return millis / 1000.0
        return time.time() - self.last_input_time

    def check_status(self):
        today_str = str(datetime.now().date())
        if self.data.get("last_date") != today_str:
            self.data["last_date"] = today_str
            self.raw_clicks = 0
            self.data["click_count"] = 0
            self.last_milestone = 0
            self.counter_label.setText(f"{self.raw_clicks:08d}")
            self.save_data()

        if self.is_dragging:
            return
            
        now = datetime.now().time()
        is_eating = (dt_time(11, 30) <= now <= dt_time(12, 30)) or (dt_time(18, 30) <= now <= dt_time(19, 30))
        idle_time = self.get_idle_time()

        new_state = self.current_state

        if idle_time > 120 and self.current_state not in ["drag", "grab"]:
            new_state = "sleep"
        elif self.current_state not in ["blink", "love", "like", "praise", "cute", "angry", "drag", "grab", "sit", "sleep"]:
            if is_eating:
                new_state = "eat" 
            else:
                new_state = "stand"
        elif self.current_state == "sleep" and idle_time < 1:
            self.c.trigger_action.emit("wakeup")

        if self.current_state == "sit" and new_state == "sit":
            if not self.snap_to_window(apply_move=False):
                new_state = "stand"

        if new_state != self.current_state:
            self.change_state(new_state)

    def change_state(self, state_name):
        self.current_state = state_name
        
        if self.current_state in ["drag", "grab", "sit"]:
            self.counter_label.hide()
        else:
            self.counter_label.show()
            
        self.update_size()

    def do_blink(self):
        if self.current_state == "stand":
            self.change_state("blink") 
            QTimer.singleShot(150, lambda: self.change_state("stand") if self.current_state == "blink" else None)
        self.blink_timer.start(random.randint(6000, 9000))
        
    def handle_input_action(self, action):
        if action == "wakeup":
            if self.current_state == "sleep":
                self.change_state("stand")
        elif action == "blink":
            if self.current_state == "stand":
                self.change_state("blink")
                QTimer.singleShot(150, lambda: self.change_state("stand") if self.current_state == "blink" else None)
        elif action == "love":
            self.change_state("love")
            self.show_dialogue("你真棒")
            self.state_timer.stop()
            self.state_timer.start(5500)

    def trigger_praise(self, custom_text="张呈真棒！"):
        self.change_state("praise") 
        self.show_dialogue(custom_text)
        self.state_timer.stop()
        self.state_timer.start(5500)

    def trigger_like(self, custom_text="飒飒飒"):
        self.change_state("like") 
        self.show_dialogue(custom_text)
        self.state_timer.stop()
        self.state_timer.start(5500)

    def start_global_hooks(self):
        def on_activity():
            self.last_input_time = time.time()
            if self.current_state == "sleep":
                self.c.trigger_action.emit("wakeup")

        def on_click(x, y, button, pressed):
            if pressed:
                on_activity()
                self.raw_clicks += 1
                t = time.time()
                if t - self.last_blink_time > 0.4:
                    self.last_blink_time = t
                    self.c.trigger_action.emit("blink")

        def on_press(key):
            on_activity()
            self.raw_clicks += 1
            t = time.time()
            if t - self.last_blink_time > 0.4:
                self.last_blink_time = t
                self.c.trigger_action.emit("blink")

        self.mouse_listener = mouse.Listener(on_click=on_click)
        self.keyboard_listener = keyboard.Listener(on_press=on_press)
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self.is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            if not self.is_dragging:
                self.is_dragging = True
                if not (self.timer_dialog and self.timer_dialog.is_running):
                    self.change_state("grab") 
                    self.show_dialogue("别动我发型啊")
            event.accept()

    def snap_to_window(self, apply_move=True):
        if not HAS_CTYPES:
            return False
            
        try:
            pet_rect = self.geometry()
            offset = int(self.pet_height * 0.05) 
            current_offset = offset if self.current_state == "sit" else 0
            pet_bottom = pet_rect.top() + self.pet_height - current_offset
            pet_center_x = pet_rect.left() + self.pet_width // 2
            
            user32 = ctypes.windll.user32
            EnumWindows = user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            
            IsWindowVisible = user32.IsWindowVisible
            IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
            
            IsIconic = user32.IsIconic
            IsIconic.argtypes = [ctypes.wintypes.HWND]
            
            GetWindowRect = user32.GetWindowRect
            GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
            
            my_hwnd = int(self.winId())
            snap_margin = 40 
            
            self.found_snap = False
            self.target_y = None
            
            def foreach_window(hwnd, lParam):
                try:
                    if hwnd == my_hwnd or not IsWindowVisible(hwnd) or IsIconic(hwnd):
                        return True
                        
                    rect = ctypes.wintypes.RECT()
                    GetWindowRect(hwnd, ctypes.byref(rect))
                    
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    
                    if width > 100 and height > 100:
                        if rect.left <= pet_center_x <= rect.right:
                            if abs(pet_bottom - rect.top) <= snap_margin:
                                self.found_snap = True
                                self.target_y = rect.top
                                return False
                except Exception:
                    pass
                return True
                
            win_enum_cb = EnumWindowsProc(foreach_window)
            EnumWindows(win_enum_cb, 0)
            
            if self.found_snap and self.target_y is not None:
                if apply_move:
                    self.move(pet_rect.left(), self.target_y - self.pet_height + offset)
                return True
                
        except Exception:
            pass
            
        return False

    def check_sit_or_stand(self):
        if self.snap_to_window(apply_move=True):
            self.change_state("sit")
        else:
            self.change_state("stand")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.timer_dialog and self.timer_dialog.is_running:
                self.change_state("angry")
                self.show_dialogue("干活要对得起三种人\n专心干活")
                self.state_timer.stop()
                self.state_timer.start(5500)
            else:
                if not self.is_dragging:
                    if self.has_incomplete_tasks():
                        self.change_state("angry")
                        self.show_dialogue("干活要对得起三种人\n专心干活")
                        self.state_timer.stop()
                        self.state_timer.start(5500)
                    else:
                        self.change_state("cute")
                        self.show_dialogue()
                        self.state_timer.stop()
                        self.state_timer.start(5500)
                else:
                    self.check_sit_or_stand()
            self.is_dragging = False
            event.accept()

    def show_dialogue(self, custom_text=None):
        text = custom_text if custom_text else random.choice(self.dialogues)
        self.bubble_label.setText(text)
        self.bubble_label.show()
        
        self.dialogue_timer.stop()
        self.dialogue_timer.start(5500)

    def show_dialog_left(self, dialog):
        dialog.show()
        pet_geo = self.geometry()
        dialog.move(pet_geo.left() - dialog.width() - 15, pet_geo.top())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        
        menu.setStyleSheet("""
            QMenu {
                border-image: url(assets/menu_bg.png);
                background-color: transparent;
                border: none;
                font-family: 'Microsoft YaHei'; font-size: 16px; font-weight: bold;
                padding: 25px 30px; 
            }
            QMenu::item { 
                padding: 12px 22px; 
                margin: 2px 0px; 
                color: #FFA500; 
                background: transparent; 
            }
            QMenu::item:selected { 
                border-image: url(assets/menu_hover.png); 
                border-radius: 4px; 
                color: white; 
            }
        """)
        
        todo_action = menu.addAction("待办清单")
        timer_action = menu.addAction("专注计时")
        settings_action = menu.addAction("视效控制")
        
        autostart_text = "开机自启 (已开启)" if self.data.get("autostart") else "开机自启 (未开启)"
        autostart_action = menu.addAction(autostart_text)
        
        hide_action = menu.addAction("隐藏雷淞然")
        quit_action = menu.addAction("退出程序")
        
        menu_width = menu.sizeHint().width()
        pet_geo = self.geometry()
        target_pos = pet_geo.topLeft()
        target_pos.setX(target_pos.x() - menu_width - 10)
        
        action = menu.exec_(target_pos)
        
        if action == todo_action:
            if not self.todo_dialog:
                self.todo_dialog = TodoListDialog(self)
            self.show_dialog_left(self.todo_dialog)
        elif action == timer_action:
            if not self.timer_dialog:
                self.timer_dialog = FocusTimerDialog(self)
            self.show_dialog_left(self.timer_dialog)
        elif action == settings_action:
            if not self.settings_dialog:
                self.settings_dialog = SettingsDialog(self)
            self.show_dialog_left(self.settings_dialog)
        elif action == autostart_action:
            current_state = self.data.get("autostart", False)
            self.set_autostart(not current_state)
        elif action == hide_action:
            self.hide()
        elif action == quit_action:
            if self.todo_dialog:
                self.todo_dialog.sync_to_pet_data()
            self.save_data()
            qApp.quit()

if __name__ == '__main__':
    # 【核心修复：强制统一坐标系，解决放大和坐空气问题】
    if HAS_CTYPES:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    qApp.setQuitOnLastWindowClosed(False)
    
    pet = DesktopPet()
    sys.exit(app.exec_())