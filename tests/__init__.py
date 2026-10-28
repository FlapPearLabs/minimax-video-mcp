"""测试包。

过滤 ResourceWarning —— mock 的 keep-alive 连接在测试结束时才被 GC，
会刷出一堆 "unclosed socket" 噪音，掩盖真正的失败信息。
"""

import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)
