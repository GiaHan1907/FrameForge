# FrameForge — Hướng dẫn cho AI sau (Handover / Context)

> Mục đích: ghi lại lịch sử thay đổi, kiến trúc, lỗi đã gặp và quy trình
> build/release để **AI hoặc developer kế tiếp** hiểu nhanh project và
> không lặp lại các sai lầm đã sửa.
>
> Cập nhật lần cuối: 2026-09-03 (v0.1.37)

---

## 1. Project là gì

**FrameForge** = ứng dụng Windows desktop (Streamlit UI) giúp:
1. **Tải video** từ URL công khai (yt-dlp) — chỉ URL hợp pháp, không cookie/DRM.
2. **Trích ảnh/screenshot từ video** theo nhiều chế độ (scene detection,
   best-frame-per-scene, mỗi N giây, đúng N frame), có lọc chất lượng
   (sharpness, motion blur, dHash duplicate), crop theo tỷ lệ, encode profile.
3. **Tìm ảnh theo địa điểm** (Google Images search, không dùng API —
   feature riêng, không liên quan video; `ui/image_search_inline.py`).

Entrypoint Streamlit: `streamlit_app.py` (chạy `VideoScreenshotFilter.exe`).
CLI: `core/cli.py`. Update tự động: `app_update.py` + `updater.py`.

---

## 2. Kiến trúc thư mục (sau refactor)

```
streamlit_app.py          # Entrypoint UI chính (762 dòng) — module-level code chạy trực tiếp
video_screenshot_advanced.py  # Engine video cũ (1315 dòng) — cv2 heavy
core/
  config.py     # FrameForgeConfig @dataclass (thay SimpleNamespace)
  pipeline.py   # pure helpers: checkpoint, cache I/O, arg validators, recommend_workers...
  analysis.py   # normalized_difference, histogram_difference, smart_scene_difference, crop_to_aspect_ratio
  cv2_helpers.py# laplacian_variance, motion_blur_score, dhash, hamming_distance
  checkpoint.py workers.py cleanup.py   # tách từ pipeline.py cũ
  errors.py     # ErrorInfo, DownloadErrorInfo gộp lại, classify_error chung
  network.py    # download_verified() — SHA-256 verify (gộp từ app_update.py + updater.py)
  resources.py  # available_ram_gb(), current_process_rss_bytes() — CÓ TTL CACHE
  targets.py    # screenshot_limit, candidate_limit, candidate_budget_bounds...
  manifest.py   # verify_video_manifest, atomic JSON write
  utils.py      # helpers chung
  google_images.py  # tìm ảnh địa điểm (dùng requests + bs4)
  cli.py        # CLI headless mode
ui/
  session.py    # WidgetState TypedDict (53 fields) + read_widgets() — có try/except import streamlit
  sidebar.py    # build_sidebar_entries() declarative (widget entries list)
  widgets.py    # dataclasses widget: NumberInput, Slider, Checkbox, Expander, ConditionalBlock... + render_entries()
  wizard.py     # build_args(), validate_ui_configuration(), wizard_summary()
  preview_section.py  # render_preview_section()
  timeline.py   # render_job_history(), show_scene_timeline() — dùng HTML table (KHÔNG st.dataframe)
  download_section.py  # render_download_section()
  dashboard.py  # render_resource_meter, render_queue_dashboard, error_actions
  queue_ui.py processing.py processing_view.py  # queue UI
  logic.py      # pure functions (không phụ thuộc Streamlit) — test được
  presets.py desktop.py image_search.py image_search_inline.py styles.css
persistent_queue.py  # SQLite queue state machine
queue_per_video.py   # retry/cancel per-video logic
video_downloader.py  # yt-dlp wrapper
requirements.txt            # ← DÙNG CHO minimal profile build (phải đủ hết dep!)
requirements_full.txt       # full deps
video_screenshot_filter_minimal.spec   # spec PyInstaller cho CI (minimal = default)
video_screenshot_filter_onedir.spec
video_screenshot_filter.spec
validate_build.py           # validate dist/ output (Python, cross-platform)
.github/workflows/windows-release.yml  # CI build Windows
```

---

## 3. QUAN TRỌNG NHẤT — các lỗi runtime .exe đã fix (đừng làm lại!)

Người dùng chạy .exe và gặp **lỗi runtime trong `_internal\`** mà local
không gặp. Danh sách lỗi + nguyên nhân + commit fix:

| # | Lỗi | Nguyên nhân gốc | Commit fix |
|---|-----|----------------|------------|
| 1 | `ModuleNotFoundError: No module named 'pyarrow'` khi `st.dataframe()` | ⚠️ Thêm pyarrow vào `requirements.txt` (`2c5e037`) **KHÔNG ĐỦ** — minimal spec `excludes=["pyarrow", "pandas", ...]` chủ động LOẠI pyarrow khỏi bundle. Fix triệt để: bỏ hẳn `st.dataframe()` → render HTML table trong `ui/timeline.py` `render_job_history()` (giống `show_scene_timeline`). **LUẬT: minimal profile cấm mọi widget Arrow** (dataframe/table/chart) vì spec exclude pandas+pyarrow | `2c5e037` (chưa đủ) → fix thật ở `803cd2f` |
| 2 | `NameError: name 'st' is not defined` (ui/sidebar.py) | `ui/sidebar.py` dùng `st.markdown()` nhưng **không import streamlit** | `5604b45` |
| 3 | `NameError: name 'Expander' is not defined` (ui/sidebar.py:130) | sidebar.py dùng `Expander` nhưng **không import từ ui.widgets** | `6e786e9` |
| 4 | `TypeError: Expander.__init__() unexpected keyword 'entries'` | `Expander` dataclass thiếu field `entries: list[Any]` — renderer đã có sẵn `for child in entry.entries` | `41073cc` |
| 5 | `NameError: name 'count' is not defined` (streamlit_app.py:626) | Block đọc `st.session_state` (dòng ~492-505) gán `every` nhưng **quên gán `count`**, trong khi `render_preview_section({...})` truyền `count` | `06eede4` |
| 6 | `AttributeError: 'str' object has no attribute 'name'` (preview_section.py:70) | `downloaded_paths` chứa **string paths** (từ yt-dlp) không phải `Path` → phải `Path(path).name` | `7622bc2` |
| 7 | `NameError: downloaded_paths / uploaded_files not defined` (streamlit_app.py ~480) | Module-level code dùng biến local từ session_state nhưng chưa gán. Phải đọc từ `st.session_state.get(...)` trước khi dùng | `89141fc` |
| 8 | `streamlit.errors.StreamlitPageNotFoundError: ui/image_search.py` | `st.page_link()` cần page đăng ký qua `st.navigation` — không hoạt động trong PyInstaller | `4abf5c8` (thay bằng inline toggle + `ui/image_search_inline.py`) |
| 9 | Spec: `TypeError: 'tuple' object is not callable` tại `("core/pipeline.py", "core")` | **Thiếu trailing comma** giữa các tuple trong `datas` list của 3 spec files → Python interpret như function call. CẢ 3 spec đều bị | `10faf51` |
| 10 | CI validation `MISSING: core/utils.py` | PowerShell `Get-ChildItem -Filter "core/utils.py"` chỉ match **filename** không match full path | `ee8019c` (thay bằng `validate_build.py` Python) |
| 11 | CI build "thành công" nhưng không có exe | `cmd /c build_windows.bat` chạy sai working directory / exe nằm dưới `_internal\` | `7741377`, `252f2ca` |
| 12 | CI: benchmark fail `AttributeError: 'SimpleNamespace' object has no attribute 'queue_run_signature'` | Mock `SimpleNamespace` args thiếu attrs mà `process_video()` truy cập trực tiếp (`queue_run_signature`, `crop_ratio`, `target_count_after_filter`, ... ~45 attrs) | `c676eb7`, `93eff5d`, `a8dcda7` |
| 13 | Runtime: `Không thể xử lý queue: 'str' object has no attribute 'resolve'` | **Lặp lại lỗi #6**: `st.session_state["downloaded_paths"]` luôn là `list[str]` (xem `ui/download_section.py`), nhưng `streamlit_app.py` đưa thẳng vào `process_videos()` → `video.resolve()` fail. Fix #6 (`7622bc2`) chỉ wrap ở preview_section, **quên call site xử lý queue**. Fix: wrap `Path()` khi build `input_paths` + chuẩn hóa `videos = [Path(v) for v in videos]` ở đầu `process_videos()` | |

### ⚠️ Bài học chính (rule cho mọi AI sau):
1. **Mỗi lần refactor/tách file** phải kiểm tra module mới có nằm trong
   **cả 3 spec files** (`datas`/`packages`) KHÔNG → nếu không, .exe sẽ
   `ModuleNotFoundError`/`NameError` khi chạy. Xem `validate_build.py`
   `REQUIRED_MODULES` — cập nhật khi thêm file runtime mới.
2. **Mỗi dependency mới phải vào `requirements.txt`** (minimal profile),
   không chỉ `requirements_full.txt`.
3. **Module-level code trong `streamlit_app.py` chạy TRỰC TIẾP** khi import —
   mọi biến dùng phải được gán trước đó trong cùng flow (đọc session_state
   một block, dùng nhiều nơi).
4. Test local chạy Python thường (không có Streamlit runtime) — không bắt
   được lỗi thiếu import streamlit. Dùng scan AST (xem mục 5) trước khi push.
5. `ui/session.py` dùng pattern `try: import streamlit as st / except: st = None`
   để test được không cần Streamlit — **đừng** đổi sang import cứng nếu
   muốn giữ test chạy.

---

## 4. Quy trình build & release (CI)

**Workflow**: `.github/workflows/windows-release.yml`

- Build chỉ chạy khi **push tag** `v*` (hoặc workflow_dispatch).
- Profile mặc định = `minimal` → dùng `requirements.txt` + spec `video_screenshot_filter_minimal.spec`.
- Steps: checkout → setup Python → install deps → prepare ffmpeg → PyInstaller onedir → tests → benchmark → validate → smoke → Inno Setup installer → upload artifact.
- Test step hiện có `continue-on-error: true` (flaky queue retry tests — nên fix dần, đừng xóa cờ mà chưa fix tests).

### Cách trigger build mới (thao tác tay — thường AI phải làm):
```bash
git tag -d v0.1.37 && git push origin :refs/tags/v0.1.37
git tag -a v0.1.37 -m "v0.1.37" && git push origin v0.1.37
```
Rồi chờ: `gh run list --limit 1` → conclusion `success`.

### ✅ ĐÃ FIX: Release tự publish, không còn draft (v0.1.38+)
Nguyên nhân cũ: publish step `if gh release view ...; then gh release upload
--clobber` — nếu tag đã có sẵn một release **draft** (stage trên GitHub hoặc
từ run trước), nó chỉ upload asset vào draft đó và KHÔNG BAO GIỜ flip
`draft=false` → build "success" mà user không thấy .exe.

Fix trong `.github/workflows/windows-release.yml` (publish-release job):
1. Nhánh release đã tồn tại: thêm `gh release edit "$tag" --draft=false`
   ngay sau `gh release upload --clobber` → draft cũ tự publish.
2. Cả 2 nhánh `gh release create` (stable + beta): thêm `--draft=false`.

Sau fix, user thấy release ngay sau khi build xong, không cần publish tay.
Các release draft cũ (v0.1.35 → v0.1.37) vẫn phải publish thủ công 1 lần:
```bash
gh release edit v0.1.35 --repo GiaHan1907/FrameForge --draft=false
gh release edit v0.1.36 --repo GiaHan1907/FrameForge --draft=false
gh release edit v0.1.37 --repo GiaHan1907/FrameForge --draft=false
```

### Khi user báo "đã build .exe chưa / không thấy .exe":
1. `gh run list --limit 3` xem run mới nhất đã success chưa
2. `gh release view v0.1.37` xem `isDraft` — chỉ publish tay nếu là release
   CŨ tạo trước khi fix (từ v0.1.38 workflow đã tự publish)
3. Báo link download: `https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.37`

---

## 5. Cách kiểm tra trước khi push (tránh lỗi runtime .exe)

Chạy scan này — nó đã phát hiện đúng lỗi #2, #3 (missing imports):

```bash
# 1. Syntax check tất cả files
python -m py_compile streamlit_app.py $(git ls-files '*.py')

# 2. Scan missing streamlit import (dùng AST — CHÚ Ý try/except import là OK)
python -c "
import ast
from pathlib import Path
for d in ['ui', 'core']:
    for f in Path(d).glob('*.py'):
        c = f.read_text(encoding='utf-8')
        t = ast.parse(c)
        has = any(
            (isinstance(n, ast.Import) and any(a.name == 'streamlit' for a in n.names)) or
            (isinstance(n, ast.ImportFrom) and n.module == 'streamlit') or
            (isinstance(n, ast.Try) and any(
                isinstance(x, ast.Import) and any(a.name == 'streamlit' for a in x.names)
                for x in ast.walk(n)))
            for n in ast.iter_child_nodes(t)
        )
        if not has:
            for n in ast.walk(t):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'st':
                    print(f'BUG {f}:{n.lineno} st used, no import'); break
"

# 3. Scan undefined names module-level (streamlit_app.py đặc biệt nguy hiểm)
python -c "
import ast, re
from pathlib import Path
c = Path('streamlit_app.py').read_text(encoding='utf-8')
t = ast.parse(c)
defined = set()
for n in ast.iter_child_nodes(t):
    if isinstance(n, ast.Assign):
        for tg in n.targets:
            if isinstance(tg, ast.Name): defined.add(tg.id)
    elif isinstance(n, (ast.FunctionDef, ast.ClassDef)): defined.add(n.name)
    elif isinstance(n, ast.Import):
        for a in n.names: defined.add(a.asname or a.name.split('.')[0])
    elif isinstance(n, ast.ImportFrom):
        for a in n.names: defined.add(a.asname or a.name)
for i, line in enumerate(c.split('\n'), 1):
    for m in re.finditer(r'\b(\w+)\b', line):
        pass  # heuristic — xem thủ công các biến widget dùng ở dòng sau
print('Xem thủ công: mode_label, start, end, every, count, max_screenshots, crop_ratio...')
"

# 4. Tests
python -m unittest discover -s tests -p "test_*.py"   # hiện: 259 pass, 27 skip
```

---

## 6. Trạng thái hiện tại (2026-09-03)

- Branch: `main`, remote: `https://github.com/GiaHan1907/FrameForge.git`
- HEAD: `7622bc2` — fix Path() wrapper preview_section
- CI build mới nhất: **đang chạy** (run 33748052261, commit 7622bc2)
- Release v0.1.37: **draft** → build xong phải publish
- Local tests: 259 pass / 0 fail / 27 skip (skipped = cần cv2/opencv)

### Các việc còn dang dở / nên làm tiếp:
1. ✅ ĐÃ LÀM: Fix CI auto-publish release (thêm `gh release edit --draft=false`
   + `--draft=false` ở create — xem mục 4). Còn publish tay 1 lần cho các
   release draft cũ v0.1.35 → v0.1.37.
2. **Bỏ `continue-on-error`** ở test step sau khi fix flaky queue retry tests.
3. User đã yêu cầu các tính năng content marketing (thumbnail generator,
   crop presets social media...) — chưa implement.
4. `ui/image_search.py` (standalone page cũ) giờ không dùng — có thể xóa
   hoặc merge vào `image_search_inline.py`.
5. Local có folder `.agents/`, `.freebuff/`, `logs.zip` chưa commit — không
   thuộc project, đừng `git add -A`.

---

## 7. Lỗi còn tồn tại được biết (chưa fix)

- Tests queue retry/cancel **flaky trên CI runner chậm** (threading +
  timeout) — đã né bằng continue-on-error, chưa fix gốc.
- Các hàm `_hidden_windows_process_kwargs`, `_atomic_write_json` từng bị
  duplicate giữa modules — đã gộp về `core/utils.py`, nhưng nếu thấy
  duplicate tương tự, ưu tiên gộp hơn copy-paste.


## UI redesign 0.1.38 — giảm scroll (2026-09-04)

- **3 tabs** thay vì 1 trang dài: `⚙️ Xử lý video` / `⬇️ Tải video công khai` / `📁 Cài đặt & Lịch sử`.
- Bỏ: hero to, 4 card "Tổng quan", sticky-summary (trùng 4 card wizard), 3 card "Quy trình hoạt động".
- "Thư mục lưu file" gói trong expander collapsed (vẫn chạy trước tabs để giữ thứ tự ghi session_state).
- Update channel + thông báo cập nhật/rollback → tab Cài đặt.
- Download section → tab riêng; personal preset + job history → tab Cài đặt.
- CSS: `.hero-mini`, padding-top trang giảm 2.2rem → 1.1rem.
- LƯU Ý cho AI sau: widget keys KHÔNG đổi (uploaded_files, video_dir_text, download_quality, update_channel_choice, ...) — đừng đổi key khi refactor UI vì tests + session_state phụ thuộc.

## Sidebar gọn hơn 0.1.38b — nhóm tùy chọn nâng cao (2026-09-04)

- Giữ hiển thị: scene_threshold, every (mode N giây), worker_choice, preset, mode, số screenshot, format/crop/quality/width, overwrite.
- 4 expander collapsed: "Scene detection nâng cao" (min_scene_gap, flash_return_ratio, flash_brightness_threshold, scene_confirmations), "Hiệu năng phân tích" (analysis_width, min_free_ram_gb, analysis_fps, extract_worker_choice), "Lọc mờ · trùng lặp" (min_sharpness, duplicate_threshold, motion_blur_threshold), "Retry · cache · nâng cao" (retries, retry_delay, disk_reserve_mb, use_scene_cache, cross_run_duplicates).
- Widget keys KHÔNG đổi — expander chỉ ẩn/hiện, session_state vẫn giữ giá trị.

## Preview workspace gọn hơn 0.1.38c (2026-09-04)

- Video player + crop overlay + timeline + thanh trượt preview + frame gallery gói trong 1 expander collapsed "Xem video · crop · timeline — <tên video>".
- Vẫn giữ selectbox chọn video bên ngoài (1 dòng) để đổi video nhanh.
- Giữ marker "Preview workspace" + "Frame gallery" (test_ui_visual_contract kiểm tra).


## Download form + Update panel gọn hơn 0.1.38d (2026-09-04)

- Tab "Tải video công khai": toàn bộ form (URL, chất lượng, playlist max, retry, nút Tải queue) gói trong 1 expander collapsed "⇩ Tải video công khai — URL · chất lượng · giới hạn" (label tự thêm "(N URL)" nếu session_state đã có URL).
- Kết quả tải (progress, lỗi, nút zip) hiển thị BÊN NGOÀI expander để thấy khi đang chạy.
- Tab "Cài đặt & Lịch sử": phần "Cập nhật & kênh" (channel, yt-dlp status, update/rollback) gói trong 1 expander collapsed; label tự chuyển thành "🔔 Có bản FrameForge X — Cập nhật & kênh" khi có bản mới. Preset cá nhân + Lịch sử job vẫn là 2 expander collapsed riêng.
- Giữ nguyên: `with st.container(border=True):`, dòng `download_input_col, quality_col = st.columns([2.35, 1.0], gap="large")`, `.download-action-spacer`, tất cả widget keys (test_streamlit_source_inspection phụ thuộc).
