"""
자동매매 실행 엔진
홍인기 전략 기반 빗섬 자동매매
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from bithumb_api import BithumbAPI
from strategy import HongStrategy
from logger import get_logger, TradeLogger
from config import (
    WATCHLIST, MAX_POSITION_KRW, BUY_UNIT_KRW,
    BUY_SPLIT, POLLING_INTERVAL, MIN_VOLUME_RANK
)

logger = get_logger()
trade_logger = TradeLogger()


@dataclass
class Position:
    """보유 포지션"""
    coin: str
    buy_price: float
    quantity: float
    buy_count: int = 1           # 불타기 횟수
    total_amount: float = 0.0    # 총 투자금액
    highest_price: float = 0.0   # 진입 후 최고가 (트레일링 스탑용)
    entry_time: str = ""

    def __post_init__(self):
        self.entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.total_amount:
            self.total_amount = self.buy_price * self.quantity
        if not self.highest_price:
            self.highest_price = self.buy_price

    @property
    def pnl_pct(self) -> float:
        return (self.current_price - self.buy_price) / self.buy_price * 100 if hasattr(self, '_current_price') else 0.0

    def avg_price(self) -> float:
        return self.total_amount / self.quantity if self.quantity > 0 else 0


class AutoTrader:
    def __init__(self):
        self.api = BithumbAPI()
        self.strategy = HongStrategy()
        self.positions: dict[str, Position] = {}  # 보유 포지션
        self.is_running = False
        logger.info("=" * 50)
        logger.info("빗섬 자동매매 시스템 시작 (홍인기 전략)")
        logger.info("=" * 50)

    # ===== 메인 루프 =====

    def run(self):
        """메인 실행 루프"""
        self.is_running = True
        while self.is_running:
            try:
                logger.info(f"\n{'='*40}")
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 전략 실행 중...")

                # 1. 거래대금 상위 코인 조회
                top_coins = self._get_top_coins()
                if not top_coins:
                    logger.warning("거래대금 데이터 조회 실패")
                    time.sleep(POLLING_INTERVAL)
                    continue

                self._log_market_overview(top_coins)

                # 2. 보유 포지션 관리 (매도 우선)
                self._manage_positions(top_coins)

                # 3. 신규 매수 탐색
                self._scan_for_entry(top_coins)

                # 4. 대기
                logger.info(f"다음 실행: {POLLING_INTERVAL}초 후")
                time.sleep(POLLING_INTERVAL)

            except KeyboardInterrupt:
                logger.info("\n사용자 중단 요청")
                self._shutdown()
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {e}", exc_info=True)
                time.sleep(10)

    def stop(self):
        self.is_running = False

    def _shutdown(self):
        """종료 처리"""
        logger.info("시스템 종료 중...")
        if self.positions:
            logger.warning(f"미청산 포지션 {len(self.positions)}개:")
            for coin, pos in self.positions.items():
                price = self.api.get_current_price(coin)
                if price:
                    pnl = (price - pos.buy_price) / pos.buy_price * 100
                    logger.warning(f"  {coin}: 매입가={pos.buy_price:,.0f} 현재={price:,.0f} ({pnl:+.1f}%)")

    # ===== 거래대금 상위 코인 =====

    def _get_top_coins(self) -> list:
        """거래대금 상위 코인 목록 조회"""
        return self.api.get_volume_ranking(WATCHLIST, top_n=MIN_VOLUME_RANK * 2)

    def _log_market_overview(self, top_coins: list):
        """시장 현황 로그"""
        logger.info("거래대금 상위 코인:")
        for i, c in enumerate(top_coins[:5], 1):
            logger.info(f"  {i}위 {c['coin']}: {c['volume_krw']/1e8:.1f}억 | {c['change_pct']:+.1f}%")

    # ===== 포지션 관리 (매도) =====

    def _manage_positions(self, top_coins: list):
        """보유 포지션 매도 판단"""
        if not self.positions:
            return

        coins_to_sell = []
        volume_rank_map = {c['coin']: i+1 for i, c in enumerate(top_coins)}

        for coin, pos in self.positions.items():
            current_price = self.api.get_current_price(coin)
            if not current_price:
                continue

            df = self.api.get_ohlcv(coin, interval="1h", count=200)
            if df is None:
                continue

            # 최고가 갱신 (트레일링 스탑용)
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            rank = volume_rank_map.get(coin, 99)

            signal = self.strategy.check_sell_signal(
                coin, df, pos.buy_price, current_price, rank, pos.highest_price
            )

            logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                        f"손익={pnl_pct:+.1f}% | {'⚠️ 매도신호' if signal['sell'] else '보유중'}")

            if signal['sell']:
                coins_to_sell.append((coin, pos, current_price, signal))

        for coin, pos, price, signal in coins_to_sell:
            self._execute_sell(coin, pos, price, signal['reason'])

    def _execute_sell(self, coin: str, pos: Position, price: float, reason: str):
        """매도 실행"""
        logger.info(f"[매도 실행] {coin} | 사유: {reason}")
        result = self.api.sell_market(coin, pos.quantity)
        if result:
            pnl_pct = (price - pos.buy_price) / pos.buy_price * 100
            trade_logger.log_trade(
                coin, "매도", price, pos.quantity,
                pos.quantity * price, pnl_pct, reason
            )
            del self.positions[coin]
            logger.info(f"[매도 완료] {coin} | 손익: {pnl_pct:+.1f}%")

    # ===== 신규 매수 탐색 =====

    def _scan_for_entry(self, top_coins: list):
        """신규 매수 후보 탐색"""
        # 이미 보유 중인 코인 제외
        candidates = [c for c in top_coins if c['coin'] not in self.positions]

        for i, coin_data in enumerate(candidates[:MIN_VOLUME_RANK]):
            coin = coin_data['coin']
            rise_rate = coin_data['change_pct']
            rank = i + 1

            df = self.api.get_ohlcv(coin, interval="1h", count=200)
            if df is None:
                continue

            signal = self.strategy.check_buy_signal(coin, df, rank, rise_rate)

            if signal['buy']:
                logger.info(f"[매수 신호] {coin} | {' | '.join(signal['reasons'])}")
                self._execute_buy(coin, coin_data['price'])
            else:
                logger.debug(f"[{coin}] 매수 보류: {', '.join(signal['fail_reasons'])}")

    def _execute_buy(self, coin: str, price: float):
        """매수 실행"""
        # 이미 보유 중이면 불타기
        if coin in self.positions:
            pos = self.positions[coin]
            if pos.buy_count >= BUY_SPLIT:
                logger.info(f"[{coin}] 불타기 최대 횟수({BUY_SPLIT}회) 도달")
                return
            # 불타기
            logger.info(f"[불타기] {coin} | {pos.buy_count+1}/{BUY_SPLIT}회차")
            krw = BUY_UNIT_KRW
        else:
            # 신규 매수
            krw_balance = self.api.get_krw_balance()
            if krw_balance < BUY_UNIT_KRW:
                logger.warning(f"원화 잔고 부족: {krw_balance:,.0f}원 (필요: {BUY_UNIT_KRW:,.0f}원)")
                return
            logger.info(f"[신규 매수] {coin} | 1/{BUY_SPLIT}회차")
            krw = BUY_UNIT_KRW

        result = self.api.buy_market(coin, krw)
        if result:
            quantity = krw / price
            if coin in self.positions:
                pos = self.positions[coin]
                pos.quantity += quantity
                pos.total_amount += krw
                pos.buy_count += 1
                # 평균 매입가 갱신
                pos.buy_price = pos.total_amount / pos.quantity
            else:
                self.positions[coin] = Position(
                    coin=coin,
                    buy_price=price,
                    quantity=quantity,
                    total_amount=krw
                )
            trade_logger.log_trade(coin, "매수", price, quantity, krw, reason="매수신호")
            logger.info(f"[매수 완료] {coin} | 가격={price:,.0f} 금액={krw:,.0f}원")

    # ===== 상태 조회 =====

    def get_status(self) -> str:
        """현재 상태 요약"""
        lines = [f"\n{'='*40}", "현재 포지션"]
        if not self.positions:
            lines.append("  없음")
        else:
            for coin, pos in self.positions.items():
                price = self.api.get_current_price(coin) or pos.buy_price
                pnl = (price - pos.buy_price) / pos.buy_price * 100
                lines.append(
                    f"  {coin}: 매입={pos.buy_price:,.0f} 현재={price:,.0f} "
                    f"손익={pnl:+.1f}% | {pos.buy_count}/{BUY_SPLIT}회"
                )
        lines.append(f"{'='*40}")
        return "\n".join(lines)
