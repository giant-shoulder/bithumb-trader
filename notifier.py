"""
텔레그램 봇 알림 - 매수/매도 체결 시 즉시 알림
"""
import os
import urllib.request
import urllib.parse
import json
from logger import get_logger

logger = get_logger()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send(message: str):
    """텔레그램 메시지 전송 (실패 시 1회 재시도)"""
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }).encode()
    for attempt in range(2):  # 최대 2회 시도
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=10)
            return  # 성공
        except Exception as e:
            if attempt == 0:
                logger.warning(f"[텔레그램 알림 실패, 재시도] {e}")
            else:
                logger.warning(f"[텔레그램 알림 최종 실패] {e}")


def notify_buy(coin: str, price: float, amount: int, count: int, total_splits: int, source: str = ""):
    tag = "🔺 불타기" if count > 1 else "🟢 매수"
    src = f" [{source}]" if source else ""
    msg = (
        f"{tag} <b>{coin}</b>{src}\n"
        f"가격: {price:,.0f}원\n"
        f"금액: {amount:,}원  ({count}/{total_splits}회차)"
    )
    send(msg)


def notify_sell(coin: str, price: float, amount: int, pnl_pct: float, pnl_krw: float, reason: str):
    if pnl_pct >= 0:
        tag = "🔵 익절"
    else:
        tag = "🔴 손절" if "손절" in reason else "⚪ 매도"
    msg = (
        f"{tag} <b>{coin}</b>\n"
        f"가격: {price:,.0f}원\n"
        f"금액: {amount:,}원\n"
        f"손익: {pnl_pct:+.2f}% ({pnl_krw:+,.0f}원)\n"
        f"사유: {reason}"
    )
    send(msg)
