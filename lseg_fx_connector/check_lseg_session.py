"""Preflight check for LSEG/Refinitiv Data Library desktop/platform session."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import lseg.data as rd
        library_name = "lseg.data"
    except ImportError:
        try:
            import refinitiv.data as rd
            library_name = "refinitiv.data"
        except ImportError:
            print("未安装 lseg-data，也没有 refinitiv.data。")
            print("如果你在 Refinitiv Workspace CodeBook 里，请用 CodeBook 的 Python 环境运行。")
            print("如果在本机终端跑，请先运行：python3 -m pip install lseg-data")
            return 2

    print(f"使用数据包：{library_name}")

    try:
        rd.open_session()
        try:
            test = rd.get_data(universe=["EUR="], fields=["BID", "ASK"])
        except Exception as exc:
            print("LSEG/Refinitiv 会话未正常打开，无法请求测试数据。")
            print(f"原始错误：{exc}")
            print("")
            print("请确认：")
            print("1. Refinitiv Workspace / Eikon 已经打开并完成登录。")
            print("2. Workspace/Eikon 的 API Proxy 正在运行。")
            print("3. 账号有 EUR= 或外汇数据权限。")
            print("4. 如果你在 CodeBook 里，可以直接在 CodeBook notebook 运行对接脚本。")
            return 3
        print("LSEG/Refinitiv 会话可用。测试请求 EUR= 成功。")
        print(test)
        return 0
    except Exception as exc:
        print("LSEG/Refinitiv 会话打开失败。")
        print(f"原始错误：{exc}")
        print("")
        print("localhost:9000 / 9060 connection refused 通常表示 Workspace/Eikon 桌面代理没连上。")
        return 2
    finally:
        try:
            rd.close_session()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
