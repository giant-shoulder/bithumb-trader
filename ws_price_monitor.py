"""
WebSocket 기반 실시간 가격 모니터

두 가지 기능:
1. 보유 포지션 하드손절/트레일링 실시간 감지 (REST 폴링 5초 → WebSocket 수십ms)
2. 관심 코인 급등 실시간 감지 → 즉시 매수 분석 트리거 (30초 스캔 → ~1초 감지)
"""
import json
import threading
import time
import uuid
from collections import deque
from logger import get_logger

logger = get_logger()


class WSPriceMonitor:
    """빗썸 WebSocket 실시간 가격 모니터"""

    WS_URL = "wss://api.bithumb.com/websocket/v1"

    # 급등 감지 파라미터
    SURGE_WINDOW_SECS = 60    # 60초 윈도우 내
    SURGE_PCT = 1.0           # 1.0% 이상 상승 시 급등으로 판단
    SURGE_COOLDOWN_SECS = 300 # 같은 코인 재알림 최소 5분 간격

    def __init__(self, on_stop_signal, on_surge_detected=None):
        """
        Args:
            on_stop_signal:     (coin, price) -> None
                                포지션 코인 가격 업데이트 콜백 (하드손절/트레일링 판단)
            on_surge_detected:  (coin, price, change_pct) -> None  (선택)
                                관심 코인 급등 감지 콜백 (매수 분석 트리거)
        """
        self._on_stop_signal = on_stop_signal
        self._on_surge_detected = on_surge_detected

        self._position_coins: set = set()   # 손절 모니터링 대상 (보유 코인)
        self._watch_coins: set = set()      # 급등 감시 대상 (상위 N개)
        self._lock = threading.Lock()

        # 급등 감지: 코인별 가격 이력 (timestamp, price)
        self._price_history: dict[str, deque] = {}
        self._surge_cooldown: dict[str, float] = {}  # coin -> last_surge_time

        self._ws = None
        self._thread = None
        self._running = False
        self._connected = False

    # ===== 외부 인터페이스 =====

    def start(self):
        """백그라운드 WebSocket 스레드 시작"""
        self._running = True
        self._thread = threading.Thread(
            target=self._run_forever, daemon=True, name="ws-price-monitor"
        )
        self._thread.start()
        logger.info("[WS] 실시간 가격 모니터 시작 (손절 감지 + 급등 감지)")

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def update_position_coins(self, coins: set):
        """보유 포지션 코인 갱신 (매수/매도 시 호출)"""
        with self._lock:
            if coins == self._position_coins:
                return
            self._position_coins = set(coins)
        self._resubscribe()
        logger.info(f"[WS] 포지션 구독: {coins if coins else '없음'}")

    def update_watch_coins(self, coins: set):
        """급등 감시 대상 코인 갱신 (스캔 결과 top N)"""
        with self._lock:
            if coins == self._watch_coins:
                return
            self._watch_coins = set(coins)
        self._resubscribe()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ===== 내부 구현 =====

    def _all_coins(self) -> set:
        with self._lock:
            return self._position_coins | self._watch_coins

    def _build_subscribe_msg(self) -> str | None:
        coins = self._all_coins()
        if not coins:
            return None
        codes = [f"KRW-{c}" for c in coins]
        return json.dumps([
            {"ticket": str(uuid.uuid4())},
            {"type": "ticker", "codes": codes, "isOnlyRealtime": True},
            {"format": "DEFAULT"},
        ])

    def _resubscribe(self):
        if self._ws and self._connected:
            msg = self._build_subscribe_msg()
            if msg:
                try:
                    self._ws.send(msg)
                except Exception as e:
                    logger.debug(f"[WS] 재구독 실패: {e}")

    def _run_forever(self):
        import websocket
        delay = 3
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self.WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=lambda ws, e: logger.warning(f"[WS] 오류: {e}"),
                    on_close=lambda ws, c, m: logger.info("[WS] 연결 끊김"),
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
                delay = 3
            except Exception as e:
                logger.error(f"[WS] 예외: {e}")
            finally:
                self._connected = False

            if self._running:
                logger.info(f"[WS] {delay}초 후 재연결...")
                time.sleep(delay)
                delay = min(delay * 2, 60)

    def _on_open(self, ws):
        self._connected = True
        logger.info("[WS] 연결 성공")
        msg = self._build_subscribe_msg()
        if msg:
            ws.send(msg)

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            code = data.get("code", "")
            price = float(data.get("trade_price", 0))
            if not (code.startswith("KRW-") and price > 0):
                return
            coin = code[4:]

            with self._lock:
                is_position = coin in self._position_coins
                is_watch = coin in self._watch_coins

            # 1. 보유 포지션: 손절/트레일링 콜백
            if is_position:
                self._on_stop_signal(coin, price)

            # 2. 관심 코인: 급등 감지 (포지션과 중복돼도 감지)
            if is_watch and self._on_surge_detected:
                self._check_surge(coin, price)

        except Exception as e:
            logger.debug(f"[WS] 메시지 파싱 오류: {e}")

    def _check_surge(self, coin: str, price: float):
        """60초 내 1% 이상 상승 시 급등 콜백 호출"""
        now = time.time()

        # 쿨다운 체크
        if now - self._surge_cooldown.get(coin, 0) < self.SURGE_COOLDOWN_SECS:
            return

        # 가격 이력 갱신
        if coin not in self._price_history:
            self._price_history[coin] = deque()
        history = self._price_history[coin]
        history.append((now, price))

        # 윈도우 밖 오래된 데이터 제거
        cutoff = now - self.SURGE_WINDOW_SECS - 5
        while history and history[0][0] < cutoff:
            history.popleft()

        # 윈도우 시작 가격 찾기 (60초 전에 가장 가까운 값)
        old_entries = [(t, p) for t, p in history if now - t >= self.SURGE_WINDOW_SECS]
        if not old_entries:
            return
        old_price = old_entries[-1][1]

        change_pct = (price - old_price) / old_price * 100
        if change_pct >= self.SURGE_PCT:
            self._surge_cooldown[coin] = now
            logger.info(f"[WS 급등 감지] {coin} | 60초 내 +{change_pct:.1f}% → 즉시 분석")
            self._on_surge_detected(coin, price, change_pct)
