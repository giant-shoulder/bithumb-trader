"""
빗섬 자동매매 설정 파일
실제 API 키는 환경변수로 관리하세요.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===== API 설정 =====
BITHUMB_ACCESS_KEY = os.environ.get("BITHUMB_ACCESS_KEY", "여기에_액세스키_입력")
BITHUMB_SECRET_KEY = os.environ.get("BITHUMB_SECRET_KEY", "여기에_시크릿키_입력")

# ===== 동적 종목 스캔 =====
MIN_VOLUME_24H_KRW = 2_000_000_000  # 최소 24h 거래대금 (20억 KRW)
MOMENTUM_TOP_N = 20                  # 심층 분석 상위 N개

# ===== 전략 파라미터 =====
# 이동평균
MA_SHORT = 5      # 단기
MA_MID1 = 20      # 중기1
MA_MID2 = 60      # 중기2
MA_LONG = 120     # 장기

# 매수 조건
RSI_BUY_MIN = 40             # 매수 RSI 하한 (과매도 제외)
RSI_BUY_MAX = 65             # 매수 RSI 상한 (과열 제외)
BULLISH_CANDLE_MIN = 3.0     # 장대양봉 최소 크기 (시가 대비 %)
PREV_HIGH_PERIOD = 120       # 전고점 기간 (캔들 수)

# 매수 실행
MAX_POSITION_KRW = 500000    # 코인당 최대 투자금액 (원)
BUY_SPLIT = 5                # 불타기 분할 횟수
BUY_UNIT_KRW = MAX_POSITION_KRW // BUY_SPLIT  # 1회 매수 금액

# 손절
STOP_LOSS_PCT = -1.0         # 손절 기준 (%)

# 트레일링 스탑
TRAILING_STOP_TRIGGER = 0.8  # 트레일링 스탑 활성화 기준 (%)
TRAILING_STOP_PCT = 0.4      # 고점 대비 하락 허용폭 (%)

# RSI
RSI_PERIOD = 14
RSI_OVERBOUGHT = 72

# 볼린저 밴드
BB_PERIOD = 20
BB_STD = 2.0

# ===== 루프 설정 =====
POLLING_INTERVAL = 10         # 전략 실행 주기 (초)
LOG_FILE = "trades.log"       # 로그 파일명
