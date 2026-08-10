"""
Video Editor Extension — AI-powered video editing with Timeline, FFmpeg Processing, and Workflow Nodes.
Provides: API routes, 6 workflow nodes, AI skill, and a web-based editor UI.
"""
import os
import logging
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("VideoEditorExtension")


class VideoEditorExtension(Extension):
    name = "video_editor"
    version = "1.0.0"
    description = "AI-powered Video Editor with Timeline, FFmpeg Processing, and Workflow Nodes"
    author = "TubeCreate"

    def on_install(self):
        """Create workspace directories on install."""
        logger.info("Video Editor Extension installed")
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        projects_dir = os.path.join(data_dir, "video_editor", "projects")
        exports_dir = os.path.join(data_dir, "video_editor", "exports")
        uploads_dir = os.path.join(data_dir, "video_editor", "uploads")
        thumbs_dir = os.path.join(data_dir, "video_editor", "thumbnails")
        for d in [projects_dir, exports_dir, uploads_dir, thumbs_dir]:
            os.makedirs(d, exist_ok=True)

    def on_enable(self):
        logger.info("Video Editor Extension enabled")

    def on_disable(self):
        try:
            import sys
            ve_dir = os.path.dirname(os.path.abspath(__file__))
            # append, NOT insert(0). This directory contains generically named
            # modules (job_engine, video_engine, nodes/) and every other
            # extension ships similar names. Putting it first made it shadow
            # them: sheets_manager's `from nodes import ALL_NODES` resolved to
            # THIS extension's nodes package, so it reported video nodes as its
            # own and its own sheets_writer never registered. Appending keeps
            # this extension's own bare imports working while making it
            # impossible for it to answer someone else's.
            if ve_dir not in sys.path:
                sys.path.append(ve_dir)
            import job_engine
            job_engine.global_job_engine.stop()
        except Exception:
            pass

    def get_routes(self):
        try:
            import importlib.util

            routes_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_api.py")
            spec = importlib.util.spec_from_file_location("video_editor_ext_routes", routes_file)
            routes_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(routes_mod)

            router = getattr(routes_mod, "router", None)
            print(f"Video Editor: loaded router, {len(router.routes) if router else 0} routes")
            return router
        except Exception as e:
            print(f"FAILED to import video_editor router: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_nodes(self):
        try:
            import importlib.util

            nodes_init = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes", "__init__.py")
            spec = importlib.util.spec_from_file_location("video_editor_nodes", nodes_init)
            nodes_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(nodes_mod)

            return getattr(nodes_mod, "ALL_NODES", {})
        except Exception as e:
            print(f"FAILED to import video_editor nodes: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def get_telegram_actions(self):
        return {
            "remove_background": self._action_remove_background,
            "edit_video": self._action_edit_video,
        }

    async def _action_remove_background(self, action_data: dict, context: dict) -> str:
        """Handle remove_background action from AI chatbot."""
        import httpx
        import asyncio

        source_url = action_data.get("source_url", "")
        file_path = action_data.get("file_path", "")
        bg_type = action_data.get("bg_type", "green")
        bg_path = action_data.get("bg_path", "")

        # Determine background path
        if bg_type in ("green", "greenscreen", "transparent"):
            bg_path = "#00FF00"
        elif bg_type == "image" and bg_path:
            pass  # use provided bg_path
        elif not bg_path:
            bg_path = "#00FF00"  # default to green

        # Priority: local file_path > source_url
        # If file_path exists locally, use it directly (skip download in job_engine)
        import os
        if file_path:
            abs_path = os.path.abspath(file_path)
            if os.path.exists(abs_path):
                source_url = abs_path
            elif os.path.exists(file_path):
                source_url = file_path
        elif not source_url and file_path:
            source_url = file_path

        if not source_url:
            return "❌ Bạn muốn tách nền video nào? Hãy gửi link video hoặc tải video về trước."

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "http://localhost:5295/api/v1/video/jobs",
                    json={
                        "source_url": source_url,
                        "bg_path": bg_path,
                        "trim_no_person": True
                    }
                )

                if resp.status_code != 200:
                    try:
                        err = resp.json().get("detail", resp.text)
                    except Exception:
                        err = resp.text
                    err = str(err).replace("_", "\\_").replace("*", "\\*")
                    return f"❌ Lỗi tạo job tách nền: {err}"

                result = resp.json()
                job = result.get("job", {})
                job_id = job.get("id", "unknown")

                # Start background polling task to send file when done
                token = context.get("token", "")
                chat_id = context.get("chat_id", 0)
                if token and chat_id:
                    asyncio.create_task(self._poll_and_send_result(job_id, token, chat_id))

                return (
                    f"✅ **Đã tạo job tách nền thành công!**\n\n"
                    f"🆔 Job ID: `{job_id[:8]}`\n"
                    f"🎬 Video: {source_url[:60]}...\n"
                    f"🖼️ Nền: {'Màn xanh (Greenscreen)' if bg_path == '#00FF00' else bg_path}\n"
                    f"⏳ Đang xử lý... Bot sẽ tự gửi video khi hoàn tất!"
                )

        except Exception as e:
            return f"❌ Lỗi: {str(e)[:300]}"

    async def _action_edit_video(self, action_data: dict, context: dict) -> str:
        """Handle edit_video action (flip, blur, grayscale, etc) from AI chatbot."""
        import httpx
        import asyncio
        import os

        # Check for input file in action data first, fallback to context history
        input_file = action_data.get("input_file", "")
        if not input_file:
            # Fallback for when AI doesn't know the exact string but there is one in memory
            input_file = context.get("last_file_path", "")
            
        effect = action_data.get("effect", "flip_h")
        params = action_data.get("params", {})

        if not input_file or not os.path.exists(input_file):
            return "❌ Bạn muốn chỉnh sửa video nào? Hãy gửi tên file video hoặc tải video về trước nhé (Tốt nhất là Reply vào đoạn chat có video)."

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "http://localhost:5295/api/v1/video/effect",
                    json={
                        "input_file": input_file,
                        "effect": effect,
                        "params": params
                    }
                )

                if resp.status_code != 200:
                    err = resp.json().get("detail", resp.text) if resp.text else "Unknown error"
                    err = str(err).replace("_", "\\_").replace("*", "\\*")
                    return f"❌ Lỗi tạo tác vụ xử lý video: {err}"

                result = resp.json()
                task_id = result.get("task_id", "unknown")

                # Start background polling task to send file when done
                token = context.get("token", "")
                chat_id = context.get("chat_id", 0)
                if token and chat_id:
                    asyncio.create_task(self._poll_task_and_send_result(task_id, token, chat_id))

                return (
                    f"✅ **Đã bắt đầu xử lý tùy chỉnh video!**\n\n"
                    f"🆔 Task ID: `{task_id[:8]}`\n"
                    f"🎬 Tùy chỉnh: `{effect}`\n"
                    f"⌛ Đang xử lý nền... Bot sẽ tự gửi video lại khi xong nhé!"
                )

        except Exception as e:
            return f"❌ Lỗi kết nối đến Video API: {str(e)[:300]}"

    async def _poll_and_send_result(self, job_id: str, token: str, chat_id: int):
        """Background task: poll job status, send output video when done."""
        import httpx
        import asyncio
        import os

        max_wait = 600  # 10 minutes max
        interval = 10   # check every 10 seconds
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"http://localhost:5295/api/v1/video/jobs/{job_id}")
                    if resp.status_code != 200:
                        continue
                    
                    data = resp.json()
                    job = data.get("job", data)
                    status = job.get("status", "")
                    progress = job.get("progress", 0)

                    if status == "done":
                        output_file = job.get("output_file", "")
                        if output_file and os.path.exists(output_file):
                            # Send file via Telegram
                            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                            print(f"[VideoEditor] Job {job_id[:8]} done! Sending {output_file} ({file_size_mb:.1f} MB)")

                            if file_size_mb > 50:
                                await self._tg_send_message(token, chat_id,
                                    f"✅ **Tách nền hoàn tất!**\n\n"
                                    f"⚠️ File quá lớn ({file_size_mb:.1f} MB > 50 MB limit).\n"
                                    f"📁 Lưu tại: `{output_file}`"
                                )
                            else:
                                await self._tg_send_video(token, chat_id, output_file,
                                    f"✅ Tách nền hoàn tất! Job: {job_id[:8]}")
                        else:
                            await self._tg_send_message(token, chat_id,
                                f"✅ Job `{job_id[:8]}` hoàn tất nhưng không tìm thấy file output.")
                        return

                    elif status == "failed":
                        error = job.get("error", "Unknown error")
                        await self._tg_send_message(token, chat_id,
                            f"❌ Job tách nền `{job_id[:8]}` thất bại!\n\nLỗi: {str(error)[:300]}")
                        return

            except Exception as e:
                print(f"[VideoEditor] Poll error: {e}")

        # Timeout
        await self._tg_send_message(token, chat_id,
            f"⚠️ Job `{job_id[:8]}` đang chạy quá lâu (>10 phút). Kiểm tra tại Dashboard.")

    async def _poll_task_and_send_result(self, task_id: str, token: str, chat_id: int):
        """Background task: poll /api/v1/video/task and send output when done."""
        import httpx
        import asyncio
        import os

        max_wait = 600  # 10 minutes
        interval = 5    # check every 5 secs
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"http://localhost:5295/api/v1/video/task/{task_id}")
                    if resp.status_code != 200:
                        continue
                    
                    data = resp.json()
                    task = data.get("task", {})
                    status = task.get("status", "")

                    if status == "done":
                        output_file = task.get("result", {}).get("output_file", "")
                        if output_file and os.path.exists(output_file):
                            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
                            if file_size_mb > 50:
                                await self._tg_send_message(token, chat_id,
                                    f"✅ **Chỉnh sửa video hoàn tất!**\n\n"
                                    f"⚠️ File quá lớn ({file_size_mb:.1f} MB > 50 MB limit).\n📁 Lưu tại: `{output_file}`"
                                )
                            else:
                                await self._tg_send_video(token, chat_id, output_file,
                                    f"✅ Chỉnh sửa video xong! Task: {task_id[:8]}")
                        else:
                            await self._tg_send_message(token, chat_id, f"✅ Task `{task_id[:8]}` xong nhưng không thấy file output.")
                        return

                    elif status == "error":
                        error = task.get("error", "Unknown")
                        await self._tg_send_message(token, chat_id, f"❌ Chỉnh sửa video `{task_id[:8]}` thất bại!\n\nLỗi: {str(error)[:300]}")
                        return

            except Exception as e:
                print(f"[VideoEditor] Poll task result error: {e}")

        await self._tg_send_message(token, chat_id, f"⚠️ Xử lý video `{task_id[:8]}` đang chạy quá lâu (>10 phút).")

    async def _tg_send_message(self, token: str, chat_id: int, text: str):
        """Send a text message via Telegram."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
                )
        except Exception as e:
            print(f"[VideoEditor] TG send error: {e}")

    async def _tg_send_video(self, token: str, chat_id: int, file_path: str, caption: str = ""):
        """Send a video file via Telegram."""
        import httpx
        import os
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{token}/sendVideo",
                        data={"chat_id": str(chat_id), "caption": caption},
                        files={"video": (os.path.basename(file_path), f, "video/mp4")}
                    )
                if resp.status_code == 200 and resp.json().get("ok"):
                    print(f"[VideoEditor] ✅ Video sent to Telegram successfully")
                else:
                    # Fallback: send as document
                    with open(file_path, "rb") as f:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendDocument",
                            data={"chat_id": str(chat_id), "caption": caption},
                            files={"document": (os.path.basename(file_path), f, "application/octet-stream")}
                        )
        except Exception as e:
            print(f"[VideoEditor] TG send video error: {e}")
            await self._tg_send_message(token, chat_id,
                f"✅ Tách nền xong!\n📁 File: `{os.path.basename(file_path)}`\n⚠️ Không gửi được qua TG: {str(e)[:100]}")

