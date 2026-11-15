import hashlib
import hmac
import os
import random
import sqlite3
import sys
from pathlib import Path

import requests
from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSlider, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
)
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

# Paste your YouTube Data API v3 key between the quotation marks.
# You can create one in Google Cloud Console after enabling YouTube Data API v3.
YOUTUBE_API_KEY = "PASTE_YOUR_YOUTUBE_API_KEY_HERE"
DB_NAME = "trackboxd.db"
PASSWORD_ITERATIONS = 260_000


def connect_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash BLOB NOT NULL,
                salt BLOB NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                search_query TEXT NOT NULL,
                media_title TEXT NOT NULL,
                video_id TEXT,
                searched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        history_columns = {row[1] for row in conn.execute("PRAGMA table_info(watch_history)").fetchall()}
        if "video_id" not in history_columns:
            conn.execute("ALTER TABLE watch_history ADD COLUMN video_id TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                media_title TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)


def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return password_hash, salt


class YouTubeSearchThread(QThread):
    results_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, query, api_key, parent=None):
        super().__init__(parent)
        self.query = query
        self.api_key = api_key

    def run(self):
        try:
            endpoint = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet", "type": "video", "maxResults": 10,
                "q": self.query, "key": self.api_key
            }
            response = requests.get(endpoint, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            results = []
            for item in payload.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                snippet = item.get("snippet", {})
                if video_id:
                    results.append({
                        "video_id": video_id,
                        "title": snippet.get("title", "Untitled video"),
                        "channel": snippet.get("channelTitle", "Unknown channel"),
                        "description": snippet.get("description", "")
                    })
            self.results_ready.emit(results)
        except requests.HTTPError as exc:
            message = "YouTube API request failed. Check your API key, quota, and API settings."
            try:
                details = exc.response.json().get("error", {}).get("message", "")
                if details:
                    message += f"\n\nDetails: {details}"
            except Exception:
                pass
            self.error_occurred.emit(message)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class TrackboxdApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_user_id = None
        self.current_username = ""
        self.search_thread = None
        self.current_video_id = None
        self.pending_query = ""
        self.music_files = []
        self.quiz_questions = []
        self.quiz_index = 0
        self.quiz_score = 0
        self.quiz_total = 10
        self.current_question = None
        self.answer_locked = False

        self.music_player = QMediaPlayer(self)
        self.music_output = QAudioOutput(self)
        self.music_player.setAudioOutput(self.music_output)
        self.music_output.setVolume(0.7)

        self.game_player = QMediaPlayer(self)
        self.game_output = QAudioOutput(self)
        self.game_player.setAudioOutput(self.game_output)
        self.game_output.setVolume(0.8)
        self.clip_timer = QTimer(self)
        self.clip_timer.setSingleShot(True)
        self.clip_timer.timeout.connect(self.stop_quiz_clip)
        self.game_player.mediaStatusChanged.connect(self.handle_quiz_media_status)
        self.waiting_for_quiz_clip = False
        self.quiz_clip_duration_ms = 3000

        self.setWindowTitle("Trackboxd | Media and Entertainment")
        self.resize(1200, 850)
        self.build_auth_pages()
        self.apply_styles()
        self.show_login()

    # ---------------- AUTHENTICATION ----------------
    def build_auth_pages(self):
        self.stack = QTabWidget()
        self.stack.tabBar().hide()
        self.setCentralWidget(self.stack)

        login_page = QWidget()
        login_outer = QVBoxLayout(login_page)
        login_outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        login_card = QFrame()
        login_card.setObjectName("AuthCard")
        login_card.setFixedWidth(430)
        login_layout = QVBoxLayout(login_card)
        login_layout.setContentsMargins(35, 35, 35, 35)
        logo = QLabel("TRACKBOXD")
        logo.setObjectName("AuthLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Your space for music, videos, and games")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("Muted")
        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("Username")
        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Password")
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        login_btn = QPushButton("Log In")
        login_btn.setObjectName("Primary")
        login_btn.clicked.connect(self.handle_login)
        register_link = QPushButton("Create an account")
        register_link.setObjectName("LinkButton")
        register_link.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.login_message = QLabel("")
        self.login_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (logo, subtitle, self.login_username, self.login_password,
                       login_btn, register_link, self.login_message):
            login_layout.addWidget(widget)
        login_outer.addWidget(login_card)
        self.stack.addTab(login_page, "Login")

        register_page = QWidget()
        register_outer = QVBoxLayout(register_page)
        register_outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        register_card = QFrame()
        register_card.setObjectName("AuthCard")
        register_card.setFixedWidth(430)
        register_layout = QVBoxLayout(register_card)
        register_layout.setContentsMargins(35, 35, 35, 35)
        register_logo = QLabel("CREATE ACCOUNT")
        register_logo.setObjectName("AuthLogo")
        register_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.register_username = QLineEdit()
        self.register_username.setPlaceholderText("Username")
        self.register_password = QLineEdit()
        self.register_password.setPlaceholderText("Password (10+ characters)")
        self.register_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.register_confirm = QLineEdit()
        self.register_confirm.setPlaceholderText("Confirm password")
        self.register_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        create_btn = QPushButton("Create Account")
        create_btn.setObjectName("Primary")
        create_btn.clicked.connect(self.handle_register)
        back_btn = QPushButton("Back to login")
        back_btn.setObjectName("LinkButton")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.register_message = QLabel("")
        self.register_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (register_logo, self.register_username, self.register_password,
                       self.register_confirm, create_btn, back_btn, self.register_message):
            register_layout.addWidget(widget)
        register_outer.addWidget(register_card)
        self.stack.addTab(register_page, "Register")

    def show_login(self):
        self.stack.setCurrentIndex(0)

    def handle_register(self):
        username = self.register_username.text().strip()
        password = self.register_password.text()
        confirm = self.register_confirm.text()
        if not username or not password or not confirm:
            self.register_message.setText("Please complete all fields.")
            return
        if len(username) < 4 or not username.replace("_", "").isalnum():
            self.register_message.setText("Use at least 4 letters/numbers. Underscores are allowed.")
            return
        if len(password) < 10 or not any(c.isupper() for c in password) or \
           not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
            self.register_message.setText("Password needs 10+ characters, uppercase, lowercase, and a number.")
            return
        if password != confirm:
            self.register_message.setText("Passwords do not match.")
            return
        password_hash, salt = hash_password(password)
        try:
            with connect_db() as conn:
                conn.execute(
                    "INSERT INTO users(username, password_hash, salt) VALUES (?, ?, ?)",
                    (username, password_hash, salt)
                )
            QMessageBox.information(self, "Account created", "You can now log in.")
            self.register_username.clear()
            self.register_password.clear()
            self.register_confirm.clear()
            self.stack.setCurrentIndex(0)
        except sqlite3.IntegrityError:
            self.register_message.setText("That username is already taken.")

    def handle_login(self):
        username = self.login_username.text().strip()
        password = self.login_password.text()
        with connect_db() as conn:
            row = conn.execute(
                "SELECT id, password_hash, salt FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            self.login_message.setText("Invalid username or password.")
            return
        user_id, stored_hash, salt = row
        entered_hash, _ = hash_password(password, salt)
        if not hmac.compare_digest(entered_hash, stored_hash):
            self.login_message.setText("Invalid username or password.")
            return
        self.current_user_id = user_id
        self.current_username = username
        self.build_dashboard()
        self.stack.setCurrentIndex(2)

    # ---------------- MAIN DASHBOARD ----------------
    def build_dashboard(self):
        if self.stack.count() > 2:
            old_page = self.stack.widget(2)
            self.stack.removeTab(2)
            old_page.deleteLater()
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 16, 22, 22)
        header = QHBoxLayout()
        brand = QLabel("TRACKBOXD")
        brand.setObjectName("Brand")
        self.user_badge = QLabel(f"@{self.current_username}")
        self.user_badge.setObjectName("UserBadge")
        logout = QPushButton("Log Out")
        logout.clicked.connect(self.logout)
        header.addWidget(brand)
        header.addStretch()
        header.addWidget(self.user_badge)
        header.addWidget(logout)
        root.addLayout(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.build_youtube_tab()
        self.build_music_tab()
        self.build_game_tab()
        self.build_community_tab()
        self.stack.addTab(page, "Dashboard")
        self.load_history()
        self.load_reviews()
        self.load_quiz_songs()

    # ---------------- YOUTUBE TAB ----------------
    def build_youtube_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        search_row = QHBoxLayout()
        self.youtube_search = QLineEdit()
        self.youtube_search.setPlaceholderText("Search YouTube videos, songs, or artists...")
        self.youtube_search.returnPressed.connect(self.search_youtube)
        search_btn = QPushButton("Search YouTube")
        search_btn.setObjectName("Primary")
        search_btn.clicked.connect(self.search_youtube)
        search_row.addWidget(self.youtube_search, 1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        key_note = QLabel("YouTube search uses your YouTube Data API v3 key. Playback stays embedded below.")
        key_note.setObjectName("Muted")
        layout.addWidget(key_note)

        body = QHBoxLayout()
        self.youtube_results = QListWidget()
        self.youtube_results.setMinimumWidth(310)
        self.youtube_results.itemDoubleClicked.connect(self.play_selected_video)
        body.addWidget(self.youtube_results, 1)

        player_column = QVBoxLayout()
        self.youtube_player = QWebEngineView()
        self.youtube_player.setMinimumHeight(430)
        settings = self.youtube_player.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.youtube_player.setHtml("<html><body style='background:#080d18;color:#cbd5e1;font-family:Arial;display:grid;place-items:center;height:100vh'><h2>Search and select a video to play</h2></body></html>")
        self.youtube_title = QLabel("No video selected")
        self.youtube_title.setObjectName("SectionTitle")
        self.youtube_description = QTextEdit()
        self.youtube_description.setReadOnly(True)
        self.youtube_description.setMaximumHeight(95)
        player_column.addWidget(self.youtube_player, 1)
        player_column.addWidget(self.youtube_title)
        player_column.addWidget(self.youtube_description)
        body.addLayout(player_column, 2)
        layout.addLayout(body, 1)

        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Search", "Video", "Played at"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setMaximumHeight(150)
        layout.addWidget(QLabel("RECENTLY PLAYED"))
        layout.addWidget(self.history_table)
        self.tabs.addTab(page, "YouTube")

    def search_youtube(self):
        query = self.youtube_search.text().strip()
        if not query:
            QMessageBox.warning(self, "Search", "Enter a search term first.")
            return
        if not YOUTUBE_API_KEY or YOUTUBE_API_KEY == "PASTE_YOUR_YOUTUBE_API_KEY_HERE":
            QMessageBox.warning(
                self, "API key needed",
                "Open the Python file and replace PASTE_YOUR_YOUTUBE_API_KEY_HERE with your YouTube Data API v3 key."
            )
            return
        if self.search_thread and self.search_thread.isRunning():
            return
        self.youtube_results.clear()
        self.youtube_results.addItem("Searching YouTube...")
        self.pending_query = query
        self.search_thread = YouTubeSearchThread(query, YOUTUBE_API_KEY, self)
        self.search_thread.results_ready.connect(self.show_youtube_results)
        self.search_thread.error_occurred.connect(self.show_youtube_error)
        self.search_thread.start()

    def show_youtube_results(self, results):
        self.youtube_results.clear()
        if not results:
            self.youtube_results.addItem("No videos found.")
            return
        for video in results:
            item = QListWidgetItem(f"{video['title']}\n{video['channel']}")
            item.setData(Qt.ItemDataRole.UserRole, video)
            self.youtube_results.addItem(item)

    def show_youtube_error(self, message):
        self.youtube_results.clear()
        QMessageBox.warning(self, "YouTube Search Error", message)

    def play_selected_video(self, item):
        video = item.data(Qt.ItemDataRole.UserRole)
        if not video:
            return
        video_id = video["video_id"]
        self.current_video_id = video_id
        title = video["title"]
        embed_html = f"""<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>
        <style>html,body{{margin:0;padding:0;background:#000;height:100%;overflow:hidden}}iframe{{width:100%;height:100%;border:0}}</style></head>
        <body><iframe src='https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&playsinline=1'
        title='YouTube video player' allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share' allowfullscreen></iframe></body></html>"""
        self.youtube_player.setHtml(embed_html, QUrl("https://www.youtube-nocookie.com"))
        self.youtube_title.setText(title)
        self.youtube_description.setPlainText(video.get("description", ""))
        self.save_history(self.pending_query or self.youtube_search.text(), title, video_id)
        self.load_history()

    def save_history(self, query, title, video_id):
        if not self.current_user_id:
            return
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO watch_history(user_id, search_query, media_title, video_id) VALUES (?, ?, ?, ?)",
                (self.current_user_id, query, title, video_id)
            )

    def load_history(self):
        if not hasattr(self, "history_table"):
            return
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT search_query, media_title, datetime(searched_at, 'localtime') FROM watch_history WHERE user_id=? ORDER BY id DESC LIMIT 20",
                (self.current_user_id,)
            ).fetchall()
        self.history_table.setRowCount(0)
        for row, values in enumerate(rows):
            self.history_table.insertRow(row)
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(str(value)))

    # ---------------- LOCAL MUSIC PLAYER ----------------
    def build_music_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("LOCAL MUSIC PLAYER")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Add audio files from your computer. Supported formats depend on your system's Qt audio codecs."))
        add_row = QHBoxLayout()
        add_btn = QPushButton("Add Music Files")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self.add_music_files)
        remove_btn = QPushButton("Clear Playlist")
        remove_btn.clicked.connect(self.clear_music_playlist)
        add_row.addWidget(add_btn)
        add_row.addWidget(remove_btn)
        add_row.addStretch()
        layout.addLayout(add_row)
        self.music_list = QListWidget()
        self.music_list.itemDoubleClicked.connect(self.play_music_item)
        layout.addWidget(self.music_list, 1)
        self.now_playing = QLabel("Nothing playing")
        self.now_playing.setObjectName("SectionTitle")
        layout.addWidget(self.now_playing)
        controls = QHBoxLayout()
        for label, callback in [("Play", self.play_music), ("Pause", self.pause_music), ("Stop", self.stop_music)]:
            btn = QPushButton(label)
            btn.clicked.connect(callback)
            controls.addWidget(btn)
        controls.addStretch()
        layout.addLayout(controls)
        self.tabs.addTab(page, "Music Player")

    def add_music_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select audio files", "", "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a);;All Files (*)"
        )
        for file_path in files:
            if file_path not in self.music_files:
                self.music_files.append(file_path)
                self.music_list.addItem(Path(file_path).name)

    def clear_music_playlist(self):
        self.stop_music()
        self.music_files.clear()
        self.music_list.clear()
        self.now_playing.setText("Nothing playing")

    def play_music_item(self, item):
        index = self.music_list.row(item)
        if 0 <= index < len(self.music_files):
            self.music_player.setSource(QUrl.fromLocalFile(self.music_files[index]))
            self.music_player.play()
            self.now_playing.setText(Path(self.music_files[index]).name)

    def play_music(self):
        if self.music_player.source().isEmpty() and self.music_files:
            self.play_music_item(self.music_list.item(0))
        else:
            self.music_player.play()

    def pause_music(self):
        self.music_player.pause()

    def stop_music(self):
        self.music_player.stop()

    # ---------------- GUESS THE SONG ----------------
    def build_game_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("GUESS THE SONG")
        heading.setObjectName("SectionTitle")
        intro = QLabel("Listen to a short music clip, then choose the correct song from four answers.")
        intro.setObjectName("Muted")
        layout.addWidget(heading)
        layout.addWidget(intro)

        library_row = QHBoxLayout()
        add_song_btn = QPushButton("Add Quiz Song")
        add_song_btn.setObjectName("Primary")
        add_song_btn.clicked.connect(self.add_quiz_song)
        library_row.addWidget(add_song_btn)
        self.song_count_label = QLabel("0 songs in quiz library")
        self.song_count_label.setObjectName("Muted")
        library_row.addWidget(self.song_count_label)
        library_row.addStretch()
        layout.addLayout(library_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Clip length:"))
        self.clip_length = QComboBox()
        self.clip_length.addItem("3 seconds", 3)
        self.clip_length.addItem("5 seconds", 5)
        self.clip_length.addItem("10 seconds", 10)
        settings_row.addWidget(self.clip_length)
        settings_row.addWidget(QLabel("Questions:"))
        self.question_count = QComboBox()
        self.question_count.addItem("5", 5)
        self.question_count.addItem("10", 10)
        self.question_count.addItem("15", 15)
        self.question_count.setCurrentIndex(1)
        settings_row.addWidget(self.question_count)
        settings_row.addStretch()
        layout.addLayout(settings_row)

        self.game_status = QLabel("Add at least four quiz songs to start playing.")
        self.game_status.setObjectName("GameStatus")
        self.game_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.game_status)
        self.game_score_label = QLabel("Score: 0 / 0")
        self.game_score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.game_score_label)
        self.game_progress = QLabel("Ready when you are")
        self.game_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.game_progress.setObjectName("Muted")
        layout.addWidget(self.game_progress)

        self.answer_buttons = []
        for index in range(4):
            button = QPushButton(f"Option {index + 1}")
            button.setMinimumHeight(48)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, i=index: self.check_answer(i))
            self.answer_buttons.append(button)
            layout.addWidget(button)

        self.game_feedback = QLabel("")
        self.game_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.game_feedback)
        game_controls = QHBoxLayout()
        self.start_game_btn = QPushButton("Start Game")
        self.start_game_btn.setObjectName("Primary")
        self.start_game_btn.clicked.connect(self.start_game)
        self.next_question_btn = QPushButton("Next Question")
        self.next_question_btn.setEnabled(False)
        self.next_question_btn.clicked.connect(self.next_question)
        game_controls.addWidget(self.start_game_btn)
        game_controls.addWidget(self.next_question_btn)
        game_controls.addStretch()
        layout.addLayout(game_controls)

        layout.addWidget(QLabel("YOUR RECENT GAME SCORES"))
        self.scores_table = QTableWidget(0, 3)
        self.scores_table.setHorizontalHeaderLabels(["Score", "Questions", "Played at"])
        self.scores_table.horizontalHeader().setStretchLastSection(True)
        self.scores_table.setMaximumHeight(170)
        layout.addWidget(self.scores_table)
        layout.addStretch()
        self.tabs.addTab(page, "Guess the Song")

    def add_quiz_song(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Choose a song clip", "", "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a);;All Files (*)"
        )
        if not file_path:
            return
        title, ok = QInputDialog.getText(self, "Song title", "Enter the song title:")
        if not ok or not title.strip():
            return
        artist, ok = QInputDialog.getText(self, "Artist", "Enter the artist name:")
        if not ok:
            return
        try:
            with connect_db() as conn:
                conn.execute(
                    "INSERT INTO quiz_songs(title, artist, file_path) VALUES (?, ?, ?)",
                    (title.strip(), artist.strip() or "Unknown artist", file_path)
                )
            self.load_quiz_songs()
            QMessageBox.information(self, "Song added", "The song has been added to your quiz library.")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Already added", "This audio file is already in your quiz library.")

    def load_quiz_songs(self):
        with connect_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM quiz_songs").fetchone()[0]
        if hasattr(self, "song_count_label"):
            self.song_count_label.setText(f"{count} songs in quiz library")
        self.load_game_scores()

    def start_game(self):
        with connect_db() as conn:
            songs = conn.execute("SELECT id, title, artist, file_path FROM quiz_songs").fetchall()
        songs = [song for song in songs if os.path.isfile(song[3])]
        if len(songs) < 4:
            QMessageBox.warning(self, "Not enough songs", "Add at least four valid audio files to the quiz library first.")
            return
        self.quiz_total = self.question_count.currentData()
        self.quiz_questions = random.sample(songs, min(len(songs), self.quiz_total))
        self.quiz_total = len(self.quiz_questions)
        self.quiz_index = 0
        self.quiz_score = 0
        self.game_score_label.setText(f"Score: 0 / {self.quiz_total}")
        self.start_game_btn.setEnabled(False)
        self.show_question()

    def show_question(self):
        self.clip_timer.stop()
        self.game_player.stop()
        if self.quiz_index >= self.quiz_total:
            self.finish_game()
            return
        song = self.quiz_questions[self.quiz_index]
        other_songs = [s for s in self.quiz_questions if s[0] != song[0]]
        # Add distractors from the full library if the selected game has fewer than four songs.
        with connect_db() as conn:
            all_songs = conn.execute("SELECT id, title, artist, file_path FROM quiz_songs").fetchall()
        distractors = [s for s in all_songs if s[0] != song[0] and s[0] not in {x[0] for x in other_songs}]
        choices = [song] + random.sample(other_songs + distractors, 3)
        random.shuffle(choices)
        self.current_question = {"song": song, "choices": choices}
        self.answer_locked = False
        self.game_feedback.setText("")
        self.game_progress.setText(f"Question {self.quiz_index + 1} of {self.quiz_total}")
        self.game_status.setText(f"Listen to the {self.clip_length.currentData()}-second clip...")
        for index, button in enumerate(self.answer_buttons):
            button.setText(f"{chr(65 + index)}. {choices[index][1]} — {choices[index][2]}")
            button.setEnabled(False)
            button.setStyleSheet("")
        self.quiz_clip_duration_ms = int(self.clip_length.currentData()) * 1000
        self.waiting_for_quiz_clip = True
        self.game_player.setSource(QUrl.fromLocalFile(song[3]))
        self.game_player.play()

    def handle_quiz_media_status(self, status):
        if self.waiting_for_quiz_clip and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self.waiting_for_quiz_clip = False
            self.clip_timer.start(self.quiz_clip_duration_ms)

    def stop_quiz_clip(self):
        self.game_player.stop()
        self.game_status.setText("Clip finished! Choose the correct song.")
        for button in self.answer_buttons:
            button.setEnabled(True)

    def check_answer(self, choice_index):
        if self.answer_locked or not self.current_question:
            return
        self.answer_locked = True
        correct_song = self.current_question["song"]
        selected_song = self.current_question["choices"][choice_index]
        if selected_song[0] == correct_song[0]:
            self.quiz_score += 1
            self.game_feedback.setText("Correct! Nice work.")
            self.game_feedback.setStyleSheet("color:#34d399;font-weight:700")
        else:
            self.game_feedback.setText(f"Not quite. Correct answer: {correct_song[1]} — {correct_song[2]}")
            self.game_feedback.setStyleSheet("color:#f87171;font-weight:700")
        self.game_score_label.setText(f"Score: {self.quiz_score} / {self.quiz_total}")
        for button in self.answer_buttons:
            button.setEnabled(False)
        self.next_question_btn.setEnabled(True)

    def next_question(self):
        self.next_question_btn.setEnabled(False)
        self.quiz_index += 1
        self.show_question()

    def finish_game(self):
        self.game_player.stop()
        self.game_status.setText("Game completed!")
        self.game_progress.setText(f"Final result: {self.quiz_score} out of {self.quiz_total}")
        self.game_feedback.setText("Great job! Start another game whenever you're ready.")
        self.start_game_btn.setEnabled(True)
        self.next_question_btn.setEnabled(False)
        for button in self.answer_buttons:
            button.setEnabled(False)
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO game_scores(user_id, score, total_questions) VALUES (?, ?, ?)",
                (self.current_user_id, self.quiz_score, self.quiz_total)
            )
        self.load_game_scores()

    def load_game_scores(self):
        if not hasattr(self, "scores_table") or not self.current_user_id:
            return
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT score, total_questions, datetime(played_at, 'localtime') FROM game_scores WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (self.current_user_id,)
            ).fetchall()
        self.scores_table.setRowCount(0)
        for row, values in enumerate(rows):
            self.scores_table.insertRow(row)
            for col, value in enumerate(values):
                self.scores_table.setItem(row, col, QTableWidgetItem(str(value)))

    # ---------------- REVIEWS / COMMUNITY ----------------
    def build_community_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("COMMUNITY REVIEWS")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.review_title = QLineEdit()
        self.review_title.setPlaceholderText("Song or video title")
        self.review_rating = QComboBox()
        for value in range(1, 6):
            self.review_rating.addItem("★" * value, value)
        self.review_rating.setCurrentIndex(4)
        self.review_comment = QTextEdit()
        self.review_comment.setPlaceholderText("Write your review...")
        self.review_comment.setMaximumHeight(100)
        form.addRow("Media title", self.review_title)
        form.addRow("Rating", self.review_rating)
        form.addRow("Review", self.review_comment)
        layout.addLayout(form)
        save_btn = QPushButton("Save Review")
        save_btn.setObjectName("Primary")
        save_btn.clicked.connect(self.save_review)
        layout.addWidget(save_btn)
        self.reviews_table = QTableWidget(0, 4)
        self.reviews_table.setHorizontalHeaderLabels(["User", "Media", "Rating", "Review"])
        self.reviews_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.reviews_table, 1)
        self.tabs.addTab(page, "Reviews")

    def save_review(self):
        title = self.review_title.text().strip()
        comment = self.review_comment.toPlainText().strip()
        if not title or not comment:
            QMessageBox.warning(self, "Missing information", "Enter a media title and review.")
            return
        with connect_db() as conn:
            conn.execute(
                "INSERT INTO reviews(user_id, media_title, rating, comment) VALUES (?, ?, ?, ?)",
                (self.current_user_id, title, self.review_rating.currentData(), comment)
            )
        self.review_title.clear()
        self.review_comment.clear()
        self.load_reviews()

    def load_reviews(self):
        if not hasattr(self, "reviews_table"):
            return
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT users.username, reviews.media_title, reviews.rating, reviews.comment FROM reviews JOIN users ON users.id=reviews.user_id ORDER BY reviews.id DESC LIMIT 100"
            ).fetchall()
        self.reviews_table.setRowCount(0)
        for row, values in enumerate(rows):
            self.reviews_table.insertRow(row)
            for col, value in enumerate(values):
                display = "★" * value if col == 2 else str(value)
                self.reviews_table.setItem(row, col, QTableWidgetItem(display))

    # ---------------- LOGOUT / STYLING ----------------
    def logout(self):
        self.clip_timer.stop()
        self.music_player.stop()
        self.game_player.stop()
        self.current_user_id = None
        self.current_username = ""
        self.stack.setCurrentIndex(0)

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget { background:#090d16; color:#e2e8f0; font-family:'Segoe UI'; font-size:13px; }
            QFrame#AuthCard { background:#0f172a; border:1px solid #263449; border-radius:16px; }
            QLabel#AuthLogo { color:#ffffff; font-size:25px; font-weight:900; letter-spacing:3px; padding:8px; }
            QLabel#Brand { color:#ffffff; font-size:21px; font-weight:900; letter-spacing:2px; }
            QLabel#UserBadge { color:#34d399; background:#10251f; border:1px solid #1e4939; border-radius:10px; padding:7px 12px; }
            QLabel#Muted { color:#94a3b8; }
            QLabel#SectionTitle { color:#ffffff; font-size:18px; font-weight:700; padding:5px 0; }
            QLabel#GameStatus { color:#ffffff; background:#111c30; border:1px solid #263449; border-radius:12px; padding:20px; font-size:18px; font-weight:700; }
            QLineEdit, QTextEdit, QComboBox, QListWidget, QTableWidget { background:#0b1220; color:#e2e8f0; border:1px solid #263449; border-radius:8px; padding:8px; selection-background-color:#1d4ed8; }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border:1px solid #3b82f6; }
            QPushButton { background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:10px 15px; font-weight:600; }
            QPushButton:hover { background:#334155; }
            QPushButton:disabled { color:#64748b; background:#111827; }
            QPushButton#Primary { background:#2563eb; border:1px solid #2563eb; color:white; }
            QPushButton#Primary:hover { background:#1d4ed8; }
            QPushButton#LinkButton { background:transparent; border:none; color:#60a5fa; }
            QTabWidget::pane { border:1px solid #263449; border-radius:10px; padding:8px; }
            QTabBar::tab { background:#111827; color:#94a3b8; padding:11px 18px; margin-right:4px; border-radius:7px; }
            QTabBar::tab:selected { background:#1d4ed8; color:white; }
            QHeaderView::section { background:#172033; color:#cbd5e1; border:none; padding:7px; }
        """)


def main():
    init_db()
    app = QApplication(sys.argv)
    window = TrackboxdApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
