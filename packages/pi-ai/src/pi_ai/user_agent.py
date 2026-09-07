"""pi User-Agent 构造。

对应上游 ``utils/pi-user-agent.ts``：所有 provider 请求统一携带
``pi (<platform> <release>; <arch>)`` 形式的 User-Agent，便于网关/厂商识别
pi 流量（部分厂商对已知客户端有更高的兼容性容忍）。
"""

from __future__ import annotations

import platform


def get_pi_user_agent() -> str:
    """返回 pi 的 User-Agent 字符串，如 ``pi (Darwin 27.0.0; arm64)``。"""
    return f"pi ({platform.system()} {platform.release()}; {platform.machine()})"


__all__ = ["get_pi_user_agent"]
