# TRACKBOXD - MEDIA AND ENTERTAINMENT APP

## FILES
- `Trackboxd_MediaHub.py` - Main Python application
- `requirements.txt` - Required Python packages

## 1. INSTALL PYTHON PACKAGES

Install Python first. Open Command Prompt in the project folder and run:

```bash
py -m pip install -r requirements.txt
```

## 2. SET UP THE YOUTUBE API KEY

TRACKBOXD uses YouTube Data API v3 for video search.

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable YouTube Data API v3.
4. Create an API key under APIs & Services > Credentials.
5. Set a Windows User environment variable:

   - Variable name: `YOUTUBE_API_KEY`
   - Variable value: Your YouTube API key

6. Restart your terminal or application.

**Security:** Never put your API key directly in the Python source code or upload it to GitHub. Restrict the key to YouTube Data API v3.

Each computer needs its own API key with this setup.

## 3. RUN THE APPLICATION

Open Command Prompt in the project folder and run:

```bash
py Trackboxd_MediaHub.py
```

## 4. HOW TO USE

- Register an account, then log in.
- YouTube: Search and double-click a result to play an available video inside the app.
- Music Player: Add local audio files and double-click a track to play it.
- Guess the Song: Add at least four audio files with their correct titles and artists. Select 3, 5, or 10 seconds and start the quiz.
- Reviews: Save and view media reviews.

## NOTES

- The app uses SQLite and automatically creates `trackboxd.db` in the working folder.
- The app may update an older database when needed.
- Use audio files that you have permission to use.
- Some YouTube videos may not allow embedded playback.
- An internet connection is required for YouTube search and playback.
