import hashlib
import html
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

DB_NAME = "trackboxd.db"

WORD_CASES = (
    ("ACTOR", "A person who plays a role on stage or on screen."),
    ("ALBUM", "A collection of songs released together."),
    ("AUDIO", "What you hear when you turn up the volume."),
    ("CAMEO", "A short appearance by a recognizable performer."),
    ("CHOIR", "A group that sings together."),
    ("COMIC", "A performer who tells jokes, or a story drawn in panels."),
    ("DANCE", "Moving rhythmically to music."),
    ("DRAMA", "A story genre that often centers on serious conflict."),
    ("GENRE", "A type of movie, like comedy or horror."),
    ("LYRIC", "A line or phrase from a song."),
    ("MOVIE", "A film you might watch at the cinema."),
    ("MUSIC", "What you listen to when you play a song."),
    ("NOVEL", "A long work of fiction that might be adapted for film."),
    ("PIANO", "A keyboard instrument whose hammers strike strings."),
    ("PILOT", "An early episode made to introduce a TV series."),
    ("RADIO", "A medium that broadcasts music and spoken programs."),
    ("REMIX", "A new version of a recording using its original material."),
    ("SCENE", "A unit of action in a play or movie."),
    ("SONGS", "The individual pieces of music on an album."),
    ("STAGE", "The space where performers appear before an audience."),
    ("TRACK", "An individual recording on an album."),
    ("VIDEO", "Footage you can watch on YouTube."),
)

MOVIE_CLUES = (
    ("🦖 🦕 🏝️", "Jurassic Park", ()),
    ("🚢 🧊 💔", "Titanic", ()),
    ("🐠 🌊 🔍", "Finding Nemo", ()),
    ("🦁 👑 🌅", "The Lion King", ("Lion King",)),
    ("🐀 🧑‍🍳 🍲", "Ratatouille", ()),
    ("🧊 👭 ⛄", "Frozen", ()),
    ("🎈 🏠 ☁️", "Up", ()),
    ("🤠 🧸 🚀", "Toy Story", ()),
    ("🚗 ⚡ ⏰", "Back to the Future", ()),
    ("🕷️ 🧑 🏙️", "Spider-Man", ("Spiderman",)),
    ("👽 ☎️ 🚲", "E.T. the Extra-Terrestrial", ("ET", "E.T.")),
    ("💍 🌋 🧙", "The Lord of the Rings", ("Lord of the Rings", "LOTR")),
    ("🐼 🥋 🥟", "Kung Fu Panda", ()),
    ("🐉 🛡️ 🪽", "How to Train Your Dragon", ()),
    ("💀 🎸 🌼", "Coco", ()),
    ("🏐 🏝️ 📦", "Cast Away", ("Castaway",)),
)


def classify_letters(answer, guess):
    marks = ["absent"] * len(answer)
    remaining = {}
    for index, (target, letter) in enumerate(zip(answer, guess)):
        if target == letter:
            marks[index] = "exact"
        else:
            remaining[target] = remaining.get(target, 0) + 1
    for index, letter in enumerate(guess):
        if marks[index] == "absent" and remaining.get(letter, 0):
            marks[index] = "elsewhere"
            remaining[letter] -= 1
    return marks


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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS music_search_history (
            user_id INTEGER NOT NULL REFERENCES users(id),
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            channel TEXT NOT NULL,
            searched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, video_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_titles (
            user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL COLLATE NOCASE,
            selected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, title)
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


def youtube_watch_url(video_id):
    return "https://www.youtube.com/watch?" + urllib.parse.urlencode({"v": video_id})


def youtube_api_key(movies=True):
    names = ("YOUTUBE_MOVIES_API_KEY", "YOUTUBE_API_KEY") if movies else ("YOUTUBE_API_KEY",)
    for name in names:
        key = os.environ.get(name, "").strip()
        if key:
            return key
        if sys.platform == "win32":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as settings:
                    value, _ = winreg.QueryValueEx(settings, name)
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def get_search_history(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        rows = conn.execute(
            """
            SELECT video_id, title, channel FROM music_search_history
            WHERE user_id = ? ORDER BY searched_at DESC, rowid DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(zip(("id", "title", "channel"), row)) for row in rows]


def remember_song(user_id, song):
    with closing(sqlite3.connect(DB_NAME)) as conn, conn:
        conn.execute(
            """
            INSERT INTO music_search_history (user_id, video_id, title, channel)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, video_id) DO UPDATE SET
                title = excluded.title, channel = excluded.channel,
                searched_at = CURRENT_TIMESTAMP
            """,
            (user_id, song["id"], song["title"], song["channel"]),
        )


def format_time(milliseconds):
    minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def record_review_title(user_id, title):
    with closing(sqlite3.connect(DB_NAME)) as conn, conn:
        conn.execute(
            """
            INSERT INTO review_titles (user_id, title) VALUES (?, ?)
            ON CONFLICT(user_id, title) DO UPDATE SET selected_at = CURRENT_TIMESTAMP
            """,
            (user_id, title),
        )


def recent_review_titles(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        selected = conn.execute(
            "SELECT title FROM review_titles WHERE user_id = ? ORDER BY selected_at DESC, rowid DESC LIMIT 25",
            (user_id,),
        ).fetchall()
    titles = [row[0] for row in selected]
    titles.extend(song["title"] for song in get_search_history(user_id)[:25])
    unique = {}
    for title in titles:
        if title.strip():
            unique.setdefault(title.casefold(), title)
    return list(unique.values())


class MediaRequest(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, query, parent):
        super().__init__(parent)
        self.operation = operation
        self.query = query

    def run(self):
        try:
            data = self.fetch_media()
        except Exception:
            messages = {
                "search": "Music search failed. Check your connection and yt-dlp setup.",
                "screen_search": "Online search is unavailable. Check your connection or open a local video.",
                "video": "This video has no compatible in-app stream. Try another result or a local file.",
                "screen_video": "This video has no compatible in-app stream. Try another result or a local file.",
                "clip": "This song could not be loaded. Retry or skip to another song.",
                "clip_buffer": "This song could not be buffered. Try Next song.",
                "music_buffer": "The temporary copy could not be prepared. Try another song.",
                "screen_buffer": "The temporary copy could not be prepared. Try another result or a local video.",
            }
            self.failed.emit(messages[self.operation])
        else:
            self.succeeded.emit(data)

    def fetch_media(self):
        if self.operation in ("search", "screen_search"):
            api_results = self.search_youtube_api(movies=self.operation == "screen_search")
            if api_results is not None:
                return api_results, "YouTube Data API"

        from yt_dlp import YoutubeDL

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 12,
            "retries": 0,
            "js_runtimes": {"deno": {}, "node": {}},
        }

        if self.operation in ("search", "screen_search"):
            options["extract_flat"] = "in_playlist"
            query = f"{self.query} music video" if self.operation == "search" else self.query
            with YoutubeDL(options) as downloader:
                result = downloader.extract_info(f"ytsearch12:{query}", download=False)
            results = [
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "channel": entry.get("channel") or entry.get("uploader") or "YouTube",
                }
                for entry in result.get("entries", [])
                if entry and entry.get("id") and entry.get("title")
                and (self.operation == "screen_search" or not entry.get("duration") or entry["duration"] >= 10)
            ]
            return results, "YouTube search via yt-dlp"

        if self.operation in ("music_buffer", "screen_buffer", "clip_buffer"):
            video_id, folder = self.query
            return self.buffer_video(YoutubeDL, options, video_id, folder, audio_only=self.operation == "clip_buffer")

        # Qt needs a single source for audio and video. Skip video-only streams.
        video = self.operation != "clip"
        direct_video = "best[ext=mp4][vcodec^=avc1][acodec^=mp4a][protocol=https]"
        options["format"] = (
            f"{direct_video}/best[protocol=https]/best[protocol^=m3u8]"
            if video
            else self.clip_format()
        )
        with YoutubeDL(options) as downloader:
            result = downloader.extract_info(youtube_watch_url(self.query), download=False)
        if not result.get("url") or result.get("is_live"):
            raise ValueError("A finite, playable stream is required")
        if not video:
            return result["url"]
        sources = [result["url"]]
        for stream in reversed(result.get("formats", [])):
            has_picture_and_sound = all(stream.get(codec) not in (None, "none") for codec in ("vcodec", "acodec"))
            playable_protocol = stream.get("protocol", "") in ("https", "m3u8", "m3u8_native")
            url = stream.get("url")
            if has_picture_and_sound and playable_protocol and url and url not in sources:
                sources.append(url)
            if len(sources) == 3:
                break
        return sources

    @staticmethod
    def clip_format():
        return "bestaudio[ext=m4a][protocol=https]/bestaudio[protocol=https]/best[protocol=https]"

    def buffer_video(self, downloader_type, options, video_id, folder, audio_only=False):
        prefix = uuid.uuid4().hex
        folder = Path(folder)
        deadline = time.monotonic() + 90
        max_bytes = (40 if audio_only else 150) * 1024 * 1024

        def check_progress(update):
            if self.isInterruptionRequested() or time.monotonic() >= deadline:
                raise RuntimeError("Temporary playback cancelled or timed out")
            if update.get("downloaded_bytes", 0) > max_bytes:
                raise RuntimeError("Temporary playback size limit reached")

        options.update({
            "format": (
                self.clip_format() if audio_only else
                "best[ext=mp4][vcodec^=avc1][acodec^=mp4a][height<=480][protocol=https]"
                "/best[height<=480][protocol=https]/best[protocol=https]"
            ),
            "outtmpl": str(folder / (prefix + ".%(ext)s")),
            "max_filesize": max_bytes,
            "progress_hooks": [check_progress],
            "noprogress": True,
        })
        output = None
        try:
            check_progress({})
            with downloader_type(options) as downloader:
                info = downloader.extract_info(youtube_watch_url(video_id), download=True)
                path = Path(downloader.prepare_filename(info))
            check_progress({})
            if path.is_file() and 0 < path.stat().st_size <= max_bytes:
                output = path
                return [path.as_uri()]
            raise ValueError("No temporary media file was produced")
        finally:
            for path in folder.glob(prefix + ".*"):
                if path != output:
                    path.unlink(missing_ok=True)

    def search_youtube_api(self, movies):
        key = youtube_api_key(movies)
        if not key:
            return None
        params = {
            "part": "snippet",
            "type": "video",
            "q": self.query,
            "maxResults": 15,
            "key": key,
        }
        if not movies:
            params["videoCategoryId"] = "10"  # YouTube's Music category.
        try:
            with urllib.request.urlopen(
                "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params),
                timeout=10,
            ) as response:
                payload = json.load(response)
        except (OSError, ValueError):
            # A missing, rejected, or exhausted key need not block online search.
            return None
        return [
            {
                "id": item["id"]["videoId"],
                "title": html.unescape(item["snippet"]["title"]),
                "channel": html.unescape(item["snippet"]["channelTitle"]),
            }
            for item in payload.get("items", [])
        ]


def normalize_title(title):
    text = unicodedata.normalize("NFKC", title).casefold()
    return "".join(character for character in text if character.isalnum())


def accepted_titles(title):
    cleaned = re.sub(
        r"\s*[\[(][^\])]*(?:official|music video|lyrics|audio|visualizer)[^\])]*[\])]",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    song_title = re.split(r"\s+[-–—]\s+", cleaned, maxsplit=1)[-1]
    without_feature = re.split(r"\s*[\[(]?\s+(?:feat\.?|ft\.?)\s+", song_title, maxsplit=1, flags=re.IGNORECASE)[0]
    return {normalize_title(value) for value in (title, cleaned, song_title, without_feature)} - {""}


class PlaybackPanel(QWidget):
    def __init__(self, status, error_message):
        super().__init__()
        self.status = status
        self.error_message = error_message
        self.candidates = []
        self.fallback = None
        self.last_error = ""
        self.want_playback = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        video = QVideoWidget()
        video.setObjectName("VideoSurface")
        video.setMinimumHeight(270)
        layout.addWidget(video)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.7)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(video)
        self.player.playbackStateChanged.connect(self.on_playback_state)
        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.player.errorOccurred.connect(self.try_next_source)

        self.load_timer = QTimer(self)
        self.load_timer.setSingleShot(True)
        self.load_timer.setInterval(15000)
        self.load_timer.timeout.connect(self.try_next_source)

        timeline = QHBoxLayout()
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.player.seekableChanged.connect(self.seek.setEnabled)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("SubText")
        timeline.addWidget(self.seek, 1)
        timeline.addWidget(self.time)
        layout.addLayout(timeline)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(lambda _: self.update_position(self.player.position()))

        controls = QHBoxLayout()
        for label, action in (("Play", self.resume), ("Pause", self.pause), ("Stop", self.stop)):
            button = QPushButton(label)
            button.setObjectName("ControlButton")
            button.clicked.connect(action)
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(QLabel("Volume"))
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(70)
        volume.setFixedWidth(110)
        volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100.0))
        controls.addWidget(volume)
        layout.addLayout(controls)

    def play(self, sources, fallback=None):
        self.clear()
        self.candidates = list(sources)
        self.fallback = fallback
        self.want_playback = True
        self.load_next_source()

    def load_next_source(self):
        if not self.candidates:
            fallback = self.fallback
            error = self.last_error
            self.clear()
            if fallback:
                fallback()
            else:
                self.status.setText(f"{self.error_message} ({error})" if error else self.error_message)
            return
        source = QUrl(self.candidates.pop(0))
        self.status.setText("Loading media…")
        self.load_timer.start()
        self.player.setSource(source)
        if self.player.source() == source:
            self.player.play()

    def try_next_source(self, error=None, *_):
        failed_source = self.player.source()
        if failed_source.isEmpty() or not self.want_playback:
            return
        self.last_error = getattr(error, "name", "Playback timed out")
        self.load_timer.stop()

        def retry():
            if self.want_playback and self.player.source() == failed_source:
                self.load_next_source()

        QTimer.singleShot(0, retry)

    def on_playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.load_timer.stop()
            self.status.setText("Playing")

    def on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.load_timer.stop()
            self.status.setText("Playback finished")

    def update_position(self, position):
        duration = self.player.duration()
        self.seek.setRange(0, min(duration, 2147483647))
        if not self.seek.isSliderDown():
            self.seek.setValue(min(position, 2147483647))
        self.time.setText(f"{format_time(position)} / {format_time(duration)}")

    def resume(self):
        if not self.player.source().isEmpty():
            self.want_playback = True
            self.player.play()

    def pause(self):
        self.want_playback = False
        self.load_timer.stop()
        self.player.pause()

    def stop(self):
        self.want_playback = False
        self.load_timer.stop()
        self.player.stop()

    def clear(self):
        self.candidates.clear()
        self.fallback = None
        self.last_error = ""
        self.stop()
        self.player.setSource(QUrl())


class TrackboxdApp(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.current_user_id = None
        self.current_username = ""
        self.temp_media = tempfile.TemporaryDirectory(prefix="trackboxd-")
        self.requests = {}
        self.workers = set()
        self.closing = False
        self.quiz_song = None
        self.quiz_seen = set()
        self.quiz_finished = False
        self.quiz_heard = False
        self.clip_phase = None
        self.clip_milliseconds = 0
        self.clip_buffer_attempted = False
        self.clip_cached_url = None
        self.clip_last_position = 0

        self.login_screen = QWidget()
        self.register_screen = QWidget()
        self.main_screen = QWidget()
        for screen in (self.login_screen, self.register_screen, self.main_screen):
            self.addWidget(screen)
        self.setup_login_ui()
        self.setup_register_ui()
        self.setup_main_ui()
        self.apply_professional_stylesheet()
        self.setWindowTitle("TrackboxD")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

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
        root = QHBoxLayout(self.main_screen)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(205)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(16, 22, 16, 18)
        brand = QLabel("TRACKBOXD")
        brand.setObjectName("SidebarBrand")
        navigation.addWidget(brand)
        navigation.addSpacing(18)

        content = QWidget()
        content.setObjectName("ContentArea")
        layout = QVBoxLayout(content)
        layout.setSpacing(16)
        self.page_title = QLabel("Music & Audio")
        self.page_title.setObjectName("PageTitle")
        layout.addWidget(self.page_title)
        self.content_stack = QStackedWidget()
        layout.addWidget(self.content_stack, 1)
        root.addWidget(sidebar)
        root.addWidget(content, 1)

        self.pages = {
            "Music & Audio": self.build_media_page(self.build_music_player()),
            "Movies & TV Shows": self.build_media_page(self.build_screen_player()),
            "Games": self.build_games_page(),
            "My Reviews": self.build_reviews_page(),
        }
        self.nav_buttons = {}
        for section, page in self.pages.items():
            self.content_stack.addWidget(page)
            button = QPushButton(section)
            button.setObjectName("NavButton")
            button.setMinimumHeight(43)
            button.clicked.connect(lambda checked=False, name=section: self.show_section(name))
            self.nav_buttons[section] = button
            navigation.addWidget(button)

        navigation.addStretch()
        self.user_badge = QLabel("@guest")
        self.user_badge.setObjectName("UserPill")
        self.user_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.user_badge)
        logout = QPushButton("Log Out")
        logout.setObjectName("SidebarLogout")
        logout.clicked.connect(self.handle_logout)
        navigation.addWidget(logout)
        self.show_section("Music & Audio")

    def build_music_player(self):
        card = QFrame()
        card.setObjectName("ProCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search a song title or artist")
        self.search_input.returnPressed.connect(self.search_music)
        search_row.addWidget(self.search_input, 1)
        for label, action, style in (
            ("Search", self.search_music, "PrimaryButton"),
            ("History", self.show_music_history, "ControlButton"),
        ):
            button = QPushButton(label)
            button.setObjectName(style)
            button.clicked.connect(action)
            search_row.addWidget(button)
        layout.addLayout(search_row)
        self.status_label = QLabel("Search YouTube by song title or artist.")
        self.status_label.setObjectName("SubText")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.music_provider = QLabel()
        self.music_provider.setObjectName("SubText")
        self.music_provider.hide()
        layout.addWidget(self.music_provider)

        self.music_results = QListWidget()
        self.music_results.setObjectName("CatalogResults")
        self.music_results.setMinimumHeight(102)
        self.music_results.setMaximumHeight(135)
        self.music_results.itemActivated.connect(self.play_music)
        layout.addWidget(self.music_results)

        actions = QHBoxLayout()
        play_result = QPushButton("Play selected")
        play_result.setObjectName("PrimaryButton")
        play_result.clicked.connect(lambda: self.play_music(self.music_results.currentItem()))
        actions.addWidget(play_result)
        actions.addStretch()
        layout.addLayout(actions)

        self.about_text = QLabel("Select a result to see its title and source.")
        self.about_text.setObjectName("SubText")
        self.about_text.setTextFormat(Qt.TextFormat.PlainText)
        self.about_text.setWordWrap(True)
        layout.addWidget(self.about_text)
        self.music_playback = PlaybackPanel(
            self.status_label,
            "Playback failed inside TrackboxD. Try another song.",
        )
        layout.addWidget(self.music_playback)
        return card

    def build_screen_player(self):
        card = QFrame()
        card.setObjectName("ProCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        row = QHBoxLayout()
        self.screen_query = QLineEdit()
        self.screen_query.setPlaceholderText("Search for a movie or TV show")
        self.screen_query.returnPressed.connect(self.search_screen)
        row.addWidget(self.screen_query, 1)
        self.screen_kind = QComboBox()
        for label, keyword in (("Movies", "full movie"), ("TV Shows", "full episode")):
            self.screen_kind.addItem(label, keyword)
        row.addWidget(self.screen_kind)
        search = QPushButton("Search YouTube")
        search.setObjectName("PrimaryButton")
        search.clicked.connect(self.search_screen)
        row.addWidget(search)
        layout.addLayout(row)

        self.screen_status = QLabel("Search for a movie or TV episode, or open a local video.")
        self.screen_status.setObjectName("SubText")
        self.screen_status.setTextFormat(Qt.TextFormat.PlainText)
        self.screen_status.setWordWrap(True)
        layout.addWidget(self.screen_status)
        self.screen_provider = QLabel()
        self.screen_provider.setObjectName("SubText")
        self.screen_provider.hide()
        layout.addWidget(self.screen_provider)
        self.screen_results = QListWidget()
        self.screen_results.setObjectName("CatalogResults")
        self.screen_results.setMinimumHeight(102)
        self.screen_results.setMaximumHeight(135)
        self.screen_results.itemActivated.connect(self.play_screen_result)
        layout.addWidget(self.screen_results)

        actions = QHBoxLayout()
        play = QPushButton("Play selected")
        play.setObjectName("PrimaryButton")
        play.clicked.connect(lambda: self.play_screen_result(self.screen_results.currentItem()))
        actions.addWidget(play)
        local = QPushButton("Open local video")
        local.setObjectName("ControlButton")
        local.clicked.connect(self.open_screen_file)
        actions.addWidget(local)
        actions.addStretch()
        layout.addLayout(actions)

        self.screen_title = QLabel()
        self.screen_title.setObjectName("SubText")
        self.screen_title.setTextFormat(Qt.TextFormat.PlainText)
        self.screen_title.setWordWrap(True)
        layout.addWidget(self.screen_title)
        self.screen_playback = PlaybackPanel(
            self.screen_status,
            "Playback failed. Try another result or open a compatible local MP4 file.",
        )
        layout.addWidget(self.screen_playback)
        return card

    def build_reviews_page(self):
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setObjectName("MainScroll")
        panel = QWidget()
        panel.setObjectName("ScrollContent")
        page.setWidget(panel)
        scroll_layout = QVBoxLayout(panel)
        scroll_layout.setContentsMargins(2, 2, 10, 18)
        lower_row = QHBoxLayout()
        lower_row.setSpacing(18)
        log_card = QFrame()
        log_card.setObjectName("ProCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(22, 20, 22, 20)

        log_title = QLabel("Log & Review")
        log_title.setObjectName("CardHeader")
        log_sub = QLabel("Choose a recent title or type the name of a song, movie, or TV show.")
        log_sub.setObjectName("SubText")
        log_sub.setWordWrap(True)

        name_label = QLabel("REVIEWER")
        name_label.setObjectName("FieldLabel")
        self.name_display = QLineEdit()
        self.name_display.setReadOnly(True)

        target_label = QLabel("TITLE TO REVIEW")
        target_label.setObjectName("FieldLabel")
        self.media_title_input = QComboBox()
        self.media_title_input.setEditable(True)
        self.media_title_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.media_title_input.lineEdit().setPlaceholderText("Choose or type a title")

        rating_label = QLabel("YOUR RATING")
        rating_label.setObjectName("FieldLabel")
        self.rating_combo = QComboBox()
        for rating in range(1, 6):
            self.rating_combo.addItem(f"{rating} / 5", rating)
        self.rating_combo.setCurrentIndex(4)

        review_label = QLabel("YOUR REVIEW")
        review_label.setObjectName("FieldLabel")
        self.review_input = QTextEdit()
        self.review_input.setPlaceholderText("What stood out to you?")
        self.review_input.setFixedHeight(100)

        submit_btn = QPushButton("Save review")
        submit_btn.setObjectName("PrimaryButton")
        submit_btn.clicked.connect(self.save_review)
        self.review_status = QLabel()
        self.review_status.setObjectName("SubText")
        self.review_status.setWordWrap(True)

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
        log_layout.addWidget(self.review_status)

        reviews_card = QFrame()
        reviews_card.setObjectName("ProCard")
        reviews_layout = QVBoxLayout(reviews_card)
        reviews_layout.setContentsMargins(22, 20, 22, 20)

        reviews_title = QLabel("Your saved reviews")
        reviews_title.setObjectName("CardHeader")
        self.reviews_summary = QLabel()
        self.reviews_summary.setObjectName("SubText")
        self.reviews_summary.setWordWrap(True)

        self.reviews_table = QTableWidget(0, 3)
        self.reviews_table.setHorizontalHeaderLabels(
            ["TITLE", "RATING", "REVIEW"]
        )
        self.reviews_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.reviews_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.reviews_table.setMinimumHeight(270)
        self.reviews_table.setAlternatingRowColors(True)

        reviews_layout.addWidget(reviews_title)
        reviews_layout.addWidget(self.reviews_summary)
        reviews_layout.addSpacing(12)
        reviews_layout.addWidget(self.reviews_table)

        lower_row.addWidget(log_card, 1)
        lower_row.addWidget(reviews_card, 1)
        scroll_layout.addLayout(lower_row)

        return page

    def build_media_page(self, player_card):
        page = QScrollArea()
        page.setObjectName("MainScroll")
        page.setWidgetResizable(True)
        panel = QWidget()
        panel.setObjectName("ScrollContent")
        page.setWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 2, 10, 18)
        layout.setSpacing(16)
        layout.addWidget(player_card)
        layout.addStretch()
        return page

    def build_games_page(self):
        tabs = QTabWidget()
        tabs.setObjectName("GameTabs")
        tabs.addTab(self.build_quiz_page(), "Guess the Song")
        tabs.addTab(self.build_word_detective(), "Word Detective")
        tabs.addTab(self.build_movie_emoji_quiz(), "Movie Emoji Quiz")
        tabs.currentChanged.connect(self.on_game_changed)
        return tabs

    def on_game_changed(self, index):
        if index != 0:
            self.interrupt_quiz()
        elif self.quiz_song is None and self.current_user_id:
            self.next_quiz_song()

    def build_word_detective(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        clue = QLabel("Entertainment clue")
        clue.setObjectName("SectionKicker")
        layout.addWidget(clue)
        self.word_clue = QLabel()
        self.word_clue.setObjectName("CardHeader")
        self.word_clue.setWordWrap(True)
        layout.addWidget(self.word_clue)
        self.word_pattern = QLabel()
        self.word_pattern.setObjectName("CardHeader")
        layout.addWidget(self.word_pattern)

        key = QLabel("Green = correct position · Yellow = elsewhere · Gray = absent")
        key.setObjectName("SubText")
        key.setWordWrap(True)
        layout.addWidget(key)
        self.word_log = QTextEdit()
        self.word_log.setReadOnly(True)
        layout.addWidget(self.word_log, 1)
        self.word_status = QLabel()
        self.word_status.setWordWrap(True)
        layout.addWidget(self.word_status)

        controls = QHBoxLayout()
        self.word_input = QLineEdit()
        self.word_input.setPlaceholderText("Enter a five-letter guess")
        self.word_input.returnPressed.connect(self.check_word_guess)
        controls.addWidget(self.word_input, 1)
        self.word_submit = QPushButton("Check guess")
        self.word_submit.setObjectName("PrimaryButton")
        self.word_submit.clicked.connect(self.check_word_guess)
        controls.addWidget(self.word_submit)
        self.word_hint = QPushButton("Reveal middle letter")
        self.word_hint.setObjectName("ControlButton")
        self.word_hint.clicked.connect(self.reveal_word_hint)
        controls.addWidget(self.word_hint)
        new_case = QPushButton("New case")
        new_case.setObjectName("ControlButton")
        new_case.clicked.connect(self.new_word_case)
        controls.addWidget(new_case)
        layout.addLayout(controls)
        self.word_answer = ""
        self.new_word_case()
        return page

    def new_word_case(self):
        choices = [case for case in WORD_CASES if case[0] != self.word_answer]
        self.word_answer, clue = random.choice(choices)
        self.word_guesses = set()
        self.word_finished = False
        self.word_clue.setText(clue)
        self.word_pattern.setText(f"{self.word_answer[0]}  _  _  _  {self.word_answer[-1]}")
        self.word_hint.setEnabled(True)
        self.word_log.clear()
        self.word_input.clear()
        self.word_input.setEnabled(True)
        self.word_submit.setEnabled(True)
        self.word_status.setText("6 guesses left")

    def reveal_word_hint(self):
        if not self.word_finished:
            answer = self.word_answer
            self.word_pattern.setText(f"{answer[0]}  _  {answer[2]}  _  {answer[-1]}")
            self.word_hint.setEnabled(False)

    def check_word_guess(self):
        if self.word_finished:
            return
        guess = self.word_input.text().strip().upper()
        if not re.fullmatch("[A-Z]{5}", guess):
            self.word_status.setText("Enter exactly five letters.")
            return
        if guess in self.word_guesses:
            self.word_status.setText("You already tried that word.")
            return
        self.word_guesses.add(guess)
        self.word_input.clear()
        marks = classify_letters(self.word_answer, guess)
        colors = {"exact": "#7ee2a8", "elsewhere": "#ffd27b", "absent": "#9aabb9"}
        letters = " ".join(
            f'<span style="color: {colors[mark]}"><b>{letter}</b></span>'
            for letter, mark in zip(guess, marks)
        )
        summary = ", ".join(f"{letter} {mark}" for letter, mark in zip(guess, marks))
        self.word_log.append(f"{len(self.word_guesses)}. {letters}<br>{summary}")
        remaining = 6 - len(self.word_guesses)
        if guess == self.word_answer or not remaining:
            self.word_finished = True
            self.word_pattern.setText("  ".join(self.word_answer))
            self.word_hint.setEnabled(False)
            self.word_input.setEnabled(False)
            self.word_submit.setEnabled(False)
            message = "Case solved!" if guess == self.word_answer else "Out of guesses."
            self.word_status.setText(f"{message} The answer was {self.word_answer}.")
        else:
            noun = "guess" if remaining == 1 else "guesses"
            self.word_status.setText(f"{remaining} {noun} left")

    def build_movie_emoji_quiz(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        intro = QLabel("Guess the movie from the emojis.")
        intro.setObjectName("CardHeader")
        layout.addWidget(intro)
        self.emoji_score_label = QLabel()
        self.emoji_score_label.setObjectName("SubText")
        layout.addWidget(self.emoji_score_label)

        self.emoji_clue = QLabel()
        self.emoji_clue.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emoji_clue.setStyleSheet('font: 36px "Segoe UI Emoji";')
        self.emoji_clue.setMinimumHeight(100)
        layout.addWidget(self.emoji_clue)
        self.emoji_status = QLabel()
        self.emoji_status.setWordWrap(True)
        layout.addWidget(self.emoji_status)

        self.emoji_guess = QLineEdit()
        self.emoji_guess.setPlaceholderText("Enter the movie title")
        self.emoji_guess.returnPressed.connect(self.check_movie_guess)
        layout.addWidget(self.emoji_guess)
        controls = QHBoxLayout()
        self.emoji_check = QPushButton("Check guess")
        self.emoji_check.setObjectName("PrimaryButton")
        self.emoji_check.clicked.connect(self.check_movie_guess)
        self.emoji_reveal = QPushButton("Reveal answer")
        self.emoji_reveal.setObjectName("ControlButton")
        self.emoji_reveal.clicked.connect(lambda: self.finish_movie_round(False))
        self.emoji_next = QPushButton("Next clue")
        self.emoji_next.setObjectName("ControlButton")
        self.emoji_next.clicked.connect(self.next_movie_clue)
        for button in (self.emoji_check, self.emoji_reveal, self.emoji_next):
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        layout.addStretch()
        self.reset_movie_quiz()
        return page

    def reset_movie_quiz(self):
        self.emoji_deck = list(MOVIE_CLUES)
        random.shuffle(self.emoji_deck)
        self.emoji_score = 0
        self.emoji_round = 0
        self.next_movie_clue()

    def next_movie_clue(self):
        if not self.emoji_deck:
            self.reset_movie_quiz()
            return
        clue, self.emoji_title, aliases = self.emoji_deck.pop()
        self.emoji_answers = {normalize_title(title) for title in (self.emoji_title, *aliases)}
        self.emoji_round += 1
        self.emoji_finished = False
        self.emoji_clue.setText(clue)
        self.emoji_status.clear()
        self.emoji_guess.clear()
        self.emoji_guess.setEnabled(True)
        self.emoji_check.setEnabled(True)
        self.emoji_reveal.setEnabled(True)
        self.emoji_next.setEnabled(False)
        self.emoji_next.setText("Next clue" if self.emoji_deck else "Play again")
        self.update_movie_score()

    def check_movie_guess(self):
        if self.emoji_finished:
            return
        guess = normalize_title(self.emoji_guess.text())
        if guess in self.emoji_answers:
            self.finish_movie_round(True)
        else:
            self.emoji_status.setText("Try another title." if guess else "Enter a movie title first.")

    def finish_movie_round(self, correct):
        if self.emoji_finished:
            return
        self.emoji_finished = True
        if correct:
            self.emoji_score += 1
        prefix = "Correct!" if correct else "The answer was"
        self.emoji_status.setText(f"{prefix} {self.emoji_title}")
        self.emoji_guess.setEnabled(False)
        self.emoji_check.setEnabled(False)
        self.emoji_reveal.setEnabled(False)
        self.emoji_next.setEnabled(True)
        self.update_movie_score()

    def update_movie_score(self):
        self.emoji_score_label.setText(
            f"Clue {self.emoji_round} of {len(MOVIE_CLUES)} · Score {self.emoji_score}"
        )

    def build_quiz_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 10, 12)
        card = QFrame()
        card.setObjectName("ProCard")
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 22, 24, 22)
        form.setSpacing(12)
        title = QLabel("Guess the Song")
        title.setObjectName("CardHeader")
        form.addWidget(title)
        self.quiz_status = QLabel()
        self.quiz_status.setObjectName("SubText")
        self.quiz_status.setTextFormat(Qt.TextFormat.PlainText)
        self.quiz_status.setWordWrap(True)
        form.addWidget(self.quiz_status)

        clip_controls = QHBoxLayout()
        clip_controls.addWidget(QLabel("Clip length"))
        self.quiz_length = QComboBox()
        for seconds in (3, 5, 10):
            self.quiz_length.addItem(f"{seconds} seconds", seconds)
        clip_controls.addWidget(self.quiz_length)
        self.quiz_play = QPushButton("Play clip")
        self.quiz_play.setObjectName("PrimaryButton")
        self.quiz_play.clicked.connect(self.play_quiz_clip)
        clip_controls.addWidget(self.quiz_play)
        clip_controls.addStretch()
        form.addLayout(clip_controls)

        self.quiz_answer = QLineEdit()
        self.quiz_answer.setPlaceholderText("Enter the song title")
        self.quiz_answer.returnPressed.connect(self.check_quiz_answer)
        form.addWidget(self.quiz_answer)
        buttons = QHBoxLayout()
        self.quiz_guess = QPushButton("Check answer")
        self.quiz_guess.clicked.connect(self.check_quiz_answer)
        self.quiz_reveal = QPushButton("Reveal answer")
        self.quiz_reveal.clicked.connect(lambda: self.finish_quiz_round(False))
        self.quiz_next = QPushButton("Next song")
        self.quiz_next.clicked.connect(self.next_quiz_song)
        for button in (self.quiz_guess, self.quiz_reveal, self.quiz_next):
            button.setObjectName("ControlButton")
            buttons.addWidget(button)
        buttons.addStretch()
        form.addLayout(buttons)
        layout.addWidget(card)
        layout.addStretch()

        self.clip_player = QMediaPlayer(self)
        self.clip_audio = QAudioOutput(self)
        self.clip_audio.setVolume(self.music_playback.audio.volume())
        self.music_playback.audio.volumeChanged.connect(self.clip_audio.setVolume)
        self.clip_player.setAudioOutput(self.clip_audio)
        self.clip_player.positionChanged.connect(self.check_clip_position)
        self.clip_player.mediaStatusChanged.connect(self.on_clip_status)
        self.clip_player.errorOccurred.connect(self.on_clip_error)
        self.clip_load_timer = QTimer(self)
        self.clip_load_timer.setSingleShot(True)
        self.clip_load_timer.setInterval(12000)
        self.clip_load_timer.timeout.connect(self.on_clip_error)
        return page

    def show_section(self, section):
        if section != "Music & Audio":
            cancelled = self.cancel_request("video")
            if self.cancel_request("music_buffer") or cancelled:
                self.status_label.setText("Select Play selected to load the video.")
            self.music_playback.pause()
        if section != "Movies & TV Shows":
            cancelled = self.cancel_request("screen_video")
            if self.cancel_request("screen_buffer") or cancelled:
                self.screen_status.setText("Select Play selected to load the video.")
            self.screen_playback.pause()
        if section != "Games":
            self.interrupt_quiz()
        self.content_stack.setCurrentWidget(self.pages[section])
        self.page_title.setText(section)
        for name, button in self.nav_buttons.items():
            button.setProperty("active", name == section)
            button.style().unpolish(button)
            button.style().polish(button)
        if section == "Games" and not self.quiz_song:
            self.next_quiz_song()
        if section == "My Reviews" and self.current_user_id is not None:
            self.load_reviews()

    def start_request(self, operation, query, on_success, on_error):
        self.cancel_request(operation)
        worker = MediaRequest(operation, query, self)
        self.requests[operation] = worker
        self.workers.add(worker)

        def deliver(callback, value):
            if self.requests.get(operation) is worker:
                self.requests.pop(operation)
                callback(value)

        def release_worker():
            self.workers.discard(worker)
            if self.closing and not self.workers:
                QTimer.singleShot(0, self.close)

        worker.succeeded.connect(lambda value: deliver(on_success, value), Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(lambda value: deliver(on_error, value), Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(release_worker, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel_request(self, operation):
        worker = self.requests.pop(operation, None)
        if worker is None:
            return False
        worker.requestInterruption()
        return True

    @staticmethod
    def fill_results(listing, songs):
        listing.clear()
        for song in songs:
            item = QListWidgetItem(f"{song['title']}   ·   {song['channel']}")
            item.setData(Qt.ItemDataRole.UserRole, song)
            listing.addItem(item)
        if songs:
            listing.setCurrentRow(0)

    def search_music(self):
        query = self.search_input.text().strip()
        self.requests.pop("search", None)
        if not query:
            self.status_label.setText("Enter a song title or artist.")
            return
        self.music_provider.hide()
        self.status_label.setText("Searching for music videos…")
        self.start_request("search", query, self.show_music_results, self.status_label.setText)

    def show_music_results(self, response):
        songs, source = response
        self.music_provider.setText(f"Search source: {source}")
        self.music_provider.show()
        self.fill_results(self.music_results, songs)
        if songs:
            remember_song(self.current_user_id, songs[0])
            self.status_label.setText("Choose a song or music video to play.")
        else:
            self.status_label.setText("No matches found. Try another title or artist.")

    def show_music_history(self):
        self.requests.pop("search", None)
        self.music_provider.hide()
        songs = self.online_music_history()
        self.fill_results(self.music_results, songs)
        self.status_label.setText("Search history" if songs else "Search for a song to start your history.")

    def play_music(self, item):
        if item is None:
            return
        song = item.data(Qt.ItemDataRole.UserRole)
        self.cancel_request("music_buffer")
        remember_song(self.current_user_id, song)
        self.music_playback.clear()
        self.select_review_title(song["title"])
        self.about_text.setText(f"{song['title']}\n\n{song['channel']}")
        self.status_label.setText("Loading media.")
        self.play_online("video", "music_buffer", song["id"], self.music_playback)

    def play_online(self, operation, buffer_operation, video_id, playback):
        def prepare_copy():
            playback.status.setText("Preparing a temporary copy for in-app playback. This can take a moment.")
            self.start_request(
                buffer_operation, (video_id, self.temp_media.name),
                playback.play, playback.status.setText,
            )

        self.start_request(
            operation, video_id, lambda sources: playback.play(sources, prepare_copy),
            lambda _: prepare_copy(),
        )

    def online_music_history(self):
        history = get_search_history(self.current_user_id) if self.current_user_id else []
        return [song for song in history if not QUrl(song["id"]).isLocalFile()]

    def search_screen(self):
        title = self.screen_query.text().strip()
        if not title:
            self.screen_status.setText("Enter a movie title or TV show name.")
            return
        self.screen_results.clear()
        self.screen_provider.hide()
        self.screen_status.setText("Searching YouTube…")
        query = f"{title} {self.screen_kind.currentData()}"
        self.start_request("screen_search", query, self.show_screen_results, self.screen_status.setText)

    def show_screen_results(self, response):
        results, source = response
        self.fill_results(self.screen_results, results)
        self.screen_provider.setText(f"Search source: {source}")
        self.screen_provider.show()
        self.screen_status.setText(
            "Select a result to play." if results else "No videos found."
        )

    def play_screen_result(self, item):
        if item is None:
            return
        video = item.data(Qt.ItemDataRole.UserRole)
        self.cancel_request("screen_buffer")
        self.screen_playback.clear()
        self.screen_title.setText(f"{video['title']} · {video['channel']}")
        self.screen_status.setText("Finding an in-app stream…")
        self.play_online("screen_video", "screen_buffer", video["id"], self.screen_playback)
        self.select_review_title(video["title"])

    def open_screen_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self,
            "Open a movie or TV episode",
            "",
            "Video files (*.mp4 *.m4v *.mov *.mkv *.webm *.avi)",
        )
        if file:
            self.cancel_request("screen_video")
            self.cancel_request("screen_buffer")
            self.screen_title.setText(Path(file).stem)
            self.select_review_title(Path(file).stem)
            self.screen_playback.play([Path(file).absolute().as_uri()])

    def next_quiz_song(self):
        self.reset_clip()
        previous = self.quiz_song
        history = self.online_music_history()
        unseen = [song for song in history if song["id"] not in self.quiz_seen]
        if not unseen:
            self.quiz_seen.clear()
            unseen = [song for song in history if not previous or song["id"] != previous["id"]] or history
        self.quiz_song = random.choice(unseen) if unseen else None
        if self.quiz_song != previous:
            self.clip_cached_url = None
        self.quiz_answer.clear()
        self.quiz_finished = False
        self.quiz_heard = False
        self.update_quiz_controls()
        if self.quiz_song:
            self.quiz_seen.add(self.quiz_song["id"])
            self.quiz_status.setText("Play the clip, then enter the song title.")
        else:
            self.quiz_status.setText("Search for or play a song in Music & Audio to add it to the quiz.")

    def update_quiz_controls(self):
        active = self.quiz_song is not None and not self.quiz_finished
        busy = self.clip_phase is not None
        self.quiz_play.setEnabled(active and not busy)
        self.quiz_length.setEnabled(active and not busy)
        self.quiz_answer.setEnabled(active and not busy and self.quiz_heard)
        self.quiz_guess.setEnabled(active and not busy and self.quiz_heard)
        self.quiz_reveal.setEnabled(active)
        self.quiz_next.setEnabled(self.quiz_song is not None)

    def play_quiz_clip(self):
        if not self.quiz_song or self.quiz_finished or self.clip_phase:
            return
        self.clip_phase = "fetching"
        self.clip_buffer_attempted = bool(self.clip_cached_url)
        self.clip_milliseconds = self.quiz_length.currentData() * 1000
        self.update_quiz_controls()
        self.quiz_status.setText("Loading your clip.")
        if self.clip_cached_url:
            self.load_clip(self.clip_cached_url)
        else:
            self.start_request("clip", self.quiz_song["id"], self.load_clip, self.on_clip_error)

    def load_clip(self, url):
        self.clip_phase = "loading"
        self.clip_last_position = 0
        self.clip_load_timer.start()
        source = QUrl(url)
        self.clip_player.setSource(source)
        if self.clip_phase == "loading" and self.clip_player.source() == source:
            self.clip_player.play()

    def load_buffered_clip(self, urls):
        self.clip_cached_url = urls[0]
        self.load_clip(self.clip_cached_url)

    def on_clip_status(self, status):
        if self.clip_phase in ("loading", "playing") and status == QMediaPlayer.MediaStatus.EndOfMedia:
            end = max(self.clip_last_position, self.clip_player.position(), self.clip_player.duration())
            self.finish_clip(end >= self.clip_milliseconds)

    def check_clip_position(self, position):
        if self.clip_phase not in ("loading", "playing"):
            return
        if position > self.clip_last_position:
            self.clip_last_position = position
            self.clip_load_timer.start()
            if self.clip_phase == "loading":
                self.clip_phase = "playing"
                self.quiz_status.setText("Listen to the clip.")
        if position >= self.clip_milliseconds:
            self.finish_clip(True)

    def finish_clip(self, complete):
        self.reset_clip()
        self.quiz_heard = self.quiz_heard or complete
        self.update_quiz_controls()
        if complete:
            self.quiz_status.setText("What song did you hear?")
            self.quiz_answer.setFocus()
        else:
            self.quiz_status.setText("The full clip was unavailable. Try a shorter clip or choose Next song.")

    def on_clip_error(self, *_):
        if not self.clip_phase or self.clip_phase == "buffering":
            return
        if self.clip_buffer_attempted:
            self.clip_failed()
            return
        self.clip_buffer_attempted = True
        self.clip_phase = "buffering"
        self.clip_load_timer.stop()
        self.clip_player.stop()
        self.clip_player.setSource(QUrl())
        self.quiz_status.setText("Buffering the song for in-app playback.")
        self.start_request(
            "clip_buffer", (self.quiz_song["id"], self.temp_media.name),
            self.load_buffered_clip, self.clip_failed,
        )

    def clip_failed(self, *_):
        self.clip_cached_url = None
        self.reset_clip()
        self.quiz_status.setText("This clip could not be played. Retry or choose Next song.")

    def interrupt_quiz(self):
        if self.clip_phase:
            self.reset_clip()
            self.quiz_status.setText("Play the clip, then enter the song title.")

    def reset_clip(self):
        self.clip_phase = None
        self.cancel_request("clip")
        self.cancel_request("clip_buffer")
        self.clip_load_timer.stop()
        self.clip_player.stop()
        self.clip_player.setSource(QUrl())
        self.update_quiz_controls()


    def check_quiz_answer(self):
        if not self.quiz_song or self.quiz_finished or not self.quiz_heard:
            return
        answer = normalize_title(self.quiz_answer.text())
        if not answer:
            self.quiz_status.setText("Enter your guess first.")
            return
        if answer in accepted_titles(self.quiz_song["title"]):
            self.finish_quiz_round(True)
        else:
            self.quiz_status.setText("Try again, replay the clip, or reveal the answer.")

    def finish_quiz_round(self, correct):
        if not self.quiz_song or self.quiz_finished:
            return
        self.quiz_finished = True
        self.reset_clip()
        prefix = "Correct!" if correct else "The song was"
        self.quiz_status.setText(f"{prefix} {self.quiz_song['title']}")

    def closeEvent(self, event):
        if self.workers:
            event.ignore()
            if not self.closing:
                self.closing = True
                for operation in tuple(self.requests):
                    self.cancel_request(operation)
                self.music_playback.clear()
                self.screen_playback.clear()
                self.reset_clip()
                self.setEnabled(False)
                self.setWindowTitle("TrackboxD — closing after media requests finish")
            return
        self.music_playback.clear()
        self.screen_playback.clear()
        self.reset_clip()
        self.temp_media.cleanup()
        super().closeEvent(event)


    def select_review_title(self, title):
        title = title.strip()
        if not title or self.current_user_id is None:
            return
        record_review_title(self.current_user_id, title)
        if not self.review_input.toPlainText().strip():
            self.media_title_input.setEditText(title)
            self.review_status.clear()

    def save_review(self):
        media_title = self.media_title_input.currentText().strip()
        comment = self.review_input.toPlainText().strip()
        rating = self.rating_combo.currentData()

        if not media_title:
            QMessageBox.warning(self, "Title required", "Choose a recent title or type a title to review.")
            return
        if not comment:
            QMessageBox.warning(self, "Review required", "Write a short review before saving.")
            return

        with closing(sqlite3.connect(DB_NAME)) as conn, conn:
            conn.execute(
                "INSERT INTO reviews (user_id, media_title, rating, comment) VALUES (?, ?, ?, ?)",
                (self.current_user_id, media_title, rating, comment),
            )

        self.review_input.clear()
        self.load_reviews()
        self.review_status.setText("Review saved.")

    def load_reviews(self):
        self.name_display.setText(self.current_username)
        title = self.media_title_input.currentText()
        self.media_title_input.clear()
        self.media_title_input.addItems(recent_review_titles(self.current_user_id))
        self.media_title_input.setCurrentIndex(-1)
        self.media_title_input.setEditText(title)
        self.reviews_table.setRowCount(0)

        with closing(sqlite3.connect(DB_NAME)) as conn:
            rows = conn.execute(
                """
                SELECT media_title, rating, comment
                FROM reviews WHERE user_id = ? ORDER BY id DESC
                """,
                (self.current_user_id,),
            ).fetchall()
        if rows:
            noun = "review" if len(rows) == 1 else "reviews"
            self.reviews_summary.setText(f"{len(rows)} saved {noun}")
        else:
            self.reviews_summary.setText("Your saved reviews will appear here.")

        for row_idx, row_data in enumerate(rows):
            self.reviews_table.insertRow(row_idx)
            for col_idx, cell_data in enumerate(row_data):
                value = f"{cell_data} / 5" if col_idx == 1 else str(cell_data)
                self.reviews_table.setItem(row_idx, col_idx, QTableWidgetItem(value))

    def handle_logout(self):
        for operation in tuple(self.requests):
            self.cancel_request(operation)
        self.music_playback.clear()
        self.screen_playback.clear()
        self.music_results.clear()
        self.music_provider.hide()
        self.search_input.clear()
        self.status_label.setText("Search YouTube by song title or artist.")
        self.about_text.setText("Select a result to see its title and source.")
        self.screen_results.clear()
        self.screen_query.clear()
        self.screen_kind.setCurrentIndex(0)
        self.screen_title.clear()
        self.screen_provider.hide()
        self.screen_status.setText("Search for a movie or TV episode, or open a local video.")
        self.media_title_input.clear()
        self.review_input.clear()
        self.review_status.clear()
        self.reviews_summary.clear()
        self.reviews_table.setRowCount(0)
        self.quiz_song = None
        self.quiz_seen.clear()
        self.clip_cached_url = None
        self.quiz_answer.clear()
        self.quiz_status.clear()
        self.reset_clip()
        self.new_word_case()
        self.reset_movie_quiz()
        self.current_user_id = None
        self.current_username = ""
        self.show_section("Music & Audio")
        self.setCurrentIndex(0)

    # --- TRACKBOXD SLATE & SILVER DESIGN SYSTEM ---
    def apply_professional_stylesheet(self):
        self.setStyleSheet(
            """
            QStackedWidget, QWidget#MainScreen {
                background-color: #111820;
            }
            QTabWidget#GameTabs::pane {
                border: 1px solid #304253;
                border-radius: 8px;
                background-color: #15202B;
            }
            QTabBar::tab {
                background-color: #1B2936;
                color: #B8C6D5;
                padding: 10px 16px;
                border: 1px solid #304253;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
            }
            QTabBar::tab:selected {
                background-color: #405B70;
                color: #FFFFFF;
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
    init_db()
    app = QApplication(sys.argv)
    window = TrackboxdApp()
    window.show()
    sys.exit(app.exec())
