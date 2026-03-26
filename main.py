"""
빗섬 자동매매 - 메인 진입점
Claude 단타 전략

실행 방법:
  python main.py          # 실전 매매
  python main.py --dry    # 모의 실행 (주문 없음)
  python main.py --status # 현재 상태만 확인
"""
import sys
import argparse
from trader import AutoTrader
from logger import get_logger

logger = get_logger()


def main():
    parser = argparse.ArgumentParser(description="빗섬 자동매매 - Claude 전략")
    parser.add_argument("--dry", action="store_true", help="모의 실행 (실제 주문 없음)")
    parser.add_argument("--status", action="store_true", help="현재 상태 확인 후 종료")
    args = parser.parse_args()

    if args.dry:
        logger.info("⚠️  모의 실행 모드 (실제 주문 없음)")

    trader = AutoTrader(dry_run=args.dry)

    if args.status:
        print(trader.get_status())
        return

    logger.info("자동매매 시작. 중단하려면 Ctrl+C")
    from config import MAX_POSITION_KRW, BUY_SPLIT
    logger.info(f"설정: 종목당 최대 {MAX_POSITION_KRW:,}원 | 분할매수 {BUY_SPLIT}회")

    try:
        trader.run()
    except KeyboardInterrupt:
        logger.info("종료됨")


if __name__ == "__main__":
    main()
