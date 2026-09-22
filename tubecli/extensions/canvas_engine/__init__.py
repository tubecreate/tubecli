# -*- coding: utf-8 -*-
"""Canvas Engine — bộ dựng cảnh động của dây chuyền «Diễn giải» (Content Studio) và mọi extension khác cần vẽ khung
hình bằng node-canvas.

Nằm TRONG lõi từ 22/9/2026: trước là extension riêng trên Chợ (data/extensions_external/canvas_engine, repo riêng),
nên cài Content Studio xong máy vẫn chưa có bộ dựng — task chạy 40 phút tới bước dựng mới hỏng «renderer is not
installed», và bộ dựng có hai nhịp cập nhật khác nhau với lõi. User: «sao không theo đường builtin để nó update cùng
hệ thống, vì nó hỗ trợ cho các extension khác». Gói trên Chợ (canvas_eng) vẫn còn cho máy chạy lõi cũ; máy có lõi này
thì Chợ coi nó là đã cài sẵn và không cài đè.
"""
from .extension import extension_instance  # noqa: F401
