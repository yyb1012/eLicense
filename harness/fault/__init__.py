# Time: 2026-04-18 19:55
# Description: 暴露故障注入执行入口，用于验证降级路径与审计可追踪性。
# Author: Feixue

from harness.fault.fault_runner import run_fault_case

__all__ = ["run_fault_case"]
