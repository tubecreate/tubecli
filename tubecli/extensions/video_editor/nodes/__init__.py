"""
Video Editor Workflow Nodes — Single unified node for all video operations.
"""
import os
import importlib.util

# Import BaseNode from TubeCLI
from tubecli.nodes.base_node import BaseNode, PortType

# ── Load the unified node ──
_nodes_dir = os.path.dirname(os.path.abspath(__file__))


def _load_node_class(filename, class_name):
    """Load a node class from a file in this directory."""
    filepath = os.path.join(_nodes_dir, filename)
    if not os.path.exists(filepath):
        return None
    spec = importlib.util.spec_from_file_location(f"ve_node_{filename}", filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, class_name, None)


VideoProcessingNode = _load_node_class("video_processing_node.py", "VideoProcessingNode")
VideoEffectNode = _load_node_class("video_effect_node.py", "VideoEffectNode")
FFmpegCommandNode = _load_node_class("ffmpeg_command_node.py", "FFmpegCommandNode")
VideoTrimNode = _load_node_class("video_trim_node.py", "VideoTrimNode")

# Registry for extension.get_nodes()
ALL_NODES = {}
if VideoProcessingNode:
    ALL_NODES["video_processing"] = VideoProcessingNode
if VideoEffectNode:
    ALL_NODES["video_effect"] = VideoEffectNode
if FFmpegCommandNode:
    ALL_NODES["ffmpeg_command"] = FFmpegCommandNode
if VideoTrimNode:
    ALL_NODES["video_trim"] = VideoTrimNode
