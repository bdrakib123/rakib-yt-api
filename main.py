import os
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl


app = FastAPI(
    title="VaCh yt-dlp + FFmpeg API",
    version="2.5.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MediaRequest(BaseModel):
    url: HttpUrl
    quality: str = "best"
    audio_only: bool = False


# ============================================================
# YOUTUBE COOKIES
# ============================================================

def get_cookie_source():
    """
    Priority:
    1. YOUTUBE_COOKIES environment variable
    2. Local cookie.txt
    3. No cookies
    """

    env_cookies = os.environ.get(
        "YOUTUBE_COOKIES",
        ""
    ).strip()

    if env_cookies:
        return ("env", env_cookies)

    local_cookie = Path("/app/cookie.txt")

    if not local_cookie.exists():
        local_cookie = Path("cookie.txt")

    if local_cookie.exists():
        return ("file", local_cookie)

    return (None, None)


def create_cookie_file(temp_dir: Path):
    """
    Create/use a cookie file for yt-dlp.

    Environment variable has priority over cookie.txt.
    """

    source_type, source = get_cookie_source()

    if source_type == "env":
        cookie_file = temp_dir / "cookies.txt"

        cookie_file.write_text(
            source,
            encoding="utf-8"
        )

        return cookie_file

    if source_type == "file":
        return source

    return None


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def base_ydl_opts(temp_dir: Path) -> dict:

    opts = {
        "quiet": True,
        "no_warnings": False,

        # YouTube JS challenge support
        "js_runtimes": {
            "node": {}
        },

        # yt-dlp EJS components
        "remote_components": {
            "ejs": ["github"]
        },

        "retries": 3,
        "fragment_retries": 5,

        "noplaylist": True,

        "nocheckcertificate": False,
    }

    cookie_file = create_cookie_file(temp_dir)

    if cookie_file:
        opts["cookiefile"] = str(cookie_file)

    return opts


def info_ydl_opts(temp_dir: Path) -> dict:

    opts = base_ydl_opts(temp_dir)

    opts["skip_download"] = True

    return opts


def download_ydl_opts(temp_dir: Path) -> dict:

    return base_ydl_opts(temp_dir)


# ============================================================
# FORMAT
# ============================================================

def build_video_format(quality: str) -> str:

    quality = str(
        quality
    ).lower().strip()

    if quality.endswith("p"):
        quality = quality[:-1]

    if quality.isdigit():

        height = int(quality)

        if height <= 0:
            raise ValueError(
                "Quality must be a positive height."
            )

        return (
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]"
        )

    return "bestvideo+bestaudio/best"


# ============================================================
# FIND DOWNLOADED FILE
# ============================================================

def find_downloaded_file(
    temp_dir: Path,
    audio_only: bool
) -> Path:

    if audio_only:
        candidates = list(
            temp_dir.glob("*")
        )

    else:
        candidates = list(
            temp_dir.glob("*.mp4")
        )

    candidates = [
        p for p in candidates
        if p.is_file()
    ]

    if not candidates:

        candidates = [
            p for p in temp_dir.glob("*")
            if p.is_file()
        ]

    if not candidates:

        raise RuntimeError(
            "Downloaded file was not created."
        )

    return max(
        candidates,
        key=lambda p: p.stat().st_mtime
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
def health():

    source_type, _ = get_cookie_source()

    return {
        "status": "online",
        "service": "yt-dlp + FFmpeg API",
        "version": "2.5.0",

        "youtube_js_runtime": "node",
        "youtube_ejs": True,

        "youtube_client_mode": "yt-dlp-default",
        "youtube_po_token_forced": False,

        "youtube_cookies": bool(
            source_type
        ),

        "youtube_cookie_source": (
            source_type or "none"
        ),

        "bgutil_plugin": (
            "installed-but-not-forced"
        ),
    }


# ============================================================
# INFO
# ============================================================

@app.post("/info")
def get_info(
    request: MediaRequest
):

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="vach_info_"
        )
    )

    try:

        opts = info_ydl_opts(
            temp_dir
        )

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info = ydl.extract_info(
                str(request.url),
                download=False
            )

        formats = []

        for f in info.get(
            "formats",
            []
        ):

            height = f.get(
                "height"
            )

            vcodec = f.get(
                "vcodec"
            )

            ext = f.get(
                "ext"
            )

            if not height:
                continue

            if not vcodec or vcodec == "none":
                continue

            if ext == "mhtml":
                continue

            if (
                f.get("format_note")
                == "storyboard"
            ):
                continue

            formats.append({
                "format_id":
                    f.get("format_id"),

                "ext":
                    ext,

                "height":
                    height,

                "width":
                    f.get("width"),

                "fps":
                    f.get("fps"),

                "filesize":
                    (
                        f.get("filesize")
                        or
                        f.get(
                            "filesize_approx"
                        )
                    ),

                "vcodec":
                    vcodec,

                "acodec":
                    f.get("acodec"),

                "format_note":
                    f.get(
                        "format_note"
                    ),
            })

        seen = set()

        unique_formats = []

        for item in formats:

            key = (
                item["height"],
                item["ext"],
                item["vcodec"],
                item["acodec"],
            )

            if key in seen:
                continue

            seen.add(key)

            unique_formats.append(
                item
            )

        unique_formats.sort(
            key=lambda x: (
                x["height"] or 0,
                x["width"] or 0
            )
        )

        return {
            "title":
                info.get("title"),

            "thumbnail":
                info.get("thumbnail"),

            "duration":
                info.get("duration"),

            "uploader":
                info.get("uploader"),

            "webpage_url":
                info.get(
                    "webpage_url"
                ),

            "formats":
                unique_formats,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=400,
            detail=f"ERROR: {exc}",
        ) from exc

    finally:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


# ============================================================
# DOWNLOAD
# ============================================================

@app.post("/download")
def download_media(
    request: MediaRequest
):

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="vach_"
        )
    )

    output_template = str(
        temp_dir /
        "%(title).150s.%(ext)s"
    )

    try:

        opts = download_ydl_opts(
            temp_dir
        )

        opts.update({

            "outtmpl":
                output_template,

            "restrictfilenames":
                True,
        })

        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

        if request.audio_only:

            opts.update({

                "format":
                    "bestaudio/best",

                "postprocessors": [
                    {
                        "key":
                            "FFmpegExtractAudio",

                        "preferredcodec":
                            "mp3",

                        "preferredquality":
                            "192",
                    }
                ],
            })

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        else:

            try:

                opts["format"] = (
                    build_video_format(
                        request.quality
                    )
                )

            except ValueError as exc:

                raise HTTPException(
                    status_code=400,
                    detail=f"ERROR: {exc}",
                ) from exc

            opts[
                "merge_output_format"
            ] = "mp4"

        # ----------------------------------------------------
        # DOWNLOAD
        # ----------------------------------------------------

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info = ydl.extract_info(
                str(request.url),
                download=True
            )

            ydl.prepare_filename(
                info
            )

        # ----------------------------------------------------
        # FIND FILE
        # ----------------------------------------------------

        file_path = (
            find_downloaded_file(
                temp_dir,
                request.audio_only
            )
        )

        if not file_path.exists():

            raise RuntimeError(
                "Downloaded file does not exist."
            )

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        if request.audio_only:

            media_type = "audio/mpeg"

        else:

            media_type = "video/mp4"

        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=file_path.name,
        )

    except HTTPException:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise

    except Exception as exc:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise HTTPException(
            status_code=400,
            detail=f"ERROR: {exc}",
        ) from exc


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                8000
            )
        )
    )
