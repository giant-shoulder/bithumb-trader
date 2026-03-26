"""
빗썸 공식 텔레그램 채널 실시간 모니터링
[속보] 알림을 캐치하여 매수 신호 큐에 전달
"""
import re
import asyncio
import threading
import queue
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from logger import get_logger

logger = get_logger()

# 빗썸 공식 실시간 알림 채널
BITHUMB_CHANNEL = 'BithumbExchangeData'

# 캐치할 알림 패턴 및 우선순위
ALERT_PATTERNS = [
    # [속보] 코인이름(TICKER) 매수세 급증 (가장 강한 신호)
    (re.compile(r'\[속보\].+?\(([A-Z]+)\).*(매수세 급증|체결강도)'), 'buy_pressure', 3),
    # [속보] 코인이름(TICKER) 상승 감지 (1분간 급등)
    (re.compile(r'\[속보\].+?\(([A-Z]+)\)\s*상승 감지'), 'surge', 2),
]

# 무시할 알림 (관련성 낮음)
IGNORE_KEYWORDS = ['김치 프리미엄', '김프', '공지', '점검', '상장', '이벤트', '하락 감지', '하락 돌파']


def parse_alert(text: str) -> dict | None:
    """텔레그램 메시지에서 코인 신호 추출"""
    for keyword in IGNORE_KEYWORDS:
        if keyword in text:
            return None

    for pattern, alert_type, priority in ALERT_PATTERNS:
        match = pattern.search(text)
        if match:
            ticker = match.group(1)
            return {
                'coin': ticker,
                'type': alert_type,
                'priority': priority,
                'message': text[:100],
            }
    return None


class TelegramMonitor:
    def __init__(self, signal_queue: queue.Queue):
        self.signal_queue = signal_queue
        self.api_id = int(os.environ.get('TELEGRAM_API_ID', 0))
        self.api_hash = os.environ.get('TELEGRAM_API_HASH', '')
        self.session = os.environ.get('TELEGRAM_SESSION', '')
        self._thread = None
        self._loop = None

    def start(self):
        """백그라운드 스레드에서 모니터링 시작"""
        if not self.api_id or not self.api_hash:
            logger.warning("텔레그램 API 키 미설정 (TELEGRAM_API_ID, TELEGRAM_API_HASH)")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("텔레그램 모니터 시작")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._monitor())

    async def _monitor(self):
        session = StringSession(self.session) if self.session else StringSession()
        async with TelegramClient(session, self.api_id, self.api_hash) as client:
            # 세션 문자열 저장 (최초 1회 로그인 후 재사용)
            if not self.session:
                session_str = client.session.save()
                logger.info(f"텔레그램 세션 저장 완료. .env에 추가하세요:\nTELEGRAM_SESSION={session_str}")

            @client.on(events.NewMessage(chats=BITHUMB_CHANNEL))
            async def handler(event):
                text = event.message.text or ''
                signal = parse_alert(text)
                if signal:
                    logger.info(f"[텔레그램 신호] {signal['coin']} | {signal['type']} | {signal['message']}")
                    self.signal_queue.put(signal)

            logger.info(f"빗썸 채널 감시 중: @{BITHUMB_CHANNEL}")
            await client.run_until_disconnected()
