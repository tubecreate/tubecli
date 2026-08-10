"""Video Editor Extension — FFmpeg processing and the workflow Video nodes.

Bundled rather than left in the Marketplace because the AI workflow builder's
system prompt teaches the model to use `video_processing` for any video task.
When the extension was optional, a server installed by git clone had no such
node, the model emitted it anyway, and the builder silently rewrote it to an
empty python_code box. Shipping the nodes with the product is what makes that
instruction honest.

What is deliberately NOT bundled: RobustVideoMatting, the ~29 MB model repo the
background-removal feature uses. It is GPL-3.0, and this project is MIT —
redistributing it here would put the combined work under GPL terms. It is also
99% of the extension's size and is needed by exactly one feature. video_matting
already guards its own import, so the rest works without it; installing the full
Video Editor from the Marketplace adds background removal on top.
"""
from tubecli.extensions.video_editor.extension import VideoEditorExtension

extension_instance = VideoEditorExtension()
