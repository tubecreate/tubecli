// Dọn tab của LƯỢT AGENT (user 30/10/2026: «cho agent tự đóng khi chạy xong»).
//
// Vì sao: lượt agent theo lịch mở tab bài viết / kết quả tìm kiếm rồi bỏ đó. Hồ sơ testphienbansharr149 của agent
// «chuyên gia it» dồn tới 202 tab (≈ 200 tiến trình, máy treo) — phần dồn QUA các lượt chặn bằng clearSavedSession()
// trong browser_manager.js; file này chặn phần dồn TRONG một lượt và dọn khi lượt xong.
//
//   trimTabs(context, keep, max): còn quá `max` tab thì đóng tab CŨ NHẤT trước, không bao giờ đóng `keep`
//     (tab agent đang làm việc). Gọi mỗi lần có tab mới trong lượt agent.
//   closeExtraTabs(context, keep): chạy xong — chỉ giữ một tab.
// Chỉ dùng cho lượt agent (open.js: !isManual). Người dùng tự mở trình duyệt thì không đụng tới tab của họ.

export const MAX_AGENT_TABS = 4;

function openPages(context) {
    try {
        return context.pages().filter((p) => !p.isClosed());
    } catch (e) {
        return [];
    }
}

export async function trimTabs(context, keep, max = MAX_AGENT_TABS) {
    const limit = Math.max(1, Number(max) || MAX_AGENT_TABS);
    const pages = openPages(context);
    let left = pages.length;
    let closed = 0;
    for (const p of pages) {                 // context.pages() theo thứ tự mở: cũ nhất trước
        if (left <= limit) break;
        if (p === keep) continue;
        try {
            await p.close({ runBeforeUnload: false });
            closed++;
            left--;
        } catch (e) { /* tab đã tự đóng / trình duyệt đang tắt */ }
    }
    return closed;
}

export async function closeExtraTabs(context, keep) {
    const pages = openPages(context);
    const stay = (keep && typeof keep.isClosed === 'function' && !keep.isClosed()) ? keep : pages[pages.length - 1];
    return trimTabs(context, stay, 1);
}
