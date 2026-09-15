from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from icalendar import Calendar, Event, vDuration

from src.models import CalendarEvent, event_sort_key
from src.utils.timezone import display_time

CALENDAR_TITLES = {
    "macro": "宏观经济",
    "earnings": "自选股财报",
    "market": "市场交易",
    "all": "全部事件",
}

DESCRIPTION_LABELS = {
    "Ticker": "股票代码",
    "Company": "公司",
    "Earnings Date": "财报日期",
    "Earnings Time": "财报时段",
    "Fiscal Quarter": "财务季度",
    "Fiscal Quarter Source": "财务季度来源",
    "EPS Estimate": "每股收益预期",
    "Revenue Estimate": "营收预期",
    "Event": "事件",
    "Indicator": "指标",
    "Release": "发布项目",
    "Estimate Stage": "估值阶段",
    "Reference Period": "数据所属期",
    "Reference Week Ending": "统计周截止日",
    "Meeting": "会议日期",
    "Meeting End Date": "会议结束日期",
    "Market": "市场",
    "Status": "状态",
    "Holiday": "节假日",
    "Official Close": "正式收市时间",
    "Rule": "规则",
    "Schedule Method": "日期确定方式",
}

DESCRIPTION_ORDER = {key: index for index, key in enumerate(DESCRIPTION_LABELS)}

COMPANY_NAMES = {
    "AAPL": "苹果",
    "AMD": "超威半导体",
    "AMZN": "亚马逊",
    "AVGO": "博通",
    "GOOGL": "谷歌母公司",
    "META": "脸书母公司",
    "MSFT": "微软",
    "MU": "美光科技",
    "NVDA": "英伟达",
    "TSM": "台积电",
}

VALUE_TRANSLATIONS = {
    "BMO": "盘前（BMO）",
    "AMC": "盘后（AMC）",
    "TAS": "时间待定（TAS）",
    "Advance Estimate": "初值",
    "Second Estimate": "第二次估值",
    "Third Estimate": "终值",
    "Federal Open Market Committee Meeting": "联邦公开市场委员会会议",
    "Quarterly derivatives expiration concentration": "季度衍生品集中到期",
    "Consumer Price Index": "消费者价格指数",
    "Core Consumer Price Index": "核心消费者价格指数",
    "Producer Price Index": "生产者价格指数",
    "Core Producer Price Index": "核心生产者价格指数",
    "Nonfarm Payrolls": "非农就业人数",
    "Unemployment Rate": "失业率",
    "PCE Price Index": "PCE 物价指数",
    "Core PCE Price Index": "核心 PCE 物价指数",
    "NYSE equities": "纽约证券交易所股票市场",
    "Early Close": "提前收市",
    "Full Market Holiday": "全天休市",
    "Third Friday of March, June, September and December": "每年三月、六月、九月和十二月的第三个星期五",
    "Fallback: ISM first-business-day rule": "备用规则：ISM 每月第一个工作日",
    "Fallback: ISM third-business-day rule": "备用规则：ISM 每月第三个工作日",
    "Federal Reserve three-week publication policy": "美联储会后三周发布规则",
    "Normal Thursday 08:30 ET publication pattern": "通常于周四美国东部时间 08:30 发布",
    "Normal Thursday publication; moved one day earlier for a federal holiday": "通常周四发布；遇联邦假日提前一天",
    "Official release date": "官方发布日期",
    "calendar-quarter fallback; Yahoo does not expose a fiscal period here": "采用自然季度备用值；雅虎财经未提供财务期间",
    "FOMC Minutes": "FOMC 会议纪要",
    "FOMC Statement and Interest Rate Decision": "FOMC 声明及利率决议",
    "ISM Manufacturing PMI Report": "ISM 制造业 PMI 报告",
    "ISM Services PMI Report": "ISM 服务业 PMI 报告",
    "Unemployment Insurance Weekly Claims Report": "失业保险每周申领报告",
}

HOLIDAY_NAMES = {
    "New Years Day": "元旦",
    "Dr. Martin Luther King Jr. Day": "马丁·路德·金纪念日",
    "Presidents Day": "总统日",
    "Good Friday 1908+": "耶稣受难日",
    "Memorial Day": "阵亡将士纪念日",
    "Juneteenth Starting at 2022": "六月节",
    "July 4th": "美国独立日",
    "Labor Day": "劳动节",
    "Thanksgiving": "感恩节",
    "Christmas": "圣诞节",
}

SOURCE_NAMES = {
    "U.S. Bureau of Labor Statistics (BLS)": "美国劳工统计局（BLS）",
    "FRED release calendar (dates supplied by BLS)": "FRED 发布日历（日期由 BLS 提供）",
    "U.S. Bureau of Economic Analysis (BEA)": "美国经济分析局（BEA）",
    "U.S. Census Bureau": "美国人口普查局",
    "Federal Reserve Board": "美国联邦储备委员会",
    "Institute for Supply Management (ISM)": "美国供应管理协会（ISM）",
    "U.S. Department of Labor (ETA)": "美国劳工部就业与培训管理局（ETA）",
    "Yahoo Finance via yfinance": "雅虎财经（通过 yfinance）",
    "NYSE schedule via pandas-market-calendars": "纽约证券交易所日程（通过 pandas-market-calendars）",
    "Calendar rule": "日历规则",
}

MONTH_NAMES = {
    "January": "一月",
    "February": "二月",
    "March": "三月",
    "April": "四月",
    "May": "五月",
    "June": "六月",
    "July": "七月",
    "August": "八月",
    "September": "九月",
    "October": "十月",
    "November": "十一月",
    "December": "十二月",
}


def _translate_period_text(value: str) -> str:
    translated = value
    for english, chinese in MONTH_NAMES.items():
        translated = re.sub(rf"\b{english}\b", chinese, translated)
    for ordinal, number in (("1st", "一"), ("2nd", "二"), ("3rd", "三"), ("4th", "四")):
        translated = re.sub(rf"\b{ordinal} Quarter\b", f"第{number}季度", translated)
    chinese_months = "|".join(sorted(MONTH_NAMES.values(), key=len, reverse=True))
    translated = re.sub(
        rf"({chinese_months})\s+(20\d{{2}})",
        lambda match: f"{match.group(2)}年{match.group(1)}",
        translated,
    )
    translated = re.sub(r"第([一二三四])季度\s+(20\d{2})", r"\2年第\1季度", translated)
    return translated


def _translate_release(value: str) -> str:
    translated = _translate_period_text(value)
    replacements = (
        ("Advance Monthly Retail Trade Report", "月度零售贸易预估报告"),
        ("Consumer Price Index for", "消费者价格指数，"),
        ("Employment Situation for", "就业形势报告，"),
        ("Producer Price Index for", "生产者价格指数，"),
        ("Personal Income and Outlays", "个人收入与支出"),
        ("GDP (Advance Estimate)", "国内生产总值（GDP）初值"),
        ("GDP (Second Estimate)", "国内生产总值（GDP）第二次估值"),
        ("GDP (Third Estimate)", "国内生产总值（GDP）终值"),
        ("Corporate Profits", "企业利润"),
        ("Industries", "行业数据"),
        ("State GDP", "各州 GDP"),
        ("State Personal Income", "各州个人收入"),
        ("State PCE", "各州 PCE"),
        (" and ", "及"),
    )
    for english, chinese in replacements:
        translated = translated.replace(english, chinese)
    return (
        translated.replace("， ", "，")
        .replace(", ", "，")
        .replace(",", "，")
        .replace("; ", "；")
    )


def _translate_description_value(event: CalendarEvent, key: str, value: Any) -> str:
    text = str(value)
    if key == "Company":
        ticker = str(event.metadata.get("ticker", ""))
        return COMPANY_NAMES.get(ticker, text)
    if key == "Holiday":
        return HOLIDAY_NAMES.get(text, text)
    if key == "Release":
        return VALUE_TRANSLATIONS.get(text, _translate_release(text))
    if key == "Meeting":
        return text.replace(" to ", " 至 ")
    if key == "Official Close":
        return re.sub(r" (EST|EDT)$", r"（美国东部时间 \1）", text)
    if key == "Fiscal Quarter":
        return re.sub(r"^(\d{4})Q([1-4])$", r"\1年第\2季度", text)
    return VALUE_TRANSLATIONS.get(text, text)


def _description_text(
    event: CalendarEvent, *, timezone_name: str, updated_at: datetime
) -> str:
    lines = [
        f"{DESCRIPTION_LABELS.get(key, key)}: {_translate_description_value(event, key, value)}"
        for key, value in sorted(
            event.description.items(),
            key=lambda item: (DESCRIPTION_ORDER.get(item[0], len(DESCRIPTION_ORDER)), item[0]),
        )
        if value not in (None, "")
    ]
    if not event.all_day and isinstance(event.start, datetime):
        lines.append(f"本地时间（{timezone_name}）: {display_time(event.start, timezone_name)}")
    lines.extend(
        [
            f"来源: {SOURCE_NAMES.get(event.source, event.source)}",
            f"来源链接: {event.source_url}",
            f"最后更新: {updated_at.astimezone(timezone.utc).isoformat()}",
        ]
    )
    return "\n".join(lines)


def build_calendar(
    events: Iterable[CalendarEvent],
    *,
    category: str,
    calendar_name: str,
    timezone_name: str,
    updated_at_by_category: dict[str, datetime],
) -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", "-//Finance Calendar//finance-calendar//ZH-CN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", f"{calendar_name} · {CALENDAR_TITLES[category]}")
    calendar.add("x-wr-timezone", timezone_name)
    calendar["refresh-interval"] = vDuration(timedelta(hours=12))
    calendar.add("x-published-ttl", "PT12H")

    seen: set[str] = set()
    for item in sorted(events, key=event_sort_key):
        if item.uid in seen:
            continue
        seen.add(item.uid)
        component = Event()
        component.add("uid", item.uid)
        updated_at = updated_at_by_category[item.category]
        component.add("dtstamp", updated_at.astimezone(timezone.utc))
        component.add("summary", item.summary)
        component.add(
            "description",
            _description_text(item, timezone_name=timezone_name, updated_at=updated_at),
        )
        component.add("url", item.source_url)
        component.add("categories", [item.category.upper(), item.kind.upper()])

        if item.all_day:
            component.add("dtstart", item.start)
            component.add("dtend", item.end)
            component.add("transp", "TRANSPARENT")
        else:
            start = item.start
            end = item.end
            if not isinstance(start, datetime) or not isinstance(end, datetime):
                raise TypeError(f"timed event {item.uid} must use datetime")
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError(f"timed event {item.uid} must be timezone-aware")
            component.add("dtstart", start.astimezone(timezone.utc))
            component.add("dtend", end.astimezone(timezone.utc))
        calendar.add_component(component)
    return calendar


def write_calendar(calendar: Calendar, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = calendar.to_ical()
    if not data.endswith(b"\r\n"):
        data += b"\r\n"
    path.write_bytes(data)


def empty_timestamp() -> datetime:
    return datetime.combine(date(1970, 1, 1), time.min, tzinfo=timezone.utc)
