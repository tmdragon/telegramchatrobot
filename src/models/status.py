"""项目状态模型：枚举 + 别名表 + 状态机。

完整定义见 spec §3.2 与 §3.3。
"""
from __future__ import annotations

from enum import Enum


class StatusCode(str, Enum):
    ORDERED = "ORDERED"
    MAKING = "MAKING"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    REWORK = "REWORK"
    WAITING_AAB = "WAITING_AAB"
    WAITING_SUBMIT = "WAITING_SUBMIT"
    SUBMITTING = "SUBMITTING"
    FIRST_REVIEW_PASSED = "FIRST_REVIEW_PASSED"
    FIRST_REVIEW_REJECTED = "FIRST_REVIEW_REJECTED"
    SECOND_REVIEW = "SECOND_REVIEW"
    REMAKING = "REMAKING"
    PUBLISHED = "PUBLISHED"
    PAID = "PAID"
    UNPAID = "UNPAID"
    OFF_SHELF = "OFF_SHELF"


# 完整别名表（spec §3.2）。标准化函数先精确匹配代码本身，再遍历别名。
ALIASES: dict[StatusCode, list[str]] = {
    StatusCode.ORDERED: ["下单", "已下单", "待开始", "已下单待制作", "对方下单"],
    StatusCode.MAKING: ["制作中", "生产中", "制作", "我方制作中"],
    StatusCode.CLIENT_REVIEW: ["验收中", "客户验收", "客户测试", "对方验收中"],
    StatusCode.REWORK: ["返工", "修改中", "调整中", "返工中"],
    StatusCode.WAITING_AAB: ["等AAB", "AAB包准备中", "等待AAB包"],
    StatusCode.WAITING_SUBMIT: ["等待提审", "待提交"],
    StatusCode.SUBMITTING: ["提审中", "提交中", "提交审核"],
    StatusCode.FIRST_REVIEW_PASSED: ["一审通过", "第一轮通过"],
    StatusCode.FIRST_REVIEW_REJECTED: ["一审打回", "第一轮未通过"],
    StatusCode.SECOND_REVIEW: ["复审中", "最终审核"],
    StatusCode.REMAKING: ["重做中", "重新制作", "修复中", "我方重做中"],
    StatusCode.PUBLISHED: ["已发布", "上线了", "上架","已上架"],
    StatusCode.PAID: ["已回款", "已收款", "已结款", "对方已回款"],
    StatusCode.UNPAID: ["未回款", "未收款", "待回款", "对方未回款"],
    StatusCode.OFF_SHELF: ["已下架", "下架", "下架了", "已下线"],
}


# 合法转换（spec §3.3 LEGAL_TRANSITIONS）
LEGAL_TRANSITIONS: dict[StatusCode, set[StatusCode]] = {
    StatusCode.ORDERED: {StatusCode.MAKING},
    StatusCode.MAKING: {StatusCode.CLIENT_REVIEW},
    StatusCode.CLIENT_REVIEW: {StatusCode.REWORK, StatusCode.WAITING_AAB},
    StatusCode.REWORK: {StatusCode.CLIENT_REVIEW},
    StatusCode.WAITING_AAB: {StatusCode.WAITING_SUBMIT},
    StatusCode.WAITING_SUBMIT: {StatusCode.SUBMITTING},
    StatusCode.SUBMITTING: {StatusCode.FIRST_REVIEW_PASSED, StatusCode.FIRST_REVIEW_REJECTED},
    StatusCode.FIRST_REVIEW_PASSED: {StatusCode.SECOND_REVIEW},
    StatusCode.FIRST_REVIEW_REJECTED: {StatusCode.SUBMITTING},
    StatusCode.SECOND_REVIEW: {StatusCode.PUBLISHED, StatusCode.REMAKING},
    StatusCode.REMAKING: {StatusCode.MAKING},
    StatusCode.PUBLISHED: {StatusCode.PAID, StatusCode.UNPAID, StatusCode.OFF_SHELF},
    StatusCode.PAID: {StatusCode.UNPAID},
    StatusCode.UNPAID: {StatusCode.PAID},
    StatusCode.OFF_SHELF: set(),
}


def normalize(value: str | None) -> StatusCode | None:
    """把任意文本规范化成 StatusCode；无法识别返回 None。

    规则：去首尾空格 → 大写 → 先比代码本身 → 再遍历别名表。
    """
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    upper = s.upper()
    # 先比代码本身（精确匹配优先级最高）
    for code in StatusCode:
        if upper == code.value:
            return code
    # 再比别名（用原始 s，因为别名有中文）
    for code, aliases in ALIASES.items():
        if s in aliases:
            return code
    return None


def is_legal(from_: StatusCode, to: StatusCode) -> bool:
    """判断 from_ → to 是否为合法转换。"""
    return to in LEGAL_TRANSITIONS.get(from_, set())


def legal_next_states(current: StatusCode) -> set[StatusCode]:
    """返回当前状态可去的下一个状态集合。"""
    return set(LEGAL_TRANSITIONS.get(current, set()))