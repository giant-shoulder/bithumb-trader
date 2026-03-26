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

# ===== ATR 기반 3단계 손절/익절 =====
ATR_PERIOD = 14               # ATR 계산 기간

# Phase 1: 방어 - 하드 손절 (ATR 기반, 클램프)
HARD_STOP_ATR_MULT = 1.5      # 하드 손절 = ATR × 1.5
HARD_STOP_MIN_PCT = 0.8       # 하드 손절 최소값 (%)
HARD_STOP_MAX_PCT = 3.0       # 하드 손절 최대값 (%)

# Phase 2: 본전 확보 (수익 >= 0.5×ATR)
BREAKEVEN_TRIGGER_ATR = 0.5   # 본전 컷 활성화 기준 (ATR 배수)
TRAILING_PHASE2_ATR = 1.0     # Phase 2 트레일링 폭 (ATR 배수)

# Phase 3: 수익 극대화 (수익 >= 1.5×ATR)
PROFIT_TRIGGER_ATR = 1.5      # Phase 3 활성화 기준 (ATR 배수)
TRAILING_PHASE3_ATR = 0.7     # Phase 3 트레일링 폭 (ATR 배수)

# 최소 보유 시간
MIN_HOLD_SECONDS = 180        # 매수 후 최소 보유 시간 (초)

# 매도 후 재매수 금지 시간
BUY_COOLDOWN_SECONDS = 600    # 매도 후 동일 코인 재매수 금지 시간 (초)

# RSI
RSI_PERIOD = 14
RSI_OVERBOUGHT = 72

# 볼린저 밴드
BB_PERIOD = 20
BB_STD = 2.0

# ===== 루프 설정 =====
POLLING_INTERVAL_IDLE = 30    # 포지션 없을 때 실행 주기 (초)
POLLING_INTERVAL_ACTIVE = 10  # 포지션 있을 때 실행 주기 (초)
LOG_FILE = "trades.log"       # 로그 파일명

# ===== 리스크 관리 =====
DAILY_LOSS_LIMIT_PCT = 5.0    # 일일 최대 손실 한도 (원금 대비 %)
HARD_TAKE_PROFIT_PCT = 4.0    # 하드 익절선 (%) - 이 이상 수익 시 무조건 전량 매도

# 지정가 매수 설정
BUY_LIMIT_OFFSET_PCT = 0.1   # 현재가 대비 지정가 매수 호가 여유폭 (%)
