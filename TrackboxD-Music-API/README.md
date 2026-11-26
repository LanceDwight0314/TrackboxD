# TrackboxD

**ITL313-18 (SIA 2 LAB) media and entertainment project**

TrackboxD uses PyQt6 for the interface and SQLite for accounts, search history, and reviews. Passwords use salted PBKDF2-HMAC-SHA256 hashes via Python's hashlib.

## Run in PyCharm

1. Extract the ZIP. Open the folder containing Trackboxd_MediaHub.py and requirements.txt in PyCharm.
2. Choose **Create a virtual environment using requirements.txt** if prompted. If you already have a project interpreter, install the packages from requirements.txt into that interpreter.
3. Right-click Trackboxd_MediaHub.py and select **Run 'Trackboxd_MediaHub'**. Register an account and sign in.

The app stores trackboxd.db in the working directory. To reuse your accounts, reviews, and search history from an earlier version, place the database beside the script and set the PyCharm run configuration's working directory to that folder.

## Movies & TV Shows

Select **Movies** or **TV Shows**, enter a title, and search YouTube. Select a result and click **Play selected** to play it inside TrackboxD. Search results reflect the videos available on YouTube and can include clips or trailers. **Open local video** plays a video you already have, such as an MP4 movie or episode. The built-in player has a timeline, volume, and playback controls.

## Music & Audio

Search YouTube by song title or artist. Select a result and click **Play selected**. TrackboxD saves the top match from each successful search and any result you select for playback to your account's **History**.

## Games

Open **Games → Guess the Song**, choose **3**, **5**, or **10 seconds**, and play a clip from your online music history. Guess the song title or reveal the answer.

## School demo

Movies & TV Shows can play a local H.264/AAC MP4 offline. Online playback uses yt-dlp and requires internet access and a supported [Deno or Node.js runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS). If a direct video stream fails, TrackboxD tries to prepare a temporary copy and play it in the same window. This requires available disk space and can take longer than direct playback. The app removes temporary copies on normal exit.

Set YOUTUBE_API_KEY as a Windows user environment variable to enable YouTube Data API v3 searches in Music & Audio and Movies & TV Shows. Movies & TV Shows gives priority to YOUTUBE_MOVIES_API_KEY when set. Both sections show the search source and fall back to yt-dlp if their key is missing or the API request fails. These keys apply to search. Playback uses yt-dlp.
