"""
Encrypt modules ported from TikTokDownloader.
These are optional — used for advanced API auth when needed.
Imports are wrapped in try/except since they depend on original project stubs.
"""
try:
    from .aBogus import ABogus
    from .xBogus import XBogus, XBogusTikTok
    from .verifyFp import VerifyFp
except ImportError:
    ABogus = None
    XBogus = None
    XBogusTikTok = None
    VerifyFp = None
