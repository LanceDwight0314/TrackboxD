TRACKBOXD - MEDIA AND ENTERTAINMENT APP

FILES
- Trackboxd_MediaHub.py : main Python application
- requirements.txt      : required Python packages

1. INSTALL PYTHON PACKAGES
Open Command Prompt in the folder containing these files and run:

    py -m pip install -r requirements.txt

2. SET UP THE YOUTUBE API KEY
- Open https://console.cloud.google.com/
- Create/select a Google Cloud project.
- Enable YouTube Data API v3.
- Create an API key under APIs & Services > Credentials.
- Open Trackboxd_MediaHub.py in VS Code.
- Find YOUTUBE_API_KEY near the top of the file.
- Replace PASTE_YOUR_YOUTUBE_API_KEY_HERE with your API key.

Example:
YOUTUBE_API_KEY = "AIza...your-key..."

Restrict the key in Google Cloud Console to YouTube Data API v3 and set quota limits.
Do not upload your API key publicly to GitHub.

3. RUN THE APPLICATION
In Command Prompt, run:

    py Trackboxd_MediaHub.py

4. HOW TO USE
- Register an account, then log in.
- YouTube tab: search and double-click a result. The video plays inside the app.
- Music Player tab: add local audio files and double-click a track to play it.
- Guess the Song tab: add at least four audio files with their correct titles and artists.
  Select 3, 5, or 10 seconds and start the quiz.
- Reviews tab: save and view media reviews.

NOTES
- The app uses SQLite and creates trackboxd.db automatically in the same working folder.
- If an older trackboxd.db exists, the app adds the video_id column to watch_history when needed.
- The Guess the Song game uses local audio files that you have permission to use.
- YouTube playback uses the official embedded player. Some videos may disallow embedding.
- The first run requires an internet connection for YouTube search and video playback.
