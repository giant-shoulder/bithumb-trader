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
COIN_BLACKLIST = {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD'}  # 스테이블 코인 제외

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
MIN_PRICE_KRW = 500          # 최소 코인 가격 (원) - 저가 코인 필터

# 매수 실행
MAX_POSITION_KRW = 500000    # 코인당 최대 투자금액 (원)
BUY_SPLIT = 5                # 불타기 분할 횟수
BUY_UNIT_KRW = MAX_POSITION_KRW // BUY_SPLIT  # 1회 매수 금액
MAX_CONCURRENT_POSITIONS = 3  # 최대 동시 포지션 수

# ===== 손절/익절 (고정값, 단순) =====
HARD_STOP_PCT = 1.2           # 하드 손절 (%) - 매입가 대비 -1.2% 즉시 손절
TRAILING_ACTIVATE_PCT = 1.0   # 트레일링 스탑 활성화 (%) - +1% 수익 시 활성화
TRAILING_DROP_PCT = 0.5       # 트레일링 하락 폭 (%) - 고점 대비 -0.5% 시 매도
HARD_TAKE_PROFIT_PCT = 4.0    # 하드 익절선 (%) - +4% 이상 시 무조건 매도
MOMENTUM_KILL_RANK = 40       # 모멘텀 소멸 기준 순위

# 최소 보유 시간 (하드손절 제외한 일반 매도에만 적용)
MIN_HOLD_SECONDS = 180        # 매수 후 최소 보유 시간 (초)

# 매도 후 재매수 금지 시간 (손절/익절에 따라 다르게 적용)
COOLDOWN_AFTER_STOP_LOSS = 3600   # 손절 후 쿨다운 (초) - 1시간
COOLDOWN_AFTER_TAKE_PROFIT = 600  # 익절 후 쿨다운 (초) - 10분

# RSI
RSI_PERIOD = 14
RSI_OVERBOUGHT = 72

# 볼린저 밴드
BB_PERIOD = 20
BB_STD = 2.0

# ===== 거래 시간 제한 =====
TRADING_HOUR_START = 9    # 매수 허용 시작 (KST)
TRADING_HOUR_END = 22     # 매수 허용 종료 (KST)

# ===== 캔들 간격 =====
BUY_CANDLE_INTERVAL = "5m"   # 매수 신호용 캔들 간격
BUY_CANDLE_COUNT = 200        # 매수 신호용 캔들 개수

# ===== 루프 설정 =====
POLLING_INTERVAL_IDLE = 30    # 포지션 없을 때 실행 주기 (초)
POLLING_INTERVAL_ACTIVE = 10  # 포지션 있을 때 실행 주기 (초)
LOG_FILE = "trades.log"       # 로그 파일명

# ===== 리스크 관리 =====
DAILY_LOSS_LIMIT_PCT = 5.0    # 일일 최대 손실 한도 (원금 대비 %)

# 지정가 매수 설정
BUY_LIMIT_OFFSET_PCT = 0.1   # 현재가 대비 지정가 매수 호가 여유폭 (%)
