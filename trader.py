"""
자동매매 실행 엔진
Claude 전략 기반 빗섬 자동매매
"""
import time
import queue
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from bithumb_api import BithumbAPI
from strategy import ClaudeStrategy
from logger import get_logger, TradeLogger
from config import (
    MAX_POSITION_KRW, BUY_UNIT_KRW, BUY_SPLIT,
    POLLING_INTERVAL_IDLE, POLLING_INTERVAL_ACTIVE,
    MOMENTUM_TOP_N, MIN_VOLUME_24H_KRW,
    MIN_HOLD_SECONDS,
    COOLDOWN_AFTER_STOP_LOSS, COOLDOWN_AFTER_TAKE_PROFIT,
    DAILY_LOSS_LIMIT_PCT,
    BUY_LIMIT_OFFSET_PCT,
    MAX_CONCURRENT_POSITIONS,
    MIN_PRICE_KRW,
    TRADING_BLOCK_START, TRADING_BLOCK_END,
    BUY_CANDLE_INTERVAL, BUY_CANDLE_COUNT,
    COIN_BLACKLIST,
    DAILY_COIN_STOP_LIMIT,
    HARD_STOP_MIN_HOLD_SECONDS,
)

KST = timezone(timedelta(hours=9))

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
        self.strategy = ClaudeStrategy()
        self.positions: dict[str, Position] = {}
        self.sell_cooldown: dict[str, float] = {}  # coin -> cooldown_end_timestamp
        self.daily_coin_stops: dict[str, int] = {}  # coin -> 당일 손절 횟수
        self.is_running = False
        self.dry_run = dry_run
        self.daily_pnl_krw = 0.0
        self.daily_reset_date = datetime.now().date()
        self.telegram_queue: queue.Queue = queue.Queue()
        logger.info("=" * 50)
        logger.info("빗섬 자동매매 시스템 시작 (Claude 전략 v2)")
        logger.info(f"설정: 하드손절 -1.2% | 트레일링 +1%/-0.5% | 익절 +4%")
        logger.info(f"설정: 최소가격 {MIN_PRICE_KRW}원 | 거래중단 {TRADING_BLOCK_START}~{TRADING_BLOCK_END}시")
        logger.info(f"설정: 최대 포지션 {MAX_CONCURRENT_POSITIONS}개 | 캔들 {BUY_CANDLE_INTERVAL}")
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

    # ===== 거래 시간 체크 =====

    def _is_trading_hours(self) -> bool:
        """KST 기준 거래 허용 시간인지 확인 (매수 전용, 매도는 항상 가능)"""
        now_kst = datetime.now(KST)
        return not (TRADING_BLOCK_START <= now_kst.hour < TRADING_BLOCK_END)

    # ===== 메인 루프 =====

    def run(self):
        """메인 실행 루프"""
        self.is_running = True
        while self.is_running:
            try:
                logger.info(f"\n{'='*40}")
                now_kst = datetime.now(KST)
                logger.info(f"[{now_kst.strftime('%H:%M:%S')}] 전략 실행 중...")

                # 일일 손실 한도 체크
                if not self._check_daily_loss_limit():
                    interval = POLLING_INTERVAL_IDLE
                    logger.info(f"다음 실행: {interval}초 후")
                    time.sleep(interval)
                    continue

                # 1. 거래대금 상위 코인 조회
                top_coins = self._get_top_coins()
                if not top_coins:
                    logger.warning("거래대금 데이터 조회 실패")
                    time.sleep(POLLING_INTERVAL_IDLE)
                    continue

                self._log_market_overview(top_coins)

                # 2. 보유 포지션 관리 (매도 우선 - 항상 실행)
                self._manage_positions(top_coins)

                # 3. 텔레그램 신호 처리 (거래 시간 내에만)
                if self._is_trading_hours():
                    self._process_telegram_signals()

                # 4. 신규 매수 탐색 (거래 시간 내에만)
                if self._is_trading_hours():
                    self._scan_for_entry(top_coins)
                else:
                    logger.info(f"[거래시간 외] 현재 {now_kst.strftime('%H:%M')} KST "
                                f"(차단: {TRADING_BLOCK_START}:00~{TRADING_BLOCK_END}:00) - 매수 탐색 스킵")

                # 5. 포지션 유무에 따라 대기 시간 결정
                interval = POLLING_INTERVAL_ACTIVE if self.positions else POLLING_INTERVAL_IDLE
                logger.info(f"다음 실행: {interval}초 후 ({'포지션 있음' if self.positions else '대기 중'})")
                time.sleep(interval)

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

    # ===== 일일 손실 한도 =====

    def _check_daily_loss_limit(self) -> bool:
        """일일 손실 한도 체크. 한도 초과 시 False 반환"""
        today = datetime.now().date()
        if today != self.daily_reset_date:
            self.daily_pnl_krw = 0.0
            self.daily_coin_stops = {}
            self.daily_reset_date = today
            logger.info("일일 손익 초기화")

        if self.daily_pnl_krw < 0:
            loss_pct = abs(self.daily_pnl_krw) / MAX_POSITION_KRW * 100
            if loss_pct >= DAILY_LOSS_LIMIT_PCT:
                logger.warning(f"일일 손실 한도 도달: {self.daily_pnl_krw:,.0f}원 ({loss_pct:.1f}%) -> 매수 중단")
                return False
        return True

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
        """보유 포지션 매도 판단

        핵심 수정: 하드 손절(-1.2%)은 MIN_HOLD_SECONDS와 무관하게 항상 체크.
        트레일링/RSI/BB/MACD 등 일반 매도는 MIN_HOLD_SECONDS 경과 후에만.
        """
        if not self.positions:
            return

        coins_to_sell = []
        # 스캔 결과 내 순위 (없으면 999 -> 모멘텀 소멸로 간주)
        volume_rank_map = {c['coin']: i+1 for i, c in enumerate(top_coins)}

        for coin, pos in self.positions.items():
            current_price = self.api.get_current_price(coin)
            if not current_price:
                continue

            # 최고가 갱신 (트레일링 스탑용)
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            rank = volume_rank_map.get(coin, 999)

            # === 1단계: 하드 손절/익절 + 트레일링 ===
            hold_secs_hard = (datetime.now() - datetime.strptime(pos.entry_time, "%Y-%m-%d %H:%M:%S")).total_seconds()
            hard_signal = self.strategy.check_hard_stop(coin, pos.buy_price, current_price)
            if hard_signal['sell']:
                if hold_secs_hard < HARD_STOP_MIN_HOLD_SECONDS:
                    logger.debug(f"[{coin}] 하드 손절 대기: 보유 {hold_secs_hard:.0f}s < {HARD_STOP_MIN_HOLD_SECONDS}s "
                                 f"(손익={pnl_pct:+.1f}%)")
                else:
                    logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                                f"손익={pnl_pct:+.1f}% | [즉시 매도] {hard_signal['reason']}")
                    coins_to_sell.append((coin, pos, current_price, hard_signal))
                    continue

            trail_signal = self.strategy.check_trailing_stop(coin, pos.buy_price, current_price, pos.highest_price)
            if trail_signal['sell']:
                logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                            f"손익={pnl_pct:+.1f}% | [즉시 매도] {trail_signal['reason']}")
                coins_to_sell.append((coin, pos, current_price, trail_signal))
                continue

            # === 2단계: 최소 보유시간 체크 (RSI/MACD/BB/모멘텀 매도에만 적용) ===
            hold_secs = (datetime.now() - datetime.strptime(pos.entry_time, "%Y-%m-%d %H:%M:%S")).total_seconds()
            if hold_secs < MIN_HOLD_SECONDS:
                logger.debug(f"[{coin}] 최소 보유시간 미충족: {hold_secs:.0f}s / {MIN_HOLD_SECONDS}s "
                             f"(손익={pnl_pct:+.1f}%)")
                continue

            # === 3단계: 일반 매도 신호 (트레일링/모멘텀/RSI/BB/MACD) ===
            # 5분봉은 매도에는 불필요하지만 RSI/BB/MACD 체크용으로 가져옴
            df = self.api.get_ohlcv(coin, interval="5m", count=200)

            signal = self.strategy.check_sell_signal(
                coin, pos.buy_price, current_price, rank,
                pos.highest_price, df
            )

            # 상태 로그
            drop_from_high = (pos.highest_price - current_price) / pos.highest_price * 100 if pos.highest_price > 0 else 0
            status_str = f"매도신호: {signal['reason']}" if signal['sell'] else f"보유중 | 고점대비 -{drop_from_high:.2f}%"
            logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                        f"손익={pnl_pct:+.1f}% | {status_str}")

            if signal['sell']:
                coins_to_sell.append((coin, pos, current_price, signal))

        for coin, pos, price, signal in coins_to_sell:
            self._execute_sell(coin, pos, price, signal['reason'], signal.get('is_stop_loss', False))

    def _execute_sell(self, coin: str, pos: Position, price: float, reason: str,
                      is_stop_loss: bool = False):
        """매도 실행

        Args:
            is_stop_loss: True면 손절 쿨다운(1시간) 적용, False면 익절 쿨다운(10분) 적용
        """
        logger.info(f"[매도 실행] {coin} | 사유: {reason}")
        if self.dry_run:
            logger.info(f"[DRY] 매도 생략: {coin} {pos.quantity}")
            del self.positions[coin]
            # 쿨다운 적용 (드라이런에서도)
            cooldown = COOLDOWN_AFTER_STOP_LOSS if is_stop_loss else COOLDOWN_AFTER_TAKE_PROFIT
            self.sell_cooldown[coin] = time.time() + cooldown
            return
        # 실제 잔고 조회 (추적 수량과 오차 방지)
        actual_qty = self.api.get_coin_balance(coin)
        if actual_qty <= 0:
            logger.warning(f"[{coin}] 실제 잔고 없음, 포지션 제거")
            del self.positions[coin]
            return
        result = self.api.sell_market(coin, actual_qty)
        if result:
            # 실제 체결 금액 조회 (시장가는 체결가가 추정가와 다를 수 있음)
            order_id = result.get('order_id') or result.get('uuid')
            actual_amount = None
            actual_exec_price = price
            if order_id:
                time.sleep(0.5)  # 체결 확정 대기
                order_detail = self.api.get_order(order_id)
                if order_detail:
                    executed_funds = float(order_detail.get('executed_funds', 0) or 0)
                    executed_vol = float(order_detail.get('executed_volume', 0) or 0)
                    if executed_funds > 0:
                        actual_amount = executed_funds
                        if executed_vol > 0:
                            actual_exec_price = executed_funds / executed_vol
                        logger.info(f"[{coin}] 실제 체결: {executed_funds:,.0f}원 (추정: {actual_qty * price:,.0f}원)")

            sell_amount = actual_amount if actual_amount else actual_qty * price
            pnl_krw = sell_amount - pos.total_amount
            pnl_pct = pnl_krw / pos.total_amount * 100
            trade_logger.log_trade(
                coin, "매도", actual_exec_price, actual_qty,
                sell_amount, pnl_pct, reason
            )
            self.daily_pnl_krw += pnl_krw
            del self.positions[coin]

            # 쿨다운 적용: 손절이면 1시간, 익절이면 10분
            cooldown = COOLDOWN_AFTER_STOP_LOSS if is_stop_loss else COOLDOWN_AFTER_TAKE_PROFIT
            self.sell_cooldown[coin] = time.time() + cooldown
            cooldown_label = "1시간" if is_stop_loss else "10분"

            # 손절 횟수 누적 및 당일 블랙리스트 체크
            if is_stop_loss:
                self.daily_coin_stops[coin] = self.daily_coin_stops.get(coin, 0) + 1
                stops_today = self.daily_coin_stops[coin]
                if stops_today >= DAILY_COIN_STOP_LIMIT:
                    logger.warning(f"[당일 블랙리스트] {coin} | 오늘 손절 {stops_today}회 → 오늘 재매수 금지")

            logger.info(f"[매도 완료] {coin} | 손익: {pnl_pct:+.1f}% ({pnl_krw:+,.0f}원) "
                        f"| 오늘 누적: {self.daily_pnl_krw:+,.0f}원 "
                        f"| 쿨다운: {cooldown_label}")

    # ===== 텔레그램 신호 처리 =====

    def _process_telegram_signals(self):
        """텔레그램 신호 큐 처리 - 기술적 분석 통과 시 매수"""
        while not self.telegram_queue.empty():
            try:
                signal = self.telegram_queue.get_nowait()
            except queue.Empty:
                break

            coin = signal['coin']
            alert_type = signal['type']
            logger.info(f"[텔레그램 신호 처리] {coin} | {alert_type}")

            # 쿨다운/포지션 체크
            if coin in self.positions:
                logger.info(f"[텔레그램] {coin} 이미 보유 중, 스킵")
                continue
            if time.time() <= self.sell_cooldown.get(coin, 0):
                remaining = self.sell_cooldown[coin] - time.time()
                logger.info(f"[텔레그램] {coin} 쿨다운 중 (잔여 {remaining:.0f}초), 스킵")
                continue

            # 최대 포지션 수 체크
            if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
                logger.info(f"[텔레그램] 최대 포지션 수 도달 ({MAX_CONCURRENT_POSITIONS}개), 스킵")
                continue

            # 현재가 및 기술적 분석 (모멘텀 스캔 무관하게 직접 분석)
            price = self.api.get_current_price(coin)
            if not price:
                logger.info(f"[텔레그램] {coin} 현재가 조회 실패 (빗썸 미상장 가능성)")
                continue

            # 최소 가격 필터
            if price < MIN_PRICE_KRW:
                logger.info(f"[텔레그램] {coin} 가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원, 스킵")
                continue

            df = self.api.get_ohlcv(coin, interval=BUY_CANDLE_INTERVAL, count=BUY_CANDLE_COUNT)
            if df is None:
                logger.info(f"[텔레그램] {coin} 캔들 데이터 없음")
                continue

            # 오더북만 체크 (텔레그램 신호 자체가 빗썸의 분석 결과)
            orderbook = self.api.get_orderbook(coin)
            trades = self.api.get_recent_trades(coin, count=100)
            pressure = self.strategy.check_buy_pressure(orderbook, trades)
            if not pressure['strong']:
                logger.info(f"[텔레그램] {coin} 오더북 미통과: {pressure['reason']}")
                continue

            logger.info(f"[텔레그램 매수] {coin} | {pressure['reason']} -> 매수 실행")
            self._execute_buy(coin, price, source="telegram")

    # ===== 신규 매수 탐색 =====

    def _scan_for_entry(self, top_coins: list):
        """신규 매수 후보 탐색 - 5분봉 사용, 최대 포지션 수 제한"""
        # 최대 포지션 수 체크
        if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
            logger.info(f"[매수 탐색] 최대 포지션 수 도달 ({len(self.positions)}/{MAX_CONCURRENT_POSITIONS}개)")
            return

        now = time.time()
        daily_blocked = [coin for coin, cnt in self.daily_coin_stops.items() if cnt >= DAILY_COIN_STOP_LIMIT]
        candidates = [
            c for c in top_coins
            if c['coin'] not in self.positions
            and now > self.sell_cooldown.get(c['coin'], 0)
            and c['coin'] not in daily_blocked
        ]
        cooldown_skipped = [c['coin'] for c in top_coins if c['coin'] not in self.positions and now <= self.sell_cooldown.get(c['coin'], 0)]
        if cooldown_skipped:
            logger.info(f"[쿨다운 중] {', '.join(cooldown_skipped)}")
        if daily_blocked:
            logger.info(f"[당일 블랙리스트] {', '.join(daily_blocked)}")

        buy_candidates = []
        for coin_data in candidates:
            coin = coin_data['coin']
            price = coin_data.get('price', 0)

            # 블랙리스트 필터 (스테이블 코인 등)
            if coin in COIN_BLACKLIST:
                continue

            # 최소 가격 필터 (API 호출 전에 사전 필터링)
            if price and price < MIN_PRICE_KRW:
                logger.info(f"[탈락] {coin} | 가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원")
                continue

            # 5분봉 200개 사용
            df = self.api.get_ohlcv(coin, interval=BUY_CANDLE_INTERVAL, count=BUY_CANDLE_COUNT)
            if df is None:
                continue

            signal = self.strategy.check_buy_signal(coin, df, coin_data['score'],
                                                     current_price=price)

            if signal['buy']:
                buy_candidates.append((coin_data, signal))
                logger.info(f"[매수 후보] {coin} | RSI={signal['rsi']:.1f} | {' | '.join(signal['reasons'])}")
            else:
                logger.info(f"[탈락] {coin} | {', '.join(signal['fail_reasons'])}")

        if not buy_candidates:
            logger.info("[매수 탐색 완료] 조건 통과 종목 없음")
            return

        # RSI 가장 낮은 것 선택 (추가 상승 여력 최대)
        buy_candidates.sort(key=lambda x: x[1]['rsi'])

        # 오더북/체결 매수세 필터 - 상위 후보부터 통과하는 첫 번째 선택
        final_coin_data, final_signal = None, None
        for coin_data, signal in buy_candidates:
            coin = coin_data['coin']
            orderbook = self.api.get_orderbook(coin)
            trades = self.api.get_recent_trades(coin, count=100)
            pressure = self.strategy.check_buy_pressure(orderbook, trades)
            if pressure['strong']:
                logger.info(f"[오더북 통과] {coin} | {pressure['reason']}")
                final_coin_data, final_signal = coin_data, signal
                break
            else:
                logger.info(f"[오더북 탈락] {coin} | {pressure['reason']}")
                trade_logger.log_reject(coin, pressure['reason'], coin_data['price'])

        if final_coin_data is None:
            logger.info("[매수 보류] 매수세 강한 후보 없음")
            return

        logger.info(f"[최종 선택] {final_coin_data['coin']} | RSI={final_signal['rsi']:.1f}")
        self._execute_buy(final_coin_data['coin'], final_coin_data['price'], source="momentum")

    def _execute_buy(self, coin: str, price: float, source: str = "momentum"):
        """매수 실행 - 거래시간/최대포지션/최소가격 체크 포함"""

        # 거래 시간 체크
        if not self._is_trading_hours():
            now_kst = datetime.now(KST)
            logger.info(f"[매수 차단] {coin} | 거래시간 외 ({now_kst.strftime('%H:%M')} KST)")
            return

        # 최소 가격 체크
        if price < MIN_PRICE_KRW:
            logger.info(f"[매수 차단] {coin} | 가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원")
            return

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
            # 최대 포지션 수 체크 (신규 매수만)
            if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
                logger.info(f"[매수 차단] {coin} | 최대 포지션 수 도달 ({MAX_CONCURRENT_POSITIONS}개)")
                return

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

        # 시장가 매수
        result = self.api.buy_market(coin, krw)
        if result:
            quantity = krw / price
            if coin in self.positions:
                pos = self.positions[coin]
                pos.quantity += quantity
                pos.total_amount += krw
                pos.buy_count += 1
                pos.buy_price = pos.total_amount / pos.quantity
            else:
                self.positions[coin] = Position(
                    coin=coin,
                    buy_price=price,
                    quantity=quantity,
                    total_amount=krw
                )
            trade_logger.log_trade(coin, "매수", price, quantity, krw, reason="매수신호", source=source)
            logger.info(f"[매수 완료] {coin} | 가격={price:,.0f} 금액={krw:,.0f}원 [{source}]")

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
        lines.append(f"포지션 수: {len(self.positions)}/{MAX_CONCURRENT_POSITIONS}")
        now_kst = datetime.now(KST)
        trading = "O" if self._is_trading_hours() else "X"
        lines.append(f"거래시간: {now_kst.strftime('%H:%M')} KST ({trading})")
        lines.append(f"오늘 누적 손익: {self.daily_pnl_krw:+,.0f}원")
        lines.append(f"{'='*40}")
        return "\n".join(lines)
