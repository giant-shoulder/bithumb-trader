"""
WebSocket 기반 실시간 가격 모니터

보유 포지션의 가격을 빗썸 WebSocket으로 실시간 수신.
REST 폴링(5초 지연) 대신 수십ms 단위 가격 감지 → 하드손절 슬리피지 최소화.
"""
import json
import threading
import time
import uuid
from logger import get_logger

logger = get_logger()


class WSPriceMonitor:
    """빗썸 WebSocket 실시간 가격 모니터"""

    WS_URL = "wss://api.bithumb.com/websocket/v1"

    def __init__(self, on_price_update):
        """
        Args:
            on_price_update: (coin: str, price: float) -> None
                             가격 업데이트마다 호출되는 콜백.
                             하드손절/트레일링 판단은 호출자(AutoTrader)가 담당.
        """
        self._on_price_update = on_price_update
        self._coins: set = set()
        self._coins_lock = threading.Lock()
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
        logger.info("[WS] 실시간 가격 모니터 시작")

    def stop(self):
        """WebSocket 모니터 종료"""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def update_coins(self, coins: set):
        """
        구독 코인 목록 갱신 (포지션 변경 시마다 호출).
        빈 set이면 구독 해제.
        """
        with self._coins_lock:
            if coins == self._coins:
                return
            self._coins = set(coins)

        if coins:
            logger.info(f"[WS] 구독 갱신 → {coins}")
        else:
            logger.info("[WS] 구독 해제 (포지션 없음)")

        if self._connected:
            self._resubscribe()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ===== 내부 구현 =====

    def _get_codes(self) -> list:
        with self._coins_lock:
            return [f"KRW-{c}" for c in self._coins]

    def _build_subscribe_msg(self) -> str | None:
        codes = self._get_codes()
        if not codes:
            return None
        return json.dumps([
            {"ticket": str(uuid.uuid4())},
            {"type": "ticker", "codes": codes, "isOnlyRealtime": True},
            {"format": "DEFAULT"},
        ])

    def _resubscribe(self):
        msg = self._build_subscribe_msg()
        if msg and self._ws:
            try:
                self._ws.send(msg)
            except Exception as e:
                logger.debug(f"[WS] 재구독 전송 실패: {e}")

    def _run_forever(self):
        import websocket
        delay = 3
        while self._running:
            try:
                self._ws = websocket.WebSocketApp(
                    self.WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
                delay = 3  # 정상 종료 시 재연결 딜레이 초기화
            except Exception as e:
                logger.error(f"[WS] 예외: {e}")
            finally:
                self._connected = False

            if self._running:
                logger.info(f"[WS] {delay}초 후 재연결 시도...")
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
            code = data.get("code", "")       # "KRW-BTC"
            price = float(data.get("trade_price", 0))
            if code.startswith("KRW-") and price > 0:
                self._on_price_update(code[4:], price)
        except Exception as e:
            logger.debug(f"[WS] 메시지 파싱 오류: {e}")

    def _on_error(self, ws, error):
        logger.warning(f"[WS] 오류: {error}")

    def _on_close(self, ws, close_code, close_msg):
        self._connected = False
        logger.info(f"[WS] 연결 끊김 (code={close_code})")
