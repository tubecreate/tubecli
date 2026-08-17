/**
 * File Manager — frontend controller for the standalone page at /file-manager.
 *
 * Endpoint prefixes are probed at boot, not hardcoded. The legacy router
 * declares prefix="/api/v1/files" while the new contract specifies
 * "/api/v1/file-manager"; whichever the server actually mounts, the page finds
 * it and says so in the console. A wrong guess would 404 every request against
 * a server that reports itself healthy, which is the exact silent failure this
 * codebase keeps shipping.
 *
 * Elements read from the HTML (all optional — a missing one degrades to a
 * console warning, never a TypeError that kills the rest of the page):
 *   #breadcrumb #fileGrid #emptyState #loading #searchInput #showHidden
 *   #quickAccess #statusInfo #statusCount #toastContainer #contextMenu
 *   #previewModal #previewTitle #previewContent #propertiesPanel
 *   #propertiesBody #viewGrid #viewList #btnRename #btnDelete #btnCopy
 *   #btnPaste #pickerBanner #btnPickerSelect
 *   #fmVolumes      — host for the volume bars (created inside #sidebar if absent)
 *   #fmToolbarExtra — host for the Scan/Cleanup/Permissions buttons
 *                     (injected into .fm-toolbar-right if absent)
 *
 * Elements created by this file if they do not exist: #toastContainer,
 * #fmVolumes, #fmOverlayHost, and a <style id="fmRuntimeStyles"> inserted as
 * the FIRST child of <head> so any linked stylesheet still wins on equal
 * specificity.
 *
 * All generated markup uses the fmx- class prefix and plain text glyphs rather
 * than Material Icons ligatures: when the Google Fonts request fails (offline
 * install), an icon-font <span> renders its ligature name as literal text and
 * shifts the layout. Text glyphs cannot do that.
 */
(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════
    // i18n — same T() / applyI18n() / data-i18n contract as the dashboard
    // ══════════════════════════════════════════════════════════════════

    /**
     * Built-in strings. The aggregated /api/v1/i18n/{lang} dictionary wins when
     * it carries a key, but it cannot be relied on: this extension's own
     * locales/*.json are nested one level ({"file_manager": {...}}) while the
     * dashboard convention is flat dotted keys, so almost nothing in them
     * resolves today. Without a local fallback the dashboard's T() returns the
     * key itself and the UI renders "fm.cleanup_apply" as a button label.
     */
    var FALLBACK = {
        vi: {
            'fm.title': 'Quản lý File',
            'fm.close': 'Đóng',
            'fm.cancel': 'Hủy',
            'fm.confirm': 'Xác nhận',
            'fm.retry': 'Thử lại',
            'fm.loading': 'Đang tải…',
            'fm.ready': 'Sẵn sàng',
            'fm.empty_folder': 'Thư mục trống',
            'fm.count_summary': '{dirs} thư mục, {files} file',
            'fm.no_selection': 'Chưa chọn mục nào.',
            'fm.copy_path': 'Chép đường dẫn',
            'fm.path_copied': 'Đã chép đường dẫn.',
            'fm.path_copy_failed': 'Trình duyệt không cho chép vào clipboard: {msg}',

            'fm.err_network': 'Không gọi được máy chủ ({url}). Kiểm tra xem TubeCLI API còn chạy không.',
            'fm.err_not_json': 'Máy chủ trả về dữ liệu không phải JSON (HTTP {status}): {body}',
            'fm.err_http': 'Lỗi HTTP {status} {statusText}',
            'fm.err_no_api': 'Không tìm thấy API File Manager. Đã thử: {tried}. Máy chủ đang chạy nhưng không có endpoint nào trong số đó.',
            'fm.err_shape': 'Máy chủ trả lời thành công nhưng thiếu trường "{field}". Nhận được: {got}',
            'fm.err_aborted': 'Đã dừng yêu cầu theo lệnh của bạn. Máy chủ có thể vẫn đang xử lý.',

            'fm.new_folder': 'Tạo thư mục',
            'fm.new_file': 'Tạo file',
            'fm.rename': 'Đổi tên',
            'fm.delete': 'Xóa',
            'fm.copy': 'Sao chép',
            'fm.cut': 'Di chuyển',
            'fm.paste': 'Dán',
            'fm.refresh': 'Làm mới',
            'fm.properties': 'Thuộc tính',
            'fm.open': 'Mở',
            'fm.prompt_folder_name': 'Tên thư mục mới',
            'fm.prompt_file_name': 'Tên file mới',
            'fm.prompt_new_name': 'Tên mới',
            'fm.name_required': 'Tên không được để trống.',
            'fm.name_invalid': 'Tên không được chứa "/" hoặc "\\", và không được là "." hay "..".',
            'fm.confirm_delete_title': 'Xóa vĩnh viễn?',
            'fm.confirm_delete_body': 'Xóa "{name}"? Thao tác này không thể hoàn tác.',
            'fm.created_folder': 'Đã tạo thư mục: {name}',
            'fm.created_file': 'Đã tạo file: {name}',
            'fm.deleted': 'Đã xóa: {name}',
            'fm.renamed': 'Đã đổi tên thành: {name}',
            'fm.clip_copy': 'Sẽ sao chép: {name} — chuyển tới thư mục đích rồi bấm Dán.',
            'fm.clip_cut': 'Sẽ di chuyển: {name} — chuyển tới thư mục đích rồi bấm Dán.',
            'fm.pasted_copy': 'Đã sao chép: {name}',
            'fm.pasted_move': 'Đã di chuyển: {name}',
            'fm.paste_same_dir': 'Nguồn và đích là cùng một thư mục — không có gì để làm.',
            'fm.binary_no_preview': 'File nhị phân — không xem trước được.',
            'fm.search_deep': 'Tìm sâu trong thư mục con (Enter)',
            'fm.search_results': 'Kết quả tìm "{q}": {n} mục',
            'fm.search_clear': 'Xóa tìm kiếm',
            'fm.search_capped': 'Máy chủ giới hạn 200 kết quả — có thể còn mục khác.',

            'fm.vol_title': 'Ổ đĩa',
            'fm.vol_usage': '{used} / {total}',
            'fm.vol_free': 'còn trống {free}',
            'fm.vol_none': 'Máy chủ không trả về ổ đĩa nào.',
            'fm.vol_failed': 'Không đọc được danh sách ổ đĩa: {msg}',
            'fm.vol_outside': 'Ổ đĩa này nằm ngoài vùng cho phép nên không mở được từ đây.',

            'fm.scan_title': 'Phân tích dung lượng',
            'fm.scan_for': 'Thư mục: {path}',
            'fm.scan_start': 'Bắt đầu quét',
            'fm.scan_running': 'Đang quét…',
            'fm.scan_done': 'Quét xong',
            'fm.scan_cancelled': 'Đã hủy quét. Không có gì bị thay đổi.',
            'fm.scan_error': 'Quét lỗi',
            'fm.scan_status_unknown': 'Máy chủ báo trạng thái lạ: "{status}"',
            'fm.scan_elapsed': 'đã chạy {t}',
            'fm.scan_counts': '{files} file · {dirs} thư mục',
            'fm.scan_files_only': '{files} file',
            'fm.scan_rate': '{n} file/giây',
            'fm.scan_current': 'Đang đọc: {p}',
            'fm.scan_percent': '~{p}% (ước tính)',
            'fm.scan_no_percent': 'Chưa ước tính được phần trăm — vẫn đang đếm.',
            'fm.scan_stalled': 'Số liệu chưa đổi trong {s} giây — nhiều khả năng đang đi vào một thư mục rất lớn.',
            'fm.scan_children': 'Thư mục con theo dung lượng',
            'fm.scan_largest': 'File lớn nhất',
            'fm.scan_none': 'Không có mục con nào.',
            'fm.scan_poll_failed': 'Mất liên lạc với tiến trình quét sau {n} lần thử: {msg}',
            'fm.scan_close_running': 'Đang quét dở. Đóng bảng này sẽ hủy tiến trình quét. Tiếp tục?',
            'fm.scan_cancel_failed': 'Không hủy được tiến trình quét: {msg}',
            'fm.scan_drill': 'Quét thư mục này',
            'fm.scan_reveal': 'Mở thư mục chứa',

            'fm.cleanup_title': 'Dọn dẹp',
            'fm.cleanup_scan': 'Tìm mục có thể dọn',
            'fm.cleanup_scanning': 'Đang tìm… ({t}). Thư mục lớn có thể mất vài phút.',
            'fm.cleanup_stop': 'Dừng chờ',
            'fm.cleanup_none': 'Không tìm thấy mục nào có thể dọn trong {p}.',
            'fm.cleanup_risk_safe': 'An toàn',
            'fm.cleanup_risk_review': 'Cần xem lại',
            'fm.cleanup_risk_unknown': 'Chưa phân loại',
            'fm.cleanup_cat_meta': '{n} mục · {b}',
            'fm.cleanup_samples': 'Ví dụ:',
            'fm.cleanup_more': '… và {n} mục khác',
            'fm.cleanup_selected': 'Đã chọn {c} nhóm · {n} mục · {b}',
            'fm.cleanup_nothing_selected': 'Chưa chọn nhóm nào.',
            'fm.cleanup_preview': 'Xem trước (không xóa gì)',
            'fm.cleanup_previewing': 'Đang dựng bản xem trước…',
            'fm.cleanup_preview_title': 'Bản xem trước — chưa xóa gì',
            'fm.cleanup_preview_result': 'Sẽ xóa {n} mục, giải phóng {b}.',
            'fm.cleanup_preview_empty': 'Bản xem trước không có mục nào để xóa.',
            'fm.cleanup_apply': 'Xóa thật',
            'fm.cleanup_applying': 'Đang xóa…',
            'fm.cleanup_confirm_title': 'Xóa vĩnh viễn {n} mục?',
            'fm.cleanup_confirm_body': 'Sẽ xóa {n} mục thuộc các nhóm: {cats}. Giải phóng khoảng {b}. Thao tác này KHÔNG thể hoàn tác và không có thùng rác.',
            'fm.cleanup_confirm_word': 'XOA',
            'fm.cleanup_confirm_hint': 'Gõ {word} vào ô dưới để mở nút xóa.',
            'fm.cleanup_confirm_review': 'Trong đó có nhóm "cần xem lại" — hãy chắc chắn bạn đã đọc danh sách phía trên.',
            'fm.cleanup_done': 'Đã xóa {n} mục, giải phóng {b}.',
            'fm.cleanup_partial': 'Đã xóa {n} mục ({b}), nhưng {f} mục thất bại.',
            'fm.cleanup_all_failed': 'Không xóa được mục nào. {f} mục thất bại.',
            'fm.cleanup_failed_list': 'Mục thất bại',
            'fm.cleanup_divergence': 'Cảnh báo: kết quả khác bản xem trước — xem trước {p} mục, lần chạy thật xử lý {a} mục. Cây thư mục đã đổi giữa hai lần.',
            'fm.cleanup_dryrun_flag': 'Máy chủ báo đây vẫn là chạy thử (dry_run=true) nên KHÔNG có gì bị xóa.',
            'fm.cleanup_deleted_list': 'Đã xóa',

            'fm.perm_title': 'Quyền truy cập',
            'fm.perm_platform': 'Nền tảng: {p}',
            'fm.perm_unsupported': 'Không hỗ trợ trên nền tảng này: {reason}',
            'fm.perm_owner': 'Chủ sở hữu',
            'fm.perm_group': 'Nhóm',
            'fm.perm_mode': 'Chế độ (octal)',
            'fm.perm_who_user': 'Chủ sở hữu',
            'fm.perm_who_group': 'Nhóm',
            'fm.perm_who_other': 'Khác',
            'fm.perm_r': 'Đọc',
            'fm.perm_w': 'Ghi',
            'fm.perm_x': 'Thực thi',
            'fm.perm_effective': 'Thực tế với tiến trình đang chạy: đọc {r} · ghi {w} · chạy {x}',
            'fm.perm_yes': 'có',
            'fm.perm_no': 'không',
            'fm.perm_recursive': 'Áp dụng cho mọi thứ bên trong',
            'fm.perm_apply': 'Áp dụng',
            'fm.perm_applying': 'Đang áp dụng…',
            'fm.perm_applied': 'Đã áp dụng: {applied}',
            'fm.perm_failed_list': 'Không áp dụng được',
            'fm.perm_special_bits': 'Chế độ hiện tại có bit đặc biệt ({bits}). Các bit này được giữ nguyên, ô tick bên dưới chỉ sửa 9 bit quyền thường.',
            'fm.perm_recursive_warn_title': 'Chế độ này sẽ khóa thư mục con',
            'fm.perm_recursive_warn_body': 'Chế độ {mode} không có quyền thực thi cho chủ sở hữu. Áp dụng đệ quy sẽ khiến không vào được thư mục con nữa — kể cả để sửa lại. Máy chủ có thể từ chối. Vẫn gửi?',
            'fm.perm_invalid_mode': 'Chế độ không hợp lệ. Nhập 3 hoặc 4 chữ số octal, ví dụ 755 hoặc 0644.',
            'fm.perm_win_readonly': 'Trên Windows, trang này chỉ đọc quyền chứ không sửa. Một ACE "deny" đặt nhầm có thể khóa vĩnh viễn thư mục mà chỉ tài khoản quản trị mới gỡ được — dịch vụ nền này không có quyền đó.',
            'fm.perm_win_owner': 'Chủ sở hữu (Windows)',
            'fm.perm_win_entries': 'Danh sách ACE',
            'fm.perm_win_no_entries': 'Máy chủ trả về danh sách ACE rỗng. Đây KHÔNG có nghĩa là không ai có quyền — nhiều khả năng đọc DACL thất bại.',
            'fm.perm_col_identity': 'Tài khoản',
            'fm.perm_col_rights': 'Quyền',
            'fm.perm_col_type': 'Loại',
            'fm.perm_col_inherited': 'Kế thừa',
            'fm.perm_reason': 'Ghi chú từ máy chủ: {reason}',

            'fm.tbl_name': 'Tên',
            'fm.tbl_size': 'Kích thước',
            'fm.tbl_count': 'Số file',
            'fm.tbl_modified': 'Sửa lúc',
            'fm.tbl_path': 'Đường dẫn',
            'fm.tbl_reason': 'Lý do',
            'fm.dir_size_unknown': 'Chưa tính',
            'fm.dir_size_scan': 'Quét để biết dung lượng',
            'fm.type_label': 'Loại',
            'fm.type_folder': 'Thư mục',
            'fm.type_file': 'File',
            'fm.created_at': 'Tạo lúc',
            'fm.extension': 'Phần mở rộng',
            'fm.root_missing': 'không tồn tại',
            'fm.preview_truncated': 'Chỉ hiển thị {n} dòng đầu.',
            'fm.media.prev': 'Trước',
            'fm.media.next': 'Sau',
            'fm.media.counter': '{i}/{n}',
            'fm.media.cannot_play': 'Trình duyệt này không phát được định dạng {ext}. Hãy tải file về và mở bằng một trình phát khác.',
            'fm.media.load_failed': 'Không tải được file. Có thể nó đã bị di chuyển hoặc xóa kể từ lần làm mới trước.',
            'fm.media.open_new_tab': 'Mở trong tab mới',
            'fm.clipboard_unavailable': 'Trình duyệt chỉ cho dùng clipboard qua HTTPS hoặc localhost.',
            'fm.cleanup_dryrun_ignored': 'Máy chủ trả về dry_run=false cho một yêu cầu xem trước. Các mục dưới đây CÓ THỂ đã bị xóa thật — hãy kiểm tra lại thư mục trước khi làm gì tiếp.',
        },
        en: {
            'fm.title': 'File Manager',
            'fm.close': 'Close',
            'fm.cancel': 'Cancel',
            'fm.confirm': 'Confirm',
            'fm.retry': 'Retry',
            'fm.loading': 'Loading…',
            'fm.ready': 'Ready',
            'fm.empty_folder': 'Empty folder',
            'fm.count_summary': '{dirs} folders, {files} files',
            'fm.no_selection': 'Nothing selected.',
            'fm.copy_path': 'Copy path',
            'fm.path_copied': 'Path copied.',
            'fm.path_copy_failed': 'The browser refused clipboard access: {msg}',

            'fm.err_network': 'Could not reach the server ({url}). Check that the TubeCLI API is still running.',
            'fm.err_not_json': 'The server returned non-JSON data (HTTP {status}): {body}',
            'fm.err_http': 'HTTP error {status} {statusText}',
            'fm.err_no_api': 'File Manager API not found. Tried: {tried}. The server is up but serves none of those.',
            'fm.err_shape': 'The server replied successfully but the "{field}" field is missing. Got: {got}',
            'fm.err_aborted': 'Request stopped at your request. The server may still be working.',

            'fm.new_folder': 'New folder',
            'fm.new_file': 'New file',
            'fm.rename': 'Rename',
            'fm.delete': 'Delete',
            'fm.copy': 'Copy',
            'fm.cut': 'Move',
            'fm.paste': 'Paste',
            'fm.refresh': 'Refresh',
            'fm.properties': 'Properties',
            'fm.open': 'Open',
            'fm.prompt_folder_name': 'New folder name',
            'fm.prompt_file_name': 'New file name',
            'fm.prompt_new_name': 'New name',
            'fm.name_required': 'The name cannot be empty.',
            'fm.name_invalid': 'The name cannot contain "/" or "\\", and cannot be "." or "..".',
            'fm.confirm_delete_title': 'Delete permanently?',
            'fm.confirm_delete_body': 'Delete "{name}"? This cannot be undone.',
            'fm.created_folder': 'Created folder: {name}',
            'fm.created_file': 'Created file: {name}',
            'fm.deleted': 'Deleted: {name}',
            'fm.renamed': 'Renamed to: {name}',
            'fm.clip_copy': 'Will copy: {name} — go to the destination folder and press Paste.',
            'fm.clip_cut': 'Will move: {name} — go to the destination folder and press Paste.',
            'fm.pasted_copy': 'Copied: {name}',
            'fm.pasted_move': 'Moved: {name}',
            'fm.paste_same_dir': 'Source and destination are the same folder — nothing to do.',
            'fm.binary_no_preview': 'Binary file — cannot preview.',
            'fm.search_deep': 'Search subfolders too (Enter)',
            'fm.search_results': 'Results for "{q}": {n} items',
            'fm.search_clear': 'Clear search',
            'fm.search_capped': 'The server caps results at 200 — there may be more.',

            'fm.vol_title': 'Volumes',
            'fm.vol_usage': '{used} / {total}',
            'fm.vol_free': '{free} free',
            'fm.vol_none': 'The server returned no volumes.',
            'fm.vol_failed': 'Could not read the volume list: {msg}',
            'fm.vol_outside': 'This volume is outside the allowed roots, so it cannot be opened here.',

            'fm.scan_title': 'Storage analysis',
            'fm.scan_for': 'Folder: {path}',
            'fm.scan_start': 'Start scan',
            'fm.scan_running': 'Scanning…',
            'fm.scan_done': 'Scan complete',
            'fm.scan_cancelled': 'Scan cancelled. Nothing was changed.',
            'fm.scan_error': 'Scan failed',
            'fm.scan_status_unknown': 'The server reported an unknown status: "{status}"',
            'fm.scan_elapsed': 'running {t}',
            'fm.scan_counts': '{files} files · {dirs} folders',
            'fm.scan_files_only': '{files} files',
            'fm.scan_rate': '{n} files/s',
            'fm.scan_current': 'Reading: {p}',
            'fm.scan_percent': '~{p}% (estimated)',
            'fm.scan_no_percent': 'No percentage yet — still counting.',
            'fm.scan_stalled': 'No change for {s} seconds — most likely inside a very large folder.',
            'fm.scan_children': 'Subfolders by size',
            'fm.scan_largest': 'Largest files',
            'fm.scan_none': 'No child entries.',
            'fm.scan_poll_failed': 'Lost contact with the scan job after {n} attempts: {msg}',
            'fm.scan_close_running': 'A scan is still running. Closing this panel will cancel it. Continue?',
            'fm.scan_cancel_failed': 'Could not cancel the scan: {msg}',
            'fm.scan_drill': 'Scan this folder',
            'fm.scan_reveal': 'Open containing folder',

            'fm.cleanup_title': 'Cleanup',
            'fm.cleanup_scan': 'Find cleanable items',
            'fm.cleanup_scanning': 'Searching… ({t}). Large folders can take minutes.',
            'fm.cleanup_stop': 'Stop waiting',
            'fm.cleanup_none': 'Nothing cleanable found in {p}.',
            'fm.cleanup_risk_safe': 'Safe',
            'fm.cleanup_risk_review': 'Needs review',
            'fm.cleanup_risk_unknown': 'Unclassified',
            'fm.cleanup_cat_meta': '{n} items · {b}',
            'fm.cleanup_samples': 'Examples:',
            'fm.cleanup_more': '… and {n} more',
            'fm.cleanup_selected': '{c} groups selected · {n} items · {b}',
            'fm.cleanup_nothing_selected': 'No group selected.',
            'fm.cleanup_preview': 'Preview (deletes nothing)',
            'fm.cleanup_previewing': 'Building the preview…',
            'fm.cleanup_preview_title': 'Preview — nothing deleted yet',
            'fm.cleanup_preview_result': 'Will delete {n} items, freeing {b}.',
            'fm.cleanup_preview_empty': 'The preview contains no items to delete.',
            'fm.cleanup_apply': 'Delete for real',
            'fm.cleanup_applying': 'Deleting…',
            'fm.cleanup_confirm_title': 'Permanently delete {n} items?',
            'fm.cleanup_confirm_body': 'This deletes {n} items from the groups: {cats}. It frees about {b}. There is NO undo and no recycle bin.',
            'fm.cleanup_confirm_word': 'DELETE',
            'fm.cleanup_confirm_hint': 'Type {word} below to unlock the delete button.',
            'fm.cleanup_confirm_review': 'This includes a "needs review" group — make sure you read the list above.',
            'fm.cleanup_done': 'Deleted {n} items, freed {b}.',
            'fm.cleanup_partial': 'Deleted {n} items ({b}), but {f} items failed.',
            'fm.cleanup_all_failed': 'Nothing was deleted. {f} items failed.',
            'fm.cleanup_failed_list': 'Failed items',
            'fm.cleanup_divergence': 'Warning: the result differs from the preview — preview listed {p} items, the real run handled {a}. The tree changed between the two.',
            'fm.cleanup_dryrun_flag': 'The server says this was still a dry run (dry_run=true), so NOTHING was deleted.',
            'fm.cleanup_deleted_list': 'Deleted',

            'fm.perm_title': 'Permissions',
            'fm.perm_platform': 'Platform: {p}',
            'fm.perm_unsupported': 'Not supported on this platform: {reason}',
            'fm.perm_owner': 'Owner',
            'fm.perm_group': 'Group',
            'fm.perm_mode': 'Mode (octal)',
            'fm.perm_who_user': 'Owner',
            'fm.perm_who_group': 'Group',
            'fm.perm_who_other': 'Other',
            'fm.perm_r': 'Read',
            'fm.perm_w': 'Write',
            'fm.perm_x': 'Execute',
            'fm.perm_effective': 'Actual for the running process: read {r} · write {w} · execute {x}',
            'fm.perm_yes': 'yes',
            'fm.perm_no': 'no',
            'fm.perm_recursive': 'Apply to everything inside',
            'fm.perm_apply': 'Apply',
            'fm.perm_applying': 'Applying…',
            'fm.perm_applied': 'Applied: {applied}',
            'fm.perm_failed_list': 'Could not apply',
            'fm.perm_special_bits': 'The current mode carries special bits ({bits}). They are preserved; the checkboxes below only edit the 9 ordinary permission bits.',
            'fm.perm_recursive_warn_title': 'This mode will lock the subfolders',
            'fm.perm_recursive_warn_body': 'Mode {mode} has no execute bit for the owner. Applying it recursively makes the subfolders impossible to enter — including to undo this. The server may refuse. Send anyway?',
            'fm.perm_invalid_mode': 'Invalid mode. Enter 3 or 4 octal digits, e.g. 755 or 0644.',
            'fm.perm_win_readonly': 'On Windows this page reads permissions but does not edit them. A misplaced deny ACE can lock a folder permanently in a way only an elevated account can undo — which a background service does not have.',
            'fm.perm_win_owner': 'Owner (Windows)',
            'fm.perm_win_entries': 'ACE list',
            'fm.perm_win_no_entries': 'The server returned an empty ACE list. This does NOT mean nobody has access — reading the DACL most likely failed.',
            'fm.perm_col_identity': 'Identity',
            'fm.perm_col_rights': 'Rights',
            'fm.perm_col_type': 'Type',
            'fm.perm_col_inherited': 'Inherited',
            'fm.perm_reason': 'Server note: {reason}',

            'fm.tbl_name': 'Name',
            'fm.tbl_size': 'Size',
            'fm.tbl_count': 'Files',
            'fm.tbl_modified': 'Modified',
            'fm.tbl_path': 'Path',
            'fm.tbl_reason': 'Reason',
            'fm.dir_size_unknown': 'Not computed',
            'fm.dir_size_scan': 'Scan to measure',
            'fm.type_label': 'Type',
            'fm.type_folder': 'Folder',
            'fm.type_file': 'File',
            'fm.created_at': 'Created',
            'fm.extension': 'Extension',
            'fm.root_missing': 'does not exist',
            'fm.preview_truncated': 'Showing only the first {n} lines.',
            'fm.media.prev': 'Previous',
            'fm.media.next': 'Next',
            'fm.media.counter': '{i}/{n}',
            'fm.media.cannot_play': 'This browser cannot play {ext} files. Download the file and open it in another player.',
            'fm.media.load_failed': 'The file could not be loaded. It may have been moved or deleted since the last refresh.',
            'fm.media.open_new_tab': 'Open in a new tab',
            'fm.clipboard_unavailable': 'The browser only allows clipboard access over HTTPS or localhost.',
            'fm.cleanup_dryrun_ignored': 'The server returned dry_run=false for a preview request. The items below MAY have been deleted for real — check the folder before doing anything else.'
        }
    };

    var _lang = 'vi';
    var _dict = {};
    var _warnedKeys = {};

    /** Locale files here are nested one level; the dashboard's are flat dotted
     *  keys. Flattening makes both shapes resolve through the same lookup. */
    function flattenDict(src, prefix, out) {
        Object.keys(src || {}).forEach(function (k) {
            var v = src[k];
            var key = prefix ? prefix + '.' + k : k;
            if (v && typeof v === 'object' && !Array.isArray(v)) flattenDict(v, key, out);
            else out[key] = String(v);
        });
        return out;
    }

    function T(key, vars) {
        var s = _dict[key];
        if (s === undefined) s = (FALLBACK[_lang] || {})[key];
        if (s === undefined) s = FALLBACK.en[key];
        if (s === undefined) {
            if (!_warnedKeys[key]) {
                _warnedKeys[key] = true;
                console.warn('[file_manager] no translation for key:', key);
            }
            s = key;
        }
        if (vars) {
            Object.keys(vars).forEach(function (k) {
                s = s.split('{' + k + '}').join(String(vars[k]));
            });
        }
        return s;
    }

    function applyI18n(root) {
        var scope = root || document;
        scope.querySelectorAll('[data-i18n]').forEach(function (el) {
            el.textContent = T(el.getAttribute('data-i18n'));
        });
        scope.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
            el.placeholder = T(el.getAttribute('data-i18n-placeholder'));
        });
        scope.querySelectorAll('[data-i18n-title]').forEach(function (el) {
            el.title = T(el.getAttribute('data-i18n-title'));
        });
        if (!root) document.documentElement.lang = _lang;
    }

    /** Never rejects: a missing translation service must not stop the page. */
    async function loadI18n() {
        var base = localStorage.getItem('tubecli_api') || window.location.origin;
        try {
            var r = await fetch(base + '/api/v1/settings/language');
            if (r.ok) {
                var d = await r.json();
                if (d && d.language) _lang = d.language;
            }
        } catch (e) {
            _lang = localStorage.getItem('tubecli_lang') || _lang;
        }
        var bust = '?v=' + Date.now();
        for (var i = 0; i < 2; i++) {
            var lang = i === 0 ? _lang : 'en';
            try {
                var rd = await fetch(base + '/api/v1/i18n/' + lang + bust);
                if (rd.ok) { _dict = flattenDict(await rd.json(), '', {}); break; }
            } catch (e) {
                console.warn('[file_manager] i18n fetch failed for', lang, e);
            }
        }
        applyI18n();
    }

    // ══════════════════════════════════════════════════════════════════
    // Small helpers
    // ══════════════════════════════════════════════════════════════════

    var UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

    function fmtBytes(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        var v = Number(n), i = 0;
        while (v >= 1024 && i < UNITS.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + ' ' + UNITS[i];
    }

    function fmtBytesExact(n) {
        if (n === null || n === undefined || isNaN(n)) return '—';
        return Number(n).toLocaleString('en-US') + ' B';
    }

    function fmtInt(n) {
        if (n === null || n === undefined || isNaN(n)) return '0';
        return Number(n).toLocaleString('en-US');
    }

    function fmtDuration(ms) {
        var s = Math.max(0, Math.floor(ms / 1000));
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        if (h) return h + 'h ' + m + 'm ' + sec + 's';
        if (m) return m + 'm ' + sec + 's';
        return sec + 's';
    }

    /** Middle-truncate so both the drive and the leaf stay readable. */
    function middleTrim(str, max) {
        var s = String(str || '');
        if (s.length <= (max || 60)) return s;
        var keep = Math.floor(((max || 60) - 1) / 2);
        return s.slice(0, keep) + '…' + s.slice(s.length - keep);
    }

    /**
     * The one place that decides what separates path components.
     *
     * It is NOT inferred from the characters in the path. "\" is a legal
     * character in a POSIX filename, so "does this string contain a backslash"
     * answered "Windows" for the real Linux directory
     * /home/bob/Downloads/my\folder: creating a subfolder built
     * …/my\folder\new, POSIX os.path.normpath keeps backslashes verbatim, and
     * the server made ONE directory literally named "my\folder\new" inside
     * Downloads. The same guess sent Up to /home/bob/Downloads/my (404) and cut
     * the breadcrumb into crumbs whose data-path led nowhere.
     *
     * `sep` is stated by the server (os.sep, from GET /roots). Until that
     * answers — and against an older build that omits the field — sepFor()
     * falls back to the *shape* of the path instead of its contents: only a
     * "C:\" / "C:/" drive prefix or a "\\host" UNC prefix can be Windows, and
     * neither shape can be produced by an absolute POSIX path, which always
     * starts with "/".
     */
    var PATH = {
        sep: null,

        sepFor: function (p) {
            if (this.sep === '\\' || this.sep === '/') return this.sep;
            var s = String(p || '');
            return (/^[A-Za-z]:[\\/]/.test(s) || /^\\\\/.test(s)) ? '\\' : '/';
        },

        isWindows: function (p) { return this.sepFor(p) === '\\'; },

        /** Windows accepts either slash, so both split a path there. POSIX must
         *  split on "/" alone or a filename containing "\" is torn into
         *  components that do not exist. */
        splitRe: function (p) { return this.isWindows(p) ? /[\\/]/ : /\//; }
    };

    function baseName(p) {
        var s = String(p || '');
        var parts = s.split(PATH.splitRe(s));
        while (parts.length && parts[parts.length - 1] === '') parts.pop();
        return parts.length ? parts[parts.length - 1] : s;
    }

    function parentOf(p) {
        var s = String(p || '');
        // On POSIX a backslash is data, so scanning for it would cut a filename
        // in half and hand back a directory that does not exist.
        var idx = PATH.isWindows(s)
            ? Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'))
            : s.lastIndexOf('/');
        if (idx < 0) return '';
        var head = s.slice(0, idx);
        // "C:\" and "/" are their own parents; stripping to "C:" would be invalid.
        if (/^[A-Za-z]:$/.test(head)) return head + '\\';
        // idx === 0 means the only separator is the leading one, so the parent
        // is the root itself. Returning '' here froze Up at the first POSIX
        // level ("/home") with no message explaining why nothing happened.
        return head || '/';
    }

    function joinPath(dir, name) {
        var d = String(dir || '');
        var sep = PATH.sepFor(d);
        var tail = d.charAt(d.length - 1);
        // Only a real separator may be reused as one. On POSIX a directory
        // whose name ends in "\" is an ordinary name, and treating that as a
        // boundary appended the child straight onto it.
        if (tail === sep || (sep === '\\' && tail === '/')) return d + name;
        return d + sep + name;
    }

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    /** DOM builder — every text value goes through textContent, so a Vietnamese
     *  filename with quotes or backslashes can never become markup. */
    function h(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                var v = attrs[k];
                if (v === null || v === undefined || v === false) return;
                if (k === 'class') node.className = v;
                else if (k === 'text') node.textContent = v;
                else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
                else if (k.slice(0, 2) === 'on' && typeof v === 'function') node.addEventListener(k.slice(2), v);
                else if (k === 'checked' || k === 'disabled' || k === 'value' || k === 'type' ||
                         k === 'placeholder' || k === 'href' || k === 'id' || k === 'title' ||
                         k === 'colSpan' || k === 'maxLength') node[k] = v;
                else node.setAttribute(k, v);
            });
        }
        (Array.isArray(children) ? children : (children ? [children] : [])).forEach(function (c) {
            if (c === null || c === undefined || c === false) return;
            node.appendChild(typeof c === 'object' && c.nodeType ? c : document.createTextNode(String(c)));
        });
        return node;
    }

    function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

    function byId(id) { return document.getElementById(id); }

    /**
     * <svg class="…"><use href="#i-…"/></svg> against the sprite in the page.
     *
     * The page used emoji for folder and file-type icons. Emoji come from the OS
     * colour font, so they sat at a different weight, size and baseline from the
     * outlined icons in the toolbar and rail — the reason the file grid looked
     * pasted in from another application. Prefers fm_actions.js's implementation
     * when it is loaded so there is one definition, and draws the same markup
     * itself when it is not.
     */
    function spriteIcon(symbolId, cls) {
        if (window.FMActions && typeof window.FMActions.icon === 'function') {
            return window.FMActions.icon(symbolId, cls || 'fm-ico');
        }
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', cls || 'fm-ico');
        svg.setAttribute('aria-hidden', 'true');
        var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        // Both spellings: href is SVG2, xlink:href keeps older engines from
        // rendering an empty box.
        use.setAttribute('href', '#' + symbolId);
        use.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', '#' + symbolId);
        svg.appendChild(use);
        return svg;
    }

    // ══════════════════════════════════════════════════════════════════
    // Runtime stylesheet
    // ══════════════════════════════════════════════════════════════════

    var RUNTIME_CSS = [
        ':root{--fmx-bg:var(--bg,#1a1a1a);--fmx-bg2:var(--bg2,#1e1e1e);--fmx-bg3:var(--bg3,#262626);',
        '--fmx-hover:var(--bg-hover,#303030);--fmx-dark:var(--bg-dark,#141414);',
        '--fmx-border:var(--border,#333);--fmx-border2:var(--border-subtle,#2a2a2a);',
        '--fmx-text:var(--text,#ededed);--fmx-text2:var(--text2,#9ca3af);--fmx-muted:var(--text-muted,#6b7280);',
        '--fmx-primary:var(--primary,#5276EB);--fmx-primary-hover:var(--primary-hover,#3d5fd4);',
        '--fmx-primary-light:var(--primary-light,rgba(82,118,235,0.12));',
        '--fmx-green:var(--green,#22c55e);--fmx-orange:var(--orange,#f59e0b);--fmx-red:var(--red,#ef4444);',
        '--fmx-purple:var(--purple,#7c5ce7);',
        '--fmx-radius:var(--radius,10px);--fmx-radius-lg:var(--radius-lg,14px);',
        '--fmx-shadow:var(--shadow-elevated,0 12px 28px -4px rgba(0,0,0,0.45));',
        '--fmx-font:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif;',
        '--fmx-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace}',

        '.fmx-overlay{position:fixed;inset:0;z-index:9000;display:flex;align-items:center;justify-content:center;',
        'background:rgba(0,0,0,.62);padding:24px;font-family:var(--fmx-font);color:var(--fmx-text)}',
        '.fmx-dialog{background:var(--fmx-bg2);border:1px solid var(--fmx-border);border-radius:var(--fmx-radius-lg);',
        'box-shadow:var(--fmx-shadow);width:min(920px,100%);max-height:100%;display:flex;flex-direction:column;overflow:hidden}',
        '.fmx-dialog.sm{width:min(520px,100%)}',
        // ── Media viewer ──
        '.fmx-dialog.xl{width:min(1400px,96vw);height:min(900px,92vh)}',
        // The stage owns the height. The default .fmx-body scrolls, which would
        // let a tall image push the controls off the bottom of the dialog
        // instead of being fitted into it.
        '.fmx-body.fmx-media-body{padding:12px 20px;overflow:hidden;display:flex;flex-direction:column}',
        '.fmx-media{flex:1 1 auto;min-height:0;display:flex;align-items:center;justify-content:center;',
        'background:var(--fmx-dark);border-radius:var(--fmx-radius);overflow:hidden}',
        '.fmx-media>img,.fmx-media>video{max-width:100%;max-height:100%;object-fit:contain;display:block}',
        '.fmx-media>audio{width:min(560px,100%)}',
        // The built-in PDF viewer paints its own light chrome, so a dark
        // backdrop behind a half-loaded page reads as a rendering fault.
        '.fmx-media>iframe{width:100%;height:100%;border:0;background:#fff}',
        '.fmx-media-nav{display:inline-flex;align-items:center;justify-content:center;padding:8px}',
        '.fmx-media-nav .fm-ico{width:18px;height:18px}',
        '.fmx-head{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--fmx-border2);flex:0 0 auto}',
        '.fmx-title{font-size:15px;font-weight:600;margin:0;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        // Holds an <svg class="fm-ico">, so it is centred as a flex box rather
        // than by line-height the way it was when the label was a "x" character.
        '.fmx-close{background:none;border:none;color:var(--fmx-text2);cursor:pointer;',
        'display:inline-flex;align-items:center;justify-content:center;',
        'padding:7px;border-radius:8px;font-family:var(--fmx-font)}',
        '.fmx-close:hover{background:var(--fmx-hover);color:var(--fmx-text)}',
        '.fmx-close .fm-ico{width:17px;height:17px}',
        '.fmx-body{padding:18px 20px;overflow:auto;flex:1 1 auto;min-height:0}',
        '.fmx-foot{display:flex;align-items:center;gap:10px;padding:14px 20px;border-top:1px solid var(--fmx-border2);flex:0 0 auto;flex-wrap:wrap}',
        '.fmx-foot .fmx-spacer{flex:1}',

        '.fmx-btn{background:var(--fmx-bg3);color:var(--fmx-text);border:1px solid var(--fmx-border);',
        'border-radius:8px;padding:8px 14px;font-size:13px;font-weight:500;cursor:pointer;font-family:var(--fmx-font);white-space:nowrap}',
        '.fmx-btn:hover:not(:disabled){background:var(--fmx-hover)}',
        '.fmx-btn:disabled{opacity:.45;cursor:not-allowed}',
        '.fmx-btn.primary{background:var(--fmx-primary);border-color:var(--fmx-primary);color:#fff}',
        '.fmx-btn.primary:hover:not(:disabled){background:var(--fmx-primary-hover)}',
        '.fmx-btn.danger{background:var(--fmx-red);border-color:var(--fmx-red);color:#fff}',
        '.fmx-btn.danger:hover:not(:disabled){filter:brightness(1.1)}',
        '.fmx-btn.ghost{background:transparent}',

        '.fmx-sec{margin-bottom:18px}',
        '.fmx-sec-title{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;',
        'color:var(--fmx-muted);margin:0 0 8px}',
        '.fmx-muted{color:var(--fmx-text2);font-size:12px}',
        '.fmx-mono{font-family:var(--fmx-mono);font-size:12px;word-break:break-all}',
        '.fmx-note{background:var(--fmx-bg3);border:1px solid var(--fmx-border);border-left:3px solid var(--fmx-primary);',
        'border-radius:8px;padding:10px 12px;font-size:12.5px;line-height:1.55;color:var(--fmx-text2);margin-bottom:12px;white-space:pre-wrap}',
        '.fmx-note.warn{border-left-color:var(--fmx-orange)}',
        '.fmx-note.err{border-left-color:var(--fmx-red);color:var(--fmx-text)}',
        '.fmx-note.ok{border-left-color:var(--fmx-green)}',

        '.fmx-bar{position:relative;height:8px;border-radius:99px;background:var(--fmx-dark);overflow:hidden}',
        '.fmx-bar-fill{height:100%;border-radius:99px;background:var(--fmx-primary);transition:width .35s ease}',
        '.fmx-bar-fill.warn{background:var(--fmx-orange)}.fmx-bar-fill.crit{background:var(--fmx-red)}',
        // Indeterminate stripe: a percentage stuck at 0 must still look alive.
        '.fmx-bar.indet:after{content:"";position:absolute;inset:0;border-radius:99px;',
        'background:linear-gradient(90deg,transparent 0%,var(--fmx-primary) 45%,var(--fmx-purple) 55%,transparent 100%);',
        'background-size:40% 100%;background-repeat:no-repeat;animation:fmxSlide 1.15s linear infinite}',
        '@keyframes fmxSlide{0%{background-position:-45% 0}100%{background-position:145% 0}}',
        '@media (prefers-reduced-motion:reduce){.fmx-bar.indet:after{animation-duration:3s}}',

        '.fmx-badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;',
        'border:1px solid transparent;white-space:nowrap}',
        '.fmx-badge.safe{background:rgba(34,197,94,.14);color:var(--fmx-green);border-color:rgba(34,197,94,.35)}',
        '.fmx-badge.review{background:rgba(245,158,11,.14);color:var(--fmx-orange);border-color:rgba(245,158,11,.35)}',
        '.fmx-badge.unknown{background:var(--fmx-bg3);color:var(--fmx-text2);border-color:var(--fmx-border)}',
        '.fmx-badge.err{background:rgba(239,68,68,.14);color:var(--fmx-red);border-color:rgba(239,68,68,.35)}',

        '.fmx-table{width:100%;border-collapse:collapse;font-size:12.5px}',
        '.fmx-table th{text-align:left;color:var(--fmx-muted);font-weight:600;font-size:11px;',
        'text-transform:uppercase;letter-spacing:.04em;padding:6px 8px;border-bottom:1px solid var(--fmx-border)}',
        '.fmx-table td{padding:6px 8px;border-bottom:1px solid var(--fmx-border2);vertical-align:top}',
        '.fmx-table td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}',
        '.fmx-scroll{max-height:280px;overflow:auto;border:1px solid var(--fmx-border2);border-radius:8px}',

        '.fmx-cat{border:1px solid var(--fmx-border);border-radius:var(--fmx-radius);padding:12px;margin-bottom:10px;background:var(--fmx-bg3)}',
        '.fmx-cat.on{border-color:var(--fmx-primary);background:var(--fmx-primary-light)}',
        '.fmx-cat-head{display:flex;align-items:flex-start;gap:10px}',
        '.fmx-cat-head input{margin-top:3px;flex:0 0 auto;width:16px;height:16px;accent-color:var(--fmx-primary)}',
        '.fmx-cat-name{font-size:13.5px;font-weight:600;display:flex;align-items:center;gap:8px;flex-wrap:wrap}',

        '.fmx-input{background:var(--fmx-dark);border:1px solid var(--fmx-border);border-radius:8px;color:var(--fmx-text);',
        'padding:8px 10px;font-size:13px;font-family:var(--fmx-mono);width:100%;box-sizing:border-box}',
        '.fmx-input:focus{outline:none;border-color:var(--fmx-primary)}',

        '.fmx-grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}',
        '.fmx-perm-box{border:1px solid var(--fmx-border);border-radius:8px;padding:10px;background:var(--fmx-bg3)}',
        '.fmx-perm-box label{display:flex;align-items:center;gap:8px;font-size:13px;padding:3px 0;cursor:pointer}',
        '.fmx-perm-box input{accent-color:var(--fmx-primary);width:15px;height:15px}',
        '.fmx-kv{display:flex;gap:10px;font-size:12.5px;padding:4px 0;border-bottom:1px solid var(--fmx-border2)}',
        '.fmx-kv b{flex:0 0 34%;color:var(--fmx-muted);font-weight:500}',
        '.fmx-kv span{flex:1;min-width:0;word-break:break-all}',

        '.fmx-vols{padding:8px 10px}',
        '.fmx-vol{padding:8px;border-radius:8px;cursor:pointer;margin-bottom:4px;border:1px solid transparent}',
        '.fmx-vol:hover{background:var(--fmx-hover);border-color:var(--fmx-border)}',
        '.fmx-vol-top{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-bottom:5px}',
        '.fmx-vol-label{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--fmx-text)}',
        '.fmx-vol-sub{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--fmx-text2);margin-top:5px}',

        '.fmx-list{list-style:none;margin:0;padding:0}',
        '.fmx-list li{padding:5px 8px;border-bottom:1px solid var(--fmx-border2);font-size:12px;',
        'font-family:var(--fmx-mono);word-break:break-all}',
        '.fmx-list li:last-child{border-bottom:none}',
        '.fmx-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}',
        '.fmx-toast-wrap{position:fixed;right:18px;bottom:18px;z-index:9500;display:flex;flex-direction:column;gap:8px;',
        'max-width:min(460px,calc(100vw - 36px));font-family:var(--fmx-font)}'
    ].join('');

    function installRuntimeStyles() {
        if (byId('fmRuntimeStyles')) return;
        var st = document.createElement('style');
        st.id = 'fmRuntimeStyles';
        st.textContent = RUNTIME_CSS;
        // First child of <head>: a later <link> stylesheet must still be able to
        // override these at equal specificity.
        if (document.head.firstChild) document.head.insertBefore(st, document.head.firstChild);
        else document.head.appendChild(st);
    }

    // ══════════════════════════════════════════════════════════════════
    // Network layer — one place where every response is checked
    // ══════════════════════════════════════════════════════════════════

    var API_ORIGIN = (localStorage.getItem('tubecli_api') || '').replace(/\/+$/, '');
    var PREFIXES = ['/api/v1/file-manager', '/api/v1/files'];

    /** Pull the server's own explanation out of whatever shape it came in. */
    function serverMessage(data, res, rawText) {
        if (data && typeof data === 'object') {
            var d = data.detail;
            if (typeof d === 'string' && d) return d;
            // FastAPI 422 returns detail as a list of validation objects.
            if (Array.isArray(d) && d.length) {
                return d.map(function (it) {
                    if (typeof it === 'string') return it;
                    var loc = Array.isArray(it.loc) ? it.loc.join('.') : '';
                    return (loc ? loc + ': ' : '') + (it.msg || JSON.stringify(it));
                }).join('\n');
            }
            if (typeof data.message === 'string' && data.message) return data.message;
            if (typeof data.error === 'string' && data.error) return data.error;
        }
        if (rawText && rawText.trim()) return middleTrim(rawText.trim(), 400);
        return T('fm.err_http', { status: res.status, statusText: res.statusText || '' });
    }

    /**
     * Every call goes through here. Rules, in order:
     *   1. A transport failure names the URL — "failed to fetch" alone tells the
     *      user nothing actionable.
     *   2. A non-JSON body is reported with its first 400 characters instead of
     *      being swallowed by a JSON.parse exception.
     *   3. !res.ok always throws carrying the server's own message.
     *   4. A 200 body of {"error": "..."} is still a failure — file_service
     *      returns that shape for "file too large" and for read errors.
     */
    async function requestJson(url, opts) {
        var full = API_ORIGIN + url;
        var res;
        try {
            res = await fetch(full, opts || {});
        } catch (e) {
            if (e && e.name === 'AbortError') {
                var abortErr = new Error(T('fm.err_aborted'));
                abortErr.aborted = true;
                throw abortErr;
            }
            throw new Error(T('fm.err_network', { url: full }) + '\n(' + (e && e.message ? e.message : e) + ')');
        }
        var text = await res.text();
        var data = null, parsed = true;
        if (text) {
            try { data = JSON.parse(text); } catch (e) { parsed = false; }
        }
        if (!res.ok) {
            var err = new Error(parsed
                ? serverMessage(data, res, text)
                : T('fm.err_not_json', { status: res.status, body: middleTrim(text, 400) }));
            err.status = res.status;
            throw err;
        }
        if (!parsed) {
            throw new Error(T('fm.err_not_json', { status: res.status, body: middleTrim(text, 400) }));
        }
        if (data && typeof data === 'object' && typeof data.error === 'string' && data.error) {
            throw new Error(data.error);
        }
        if (data && data.success === false) {
            throw new Error(serverMessage(data, res, text));
        }
        return data;
    }

    function jsonPost(url, body, signal) {
        return requestJson(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
            signal: signal
        });
    }

    /**
     * The legacy router declares prefix "/api/v1/files"; the new contract says
     * "/api/v1/file-manager". Probing means the page works whichever one the
     * server actually mounted, instead of 404-ing against a healthy server.
     * The two groups are probed separately because a second router mounted for
     * the new endpoints would leave the CRUD ones where they are.
     */
    async function probePrefix(probePath, cache) {
        if (cache.value) return { prefix: cache.value, data: null };
        var errors = [];
        for (var i = 0; i < PREFIXES.length; i++) {
            try {
                var data = await requestJson(PREFIXES[i] + probePath, {});
                cache.value = PREFIXES[i];
                return { prefix: PREFIXES[i], data: data };
            } catch (e) {
                errors.push(PREFIXES[i] + ': ' + (e.message || e).split('\n')[0]);
                if (e.status === undefined) {
                    // No HTTP status means the request never landed (server down,
                    // CORS, DNS). Trying the other prefix would fail identically
                    // and turn a connectivity problem into a bogus "API not
                    // found", sending the user to debug the wrong thing.
                    throw e;
                }
                if (e.status !== 404 && e.status !== 405) {
                    // The endpoint exists here but failed for its own reason —
                    // reporting "API not found" would hide the real cause.
                    cache.value = PREFIXES[i];
                    throw e;
                }
            }
        }
        throw new Error(T('fm.err_no_api', { tried: PREFIXES.join(', ') }) + '\n' + errors.join('\n'));
    }

    // ══════════════════════════════════════════════════════════════════
    // Toast + dialog primitives
    // ══════════════════════════════════════════════════════════════════

    function toastHost() {
        var c = byId('toastContainer');
        if (!c) {
            c = h('div', { id: 'toastContainer', class: 'fmx-toast-wrap' });
            document.body.appendChild(c);
        } else if (!c.className) {
            c.className = 'fmx-toast-wrap';
        }
        return c;
    }

    /**
     * Errors stay 9s and are click-to-dismiss, and the text wraps: the server's
     * own ValueError spans several lines ("Đường dẫn nằm ngoài vùng cho phép…"
     * plus the root list) and truncating it to one line removes the only part
     * that tells the user what to do.
     */
    function toast(msg, type) {
        var kind = type || 'info';
        var colors = { success: 'var(--fmx-green,#22c55e)', error: 'var(--fmx-red,#ef4444)', warn: 'var(--fmx-orange,#f59e0b)', info: 'var(--fmx-primary,#5276EB)' };
        var glyph = { success: 'i-check-circle', error: 'i-x-circle', warn: 'i-alert', info: 'i-info' };
        var el = h('div', {
            class: 'fm-toast ' + kind,
            style: {
                display: 'flex', gap: '10px', alignItems: 'flex-start',
                background: 'var(--fmx-bg2,#1e1e1e)', color: 'var(--fmx-text,#ededed)',
                border: '1px solid var(--fmx-border,#333)', borderLeft: '3px solid ' + (colors[kind] || colors.info),
                borderRadius: '10px', padding: '11px 13px', fontSize: '13px', lineHeight: '1.5',
                boxShadow: '0 12px 28px -4px rgba(0,0,0,0.45)', cursor: 'pointer',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word', transition: 'opacity .25s ease'
            },
            title: T('fm.close')
        }, [
            spriteIcon(glyph[kind] || 'i-info', 'fm-ico'),
            h('span', { text: String(msg === undefined || msg === null ? '' : msg), style: { flex: '1', minWidth: '0' } })
        ]);
        var dismiss = function () {
            el.style.opacity = '0';
            setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 260);
        };
        el.addEventListener('click', dismiss);
        toastHost().appendChild(el);
        setTimeout(dismiss, kind === 'error' ? 9000 : (kind === 'warn' ? 6500 : 3200));
        return el;
    }

    var _modalStack = [];

    /**
     * Overlay modal. Returns {root, body, foot, close}. Escape closes the top
     * one only; a click on the backdrop closes it too unless `sticky` is set
     * (used while a delete is in flight, where a stray click must not hide the
     * result the user needs to read).
     *
     * opts: {small, large, sticky, onClose}. `small` and `large` size the
     * dialog and `small` wins if both are passed; `large` is the media stage,
     * which needs a fixed height rather than the default shrink-to-content.
     */
    function openModal(title, opts) {
        var o = opts || {};
        installRuntimeStyles();
        var body = h('div', { class: 'fmx-body' });
        var foot = h('div', { class: 'fmx-foot' });
        var closeBtn = h('button', {
            class: 'fmx-close', type: 'button',
            title: T('fm.close'),
            // The glyph is decorative once the button has a name of its own.
            'aria-label': T('fm.close')
        });
        closeBtn.appendChild(spriteIcon('i-x', 'fm-ico'));
        var dialog = h('div', { class: 'fmx-dialog' + (o.small ? ' sm' : (o.large ? ' xl' : '')) }, [
            h('div', { class: 'fmx-head' }, [
                h('h2', { class: 'fmx-title', text: title, title: title }),
                closeBtn
            ]),
            body, foot
        ]);
        var root = h('div', { class: 'fmx-overlay' }, [dialog]);
        var entry = { root: root, sticky: !!o.sticky, onClose: o.onClose };

        var close = function (skipHook) {
            var i = _modalStack.indexOf(entry);
            if (i === -1) return;
            _modalStack.splice(i, 1);
            if (root.parentNode) root.parentNode.removeChild(root);
            if (!skipHook && entry.onClose) entry.onClose();
        };
        entry.close = close;
        closeBtn.addEventListener('click', function () { close(); });
        root.addEventListener('mousedown', function (e) {
            if (e.target === root && !entry.sticky) close();
        });

        // Keep Tab inside the dialog while it is open.
        //
        // The backdrop stops the mouse but not the keyboard, so without this a
        // few Tab presses land on the toolbar behind the overlay and Enter
        // dispatches whatever action sits there — including Delete, on the very
        // file the dialog is showing. The action router listens on document and
        // has no idea a modal is up.
        var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),' +
                        'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
        function trapTab(e) {
            if (e.key !== 'Tab') return;
            if (_modalStack.length && _modalStack[_modalStack.length - 1] !== entry) return;
            var items = Array.prototype.filter.call(
                dialog.querySelectorAll(FOCUSABLE),
                function (el) { return el.offsetParent !== null || el === document.activeElement; }
            );
            if (!items.length) { e.preventDefault(); return; }
            var first = items[0], last = items[items.length - 1];
            // Focus sitting outside the dialog (the page behind, or nothing at
            // all) has to be pulled back in rather than wrapped.
            if (!dialog.contains(document.activeElement)) {
                e.preventDefault();
                (e.shiftKey ? last : first).focus();
            } else if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
        // Only on document, and in capture: focus may be OUTSIDE the dialog
        // (that is the case being fixed), so a listener on the overlay would
        // never see the key. Binding both places would run the trap twice per
        // Tab and skip an element.
        document.addEventListener('keydown', trapTab, true);

        // Where focus was before the dialog took over, so closing it returns
        // the user to the control they opened it from.
        var restoreTo = document.activeElement;
        var innerClose = close;
        close = entry.close = function (skipHook) {
            var wasOpen = _modalStack.indexOf(entry) !== -1;
            innerClose(skipHook);
            if (!wasOpen) return;
            document.removeEventListener('keydown', trapTab, true);
            if (restoreTo && typeof restoreTo.focus === 'function' && document.contains(restoreTo)) {
                try { restoreTo.focus(); } catch (e) { /* element went away */ }
            }
        };
        // The listener registered above already calls this one: `close` is a
        // var and the closure resolves it at click time, not at bind time.

        (byId('fmOverlayHost') || document.body).appendChild(root);
        _modalStack.push(entry);
        return {
            root: root, dialog: dialog, body: body, foot: foot, close: close,
            setSticky: function (v) { entry.sticky = !!v; },
            setTitle: function (t) { dialog.querySelector('.fmx-title').textContent = t; }
        };
    }

    function closeTopModal() {
        if (!_modalStack.length) return false;
        _modalStack[_modalStack.length - 1].close();
        return true;
    }

    // ══════════════════════════════════════════════════════════════════
    // Media viewer
    // ══════════════════════════════════════════════════════════════════

    /**
     * ext -> which element draws it. The key set must stay identical to the
     * server's _MEDIA_TYPES: offering a preview the server answers 415 to is a
     * guaranteed error toast, and refusing one it would have served hides a
     * working feature. tests/file_manager_media_smoke.py asserts the two match.
     *
     * The media type itself is deliberately NOT here — the browser takes it
     * from the response header, and a second copy would only be a second thing
     * to drift.
     *
     * This does not replace getFileIcon()'s table; that one colours icons for
     * every extension, including ones no browser can play.
     */
    var MEDIA = {
        '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image',
        '.webp': 'image', '.bmp': 'image', '.ico': 'image', '.avif': 'image',
        '.mp4': 'video', '.m4v': 'video', '.webm': 'video', '.ogv': 'video',
        '.mov': 'video',
        '.mp3': 'audio', '.m4a': 'audio', '.aac': 'audio', '.wav': 'audio',
        '.flac': 'audio', '.ogg': 'audio', '.oga': 'audio', '.opus': 'audio',
        '.pdf': 'pdf'
    };

    function extOfPath(p) {
        var b = baseName(String(p || ''));
        var i = b.lastIndexOf('.');
        return i > 0 ? b.slice(i).toLowerCase() : '';
    }

    function mediaOf(path) { return MEDIA[extOfPath(path)] || null; }

    /**
     * Relative to the page, NOT to API_ORIGIN — unlike every other call here.
     *
     * API_ORIGIN comes from localStorage.tubecli_api, which the dashboard's
     * Settings form fills from the server's api_base_url, whose default is
     * "http://localhost:{port}". Open the dashboard at the 127.0.0.1 address the
     * installers and the CLI banner print, save Settings once, and API_ORIGIN is
     * a different host from the page. JSON calls survive that — they are CORS
     * requests and the origin guard allows loopback — but <img>/<video>/<iframe>
     * send Sec-Fetch-Site: cross-site, which /raw refuses by design, and the
     * user gets "could not load this file" on every single media file.
     *
     * There is nothing to configure away: the endpoint requires same-origin, so
     * an API_ORIGIN that differs from the page can never serve media. Serving a
     * genuinely remote API base would be a separate design, needing both the
     * fetch-site guard and Cross-Origin-Resource-Policy to be relaxed for named
     * hosts.
     */
    function mediaUrl(base, path) {
        return base + '/raw?path=' + encodeURIComponent(path);
    }

    /**
     * The next/prev playlist, read from the DOM rather than from FM.items.
     * renderFiles sorts into a throwaway local — folders first, then
     * localeCompare — and leaves FM.items in server order, so a list built from
     * FM.items would step through a different sequence than the one on screen.
     * Deep search replaces the grid too, and the DOM is right in that case as
     * well.
     */
    function mediaSiblings(path) {
        var grid = byId('fileGrid'), out = [];
        if (grid) {
            grid.querySelectorAll('.fm-file-card[data-dir="0"]').forEach(function (c) {
                var p = c.getAttribute('data-path');
                if (p && mediaOf(p)) out.push(p);
            });
        }
        if (out.indexOf(path) === -1) out = [path];
        return out;
    }

    /**
     * Media lightbox, built on openModal() rather than the static #previewModal
     * for one load-bearing reason: openModal pushes onto _modalStack, and
     * FM.handleKeyboard disarms Delete / F2 / Backspace / F5 only while that
     * stack is non-empty. #previewModal is invisible to that check, so a viewer
     * built on it would leave Delete live with the file still selected behind
     * it. Escape, backdrop-close and the onClose teardown hook come with the
     * stack too.
     */
    function openMediaViewer(list, startPath, base) {
        var index = Math.max(0, list.indexOf(startPath));
        var current = null;
        var stage = h('div', { class: 'fmx-media' });
        var counter = h('span', { class: 'fmx-muted' });
        var meta = h('span', { class: 'fmx-muted' });
        var dl = h('a', { class: 'fmx-btn ghost', title: T('fm.browse.download') });
        dl.appendChild(spriteIcon('i-download', 'fm-ico'));

        var m = openModal(baseName(list[index]), {
            large: true,
            onClose: function () {
                document.removeEventListener('keydown', onKey, true);
                teardown();
            }
        });
        m.body.classList.add('fmx-media-body');
        m.body.appendChild(stage);

        /**
         * A <video> left in a detached node keeps decoding, keeps the socket
         * open and keeps playing audio over the rest of the UI.
         */
        function teardown() {
            var el = current;
            current = null;
            if (!el) return;
            try { if (typeof el.pause === 'function') el.pause(); } catch (e) { /* not a player */ }
            el.removeAttribute('src');
            try { if (typeof el.load === 'function') el.load(); } catch (e) { /* not a player */ }
            if (el.parentNode) el.parentNode.removeChild(el);
        }

        function fail(msg, url) {
            teardown();
            clear(stage);
            var note = h('div', { class: 'fmx-note warn', style: { margin: '0', maxWidth: '560px' } },
                         [h('div', { text: msg })]);
            if (url) {
                // A same-origin top-level navigation sends Sec-Fetch-Site:
                // same-origin, so it passes the raw endpoint's guard. This is
                // also the iOS answer for PDFs, which iOS Safari renders inside
                // an iframe as a single unscrollable page.
                note.appendChild(h('a', {
                    href: url, target: '_blank', rel: 'noopener',
                    style: { display: 'inline-block', marginTop: '8px', color: 'var(--fmx-primary)' },
                    text: T('fm.media.open_new_tab')
                }));
            }
            stage.appendChild(note);
        }

        function show(i) {
            index = (i + list.length) % list.length;
            var path = list[index];
            var kind = mediaOf(path);
            var url = mediaUrl(base, path);
            teardown();
            clear(stage);
            m.setTitle(baseName(path));
            counter.textContent = list.length > 1
                ? T('fm.media.counter', { i: index + 1, n: list.length }) : '';
            // Deep search replaces the grid with searchResults and leaves
            // FM.items holding the folder the user came from, so looking only
            // there left the size blank for every hit in a search.
            var rows = (FM.searchResults && FM.searchResults.length ? FM.searchResults : FM.items) || [];
            var item = rows.find(function (x) { return x.path === path; });
            meta.textContent = item && item.size_human ? item.size_human : '';
            dl.href = url;
            dl.setAttribute('download', baseName(path));
            if (!kind) { fail(T('fm.media.load_failed'), url); return; }

            var el;
            if (kind === 'image') {
                el = h('img', { alt: baseName(path), decoding: 'async' });
            } else if (kind === 'video' || kind === 'audio') {
                el = document.createElement(kind);
                el.controls = true;
                el.preload = 'metadata';
                if (kind === 'video') el.setAttribute('playsinline', '');
                // No canPlayType() gate. It answers about the MIME STRING, not
                // the file, and Chrome 150 returns '' for video/quicktime while
                // happily playing H.264 inside a .mov — measured, alongside
                // 'maybe' for every other type in this table. Gating on it made
                // every .mov preview dead in Chrome and Edge. Attach the source
                // and let the error listener below report a real refusal; that
                // path already exists and already offers the download link.
            } else {
                el = h('iframe', { title: baseName(path) });
                el.setAttribute('referrerpolicy', 'no-referrer');
            }
            // Media elements fire error on the element itself rather than along
            // a bubbling path; capture catches that and a failing <source> both.
            el.addEventListener('error', function () {
                fail(T('fm.media.load_failed'), url);
            }, true);
            el.src = url;
            stage.appendChild(el);
            current = el;
        }

        function onKey(e) {
            if (list.length < 2) return;
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            var tag = e.target && e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            // With the player focused the arrows are its own scrub controls.
            if (current && e.target === current) return;
            e.preventDefault();
            show(index + (e.key === 'ArrowRight' ? 1 : -1));
        }
        // Capture, so it runs ahead of FM.handleKeyboard's document listener.
        document.addEventListener('keydown', onKey, true);

        if (list.length > 1) {
            var prev = h('button', {
                class: 'fmx-btn ghost fmx-media-nav', type: 'button',
                title: T('fm.media.prev'), 'aria-label': T('fm.media.prev'),
                onclick: function () { show(index - 1); }
            });
            prev.appendChild(spriteIcon('i-chevron-left', 'fm-ico'));
            var next = h('button', {
                class: 'fmx-btn ghost fmx-media-nav', type: 'button',
                title: T('fm.media.next'), 'aria-label': T('fm.media.next'),
                onclick: function () { show(index + 1); }
            });
            next.appendChild(spriteIcon('i-chevron-right', 'fm-ico'));
            m.foot.appendChild(prev);
            m.foot.appendChild(next);
            m.foot.appendChild(counter);
        }
        m.foot.appendChild(meta);
        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(dl);
        m.foot.appendChild(h('button', {
            class: 'fmx-btn ghost', type: 'button',
            text: T('fm.close'), onclick: function () { m.close(); }
        }));

        show(index);
        // The other modals set aria-modal without moving focus anywhere.
        setTimeout(function () {
            var btn = m.dialog.querySelector('.fmx-close');
            if (btn) btn.focus();
        }, 30);
        return m;
    }

    /** Promise<boolean>. `typeWord` gates the accept button behind typed text. */
    function confirmDialog(opts) {
        return new Promise(function (resolve) {
            var settled = false;
            var finish = function (v) { if (settled) return; settled = true; m.close(true); resolve(v); };
            var m = openModal(opts.title, { small: !opts.wide, onClose: function () { finish(false); } });

            (opts.blocks || []).forEach(function (b) { if (b) m.body.appendChild(b); });
            if (opts.body) m.body.appendChild(h('div', { class: 'fmx-note' + (opts.danger ? ' err' : ''), text: opts.body }));

            var accept = h('button', {
                class: 'fmx-btn ' + (opts.danger ? 'danger' : 'primary'),
                type: 'button',
                text: opts.acceptLabel || T('fm.confirm'),
                disabled: !!opts.typeWord,
                onclick: function () { finish(true); }
            });

            if (opts.typeWord) {
                var input = h('input', {
                    class: 'fmx-input', type: 'text', autocomplete: 'off', spellcheck: 'false',
                    placeholder: opts.typeWord,
                    oninput: function () {
                        accept.disabled = input.value.trim().toUpperCase() !== opts.typeWord.toUpperCase();
                    },
                    onkeydown: function (e) { if (e.key === 'Enter' && !accept.disabled) finish(true); }
                });
                m.body.appendChild(h('div', { class: 'fmx-sec' }, [
                    h('div', { class: 'fmx-muted', text: T('fm.cleanup_confirm_hint', { word: opts.typeWord }), style: { marginBottom: '6px' } }),
                    input
                ]));
                setTimeout(function () { input.focus(); }, 30);
            } else {
                setTimeout(function () { accept.focus(); }, 30);
            }

            m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
            m.foot.appendChild(h('button', {
                class: 'fmx-btn ghost', type: 'button', text: opts.cancelLabel || T('fm.cancel'),
                onclick: function () { finish(false); }
            }));
            m.foot.appendChild(accept);
        });
    }

    /** Promise<string|null>. Replaces window.prompt so the text is translatable. */
    function promptDialog(title, initial) {
        return new Promise(function (resolve) {
            var settled = false;
            var finish = function (v) { if (settled) return; settled = true; m.close(true); resolve(v); };
            var m = openModal(title, { small: true, onClose: function () { finish(null); } });
            var input = h('input', {
                class: 'fmx-input', type: 'text', value: initial || '', autocomplete: 'off', spellcheck: 'false',
                onkeydown: function (e) {
                    if (e.key === 'Enter') { e.preventDefault(); finish(input.value); }
                }
            });
            m.body.appendChild(input);
            m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
            m.foot.appendChild(h('button', { class: 'fmx-btn ghost', type: 'button', text: T('fm.cancel'), onclick: function () { finish(null); } }));
            m.foot.appendChild(h('button', { class: 'fmx-btn primary', type: 'button', text: T('fm.confirm'), onclick: function () { finish(input.value); } }));
            setTimeout(function () { input.focus(); input.select(); }, 30);
        });
    }

    // ══════════════════════════════════════════════════════════════════
    // FM — page controller
    // ══════════════════════════════════════════════════════════════════

    var FM = {
        currentPath: '',
        selectedItem: null,
        clipboard: null,            // {action:'copy'|'cut', path}
        viewMode: 'grid',
        items: [],
        searchResults: null,        // non-null while showing server-side results
        pickerMode: false,
        pickerFilter: '',
        _crudPrefix: { value: null },
        _featPrefix: { value: null },

        // ── prefix resolution ────────────────────────────────────────

        async crudBase() {
            if (this._crudPrefix.value) return this._crudPrefix.value;
            var r = await probePrefix('/roots', this._crudPrefix);
            console.info('[file_manager] CRUD endpoints resolved to', r.prefix);
            return r.prefix;
        },

        async featBase() {
            if (this._featPrefix.value) return this._featPrefix.value;
            var r = await probePrefix('/disk', this._featPrefix);
            console.info('[file_manager] storage endpoints resolved to', r.prefix);
            this._lastDisk = r.data;
            return r.prefix;
        },

        /** Kept for backwards compatibility with any caller outside this file. */
        async api(method, endpoint, body) {
            var base = await this.crudBase();
            var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
            if (body) opts.body = JSON.stringify(body);
            try {
                return await requestJson(base + endpoint, opts);
            } catch (e) {
                toast(e.message, 'error');
                throw e;
            }
        },

        async feat(method, endpoint, body, signal) {
            var base = await this.featBase();
            var opts = { method: method, headers: { 'Content-Type': 'application/json' }, signal: signal };
            if (body) opts.body = JSON.stringify(body);
            return requestJson(base + endpoint, opts);
        },

        // ── Init ─────────────────────────────────────────────────────

        async init() {
            installRuntimeStyles();

            // Re-assert our T/applyI18n after every synchronous script has run,
            // so load order with the shared /static/i18n.js cannot decide which
            // implementation wins. Ours knows the fm.* fallbacks; the shared one
            // would render raw keys for them.
            window.T = T;
            window.applyI18n = applyI18n;

            var params = new URLSearchParams(window.location.search);
            this.pickerMode = params.get('mode') === 'picker';
            this.pickerFilter = params.get('filter') || '';
            if (this.pickerMode) {
                var banner = byId('pickerBanner');
                if (banner) banner.style.display = 'flex';
            }

            if (!byId('fmOverlayHost')) {
                document.body.appendChild(h('div', { id: 'fmOverlayHost' }));
            }

            this.bindEvents();

            // Translations first: the injected buttons take their labels from
            // T() once and have no data-i18n attribute to be re-translated by a
            // later applyI18n() pass.
            await loadI18n();
            this.injectToolbarButtons();

            // Roots and volumes are independent: one failing must not hide the
            // other, so they are awaited separately rather than in a Promise.all
            // whose first rejection would discard the successful half.
            await this.loadRoots();
            this.loadVolumes();
        },

        async loadRoots() {
            try {
                var data = await this.api('GET', '/roots');
                // Adopt the server's os.sep before anything builds or splits a
                // path. This is the first request the page makes, so every
                // helper below runs with the real separator rather than one
                // guessed from a filename that may legally contain "\".
                if (data.sep === '\\' || data.sep === '/') {
                    PATH.sep = data.sep;
                } else {
                    // Never silent: the shape fallback is correct for the
                    // absolute paths this API returns, but whoever debugs a
                    // path bug must be able to see that the server did not say.
                    console.warn('[file_manager] GET /roots reported no "sep"; ' +
                        'falling back to detecting Windows by path shape (C:\\ or \\\\host).');
                }
                var roots = data.roots || [];
                this.renderSidebar(roots);
                var first = roots.find(function (r) { return r.exists; });
                if (first) await this.navigate(first.path);
                else this.setStatus(T('fm.ready'), '');
            } catch (e) {
                // The toast already carried the reason; the content area must
                // also stop showing a spinner that would never resolve.
                this.showGridError(e.message);
            }
        },

        bindEvents() {
            document.addEventListener('keydown', this.handleKeyboard.bind(this));
            document.addEventListener('click', this.hideContextMenu.bind(this));

            var search = byId('searchInput');
            if (search) {
                search.addEventListener('input', debounce(this.handleSearch.bind(this), 250));
                search.addEventListener('keydown', (function (e) {
                    if (e.key === 'Enter') { e.preventDefault(); this.deepSearch(); }
                }).bind(this));
                if (!search.title) search.title = T('fm.search_deep');
            }

            var hidden = byId('showHidden');
            if (hidden) hidden.addEventListener('change', this.refresh.bind(this));

            // Delegated handlers. Inline onclick="FM.navigate('…')" broke on any
            // path containing an apostrophe — routine for Vietnamese folder
            // names — because the quote closed the attribute's JS string.
            var grid = byId('fileGrid');
            if (grid) {
                grid.addEventListener('click', (function (e) {
                    var card = e.target.closest('.fm-file-card');
                    if (card) this.selectItem(card, card.getAttribute('data-path'));
                }).bind(this));
                grid.addEventListener('dblclick', (function (e) {
                    var card = e.target.closest('.fm-file-card');
                    if (card) this.openItem(card.getAttribute('data-path'), card.getAttribute('data-dir') === '1');
                }).bind(this));
                grid.addEventListener('contextmenu', (function (e) {
                    var card = e.target.closest('.fm-file-card');
                    if (card) this.showContextMenu(e, card.getAttribute('data-path'), card.getAttribute('data-dir') === '1');
                }).bind(this));
                // Kéo file (không phải thư mục) sang canvas Flow của cloud bằng POINTER CAPTURE
                // (không dùng drag gốc để tránh con trỏ 🚫 no-drop qua iframe khác origin).
                // pointerdown ghim card → vượt ngưỡng thì setPointerCapture (card nhận mọi
                // pointermove/up kể cả khi con trỏ ra ngoài iframe) + báo 'drag'; stream 'move';
                // nhả chuột → 'drop'. Cloud vẽ chip theo con trỏ + đặt node tại vị trí thả.
                var fmDrag = null;
                grid.addEventListener('pointerdown', function (e) {
                    if (e.button !== 0) return;
                    var card = e.target.closest ? e.target.closest('.fm-file-card') : null;
                    if (!card || card.getAttribute('data-dir') === '1') return;
                    var path = card.getAttribute('data-path');
                    fmDrag = {
                        id: e.pointerId, el: card, x: e.clientX, y: e.clientY, started: false,
                        ref: {
                            v: 1, source: 'local', path: path,
                            name: card.getAttribute('data-name') || (path || '').split('/').pop(),
                            ext: card.getAttribute('data-ext') || null,
                            size: card.getAttribute('data-size') ? Number(card.getAttribute('data-size')) : null
                        }
                    };
                });
                window.addEventListener('pointermove', function (e) {
                    if (!fmDrag || e.pointerId !== fmDrag.id) return;
                    if (!fmDrag.started) {
                        if (Math.abs(e.clientX - fmDrag.x) + Math.abs(e.clientY - fmDrag.y) < 6) return;
                        fmDrag.started = true;
                        try { fmDrag.el.setPointerCapture(fmDrag.id); } catch (x) {}
                        document.body.style.userSelect = 'none';
                        document.body.style.cursor = 'grabbing';
                        try { window.parent.postMessage({ type: 'tubecli-fm-drag', ref: fmDrag.ref }, '*'); } catch (x) {}
                    }
                    try { window.parent.postMessage({ type: 'tubecli-fm-move', ix: e.clientX, iy: e.clientY }, '*'); } catch (x) {}
                });
                window.addEventListener('pointerup', function (e) {
                    if (!fmDrag || e.pointerId !== fmDrag.id) return;
                    var started = fmDrag.started, el = fmDrag.el, id = fmDrag.id;
                    fmDrag = null;
                    document.body.style.userSelect = '';
                    document.body.style.cursor = '';
                    try { el.releasePointerCapture(id); } catch (x) {}
                    if (started) { try { window.parent.postMessage({ type: 'tubecli-fm-drop', ix: e.clientX, iy: e.clientY }, '*'); } catch (x) {} }
                });
            }

            // ── NHẬN file kéo-thả từ canvas Flow (giao thức chung 'tubecli-file-drop') ──
            // Extension khác muốn nhận file: COPY nguyên đoạn này. Cloud gửi {file:{path,name,
            // ext,size,source}} khi user thả node media đè lên node extension. Kiểm nguồn là
            // cửa cha để an toàn. Ở đây demo bằng toast; extension thật thay bằng xử lý path.
            if (!window.__tcFileDropBound) {
                window.__tcFileDropBound = true;
                window.addEventListener('message', function (e) {
                    if (e.source !== window.parent || !e.data || e.data.type !== 'tubecli-file-drop') return;
                    var f = e.data.file || {};
                    try {
                        var el = document.createElement('div');
                        el.textContent = '📎 Đã nhận file: ' + (f.name || f.path || '');
                        el.style.cssText = 'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:99999;background:#10b981;color:#fff;font:600 13px system-ui;padding:8px 16px;border-radius:999px;box-shadow:0 8px 24px rgba(0,0,0,.4)';
                        document.body.appendChild(el);
                        setTimeout(function () { el.remove(); }, 2600);
                    } catch (x) {}
                    // TODO(extension): dùng f.path để làm việc thật (mở thư mục, import, nạp script...).
                });
            }

            var bc = byId('breadcrumb');
            if (bc) bc.addEventListener('click', (function (e) {
                var crumb = e.target.closest('[data-path]');
                if (crumb) this.navigate(crumb.getAttribute('data-path'));
            }).bind(this));

            var quick = byId('quickAccess');
            if (quick) {
                quick.addEventListener('click', (function (e) {
                    var item = e.target.closest('[data-path]');
                    if (item && item.getAttribute('data-exists') !== '0') this.navigate(item.getAttribute('data-path'));
                }).bind(this));
                // The rows carry role="button" and tabindex, so they have to answer
                // to the keyboard too — announcing a control and then ignoring Enter
                // is worse than not announcing it.
                quick.addEventListener('keydown', (function (e) {
                    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
                    var item = e.target.closest('[data-path]');
                    if (!item || item.getAttribute('data-exists') === '0') return;
                    e.preventDefault();
                    this.navigate(item.getAttribute('data-path'));
                }).bind(this));
            }
        },

        /** Only injected when the HTML has not already provided the buttons. */
        injectToolbarButtons() {
            var host = byId('fmToolbarExtra') || document.querySelector('.fm-toolbar-right');
            if (!host || byId('btnStorageScan')) return;
            var mk = function (id, label, handler) {
                return h('button', {
                    id: id, class: 'fm-btn fmx-btn ghost', type: 'button', text: label, title: label,
                    onclick: handler
                });
            };
            var frag = document.createDocumentFragment();
            frag.appendChild(mk('btnStorageScan', T('fm.scan_title'), function () { FM.openScan(); }));
            frag.appendChild(mk('btnCleanup', T('fm.cleanup_title'), function () { FM.openCleanup(); }));
            frag.appendChild(mk('btnPermissions', T('fm.perm_title'), function () { FM.openPermissions(); }));
            host.insertBefore(frag, host.firstChild);
        },

        // ── Navigation ───────────────────────────────────────────────

        async navigate(path) {
            if (!path) return;
            // Any file navigation implies the Files view. Clicking a Quick Access
            // folder while the Drive (or Storage/Cleanup) view is on screen used
            // to update the browser underneath without switching back, so the
            // click looked dead. Return to Files whenever we navigate.
            if (window.FMActions && typeof window.FMActions.setView === 'function') {
                window.FMActions.setView('files');
            }
            this.currentPath = path;
            this.selectedItem = null;
            this.searchResults = null;
            this.updateToolbarButtons();

            var grid = byId('fileGrid'), empty = byId('emptyState'), loading = byId('loading');
            if (grid) clear(grid);
            if (empty) empty.style.display = 'none';
            if (loading) loading.style.display = 'flex';

            try {
                var hidden = byId('showHidden');
                var data = await this.api('GET', '/list?path=' + encodeURIComponent(path) +
                    '&show_hidden=' + (hidden && hidden.checked ? 'true' : 'false'));
                if (!Array.isArray(data.items)) {
                    throw new Error(T('fm.err_shape', { field: 'items', got: middleTrim(JSON.stringify(data), 200) }));
                }
                this.items = data.items;
                this.renderFiles(this.items);
                this.renderBreadcrumb(data.path || path);
                this.setStatus(data.path || path, T('fm.count_summary', { dirs: data.dirs || 0, files: data.files || 0 }));

                document.querySelectorAll('.fm-sidebar-item').forEach(function (el) {
                    el.classList.toggle('active', el.getAttribute('data-path') === path);
                });
            } catch (e) {
                this.showGridError(e.message);
            }
        },

        goUp() {
            var parent = parentOf(this.currentPath);
            if (parent && parent !== this.currentPath) this.navigate(parent);
        },

        refresh() {
            if (this.currentPath) this.navigate(this.currentPath);
        },

        showGridError(msg) {
            var loading = byId('loading'), empty = byId('emptyState'), grid = byId('fileGrid');
            if (loading) loading.style.display = 'none';
            if (empty) empty.style.display = 'none';
            if (!grid) return;
            clear(grid);
            grid.appendChild(h('div', {
                class: 'fmx-note err',
                style: { gridColumn: '1 / -1', margin: '12px' }
            }, [
                h('div', { text: String(msg || ''), style: { marginBottom: '10px' } }),
                h('button', { class: 'fmx-btn', type: 'button', text: T('fm.retry'), onclick: function () { FM.refresh(); } })
            ]));
        },

        // ── Render ───────────────────────────────────────────────────

        renderSidebar(roots) {
            var container = byId('quickAccess');
            if (!container) return;
            clear(container);
            // Sprite symbols, not emoji. Emoji render in the OS colour font at a
            // different weight and baseline from every other icon on the page, which
            // is why Quick Access looked pasted in next to the dashboard's outlined
            // set. The ids come from the inline sprite in file_manager.html.
            var symbols = {
                Desktop: 'i-monitor', Documents: 'i-file-text',
                Downloads: 'i-download', data: 'i-database'
            };
            function rootIcon(name) {
                return spriteIcon(symbols[name] || 'i-folder', 'fm-ico');
            }
            roots.forEach(function (r) {
                // 'fm-rail-item', not 'fm-sidebar-item'. The stylesheet defines the
                // former and has no rule at all for the latter, so these rows came
                // out with no padding and no height — the label was visible but the
                // clickable box was a couple of pixels tall, which reads as "Quick
                // Access doesn't work". The click handler was fine all along.
                var row = h('div', {
                    class: 'fm-rail-item',
                    role: 'button',
                    tabindex: r.exists ? '0' : '-1',
                    'data-path': r.path,
                    'data-exists': r.exists ? '1' : '0',
                    // The CSS dims and disables via aria-disabled; setting inline
                    // styles instead meant the disabled look depended on this
                    // function rather than on the design system.
                    'aria-disabled': r.exists ? null : 'true',
                    title: r.path + (r.exists ? '' : ' — ' + T('fm.root_missing'))
                }, [
                    rootIcon(r.name),
                    h('span', { text: r.name || r.path })
                ]);
                container.appendChild(row);
            });
        },

        renderBreadcrumb(path) {
            var bc = byId('breadcrumb');
            if (!bc) return;
            clear(bc);
            var s = String(path);
            var win = PATH.isWindows(s);
            var parts = s.split(PATH.splitRe(s)).filter(function (p) { return p !== ''; });
            // Meaningful only on Windows: "/C:" is a legal POSIX directory name,
            // and rewriting that first crumb to "C:\" pointed it at another disk.
            var isWinAbs = win && /^[A-Za-z]:$/.test(parts[0] || '');
            var acc = '';
            parts.forEach(function (part, i) {
                if (i === 0) acc = isWinAbs ? part + '\\' : (win ? part : '/' + part);
                else acc = joinPath(acc, part);
                var last = i === parts.length - 1;
                bc.appendChild(h('span', {
                    class: last ? 'fm-crumb active' : 'fm-crumb',
                    'data-path': acc, text: part, title: acc
                }));
                if (!last) bc.appendChild(h('span', { class: 'fm-crumb-sep', text: '›' }));
            });
        },

        renderFiles(items) {
            var grid = byId('fileGrid'), loading = byId('loading'), empty = byId('emptyState');
            if (loading) loading.style.display = 'none';
            if (!grid) return;
            grid.className = 'fm-file-grid' + (this.viewMode === 'list' ? ' list-view' : '');

            var filtered = items || [];
            if (this.pickerMode && this.pickerFilter) {
                var videoExts = ['.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv', '.wmv', '.m4v', '.ts', '.mpg', '.mpeg'];
                var imageExts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff'];
                var f = this.pickerFilter;
                filtered = filtered.filter(function (item) {
                    if (item.is_dir) return true;
                    var ext = (item.extension || '').toLowerCase();
                    if (f === 'video') return videoExts.indexOf(ext) !== -1;
                    if (f === 'image') return imageExts.indexOf(ext) !== -1;
                    return true;
                });
            }

            clear(grid);
            if (!filtered.length) {
                if (empty) empty.style.display = 'flex';
                return;
            }
            if (empty) empty.style.display = 'none';

            var sorted = filtered.slice().sort(function (a, b) {
                if (a.is_dir && !b.is_dir) return -1;
                if (!a.is_dir && b.is_dir) return 1;
                return String(a.name).localeCompare(String(b.name), 'vi');
            });

            var listView = this.viewMode === 'list';
            var frag = document.createDocumentFragment();
            sorted.forEach(function (item) {
                var icon = FM.getFileIcon(item);
                var iconBox = h('span', { class: 'fm-file-icon ' + icon.cls });
                iconBox.appendChild(spriteIcon(icon.symbol, 'fm-ico'));
                var kids = [
                    iconBox,
                    h('span', { class: 'fm-file-name', text: item.name, title: item.path })
                ];
                if (listView) {
                    kids.push(h('span', { class: 'fm-file-size', text: item.is_dir ? '' : (item.size_human || '') }));
                    kids.push(h('span', { class: 'fm-file-modified', text: item.modified || '' }));
                } else if (!item.is_dir) {
                    kids.push(h('span', { class: 'fm-file-size', text: item.size_human || '' }));
                }
                if (item.error) {
                    kids.push(h('span', { class: 'fmx-badge err', text: item.error, style: { marginTop: '4px' } }));
                }
                var cardAttrs = {
                    class: 'fm-file-card', 'data-path': item.path, 'data-dir': item.is_dir ? '1' : '0'
                };
                if (!item.is_dir) {
                    // Kéo file ra canvas Flow (cloud) → tạo Media node. KHÔNG dùng drag gốc
                    // (con trỏ 🚫 no-drop qua iframe khác origin). Dùng pointer capture + stream
                    // vị trí; cloud vẽ chip theo con trỏ. Xem bindGridEvents.
                    cardAttrs['data-name'] = item.name;
                    cardAttrs['data-ext'] = (item.extension || '').replace(/^\./, '');
                    if (item.size != null) cardAttrs['data-size'] = String(item.size);
                }
                frag.appendChild(h('div', cardAttrs, kids));
            });
            grid.appendChild(frag);
        },

        /** Sprite symbol + colour class for a row. See rootIcon() for why not emoji. */
        getFileIcon(item) {
            if (item.is_dir) return { symbol: 'i-folder', cls: 'folder' };
            var ext = (item.extension || '').toLowerCase();
            var byExt = {
                '.txt': 'text', '.md': 'text', '.log': 'text', '.pdf': 'text',
                '.json': 'code', '.js': 'code', '.py': 'code', '.html': 'code',
                '.css': 'code', '.ts': 'code', '.sh': 'code', '.yml': 'code', '.yaml': 'code',
                '.jpg': 'img', '.jpeg': 'img', '.png': 'img', '.gif': 'img',
                '.svg': 'img', '.webp': 'img', '.bmp': 'img', '.ico': 'img',
                '.mp4': 'video', '.mkv': 'video', '.mov': 'video', '.avi': 'video', '.webm': 'video',
                '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio', '.m4a': 'audio', '.ogg': 'audio',
                '.zip': 'archive', '.rar': 'archive', '.7z': 'archive', '.tar': 'archive', '.gz': 'archive'
            };
            var kinds = {
                text:    { symbol: 'i-file-text', cls: 'file-txt' },
                code:    { symbol: 'i-code',      cls: 'file-code' },
                img:     { symbol: 'i-image',     cls: 'file-img' },
                video:   { symbol: 'i-film',      cls: 'file-media' },
                audio:   { symbol: 'i-music',     cls: 'file-media' },
                archive: { symbol: 'i-archive',   cls: 'file-other' }
            };
            return kinds[byExt[ext]] || { symbol: 'i-file', cls: 'file-other' };
        },

        setStatus(info, count) {
            var a = byId('statusInfo'), b = byId('statusCount');
            if (a) a.textContent = info || '';
            if (b) b.textContent = count || '';
        },

        // ── Selection ────────────────────────────────────────────────

        selectItem(el, path) {
            document.querySelectorAll('.fm-file-card.selected').forEach(function (c) { c.classList.remove('selected'); });
            if (el) el.classList.add('selected');
            this.selectedItem = path;
            this.updateToolbarButtons();

            if (this.pickerMode) {
                var isFolder = el && el.getAttribute('data-dir') === '1';
                var btn = byId('btnPickerSelect');
                if (btn) {
                    btn.style.opacity = isFolder ? '0.4' : '1';
                    btn.style.pointerEvents = isFolder ? 'none' : 'auto';
                }
            }
        },

        updateToolbarButtons() {
            var has = !!this.selectedItem;
            [['btnRename', has], ['btnDelete', has], ['btnCopy', has], ['btnPaste', !!this.clipboard]]
                .forEach(function (pair) {
                    var b = byId(pair[0]);
                    if (b) b.disabled = !pair[1];
                });
        },

        confirmPick() {
            if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
            if (window.opener) {
                window.opener.postMessage({ type: 'file-picker-select', path: this.selectedItem }, '*');
            }
            window.close();
        },

        // ── File operations (preserved behaviour) ────────────────────

        validName(name) {
            if (!name || !name.trim()) return T('fm.name_required');
            var n = name.trim();
            if (n.indexOf('/') !== -1 || n.indexOf('\\') !== -1 || n === '.' || n === '..') return T('fm.name_invalid');
            return null;
        },

        async createFolder() {
            var name = await promptDialog(T('fm.prompt_folder_name'), '');
            if (name === null) return;
            var bad = this.validName(name);
            if (bad) { toast(bad, 'error'); return; }
            try {
                await this.api('POST', '/create-folder', { path: joinPath(this.currentPath, name.trim()) });
                toast(T('fm.created_folder', { name: name.trim() }), 'success');
                this.refresh();
            } catch (e) { /* reported by api() */ }
        },

        async createFile() {
            var name = await promptDialog(T('fm.prompt_file_name'), '');
            if (name === null) return;
            var bad = this.validName(name);
            if (bad) { toast(bad, 'error'); return; }
            try {
                await this.api('POST', '/create-file', { path: joinPath(this.currentPath, name.trim()), content: '' });
                toast(T('fm.created_file', { name: name.trim() }), 'success');
                this.refresh();
            } catch (e) { /* reported by api() */ }
        },

        async deleteSelected() {
            if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
            var target = this.selectedItem;
            var name = baseName(target);
            var ok = await confirmDialog({
                title: T('fm.confirm_delete_title'),
                body: T('fm.confirm_delete_body', { name: name }),
                blocks: [h('div', { class: 'fmx-mono fmx-muted', text: target, style: { marginBottom: '10px' } })],
                danger: true,
                acceptLabel: T('fm.delete')
            });
            if (!ok) return;
            try {
                await this.api('DELETE', '/delete?path=' + encodeURIComponent(target));
                toast(T('fm.deleted', { name: name }), 'success');
                this.selectedItem = null;
                this.refresh();
                this.loadVolumes();
            } catch (e) { /* reported by api() */ }
        },

        async renameSelected() {
            if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
            var oldName = baseName(this.selectedItem);
            var newName = await promptDialog(T('fm.prompt_new_name'), oldName);
            if (newName === null) return;
            newName = newName.trim();
            if (newName === oldName) return;
            var bad = this.validName(newName);
            if (bad) { toast(bad, 'error'); return; }
            // Rebuild from the parent rather than string-replacing the old name:
            // "C:\data\log\log" would have had its FIRST "log" replaced.
            var dst = joinPath(parentOf(this.selectedItem) || this.currentPath, newName);
            try {
                await this.api('POST', '/move', { src: this.selectedItem, dst: dst });
                toast(T('fm.renamed', { name: newName }), 'success');
                this.selectedItem = null;
                this.refresh();
            } catch (e) { /* reported by api() */ }
        },

        copySelected() {
            if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
            this.clipboard = { action: 'copy', path: this.selectedItem };
            this.updateToolbarButtons();
            toast(T('fm.clip_copy', { name: baseName(this.selectedItem) }), 'info');
        },

        moveSelected() {
            if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
            this.clipboard = { action: 'cut', path: this.selectedItem };
            this.updateToolbarButtons();
            toast(T('fm.clip_cut', { name: baseName(this.selectedItem) }), 'info');
        },

        async pasteClipboard() {
            if (!this.clipboard) return;
            var src = this.clipboard.path;
            var name = baseName(src);
            var dst = joinPath(this.currentPath, name);
            if (dst === src) { toast(T('fm.paste_same_dir'), 'warn'); return; }
            try {
                if (this.clipboard.action === 'copy') {
                    await this.api('POST', '/copy', { src: src, dst: dst });
                    toast(T('fm.pasted_copy', { name: name }), 'success');
                } else {
                    await this.api('POST', '/move', { src: src, dst: dst });
                    toast(T('fm.pasted_move', { name: name }), 'success');
                    this.clipboard = null;
                    this.updateToolbarButtons();
                }
                this.refresh();
            } catch (e) { /* reported by api() */ }
        },

        openItem(path, isDir) {
            var target = path || this.selectedItem;
            if (!target) { toast(T('fm.no_selection'), 'warn'); return; }
            var realIsDir = isDir;
            if (realIsDir === undefined || realIsDir === null) {
                var item = this.items.find(function (i) { return i.path === target; });
                realIsDir = !!(item && item.is_dir);
            }
            if (realIsDir) this.navigate(target);
            else if (this.pickerMode) { this.selectedItem = target; this.confirmPick(); }
            // Branch here, not inside previewFile. `is_binary` there is a
            // UnicodeDecodeError side-effect rather than a type check, so a
            // binary that happens to decode as UTF-8 would slip past it — and
            // anything over the 50 MB read limit never reaches that branch at
            // all, it comes back as {"error": "File quá lớn…"} and surfaces as
            // an error toast. Media must never go through /read.
            else if (mediaOf(target)) this.openMedia(target);
            else this.previewFile(target);
        },

        async openMedia(path) {
            var base;
            // The URL goes straight into <img src>/<video src>: FM.api() always
            // JSON.parses the body and cannot carry bytes. Only this prefix
            // probe is a real request.
            try { base = await this.crudBase(); }
            catch (e) { toast(e.message, 'error'); return; }
            openMediaViewer(mediaSiblings(path), path, base);
        },

        async previewFile(path) {
            try {
                var data = await this.api('GET', '/read?path=' + encodeURIComponent(path) + '&max_lines=500');
                if (data.is_binary) { toast(data.message || T('fm.binary_no_preview'), 'info'); return; }
                var title = byId('previewTitle'), content = byId('previewContent'), modal = byId('previewModal');
                if (!modal || !content) {
                    // No preview markup on the page — show it in a generated one
                    // rather than silently doing nothing.
                    var m = openModal(baseName(path));
                    m.body.appendChild(h('pre', {
                        class: 'fmx-mono', text: data.content || '',
                        style: { whiteSpace: 'pre-wrap', margin: '0' }
                    }));
                    return;
                }
                if (title) title.textContent = baseName(path);
                content.textContent = data.content || '';
                modal.style.display = 'flex';
                if (data.truncated) toast(T('fm.preview_truncated', { n: fmtInt(data.lines) }), 'info');
            } catch (e) { /* reported by api() */ }
        },

        closePreview() {
            var m = byId('previewModal');
            if (m) m.style.display = 'none';
        },

        closeProperties() {
            var p = byId('propertiesPanel');
            if (p) p.style.display = 'none';
        },

        // ── Context menu ─────────────────────────────────────────────

        showContextMenu(e, path, isDir) {
            e.preventDefault();
            e.stopPropagation();
            var card = e.target.closest ? e.target.closest('.fm-file-card') : null;
            this.selectItem(card, path);
            var menu = byId('contextMenu');
            if (!menu) return;
            menu.style.display = 'block';
            menu.style.left = Math.max(4, Math.min(e.clientX, window.innerWidth - menu.offsetWidth - 8)) + 'px';
            menu.style.top = Math.max(4, Math.min(e.clientY, window.innerHeight - menu.offsetHeight - 8)) + 'px';
        },

        hideContextMenu() {
            var menu = byId('contextMenu');
            if (menu) menu.style.display = 'none';
        },

        // ── Search ───────────────────────────────────────────────────

        handleSearch() {
            var input = byId('searchInput');
            var q = input ? input.value.trim().toLowerCase() : '';
            if (this.searchResults) return;   // deep results stay until cleared
            if (!q) { this.renderFiles(this.items); return; }
            this.renderFiles(this.items.filter(function (i) {
                return String(i.name).toLowerCase().indexOf(q) !== -1;
            }));
        },

        /** Enter runs the server-side recursive search (existing /search endpoint). */
        async deepSearch() {
            var input = byId('searchInput');
            var q = input ? input.value.trim() : '';
            if (!q || !this.currentPath) return;
            var loading = byId('loading');
            if (loading) loading.style.display = 'flex';
            try {
                var data = await this.api('GET', '/search?path=' + encodeURIComponent(this.currentPath) +
                    '&pattern=' + encodeURIComponent('*' + q + '*') + '&recursive=true');
                var matches = data.matches || [];
                this.searchResults = matches;
                this.renderFiles(matches);
                this.setStatus(this.currentPath, T('fm.search_results', { q: q, n: matches.length }));
                if (matches.length >= 200) toast(T('fm.search_capped'), 'warn');
            } catch (e) {
                if (loading) loading.style.display = 'none';
            }
        },

        clearSearch() {
            var input = byId('searchInput');
            if (input) input.value = '';
            this.searchResults = null;
            this.renderFiles(this.items);
        },

        // ── View + keyboard ──────────────────────────────────────────

        setView(mode) {
            this.viewMode = mode;
            var g = byId('viewGrid'), l = byId('viewList');
            if (g) g.classList.toggle('active', mode === 'grid');
            if (l) l.classList.toggle('active', mode === 'list');
            this.renderFiles(this.searchResults || this.items);
        },

        handleKeyboard(e) {
            if (e.key === 'Escape') {
                if (closeTopModal()) return;
                this.closePreview();
                this.closeProperties();
                this.hideContextMenu();
                return;
            }
            if (_modalStack.length) return;
            var tag = e.target && e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

            if (e.key === 'Delete' && this.selectedItem) { e.preventDefault(); this.deleteSelected(); }
            else if (e.key === 'F2' && this.selectedItem) { e.preventDefault(); this.renameSelected(); }
            else if ((e.ctrlKey || e.metaKey) && e.key === 'c' && this.selectedItem) { e.preventDefault(); this.copySelected(); }
            else if ((e.ctrlKey || e.metaKey) && e.key === 'x' && this.selectedItem) { e.preventDefault(); this.moveSelected(); }
            else if ((e.ctrlKey || e.metaKey) && e.key === 'v' && this.clipboard) { e.preventDefault(); this.pasteClipboard(); }
            else if (e.key === 'Backspace') { e.preventDefault(); this.goUp(); }
            else if (e.key === 'F5') { e.preventDefault(); this.refresh(); }
        },

        escHtml(s) {
            var d = document.createElement('div');
            d.textContent = s === null || s === undefined ? '' : s;
            return d.innerHTML;
        },

        toast: toast,
        debounce: function (fn, ms) { return debounce(fn, ms); }
    };

    function debounce(fn, ms) {
        var timer;
        return function () {
            var args = arguments, self = this;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(self, args); }, ms);
        };
    }

    // ══════════════════════════════════════════════════════════════════
    // Properties — /info, with directory size deferred to /usage/scan
    // ══════════════════════════════════════════════════════════════════

    function kv(label, value, mono) {
        return h('div', { class: 'fmx-kv' }, [
            h('b', { text: label }),
            h('span', { class: mono ? 'fmx-mono' : null, text: value === null || value === undefined || value === '' ? '—' : String(value) })
        ]);
    }

    FM.showProperties = async function () {
        if (!this.selectedItem) { toast(T('fm.no_selection'), 'warn'); return; }
        var target = this.selectedItem;
        var panel = byId('propertiesPanel'), body = byId('propertiesBody');
        var m = null;
        if (!panel || !body) {
            m = openModal(T('fm.properties'), { small: true });
            body = m.body;
        }
        clear(body);
        body.appendChild(h('div', { class: 'fmx-muted', text: T('fm.loading') }));

        try {
            var data = await this.api('GET', '/info?path=' + encodeURIComponent(target));
            clear(body);
            body.appendChild(kv(T('fm.tbl_name'), data.name));
            body.appendChild(kv(T('fm.tbl_path'), data.path, true));
            body.appendChild(kv(T('fm.type_label'), data.is_dir ? T('fm.type_folder') : T('fm.type_file')));

            if (data.is_dir) {
                // The contract makes directory size null on purpose: walking a
                // tree to answer /info would block the request for minutes on a
                // large folder. Offer the background scan instead of showing a
                // fabricated 0 B.
                var sizeKnown = data.total_size !== undefined && data.total_size !== null;
                var row = h('div', { class: 'fmx-kv' }, [
                    h('b', { text: T('fm.tbl_size') }),
                    h('span', {}, [
                        sizeKnown
                            ? h('span', { text: fmtBytes(data.total_size), title: fmtBytesExact(data.total_size) })
                            // size_hint is the server explaining WHY the number
                            // is absent; it is more specific than our generic
                            // label, so prefer it as the tooltip.
                            : h('span', { class: 'fmx-muted', text: T('fm.dir_size_unknown'), title: data.size_hint || '' }),
                        h('button', {
                            class: 'fmx-btn ghost', type: 'button', text: T('fm.dir_size_scan'),
                            style: { marginLeft: '8px', padding: '3px 9px', fontSize: '11.5px' },
                            onclick: function () { if (m) m.close(); FM.openScan(data.path); }
                        })
                    ])
                ]);
                body.appendChild(row);
                if (data.total_files !== undefined && data.total_files !== null) {
                    body.appendChild(kv(T('fm.tbl_count'), fmtInt(data.total_files)));
                }
            } else {
                body.appendChild(kv(T('fm.tbl_size'), data.size_human || fmtBytes(data.size)));
            }

            body.appendChild(kv(T('fm.tbl_modified'), data.modified));
            body.appendChild(kv(T('fm.created_at'), data.created));
            if (data.extension) body.appendChild(kv(T('fm.extension'), data.extension));

            body.appendChild(h('div', { class: 'fmx-row', style: { marginTop: '12px' } }, [
                h('button', {
                    class: 'fmx-btn', type: 'button', text: T('fm.perm_title'),
                    onclick: function () { if (m) m.close(); FM.openPermissions(data.path); }
                }),
                h('button', {
                    class: 'fmx-btn ghost', type: 'button', text: T('fm.copy_path'),
                    onclick: function () { FM.copyPath(data.path); }
                })
            ]));

            if (panel) panel.style.display = 'block';
        } catch (e) {
            clear(body);
            body.appendChild(h('div', { class: 'fmx-note err', text: e.message }));
            if (panel) panel.style.display = 'block';
        }
    };

    FM.copyPath = async function (path) {
        try {
            if (!navigator.clipboard) throw new Error(T('fm.clipboard_unavailable'));
            await navigator.clipboard.writeText(path);
            toast(T('fm.path_copied'), 'success');
        } catch (e) {
            toast(T('fm.path_copy_failed', { msg: e.message || e }), 'error');
        }
    };

    // ══════════════════════════════════════════════════════════════════
    // Volume bars — GET /disk
    // ══════════════════════════════════════════════════════════════════

    function volumesHost() {
        var host = byId('fmVolumes');
        if (host) return host;
        host = h('div', { id: 'fmVolumes', class: 'fmx-vols' });
        var sidebar = byId('sidebar') || document.querySelector('.fm-sidebar');
        if (sidebar) {
            var section = h('div', { class: 'fm-sidebar-section' }, [
                h('h3', { text: T('fm.vol_title') }),
                host
            ]);
            sidebar.appendChild(section);
        } else {
            document.body.appendChild(host);
        }
        return host;
    }

    FM.loadVolumes = async function () {
        var host = volumesHost();
        clear(host);
        host.appendChild(h('div', { class: 'fmx-muted', text: T('fm.loading') }));
        var data;
        try {
            // featBase() probes with GET /disk, so the probe response is the
            // payload — no second round trip.
            await this.featBase();
            data = this._lastDisk;
            if (!data) data = await this.feat('GET', '/disk');
        } catch (e) {
            clear(host);
            host.appendChild(h('div', { class: 'fmx-note err', style: { margin: '0', fontSize: '11.5px' } }, [
                h('div', { text: T('fm.vol_failed', { msg: e.message }) }),
                h('button', { class: 'fmx-btn ghost', type: 'button', text: T('fm.retry'), style: { marginTop: '8px' }, onclick: function () { FM._lastDisk = null; FM.loadVolumes(); } })
            ]));
            return;
        }
        this._lastDisk = null;   // force a fresh read on the next call

        clear(host);
        var vols = data && data.volumes;
        if (!Array.isArray(vols)) {
            host.appendChild(h('div', { class: 'fmx-note err', style: { margin: '0', fontSize: '11.5px' },
                text: T('fm.err_shape', { field: 'volumes', got: middleTrim(JSON.stringify(data), 160) }) }));
            return;
        }
        if (!vols.length) {
            host.appendChild(h('div', { class: 'fmx-muted', text: T('fm.vol_none') }));
            return;
        }

        vols.forEach(function (v) {
            var pct = Number(v.percent);
            if (isNaN(pct)) {
                pct = (v.total > 0) ? (Number(v.used) / Number(v.total)) * 100 : 0;
            }
            pct = Math.max(0, Math.min(100, pct));
            var cls = pct >= 90 ? 'crit' : (pct >= 75 ? 'warn' : '');
            host.appendChild(h('div', {
                class: 'fmx-vol',
                title: v.path + (v.fstype ? ' (' + v.fstype + ')' : '') + '\n' +
                    fmtBytesExact(v.used) + ' / ' + fmtBytesExact(v.total),
                onclick: function () { FM.openVolume(v); }
            }, [
                h('div', { class: 'fmx-vol-top' }, [
                    h('span', { class: 'fmx-vol-label', text: v.label || v.path }),
                    h('span', { class: 'fmx-muted', text: Math.round(pct) + '%' })
                ]),
                h('div', { class: 'fmx-bar' }, [
                    h('div', { class: 'fmx-bar-fill ' + cls, style: { width: pct + '%' } })
                ]),
                h('div', { class: 'fmx-vol-sub' }, [
                    h('span', { text: T('fm.vol_usage', { used: fmtBytes(v.used), total: fmtBytes(v.total) }) }),
                    h('span', { text: T('fm.vol_free', { free: fmtBytes(v.free) }) })
                ])
            ]));
        });
    };

    /** A volume is usually outside the sandbox; say so instead of doing nothing. */
    FM.openVolume = async function (v) {
        try {
            await this.api('GET', '/list?path=' + encodeURIComponent(v.path) + '&show_hidden=false');
            this.navigate(v.path);
        } catch (e) {
            // api() already surfaced the server's message (which names the
            // allowed roots); add the reason this click appeared to do nothing.
            toast(T('fm.vol_outside'), 'warn');
        }
    };

    // ══════════════════════════════════════════════════════════════════
    // Storage scan — POST /usage/scan, poll, cancel
    // ══════════════════════════════════════════════════════════════════

    FM._scan = null;

    FM.openScan = function (path) {
        var target = path || this.selectedItem || this.currentPath;
        if (!target) { toast(T('fm.no_selection'), 'warn'); return; }

        var state = {
            path: target, id: null, status: 'idle', startedAt: 0,
            lastFiles: -1, lastBytes: -1, lastChangeAt: 0, token: 0, closed: false
        };
        FM._scan = state;

        var m = openModal(T('fm.scan_title'), {
            onClose: function () { state.closed = true; FM._stopScan(state, true); }
        });
        state.modal = m;

        m.body.appendChild(h('div', { class: 'fmx-muted fmx-mono', text: T('fm.scan_for', { path: target }), style: { marginBottom: '12px' } }));

        state.statusEl = h('div', { class: 'fmx-row', style: { marginBottom: '8px', fontSize: '13px', fontWeight: '600' } });
        state.barWrap = h('div', { class: 'fmx-bar', style: { marginBottom: '8px' } });
        state.barFill = h('div', { class: 'fmx-bar-fill', style: { width: '0%' } });
        state.barWrap.appendChild(state.barFill);
        state.metaEl = h('div', { class: 'fmx-muted', style: { marginBottom: '4px' } });
        state.currentEl = h('div', { class: 'fmx-muted fmx-mono', style: { marginBottom: '4px', minHeight: '16px' } });
        state.stallEl = h('div', { class: 'fmx-muted', style: { color: 'var(--fmx-orange,#f59e0b)', minHeight: '16px' } });
        state.resultEl = h('div', { style: { marginTop: '16px' } });

        m.body.appendChild(h('div', { class: 'fmx-sec' }, [
            state.statusEl, state.barWrap, state.metaEl, state.currentEl, state.stallEl
        ]));
        m.body.appendChild(state.resultEl);

        state.cancelBtn = h('button', {
            class: 'fmx-btn danger', type: 'button', text: T('fm.cancel'), disabled: true,
            onclick: function () { FM._cancelScan(state); }
        });
        state.startBtn = h('button', {
            class: 'fmx-btn primary', type: 'button', text: T('fm.scan_start'),
            onclick: function () { FM._startScan(state); }
        });
        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(state.cancelBtn);
        m.foot.appendChild(state.startBtn);

        this._startScan(state);
    };

    FM._startScan = async function (state) {
        state.token++;
        var token = state.token;
        state.status = 'running';
        state.startedAt = Date.now();
        state.lastChangeAt = Date.now();
        state.lastFiles = -1;
        state.lastBytes = -1;
        clear(state.resultEl);
        state.startBtn.disabled = true;
        state.cancelBtn.disabled = true;
        state.barWrap.classList.add('indet');
        state.barFill.style.width = '0%';
        state.statusEl.textContent = T('fm.scan_running');
        state.stallEl.textContent = '';
        state.currentEl.textContent = '';
        state.metaEl.textContent = '';

        // A ticker independent of the poll responses: the elapsed time must keep
        // moving even while a single scandir call blocks the server for 30s, or
        // the panel reads as frozen.
        clearInterval(state.ticker);
        state.ticker = setInterval(function () { FM._renderScanTick(state); }, 1000);
        // Paint the zero state immediately: waiting for the first poll left the
        // counters blank for the first half second, which reads as a hang.
        state.snapshot = null;
        this._renderScanTick(state);

        try {
            var res = await this.feat('POST', '/usage/scan', { path: state.path });
            if (state.token !== token || state.closed) return;
            if (!res || !res.scan_id) {
                throw new Error(T('fm.err_shape', { field: 'scan_id', got: middleTrim(JSON.stringify(res), 200) }));
            }
            state.id = res.scan_id;
            state.cancelBtn.disabled = false;
            this._pollScan(state, token);
        } catch (e) {
            if (state.token !== token || state.closed) return;
            this._scanFailed(state, e.message);
        }
    };

    FM._pollScan = async function (state, token) {
        var failures = 0, lastError = '';
        var interval = 500;
        while (!state.closed && state.token === token && state.status === 'running') {
            var data;
            try {
                data = await this.feat('GET', '/usage/scan/' + encodeURIComponent(state.id));
                failures = 0;
            } catch (e) {
                failures++;
                lastError = e.message;
                if (e.status === 404) {
                    // The scan id expired or the server restarted. Retrying can
                    // never recover it, and the server's message already says to
                    // scan again — showing it now beats three silent retries.
                    this._scanFailed(state, lastError);
                    return;
                }
                if (failures >= 3) {
                    this._scanFailed(state, T('fm.scan_poll_failed', { n: failures, msg: lastError }));
                    return;
                }
                await sleep(interval);
                continue;
            }
            if (state.closed || state.token !== token) return;
            this._renderScan(state, data);

            if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
                state.status = data.status;
                clearInterval(state.ticker);
                state.barWrap.classList.remove('indet');
                state.cancelBtn.disabled = true;
                state.startBtn.disabled = false;
                state.startBtn.textContent = T('fm.retry');

                if (data.status === 'error') {
                    state.statusEl.textContent = T('fm.scan_error');
                    state.barFill.style.width = '100%';
                    state.barFill.className = 'fmx-bar-fill crit';
                    clear(state.resultEl);
                    state.resultEl.appendChild(h('div', { class: 'fmx-note err', text: data.error || T('fm.scan_error') }));
                } else if (data.status === 'cancelled') {
                    state.statusEl.textContent = T('fm.scan_cancelled');
                    state.barFill.style.width = '0%';
                } else {
                    state.statusEl.textContent = T('fm.scan_done');
                    state.barFill.style.width = '100%';
                    this._renderScanResult(state, data);
                }
                return;
            }
            // Back off once a scan is clearly long-running: a 500 ms poll for
            // twenty minutes is thousands of pointless requests.
            if (Date.now() - state.startedAt > 30000) interval = 1500;
            if (Date.now() - state.startedAt > 300000) interval = 3000;
            await sleep(interval);
            if (state.closed || state.token !== token) return;
        }
    };

    FM._renderScan = function (state, data) {
        var files = Number(data.scanned_files || 0);
        var bytes = Number(data.total_bytes || 0);
        if (files !== state.lastFiles || bytes !== state.lastBytes) {
            state.lastFiles = files;
            state.lastBytes = bytes;
            state.lastChangeAt = Date.now();
        }
        state.snapshot = data;
        this._renderScanTick(state);
    };

    /**
     * Bytes and file count lead; the percentage is secondary and explicitly
     * labelled an estimate. A scan that reports 0 % for ten minutes while
     * walking node_modules is working correctly, and a bare progress bar is the
     * one thing that makes it look broken.
     */
    FM._renderScanTick = function (state) {
        var d = state.snapshot || {};
        var elapsed = state.startedAt ? Date.now() - state.startedAt : 0;
        var files = Number(d.scanned_files || 0);
        var bytes = Number(d.total_bytes || 0);
        var secs = Math.max(1, elapsed / 1000);

        var parts = [
            fmtBytes(bytes),
            (d.scanned_dirs !== undefined && d.scanned_dirs !== null)
                ? T('fm.scan_counts', { files: fmtInt(files), dirs: fmtInt(d.scanned_dirs) })
                : T('fm.scan_files_only', { files: fmtInt(files) }),
            T('fm.scan_elapsed', { t: fmtDuration(elapsed) })
        ];
        if (state.status === 'running' && files > 0) {
            parts.push(T('fm.scan_rate', { n: fmtInt(Math.round(files / secs)) }));
        }
        var pct = Number(d.percent);
        if (!isNaN(pct) && pct > 0) parts.push(T('fm.scan_percent', { p: Math.round(pct) }));
        state.metaEl.textContent = parts.join('  ·  ');
        state.metaEl.title = fmtBytesExact(bytes);

        if (state.status === 'running' && (isNaN(pct) || pct <= 0)) {
            state.barWrap.classList.add('indet');
            state.barFill.style.width = '0%';
        } else if (!isNaN(pct) && pct > 0) {
            state.barWrap.classList.remove('indet');
            state.barFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
        }

        state.currentEl.textContent = d.current ? T('fm.scan_current', { p: middleTrim(d.current, 90) }) : '';
        state.currentEl.title = d.current || '';

        if (state.status === 'running') {
            var stalledFor = Math.floor((Date.now() - state.lastChangeAt) / 1000);
            state.stallEl.textContent = stalledFor >= 8 ? T('fm.scan_stalled', { s: stalledFor }) : '';
        } else {
            state.stallEl.textContent = '';
        }
    };

    FM._renderScanResult = function (state, data) {
        clear(state.resultEl);
        var total = Number(data.total_bytes || 0);
        var children = Array.isArray(data.children) ? data.children : [];
        var largest = Array.isArray(data.largest) ? data.largest : [];

        var childSec = h('div', { class: 'fmx-sec' }, [h('h3', { class: 'fmx-sec-title', text: T('fm.scan_children') })]);
        if (!children.length) {
            childSec.appendChild(h('div', { class: 'fmx-muted', text: T('fm.scan_none') }));
        } else {
            var rows = children.map(function (c) {
                var pct = Number(c.percent);
                if (isNaN(pct)) pct = total > 0 ? (Number(c.bytes) / total) * 100 : 0;
                var nameRow = h('div', { class: 'fmx-row', style: { gap: '6px' } });
                nameRow.appendChild(spriteIcon(c.is_dir ? 'i-folder' : 'i-file', 'fm-ico'));
                nameRow.appendChild(h('span', { text: c.name, title: c.path, style: { wordBreak: 'break-all' } }));
                return h('tr', {}, [
                    h('td', {}, [
                        nameRow,
                        h('div', { class: 'fmx-bar', style: { marginTop: '4px', height: '5px' } }, [
                            h('div', { class: 'fmx-bar-fill', style: { width: Math.max(0, Math.min(100, pct)) + '%' } })
                        ])
                    ]),
                    h('td', { class: 'num', text: fmtBytes(c.bytes), title: fmtBytesExact(c.bytes) }),
                    h('td', { class: 'num', text: c.file_count === undefined || c.file_count === null ? '—' : fmtInt(c.file_count) }),
                    h('td', { class: 'num' }, [
                        c.is_dir ? h('button', {
                            class: 'fmx-btn ghost', type: 'button', text: T('fm.scan_drill'),
                            style: { padding: '2px 8px', fontSize: '11px' },
                            onclick: function () { state.path = c.path; FM._startScan(state); }
                        }) : null
                    ])
                ]);
            });
            childSec.appendChild(h('div', { class: 'fmx-scroll' }, [
                h('table', { class: 'fmx-table' }, [
                    h('thead', {}, [h('tr', {}, [
                        h('th', { text: T('fm.tbl_name') }),
                        h('th', { text: T('fm.tbl_size') }),
                        h('th', { text: T('fm.tbl_count') }),
                        h('th', { text: '' })
                    ])]),
                    h('tbody', {}, rows)
                ])
            ]));
        }
        state.resultEl.appendChild(childSec);

        if (largest.length) {
            var bigRows = largest.map(function (f) {
                return h('tr', {}, [
                    h('td', {}, [h('span', { text: f.name, title: f.path, style: { wordBreak: 'break-all' } })]),
                    h('td', { class: 'num', text: fmtBytes(f.bytes), title: fmtBytesExact(f.bytes) }),
                    h('td', { class: 'num', text: f.modified || '—' }),
                    h('td', { class: 'num' }, [
                        h('button', {
                            class: 'fmx-btn ghost', type: 'button', text: T('fm.scan_reveal'),
                            style: { padding: '2px 8px', fontSize: '11px' },
                            onclick: function () {
                                state.modal.close();
                                FM.navigate(parentOf(f.path));
                            }
                        })
                    ])
                ]);
            });
            state.resultEl.appendChild(h('div', { class: 'fmx-sec' }, [
                h('h3', { class: 'fmx-sec-title', text: T('fm.scan_largest') + ' (' + largest.length + ')' }),
                h('div', { class: 'fmx-scroll' }, [
                    h('table', { class: 'fmx-table' }, [
                        h('thead', {}, [h('tr', {}, [
                            h('th', { text: T('fm.tbl_name') }),
                            h('th', { text: T('fm.tbl_size') }),
                            h('th', { text: T('fm.tbl_modified') }),
                            h('th', { text: '' })
                        ])]),
                        h('tbody', {}, bigRows)
                    ])
                ])
            ]));
        }
    };

    FM._scanFailed = function (state, msg) {
        state.status = 'error';
        clearInterval(state.ticker);
        state.barWrap.classList.remove('indet');
        state.barFill.style.width = '0%';
        state.statusEl.textContent = T('fm.scan_error');
        state.cancelBtn.disabled = true;
        state.startBtn.disabled = false;
        state.startBtn.textContent = T('fm.retry');
        clear(state.resultEl);
        state.resultEl.appendChild(h('div', { class: 'fmx-note err', text: msg }));
    };

    FM._cancelScan = async function (state) {
        if (!state.id) return;
        state.cancelBtn.disabled = true;
        try {
            await this.feat('POST', '/usage/scan/' + encodeURIComponent(state.id) + '/cancel', {});
            state.status = 'cancelled';
            clearInterval(state.ticker);
            state.barWrap.classList.remove('indet');
            state.statusEl.textContent = T('fm.scan_cancelled');
            state.startBtn.disabled = false;
            state.startBtn.textContent = T('fm.retry');
        } catch (e) {
            state.cancelBtn.disabled = false;
            toast(T('fm.scan_cancel_failed', { msg: e.message }), 'error');
        }
    };

    /** Closing the panel abandons the polling loop, so the job is cancelled too
     *  — otherwise a server-side walk keeps burning I/O with nobody watching. */
    FM._stopScan = function (state, alsoCancel) {
        clearInterval(state.ticker);
        state.token++;
        if (alsoCancel && state.id && state.status === 'running') {
            this.feat('POST', '/usage/scan/' + encodeURIComponent(state.id) + '/cancel', {})
                .catch(function (e) { toast(T('fm.scan_cancel_failed', { msg: e.message }), 'warn'); });
        }
    };

    // ══════════════════════════════════════════════════════════════════
    // Cleanup — scan, dry run, typed confirmation, apply
    // ══════════════════════════════════════════════════════════════════

    function riskBadge(risk) {
        var cls = risk === 'safe' ? 'safe' : (risk === 'review' ? 'review' : 'unknown');
        var label = risk === 'safe' ? T('fm.cleanup_risk_safe')
            : (risk === 'review' ? T('fm.cleanup_risk_review') : T('fm.cleanup_risk_unknown'));
        return h('span', { class: 'fmx-badge ' + cls, text: label });
    }

    /** Renders up to `cap` paths, then states how many were not shown. */
    function pathList(items, cap, mapper) {
        var list = h('ul', { class: 'fmx-list' });
        var shown = Math.min(items.length, cap);
        for (var i = 0; i < shown; i++) list.appendChild(h('li', {}, mapper(items[i])));
        var wrap = h('div', { class: 'fmx-scroll' }, [list]);
        if (items.length > shown) {
            return h('div', {}, [wrap, h('div', { class: 'fmx-muted', style: { marginTop: '4px' }, text: T('fm.cleanup_more', { n: items.length - shown }) })]);
        }
        return wrap;
    }

    FM.openCleanup = function (path) {
        var target = path || this.currentPath;
        if (!target) { toast(T('fm.no_selection'), 'warn'); return; }

        var state = { path: target, categories: [], selected: {}, preview: null, controller: null, timer: null };
        var m = openModal(T('fm.cleanup_title'), {
            onClose: function () {
                clearInterval(state.timer);
                if (state.controller) state.controller.abort();
            }
        });
        state.modal = m;

        m.body.appendChild(h('div', { class: 'fmx-muted fmx-mono', text: target, style: { marginBottom: '12px' } }));
        state.listEl = h('div');
        m.body.appendChild(state.listEl);

        state.summaryEl = h('span', { class: 'fmx-muted', text: T('fm.cleanup_nothing_selected') });
        state.previewBtn = h('button', {
            class: 'fmx-btn primary', type: 'button', text: T('fm.cleanup_preview'), disabled: true,
            onclick: function () { FM._cleanupPreview(state); }
        });
        m.foot.appendChild(state.summaryEl);
        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(state.previewBtn);

        this._cleanupScan(state);
    };

    FM._cleanupScan = async function (state) {
        clear(state.listEl);
        var started = Date.now();
        var statusEl = h('div', { class: 'fmx-muted', style: { marginBottom: '8px' } });
        var bar = h('div', { class: 'fmx-bar indet' });
        var stopBtn = h('button', {
            class: 'fmx-btn ghost', type: 'button', text: T('fm.cleanup_stop'),
            style: { marginTop: '10px' },
            onclick: function () { if (state.controller) state.controller.abort(); }
        });
        state.listEl.appendChild(h('div', { class: 'fmx-sec' }, [statusEl, bar, stopBtn]));

        // The contract defines /cleanup/scan as a plain GET, so this request can
        // legitimately run for minutes. The elapsed counter is the only proof
        // for the user that it has not hung.
        var tick = function () { statusEl.textContent = T('fm.cleanup_scanning', { t: fmtDuration(Date.now() - started) }); };
        tick();
        clearInterval(state.timer);
        state.timer = setInterval(tick, 1000);
        state.controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;

        try {
            var data = await this.feat('GET', '/cleanup/scan?path=' + encodeURIComponent(state.path), null,
                state.controller ? state.controller.signal : undefined);
            clearInterval(state.timer);
            if (!Array.isArray(data.categories)) {
                throw new Error(T('fm.err_shape', { field: 'categories', got: middleTrim(JSON.stringify(data), 200) }));
            }
            state.categories = data.categories;
            this._renderCleanupCategories(state);
        } catch (e) {
            clearInterval(state.timer);
            clear(state.listEl);
            state.listEl.appendChild(h('div', { class: 'fmx-note err' }, [
                h('div', { text: e.message }),
                h('button', {
                    class: 'fmx-btn', type: 'button', text: T('fm.retry'), style: { marginTop: '10px' },
                    onclick: function () { FM._cleanupScan(state); }
                })
            ]));
        }
    };

    FM._renderCleanupCategories = function (state) {
        clear(state.listEl);
        if (!state.categories.length) {
            state.listEl.appendChild(h('div', { class: 'fmx-note', text: T('fm.cleanup_none', { p: state.path }) }));
            return;
        }

        // Largest first: leading with __pycache__ (measured at 0.016 % of the
        // tree) makes the whole feature look pointless.
        var cats = state.categories.slice().sort(function (a, b) { return Number(b.bytes || 0) - Number(a.bytes || 0); });

        cats.forEach(function (cat) {
            var box = h('div', { class: 'fmx-cat' });
            var cb = h('input', {
                type: 'checkbox', id: 'fmxcat_' + cat.id,
                // Nothing is pre-selected. Duplicates in particular are
                // byte-identical yet load-bearing (locale packs, render frame
                // sequences), so a default tick would invite a destructive click.
                onchange: function () {
                    if (cb.checked) state.selected[cat.id] = cat; else delete state.selected[cat.id];
                    box.classList.toggle('on', cb.checked);
                    state.preview = null;
                    FM._updateCleanupSummary(state);
                }
            });
            var head = h('div', { class: 'fmx-cat-head' }, [
                cb,
                h('div', { style: { flex: '1', minWidth: '0' } }, [
                    h('label', { class: 'fmx-cat-name', for: 'fmxcat_' + cat.id, style: { cursor: 'pointer' } }, [
                        h('span', { text: cat.label || cat.id }),
                        riskBadge(cat.risk),
                        h('span', { class: 'fmx-muted', text: T('fm.cleanup_cat_meta', { n: fmtInt(cat.count), b: fmtBytes(cat.bytes) }), title: fmtBytesExact(cat.bytes) })
                    ]),
                    cat.description ? h('div', { class: 'fmx-muted', style: { marginTop: '4px', lineHeight: '1.5' }, text: cat.description }) : null
                ])
            ]);
            box.appendChild(head);

            var samples = Array.isArray(cat.samples) ? cat.samples : [];
            if (samples.length) {
                box.appendChild(h('div', { style: { marginTop: '8px' } }, [
                    h('div', { class: 'fmx-muted', style: { marginBottom: '4px' }, text: T('fm.cleanup_samples') }),
                    pathList(samples, 12, function (s) { return h('span', { text: String(s) }); })
                ]));
            }
            state.listEl.appendChild(box);
        });
        this._updateCleanupSummary(state);
    };

    FM._cleanupTotals = function (state) {
        var ids = Object.keys(state.selected);
        var bytes = 0, count = 0, hasReview = false, labels = [];
        ids.forEach(function (id) {
            var c = state.selected[id];
            bytes += Number(c.bytes || 0);
            count += Number(c.count || 0);
            if (c.risk === 'review') hasReview = true;
            labels.push(c.label || c.id);
        });
        return { ids: ids, bytes: bytes, count: count, hasReview: hasReview, labels: labels };
    };

    FM._updateCleanupSummary = function (state) {
        var t = this._cleanupTotals(state);
        state.previewBtn.disabled = t.ids.length === 0;
        state.summaryEl.textContent = t.ids.length
            ? T('fm.cleanup_selected', { c: t.ids.length, n: fmtInt(t.count), b: fmtBytes(t.bytes) })
            : T('fm.cleanup_nothing_selected');
    };

    FM._cleanupPreview = async function (state) {
        var t = this._cleanupTotals(state);
        if (!t.ids.length) { toast(T('fm.cleanup_nothing_selected'), 'warn'); return; }

        state.previewBtn.disabled = true;
        state.previewBtn.textContent = T('fm.cleanup_previewing');
        var res;
        try {
            res = await this.feat('POST', '/cleanup/apply', {
                path: state.path, category_ids: t.ids, dry_run: true
            });
        } catch (e) {
            toast(e.message, 'error');
            state.previewBtn.disabled = false;
            state.previewBtn.textContent = T('fm.cleanup_preview');
            return;
        }
        state.previewBtn.disabled = false;
        state.previewBtn.textContent = T('fm.cleanup_preview');

        var deleted = Array.isArray(res.deleted) ? res.deleted : [];
        var failed = Array.isArray(res.failed) ? res.failed : [];
        state.preview = { result: res, planned: deleted.length, freed: Number(res.freed || 0), ids: t.ids };

        var m = openModal(T('fm.cleanup_preview_title'));
        if (res.dry_run === false) {
            // The server ignored dry_run — say it loudly, this is not a preview.
            m.body.appendChild(h('div', { class: 'fmx-note err', text: T('fm.cleanup_dryrun_ignored') }));
        }
        m.body.appendChild(h('div', { class: 'fmx-note ok', text: T('fm.cleanup_preview_result', { n: fmtInt(deleted.length), b: fmtBytes(res.freed) }) }));

        if (!deleted.length) {
            m.body.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.cleanup_preview_empty') }));
        } else {
            m.body.appendChild(h('div', { class: 'fmx-sec' }, [
                h('h3', { class: 'fmx-sec-title', text: T('fm.cleanup_deleted_list') }),
                pathList(deleted, 300, function (d) {
                    return [h('span', { text: d.path || String(d) }),
                            h('span', { class: 'fmx-muted', text: '  ' + fmtBytes(d.bytes) })];
                })
            ]));
        }
        if (failed.length) {
            m.body.appendChild(h('div', { class: 'fmx-sec' }, [
                h('h3', { class: 'fmx-sec-title', text: T('fm.cleanup_failed_list') + ' (' + failed.length + ')' }),
                pathList(failed, 200, function (f) {
                    return [h('span', { text: f.path || String(f) }),
                            h('span', { style: { color: 'var(--fmx-red,#ef4444)' }, text: ' — ' + (f.error || '') })];
                })
            ]));
        }

        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(h('button', { class: 'fmx-btn ghost', type: 'button', text: T('fm.cancel'), onclick: function () { m.close(); } }));
        m.foot.appendChild(h('button', {
            class: 'fmx-btn danger', type: 'button', text: T('fm.cleanup_apply'),
            disabled: deleted.length === 0,
            onclick: function () { m.close(); FM._cleanupConfirm(state, t, deleted, res); }
        }));
    };

    FM._cleanupConfirm = async function (state, totals, plannedDeleted, previewRes) {
        var word = T('fm.cleanup_confirm_word');
        var freed = Number(previewRes.freed || 0);
        var blocks = [
            h('div', { class: 'fmx-mono fmx-muted', text: state.path, style: { marginBottom: '10px' } })
        ];
        if (totals.hasReview) {
            blocks.push(h('div', { class: 'fmx-note warn', text: T('fm.cleanup_confirm_review') }));
        }
        blocks.push(pathList(plannedDeleted, 40, function (d) {
            return [h('span', { text: d.path || String(d) }),
                    h('span', { class: 'fmx-muted', text: '  ' + fmtBytes(d.bytes) })];
        }));

        var ok = await confirmDialog({
            title: T('fm.cleanup_confirm_title', { n: fmtInt(plannedDeleted.length) }),
            body: T('fm.cleanup_confirm_body', {
                n: fmtInt(plannedDeleted.length),
                cats: totals.labels.join(', '),
                b: fmtBytes(freed)
            }),
            blocks: blocks,
            danger: true,
            wide: true,
            typeWord: word,
            acceptLabel: T('fm.cleanup_apply')
        });
        if (!ok) return;
        this._cleanupApply(state, totals, plannedDeleted.length);
    };

    FM._cleanupApply = async function (state, totals, plannedCount) {
        var m = openModal(T('fm.cleanup_title'), { sticky: true });
        m.body.appendChild(h('div', { class: 'fmx-muted', text: T('fm.cleanup_applying'), style: { marginBottom: '8px' } }));
        m.body.appendChild(h('div', { class: 'fmx-bar indet' }));

        var res;
        try {
            res = await this.feat('POST', '/cleanup/apply', {
                path: state.path, category_ids: totals.ids, dry_run: false
            });
        } catch (e) {
            clear(m.body);
            m.setSticky(false);
            m.body.appendChild(h('div', { class: 'fmx-note err', text: e.message }));
            m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
            m.foot.appendChild(h('button', { class: 'fmx-btn', type: 'button', text: T('fm.close'), onclick: function () { m.close(); } }));
            return;
        }

        clear(m.body);
        m.setSticky(false);
        var deleted = Array.isArray(res.deleted) ? res.deleted : [];
        var failed = Array.isArray(res.failed) ? res.failed : [];
        var freed = Number(res.freed || 0);

        if (res.dry_run === true) {
            // Reporting success here would be the green-checkmark-for-work-that-
            // did-not-happen failure this project forbids.
            m.body.appendChild(h('div', { class: 'fmx-note err', text: T('fm.cleanup_dryrun_flag') }));
        }

        var summaryText, summaryCls;
        if (failed.length && !deleted.length) {
            summaryText = T('fm.cleanup_all_failed', { f: failed.length });
            summaryCls = 'err';
        } else if (failed.length) {
            summaryText = T('fm.cleanup_partial', { n: fmtInt(deleted.length), b: fmtBytes(freed), f: failed.length });
            summaryCls = 'warn';
        } else {
            summaryText = T('fm.cleanup_done', { n: fmtInt(deleted.length), b: fmtBytes(freed) });
            summaryCls = 'ok';
        }
        m.body.appendChild(h('div', { class: 'fmx-note ' + summaryCls, text: summaryText, title: fmtBytesExact(freed) }));

        // The preview and the real run must describe the same plan. When they
        // do not, the tree changed underneath and the user deleted something
        // they never saw — that has to be stated, not averaged away.
        var handled = deleted.length + failed.length;
        if (plannedCount !== handled) {
            m.body.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.cleanup_divergence', { p: fmtInt(plannedCount), a: fmtInt(handled) }) }));
        }

        if (failed.length) {
            m.body.appendChild(h('div', { class: 'fmx-sec' }, [
                h('h3', { class: 'fmx-sec-title', text: T('fm.cleanup_failed_list') + ' (' + failed.length + ')' }),
                pathList(failed, 300, function (f) {
                    return [h('span', { text: f.path || String(f) }),
                            h('span', { style: { color: 'var(--fmx-red,#ef4444)' }, text: ' — ' + (f.error || T('fm.tbl_reason')) })];
                })
            ]));
        }
        if (deleted.length) {
            m.body.appendChild(h('div', { class: 'fmx-sec' }, [
                h('h3', { class: 'fmx-sec-title', text: T('fm.cleanup_deleted_list') + ' (' + deleted.length + ')' }),
                pathList(deleted, 300, function (d) {
                    return [h('span', { text: d.path || String(d) }),
                            h('span', { class: 'fmx-muted', text: '  ' + fmtBytes(d.bytes) })];
                })
            ]));
        }

        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(h('button', {
            class: 'fmx-btn primary', type: 'button', text: T('fm.close'),
            onclick: function () {
                m.close();
                if (state.modal) state.modal.close();
                FM.refresh();
                FM.loadVolumes();
            }
        }));
    };

    // ══════════════════════════════════════════════════════════════════
    // Permissions — GET /permissions, POST /permissions
    // ══════════════════════════════════════════════════════════════════

    var PERM_GROUPS = [
        { key: 'user', label: 'fm.perm_who_user', bits: { r: 0x100, w: 0x80, x: 0x40 } },   // 0o400 0o200 0o100
        { key: 'group_perms', label: 'fm.perm_who_group', bits: { r: 0x20, w: 0x10, x: 0x8 } }, // 0o40 0o20 0o10
        { key: 'other', label: 'fm.perm_who_other', bits: { r: 0x4, w: 0x2, x: 0x1 } }
    ];

    function pad4Octal(n) {
        var s = (n >>> 0).toString(8);
        while (s.length < 4) s = '0' + s;
        return s;
    }

    FM.openPermissions = async function (path) {
        var target = path || this.selectedItem || this.currentPath;
        if (!target) { toast(T('fm.no_selection'), 'warn'); return; }

        var m = openModal(T('fm.perm_title'));
        m.body.appendChild(h('div', { class: 'fmx-muted fmx-mono', text: target, style: { marginBottom: '12px' } }));
        var content = h('div');
        m.body.appendChild(content);
        content.appendChild(h('div', { class: 'fmx-muted', text: T('fm.loading') }));

        var data;
        try {
            data = await this.feat('GET', '/permissions?path=' + encodeURIComponent(target));
        } catch (e) {
            clear(content);
            content.appendChild(h('div', { class: 'fmx-note err' }, [
                h('div', { text: e.message }),
                h('button', {
                    class: 'fmx-btn', type: 'button', text: T('fm.retry'), style: { marginTop: '10px' },
                    onclick: function () { m.close(); FM.openPermissions(target); }
                })
            ]));
            return;
        }

        clear(content);
        content.appendChild(h('div', { class: 'fmx-row', style: { marginBottom: '10px' } }, [
            h('span', { class: 'fmx-muted', text: T('fm.perm_platform', { p: data.platform || '?' }) }),
            h('span', {
                class: 'fmx-muted',
                text: T('fm.perm_effective', {
                    r: data.readable ? T('fm.perm_yes') : T('fm.perm_no'),
                    w: data.writable ? T('fm.perm_yes') : T('fm.perm_no'),
                    x: data.executable ? T('fm.perm_yes') : T('fm.perm_no')
                })
            })
        ]));

        if (data.reason) {
            content.appendChild(h('div', { class: 'fmx-note', text: T('fm.perm_reason', { reason: data.reason }) }));
        }

        // Only the POSIX branch is an editor; the others are read-only and add
        // their own Close button so the footer is never an empty bar.
        var closeOnly = function () {
            m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
            m.foot.appendChild(h('button', { class: 'fmx-btn', type: 'button', text: T('fm.close'), onclick: function () { m.close(); } }));
        };

        if (data.supported === false) {
            content.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.perm_unsupported', { reason: data.reason || '—' }) }));
            closeOnly();
            return;
        }

        if (data.posix) {
            this._renderPosixPerms(m, content, target, data);
        } else if (data.windows) {
            this._renderWindowsPerms(content, data);
            closeOnly();
        } else {
            content.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.err_shape', { field: 'posix/windows', got: middleTrim(JSON.stringify(data), 200) }) }));
            closeOnly();
        }
    };

    /** Windows is read-only by design — see the header note on deny ACEs. */
    FM._renderWindowsPerms = function (content, data) {
        var w = data.windows;
        content.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.perm_win_readonly') }));
        content.appendChild(kv(T('fm.perm_win_owner'), w.owner));

        var entries = Array.isArray(w.entries) ? w.entries : [];
        if (!entries.length) {
            // An empty DACL means nobody has access; a failed read means unknown.
            // Rendering either as a blank table would invent a fact.
            content.appendChild(h('div', { class: 'fmx-note err', text: T('fm.perm_win_no_entries') }));
            return;
        }
        content.appendChild(h('div', { class: 'fmx-sec', style: { marginTop: '14px' } }, [
            h('h3', { class: 'fmx-sec-title', text: T('fm.perm_win_entries') + ' (' + entries.length + ')' }),
            h('div', { class: 'fmx-scroll' }, [
                h('table', { class: 'fmx-table' }, [
                    h('thead', {}, [h('tr', {}, [
                        h('th', { text: T('fm.perm_col_identity') }),
                        h('th', { text: T('fm.perm_col_rights') }),
                        h('th', { text: T('fm.perm_col_type') }),
                        h('th', { text: T('fm.perm_col_inherited') })
                    ])]),
                    h('tbody', {}, entries.map(function (e) {
                        var deny = String(e.type || '').toLowerCase().indexOf('den') !== -1;
                        return h('tr', {}, [
                            h('td', { text: e.identity || '—' }),
                            h('td', { class: 'fmx-mono', text: e.rights || '—' }),
                            h('td', {}, [h('span', { class: 'fmx-badge ' + (deny ? 'err' : 'safe'), text: e.type || '—' })]),
                            h('td', { text: e.inherited ? T('fm.perm_yes') : T('fm.perm_no') })
                        ]);
                    }))
                ])
            ])
        ]));
    };

    FM._renderPosixPerms = function (m, content, target, data) {
        var p = data.posix;
        var octal = Number(p.octal);
        if (isNaN(octal)) octal = parseInt(String(p.mode || '0'), 8) || 0;
        // S_ISUID|S_ISGID|S_ISVTX. Kept aside so the 9 checkboxes below cannot
        // strip them when the mode is recomposed.
        var special = octal & 0o7000;

        content.appendChild(kv(T('fm.perm_owner'), p.owner));
        content.appendChild(kv(T('fm.perm_group'), p.group));

        if (special) {
            // Echoing a 3-digit mode back into chmod would silently strip
            // setuid/setgid/sticky from the file.
            content.appendChild(h('div', { class: 'fmx-note warn', text: T('fm.perm_special_bits', { bits: pad4Octal(special) }) }));
        }

        var boxes = {};
        var modeInput = h('input', { class: 'fmx-input', type: 'text', value: p.mode || pad4Octal(octal), maxLength: 5, style: { maxWidth: '140px' } });

        var readChecks = function () {
            var perms = 0;
            PERM_GROUPS.forEach(function (g) {
                ['r', 'w', 'x'].forEach(function (bit) {
                    if (boxes[g.key + bit].checked) perms |= g.bits[bit];
                });
            });
            return perms;
        };
        var syncFromChecks = function () {
            modeInput.value = pad4Octal(special | readChecks());
        };
        var syncFromInput = function () {
            var v = String(modeInput.value).trim();
            if (!/^[0-7]{3,4}$/.test(v)) return false;
            var n = parseInt(v, 8);
            special = n & 0o7000;
            PERM_GROUPS.forEach(function (g) {
                ['r', 'w', 'x'].forEach(function (bit) {
                    boxes[g.key + bit].checked = (n & g.bits[bit]) !== 0;
                });
            });
            return true;
        };
        modeInput.addEventListener('change', function () {
            if (!syncFromInput()) toast(T('fm.perm_invalid_mode'), 'error');
        });

        var grid = h('div', { class: 'fmx-grid3', style: { marginTop: '12px' } });
        PERM_GROUPS.forEach(function (g) {
            var src = p[g.key] || {};
            var box = h('div', { class: 'fmx-perm-box' }, [
                h('div', { style: { fontWeight: '600', fontSize: '12.5px', marginBottom: '6px' }, text: T(g.label) })
            ]);
            [['r', 'fm.perm_r'], ['w', 'fm.perm_w'], ['x', 'fm.perm_x']].forEach(function (pair) {
                var bit = pair[0];
                var checked = (src[bit] !== undefined) ? !!src[bit] : ((octal & g.bits[bit]) !== 0);
                var cb = h('input', { type: 'checkbox', checked: checked, onchange: syncFromChecks });
                boxes[g.key + bit] = cb;
                box.appendChild(h('label', {}, [cb, h('span', { text: T(pair[1]) })]));
            });
            grid.appendChild(box);
        });
        content.appendChild(grid);

        var recursive = h('input', { type: 'checkbox' });
        content.appendChild(h('div', { class: 'fmx-row', style: { marginTop: '14px' } }, [
            h('label', { class: 'fmx-row', style: { gap: '8px', cursor: 'pointer', fontSize: '13px' } }, [
                h('span', { text: T('fm.perm_mode') }), modeInput
            ]),
            h('label', { class: 'fmx-row', style: { gap: '8px', cursor: 'pointer', fontSize: '13px' } }, [
                recursive, h('span', { text: T('fm.perm_recursive') })
            ])
        ]));

        var resultEl = h('div', { style: { marginTop: '14px' } });
        content.appendChild(resultEl);

        var applyBtn = h('button', {
            class: 'fmx-btn primary', type: 'button', text: T('fm.perm_apply'),
            onclick: async function () {
                var v = String(modeInput.value).trim();
                if (!/^[0-7]{3,4}$/.test(v)) { toast(T('fm.perm_invalid_mode'), 'error'); return; }
                var mode = pad4Octal(parseInt(v, 8));
                var numeric = parseInt(v, 8);

                // Without owner-execute a recursive chmod strips the traverse
                // bit from every directory, making the subtree unenterable —
                // including for the operation that would undo it.
                if (recursive.checked && (numeric & 0x40) === 0) {
                    var go = await confirmDialog({
                        title: T('fm.perm_recursive_warn_title'),
                        body: T('fm.perm_recursive_warn_body', { mode: mode }),
                        danger: true
                    });
                    if (!go) return;
                }

                applyBtn.disabled = true;
                applyBtn.textContent = T('fm.perm_applying');
                clear(resultEl);
                try {
                    var res = await FM.feat('POST', '/permissions', {
                        path: target, recursive: !!recursive.checked, posix_mode: mode, windows: null
                    });
                    var failed = Array.isArray(res.failed) ? res.failed : [];
                    var bad = res.status === 'error' || failed.length > 0;
                    resultEl.appendChild(h('div', {
                        class: 'fmx-note ' + (bad ? 'err' : 'ok'),
                        text: (res.message || T('fm.perm_applied', { applied: res.applied || mode }))
                    }));
                    if (failed.length) {
                        resultEl.appendChild(h('div', { class: 'fmx-sec', style: { marginTop: '10px' } }, [
                            h('h3', { class: 'fmx-sec-title', text: T('fm.perm_failed_list') + ' (' + failed.length + ')' }),
                            pathList(failed, 200, function (f) {
                                if (typeof f === 'string') return h('span', { text: f });
                                return [h('span', { text: f.path || '' }),
                                        h('span', { style: { color: 'var(--fmx-red,#ef4444)' }, text: ' — ' + (f.error || '') })];
                            })
                        ]));
                    }
                    if (!bad) toast(res.message || T('fm.perm_applied', { applied: res.applied || mode }), 'success');
                } catch (e) {
                    resultEl.appendChild(h('div', { class: 'fmx-note err', text: e.message }));
                } finally {
                    applyBtn.disabled = false;
                    applyBtn.textContent = T('fm.perm_apply');
                }
            }
        });
        m.foot.appendChild(h('span', { class: 'fmx-spacer' }));
        m.foot.appendChild(h('button', { class: 'fmx-btn ghost', type: 'button', text: T('fm.close'), onclick: function () { m.close(); } }));
        m.foot.appendChild(applyBtn);
    };

    // ══════════════════════════════════════════════════════════════════
    // Boot
    // ══════════════════════════════════════════════════════════════════

    window.FM = FM;
    window.T = T;
    window.applyI18n = applyI18n;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { FM.init(); });
    } else {
        FM.init();
    }
})();
