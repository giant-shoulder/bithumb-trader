"""
자동매매 실행 엔진
AlphaTrend 리듬 단타 전략 (제이슨 노아 방법론)
3단계: 확인(AT green) → 반응(눌림목 대기) → 진입(반등 양봉)
"""
import time
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from bithumb_api import BithumbAPI
from strategy import AlphaTrendStrategy
from logger import get_logger, TradeLogger
from ws_price_monitor import WSPriceMonitor
import notifier
from config import (
    MAX_POSITION_KRW, BUY_UNIT_KRW,
    POLLING_INTERVAL_IDLE, POLLING_INTERVAL_ACTIVE,
    MOMENTUM_TOP_N, MIN_VOLUME_24H_KRW,
    COOLDOWN_AFTER_STOP_LOSS, COOLDOWN_AFTER_TAKE_PROFIT,
    DAILY_LOSS_LIMIT_PCT,
    BUY_LIMIT_OFFSET_PCT,
    MIN_BUY_KRW,
    MIN_POSITION_KRW,
    PRIORITY_COINS,
    MAX_CONCURRENT_POSITIONS,
    MIN_PRICE_KRW,
    TRADING_BLOCK_START, TRADING_BLOCK_END,
    BUY_CANDLE_INTERVAL, BUY_CANDLE_COUNT,
    COIN_BLACKLIST,
    DAILY_COIN_STOP_LIMIT,
    PULLBACK_MAX_CANDLES,
    AT_NOISE_EXIT,
)

KST = timezone(timedelta(hours=9))

logger = get_logger()
trade_logger = TradeLogger()

# 5분봉 캔들 길이(초) - 눌림목 대기 타임아웃 계산용
_CANDLE_SECS = 5 * 60


@dataclass
class Position:
    """보유 포지션"""
    coin: str
    buy_price: float
    quantity: float
    stop_loss_price: float = 0.0    # AT 기반 절대 손절가
    take_profit_price: float = 0.0  # R:R 기반 절대 익절가
    total_amount: float = 0.0       # 총 투자금액
    entry_time: str = ""

    def __post_init__(self):
        self.entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.total_amount:
            self.total_amount = self.buy_price * self.quantity


class AutoTrader:
    def __init__(self, dry_run: bool = False):
        self.api = BithumbAPI()
        self.strategy = AlphaTrendStrategy()
        self.positions: dict[str, Position] = {}
        self.sell_cooldown: dict[str, float] = {}   # coin -> cooldown_end_timestamp
        self.daily_coin_stops: dict[str, int] = {}  # coin -> 당일 손절 횟수
        self.is_running = False
        self.dry_run = dry_run
        self.daily_pnl_krw = 0.0
        self.daily_reset_date = datetime.now().date()
        self.telegram_queue: queue.Queue = queue.Queue()

        self.pending_signals: dict = {}  # 미사용 (즉시 진입 방식)

        # WebSocket 실시간 가격 모니터
        self._ws_sell_queue: queue.Queue = queue.Queue()   # 손절/익절 즉시 매도 큐
        self._hot_buy_queue: queue.Queue = queue.Queue()   # 급등 감지 즉시 분석 큐
        self._ws_monitor = WSPriceMonitor(
            on_stop_signal=self._on_ws_price,
            on_surge_detected=self._on_ws_surge,
        )
        self._ws_monitor.start()
        logger.info("=" * 50)
        logger.info("빗섬 자동매매 시스템 시작 (AlphaTrend 리듬 단타)")
        logger.info(f"설정: 손절 0.5~2.5% | 익절 R:R 1:1.5 | AT 노이즈 청산 {AT_NOISE_EXIT}")
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
                position_value = balance * avg_price
                if position_value < MIN_POSITION_KRW:
                    logger.info(f"[더스트 스킵] {coin}: {position_value:.0f}원 (최소 {MIN_POSITION_KRW:,}원 미만)")
                    continue
                # 기존 포지션은 stop/take 미설정 (0.0) → WebSocket 자동매도 없이 수동 관리
                self.positions[coin] = Position(
                    coin=coin,
                    buy_price=avg_price,
                    quantity=balance,
                    total_amount=avg_price * balance,
                )
                logger.info(f"[기존 포지션 로드] {coin}: {balance:.6f}개 @ {avg_price:,.0f}원 "
                            f"(stop/take 미설정 → 폴링 관리)")
        except Exception as e:
            logger.error(f"기존 포지션 로드 실패: {e}")

    # ===== 거래 시간 체크 =====

    def _is_trading_hours(self) -> bool:
        """KST 기준 거래 허용 시간인지 확인 (매수 전용, 매도는 항상 가능)"""
        if TRADING_BLOCK_START is None or TRADING_BLOCK_END is None:
            return True
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
                    time.sleep(POLLING_INTERVAL_IDLE)
                    continue

                # 1. 거래대금 상위 코인 조회
                top_coins = self._get_top_coins()
                if not top_coins:
                    logger.warning("거래대금 데이터 조회 실패")
                    time.sleep(POLLING_INTERVAL_IDLE)
                    continue

                self._log_market_overview(top_coins)

                # 상위 코인 목록을 WebSocket 급등 감시 대상으로 등록
                self._ws_monitor.update_watch_coins(
                    {c['coin'] for c in top_coins if c['coin'] not in COIN_BLACKLIST}
                )

                # 2. 보유 포지션 관리 (AT 노이즈 청산 / 모멘텀 소멸)
                self._manage_positions(top_coins)

                # 3. 텔레그램 신호 처리 (거래 시간 내에만)
                if self._is_trading_hours():
                    self._process_telegram_signals()

                # 4. 신규 AT 신호 탐색 (거래 시간 내에만)
                if self._is_trading_hours():
                    self._scan_for_entry(top_coins)
                else:
                    logger.info(f"[거래시간 외] 현재 {now_kst.strftime('%H:%M')} KST - 매수 탐색 스킵")

                # 5. 대기 (포지션 있으면 짧게, 없으면 길게)
                interval = POLLING_INTERVAL_ACTIVE if self.positions else POLLING_INTERVAL_IDLE
                label = '포지션 있음' if self.positions else '대기 중'
                logger.info(f"다음 실행: {interval}초 후 ({label})")
                for _ in range(interval):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    self._process_ws_sells()   # WebSocket 손절/익절 즉시 처리
                    self._process_hot_buys()   # WebSocket 급등 감지 즉시 분석

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
        self._ws_monitor.stop()
        logger.info("시스템 종료 중...")
        if self.positions:
            logger.warning(f"미청산 포지션 {len(self.positions)}개:")
            for coin, pos in self.positions.items():
                price = self.api.get_current_price(coin)
                if price:
                    pnl = (price - pos.buy_price) / pos.buy_price * 100
                    logger.warning(f"  {coin}: 매입가={pos.buy_price:,.0f} 현재={price:,.0f} ({pnl:+.1f}%)")

    # ===== WebSocket 실시간 가격 모니터 =====

    def _on_ws_price(self, coin: str, price: float):
        """WebSocket 실시간 가격 콜백 - 절대 손절/익절 즉시 감지"""
        pos = self.positions.get(coin)
        if not pos:
            return

        # stop/take 미설정 포지션 (기존 포지션)은 스킵
        if pos.stop_loss_price <= 0 and pos.take_profit_price <= 0:
            return

        result = self.strategy.check_at_stop_take(
            coin, price, pos.stop_loss_price, pos.take_profit_price
        )
        if result['sell']:
            removed = self.positions.pop(coin, None)
            if removed:
                logger.info(f"[WS 즉시 매도] {coin} | {result['reason']}")
                self._ws_sell_queue.put((coin, removed, price, result['reason'], result['is_stop_loss']))

    def _process_ws_sells(self):
        """WebSocket 트리거 매도 큐 처리 (1초마다 메인 루프에서 호출)"""
        while not self._ws_sell_queue.empty():
            try:
                coin, pos, price, reason, is_stop_loss = self._ws_sell_queue.get_nowait()
                self._execute_sell(coin, pos, price, reason, is_stop_loss)
            except queue.Empty:
                break

    def _update_ws_subscriptions(self):
        """현재 포지션 기반으로 WebSocket 손절/익절 구독 갱신"""
        self._ws_monitor.update_position_coins(set(self.positions.keys()))

    def _on_ws_surge(self, coin: str, price: float, change_pct: float):
        """WebSocket 급등 감지 콜백 → AT 신호 분석 큐 삽입"""
        if coin in self.positions:
            return
        if coin in COIN_BLACKLIST:
            return
        if self.daily_coin_stops.get(coin, 0) >= DAILY_COIN_STOP_LIMIT:
            return
        if time.time() <= self.sell_cooldown.get(coin, 0):
            return
        if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
            return
        if not self._is_trading_hours():
            return
        self._hot_buy_queue.put((coin, price, change_pct))

    def _process_hot_buys(self):
        """WebSocket 급등 감지 큐 처리 - AT 신호 확인 후 즉시 매수"""
        while not self._hot_buy_queue.empty():
            try:
                coin, ws_price, change_pct = self._hot_buy_queue.get_nowait()
            except queue.Empty:
                break

            if coin in self.positions:
                continue
            if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
                break
            if time.time() <= self.sell_cooldown.get(coin, 0):
                continue
            if self.daily_coin_stops.get(coin, 0) >= DAILY_COIN_STOP_LIMIT:
                continue
            if coin in COIN_BLACKLIST:
                continue

            logger.info(f"[WS 급등 AT 확인] {coin} | +{change_pct:.1f}%")

            price = self.api.get_current_price(coin)
            if not price or price < MIN_PRICE_KRW:
                continue

            df = self.api.get_ohlcv(coin, interval=BUY_CANDLE_INTERVAL, count=BUY_CANDLE_COUNT)
            if df is None:
                continue

            signal = self.strategy.check_rhythm_entry(coin, df, current_price=price)
            if signal['signal']:
                logger.info(f"[WS 급등 리듬 매수] {coin} | {signal['reason']}")
                self._execute_buy(coin, price, signal['stop_loss_price'],
                                  signal['take_profit_price'], source="ws_surge")
            else:
                logger.info(f"[WS 급등 탈락] {coin} | {signal['reason']}")

    # ===== 일일 손실 한도 =====

    def _check_daily_loss_limit(self) -> bool:
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
        return self.api.scan_momentum_coins(
            min_volume_24h=MIN_VOLUME_24H_KRW,
            top_n=MOMENTUM_TOP_N
        )

    def _log_market_overview(self, top_coins: list):
        logger.info("모멘텀 상위 코인:")
        for i, c in enumerate(top_coins[:5], 1):
            logger.info(f"  {i}위 {c['coin']}: {c['volume_krw']/1e8:.1f}억 | {c['change_pct']:+.1f}% | 스코어={c['score']:.2e}")

    # ===== 포지션 관리 (AT 노이즈 청산 / 모멘텀 소멸) =====

    def _manage_positions(self, top_coins: list):
        """보유 포지션 매도 판단

        WebSocket이 stop/take를 실시간 처리하므로
        여기서는 AT yellow 노이즈 청산과 모멘텀 소멸만 처리.
        """
        if not self.positions:
            return

        volume_rank_map = {c['coin']: i + 1 for i, c in enumerate(top_coins)}
        coins_to_sell = []

        for coin, pos in list(self.positions.items()):
            current_price = self.api.get_current_price(coin)
            if not current_price:
                continue

            pnl_pct = (current_price - pos.buy_price) / pos.buy_price * 100
            rank = volume_rank_map.get(coin, 999)

            # 1. 모멘텀 소멸 체크
            momentum = self.strategy.check_momentum_exit(coin, rank)
            if momentum['sell']:
                logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                            f"손익={pnl_pct:+.1f}% | {momentum['reason']}")
                coins_to_sell.append((coin, pos, current_price, momentum))
                continue

            # 2. AT 노이즈 청산 (yellow 전환)
            if AT_NOISE_EXIT:
                df = self.api.get_ohlcv(coin, interval="5m", count=BUY_CANDLE_COUNT)
                if df is not None and self.strategy.check_at_noise_exit(coin, df):
                    signal = {
                        'sell': True,
                        'reason': 'AT yellow 노이즈 청산',
                        'is_stop_loss': False,
                    }
                    logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                                f"손익={pnl_pct:+.1f}% | {signal['reason']}")
                    coins_to_sell.append((coin, pos, current_price, signal))
                    continue

            # 상태 로그 (stop/take는 WS가 처리 중)
            stop_str = f"{pos.stop_loss_price:,.0f}" if pos.stop_loss_price > 0 else "미설정"
            take_str = f"{pos.take_profit_price:,.0f}" if pos.take_profit_price > 0 else "미설정"
            logger.info(f"[{coin}] 매입={pos.buy_price:,.0f} 현재={current_price:,.0f} "
                        f"손익={pnl_pct:+.1f}% | 손절={stop_str} 익절={take_str}")

        for coin, pos, price, signal in coins_to_sell:
            self._execute_sell(coin, pos, price, signal['reason'], signal.get('is_stop_loss', False))

    # ===== 매도 실행 =====

    def _execute_sell(self, coin: str, pos: Position, price: float, reason: str,
                      is_stop_loss: bool = False):
        logger.info(f"[매도 실행] {coin} | 사유: {reason}")
        if self.dry_run:
            logger.info(f"[DRY] 매도 생략: {coin} {pos.quantity}")
            self.positions.pop(coin, None)
            cooldown = COOLDOWN_AFTER_STOP_LOSS if is_stop_loss else COOLDOWN_AFTER_TAKE_PROFIT
            self.sell_cooldown[coin] = time.time() + cooldown
            self._update_ws_subscriptions()
            return

        actual_qty = self.api.get_coin_balance(coin)
        if actual_qty <= 0:
            logger.warning(f"[{coin}] 실제 잔고 없음, 포지션 제거")
            self.positions.pop(coin, None)
            self._update_ws_subscriptions()
            return

        result = self.api.sell_market(coin, actual_qty)
        if result:
            order_id = result.get('order_id') or result.get('uuid')
            actual_amount = None
            actual_exec_price = price
            if order_id:
                time.sleep(0.5)
                order_detail = self.api.get_order(order_id)
                if order_detail:
                    executed_funds = float(order_detail.get('executed_funds', 0) or 0)
                    executed_vol = float(order_detail.get('executed_volume', 0) or 0)
                    if executed_funds > 0:
                        actual_amount = executed_funds
                        if executed_vol > 0:
                            actual_exec_price = executed_funds / executed_vol
                        logger.info(f"[{coin}] 실제 체결: {executed_funds:,.0f}원")

            sell_amount = actual_amount if actual_amount else actual_qty * price
            pnl_krw = sell_amount - pos.total_amount
            pnl_pct = pnl_krw / pos.total_amount * 100
            trade_logger.log_trade(coin, "매도", actual_exec_price, actual_qty,
                                   sell_amount, pnl_pct, reason)
            self.daily_pnl_krw += pnl_krw
            self.positions.pop(coin, None)
            self._update_ws_subscriptions()

            cooldown = COOLDOWN_AFTER_STOP_LOSS if is_stop_loss else COOLDOWN_AFTER_TAKE_PROFIT
            self.sell_cooldown[coin] = time.time() + cooldown
            cooldown_label = "1시간" if is_stop_loss else "4시간"

            if is_stop_loss:
                self.daily_coin_stops[coin] = self.daily_coin_stops.get(coin, 0) + 1
                stops_today = self.daily_coin_stops[coin]
                if stops_today >= DAILY_COIN_STOP_LIMIT:
                    logger.warning(f"[당일 블랙리스트] {coin} | 오늘 손절 {stops_today}회 → 오늘 재매수 금지")

            logger.info(f"[매도 완료] {coin} | 손익: {pnl_pct:+.1f}% ({pnl_krw:+,.0f}원) "
                        f"| 오늘 누적: {self.daily_pnl_krw:+,.0f}원 | 쿨다운: {cooldown_label}")
            notifier.notify_sell(coin, actual_exec_price, int(sell_amount), pnl_pct, pnl_krw, reason)

    # ===== 텔레그램 신호 처리 =====

    def _process_telegram_signals(self):
        """텔레그램 신호 큐 처리 - AT 분석 통과 시 pending 등록"""
        while not self.telegram_queue.empty():
            try:
                signal = self.telegram_queue.get_nowait()
            except queue.Empty:
                break

            coin = signal['coin']
            alert_type = signal['type']
            logger.info(f"[텔레그램 신호] {coin} | {alert_type}")

            if coin in COIN_BLACKLIST:
                continue
            if self.daily_coin_stops.get(coin, 0) >= DAILY_COIN_STOP_LIMIT:
                continue
            if coin in self.positions:
                continue
            if time.time() <= self.sell_cooldown.get(coin, 0):
                continue
            if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
                continue

            price = self.api.get_current_price(coin)
            if not price or price < MIN_PRICE_KRW:
                continue

            df = self.api.get_ohlcv(coin, interval=BUY_CANDLE_INTERVAL, count=BUY_CANDLE_COUNT)
            if df is None:
                continue

            signal = self.strategy.check_rhythm_entry(coin, df, current_price=price)
            if signal['signal']:
                logger.info(f"[텔레그램 리듬 매수] {coin} | {signal['reason']}")
                self._execute_buy(coin, price, signal['stop_loss_price'],
                                  signal['take_profit_price'], source="telegram")
            else:
                logger.info(f"[텔레그램 탈락] {coin} | {signal['reason']}")

    # ===== 신규 AT 신호 탐색 =====

    def _scan_for_entry(self, top_coins: list):
        """신규 매수 후보 탐색 - AT green 전환 감지 즉시 매수"""
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
            and c['coin'] not in COIN_BLACKLIST
        ]

        cooldown_skipped = [
            c['coin'] for c in top_coins
            if c['coin'] not in self.positions and now <= self.sell_cooldown.get(c['coin'], 0)
        ]
        if cooldown_skipped:
            logger.info(f"[쿨다운 중] {', '.join(cooldown_skipped)}")
        if daily_blocked:
            logger.info(f"[당일 블랙리스트] {', '.join(daily_blocked)}")

        buy_candidates = []
        for coin_data in candidates:
            coin = coin_data['coin']
            price = coin_data.get('price', 0)

            if price and price < MIN_PRICE_KRW:
                logger.debug(f"[탈락] {coin} | 가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원")
                continue

            df = self.api.get_ohlcv(coin, interval=BUY_CANDLE_INTERVAL, count=BUY_CANDLE_COUNT)
            if df is None:
                continue

            signal = self.strategy.check_rhythm_entry(coin, df, current_price=price)
            if signal['signal']:
                buy_candidates.append((coin, signal, coin_data))
                logger.info(f"[리듬 신호] {coin} | {signal['reason']}")
            else:
                logger.info(f"[탈락] {coin} | {signal['reason']}")

        if not buy_candidates:
            logger.info("[매수 탐색 완료] 리듬 진입 신호 없음")
            return

        # 우선 종목을 앞으로, 그 외는 순서 유지
        buy_candidates.sort(key=lambda x: 0 if x[0] in PRIORITY_COINS else 1)

        # 신호 통과한 종목 즉시 매수
        for coin, signal, coin_data in buy_candidates:
            if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
                break
            if coin in self.positions:
                continue
            self._execute_buy(coin, coin_data['price'], signal['stop_loss_price'],
                              signal['take_profit_price'], source="rhythm")

    # ===== 매수 실행 =====

    def _execute_buy(self, coin: str, price: float,
                     stop_loss_price: float, take_profit_price: float,
                     source: str = "at_pullback"):
        """매수 실행"""
        if not self._is_trading_hours():
            now_kst = datetime.now(KST)
            logger.info(f"[매수 차단] {coin} | 거래시간 외 ({now_kst.strftime('%H:%M')} KST)")
            return

        if price < MIN_PRICE_KRW:
            logger.info(f"[매수 차단] {coin} | 가격 {price:.0f}원 < 최소 {MIN_PRICE_KRW}원")
            return

        if coin in self.positions:
            logger.info(f"[매수 차단] {coin} | 이미 보유 중")
            return

        if len(self.positions) >= MAX_CONCURRENT_POSITIONS:
            logger.info(f"[매수 차단] {coin} | 최대 포지션 수 도달 ({MAX_CONCURRENT_POSITIONS}개)")
            return

        krw_balance = self.api.get_krw_balance()
        if krw_balance < MIN_BUY_KRW:
            logger.warning(f"[매수 차단] {coin} | 잔고 부족 ({krw_balance:,.0f}원 < 최소 {MIN_BUY_KRW:,}원)")
            return

        krw = min(BUY_UNIT_KRW, int(krw_balance * 0.995))
        logger.info(f"[매수 실행] {coin} | {krw:,.0f}원 | 손절={stop_loss_price:,.0f} 익절={take_profit_price:,.0f}")

        if self.dry_run:
            logger.info(f"[DRY] 매수 생략: {coin} {krw:,.0f}원")
            return

        result = self.api.buy_market(coin, krw)
        if result:
            quantity = krw / price
            self.positions[coin] = Position(
                coin=coin,
                buy_price=price,
                quantity=quantity,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                total_amount=krw,
            )
            trade_logger.log_trade(coin, "매수", price, quantity, krw, reason="AT 눌림목 반등", source=source)
            logger.info(f"[매수 완료] {coin} | 가격={price:,.0f} 금액={krw:,.0f}원 [{source}]")
            notifier.notify_buy(coin, price, krw, 1, 1, source)
            self._update_ws_subscriptions()

    # ===== 상태 조회 =====

    def get_status(self) -> str:
        lines = [f"\n{'='*40}", "현재 포지션"]
        if not self.positions:
            lines.append("  없음")
        else:
            for coin, pos in self.positions.items():
                price = self.api.get_current_price(coin) or pos.buy_price
                pnl = (price - pos.buy_price) / pos.buy_price * 100
                stop_str = f"{pos.stop_loss_price:,.0f}" if pos.stop_loss_price > 0 else "미설정"
                take_str = f"{pos.take_profit_price:,.0f}" if pos.take_profit_price > 0 else "미설정"
                lines.append(
                    f"  {coin}: 매수={pos.buy_price:,.0f} 현재={price:,.0f} "
                    f"손익={pnl:+.1f}% | 손절={stop_str} 익절={take_str}"
                )
        lines.append(f"포지션 수: {len(self.positions)}/{MAX_CONCURRENT_POSITIONS}")
        now_kst = datetime.now(KST)
        trading = "O" if self._is_trading_hours() else "X"
        lines.append(f"거래시간: {now_kst.strftime('%H:%M')} KST ({trading})")
        lines.append(f"오늘 누적 손익: {self.daily_pnl_krw:+,.0f}원")
        lines.append(f"{'='*40}")
        return "\n".join(lines)
