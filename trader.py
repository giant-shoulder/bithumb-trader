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
    MAX_POSITION_KRW, BUY_UNIT_KRW, BUY_SPLIT,
    POLLING_INTERVAL, MOMENTUM_TOP_N, MIN_VOLUME_24H_KRW,
    MIN_HOLD_SECONDS
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
    def __init__(self, dry_run: bool = False):
        self.api = BithumbAPI()
        self.strategy = HongStrategy()
        self.positions: dict[str, Position] = {}
        self.is_running = False
        self.dry_run = dry_run
        logger.info("=" * 50)
        logger.info("빗섬 자동매매 시스템 시작 (홍인기 전략)")
        logger.info("=" * 50)
        self._load_existing_positions()

    def _load_existing_positions(self):
        """시작 시 실제 보유 코인을 포지션으로 로드"""
        try:
            accounts = self.api.get_accounts()
            if not isinstance(accounts, list):
                logger.warning(f"계좌 조회 응답 오류: {accounts}")
                return
            for acc in accounts:
                coin = acc.get('currency')
                balance = float(acc.get('balance', 0))
                avg_price = float(acc.get('avg_buy_price', 0))
                if coin == 'KRW' or coin == 'P' or balance <= 0 or avg_price <= 0:
                    continue
                self.positions[coin] = Position(
                    coin=coin,
                    buy_price=avg_price,
                    quantity=balance,
                    total_amount=avg_price * balance,
                )
                logger.info(f"[기존 포지션 로드] {coin}: {balance:.6f}개 @ {avg_price:,.0f}원")
        except Exception as e:
            logger.error(f"기존 포지션 로드 실패: {e}")

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
        """전체 KRW 종목 모멘텀 스캔"""
        return self.api.scan_momentum_coins(
            min_volume_24h=MIN_VOLUME_24H_KRW,
            top_n=MOMENTUM_TOP_N
        )

    def _log_market_overview(self, top_coins: list):
        """시장 현황 로그"""
        logger.info("모멘텀 상위 코인:")
        for i, c in enumerate(top_coins[:5], 1):
            logger.info(f"  {i}위 {c['coin']}: {c['volume_krw']/1e8:.1f}억 | {c['change_pct']:+.1f}% | 스코어={c['score']:.2e}")

    # ===== 포지션 관리 (매도) =====

    def _manage_positions(self, top_coins: list):
        """보유 포지션 매도 판단"""
        if not self.positions:
            return

        coins_to_sell = []
        # 스캔 결과 내 순위 (없으면 999 → 모멘텀 소멸로 간주)
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
            rank = volume_rank_map.get(coin, 999)

            # 최소 보유시간 체크
            hold_secs = (datetime.now() - datetime.strptime(pos.entry_time, "%Y-%m-%d %H:%M:%S")).total_seconds()
            if hold_secs < MIN_HOLD_SECONDS:
                logger.debug(f"[{coin}] 최소 보유시간 미충족: {hold_secs:.0f}s / {MIN_HOLD_SECONDS}s")
                continue

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
        if self.dry_run:
            logger.info(f"[DRY] 매도 생략: {coin} {pos.quantity}")
            del self.positions[coin]
            return
        # 실제 잔고 조회 (추적 수량과 오차 방지)
        actual_qty = self.api.get_coin_balance(coin)
        if actual_qty <= 0:
            logger.warning(f"[{coin}] 실제 잔고 없음, 포지션 제거")
            del self.positions[coin]
            return
        result = self.api.sell_market(coin, actual_qty)
        if result:
            pnl_pct = (price - pos.buy_price) / pos.buy_price * 100
            trade_logger.log_trade(
                coin, "매도", price, actual_qty,
                actual_qty * price, pnl_pct, reason
            )
            del self.positions[coin]
            logger.info(f"[매도 완료] {coin} | 손익: {pnl_pct:+.1f}%")

    # ===== 신규 매수 탐색 =====

    def _scan_for_entry(self, top_coins: list):
        """신규 매수 후보 탐색 - 조건 통과 종목 중 RSI 가장 낮은 것 선택"""
        candidates = [c for c in top_coins if c['coin'] not in self.positions]

        buy_candidates = []
        for coin_data in candidates:
            coin = coin_data['coin']
            df = self.api.get_ohlcv(coin, interval="1h", count=200)
            if df is None:
                continue

            signal = self.strategy.check_buy_signal(coin, df, coin_data['score'])

            if signal['buy']:
                buy_candidates.append((coin_data, signal))
                logger.info(f"[매수 후보] {coin} | RSI={signal['rsi']:.1f} | {' | '.join(signal['reasons'])}")
            else:
                logger.debug(f"[{coin}] 매수 보류: {', '.join(signal['fail_reasons'])}")

        if not buy_candidates:
            return

        # RSI 가장 낮은 것 선택 (추가 상승 여력 최대)
        best_coin_data, best_signal = min(buy_candidates, key=lambda x: x[1]['rsi'])
        logger.info(f"[최종 선택] {best_coin_data['coin']} | RSI={best_signal['rsi']:.1f}")
        self._execute_buy(best_coin_data['coin'], best_coin_data['price'])

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
            MIN_ORDER_KRW = 5000  # 빗썸 최소 주문금액
            if krw_balance < MIN_ORDER_KRW:
                logger.warning(f"원화 잔고 부족: {krw_balance:,.0f}원 (최소: {MIN_ORDER_KRW:,}원)")
                return
            krw = min(BUY_UNIT_KRW, int(krw_balance * 0.995))
            if krw < BUY_UNIT_KRW:
                logger.info(f"[신규 매수] {coin} | 1/{BUY_SPLIT}회차 (잔고 맞춤: {krw:,.0f}원)")
            else:
                logger.info(f"[신규 매수] {coin} | 1/{BUY_SPLIT}회차")

        if self.dry_run:
            logger.info(f"[DRY] 매수 생략: {coin} {krw:,.0f}원")
            return

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
                    f"  {coin}: 매수={pos.buy_price:,.0f} 현재={price:,.0f} "
                    f"손익={pnl:+.1f}% | {pos.buy_count}/{BUY_SPLIT}회"
                )
        lines.append(f"{'='*40}")
        return "\n".join(lines)
