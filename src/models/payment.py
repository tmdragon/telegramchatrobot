"""支付状态模型：独立于生产流程的字段。

设计动机：PAID/UNPAID 不属于"包体生产/上架"流程，是商务回款的状态；
从 StatusCode 拆出来作为 Project.payment_status 独立字段，避免
LEGAL_TRANSITIONS 状态机被无关的商务流转污染。
"""
from __future__ import annotations

from enum import Enum


class PaymentStatus(str, Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"


# 别名表（spec §3.2 类似结构）
PAYMENT_ALIASES: dict[PaymentStatus, list[str]] = {
    PaymentStatus.PAID: [
        "已回款", "已收款", "已结款", "对方已回款", "已支付",
        "paid", "PAID",
    ],
    PaymentStatus.UNPAID: [
        "未回款", "未收款", "待回款", "对方未回款", "未支付",
        "unpaid", "UNPAID",
    ],
}


def normalize_payment(value: str | None) -> PaymentStatus | None:
    """把任意文本规范化成 PaymentStatus；无法识别返回 None。

    规则：去首尾空格 → 先精确匹配代码本身 → 再遍历别名表。
    """
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    upper = s.upper()
    for ps in PaymentStatus:
        if upper == ps.value:
            return ps
    for ps, aliases in PAYMENT_ALIASES.items():
        if s in aliases:
            return ps
    return None


def is_terminal(payment_status: PaymentStatus | None) -> bool:
    """PAID 视为终态（已回款不再变）；UNPAID 可回到 PAID。"""
    return payment_status == PaymentStatus.PAID