"""列识别与字段解析。完整定义见 spec §3.4。

设计原则：精确匹配候选列名（不模糊子串，避免误中）。
中文/英文表头都通过候选列表覆盖。
"""
from __future__ import annotations

from typing import Optional

from src.models.status import StatusCode, normalize


PROJECT_ID_CANDIDATES = ["项目编号", "编号", "ID", "Project ID", "项目 ID", "project_id"]
STATUS_CANDIDATES = ["状态", "当前状态", "项目状态", "Status", "status"]
PROJECT_NAME_CANDIDATES = ["项目名", "项目名称", "Name", "name"]
PACKAGE_NAME_CANDIDATES = ["包名", "Package", "package", "Package Name", "package_name"]
# 商店地址（GP/App Store 等上架后的 URL；用于 SECOND_REVIEW 监测是否已上架）
# 注意：不包含 "开关服地址"（那是游戏激活/开关服接口 URL，不是商店 URL）
STORE_URL_CANDIDATES = ["商店地址", "Shop URL", "store_url", "商店链接", "上架地址"]
# 上架地区（项目计划上架的国家/地区；将来用作代理池路由选择）
LAUNCH_REGION_CANDIDATES = ["上架地区", "发布地区", "地区", "Region", "region", "Launch Region",
                            "Available Region", "Country"]
# 支付状态列（独立于"状态"列；通常表里叫"回款"或"支付"）
PAYMENT_CANDIDATES = ["回款", "支付", "付款", "Payment", "payment", "Paid", "PAY"]

# === 用于 /info 命令（app store 投放参数）===
CLASS_NAME_CANDIDATES = ["主activity类名", "主activity 的类名", "类名",
                      "Activity 类名", "activity_class", "MainActivity"]
PRIVACY_POLICY_CANDIDATES = ["隐私政策", "Privacy Policy", "privacy_url", "隐私链接"]
SHA1_CANDIDATES = ["SHA-1", "sha-1", "SHA1", "sha1"]
SHA256_CANDIDATES = ["SHA-256", "sha-256", "SHA256", "sha256",
                     "SHA-2", "sha-2",  # 常见简写(用户 sheet 实测)
                     "SHA256-1", "sha256-1"]
HASH_CANDIDATES = ["hash值", "hash", "哈希值", "Hash", "HASH"]

# === WW 项目新增字段 ===
# 开关服地址:游戏激活/开关服接口 URL(与商店 URL 不同,刻意分开)
OPEN_SERVICE_URL_CANDIDATES = ["开关服地址", "开关服 URL", "开关服链接", "Activation URL"]
# ADJUST KEY:广告/统计平台 key
ADJUST_KEY_CANDIDATES = ["ADJUST KEY", "ADJUST_KEY", "Adjust Key", "adjust_key", "AdjustKey"]
# B 入口名称:多入口分发时的 B 入口标识
B_ENTRY_NAME_CANDIDATES = ["B 入口名称", "B入口", "B entry name", "B_entry_name", "BEntryName"]
# A包:包版本名(package variant label)
A_PACKAGE_CANDIDATES = ["A包", "A 包", "A Package", "A_package", "APackage", "package_a"]


class HeaderDetector:
    """根据表头行（list[str]）匹配已知字段的列号。"""

    def __init__(self, headers: list[str]) -> None:
        # 去除表头单元格的首尾空格
        self.headers = [(h or "").strip() for h in headers]

    def find_column(self, candidates: list[str]) -> Optional[int]:
        """返回 1-indexed 列号；未找到返回 None。匹配规则：候选中任一项精确等于表头。"""
        for i, h in enumerate(self.headers, start=1):
            if h in candidates:
                return i
        return None


def parse_project_id(value: Optional[str]) -> Optional[str]:
    """项目编号解析：去首尾空格，空字符串视为 None。"""
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_status(value: Optional[str]) -> Optional[StatusCode]:
    """状态解析：委托给 status.normalize。"""
    return normalize(value)


def parse_package_name(value: Optional[str]) -> Optional[str]:
    """包名解析：去首尾空格，空字符串视为 None。"""
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_payment_status(value: Optional[str]):
    """支付状态解析：委托给 payment.normalize_payment。"""
    from src.models.payment import normalize_payment
    return normalize_payment(value)