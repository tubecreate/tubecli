"""Video Downloader Extension — the video_download workflow node.

Bundled alongside video_editor so the commonest video chain a user asks for —
fetch a clip, then trim or convert it — exists on every install rather than only
on machines that visited the Marketplace. video_download.file_path feeds
video_processing.input_file directly, so the two nodes wire without a
python_code step in between.

Unlike video_editor there was nothing to strip: this extension is MIT, 97 KB,
and its only dependency is yt-dlp (declared in requirements.txt and installed
when the extension is enabled).
"""
from tubecli.extensions.video_downloader.extension import VideoDownloaderExtension

extension_instance = VideoDownloaderExtension()
