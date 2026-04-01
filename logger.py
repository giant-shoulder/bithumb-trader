"""
거래 로거
"""
import logging
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
from config import LOG_FILE


def get_logger(name: str = "bithumb_trader") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    formatter.converter = lambda *args: datetime.now(KST).timetuple()

    # 콘솔 출력
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 파일 출력
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


class TradeLogger:
    """거래 기록 전용 로거"""

    def _trade_file(self) -> str:
        return f"trade_history_{datetime.now(KST).strftime('%Y%m')}.csv"

    def _reject_file(self) -> str:
        return f"reject_history_{datetime.now(KST).strftime('%Y%m')}.csv"

    def _ensure_header(self, path: str, header: str):
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                f.write(header)

    def log_trade(self, coin: str, trade_type: str, price: float,
                  quantity: float, amount: float, pnl_pct: float = 0.0,
                  reason: str = "", source: str = "momentum"):
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        path = self._trade_file()
        self._ensure_header(path, "시간,코인,유형,가격,수량,금액,손익률,사유,신호출처\n")
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{now},{coin},{trade_type},{price:.2f},{quantity:.6f},"
                    f"{amount:.0f},{pnl_pct:.2f},{reason},{source}\n")
        get_logger().info(
            f"[거래기록] {trade_type} {coin} | 가격={price:,.0f} 수량={quantity:.6f} "
            f"금액={amount:,.0f}원 손익={pnl_pct:.2f}% | {reason} [{source}]"
        )

    def log_reject(self, coin: str, reason: str, price: float):
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        path = self._reject_file()
        self._ensure_header(path, "시간,코인,탈락사유,탈락시가격\n")
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"{now},{coin},{reason},{price:.2f}\n")
