# Phân tích kích thước build và cấu hình installer FrameForge

## Kết luận điều hành

Gói FrameForge hiện không còn bị chi phối chỉ bởi các thư viện Python. Với artifact Linux làm mốc tham khảo, profile minimal có kích thước **324.10 MiB** trước khi thêm FFmpeg Windows; phần lớn còn lại là binary native, codec/media libraries, OpenBLAS, Python runtime, bootloader và frontend static assets. Cặp `ffmpeg.exe`/`ffprobe.exe` Windows static đã chọn khoảng **218.01 MiB** riêng hai binary. Vì vậy mục tiêu installed size dưới 200 MB không thể đạt nếu vẫn giữ đầy đủ Streamlit, OpenCV và FFmpeg offline trong cùng package.

Có hai mục tiêu cần tách riêng. **Installed size** là dung lượng thư mục sau khi cài, còn **Setup download size** là dung lượng file `FrameForge-Setup.exe` sau nén. Inno Setup có thể làm file tải xuống nhỏ hơn bằng LZMA2 và solid compression, nhưng không làm giảm dung lượng các binary đã cài.

## Kiểm tra `build_installer.bat`

Script hiện thực hiện đúng các bước cơ bản: chuyển working directory về thư mục chứa script, dùng biến `ISCC` nếu người dùng đã chỉ định, tự tìm `ISCC.exe` trong PATH hoặc hai vị trí Inno Setup phổ biến, kiểm tra executable onedir, tạo thư mục `installer`, xóa Setup cũ, gọi compiler và xác nhận compiler thực sự tạo ra file Setup. Sau đó script in đường dẫn và kích thước file Setup.

Phiên bản hiện tại tốt hơn bản ban đầu ở hai điểm. Thứ nhất, biến môi trường `ISCC` tùy chỉnh không còn bị ghi đè khi compiler không nằm trong PATH. Thứ hai, script không chỉ dựa vào exit code của Inno Setup mà còn kiểm tra wildcard `installer\FrameForge-Setup-*.exe`, nhờ đó bắt được trường hợp compiler trả về thành công nhưng output path hoặc tên file không như mong đợi.

| Hạng mục | Đánh giá | Nhận xét |
|---|---|---|
| Tìm `ISCC.exe` | Tốt | Hỗ trợ biến `ISCC`, PATH và Program Files phổ biến. |
| Kiểm tra đầu vào | Tốt | Bắt buộc `dist\VideoScreenshotFilter\VideoScreenshotFilter.exe`. |
| Dọn output cũ | Tốt | Tránh nhầm Setup cũ với Setup vừa build. |
| Compiler flags | Hợp lý | `/Qp` phù hợp build tự động nhưng vẫn cho progress. |
| Xác minh output | Đã bổ sung | Kiểm tra file thực tế và in byte size. |
| Khả năng reproducible | Cần cải thiện | Version hiện nằm cố định trong `.iss`; nên truyền version từ CI hoặc file version chung. |
| Kiểm tra payload | Cần bổ sung | Nên kiểm tra `ffmpeg.exe`, `ffprobe.exe`, license và metadata trước khi gọi ISCC. |

Một cải tiến tiếp theo nên thêm preflight vào `build_installer.bat`: kiểm tra các file `vendor\ffmpeg\ffmpeg.exe`, `vendor\ffmpeg\ffprobe.exe`, `BUILD_METADATA.txt` và ít nhất một file license trước khi build. Điều này ngăn tạo Setup “thành công” nhưng thiếu khả năng tải/ghép video chất lượng cao.

## Kiểm tra `FrameForge.iss`

Cấu hình hiện tại chọn cài theo user vào `%LOCALAPPDATA%\Programs\FrameForge`, giới hạn `x64compatible`, dùng `PrivilegesRequired=lowest`, tạo shortcut Start Menu và shortcut Desktop tùy chọn, chạy ứng dụng sau cài và đăng ký uninstaller. Đây là lựa chọn phù hợp với updater yt-dlp vì updater ghi vào `%LOCALAPPDATA%` và không cần quyền administrator.

Dòng `[Files]` hiện đóng gói toàn bộ `dist\VideoScreenshotFilter\*`, nhưng đã thêm `Excludes: "*.map,*.pdb,*.log,*.tmp"`. Các file map/PDB/log/tmp thường không cần cho runtime; loại chúng ở lớp installer có thể giảm Setup download size mà không tác động đến code chạy. Tuy nhiên cần test bản cài sạch trước khi phát hành, vì một số file frontend hoặc metadata có thể bị nhầm là file debug.

| Cấu hình | Tác động đến kích thước | Đánh giá |
|---|---|---|
| `Compression=lzma2/max` | Giảm Setup download size, không giảm installed size | Nên giữ. Đây đã là lựa chọn nén mạnh hợp lý. |
| `SolidCompression=yes` | Có thể tăng compression ratio giữa nhiều file tương tự | Nên giữ; đổi lại là giải nén kém ngẫu nhiên hơn. |
| `CompressionThreads=auto` | Chủ yếu rút ngắn thời gian compiler | Nên giữ; không phải cơ chế giảm payload. |
| `Excludes` cho `.map/.pdb/.log/.tmp` | Giảm file không cần runtime | Hợp lý sau regression test. |
| `ignoreversion` | Ảnh hưởng update/overwrite, không đáng kể đến size | Không phải tối ưu kích thước. |
| `[Components]` | Chỉ cho phép chọn phần cài | Không tự làm Setup nhỏ hơn nếu file vẫn được compile vào cùng Setup. |
| `external`/`download` | Có thể tách payload khỏi Setup | Giảm download size, nhưng cần mạng hoặc file phân phối riêng. |

Theo tài liệu Inno Setup, `lzma2` cho phép nén tốt hơn ZIP/BZip trong nhiều trường hợp, còn `SolidCompression` nén các file trong một stream chung; vì vậy cấu hình hiện tại phù hợp với mục tiêu giảm file Setup [1] [2]. `Excludes` dùng mẫu wildcard để bỏ file khỏi mục `[Files]` [3]. Component selection chỉ liên kết các entry cài đặt với lựa chọn của người dùng, không tự loại payload khỏi file Setup [4].

## Phân rã artifact ngoài Python packages

Phép đo dưới đây dùng artifact Linux cùng mã nguồn, symlink được loại khỏi phép cộng để tránh đếm một target hai lần. Đây là mốc phân tích, không phải kích thước Windows cuối cùng.

| Thành phần | Minimal | Full | Ý nghĩa |
|---|---:|---:|---|
| Native binary/shared library | 175.11 MiB | 229.31 MiB | `cv2`, OpenBLAS, NumPy extensions, cryptography và các thư viện native. |
| “Other” runtime payload | 84.99 MiB | 233.77 MiB | Bao gồm nhiều codec/media libraries và các payload nhị phân không được phân loại riêng. |
| Python bytecode/archive | 24.32 MiB | 49.23 MiB | Bytecode và archive Python đã frozen. |
| Frontend static assets | 21.89 MiB | 61.14 MiB | JavaScript/CSS/Map của Streamlit và các chart components. |
| PyInstaller executable | 16.70 MiB | 37.81 MiB | Bootloader cộng phần archive được đưa vào executable. |
| Metadata/text | 0.99 MiB | 10.60 MiB | JSON schema, license, text và metadata. |

Các file lớn nhất của profile minimal gồm `cv2.abi3.so` khoảng **70.45 MiB**, OpenBLAS đi kèm OpenCV khoảng **37.18 MiB**, OpenBLAS đi kèm NumPy khoảng **23.96 MiB**, codec `libavcodec` của OpenCV khoảng **17.58 MiB**, Rust extension của cryptography khoảng **13.69 MiB**, NumPy multiarray khoảng **10.19 MiB** và Python runtime khoảng **8.64 MiB**. Đây là lý do chỉ loại các package Python cấp cao không thể đưa minimal từ 324 MiB xuống dưới 200 MiB.

Full profile còn có PyArrow, với các thư viện `libarrow`, `libarrow_flight`, `libarrow_compute`, `libparquet` và các thành phần liên quan; riêng các file lớn nhất đã chiếm hàng chục MiB. Full profile cũng chứa static assets của PyDeck và Plotly. Profile minimal đã loại phần Python packages này, nhưng Streamlit vẫn mang theo một số chart JavaScript tĩnh trong frontend chính; không nên xóa mù các asset đó nếu chưa test mọi màn hình.

## Các hướng tối ưu ngoài việc xóa Python libraries

### 1. Tối ưu FFmpeg: tác động lớn nhất

Script `prepare_ffmpeg_windows.ps1` hiện tải một archive Windows static LGPL từ URL BtbN, lấy toàn bộ `ffmpeg.exe` và `ffprobe.exe`, sau đó giữ license/readme và metadata checksum. Phương án này đơn giản và offline, nhưng cặp binary tham khảo khoảng **218.01 MiB** đã vượt riêng mục tiêu 200 MB.

Hướng có tác động lớn nhất là tự xây hoặc chọn một FFmpeg build tối giản, chỉ giữ các demuxer, muxer, decoder, encoder, protocol và filter mà FrameForge thật sự cần. Vì downloader dùng format `bv*+ba/b` và ghép ra MP4, cần test tối thiểu MP4/H.264/AAC, WebM/VP9/Opus nếu nền tảng trả về format đó, HTTPS, concat/merge và các container đầu vào dự kiến. Không được cắt codec chỉ dựa trên tên file; phải chạy test format thực tế và giữ thông tin configure/source/license của binary [5].

Một lựa chọn rất đáng cân nhắc cho **minimal** là chỉ nhúng `ffmpeg.exe`, còn `ffprobe.exe` để tùy chọn từ PATH. Trong mã hiện tại, `ffprobe` chủ yếu phục vụ health check; logic merge đặt `ready_for_merge` dựa trên `ffmpeg_path`, và downloader truyền `ffmpeg_location` cho yt-dlp khi có FFmpeg. Nếu chọn hướng này, cần sửa health check để phân biệt “FFmpeg merge ready” với “ffprobe metadata available”, cập nhật cảnh báo CLI và kiểm thử yt-dlp trên mọi format mục tiêu. Nó có thể bỏ khoảng kích thước của một binary FFmpeg, nhưng tổng bundle vẫn không tự xuống dưới 200 MB vì baseline Streamlit/OpenCV đã lớn.

Shared FFmpeg có thể giảm kích thước executable chính nhưng sẽ cần phân phối thêm DLL và kiểm tra dependency runtime. Vì vậy đây là tối ưu cần benchmark, không phải mặc định tốt hơn static. Nếu mục tiêu là giảm **download size**, có thể tách FFmpeg thành payload tải ở lần đầu, có HTTPS, pin version, SHA-256/signature verification, retry, cache và thông tin license. Cách này giữ trải nghiệm không cần người dùng cài FFmpeg thủ công nhưng yêu cầu mạng lần đầu; installed size sau khi tải vẫn gần như không đổi.

### 2. Tối ưu OpenCV và media stack

`cv2.abi3.so` và các codec/media libraries của wheel OpenCV là phần native lớn nhất trong minimal. FrameForge hiện dùng `cv2.VideoCapture`, resize, color conversion, histogram, Laplacian/sharpness, image encoding và dHash. Nếu muốn cắt sâu hơn, có thể xây OpenCV tùy biến chỉ với các module `core`, `imgproc`, `imgcodecs` và `videoio`, tắt GUI/Qt/GTK, Java, tests, examples, contrib và các backend không dùng. Cấu hình phải được kiểm tra riêng trên Windows vì wheel custom có rủi ro ABI, DLL search path và codec khác với wheel chính thức.

Không nên xóa các thư viện media đi kèm OpenCV bằng tay. Những file như `libavcodec`, `libavformat`, `libavutil`, `libswscale`, `libaom` và `libvpx` có thể là dependency runtime của video decode hoặc image/video codec. Cách đúng là build OpenCV/FFmpeg với tập module có chủ đích, sau đó chạy một ma trận video đại diện.

### 3. Tối ưu OpenBLAS và native numerical runtime

OpenBLAS xuất hiện cả trong nhánh OpenCV và NumPy, tổng các file lớn đã chiếm trên 60 MiB trong mốc minimal. Tuy nhiên NumPy và OpenCV vẫn cần mảng số và phép toán ma trận ở nhiều đoạn pipeline. Việc xóa DLL OpenBLAS hoặc thay bằng DLL hệ thống có thể làm app không khởi động, sai kiến trúc hoặc lỗi ở máy không có runtime tương ứng.

Hướng an toàn hơn là kiểm tra xem build NumPy/OpenCV custom không-BLAS có đáp ứng tốc độ và tính đúng đắn hay không. Đây là thay đổi build native lớn, thường chỉ đáng làm nếu mục tiêu kích thước rất quan trọng; cần benchmark scene detection, motion blur và xử lý batch trước/sau.

### 4. Tối ưu PyInstaller data collection và static assets

Spec minimal hiện dùng `collect_all` cho Streamlit, Pillow, OpenCV, NumPy và yt-dlp, đồng thời dùng `collect_submodules` cho toàn bộ Streamlit và yt-dlp. Cách này an toàn hơn nhưng có thể thu thập data/plugin không dùng. Theo tài liệu PyInstaller, `Analysis` tách riêng `binaries`, `datas`, `hiddenimports` và có thể kiểm soát từng nhóm trong spec [6].

Có thể chuyển dần từ `collect_all` sang danh sách `collect_data_files` có chủ đích, chỉ giữ data mà runtime cần; tương tự, hidden imports của yt-dlp có thể được kiểm kê theo extractor mục tiêu. Đây không phải loại bỏ package Python cấp cao, mà là cắt data/plugin không dùng. Đổi lại rủi ro cao hơn: Streamlit có frontend runtime động, yt-dlp có extractor động và mỗi phiên bản mới có thể thay đổi import graph. Nên thực hiện như profile thử nghiệm, dùng smoke test và test downloader/preview đầy đủ.

Việc loại `*.map` ở lớp Inno Setup là tối ưu ít rủi ro nhất trong nhóm static assets. Không nên xóa toàn bộ chart bundle của Streamlit bằng wildcard rộng; có thể làm hỏng frontend ở runtime dù app hiện không gọi chart API.

### 5. UPX, strip và nén binary

`UPX` có thể làm một số PE/PYD/DLL nhỏ hơn trên đĩa, nhưng có thể tăng thời gian khởi động, gây false positive antivirus, không áp dụng tốt cho mọi binary và cần loại trừ các file nhạy cảm như FFmpeg, OpenCV hoặc cryptography nếu kiểm thử không đạt. Inno Setup tiếp tục nén các file sau đó, nên lợi ích trên file Setup có thể nhỏ hơn lợi ích trên installed payload.

`strip` không nên bật mù trên Windows cho native extension và binary vendor. Nếu dùng, phải kiểm tra khởi động, import, downloader, codec và chữ ký/antivirus. Đây là tối ưu thử nghiệm cuối cùng, không phải bước mặc định.

### 6. Dùng staging directory thay vì đóng gói wildcard trực tiếp

Thay vì cho Inno Setup đọc trực tiếp toàn bộ `dist\VideoScreenshotFilter`, có thể tạo `release_stage\FrameForge\` sau build. Bước staging chỉ copy executable, `_internal` cần thiết, `vendor\ffmpeg`, license, metadata và README phát hành; đồng thời loại cache/log/debug artifacts bằng whitelist. Cách này giảm nguy cơ đưa nhầm file test hoặc log vào Setup và giúp audit payload dễ hơn. Nó không tự loại binary runtime bắt buộc, nhưng thường là cách kiểm soát package tốt hơn wildcard.

## Đánh giá cấu hình Inno Setup hiện tại

Cấu hình nén hiện tại nên được giữ. `lzma2/max` và `SolidCompression=yes` là lựa chọn hợp lý để giảm file Setup; thử `lzma2/ultra` chỉ có thể giảm thêm một phần nhỏ, trong khi tăng đáng kể thời gian và bộ nhớ compile/decompress [1] [2]. `CompressionThreads=auto` chủ yếu làm compiler nhanh hơn, không thay đổi đáng kể mục tiêu payload.

Nếu muốn Setup nhỏ hơn nữa mà vẫn giữ offline core, hãy tạo hai artifact: `FrameForge-Core-Setup.exe` và một gói `FrameForge-FFmpeg-Package` được tải/ghép có kiểm chứng. Nếu muốn vẫn chỉ có một Setup và không yêu cầu người dùng thao tác, có thể dùng `external`/`download` để Setup tải FFmpeg trong quá trình cài; cần hiển thị rõ rằng máy phải có mạng và phải kiểm tra hash/signature. Component “Embedded FFmpeg” chỉ giúp chọn cài hay không; nếu FFmpeg vẫn được compile vào cùng Setup thì nó không làm file Setup nhỏ tương ứng [3] [4].

## Lộ trình khuyến nghị

| Ưu tiên | Thay đổi | Tác động kỳ vọng | Rủi ro |
|---:|---|---|---|
| 1 | Giữ Inno LZMA2/solid và loại `.map/.pdb/.log/.tmp` | Giảm Setup download size, không đổi native baseline | Thấp, cần test clean install. |
| 2 | Tạo staging whitelist và preflight FFmpeg/license/metadata | Kiểm soát payload, tránh đóng gói rác | Thấp. |
| 3 | Profile minimal chỉ nhúng `ffmpeg.exe`, ffprobe tùy chọn | Có thể giảm rất mạnh so với nhúng cả cặp | Trung bình; cần sửa health check và test yt-dlp. |
| 4 | FFmpeg custom build theo codec/container thực tế | Giảm native payload lớn nhất sau baseline | Cao; có license/codec và compatibility risk. |
| 5 | OpenCV custom build | Có thể giảm `cv2` và media backends | Cao; ABI, DLL, codec và bảo trì. |
| 6 | Prune data/hidden imports có kiểm thử | Giảm static/plugin overhead | Trung bình đến cao; Streamlit/yt-dlp dynamic imports. |
| 7 | UPX/strip thử nghiệm | Có thể giảm installed size thêm | Cao; antivirus, startup và native compatibility. |

Với yêu cầu hiện tại, lựa chọn thực dụng nhất là giữ **full onedir** cho bản offline ổn định, dùng **minimal onedir** cho bản nhẹ hơn, giữ Inno Setup hiện tại để giảm download size, và tách một nhánh thử nghiệm “FFmpeg-only” trước khi đầu tư vào custom OpenCV. Không nên cam kết con số dưới 200 MB cho bản offline đầy đủ trước khi có phép đo Windows sau cài.

## References

[1]: https://jrsoftware.org/ishelp/topic_setup_compression.htm "Inno Setup — Compression"

[2]: https://jrsoftware.org/ishelp/topic_setup_solidcompression.htm "Inno Setup — SolidCompression"

[3]: https://jrsoftware.org/ishelp/topic_filessection.htm "Inno Setup — Files section"

[4]: https://jrsoftware.org/ishelp/topic_componentssection.htm "Inno Setup — Components section"

[5]: https://ffmpeg.org/legal.html "FFmpeg — Legal considerations"

[6]: https://pyinstaller.org/en/stable/spec-files.html "PyInstaller — Using Spec Files"
