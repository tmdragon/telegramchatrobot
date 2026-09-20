"""国家/地区名归一化：中文/英文/ISO code → ISO 3166-1 alpha-2 code。

Phase 3：商店监测按 launch_region 选代理池。region 来自 sheet，可能填中文（如"美国"）
也可能填英文（如 "United States"）或代码（"US"），需要归一化成统一形式。
"""
from __future__ import annotations

# ISO 3166-1 alpha-2 code → 中文常用名 / 英文名
CODE_TO_ZH = {
    "US": "美国", "CA": "加拿大", "MX": "墨西哥",
    "BR": "巴西", "AR": "阿根廷", "CL": "智利",
    "GB": "英国", "IE": "爱尔兰", "FR": "法国", "DE": "德国",
    "IT": "意大利", "ES": "西班牙", "PT": "葡萄牙", "NL": "荷兰",
    "BE": "比利时", "CH": "瑞士", "AT": "奥地利", "SE": "瑞典",
    "NO": "挪威", "DK": "丹麦", "FI": "芬兰", "PL": "波兰",
    "CZ": "捷克", "GR": "希腊", "HU": "匈牙利", "RU": "俄罗斯",
    "TR": "土耳其", "IL": "以色列", "SA": "沙特阿拉伯", "AE": "阿联酋",
    "EG": "埃及", "ZA": "南非", "NG": "尼日利亚", "KE": "肯尼亚",
    "IN": "印度", "PK": "巴基斯坦", "BD": "孟加拉", "LK": "斯里兰卡",
    "TH": "泰国", "VN": "越南", "ID": "印度尼西亚", "MY": "马来西亚",
    "SG": "新加坡", "PH": "菲律宾", "MM": "缅甸", "KH": "柬埔寨",
    "LA": "老挝", "VN": "越南",
    "CN": "中国", "HK": "中国香港", "TW": "中国台湾", "MO": "中国澳门",
    "JP": "日本", "KR": "韩国", "KP": "朝鲜",
    "AU": "澳大利亚", "NZ": "新西兰",
    "SG": "新加坡", "MY": "马来西亚",
    "RU": "俄罗斯", "UA": "乌克兰",
    "IL": "以色列",
}
# 同步建立 反向索引
ZH_TO_CODE: dict[str, str] = {zh: code for code, zh in CODE_TO_ZH.items()}
EN_TO_CODE: dict[str, str] = {
    # 常用英文名 → ISO code
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "england": "GB", "britain": "GB",
    "japan": "JP", "jp": "JP",
    "korea": "KR", "south korea": "KR", "kor": "KR",
    "china": "CN", "cn": "CN", "mainland china": "CN",
    "hong kong": "HK", "hk": "HK",
    "taiwan": "TW", "tw": "TW",
    "japan": "JP",
    "germany": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "italy": "IT", "it": "IT",
    "spain": "ES", "es": "ES",
    "portugal": "PT", "pt": "PT",
    "brazil": "BR", "br": "BR",
    "mexico": "MX", "mx": "MX",
    "india": "IN", "in": "IN",
    "indonesia": "ID", "id": "ID",
    "philippines": "PH", "ph": "PH",
    "vietnam": "VN", "vn": "VN",
    "thailand": "TH", "th": "TH",
    "malaysia": "MY", "my": "MY",
    "singapore": "SG", "sg": "SG",
    "australia": "AU", "au": "AU",
    "new zealand": "NZ", "nz": "NZ",
    "russia": "RU", "ru": "RU",
    "canada": "CA", "ca": "CA",
    "netherlands": "NL", "nl": "NL",
    "sweden": "SE", "se": "SE",
    "norway": "NO", "no": "NO",
    "denmark": "DK", "dk": "DK",
    "finland": "FI", "fi": "FI",
    "ireland": "IE", "ie": "IE",
    "poland": "PL", "pl": "PL",
    "turkey": "TR", "tr": "TR",
    "saudi arabia": "SA", "sa": "SA",
    "united arab emirates": "AE", "uae": "AE",
    "israel": "IL", "il": "IL",
    "south africa": "ZA", "za": "ZA",
    "egypt": "EG", "eg": "EG",
    "russia": "RU", "ru": "RU",
    "ukraine": "UA", "ua": "UA",
    "czech republic": "CZ", "czechia": "CZ",
    "hungary": "HU", "hu": "HU",
    "greece": "GR", "gr": "GR",
}


def normalize_country(value: str | None) -> str | None:
    """把任意国家/地区表示归一化成 ISO 3166-1 alpha-2 大写 code（如 "US"/"JP"）。

    接受的输入形式：
    - ISO code："US" / "us" / "US "
    - 中文："美国" / " 日本 "
    - 英文："United States" / "united_states"

    无法识别 → 返回原值（strip 后大写）以便人工排查。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s:
        return None

    # 1) 直接 ISO code（2 个字母）
    if len(s) == 2 and s.isalpha():
        return s.upper()

    # 2) 中文
    if s in ZH_TO_CODE:
        return ZH_TO_CODE[s]

    # 3) 英文（lowercase 后比较）
    low = s.lower()
    if low in EN_TO_CODE:
        return EN_TO_CODE[low]

    # 4) 下划线/连字符替换再试（如 "united_states"）
    low2 = low.replace("_", " ").replace("-", " ")
    if low2 in EN_TO_CODE:
        return EN_TO_CODE[low2]

    # 5) 兜底：返回原值（strip + 大写）方便排查
    return s.upper()


def country_display(code: str | None) -> str:
    """把 ISO code 翻译回展示用名（中文优先）。"""
    if not code:
        return "—"
    code = code.upper()
    zh = CODE_TO_ZH.get(code)
    if zh:
        return f"{zh} ({code})"
    return code