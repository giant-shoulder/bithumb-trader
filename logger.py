"""
거래 로거
"""
import logging
import os
from datetime import datetime
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
    def __init__(self):
        self.log_file = f"trade_history_{datetime.now().strftime('%Y%m')}.csv"
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("시간,코인,유형,가격,수량,금액,손익률,사유\n")

    def log_trade(self, coin: str, trade_type: str, price: float,
                  quantity: float, amount: float, pnl_pct: float = 0.0,
                  reason: str = ""):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{now},{coin},{trade_type},{price:.2f},{quantity:.6f},"
                    f"{amount:.0f},{pnl_pct:.2f},{reason}\n")
        get_logger().info(
            f"[거래기록] {trade_type} {coin} | 가격={price:,.0f} 수량={quantity:.6f} "
            f"금액={amount:,.0f}원 손익={pnl_pct:.2f}% | {reason}"
        )
