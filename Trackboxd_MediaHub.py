import hashlib
import os
import sqlite3
import sys
import json
import urllib.parse
import urllib.request
from PyQt6.QtGui import QDesktopServices
from yt_dlp import YoutubeDL

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineHttpRequest
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

DB_NAME = "trackboxd.db"


# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL,
            salt BLOB NOT NULL
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            media_title TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """
    )

    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 100000
    )
    return key, salt


# --- BACKGROUND THREAD FOR YOUTUBE SEARCH ---
class YTFetchThread(QThread):
    finished_signal = pyqtSignal(str, str, str)
    error_signal = pyqtSignal(str)

    def __init__(self, search_query):
        super().__init__()
        self.search_query = search_query

    def run(self):
        try:
            ydl_opts = {
                "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                "quiet": True,
                "noplaylist": True,
                "default_search": "ytsearch1:",
                "js_runtimes": {"node": {}},
                "remote_components": ["ejs:github"],
                "extractor_args": {
                    "youtube": {
                        "player_client": ["ios", "android", "web"],
                    }
                },
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.search_query, download=False)
                if "entries" in info and len(info["entries"]) > 0:
                    video = info["entries"][0]
                else:
                    video = info

                stream_url = video.get("url")
                title = video.get("title", self.search_query)
                description = video.get(
                    "description", "No description provided for this release."
                )

                if stream_url:
                    self.finished_signal.emit(stream_url, title, description)
                else:
                    self.error_signal.emit(
                        "Could not extract stream URL for this video."
                    )
        except Exception as e:
            self.error_signal.emit(str(e))


class CatalogFetchThread(QThread):
    results_signal = pyqtSignal(str, list)
    error_signal = pyqtSignal(str, str)

    def __init__(self, category, query):
        super().__init__()
        self.category = category
        self.query = query

    def run(self):
        try:
            if self.category == "Music":
                params = urllib.parse.urlencode({
                    "term": self.query,
                    "entity": "song",
                    "limit": 18
                })
                url = "https://itunes.apple.com/search?" + params

            elif self.category == "Movies":
                api_key = os.environ.get("YOUTUBE_API_KEY")

                if not api_key:
                    raise Exception("YouTube API key not found.")

                params = urllib.parse.urlencode({
                    "part": "snippet",
                    "q": self.query,
                    "type": "video",
                    "maxResults": 25,
                    "key": api_key
                })

                url = "https://www.googleapis.com/youtube/v3/search?" + params

            else:
                params = urllib.parse.urlencode({
                    "term": self.query,
                    "cc": "ph",
                    "l": "en",
                    "count": 25
                })
                url = "https://store.steampowered.com/api/storesearch/?" + params

            request = urllib.request.Request(
                url,
                headers={"User-Agent": "TRACKBOXD/1.0"}
            )

            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))

            if self.category == "Music":
                results = payload.get("results", [])
            else:
                results = payload.get("items", [])

            self.results_signal.emit(self.category, results)

        except Exception as exc:
            self.error_signal.emit(self.category, str(exc))


# --- MAIN APPLICATION ---



class TrackboxdApp(QStackedWidget):

    def open_snake_game(self):
        if not hasattr(self, "game_page"):
            self.game_page = QWidget()
            game_layout = QVBoxLayout(self.game_page)

            back_button = QPushButton("← Back to Games")
            back_button.setObjectName("ControlButton")
            back_button.setMinimumHeight(40)
            back_button.clicked.connect(
                lambda: self.content_stack.setCurrentIndex(3)
            )

            self.game_view = QWebEngineView()

            game_path = os.path.abspath(
                os.path.join("games", "snake.html")
            )

            self.game_view.setUrl(
                QUrl.fromLocalFile(game_path)
            )

            game_layout.addWidget(back_button)
            game_layout.addWidget(self.game_view, 1)

            self.content_stack.addWidget(self.game_page)

        self.content_stack.setCurrentWidget(self.game_page)

    def open_tictactoe_game(self):
        if not hasattr(self, "tictactoe_page"):
            self.tictactoe_page = QWidget()
            game_layout = QVBoxLayout(self.tictactoe_page)

            back_button = QPushButton("← Back to Games")
            back_button.setObjectName("ControlButton")
            back_button.setMinimumHeight(40)
            back_button.clicked.connect(
                lambda: self.content_stack.setCurrentIndex(3)
            )

            self.tictactoe_view = QWebEngineView()

            game_path = os.path.abspath(
                os.path.join("games", "tictactoe.html")
            )

            self.tictactoe_view.setUrl(
                QUrl.fromLocalFile(game_path)
            )

            game_layout.addWidget(back_button)
            game_layout.addWidget(self.tictactoe_view, 1)

            self.content_stack.addWidget(self.tictactoe_page)

        self.content_stack.setCurrentWidget(self.tictactoe_page)

    def __init__(self):
        super().__init__()

        self.current_user_id = None
        self.current_username = ""

        # Views
        self.login_screen = QWidget()
        self.register_screen = QWidget()
        self.main_screen = QWidget()

        self.addWidget(self.login_screen)
        self.addWidget(self.register_screen)
        self.addWidget(self.main_screen)

        self.setup_login_ui()
        self.setup_register_ui()
        self.setup_main_ui()

        self.setWindowTitle("Trackboxd — Music Video Journal")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.showNormal()
        self.activateWindow()
        self.raise_()

        self.apply_professional_stylesheet()

    def setup_login_ui(self):
        outer = QVBoxLayout()


    # --- PAGE 0: LOGIN UI ---
    def setup_login_ui(self):
        outer = QVBoxLayout()
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setFixedWidth(410)
        card.setObjectName("AuthCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 40, 36, 40)

        logo = QLabel("TRACKBOXD")
        logo.setObjectName("BrandLogoAuth")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sub = QLabel("Log in to your music journal")
        sub.setObjectName("BrandSubAuth")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("Username")

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Password")
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)

        login_btn = QPushButton("Log In")
        login_btn.setObjectName("PrimaryLogBtn")
        login_btn.clicked.connect(self.handle_login)

        go_to_reg_btn = QPushButton("Don't have an account? Register")
        go_to_reg_btn.setObjectName("SecondaryBtn")
        go_to_reg_btn.clicked.connect(lambda: self.setCurrentIndex(1))

        self.login_msg = QLabel("")
        self.login_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(logo)
        card_layout.addWidget(sub)
        card_layout.addSpacing(20)
        card_layout.addWidget(self.login_username)
        card_layout.addWidget(self.login_password)
        card_layout.addSpacing(12)
        card_layout.addWidget(login_btn)
        card_layout.addWidget(go_to_reg_btn)
        card_layout.addWidget(self.login_msg)

        outer.addWidget(card)
        self.login_screen.setLayout(outer)

    # --- PAGE 1: REGISTER UI ---
    def setup_register_ui(self):
        outer = QVBoxLayout()
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setFixedWidth(410)
        card.setObjectName("AuthCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 40, 36, 40)

        logo = QLabel("TRACKBOXD")
        logo.setObjectName("BrandLogoAuth")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sub = QLabel("Create a new listener profile")
        sub.setObjectName("BrandSubAuth")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.reg_username = QLineEdit()
        self.reg_username.setPlaceholderText("Choose a Username")

        self.reg_password = QLineEdit()
        self.reg_password.setPlaceholderText("Choose a Password")
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)

        reg_btn = QPushButton("Create Account")
        reg_btn.setObjectName("PrimaryLogBtn")
        reg_btn.clicked.connect(self.handle_register)

        go_to_login_btn = QPushButton("Already have an account? Log In")
        go_to_login_btn.setObjectName("SecondaryBtn")
        go_to_login_btn.clicked.connect(lambda: self.setCurrentIndex(0))

        self.reg_msg = QLabel("")
        self.reg_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(logo)
        card_layout.addWidget(sub)
        card_layout.addSpacing(20)
        card_layout.addWidget(self.reg_username)
        card_layout.addWidget(self.reg_password)
        card_layout.addSpacing(12)
        card_layout.addWidget(reg_btn)
        card_layout.addWidget(go_to_login_btn)
        card_layout.addWidget(self.reg_msg)

        outer.addWidget(card)
        self.register_screen.setLayout(outer)

    # --- AUTH LOGIC ---
    def handle_register(self):
        username = self.reg_username.text().strip()
        password = self.reg_password.text().strip()

        if not username or not password:
            self.show_msg(self.reg_msg, "Please complete all fields.", True)
            return

        key, salt = hash_password(password)
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, key, salt),
            )
            conn.commit()
            conn.close()

            QMessageBox.information(
                self,
                "Success",
                "Account created successfully! Redirecting to login...",
            )
            self.reg_username.clear()
            self.reg_password.clear()
            self.setCurrentIndex(0)

        except sqlite3.IntegrityError:
            self.show_msg(
                self.reg_msg, f"Username '{username}' already taken.", True
            )

    def handle_login(self):
        username = self.login_username.text().strip()
        password = self.login_password.text().strip()

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, password_hash, salt FROM users WHERE username = ?",
            (username,),
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            user_id, stored_hash, salt = user
            new_hash, _ = hash_password(password, salt)
            if new_hash == stored_hash:
                self.current_user_id = user_id
                self.current_username = username
                self.user_badge.setText(f"@{username}")
                self.login_username.clear()
                self.login_password.clear()
                self.login_msg.setText("")

                self.setCurrentIndex(2)
                self.load_reviews()
                return

        self.show_msg(self.login_msg, "Invalid username or password.", True)

    def show_msg(self, label, text, error=True):
        label.setText(text)
        label.setStyleSheet("color: #f87171;" if error else "color: #34d399;")

    # --- PAGE 2: MAIN DASHBOARD & MEDIA PLAYER ---
    def setup_main_ui(self):
        self.main_screen.setObjectName("MainScreen")

        root_layout = QHBoxLayout(self.main_screen)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(18)

        # Premium left navigation
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 20)
        sidebar_layout.setSpacing(10)

        brand = QLabel("TRACKBOXD")
        brand.setObjectName("SidebarBrand")
        brand_sub = QLabel("YOUR MEDIA JOURNAL")
        brand_sub.setObjectName("SidebarCaption")

        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(brand_sub)
        sidebar_layout.addSpacing(28)

        nav_label = QLabel("WORKSPACE")
        nav_label.setObjectName("SidebarSection")
        sidebar_layout.addWidget(nav_label)


        music_btn = QPushButton("♫   Music & Videos")
        music_btn.setObjectName("NavButton")
        music_btn.setProperty("active", False)

        movies_btn = QPushButton("▣   Movies")
        movies_btn.setObjectName("NavButton")
        movies_btn.setProperty("active", False)

        games_btn = QPushButton("◇   Games")
        games_btn.setObjectName("NavButton")
        games_btn.setProperty("active", False)

        reviews_nav_btn = QPushButton("✎   My Reviews")
        reviews_nav_btn.setObjectName("NavButton")
        reviews_nav_btn.setProperty("active", False)

        for button in (music_btn, movies_btn, games_btn, reviews_nav_btn):
            button.setMinimumHeight(43)
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch()

        library_label = QLabel("YOUR SPACE")
        library_label.setObjectName("SidebarSection")
        sidebar_layout.addWidget(library_label)

        self.user_badge = QLabel("@guest")
        self.user_badge.setObjectName("UserPill")
        self.user_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(self.user_badge)

        logout_btn = QPushButton("↪   Log Out")
        logout_btn.setObjectName("SidebarLogout")
        logout_btn.clicked.connect(self.handle_logout)
        sidebar_layout.addWidget(logout_btn)

        # Main content area
        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 4, 8, 4)
        content_layout.setSpacing(18)

        header = QHBoxLayout()
        header_texts = QVBoxLayout()
        page_kicker = QLabel("YOUR PERSONAL MEDIA SPACE")
        page_kicker.setObjectName("SectionKicker")
        page_title = QLabel("My Reviews")
        page_title.setObjectName("PageTitle")
        header_texts.addWidget(page_kicker)
        header_texts.addWidget(page_title)
        header.addLayout(header_texts)
        header.addStretch()
        content_layout.addLayout(header)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("MainScroll")

        scroll_content = QWidget()
        scroll_content.setObjectName("ScrollContent")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(2, 2, 10, 18)
        scroll_layout.setSpacing(18)

        # Featured hero panel
        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(28, 24, 28, 24)

        hero_text = QVBoxLayout()
        hero_kicker = QLabel("LISTEN • WATCH • DOCUMENT")
        hero_kicker.setObjectName("HeroKicker")
        hero_title = QLabel("Your next favorite\nstarts here.")
        hero_title.setObjectName("HeroTitle")
        hero_description = QLabel(
            "Discover music and music videos, then keep a record of what you think."
        )
        hero_description.setObjectName("HeroDescription")
        hero_description.setWordWrap(True)

        explore_btn = QPushButton("Explore music  →")
        explore_btn.setObjectName("HeroButton")
        explore_btn.clicked.connect(lambda: self.search_input.setFocus())

        hero_text.addWidget(hero_kicker)
        hero_text.addSpacing(7)
        hero_text.addWidget(hero_title)
        hero_text.addSpacing(5)
        hero_text.addWidget(hero_description)
        hero_text.addSpacing(14)
        hero_text.addWidget(explore_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(hero_text, 1)

        hero_side = QLabel("T\nB")
        hero_side.setObjectName("HeroMonogram")
        hero_side.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_side.setFixedSize(112, 112)
        hero_layout.addWidget(hero_side, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scroll_layout.addWidget(hero)

        # Player and release details
        player_card = QFrame()
        player_card.setObjectName("ProCard")
        player_layout = QVBoxLayout(player_card)
        player_layout.setContentsMargins(22, 20, 22, 20)
        player_layout.setSpacing(13)

        player_header = QHBoxLayout()
        player_heading = QVBoxLayout()
        player_kicker = QLabel("NOW PLAYING")
        player_kicker.setObjectName("SectionKicker")
        player_title = QLabel("Music & video player")
        player_title.setObjectName("CardHeader")
        player_heading.addWidget(player_kicker)
        player_heading.addWidget(player_title)
        player_header.addLayout(player_heading)
        player_header.addStretch()

        self.status_label = QLabel("Ready when you are. Search for a track to begin.")
        self.status_label.setObjectName("StatusPill")
        player_header.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        player_layout.addLayout(player_header)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search a track, artist, or music video...")
        self.search_input.returnPressed.connect(self.search_youtube_video)

        search_btn = QPushButton("Search & Play")
        search_btn.setObjectName("PrimaryButton")
        search_btn.clicked.connect(self.search_youtube_video)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(search_btn)
        player_layout.addLayout(search_row)

        media_row = QHBoxLayout()
        media_row.setSpacing(18)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(280)
        self.video_widget.setObjectName("VideoSurface")

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.mediaStatusChanged.connect(self.handle_media_status)

        release_panel = QFrame()
        release_panel.setObjectName("ReleasePanel")
        release_layout = QVBoxLayout(release_panel)
        release_layout.setContentsMargins(18, 18, 18, 18)
        release_kicker = QLabel("ABOUT THIS RELEASE")
        release_kicker.setObjectName("SectionKicker")
        self.about_text = QLabel(
            "Release details and description will appear here after you select a video."
        )
        self.about_text.setObjectName("SubText")
        self.about_text.setWordWrap(True)
        release_layout.addWidget(release_kicker)
        release_layout.addSpacing(8)
        release_layout.addWidget(self.about_text)
        release_layout.addStretch()

        media_row.addWidget(self.video_widget, 2)
        media_row.addWidget(release_panel, 1)
        player_layout.addLayout(media_row)

        controls = QHBoxLayout()
        play_btn = QPushButton("▶  Play")
        pause_btn = QPushButton("Ⅱ  Pause")
        stop_btn = QPushButton("■  Stop")
        for button in (play_btn, pause_btn, stop_btn):
            button.setObjectName("ControlButton")
        play_btn.clicked.connect(self.media_player.play)
        pause_btn.clicked.connect(self.media_player.pause)
        stop_btn.clicked.connect(self.media_player.stop)

        volume_label = QLabel("VOLUME")
        volume_label.setObjectName("FieldLabel")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(125)
        self.audio_output.setVolume(0.70)

        self.volume_val_label = QLabel("70%")
        self.volume_val_label.setObjectName("SubText")
        self.volume_val_label.setFixedWidth(35)
        self.volume_slider.valueChanged.connect(self.update_volume)

        controls.addWidget(play_btn)
        controls.addWidget(pause_btn)
        controls.addWidget(stop_btn)
        controls.addStretch()
        controls.addWidget(volume_label)
        controls.addWidget(self.volume_slider)
        controls.addWidget(self.volume_val_label)
        player_layout.addLayout(controls)
        scroll_layout.addWidget(player_card)

        # Review form and community activity
        lower_row = QHBoxLayout()
        lower_row.setSpacing(18)

        log_card = QFrame()
        log_card.setObjectName("ProCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(22, 20, 22, 20)

        log_title = QLabel("Log & Review")
        log_title.setObjectName("CardHeader")
        log_sub = QLabel("Save your rating and thoughts about this release.")
        log_sub.setObjectName("SubText")

        name_label = QLabel("REVIEWER")
        name_label.setObjectName("FieldLabel")
        self.name_display = QLineEdit()
        self.name_display.setReadOnly(True)

        target_label = QLabel("RELEASE TITLE")
        target_label.setObjectName("FieldLabel")
        self.media_title_input = QLineEdit()
        self.media_title_input.setPlaceholderText("Automatically filled after search...")
        self.media_title_input.setReadOnly(True)

        rating_label = QLabel("YOUR RATING")
        rating_label.setObjectName("FieldLabel")
        self.rating_combo = QComboBox()
        self.rating_combo.addItem("★☆☆☆☆   1 / 5", 1)
        self.rating_combo.addItem("★★☆☆☆   2 / 5", 2)
        self.rating_combo.addItem("★★★☆☆   3 / 5", 3)
        self.rating_combo.addItem("★★★★☆   4 / 5", 4)
        self.rating_combo.addItem("★★★★★   5 / 5", 5)
        self.rating_combo.setCurrentIndex(4)

        review_label = QLabel("YOUR REVIEW")
        review_label.setObjectName("FieldLabel")
        self.review_input = QTextEdit()
        self.review_input.setPlaceholderText("What stood out to you?")
        self.review_input.setFixedHeight(100)

        submit_btn = QPushButton("Save review")
        submit_btn.setObjectName("PrimaryButton")
        submit_btn.clicked.connect(self.save_review)

        log_layout.addWidget(log_title)
        log_layout.addWidget(log_sub)
        log_layout.addSpacing(10)
        log_layout.addWidget(name_label)
        log_layout.addWidget(self.name_display)
        log_layout.addWidget(target_label)
        log_layout.addWidget(self.media_title_input)
        log_layout.addWidget(rating_label)
        log_layout.addWidget(self.rating_combo)
        log_layout.addWidget(review_label)
        log_layout.addWidget(self.review_input)
        log_layout.addSpacing(8)
        log_layout.addWidget(submit_btn)

        reviews_card = QFrame()
        reviews_card.setObjectName("ProCard")
        reviews_layout = QVBoxLayout(reviews_card)
        reviews_layout.setContentsMargins(22, 20, 22, 20)

        reviews_title = QLabel("Community reviews")
        reviews_title.setObjectName("CardHeader")
        reviews_sub = QLabel("Recent ratings from the TRACKBOXD community.")
        reviews_sub.setObjectName("SubText")

        self.reviews_table = QTableWidget(0, 4)
        self.reviews_table.setHorizontalHeaderLabels(
            ["USER", "RELEASE", "RATING", "REVIEW"]
        )
        self.reviews_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.reviews_table.setMinimumHeight(270)
        self.reviews_table.setAlternatingRowColors(True)

        reviews_layout.addWidget(reviews_title)
        reviews_layout.addWidget(reviews_sub)
        reviews_layout.addSpacing(12)
        reviews_layout.addWidget(self.reviews_table)

        lower_row.addWidget(log_card, 1)
        lower_row.addWidget(reviews_card, 1)
        scroll_layout.addLayout(lower_row)

        scroll_area.setWidget(scroll_content)

        # Separate catalog pages; the existing Discover / Reviews UI stays intact.
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(scroll_area)
        self.catalog_lists = {}
        self.catalog_searches = {}
        self.catalog_status = {}
        for category in ("Music", "Movies", "Games"):
            page = self.build_catalog_page(category)
            self.content_stack.addWidget(page)
        content_layout.addWidget(self.content_stack)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)

        self.nav_buttons = {
            "Music": music_btn,
            "Movies": movies_btn,
            "Games": games_btn,
            "Reviews": reviews_nav_btn,
        }
        music_btn.clicked.connect(lambda: self.show_section("Music"))
        movies_btn.clicked.connect(lambda: self.show_section("Movies"))
        games_btn.clicked.connect(lambda: self.show_section("Games"))
        reviews_nav_btn.clicked.connect(lambda: self.show_section("Reviews"))
        self.show_section("Reviews")

    def build_catalog_page(self, category):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 10, 12)
        layout.setSpacing(16)

        intro = QFrame()
        intro.setObjectName("HeroCard")
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(24, 20, 24, 20)
        kicker = QLabel("TRACKBOXD DISCOVERY")
        kicker.setObjectName("HeroKicker")
        heading = QLabel({"Music": "Find your next favorite sound", "Movies": "Find your next movie night", "Games": "Find your next game"}[category])
        heading.setObjectName("HeroTitle")
        description = QLabel({
            "Music": "Browse song recommendations and play available previews.",
            "Movies": "Search movie titles and browse available movie details from the Apple iTunes catalog.",
            "Games": "Discover games from the catalog and play selected arcade games directly inside TRACKBOXD."
        }[category])
        description.setObjectName("HeroDescription")
        description.setWordWrap(True)
        intro_layout.addWidget(kicker)
        intro_layout.addWidget(heading)
        intro_layout.addWidget(description)
        layout.addWidget(intro)

        search_row = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText(f"Search {category.lower()}...")
        search_button = QPushButton(f"Search {category}")
        search_button.setObjectName("PrimaryButton")
        search_row.addWidget(search, 1)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        # Shared playback controls are also available directly on the Music page.
        # They control the same QMediaPlayer used by the video player on Discover.
        if category == "Music":
            playback_card = QFrame()
            playback_card.setObjectName("ProCard")
            playback_layout = QHBoxLayout(playback_card)
            playback_layout.setContentsMargins(18, 12, 18, 12)
            playback_layout.setSpacing(10)

            playback_label = QLabel("MUSIC PLAYER")
            playback_label.setObjectName("SectionKicker")
            playback_layout.addWidget(playback_label)

            music_play_btn = QPushButton("▶  Play")
            music_pause_btn = QPushButton("Ⅱ  Pause")
            music_stop_btn = QPushButton("■  Stop")
            for control in (music_play_btn, music_pause_btn, music_stop_btn):
                control.setObjectName("ControlButton")
                control.setMinimumHeight(36)
            music_play_btn.clicked.connect(self.media_player.play)
            music_pause_btn.clicked.connect(self.media_player.pause)
            music_stop_btn.clicked.connect(self.media_player.stop)
            playback_layout.addWidget(music_play_btn)
            playback_layout.addWidget(music_pause_btn)
            playback_layout.addWidget(music_stop_btn)
            playback_layout.addStretch()

            music_volume_label = QLabel("VOLUME")
            music_volume_label.setObjectName("FieldLabel")
            playback_layout.addWidget(music_volume_label)

            self.music_volume_slider = QSlider(Qt.Orientation.Horizontal)
            self.music_volume_slider.setRange(0, 100)
            self.music_volume_slider.setValue(70)
            self.music_volume_slider.setFixedWidth(125)
            self.music_volume_slider.valueChanged.connect(self.update_volume)
            playback_layout.addWidget(self.music_volume_slider)

            self.music_volume_value = QLabel("70%")
            self.music_volume_value.setObjectName("SubText")
            self.music_volume_value.setFixedWidth(38)
            playback_layout.addWidget(self.music_volume_value)
            layout.addWidget(playback_card)

        status = QLabel("Loading recommendations...")
        status.setObjectName("SubText")
        layout.addWidget(status)
        results = QListWidget()
        results.setObjectName("CatalogResults")
        results.setSpacing(6)
        layout.addWidget(results, 1)


        # Embedded arcade games
        if category == "Games":
            arcade_card = QFrame()
            arcade_card.setObjectName("ProCard")

            arcade_layout = QVBoxLayout(arcade_card)
            arcade_layout.setContentsMargins(18, 16, 18, 16)
            arcade_layout.setSpacing(10)

            arcade_title = QLabel("TRACKBOXD ARCADE")
            arcade_title.setObjectName("SectionKicker")

            arcade_description = QLabel(
                "Play classic arcade games without leaving TRACKBOXD."
            )
            arcade_description.setObjectName("SubText")

            snake_button = QPushButton("▶  Play Snake")
            snake_button.setObjectName("PrimaryButton")
            snake_button.setMinimumHeight(42)
            snake_button.clicked.connect(self.open_snake_game)

            tictactoe_button = QPushButton("▶  Play Tic-Tac-Toe")
            tictactoe_button.setObjectName("PrimaryButton")
            tictactoe_button.setMinimumHeight(42)
            tictactoe_button.clicked.connect(self.open_tictactoe_game)

            arcade_layout.addWidget(arcade_title)
            arcade_layout.addWidget(arcade_description)
            arcade_layout.addWidget(snake_button)
            arcade_layout.addWidget(tictactoe_button)

            layout.addWidget(arcade_card)

        self.catalog_lists[category] = results
        self.catalog_searches[category] = search
        self.catalog_status[category] = status
        search_button.clicked.connect(lambda checked=False, c=category: self.fetch_catalog(c, self.catalog_searches[c].text().strip()))
        search.returnPressed.connect(lambda c=category: self.fetch_catalog(c, self.catalog_searches[c].text().strip()))
        results.itemDoubleClicked.connect(lambda item, c=category: self.open_catalog_item(c, item))
        return page

    def show_section(self, section):
        indexes = {
            "Music": 1,
            "Movies": 2,
            "Games": 3,
            "Reviews": 0
        }

        self.content_stack.setCurrentIndex(indexes[section])

        for name, button in self.nav_buttons.items():
            button.setProperty("active", name == section)
            button.style().unpolish(button)
            button.style().polish(button)

        if section == "Reviews":
            self.review_input.setFocus()

        elif section in ("Music", "Movies", "Games"):
            listing = self.catalog_lists[section]

            if listing.count() == 0:
                defaults = {
                    "Music": "top hits",
                    "Movies": "Interstellar",
                    "Games": "Minecraft"
                }
                self.fetch_catalog(section, defaults[section])

    def fetch_catalog(self, category, query):
        if not query:
            query = {"Music": "top hits", "Movies": "Interstellar", "Games": "Minecraft"}[category]
        self.catalog_status[category].setText(f"Finding {category.lower()} recommendations...")
        self.catalog_lists[category].clear()
        self.catalog_thread = CatalogFetchThread(category, query)
        self.catalog_thread.results_signal.connect(self.show_catalog_results)
        self.catalog_thread.error_signal.connect(self.show_catalog_error)
        self.catalog_thread.start()

    def show_catalog_results(self, category, results):
        listing = self.catalog_lists[category]
        listing.clear()
        if not results:
            if category == "Movies":
                self.catalog_status[category].setText("No movie results found. Try an exact title such as Interstellar.")
            elif category == "Games":
                self.catalog_status[category].setText("No games found. Try Minecraft, Dota 2, or Portal 2. Check your internet connection.")
            else:
                self.catalog_status[category].setText("No results found. Try another search.")
            return
        for result in results:
            if category == "Music":
                title = result.get("trackName", "Unknown track")
                creator = result.get("artistName", "Unknown artist")
                detail = result.get("collectionName", "Single")

            elif category == "Movies":
                snippet = result.get("snippet", {})
                title = snippet.get("title", "Unknown video")
                creator = snippet.get("channelTitle", "YouTube")
                detail = "YouTube Video"

            else:
                title = result.get("name", "Unknown game")
                creator = "Steam game"
                detail = "Open game details"

            item = QListWidgetItem(f"  {title}   ·   {creator}   ·   {detail}")
            item.setData(Qt.ItemDataRole.UserRole, result)
            listing.addItem(item)

        self.catalog_status[category].setText(
            f"Showing {len(results)} recommendations/results. Double-click an item to open or play it."
        )

    def show_catalog_error(self, category, message):
        self.catalog_status[category].setText(f"Could not load {category.lower()}: {message}")

    def open_catalog_item(self, category, item):
        result = item.data(Qt.ItemDataRole.UserRole) or {}

        if category == "Music":
            preview = result.get("previewUrl")

            if preview:
                self.media_player.setSource(QUrl(preview))
                self.media_player.play()
                self.media_title_input.setText(result.get("trackName", ""))
                self.status_label.setText(
                    f"Preview: {result.get('trackName', 'Selected track')}"
                )
                self.about_text.setText(
                    f"{result.get('artistName', '')}\n"
                    f"{result.get('collectionName', '')}\n"
                    "Preview provided by Apple/iTunes."
                )
            else:
                link = result.get("trackViewUrl")
                if link:
                    QDesktopServices.openUrl(QUrl(link))

        elif category == "Movies":
            video_id = result.get("id", {}).get("videoId")

            if not video_id:
                QMessageBox.information(
                    self,
                    "Playback Error",
                    "YouTube video ID is not available."
                )
                return

            if not hasattr(self, "youtube_player_page"):
                self.youtube_player_page = QWidget()
                player_layout = QVBoxLayout(self.youtube_player_page)

                back_button = QPushButton("← Back to Movies")
                back_button.clicked.connect(
                    lambda: self.content_stack.setCurrentIndex(2)
                )

                self.youtube_player_view = QWebEngineView()

                player_layout.addWidget(back_button)
                player_layout.addWidget(self.youtube_player_view)

                self.content_stack.addWidget(self.youtube_player_page)

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta name="referrer" content="strict-origin-when-cross-origin">
                <style>
                    html, body {{
                        margin: 0;
                        width: 100%;
                        height: 100%;
                        background: #111827;
                    }}
                    iframe {{
                        width: 100%;
                        height: 100%;
                        border: none;
                    }}
                </style>
            </head>
            <body>
                <iframe
                    src="https://www.youtube.com/embed/{video_id}"
                    referrerpolicy="strict-origin-when-cross-origin"
                    allow="autoplay; encrypted-media; picture-in-picture"
                    allowfullscreen>
                </iframe>
            </body>
            </html>
            """

            self.youtube_player_view.setHtml(
                html,
                QUrl("https://trackboxd.app/")
            )
            self.content_stack.setCurrentWidget(self.youtube_player_page)

        else:
            app_id = result.get("id")
            if app_id:
                QDesktopServices.openUrl(
                    QUrl(f"https://store.steampowered.com/app/{app_id}/")
                )

    # --- MEDIA STATUS HANDLER (PREVENTS LOOPING) ---
    def handle_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_player.stop()  # Stop cleanly at end without looping

    def update_volume(self, value):
        self.audio_output.setVolume(value / 100.0)
        if hasattr(self, "volume_val_label"):
            self.volume_val_label.setText(f"{value}%")
        if hasattr(self, "music_volume_value"):
            self.music_volume_value.setText(f"{value}%")
        # Keep both volume sliders synchronized because they control one player.
        for slider_name in ("volume_slider", "music_volume_slider"):
            slider = getattr(self, slider_name, None)
            if slider is not None and slider.value() != value:
                slider.blockSignals(True)
                slider.setValue(value)
                slider.blockSignals(False)

    def search_youtube_video(self):
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(
                self, "Warning", "Please enter a title to search."
            )
            return

        self.status_label.setText(
            "Fetching stream and release details..."
        )
        self.status_label.setStyleSheet("color: #10b981;")

        self.fetch_thread = YTFetchThread(query)
        self.fetch_thread.finished_signal.connect(self.on_yt_fetch_success)
        self.fetch_thread.error_signal.connect(self.on_yt_fetch_error)
        self.fetch_thread.start()

    def on_yt_fetch_success(self, stream_url, title, description):
        self.status_label.setText(f"Playing: {title}")
        self.status_label.setStyleSheet("color: #10b981;")

        self.media_title_input.setText(title)
        self.about_text.setText(description)

        self.media_player.setSource(QUrl(stream_url))
        self.media_player.play()

    def on_yt_fetch_error(self, err_msg):
        self.status_label.setText("Search failed.")
        self.status_label.setStyleSheet("color: #f87171;")
        QMessageBox.warning(self, "Search Error", f"Error details:\n{err_msg}")

    def save_review(self):
        media_title = self.media_title_input.text().strip()
        comment = self.review_input.toPlainText().strip()
        rating = self.rating_combo.currentData()

        if not media_title:
            QMessageBox.warning(
                self,
                "Warning",
                "Please search for a music video first to log a review.",
            )
            return

        if not comment:
            QMessageBox.warning(
                self, "Warning", "Please write your review comment."
            )
            return

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (user_id, media_title, rating, comment) VALUES (?, ?, ?, ?)",
            (self.current_user_id, media_title, rating, comment),
        )
        conn.commit()
        conn.close()

        self.review_input.clear()
        self.load_reviews()

    def load_reviews(self):
        self.name_display.setText(self.current_username)
        self.reviews_table.setRowCount(0)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT users.username, reviews.media_title, reviews.rating, reviews.comment 
            FROM reviews 
            JOIN users ON reviews.user_id = users.id
            ORDER BY reviews.id DESC
        """
        )
        rows = cursor.fetchall()
        conn.close()

        for row_idx, row_data in enumerate(rows):
            self.reviews_table.insertRow(row_idx)
            for col_idx, cell_data in enumerate(row_data):
                val = "★" * cell_data if col_idx == 2 else str(cell_data)
                self.reviews_table.setItem(
                    row_idx, col_idx, QTableWidgetItem(val)
                )

    def handle_logout(self):
        self.media_player.stop()
        self.current_user_id = None
        self.current_username = ""
        self.setCurrentIndex(0)

    # --- TRACKBOXD SLATE & SILVER DESIGN SYSTEM ---
    def apply_professional_stylesheet(self):
        self.setStyleSheet(
            """
            QStackedWidget, QWidget#MainScreen {
                background-color: #111820;
            }
            QWidget {
                color: #E5EAF0;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 13px;
            }
            QWidget#ContentArea, QWidget#ScrollContent {
                background: transparent;
            }
            QFrame#Sidebar {
                background-color: #19232E;
                border: 1px solid #2C3947;
                border-radius: 20px;
            }
            #SidebarBrand {
                color: #F2F5F8;
                font-size: 21px;
                font-weight: 900;
                letter-spacing: 2px;
                background: transparent;
            }
            #SidebarCaption, #SidebarSection {
                color: #8291A1;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1.5px;
                background: transparent;
            }
            #SidebarSection { margin-top: 8px; }
            QPushButton#NavButton {
                text-align: left;
                color: #AEBAC7;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 11px 12px;
                font-weight: 600;
            }
            QPushButton#NavButton:hover {
                color: #F4F6F8;
                background-color: #263442;
                border-color: #354657;
            }
            QPushButton#NavButton[active="true"] {
                color: #F5F7FA;
                background-color: #304357;
                border: 1px solid #52677C;
            }
            QPushButton#SidebarLogout {
                color: #D5DDE5;
                background-color: #222F3C;
                border: 1px solid #3A4A5A;
                border-radius: 10px;
                padding: 10px;
                text-align: left;
            }
            QPushButton#SidebarLogout:hover {
                background-color: #304052;
                border-color: #718397;
            }
            #UserPill {
                color: #E2E8EF;
                background-color: #253342;
                border: 1px solid #405164;
                border-radius: 10px;
                padding: 9px;
                font-weight: 600;
            }
            #PageTitle {
                color: #F2F5F8;
                font-size: 27px;
                font-weight: 750;
                background: transparent;
            }
            #SectionKicker, #HeroKicker {
                color: #91A3B5;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1.6px;
                background: transparent;
            }
            QFrame#HeroCard {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #35495D, stop: 0.55 #293B4D, stop: 1 #202D3A
                );
                border: 1px solid #526579;
                border-top: 1px solid #718397;
                border-radius: 18px;
            }
            #HeroTitle {
                color: #FFFFFF;
                font-size: 29px;
                font-weight: 800;
                background: transparent;
            }
            #HeroDescription {
                color: #C3CDD7;
                font-size: 13px;
                background: transparent;
            }
            #HeroMonogram {
                color: rgba(238, 243, 248, 175);
                background-color: rgba(220, 230, 240, 22);
                border: 1px solid rgba(230, 238, 246, 75);
                border-radius: 56px;
                font-size: 34px;
                font-weight: 800;
            }
            QFrame#ProCard, QFrame#AuthCard {
                background-color: #1B2631;
                border: 1px solid #344250;
                border-top: 1px solid #566777;
                border-radius: 16px;
            }
            #BrandLogoAuth {
                color: #F2F5F8;
                font-size: 27px;
                font-weight: 900;
                letter-spacing: 3px;
                background: transparent;
            }
            #BrandSubAuth {
                color: #AAB7C4;
                font-size: 12px;
                background: transparent;
            }
            QPushButton#PrimaryLogBtn {
                color: #F7F9FB;
                background-color: #536B82;
                border: 1px solid #8295A8;
                border-top: 1px solid #AAB8C5;
                border-radius: 10px;
                padding: 11px 18px;
                font-weight: 750;
            }
            QPushButton#PrimaryLogBtn:hover {
                background-color: #647E96;
                border-color: #C0CBD5;
            }
            QPushButton#SecondaryBtn {
                color: #C9D3DC;
                background-color: #222F3B;
                border: 1px solid #3D4D5C;
                border-radius: 9px;
                padding: 10px 14px;
            }
            QPushButton#SecondaryBtn:hover {
                color: #FFFFFF;
                background-color: #354657;
                border-color: #718397;
            }
            QFrame#ReleasePanel {
                background-color: #202C38;
                border: 1px solid #3A4A59;
                border-radius: 12px;
            }
            #CardHeader {
                color: #F0F3F6;
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }
            #SubText {
                color: #AAB6C2;
                font-size: 12px;
                background: transparent;
            }
            #StatusPill {
                color: #C5D0DA;
                background-color: #263543;
                border: 1px solid #405365;
                border-radius: 10px;
                padding: 7px 10px;
                font-size: 11px;
            }
            #FieldLabel {
                color: #9EADBB;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1px;
                background: transparent;
            }
            QLineEdit, QTextEdit, QComboBox {
                color: #E9EEF3;
                background-color: #121B24;
                border: 1px solid #3A4958;
                border-radius: 9px;
                padding: 10px 12px;
                selection-background-color: #526A82;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 1px solid #8A9BAC;
                background-color: #17232E;
            }
            QLineEdit:read-only {
                color: #AEBAC6;
                background-color: #19242E;
            }
            QLineEdit::placeholder, QTextEdit::placeholder {
                color: #718091;
            }
            QPushButton {
                color: #E8EDF2;
                background-color: #2A3947;
                border: 1px solid #4B5D6F;
                border-top: 1px solid #718397;
                border-radius: 9px;
                padding: 10px 15px;
                font-weight: 650;
            }
            QPushButton:hover {
                background-color: #394C5E;
                border-color: #8A9BAC;
            }
            QPushButton:pressed {
                background-color: #202D39;
            }
            QPushButton#PrimaryButton, QPushButton#HeroButton {
                color: #F7F9FB;
                background-color: #536B82;
                border: 1px solid #8295A8;
                border-top: 1px solid #AAB8C5;
                border-radius: 10px;
                padding: 11px 18px;
                font-weight: 750;
            }
            QPushButton#PrimaryButton:hover, QPushButton#HeroButton:hover {
                background-color: #647E96;
                border-color: #C0CBD5;
            }
            QPushButton#ControlButton {
                color: #C9D2DB;
                background-color: #222F3B;
                border: 1px solid #3D4D5C;
                border-radius: 8px;
                padding: 8px 12px;
            }
            QPushButton#ControlButton:hover {
                color: #FFFFFF;
                background-color: #354657;
                border-color: #718397;
            }
            QVideoWidget {
                background-color: #080D12;
                border: 1px solid #465564;
                border-radius: 12px;
            }
            QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #17212B;
                width: 9px;
                margin: 2px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #586A7C;
                border-radius: 4px;
                min-height: 28px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8293A3;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: #101820;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #8295A8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #E6EBF0;
                border: 1px solid #9AA9B7;
                width: 13px;
                height: 13px;
                margin: -5px 0;
                border-radius: 6px;
            }
            QTableWidget {
                color: #DCE3E9;
                background-color: #151F29;
                alternate-background-color: #1D2934;
                gridline-color: #2E3B48;
                border: 1px solid #394957;
                border-radius: 10px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QHeaderView::section {
                color: #B9C4CE;
                background-color: #263442;
                border: none;
                border-bottom: 1px solid #465665;
                padding: 10px 8px;
                font-size: 10px;
                font-weight: 800;
            }
            """
        )


if __name__ == "__main__":
    print("STEP 1: Starting database")
    init_db()

    print("STEP 2: Starting application")
    app = QApplication(sys.argv)

    print("STEP 3: Creating TRACKBOXD")
    window = TrackboxdApp()

    print("STEP 4: Showing window")
    window.show()

    print("STEP 5: Entering application loop")
    sys.exit(app.exec())
